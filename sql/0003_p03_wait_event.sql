-- P03: run_waits / run_events and atomic wait/wake.
-- Replay-safe. No GRANT, extensions, public objects, or transaction control.
-- Applied after 0002 and before 0006. Does not reference plugin_catalog.

CREATE TABLE IF NOT EXISTS cordis.run_events (
    event_scope_id    text NOT NULL,
    event_name        text NOT NULL,
    event_log_run_id  text NOT NULL DEFAULT ('@event/' || pg_catalog.gen_random_uuid()::text),
    payload           jsonb,
    emit_seq          bigint,
    created_at        timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    emitted_at        timestamptz,
    CONSTRAINT run_events_pkey PRIMARY KEY (event_scope_id, event_name),
    CONSTRAINT run_events_event_log_run_id_key UNIQUE (event_log_run_id),
    CONSTRAINT run_events_scope_nonblank_check CHECK (pg_catalog.btrim(event_scope_id) <> ''),
    CONSTRAINT run_events_name_nonblank_check CHECK (pg_catalog.btrim(event_name) <> ''),
    CONSTRAINT run_events_event_log_run_id_check CHECK (
        event_log_run_id ~ '^@event/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    ),
    CONSTRAINT run_events_emit_seq_check CHECK (emit_seq IS NULL OR emit_seq > 0),
    CONSTRAINT run_events_emission_state_check CHECK (
        (
            payload IS NULL
            AND emit_seq IS NULL
            AND emitted_at IS NULL
        )
        OR (
            payload IS NOT NULL
            AND emit_seq IS NOT NULL
            AND emitted_at IS NOT NULL
        )
    )
);

CREATE TABLE IF NOT EXISTS cordis.run_waits (
    run_id          text NOT NULL,
    await_id        uuid NOT NULL,
    event_scope_id  text NOT NULL,
    event_name      text NOT NULL,
    await_seq       bigint NOT NULL,
    deadline        timestamptz,
    ui_metadata     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT run_waits_pkey PRIMARY KEY (run_id),
    CONSTRAINT run_waits_await_id_key UNIQUE (await_id),
    CONSTRAINT run_waits_job_fkey
        FOREIGN KEY (run_id) REFERENCES cordis.jobs (run_id) ON DELETE RESTRICT,
    CONSTRAINT run_waits_event_fkey
        FOREIGN KEY (event_scope_id, event_name)
        REFERENCES cordis.run_events (event_scope_id, event_name),
    CONSTRAINT run_waits_await_step_fkey
        FOREIGN KEY (run_id, await_seq) REFERENCES cordis.agent_steps (run_id, seq),
    CONSTRAINT run_waits_scope_nonblank_check CHECK (pg_catalog.btrim(event_scope_id) <> ''),
    CONSTRAINT run_waits_name_nonblank_check CHECK (pg_catalog.btrim(event_name) <> ''),
    CONSTRAINT run_waits_await_seq_check CHECK (await_seq > 0),
    CONSTRAINT run_waits_ui_metadata_object_check CHECK (
        pg_catalog.jsonb_typeof(ui_metadata) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS run_waits_event_idx
    ON cordis.run_waits (event_scope_id, event_name, run_id);

CREATE OR REPLACE FUNCTION cordis.await_event(
    p_claim_token    uuid,
    p_run_id         text,
    p_event_scope_id text,
    p_event_name     text,
    p_await_id       uuid,
    p_deadline       timestamptz DEFAULT NULL,
    p_ui_metadata    jsonb DEFAULT '{}'::jsonb,
    p_extend_seconds integer DEFAULT 90
)
RETURNS TABLE (
    accepted       boolean,
    should_suspend boolean,
    payload        jsonb,
    source_run_id  text,
    source_seq     bigint
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
DECLARE
    n integer;
    captured timestamptz;
    ev_payload jsonb;
    ev_emit_seq bigint;
    ev_emitted_at timestamptz;
    ev_log_run_id text;
    src_kind text;
    src_scope text;
    src_name text;
    src_payload jsonb;
    await_seq bigint;
    existing_wait uuid;
    v_job_id bigint;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_event_scope_id IS NULL OR pg_catalog.btrim(p_event_scope_id) = '' THEN
        RAISE EXCEPTION 'p_event_scope_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_event_name IS NULL OR pg_catalog.btrim(p_event_name) = '' THEN
        RAISE EXCEPTION 'p_event_name must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_await_id IS NULL THEN
        RAISE EXCEPTION 'p_await_id must not be null'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_ui_metadata IS NULL OR pg_catalog.jsonb_typeof(p_ui_metadata) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'p_ui_metadata must be a JSON object'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_extend_seconds IS NULL OR p_extend_seconds <= 0 THEN
        RAISE EXCEPTION 'p_extend_seconds must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    IF p_claim_token IS NULL THEN
        RETURN QUERY SELECT false, false, NULL::jsonb, NULL::text, NULL::bigint;
        RETURN;
    END IF;

    BEGIN
    INSERT INTO cordis.run_events (event_scope_id, event_name)
    VALUES (p_event_scope_id, p_event_name)
    ON CONFLICT DO NOTHING;

    SELECT e.payload, e.emit_seq, e.emitted_at, e.event_log_run_id
      INTO ev_payload, ev_emit_seq, ev_emitted_at, ev_log_run_id
      FROM cordis.run_events AS e
     WHERE e.event_scope_id = p_event_scope_id
       AND e.event_name = p_event_name
     FOR SHARE;

    captured := pg_catalog.clock_timestamp();
    SELECT j.job_id
      INTO v_job_id
      FROM cordis.jobs AS j
     WHERE j.claim_token = p_claim_token
       AND j.run_id = p_run_id
       AND j.status = 'RUNNING'
       AND j.claim_expires_at > captured
     FOR UPDATE SKIP LOCKED;
    IF NOT FOUND THEN
        n := 0;
    ELSE
        UPDATE cordis.jobs
           SET claim_expires_at = GREATEST(
                   claim_expires_at,
                   captured + pg_catalog.make_interval(secs => p_extend_seconds)
               )
         WHERE cordis.jobs.job_id = v_job_id
           AND claim_token = p_claim_token
           AND run_id = p_run_id
           AND status = 'RUNNING'
           AND claim_expires_at > captured;
        GET DIAGNOSTICS n = ROW_COUNT;
    END IF;
    IF n = 0 THEN
        RAISE EXCEPTION 'await_event claim not lockable'
            USING ERRCODE = 'P0301';
    END IF;

    SELECT w.await_id
      INTO existing_wait
      FROM cordis.run_waits AS w
     WHERE w.run_id = p_run_id
     FOR UPDATE;

    IF existing_wait IS NOT NULL THEN
        RAISE EXCEPTION 'run already has an active wait'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM cordis.agent_steps AS s
         WHERE s.run_id = p_run_id
           AND s.kind = 'run/await'
           AND s.payload->>'await_id' = p_await_id::text
    ) THEN
        RAISE EXCEPTION 'await_id already used on this run'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    IF ev_payload IS NULL THEN
        await_seq := cordis.emit_step(
            p_run_id,
            'run/await',
            pg_catalog.jsonb_build_object(
                'await_id', p_await_id,
                'event_scope_id', p_event_scope_id,
                'event_name', p_event_name,
                'deadline', pg_catalog.to_jsonb(p_deadline),
                'ui_metadata', p_ui_metadata
            ),
            NULL
        );

        INSERT INTO cordis.run_waits (
            run_id,
            await_id,
            event_scope_id,
            event_name,
            await_seq,
            deadline,
            ui_metadata
        )
        VALUES (
            p_run_id,
            p_await_id,
            p_event_scope_id,
            p_event_name,
            await_seq,
            p_deadline,
            p_ui_metadata
        );

        UPDATE cordis.jobs
           SET status = 'WAITING',
               claim_token = NULL,
               claimed_by = NULL,
               claim_expires_at = NULL,
               completed_at = NULL,
               result = NULL,
               error = NULL
         WHERE run_id = p_run_id
           AND claim_token = p_claim_token
           AND status = 'RUNNING';
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN
            RAISE EXCEPTION 'failed to transition job to WAITING'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        RETURN QUERY SELECT true, true, NULL::jsonb, NULL::text, NULL::bigint;
        RETURN;
    END IF;

    IF ev_emit_seq IS NULL OR ev_emitted_at IS NULL THEN
        RAISE EXCEPTION 'emitted event is missing source pointer'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT s.kind,
           s.payload->>'event_scope_id',
           s.payload->>'event_name',
           s.payload -> 'payload'
      INTO src_kind, src_scope, src_name, src_payload
      FROM cordis.agent_steps AS s
     WHERE s.run_id = ev_log_run_id
       AND s.seq = ev_emit_seq;

    IF NOT FOUND
       OR src_kind IS DISTINCT FROM 'event/emit'
       OR src_scope IS DISTINCT FROM p_event_scope_id
       OR src_name IS DISTINCT FROM p_event_name
       OR src_payload IS NULL THEN
        RAISE EXCEPTION 'canonical event/emit row is missing or mismatched'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    await_seq := cordis.emit_step(
        p_run_id,
        'run/await',
        pg_catalog.jsonb_build_object(
            'await_id', p_await_id,
            'event_scope_id', p_event_scope_id,
            'event_name', p_event_name,
            'deadline', pg_catalog.to_jsonb(p_deadline),
            'ui_metadata', p_ui_metadata
        ),
        NULL
    );

    PERFORM cordis.emit_step(
        p_run_id,
        'run/wake',
        pg_catalog.jsonb_build_object(
            'await_id', p_await_id,
            'event_scope_id', p_event_scope_id,
            'event_name', p_event_name,
            'source_run_id', ev_log_run_id,
            'source_seq', ev_emit_seq
        ),
        NULL
    );

    RETURN QUERY SELECT true, false, src_payload, ev_log_run_id, ev_emit_seq;
    RETURN;
    EXCEPTION
        WHEN SQLSTATE 'P0301' THEN
            RETURN QUERY SELECT false, false, NULL::jsonb, NULL::text, NULL::bigint;
            RETURN;
    END;
END;
$fn$;

CREATE OR REPLACE FUNCTION cordis.emit_event(
    p_event_scope_id text,
    p_event_name     text,
    p_payload        jsonb
)
RETURNS TABLE (
    emitted       boolean,
    woken_count   integer,
    source_run_id text,
    source_seq    bigint
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
DECLARE
    n integer;
    captured timestamptz;
    ev_payload jsonb;
    ev_emit_seq bigint;
    ev_log_run_id text;
    v_emit_seq bigint;
    v_woken integer := 0;
    waiter record;
    job_status text;
    job_token uuid;
    job_claimed_by text;
    job_expires timestamptz;
    wait_await uuid;
    wait_scope text;
    wait_name text;
BEGIN
    IF p_event_scope_id IS NULL OR pg_catalog.btrim(p_event_scope_id) = '' THEN
        RAISE EXCEPTION 'p_event_scope_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_event_name IS NULL OR pg_catalog.btrim(p_event_name) = '' THEN
        RAISE EXCEPTION 'p_event_name must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_payload IS NULL THEN
        RAISE EXCEPTION 'p_payload must not be null'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    INSERT INTO cordis.run_events (event_scope_id, event_name)
    VALUES (p_event_scope_id, p_event_name)
    ON CONFLICT DO NOTHING;

    SELECT e.payload, e.emit_seq, e.event_log_run_id
      INTO ev_payload, ev_emit_seq, ev_log_run_id
      FROM cordis.run_events AS e
     WHERE e.event_scope_id = p_event_scope_id
       AND e.event_name = p_event_name
     FOR UPDATE;

    IF ev_payload IS NOT NULL THEN
        RETURN QUERY SELECT false, 0, ev_log_run_id, ev_emit_seq;
        RETURN;
    END IF;

    captured := pg_catalog.clock_timestamp();
    v_emit_seq := cordis.emit_step(
        ev_log_run_id,
        'event/emit',
        pg_catalog.jsonb_build_object(
            'event_scope_id', p_event_scope_id,
            'event_name', p_event_name,
            'payload', p_payload
        ),
        NULL
    );

    UPDATE cordis.run_events
       SET payload = p_payload,
           emit_seq = v_emit_seq,
           emitted_at = captured
     WHERE event_scope_id = p_event_scope_id
       AND event_name = p_event_name
       AND payload IS NULL;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN
        RAISE EXCEPTION 'event first-write fence lost the race'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    FOR waiter IN
        SELECT w.run_id, w.await_id, w.event_scope_id, w.event_name
          FROM cordis.run_waits AS w
         WHERE w.event_scope_id = p_event_scope_id
           AND w.event_name = p_event_name
         ORDER BY w.run_id
    LOOP
        SELECT j.status, j.claim_token, j.claimed_by, j.claim_expires_at
          INTO job_status, job_token, job_claimed_by, job_expires
          FROM cordis.jobs AS j
         WHERE j.run_id = waiter.run_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'matching wait has no jobs row'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        SELECT w.await_id, w.event_scope_id, w.event_name
          INTO wait_await, wait_scope, wait_name
          FROM cordis.run_waits AS w
         WHERE w.run_id = waiter.run_id
         FOR UPDATE;
        IF NOT FOUND
           OR wait_await IS DISTINCT FROM waiter.await_id
           OR wait_scope IS DISTINCT FROM p_event_scope_id
           OR wait_name IS DISTINCT FROM p_event_name
           OR job_status IS DISTINCT FROM 'WAITING'
           OR job_token IS NOT NULL
           OR job_claimed_by IS NOT NULL
           OR job_expires IS NOT NULL THEN
            RAISE EXCEPTION 'matching wait is inconsistent with jobs state'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        PERFORM cordis.emit_step(
            waiter.run_id,
            'run/wake',
            pg_catalog.jsonb_build_object(
                'await_id', waiter.await_id,
                'event_scope_id', p_event_scope_id,
                'event_name', p_event_name,
                'source_run_id', ev_log_run_id,
                'source_seq', v_emit_seq
            ),
            NULL
        );

        UPDATE cordis.jobs
           SET status = 'PENDING',
               available_at = captured,
               completed_at = NULL,
               result = NULL,
               error = NULL
         WHERE run_id = waiter.run_id
           AND status = 'WAITING';
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN
            RAISE EXCEPTION 'failed to wake waiting job'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        DELETE FROM cordis.run_waits
         WHERE run_id = waiter.run_id
           AND await_id = waiter.await_id;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN
            RAISE EXCEPTION 'failed to delete resolved wait'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        v_woken := v_woken + 1;
    END LOOP;

    RETURN QUERY SELECT true, v_woken, ev_log_run_id, v_emit_seq;
    RETURN;
END;
$fn$;

CREATE OR REPLACE FUNCTION cordis.run_state(
    p_run_id text
)
RETURNS TABLE (
    status     text,
    steps_used integer,
    answer     text,
    error      text
)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
DECLARE
    latest_await_seq bigint;
    latest_await_id text;
    has_matching_wake boolean := false;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT a.seq, a.payload->>'await_id'
      INTO latest_await_seq, latest_await_id
      FROM cordis.agent_steps AS a
     WHERE a.run_id = p_run_id
       AND a.kind = 'run/await'
     ORDER BY a.seq DESC
     LIMIT 1;

    IF latest_await_seq IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1
              FROM cordis.agent_steps AS w
             WHERE w.run_id = p_run_id
               AND w.kind = 'run/wake'
               AND w.seq > latest_await_seq
               AND w.payload->>'await_id' = latest_await_id
        ) INTO has_matching_wake;
    END IF;

    RETURN QUERY
    SELECT
        CASE
            WHEN coalesce(bool_or(s.kind = 'final'), false) THEN 'final'
            WHEN coalesce(bool_or(s.kind = 'error'), false) THEN 'error'
            WHEN latest_await_seq IS NOT NULL AND NOT has_matching_wake THEN 'awaiting'
            ELSE 'in-progress'
        END,
        count(*) FILTER (WHERE s.kind = 'llm')::integer,
        (
            SELECT f.payload->>'answer'
              FROM cordis.agent_steps AS f
             WHERE f.run_id = p_run_id
               AND f.kind = 'final'
             ORDER BY f.seq DESC
             LIMIT 1
        ),
        (
            SELECT coalesce(e.payload->>'message', e.payload::text)
              FROM cordis.agent_steps AS e
             WHERE e.run_id = p_run_id
               AND e.kind = 'error'
             ORDER BY e.seq DESC
             LIMIT 1
        )
      FROM cordis.agent_steps AS s
     WHERE s.run_id = p_run_id;
END;
$fn$;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p03'::text;
$$;
