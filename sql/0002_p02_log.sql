-- P02: append-only agent_steps log and checkpoint⊂log.
-- Replay-safe. No GRANT, extensions, public objects, or transaction control.
-- Does not require cordis.jobs at create time; claim-aware helpers detect it at runtime.

CREATE TABLE IF NOT EXISTS cordis.agent_steps (
    run_id     text NOT NULL,
    seq        bigserial NOT NULL,
    kind       text NOT NULL,
    payload    jsonb NOT NULL,
    step_name  text,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT agent_steps_pkey PRIMARY KEY (run_id, seq),
    CONSTRAINT agent_steps_run_id_check CHECK (pg_catalog.btrim(run_id) <> ''),
    CONSTRAINT agent_steps_kind_check CHECK (kind IN (
        'llm',
        'tool',
        'final',
        'error',
        'run/claim_timeout',
        'run/await',
        'run/sleep',
        'run/wake',
        'run/yield',
        'spawn/start',
        'spawn/end',
        'event/emit'
    )),
    CONSTRAINT agent_steps_step_name_format_check CHECK (
        step_name IS NULL OR step_name ~ '^s-[1-9][0-9]*$'
    ),
    CONSTRAINT agent_steps_step_name_presence_check CHECK (
        kind NOT IN ('llm', 'tool') OR step_name IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_steps_llm_step_idx
    ON cordis.agent_steps (run_id, step_name)
    WHERE kind = 'llm';

CREATE OR REPLACE FUNCTION cordis.emit_step(
    p_run_id    text,
    p_kind      text,
    p_payload   jsonb,
    p_step_name text DEFAULT NULL
)
RETURNS bigint
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
DECLARE
    v_seq bigint;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_payload IS NULL THEN
        RAISE EXCEPTION 'p_payload must not be null'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    INSERT INTO cordis.agent_steps (run_id, kind, payload, step_name)
    VALUES (p_run_id, p_kind, p_payload, p_step_name)
    RETURNING seq INTO v_seq;

    RETURN v_seq;
END;
$fn$;

CREATE OR REPLACE FUNCTION cordis.emit_step_claimed(
    p_claim_token    uuid,
    p_run_id         text,
    p_kind           text,
    p_payload        jsonb,
    p_step_name      text DEFAULT NULL,
    p_extend_seconds integer DEFAULT 90
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
DECLARE
    captured timestamptz;
    n integer;
BEGIN
    IF p_extend_seconds IS NULL OR p_extend_seconds <= 0 THEN
        RAISE EXCEPTION 'p_extend_seconds must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_payload IS NULL THEN
        RAISE EXCEPTION 'p_payload must not be null'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_kind IS NULL OR p_kind NOT IN (
        'llm', 'tool', 'final', 'error',
        'run/claim_timeout', 'run/await', 'run/sleep', 'run/wake', 'run/yield',
        'spawn/start', 'spawn/end', 'event/emit'
    ) THEN
        RAISE EXCEPTION 'p_kind is not an allowed event kind'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_kind IN ('llm', 'tool') AND p_step_name IS NULL THEN
        RAISE EXCEPTION 'llm and tool events require step_name'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_step_name IS NOT NULL AND p_step_name !~ '^s-[1-9][0-9]*$' THEN
        RAISE EXCEPTION 'p_step_name must match s-N'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_claim_token IS NULL THEN
        RETURN false;
    END IF;

    IF pg_catalog.to_regclass('cordis.jobs') IS NULL THEN
        PERFORM cordis.emit_step(p_run_id, p_kind, p_payload, p_step_name);
        RETURN true;
    END IF;

    captured := pg_catalog.clock_timestamp();
    UPDATE cordis.jobs
       SET claim_expires_at = GREATEST(
               claim_expires_at,
               captured + pg_catalog.make_interval(secs => p_extend_seconds)
           )
     WHERE claim_token = p_claim_token
       AND run_id = p_run_id
       AND status = 'RUNNING'
       AND claim_expires_at > captured;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n = 0 THEN
        RETURN false;
    END IF;

    PERFORM cordis.emit_step(p_run_id, p_kind, p_payload, p_step_name);
    RETURN true;
END;
$fn$;

CREATE OR REPLACE FUNCTION cordis.checkpoint(
    p_claim_token    uuid,
    p_events         jsonb,
    p_extend_seconds integer DEFAULT 90
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
DECLARE
    captured timestamptz;
    n integer;
    claimed_run text;
    common_run text;
    elem jsonb;
    elem_run text;
    v_kind text;
    v_step text;
    rec record;
BEGIN
    IF p_extend_seconds IS NULL OR p_extend_seconds <= 0 THEN
        RAISE EXCEPTION 'p_extend_seconds must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_events IS NULL OR jsonb_typeof(p_events) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'p_events must be a JSONB array'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    IF jsonb_array_length(p_events) > 0 THEN
        FOR rec IN
            SELECT value, ordinality
              FROM jsonb_array_elements(p_events) WITH ORDINALITY
             ORDER BY ordinality
        LOOP
            elem := rec.value;
            IF jsonb_typeof(elem) IS DISTINCT FROM 'object' THEN
                RAISE EXCEPTION 'checkpoint event must be a JSONB object'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF NOT (elem ? 'run_id' AND elem ? 'kind' AND elem ? 'payload') THEN
                RAISE EXCEPTION 'checkpoint event requires run_id, kind, and payload'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF jsonb_typeof(elem->'run_id') IS DISTINCT FROM 'string'
               OR jsonb_typeof(elem->'kind') IS DISTINCT FROM 'string' THEN
                RAISE EXCEPTION 'checkpoint event run_id and kind must be JSON strings'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF elem ? 'step_name'
               AND jsonb_typeof(elem->'step_name') NOT IN ('string', 'null') THEN
                RAISE EXCEPTION 'checkpoint event step_name must be a JSON string or null'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            elem_run := elem->>'run_id';
            v_kind := elem->>'kind';
            v_step := elem->>'step_name';
            IF elem_run IS NULL OR pg_catalog.btrim(elem_run) = '' THEN
                RAISE EXCEPTION 'checkpoint event run_id must not be blank'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF v_kind IS NULL OR v_kind NOT IN (
                'llm', 'tool', 'final', 'error',
                'run/claim_timeout', 'run/await', 'run/sleep', 'run/wake', 'run/yield',
                'spawn/start', 'spawn/end', 'event/emit'
            ) THEN
                RAISE EXCEPTION 'checkpoint event kind is not allowed'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF v_kind IN ('llm', 'tool') AND v_step IS NULL THEN
                RAISE EXCEPTION 'llm and tool events require step_name'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF v_step IS NOT NULL AND v_step !~ '^s-[1-9][0-9]*$' THEN
                RAISE EXCEPTION 'checkpoint event step_name must match s-N'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF common_run IS NULL THEN
                common_run := elem_run;
            ELSIF elem_run IS DISTINCT FROM common_run THEN
                RAISE EXCEPTION 'checkpoint events must share one run_id'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
        END LOOP;
    END IF;

    IF p_claim_token IS NULL THEN
        RETURN false;
    END IF;

    IF pg_catalog.to_regclass('cordis.jobs') IS NOT NULL THEN
        captured := pg_catalog.clock_timestamp();
        UPDATE cordis.jobs
           SET claim_expires_at = GREATEST(
                   claim_expires_at,
                   captured + pg_catalog.make_interval(secs => p_extend_seconds)
               )
         WHERE claim_token = p_claim_token
           AND status = 'RUNNING'
           AND claim_expires_at > captured
         RETURNING run_id INTO claimed_run;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n = 0 THEN
            RETURN false;
        END IF;
        IF common_run IS NOT NULL AND common_run IS DISTINCT FROM claimed_run THEN
            RAISE EXCEPTION 'checkpoint event run_id must match the claimed job'
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
    END IF;

    IF jsonb_array_length(p_events) = 0 THEN
        RETURN true;
    END IF;

    FOR rec IN
        SELECT value, ordinality
          FROM jsonb_array_elements(p_events) WITH ORDINALITY
         ORDER BY ordinality
    LOOP
        elem := rec.value;
        v_kind := elem->>'kind';
        v_step := elem->>'step_name';
        PERFORM cordis.emit_step(elem->>'run_id', v_kind, elem->'payload', v_step);
    END LOOP;

    RETURN true;
END;
$fn$;

CREATE OR REPLACE FUNCTION cordis.next_step_name(
    p_run_id text
)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
DECLARE
    latest_seq bigint;
    latest_name text;
    completed boolean;
    max_n numeric;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT seq, step_name
      INTO latest_seq, latest_name
      FROM cordis.agent_steps
     WHERE run_id = p_run_id
       AND kind = 'llm'
     ORDER BY seq DESC
     LIMIT 1;

    IF latest_seq IS NULL THEN
        RETURN 's-1';
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM cordis.agent_steps
         WHERE run_id = p_run_id
           AND step_name IS NOT DISTINCT FROM latest_name
           AND seq > latest_seq
           AND kind IN ('tool', 'final')
    ) INTO completed;

    IF NOT completed THEN
        RETURN latest_name;
    END IF;

    SELECT coalesce(max(substring(step_name from 3)::numeric), 0)
      INTO max_n
      FROM cordis.agent_steps
     WHERE run_id = p_run_id
       AND kind = 'llm'
       AND step_name ~ '^s-[1-9][0-9]*$';

    RETURN 's-' || (max_n + 1)::text;
END;
$fn$;

CREATE OR REPLACE FUNCTION cordis.llm_checkpoint(
    p_run_id    text,
    p_step_name text
)
RETURNS SETOF cordis.agent_steps
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $fn$
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_step_name IS NULL OR p_step_name !~ '^s-[1-9][0-9]*$' THEN
        RAISE EXCEPTION 'p_step_name must match s-N'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    RETURN QUERY
    SELECT s.*
      FROM cordis.agent_steps AS s
     WHERE s.run_id = p_run_id
       AND s.kind = 'llm'
       AND s.step_name = p_step_name
     ORDER BY s.seq
     LIMIT 1;
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
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    RETURN QUERY
    SELECT
        CASE
            WHEN coalesce(bool_or(s.kind = 'final'), false) THEN 'final'
            WHEN coalesce(bool_or(s.kind = 'error'), false) THEN 'error'
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
  SELECT 'p02'::text;
$$;
