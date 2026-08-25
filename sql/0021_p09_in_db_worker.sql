-- P09: in-database worker, handler-aware enqueue, read-only tool invoke.
-- Replay-safe. No GRANT, extensions, public objects, or transaction control.
-- Does not replace or wrap cordis.step_once. plpgsql bodies use $p09$.

CREATE OR REPLACE FUNCTION cordis._resolve_in_db_queue_handler(
    p_identity text
)
RETURNS regprocedure
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p09$
DECLARE
    v_identity text;
    v_plugin cordis.plugin_catalog%ROWTYPE;
    v_proc pg_catalog.pg_proc%ROWTYPE;
    v_args text;
    v_has_path boolean;
BEGIN
    IF p_identity IS NULL
       OR pg_catalog.btrim(p_identity) = ''
       OR pg_catalog.octet_length(pg_catalog.btrim(p_identity)) > 128
       OR pg_catalog.btrim(p_identity)
          !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'P09_UNKNOWN_JOB_HANDLER'
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(p_identity);

    SELECT * INTO v_plugin
      FROM cordis.plugin_catalog
     WHERE identity = v_identity;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'P09_UNKNOWN_JOB_HANDLER'
            USING ERRCODE = '22023';
    END IF;

    IF v_plugin.locus IS DISTINCT FROM 'in-db'
       OR v_plugin.invocation IS DISTINCT FROM 'queue'
       OR v_plugin.entrypoint IS NULL
       OR COALESCE(pg_catalog.cardinality(v_plugin.required_grants), 0) <> 0 THEN
        RAISE EXCEPTION 'P09_JOB_HANDLER_UNSUPPORTED'
            USING ERRCODE = '0A000';
    END IF;

    IF pg_catalog.jsonb_typeof(v_plugin.config) IS DISTINCT FROM 'object'
       OR (v_plugin.config ->> 'worker_abi') IS DISTINCT FROM 'cordis.p09.queue.v1' THEN
        RAISE EXCEPTION 'P09_JOB_HANDLER_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;

    SELECT * INTO v_proc
      FROM pg_catalog.pg_proc
     WHERE oid = v_plugin.entrypoint;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'P09_JOB_HANDLER_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;

    v_args := pg_catalog.oidvectortypes(v_proc.proargtypes);
    SELECT EXISTS (
        SELECT 1
          FROM pg_catalog.unnest(
                   COALESCE(v_proc.proconfig, ARRAY[]::text[])
               ) AS cfg(val)
         WHERE cfg.val = 'search_path=pg_catalog'
    ) INTO v_has_path;

    IF v_proc.prokind IS DISTINCT FROM 'f'
       OR v_proc.proretset
       OR v_args IS DISTINCT FROM 'text, uuid, integer'
       OR pg_catalog.pg_get_function_result(v_proc.oid) IS DISTINCT FROM 'text'
       OR v_proc.provolatile IS DISTINCT FROM 'v'
       OR v_proc.prosecdef
       OR NOT v_has_path THEN
        RAISE EXCEPTION 'P09_JOB_HANDLER_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_proc AS p
         WHERE p.pronamespace = v_proc.pronamespace
           AND p.proname = v_proc.proname
           AND p.oid IS DISTINCT FROM v_proc.oid
    ) THEN
        RAISE EXCEPTION 'P09_JOB_HANDLER_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;

    RETURN v_plugin.entrypoint;
END;
$p09$;

CREATE OR REPLACE FUNCTION cordis.enqueue_job(
    p_run_id   text,
    p_job_type text,
    p_paradigm text,
    p_payload  jsonb DEFAULT '{}'::jsonb,
    p_priority integer DEFAULT 0
)
RETURNS bigint
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p09$
DECLARE
    v_handler regprocedure;
    v_job_type text;
    v_paradigm text;
    v_payload jsonb;
    v_job_id bigint;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'P09_INVALID_ENQUEUE'
            USING ERRCODE = '22023';
    END IF;
    IF p_payload IS NULL
       OR pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'P09_INVALID_ENQUEUE'
            USING ERRCODE = '22023';
    END IF;
    IF p_payload ? 'paradigm' THEN
        RAISE EXCEPTION 'P09_INVALID_ENQUEUE'
            USING ERRCODE = '22023';
    END IF;
    IF p_priority IS NULL THEN
        RAISE EXCEPTION 'P09_INVALID_ENQUEUE'
            USING ERRCODE = '22023';
    END IF;

    PERFORM cordis._require_isolation_feature();
    SELECT p.identity INTO v_paradigm
      FROM cordis.paradigm_policy(p_paradigm) AS p;
    v_handler := cordis._resolve_in_db_queue_handler(p_job_type);
    v_job_type := pg_catalog.btrim(p_job_type);
    IF v_handler IS NULL THEN
        RAISE EXCEPTION 'P09_JOB_HANDLER_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;

    v_payload := p_payload || pg_catalog.jsonb_build_object(
        'paradigm', v_paradigm
    );

    INSERT INTO cordis.jobs (run_id, job_type, payload, priority)
    VALUES (
        p_run_id,
        v_job_type,
        v_payload,
        p_priority
    )
    RETURNING job_id INTO v_job_id;

    RETURN v_job_id;
END;
$p09$;

CREATE OR REPLACE FUNCTION cordis.invoke_in_db_tool(
    p_claim_token uuid,
    p_run_id      text,
    p_slice_id    uuid,
    p_identity    text,
    p_bindings    jsonb,
    p_arguments   jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p09$
DECLARE
    v_identity text;
    v_live boolean;
    v_desc jsonb;
    v_entrypoint_txt text;
    v_fn regprocedure;
    v_proc pg_catalog.pg_proc%ROWTYPE;
    v_args text;
    v_has_path boolean;
    v_nsp text;
    v_proname text;
    v_result jsonb;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'P09_INVALID_TOOL_REQUEST'
            USING ERRCODE = '22023';
    END IF;
    IF p_claim_token IS NULL OR p_slice_id IS NULL THEN
        RAISE EXCEPTION 'P09_INVALID_TOOL_REQUEST'
            USING ERRCODE = '22023';
    END IF;
    IF p_identity IS NULL
       OR pg_catalog.btrim(p_identity) = ''
       OR pg_catalog.octet_length(pg_catalog.btrim(p_identity)) > 128
       OR pg_catalog.btrim(p_identity)
          !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'P09_INVALID_TOOL_REQUEST'
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(p_identity);
    IF p_bindings IS NULL
       OR pg_catalog.jsonb_typeof(p_bindings) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'P09_INVALID_TOOL_REQUEST'
            USING ERRCODE = '22023';
    END IF;
    IF p_arguments IS NULL
       OR pg_catalog.jsonb_typeof(p_arguments) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'P09_INVALID_TOOL_REQUEST'
            USING ERRCODE = '22023';
    END IF;

    PERFORM cordis._require_isolation_feature();

    SELECT EXISTS (
        SELECT 1
          FROM cordis.jobs AS j
         WHERE j.run_id = p_run_id
           AND j.claim_token = p_claim_token
           AND j.status = 'RUNNING'
           AND j.claim_expires_at > pg_catalog.clock_timestamp()
    ) INTO v_live;
    IF NOT v_live THEN
        RAISE EXCEPTION 'P09_TOOL_CLAIM_REQUIRED'
            USING ERRCODE = '42501';
    END IF;

    v_desc := cordis.authorize_tool_dispatch(
        p_run_id, p_slice_id, v_identity, p_bindings
    );

    IF (v_desc ->> 'locus') IS DISTINCT FROM 'in-db' THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_LOCUS_REQUIRED'
            USING ERRCODE = '42501';
    END IF;
    IF (v_desc ->> 'invocation') IS DISTINCT FROM 'session_select' THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_INVOCATION_UNSUPPORTED'
            USING ERRCODE = '0A000';
    END IF;
    IF (v_desc ->> 'effect_class') IS DISTINCT FROM 'read_only'
       OR (v_desc ->> 'retry_class') IS DISTINCT FROM 'replayable'
       OR (v_desc ->> 'reconciliation') IS DISTINCT FROM 'none' THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_EFFECT_UNSUPPORTED'
            USING ERRCODE = '0A000';
    END IF;

    IF pg_catalog.jsonb_typeof(v_desc -> 'entrypoint') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;
    v_entrypoint_txt := v_desc ->> 'entrypoint';
    v_fn := pg_catalog.to_regprocedure(v_entrypoint_txt);
    IF v_fn IS NULL THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;

    SELECT * INTO v_proc
      FROM pg_catalog.pg_proc
     WHERE oid = v_fn;
    v_args := pg_catalog.oidvectortypes(v_proc.proargtypes);
    SELECT EXISTS (
        SELECT 1
          FROM pg_catalog.unnest(
                   COALESCE(v_proc.proconfig, ARRAY[]::text[])
               ) AS cfg(val)
         WHERE cfg.val = 'search_path=pg_catalog'
    ) INTO v_has_path;
    IF v_proc.prokind IS DISTINCT FROM 'f'
       OR v_proc.proretset
       OR v_args IS DISTINCT FROM 'jsonb'
       OR pg_catalog.pg_get_function_result(v_proc.oid) IS DISTINCT FROM 'jsonb'
       OR v_proc.provolatile NOT IN ('s', 'i')
       OR v_proc.prosecdef
       OR NOT v_has_path THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_proc AS p
         WHERE p.pronamespace = v_proc.pronamespace
           AND p.proname = v_proc.proname
           AND p.oid IS DISTINCT FROM v_proc.oid
    ) THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_ABI_MISMATCH'
            USING ERRCODE = '55000';
    END IF;

    SELECT n.nspname, v_proc.proname
      INTO v_nsp, v_proname
      FROM pg_catalog.pg_namespace AS n
     WHERE n.oid = v_proc.pronamespace;
    EXECUTE pg_catalog.format('SELECT %I.%I($1)', v_nsp, v_proname)
       INTO v_result
      USING p_arguments;

    IF v_result IS NULL THEN
        RAISE EXCEPTION 'P09_IN_DB_TOOL_INVALID_RESULT'
            USING ERRCODE = '55000';
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM cordis.jobs AS j
         WHERE j.run_id = p_run_id
           AND j.claim_token = p_claim_token
           AND j.status = 'RUNNING'
           AND j.claim_expires_at > pg_catalog.clock_timestamp()
    ) INTO v_live;
    IF NOT v_live THEN
        RAISE EXCEPTION 'P09_TOOL_CLAIM_LOST'
            USING ERRCODE = '55000';
    END IF;

    RETURN pg_catalog.jsonb_build_object(
        'protocol', 'cordis.p09.in_db_tool.v1',
        'identity', v_desc ->> 'identity',
        'descriptor', v_desc,
        'result', v_result
    );
END;
$p09$;

CREATE OR REPLACE FUNCTION cordis.worker_step(
    p_worker_id     text,
    p_run_id        text DEFAULT NULL,
    p_lease_seconds integer DEFAULT 90
)
RETURNS TABLE (
    job_id  bigint,
    run_id  text,
    outcome text
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p09$
DECLARE
    v_job cordis.jobs%ROWTYPE;
    v_handler regprocedure;
    v_raw text;
    v_code text;
    v_message text;
    v_sqlstate text;
    v_err jsonb;
    v_final jsonb;
    v_error jsonb;
    v_ok boolean;
    v_wait_n integer;
    v_status text;
    v_token uuid;
    v_claimed_by text;
    v_expires timestamptz;
    v_nsp text;
    v_proname text;
BEGIN
    IF p_worker_id IS NULL OR pg_catalog.btrim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'P09_INVALID_WORKER'
            USING ERRCODE = '22023';
    END IF;
    IF p_run_id IS NOT NULL AND pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'P09_INVALID_WORKER'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds IS NULL OR p_lease_seconds <= 0 THEN
        RAISE EXCEPTION 'P09_INVALID_WORKER'
            USING ERRCODE = '22023';
    END IF;

    PERFORM cordis._require_isolation_feature();

    SELECT * INTO v_job
      FROM cordis.claim_job(p_run_id, p_worker_id, p_lease_seconds);
    IF NOT FOUND THEN
        job_id := NULL;
        run_id := NULL;
        outcome := 'idle';
        RETURN NEXT;
        RETURN;
    END IF;

    v_code := NULL;
    v_sqlstate := NULL;
    v_message := NULL;
    v_raw := NULL;

    IF pg_catalog.jsonb_typeof(v_job.payload) IS DISTINCT FROM 'object'
       OR pg_catalog.jsonb_typeof(v_job.payload -> 'paradigm')
          IS DISTINCT FROM 'string'
       OR pg_catalog.btrim(v_job.payload ->> 'paradigm') = '' THEN
        v_code := 'P09_JOB_PAYLOAD_INVALID';
        v_message := 'job payload is missing a valid paradigm';
    ELSE
        BEGIN
            PERFORM * FROM cordis.paradigm_policy(v_job.payload ->> 'paradigm');
        EXCEPTION
            WHEN invalid_parameter_value THEN
                v_code := 'P09_PARADIGM_UNAVAILABLE';
                v_sqlstate := SQLSTATE;
                v_message := pg_catalog.left(SQLERRM, 1000);
        END;
        IF v_code IS NULL THEN
            BEGIN
                v_handler := cordis._resolve_in_db_queue_handler(v_job.job_type);
            EXCEPTION
                WHEN invalid_parameter_value
                    OR feature_not_supported
                    OR object_not_in_prerequisite_state THEN
                    v_code := 'P09_HANDLER_UNAVAILABLE';
                    v_sqlstate := SQLSTATE;
                    v_message := pg_catalog.left(SQLERRM, 1000);
            END;
        END IF;
    END IF;

    IF v_code IS NULL THEN
        SELECT n.nspname, p.proname
          INTO v_nsp, v_proname
          FROM pg_catalog.pg_proc AS p
          JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
         WHERE p.oid = v_handler;
        EXECUTE pg_catalog.format(
            'SELECT %I.%I($1, $2, $3)', v_nsp, v_proname
        )
           INTO v_raw
          USING v_job.run_id, v_job.claim_token, p_lease_seconds;
    END IF;

    IF v_code IS NULL AND v_raw IS NOT DISTINCT FROM 'yield' THEN
        v_ok := cordis.yield_claim(v_job.claim_token);
        job_id := v_job.job_id;
        run_id := v_job.run_id;
        IF v_ok THEN
            outcome := 'yield';
        ELSE
            outcome := 'lost_claim';
        END IF;
        RETURN NEXT;
        RETURN;
    ELSIF v_code IS NULL AND v_raw IS NOT DISTINCT FROM 'complete' THEN
        SELECT s.payload INTO v_final
          FROM cordis.agent_steps AS s
         WHERE s.run_id = v_job.run_id
           AND s.kind = 'final'
         ORDER BY s.seq DESC
         LIMIT 1;
        IF v_final IS NULL THEN
            v_code := 'P09_COMPLETE_WITHOUT_FINAL';
            v_message := 'complete outcome has no final log event';
        ELSE
            v_ok := cordis.complete_claim(v_job.claim_token, v_final);
            job_id := v_job.job_id;
            run_id := v_job.run_id;
            IF v_ok THEN
                outcome := 'complete';
            ELSE
                outcome := 'lost_claim';
            END IF;
            RETURN NEXT;
            RETURN;
        END IF;
    ELSIF v_code IS NULL AND v_raw IS NOT DISTINCT FROM 'fail' THEN
        SELECT s.payload INTO v_error
          FROM cordis.agent_steps AS s
         WHERE s.run_id = v_job.run_id
           AND s.kind = 'error'
         ORDER BY s.seq DESC
         LIMIT 1;
        IF v_error IS NULL THEN
            v_code := 'P09_FAIL_WITHOUT_ERROR';
            v_message := 'fail outcome has no error log event';
        ELSE
            v_ok := cordis.fail_claim(v_job.claim_token, v_error);
            job_id := v_job.job_id;
            run_id := v_job.run_id;
            IF v_ok THEN
                outcome := 'fail';
            ELSE
                outcome := 'lost_claim';
            END IF;
            RETURN NEXT;
            RETURN;
        END IF;
    ELSIF v_code IS NULL AND v_raw IS NOT DISTINCT FROM 'wait' THEN
        SELECT j.status, j.claim_token, j.claimed_by, j.claim_expires_at
          INTO v_status, v_token, v_claimed_by, v_expires
          FROM cordis.jobs AS j
         WHERE j.job_id = v_job.job_id;
        SELECT count(*)::integer INTO v_wait_n
          FROM cordis.run_waits AS w
         WHERE w.run_id = v_job.run_id;
        IF v_status = 'WAITING'
           AND v_token IS NULL
           AND v_claimed_by IS NULL
           AND v_expires IS NULL
           AND v_wait_n = 1 THEN
            job_id := v_job.job_id;
            run_id := v_job.run_id;
            outcome := 'wait';
            RETURN NEXT;
            RETURN;
        ELSIF v_status = 'RUNNING'
           AND v_token IS NOT DISTINCT FROM v_job.claim_token THEN
            v_code := 'P09_WAIT_NOT_REGISTERED';
            v_message := 'wait outcome without durable P03 registration';
        ELSE
            RAISE EXCEPTION 'P09_WAIT_STATE_INVALID'
                USING ERRCODE = '55000';
        END IF;
    ELSIF v_code IS NULL AND v_raw IS NOT DISTINCT FROM 'lost_claim' THEN
        job_id := v_job.job_id;
        run_id := v_job.run_id;
        outcome := 'lost_claim';
        RETURN NEXT;
        RETURN;
    ELSIF v_code IS NULL THEN
        v_code := 'P09_INVALID_STEP_OUTCOME';
        v_message := 'handler returned an unknown or null outcome';
    END IF;

    v_err := pg_catalog.jsonb_build_object(
        'protocol', 'cordis.p09.worker.v1',
        'code', v_code,
        'message', COALESCE(v_message, v_code),
        'details', pg_catalog.jsonb_build_object(
            'job_type', to_jsonb(v_job.job_type),
            'paradigm', v_job.payload -> 'paradigm',
            'handler_outcome', to_jsonb(v_raw),
            'source_sqlstate', to_jsonb(v_sqlstate)
        ),
        'step_name', NULL
    );
    v_ok := cordis.emit_step_claimed(
        v_job.claim_token,
        v_job.run_id,
        'error',
        v_err,
        NULL,
        p_lease_seconds
    );
    IF NOT v_ok THEN
        job_id := v_job.job_id;
        run_id := v_job.run_id;
        outcome := 'lost_claim';
        RETURN NEXT;
        RETURN;
    END IF;
    v_ok := cordis.fail_claim(v_job.claim_token, v_err);
    job_id := v_job.job_id;
    run_id := v_job.run_id;
    IF v_ok THEN
        outcome := 'fail';
    ELSE
        outcome := 'lost_claim';
    END IF;
    RETURN NEXT;
    RETURN;
END;
$p09$;

COMMENT ON FUNCTION cordis.step_once(text, uuid, integer) IS
$p09c${"cordis_plugin":{"identity":"kernel.step_once","version":"0.1.0","name":"kernel.step_once","description":"P05 mock/proof queue body, not the user-facing isolated driver (legacy_unscoped).","locus":"in-db","invocation":"queue","required_grants":[],"effect_class":"transactional","retry_class":"idempotent","reconciliation":"none","session_scope":"run","config":{"worker_abi":"cordis.p09.queue.v1","protocol":"cordis.p05.mock.v1","isolated":false}}}$p09c$;

SELECT cordis.refresh_plugins();

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p21'::text;
$$;
