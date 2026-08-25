-- P04: sleep, wait-deadline timeout, and task-level retry on cordis.jobs.
-- Replay-safe. No GRANT, extensions, public objects, or transaction control.
-- Applied after 0003 and before 0005. Does not reference plugin_catalog.

ALTER TABLE cordis.jobs
    ADD COLUMN IF NOT EXISTS max_attempts integer DEFAULT 3;

ALTER TABLE cordis.jobs
    ADD COLUMN IF NOT EXISTS retry_backoff_base_seconds double precision NOT NULL DEFAULT 30;

ALTER TABLE cordis.jobs
    ADD COLUMN IF NOT EXISTS retry_backoff_factor double precision NOT NULL DEFAULT 2;

ALTER TABLE cordis.jobs
    ADD COLUMN IF NOT EXISTS retry_backoff_max_seconds double precision NOT NULL DEFAULT 86400;

DO $p04$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
         WHERE conrelid = 'cordis.jobs'::pg_catalog.regclass
           AND conname = 'jobs_max_attempts_check'
    ) THEN
        ALTER TABLE cordis.jobs
            ADD CONSTRAINT jobs_max_attempts_check
            CHECK (max_attempts IS NULL OR max_attempts >= 1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
         WHERE conrelid = 'cordis.jobs'::pg_catalog.regclass
           AND conname = 'jobs_retry_backoff_base_check'
    ) THEN
        ALTER TABLE cordis.jobs
            ADD CONSTRAINT jobs_retry_backoff_base_check
            CHECK (
                retry_backoff_base_seconds > '-Infinity'::double precision
                AND retry_backoff_base_seconds < 'Infinity'::double precision
                AND retry_backoff_base_seconds >= 0
                AND retry_backoff_base_seconds <= 86400
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
         WHERE conrelid = 'cordis.jobs'::pg_catalog.regclass
           AND conname = 'jobs_retry_backoff_factor_check'
    ) THEN
        ALTER TABLE cordis.jobs
            ADD CONSTRAINT jobs_retry_backoff_factor_check
            CHECK (
                retry_backoff_factor > '-Infinity'::double precision
                AND retry_backoff_factor < 'Infinity'::double precision
                AND retry_backoff_factor >= 1
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
         WHERE conrelid = 'cordis.jobs'::pg_catalog.regclass
           AND conname = 'jobs_retry_backoff_max_check'
    ) THEN
        ALTER TABLE cordis.jobs
            ADD CONSTRAINT jobs_retry_backoff_max_check
            CHECK (
                retry_backoff_max_seconds > '-Infinity'::double precision
                AND retry_backoff_max_seconds < 'Infinity'::double precision
                AND retry_backoff_max_seconds >= 0
                AND retry_backoff_max_seconds <= 86400
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
         WHERE conrelid = 'cordis.jobs'::pg_catalog.regclass
           AND conname = 'jobs_retry_backoff_bounds_check'
    ) THEN
        ALTER TABLE cordis.jobs
            ADD CONSTRAINT jobs_retry_backoff_bounds_check
            CHECK (retry_backoff_base_seconds <= retry_backoff_max_seconds);
    END IF;
END;
$p04$;

DROP INDEX IF EXISTS cordis.jobs_ready_idx;

CREATE INDEX jobs_ready_idx
    ON cordis.jobs (priority DESC, available_at ASC, job_id ASC)
    WHERE status IN ('PENDING', 'SLEEPING');

DO $p04$
BEGIN
    IF pg_catalog.to_regclass('cordis.run_waits_deadline_idx') IS NULL THEN
        CREATE INDEX run_waits_deadline_idx
            ON cordis.run_waits (
                deadline ASC, event_scope_id, event_name, run_id
            )
            WHERE deadline IS NOT NULL;
    END IF;
END;
$p04$;

DO $p04$
DECLARE
    v_n integer;
BEGIN
    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_attribute AS a
      JOIN pg_catalog.pg_attrdef AS d
        ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE a.attrelid = 'cordis.jobs'::pg_catalog.regclass
       AND a.attname = 'max_attempts'
       AND NOT a.attisdropped
       AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'integer'
       AND NOT a.attnotnull
       AND a.attgenerated = ''
       AND a.attidentity = ''
       AND pg_catalog.pg_get_expr(d.adbin, d.adrelid) = '3';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible cordis.jobs.max_attempts'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_attribute AS a
      JOIN pg_catalog.pg_attrdef AS d
        ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE a.attrelid = 'cordis.jobs'::pg_catalog.regclass
       AND a.attname = 'retry_backoff_base_seconds'
       AND NOT a.attisdropped
       AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'double precision'
       AND a.attnotnull
       AND a.attgenerated = ''
       AND a.attidentity = ''
       AND pg_catalog.pg_get_expr(d.adbin, d.adrelid) = '30';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible cordis.jobs.retry_backoff_base_seconds'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_attribute AS a
      JOIN pg_catalog.pg_attrdef AS d
        ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE a.attrelid = 'cordis.jobs'::pg_catalog.regclass
       AND a.attname = 'retry_backoff_factor'
       AND NOT a.attisdropped
       AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'double precision'
       AND a.attnotnull
       AND a.attgenerated = ''
       AND a.attidentity = ''
       AND pg_catalog.pg_get_expr(d.adbin, d.adrelid) = '2';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible cordis.jobs.retry_backoff_factor'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_attribute AS a
      JOIN pg_catalog.pg_attrdef AS d
        ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE a.attrelid = 'cordis.jobs'::pg_catalog.regclass
       AND a.attname = 'retry_backoff_max_seconds'
       AND NOT a.attisdropped
       AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'double precision'
       AND a.attnotnull
       AND a.attgenerated = ''
       AND a.attidentity = ''
       AND pg_catalog.pg_get_expr(d.adbin, d.adrelid) = '86400';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible cordis.jobs.retry_backoff_max_seconds'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_constraint AS x
     WHERE x.conrelid = 'cordis.jobs'::pg_catalog.regclass
       AND x.conname = 'jobs_max_attempts_check'
       AND x.contype = 'c'
       AND x.convalidated
       AND pg_catalog.pg_get_expr(x.conbin, x.conrelid)
           = '((max_attempts IS NULL) OR (max_attempts >= 1))';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible jobs_max_attempts_check'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_constraint AS x
     WHERE x.conrelid = 'cordis.jobs'::pg_catalog.regclass
       AND x.conname = 'jobs_retry_backoff_base_check'
       AND x.contype = 'c'
       AND x.convalidated
       AND pg_catalog.pg_get_expr(x.conbin, x.conrelid)
           = '((retry_backoff_base_seconds > ''-Infinity''::double precision) AND (retry_backoff_base_seconds < ''Infinity''::double precision) AND (retry_backoff_base_seconds >= (0)::double precision) AND (retry_backoff_base_seconds <= (86400)::double precision))';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible jobs_retry_backoff_base_check'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_constraint AS x
     WHERE x.conrelid = 'cordis.jobs'::pg_catalog.regclass
       AND x.conname = 'jobs_retry_backoff_factor_check'
       AND x.contype = 'c'
       AND x.convalidated
       AND pg_catalog.pg_get_expr(x.conbin, x.conrelid)
           = '((retry_backoff_factor > ''-Infinity''::double precision) AND (retry_backoff_factor < ''Infinity''::double precision) AND (retry_backoff_factor >= (1)::double precision))';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible jobs_retry_backoff_factor_check'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_constraint AS x
     WHERE x.conrelid = 'cordis.jobs'::pg_catalog.regclass
       AND x.conname = 'jobs_retry_backoff_max_check'
       AND x.contype = 'c'
       AND x.convalidated
       AND pg_catalog.pg_get_expr(x.conbin, x.conrelid)
           = '((retry_backoff_max_seconds > ''-Infinity''::double precision) AND (retry_backoff_max_seconds < ''Infinity''::double precision) AND (retry_backoff_max_seconds >= (0)::double precision) AND (retry_backoff_max_seconds <= (86400)::double precision))';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible jobs_retry_backoff_max_check'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_constraint AS x
     WHERE x.conrelid = 'cordis.jobs'::pg_catalog.regclass
       AND x.conname = 'jobs_retry_backoff_bounds_check'
       AND x.contype = 'c'
       AND x.convalidated
       AND pg_catalog.pg_get_expr(x.conbin, x.conrelid)
           = '(retry_backoff_base_seconds <= retry_backoff_max_seconds)';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible jobs_retry_backoff_bounds_check'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    SELECT pg_catalog.count(*)::integer INTO v_n
      FROM pg_catalog.pg_class AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
      JOIN pg_catalog.pg_index AS i ON i.indexrelid = c.oid
      JOIN pg_catalog.pg_am AS am ON am.oid = c.relam
     WHERE n.nspname = 'cordis'
       AND c.relname = 'run_waits_deadline_idx'
       AND c.relkind = 'i'
       AND am.amname = 'btree'
       AND i.indrelid = 'cordis.run_waits'::pg_catalog.regclass
       AND i.indisvalid AND i.indisready AND i.indislive
       AND NOT i.indisunique AND NOT i.indisprimary
       AND i.indexprs IS NULL
       AND i.indnkeyatts = 4 AND i.indnatts = 4
       AND pg_catalog.pg_get_indexdef(c.oid)
           = 'CREATE INDEX run_waits_deadline_idx ON cordis.run_waits USING btree (deadline, event_scope_id, event_name, run_id) WHERE (deadline IS NOT NULL)'
       AND pg_catalog.pg_get_expr(i.indpred, i.indrelid)
           = '(deadline IS NOT NULL)';
    IF v_n <> 1 THEN
        RAISE EXCEPTION 'incompatible run_waits_deadline_idx'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
END;
$p04$;

CREATE OR REPLACE FUNCTION cordis.retry_delay_seconds(
    p_attempt      integer,
    p_base_seconds double precision DEFAULT 30,
    p_factor       double precision DEFAULT 2,
    p_max_seconds  double precision DEFAULT 86400
)
RETURNS double precision
LANGUAGE plpgsql
IMMUTABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p04$
DECLARE
    v_exponent integer;
    v_log_delay double precision;
BEGIN
    IF p_attempt IS NULL OR p_attempt < 1 THEN
        RAISE EXCEPTION 'p_attempt must be at least 1'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_base_seconds IS NULL
       OR NOT (
           p_base_seconds > '-Infinity'::double precision
           AND p_base_seconds < 'Infinity'::double precision
       )
       OR p_base_seconds < 0
       OR p_base_seconds > 86400 THEN
        RAISE EXCEPTION 'p_base_seconds must be finite and in [0, 86400]'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_factor IS NULL
       OR NOT (
           p_factor > '-Infinity'::double precision
           AND p_factor < 'Infinity'::double precision
       )
       OR p_factor < 1 THEN
        RAISE EXCEPTION 'p_factor must be finite and at least 1'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_max_seconds IS NULL
       OR NOT (
           p_max_seconds > '-Infinity'::double precision
           AND p_max_seconds < 'Infinity'::double precision
       )
       OR p_max_seconds < 0
       OR p_max_seconds > 86400 THEN
        RAISE EXCEPTION 'p_max_seconds must be finite and in [0, 86400]'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_base_seconds > p_max_seconds THEN
        RAISE EXCEPTION 'p_base_seconds must not exceed p_max_seconds'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    IF p_base_seconds = 0 OR p_max_seconds = 0 THEN
        RETURN 0;
    END IF;
    IF p_factor = 1 OR p_attempt = 1 THEN
        RETURN LEAST(p_max_seconds, p_base_seconds);
    END IF;
    IF p_base_seconds >= p_max_seconds THEN
        RETURN p_max_seconds;
    END IF;

    v_exponent := p_attempt - 1;
    v_log_delay := ln(p_base_seconds)
        + (v_exponent::double precision * ln(p_factor));
    IF v_log_delay >= ln(p_max_seconds) THEN
        RETURN p_max_seconds;
    END IF;
    -- power() overflows near 1e308 even when base * factor^n is tiny.
    IF (v_exponent::double precision * ln(p_factor)) >= 700 THEN
        RETURN exp(v_log_delay);
    END IF;
    RETURN LEAST(p_max_seconds, p_base_seconds * power(p_factor, v_exponent));
END;
$p04$;

CREATE OR REPLACE FUNCTION cordis.sleep_claim(
    p_claim_token    uuid,
    p_run_id         text,
    p_until          timestamptz,
    p_extend_seconds integer DEFAULT 90
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p04$
DECLARE
    n integer;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_until IS NULL
       OR p_until = '-infinity'::timestamptz
       OR p_until = 'infinity'::timestamptz THEN
        RAISE EXCEPTION 'p_until must be a finite timestamp'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_extend_seconds IS NULL OR p_extend_seconds <= 0 THEN
        RAISE EXCEPTION 'p_extend_seconds must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    IF NOT cordis.emit_step_claimed(
        p_claim_token,
        p_run_id,
        'run/sleep',
        pg_catalog.jsonb_build_object(
            'reason', 'sleep',
            'until', pg_catalog.to_jsonb(p_until)
        ),
        NULL,
        p_extend_seconds
    ) THEN
        RETURN false;
    END IF;

    UPDATE cordis.jobs
       SET status = 'SLEEPING',
           available_at = p_until,
           claim_token = NULL,
           claimed_by = NULL,
           claim_expires_at = NULL,
           completed_at = NULL,
           result = NULL,
           error = NULL
     WHERE claim_token = p_claim_token
       AND run_id = p_run_id
       AND status = 'RUNNING';
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN
        RAISE EXCEPTION 'sleep_claim failed to transition locked job'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN true;
END;
$p04$;

CREATE OR REPLACE FUNCTION cordis.resolve_due_waits(
    p_run_id text DEFAULT NULL,
    p_limit  integer DEFAULT 100
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p04$
DECLARE
    t0 timestamptz;
    n integer;
    v_resolved integer := 0;
    cand record;
    ev_payload jsonb;
    job_status text;
    job_token uuid;
    job_claimed_by text;
    job_expires timestamptz;
    wait_await uuid;
    wait_scope text;
    wait_name text;
    wait_deadline timestamptz;
BEGIN
    IF p_limit IS NULL OR p_limit <= 0 THEN
        RAISE EXCEPTION 'p_limit must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_run_id IS NOT NULL AND pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    t0 := pg_catalog.clock_timestamp();

    FOR cand IN
        SELECT picked.run_id, picked.await_id,
               picked.event_scope_id, picked.event_name, picked.deadline
          FROM (
              SELECT w.run_id, w.await_id,
                     w.event_scope_id, w.event_name, w.deadline
                FROM cordis.run_waits AS w
               WHERE w.deadline IS NOT NULL
                 AND w.deadline <= t0
                 AND (p_run_id IS NULL OR w.run_id = p_run_id)
               ORDER BY w.deadline ASC, w.event_scope_id, w.event_name, w.run_id
               LIMIT p_limit
          ) AS picked
         ORDER BY picked.event_scope_id, picked.event_name, picked.run_id
    LOOP
        SELECT e.payload
          INTO ev_payload
          FROM cordis.run_events AS e
         WHERE e.event_scope_id = cand.event_scope_id
           AND e.event_name = cand.event_name
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'due wait has no event row'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        -- Recheck identity before taking the jobs lock. A candidate can become
        -- stale after selection if its run was woken and registered on another
        -- event key. Keeping that stale path jobs-lock-free prevents a
        -- cross-event event->jobs cycle with another resolver.
        SELECT w.await_id, w.event_scope_id, w.event_name
          INTO wait_await, wait_scope, wait_name
          FROM cordis.run_waits AS w
         WHERE w.run_id = cand.run_id;
        IF NOT FOUND
           OR wait_await IS DISTINCT FROM cand.await_id
           OR wait_scope IS DISTINCT FROM cand.event_scope_id
           OR wait_name IS DISTINCT FROM cand.event_name THEN
            CONTINUE;
        END IF;

        SELECT j.status, j.claim_token, j.claimed_by, j.claim_expires_at
          INTO job_status, job_token, job_claimed_by, job_expires
          FROM cordis.jobs AS j
         WHERE j.run_id = cand.run_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'due wait has no jobs row'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        SELECT w.await_id, w.event_scope_id, w.event_name, w.deadline
          INTO wait_await, wait_scope, wait_name, wait_deadline
          FROM cordis.run_waits AS w
         WHERE w.run_id = cand.run_id
         FOR UPDATE;
        IF NOT FOUND THEN
            CONTINUE;
        END IF;
        IF wait_await IS DISTINCT FROM cand.await_id
           OR wait_scope IS DISTINCT FROM cand.event_scope_id
           OR wait_name IS DISTINCT FROM cand.event_name THEN
            CONTINUE;
        END IF;
        IF wait_deadline IS NULL OR wait_deadline > t0 THEN
            CONTINUE;
        END IF;

        IF ev_payload IS NOT NULL
           OR job_status IS DISTINCT FROM 'WAITING'
           OR job_token IS NOT NULL
           OR job_claimed_by IS NOT NULL
           OR job_expires IS NOT NULL THEN
            RAISE EXCEPTION 'due wait is inconsistent with jobs or event state'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        PERFORM cordis.emit_step(
            cand.run_id,
            'run/wake',
            pg_catalog.jsonb_build_object(
                'await_id', wait_await,
                'event_scope_id', wait_scope,
                'event_name', wait_name,
                'wake_reason', 'timeout',
                'deadline', pg_catalog.to_jsonb(wait_deadline),
                'woken_at', pg_catalog.to_jsonb(t0)
            ),
            NULL
        );

        UPDATE cordis.jobs
           SET status = 'PENDING',
               available_at = t0,
               completed_at = NULL,
               result = NULL,
               error = NULL
         WHERE run_id = cand.run_id
           AND status = 'WAITING';
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN
            RAISE EXCEPTION 'failed to timeout-wake waiting job'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        DELETE FROM cordis.run_waits
         WHERE run_id = cand.run_id
           AND await_id = wait_await;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN
            RAISE EXCEPTION 'failed to delete timed-out wait'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;

        v_resolved := v_resolved + 1;
    END LOOP;

    RETURN v_resolved;
END;
$p04$;

CREATE OR REPLACE FUNCTION cordis.fail_claim(
    p_claim_token uuid,
    p_reason jsonb
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p04$
DECLARE
    t0 timestamptz;
    n integer;
    v_job_id bigint;
    v_run_id text;
    v_attempt integer;
    v_max_attempts integer;
    v_base double precision;
    v_factor double precision;
    v_max_sec double precision;
    v_delay double precision;
    v_retry_at timestamptz;
    v_next integer;
    v_status text;
    v_envelope jsonb;
    v_error_seq bigint;
    v_error_payload jsonb;
BEGIN
    IF p_reason IS NULL THEN
        RAISE EXCEPTION 'p_reason must not be null'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    t0 := pg_catalog.clock_timestamp();
    SELECT j.job_id, j.run_id, j.attempt, j.max_attempts,
           j.retry_backoff_base_seconds, j.retry_backoff_factor,
           j.retry_backoff_max_seconds
      INTO v_job_id, v_run_id, v_attempt, v_max_attempts,
           v_base, v_factor, v_max_sec
      FROM cordis.jobs AS j
     WHERE j.claim_token = p_claim_token
       AND j.status = 'RUNNING'
       AND j.claim_expires_at > t0
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;

    SELECT s.seq, s.payload
      INTO v_error_seq, v_error_payload
      FROM cordis.agent_steps AS s
     WHERE s.run_id = v_run_id
       AND s.kind = 'error'
     ORDER BY s.seq DESC
     LIMIT 1;
    IF v_error_seq IS NOT NULL THEN
        UPDATE cordis.jobs
           SET status = 'ERROR',
               error = v_error_payload,
               result = NULL,
               completed_at = t0,
               claim_token = NULL,
               claimed_by = NULL,
               claim_expires_at = NULL
         WHERE job_id = v_job_id
           AND claim_token = p_claim_token
           AND status = 'RUNNING';
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN
            RAISE EXCEPTION 'fail_claim prewritten error lost the locked row'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        RETURN true;
    END IF;

    IF v_attempt < 2147483647
       AND (v_max_attempts IS NULL OR v_attempt < v_max_attempts) THEN
        v_next := v_attempt + 1;
        v_delay := cordis.retry_delay_seconds(
            v_attempt, v_base, v_factor, v_max_sec
        );
        v_retry_at := t0 + pg_catalog.make_interval(secs => v_delay);
        v_status := CASE WHEN v_delay > 0 THEN 'SLEEPING' ELSE 'PENDING' END;
        PERFORM cordis.emit_step(
            v_run_id,
            'run/sleep',
            pg_catalog.jsonb_build_object(
                'reason', 'retry',
                'failed_attempt', v_attempt,
                'next_attempt', v_next,
                'until', pg_catalog.to_jsonb(v_retry_at),
                'delay_seconds', v_delay,
                'error', p_reason
            ),
            NULL
        );
        UPDATE cordis.jobs
           SET status = v_status,
               available_at = v_retry_at,
               attempt = v_next,
               claim_token = NULL,
               claimed_by = NULL,
               claim_expires_at = NULL,
               completed_at = NULL,
               result = NULL,
               error = NULL
         WHERE job_id = v_job_id
           AND claim_token = p_claim_token
           AND status = 'RUNNING';
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN
            RAISE EXCEPTION 'fail_claim retry lost the locked row'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        RETURN true;
    END IF;

    v_envelope := pg_catalog.jsonb_build_object(
        'reason', 'MAX_RECOVERY_ATTEMPTS_EXCEEDED',
        'message', 'task exceeded max recovery attempts',
        'failure_source', 'fail_claim',
        'attempt', v_attempt,
        'max_attempts', to_jsonb(v_max_attempts),
        'cause', p_reason
    );
    IF v_max_attempts IS NULL THEN
        v_envelope := v_envelope || pg_catalog.jsonb_build_object(
            'limit', 'attempt_counter_exhausted'
        );
    END IF;

    PERFORM cordis.emit_step(v_run_id, 'error', v_envelope, NULL);

    UPDATE cordis.jobs
       SET status = 'ERROR',
           error = v_envelope,
           result = NULL,
           completed_at = t0,
           claim_token = NULL,
           claimed_by = NULL,
           claim_expires_at = NULL
     WHERE job_id = v_job_id
       AND claim_token = p_claim_token
       AND status = 'RUNNING';
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN
        RAISE EXCEPTION 'fail_claim terminal lost the locked row'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN true;
END;
$p04$;

CREATE OR REPLACE FUNCTION cordis.release_stale(
    p_run_id text DEFAULT NULL,
    p_limit integer DEFAULT 100
)
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p04$
DECLARE
    t0 timestamptz;
    n integer;
    v_processed integer := 0;
    rec record;
    v_delay double precision;
    v_retry_at timestamptz;
    v_next integer;
    v_status text;
    v_cause jsonb;
    v_timeout jsonb;
    v_envelope jsonb;
    v_error_seq bigint;
    v_error_payload jsonb;
BEGIN
    IF p_limit IS NULL OR p_limit <= 0 THEN
        RAISE EXCEPTION 'p_limit must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_run_id IS NOT NULL AND pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    t0 := pg_catalog.clock_timestamp();

    FOR rec IN
        SELECT j.job_id, j.run_id, j.attempt, j.max_attempts,
               j.retry_backoff_base_seconds, j.retry_backoff_factor,
               j.retry_backoff_max_seconds, j.claim_token, j.claimed_by,
               j.claim_expires_at
          FROM cordis.jobs AS j
         WHERE j.status = 'RUNNING'
           AND j.claim_expires_at <= t0
           AND (p_run_id IS NULL OR j.run_id = p_run_id)
         ORDER BY j.claim_expires_at ASC, j.job_id ASC
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    LOOP
        v_cause := pg_catalog.jsonb_build_object(
            'reason', 'CLAIM_TIMEOUT',
            'message', 'worker did not finish before claim expiry',
            'claim_token', rec.claim_token,
            'claimed_by', rec.claimed_by,
            'claim_expires_at', pg_catalog.to_jsonb(rec.claim_expires_at)
        );

        v_error_seq := NULL;
        v_error_payload := NULL;
        SELECT s.seq, s.payload
          INTO v_error_seq, v_error_payload
          FROM cordis.agent_steps AS s
         WHERE s.run_id = rec.run_id
           AND s.kind = 'error'
         ORDER BY s.seq DESC
         LIMIT 1;
        IF v_error_seq IS NOT NULL THEN
            v_timeout := pg_catalog.jsonb_build_object(
                'reason', 'claim_timeout',
                'claim_token', rec.claim_token,
                'claimed_by', rec.claimed_by,
                'claim_expires_at', pg_catalog.to_jsonb(rec.claim_expires_at),
                'outcome', 'terminal',
                'terminal_reason', 'PREWRITTEN_ERROR_EVENT',
                'error_seq', v_error_seq
            );
            PERFORM cordis.emit_step(
                rec.run_id, 'run/claim_timeout', v_timeout, NULL
            );
            UPDATE cordis.jobs
               SET status = 'ERROR',
                   error = v_error_payload,
                   result = NULL,
                   completed_at = t0,
                   claim_token = NULL,
                   claimed_by = NULL,
                   claim_expires_at = NULL
             WHERE job_id = rec.job_id
               AND claim_token = rec.claim_token
               AND status = 'RUNNING';
            GET DIAGNOSTICS n = ROW_COUNT;
            IF n <> 1 THEN
                RAISE EXCEPTION 'release_stale prewritten error lost the locked row'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            v_processed := v_processed + 1;
            CONTINUE;
        END IF;

        IF rec.attempt < 2147483647
           AND (rec.max_attempts IS NULL OR rec.attempt < rec.max_attempts) THEN
            v_next := rec.attempt + 1;
            v_delay := cordis.retry_delay_seconds(
                rec.attempt,
                rec.retry_backoff_base_seconds,
                rec.retry_backoff_factor,
                rec.retry_backoff_max_seconds
            );
            v_retry_at := t0 + pg_catalog.make_interval(secs => v_delay);
            v_status := CASE WHEN v_delay > 0 THEN 'SLEEPING' ELSE 'PENDING' END;
            v_timeout := pg_catalog.jsonb_build_object(
                'reason', 'claim_timeout',
                'claim_token', rec.claim_token,
                'claimed_by', rec.claimed_by,
                'claim_expires_at', pg_catalog.to_jsonb(rec.claim_expires_at),
                'failed_attempt', rec.attempt,
                'outcome', 'retry',
                'next_attempt', v_next,
                'retry_at', pg_catalog.to_jsonb(v_retry_at),
                'delay_seconds', v_delay
            );
            PERFORM cordis.emit_step(rec.run_id, 'run/claim_timeout', v_timeout, NULL);
            UPDATE cordis.jobs
               SET status = v_status,
                   available_at = v_retry_at,
                   attempt = v_next,
                   claim_token = NULL,
                   claimed_by = NULL,
                   claim_expires_at = NULL,
                   completed_at = NULL,
                   result = NULL,
                   error = NULL
             WHERE job_id = rec.job_id
               AND claim_token = rec.claim_token
               AND status = 'RUNNING';
            GET DIAGNOSTICS n = ROW_COUNT;
            IF n <> 1 THEN
                RAISE EXCEPTION 'release_stale retry lost the locked row'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
        ELSE
            v_envelope := pg_catalog.jsonb_build_object(
                'reason', 'MAX_RECOVERY_ATTEMPTS_EXCEEDED',
                'message', 'task exceeded max recovery attempts',
                'failure_source', 'claim_timeout',
                'attempt', rec.attempt,
                'max_attempts', to_jsonb(rec.max_attempts),
                'cause', v_cause
            );
            IF rec.max_attempts IS NULL THEN
                v_envelope := v_envelope || pg_catalog.jsonb_build_object(
                    'limit', 'attempt_counter_exhausted'
                );
            END IF;
            v_timeout := pg_catalog.jsonb_build_object(
                'reason', 'claim_timeout',
                'claim_token', rec.claim_token,
                'claimed_by', rec.claimed_by,
                'claim_expires_at', pg_catalog.to_jsonb(rec.claim_expires_at),
                'failed_attempt', rec.attempt,
                'outcome', 'terminal',
                'dead_letter', v_envelope
            );
            PERFORM cordis.emit_step(rec.run_id, 'run/claim_timeout', v_timeout, NULL);
            PERFORM cordis.emit_step(rec.run_id, 'error', v_envelope, NULL);
            UPDATE cordis.jobs
               SET status = 'ERROR',
                   error = v_envelope,
                   result = NULL,
                   completed_at = t0,
                   claim_token = NULL,
                   claimed_by = NULL,
                   claim_expires_at = NULL
             WHERE job_id = rec.job_id
               AND claim_token = rec.claim_token
               AND status = 'RUNNING';
            GET DIAGNOSTICS n = ROW_COUNT;
            IF n <> 1 THEN
                RAISE EXCEPTION 'release_stale terminal lost the locked row'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
        END IF;
        v_processed := v_processed + 1;
    END LOOP;

    RETURN v_processed;
END;
$p04$;

CREATE OR REPLACE FUNCTION cordis.claim_job(
    p_run_id text,
    p_worker_id text,
    p_lease_seconds integer DEFAULT 90
)
RETURNS SETOF cordis.jobs
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p04$
DECLARE
    t_claim timestamptz;
    v_job_id bigint;
    v_prior_status text;
    v_prior_available timestamptz;
    rec cordis.jobs;
BEGIN
    IF p_worker_id IS NULL OR pg_catalog.btrim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'p_worker_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_run_id IS NOT NULL AND pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_lease_seconds IS NULL OR p_lease_seconds <= 0 THEN
        RAISE EXCEPTION 'p_lease_seconds must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    PERFORM cordis.resolve_due_waits(p_run_id, 100);
    PERFORM cordis.release_stale(p_run_id, 100);
    t_claim := pg_catalog.clock_timestamp();

    SELECT j.job_id, j.status, j.available_at
      INTO v_job_id, v_prior_status, v_prior_available
      FROM cordis.jobs AS j
     WHERE j.status IN ('PENDING', 'SLEEPING')
       AND j.available_at <= t_claim
       AND (p_run_id IS NULL OR j.run_id = p_run_id)
     ORDER BY j.priority DESC, j.available_at ASC, j.job_id ASC
     FOR UPDATE SKIP LOCKED
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    UPDATE cordis.jobs AS j
       SET status = 'RUNNING',
           claim_token = pg_catalog.gen_random_uuid(),
           claimed_by = p_worker_id,
           claim_expires_at = t_claim + pg_catalog.make_interval(secs => p_lease_seconds),
           completed_at = NULL,
           result = NULL,
           error = NULL
     WHERE j.job_id = v_job_id
     RETURNING j.* INTO rec;

    IF v_prior_status = 'SLEEPING' THEN
        PERFORM cordis.emit_step(
            rec.run_id,
            'run/wake',
            pg_catalog.jsonb_build_object(
                'wake_reason', 'sleep',
                'scheduled_for', pg_catalog.to_jsonb(v_prior_available),
                'woken_at', pg_catalog.to_jsonb(t_claim)
            ),
            NULL
        );
    END IF;

    RETURN NEXT rec;
    RETURN;
END;
$p04$;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p04'::text;
$$;
