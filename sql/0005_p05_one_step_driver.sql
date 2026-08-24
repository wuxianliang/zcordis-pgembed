-- P05: one-step driver and mock LLM hook.
-- Replay-safe. No GRANT, extensions, public objects, or transaction control.
-- Semantics only: does not copy scratch or G research SQL.

CREATE OR REPLACE FUNCTION cordis.invoke_llm(
    p_run_id       text,
    p_step_name    text,
    p_request      jsonb,
    p_provider_key text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p05$
DECLARE
    v_payload jsonb;
    v_resp    jsonb;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_step_name IS NULL OR p_step_name !~ '^s-[1-9][0-9]*$' THEN
        RAISE EXCEPTION 'p_step_name must match s-N'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_request IS NULL OR pg_catalog.jsonb_typeof(p_request) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'p_request must be a JSON object'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_provider_key IS NULL OR pg_catalog.btrim(p_provider_key) = '' THEN
        RAISE EXCEPTION 'p_provider_key must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_provider_key IS DISTINCT FROM pg_catalog.md5(p_run_id || '/' || p_step_name) THEN
        RAISE EXCEPTION 'p_provider_key must equal md5(run_id || ''/'' || step_name)'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT j.payload
      INTO v_payload
      FROM cordis.jobs AS j
     WHERE j.run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'jobs row for run_id not found'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    IF pg_catalog.jsonb_typeof(v_payload) IS DISTINCT FROM 'object'
       OR pg_catalog.jsonb_typeof(v_payload -> 'mock_llm') IS DISTINCT FROM 'object'
       OR pg_catalog.jsonb_typeof(v_payload -> 'mock_llm' -> 'responses') IS DISTINCT FROM 'object'
       OR NOT ((v_payload -> 'mock_llm' -> 'responses') ? p_step_name) THEN
        RAISE EXCEPTION 'mock LLM response for step is missing'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    v_resp := v_payload -> 'mock_llm' -> 'responses' -> p_step_name;
    IF pg_catalog.jsonb_typeof(v_resp) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'mock LLM response for step must be a JSON object'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;

    RETURN v_resp;
END;
$p05$;

CREATE OR REPLACE FUNCTION cordis.step_once(
    p_run_id         text,
    p_claim_token    uuid,
    p_extend_seconds integer DEFAULT 90
)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p05$
DECLARE
    captured            timestamptz;
    v_job_type          text;
    v_payload           jsonb;
    v_model             text;
    v_params            jsonb;
    v_tools             jsonb;
    v_input             jsonb;
    v_max_steps         integer;
    v_max_txt           text;
    v_max_big           bigint;
    v_step_name         text;
    v_ckpt              cordis.agent_steps;
    v_ckpt_seq          bigint;
    v_steps_used        integer;
    v_history           jsonb;
    v_request           jsonb;
    v_provider_key      text;
    v_fingerprint       text;
    v_decision          jsonb;
    v_action            text;
    v_args              jsonb;
    v_obs_root          jsonb;
    v_obs               jsonb;
    v_llm_payload       jsonb;
    v_err               jsonb;
    v_code              text;
    v_message           text;
    v_details           jsonb;
    v_latest_await_seq  bigint;
    v_latest_await_id   text;
    v_has_wake          boolean;
    v_sqlstate          text;
    v_sqlerrm           text;
    v_live              boolean;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'p_run_id must not be blank'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_extend_seconds IS NULL OR p_extend_seconds <= 0 THEN
        RAISE EXCEPTION 'p_extend_seconds must be positive'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_claim_token IS NULL THEN
        RETURN 'lost_claim';
    END IF;

    captured := pg_catalog.clock_timestamp();
    SELECT j.job_type, j.payload
      INTO v_job_type, v_payload
      FROM cordis.jobs AS j
     WHERE j.run_id = p_run_id
       AND j.claim_token = p_claim_token
       AND j.status = 'RUNNING'
       AND j.claim_expires_at > captured;
    IF NOT FOUND THEN
        RETURN 'lost_claim';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM cordis.agent_steps AS s
         WHERE s.run_id = p_run_id
           AND s.kind = 'final'
    ) THEN
        RETURN 'complete';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM cordis.agent_steps AS s
         WHERE s.run_id = p_run_id
           AND s.kind = 'error'
    ) THEN
        RETURN 'fail';
    END IF;

    SELECT a.seq, a.payload ->> 'await_id'
      INTO v_latest_await_seq, v_latest_await_id
      FROM cordis.agent_steps AS a
     WHERE a.run_id = p_run_id
       AND a.kind = 'run/await'
     ORDER BY a.seq DESC
     LIMIT 1;
    IF v_latest_await_seq IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1
              FROM cordis.agent_steps AS w
             WHERE w.run_id = p_run_id
               AND w.kind = 'run/wake'
               AND w.seq > v_latest_await_seq
               AND w.payload ->> 'await_id' = v_latest_await_id
        ) INTO v_has_wake;
        IF v_latest_await_id IS NULL OR NOT v_has_wake THEN
            v_err := pg_catalog.jsonb_build_object(
                'code', 'P05_INVALID_HISTORY',
                'details', pg_catalog.jsonb_build_object(
                    'reason', 'unmatched_await'
                ),
                'message', 'unmatched run/await on a live RUNNING claim',
                'step_name', pg_catalog.to_jsonb(NULL::text)
            );
            IF NOT cordis.emit_step_claimed(
                p_claim_token, p_run_id, 'error', v_err, NULL, p_extend_seconds
            ) THEN
                RETURN 'lost_claim';
            END IF;
            RETURN 'fail';
        END IF;
    END IF;

    v_code := NULL;
    v_message := NULL;
    v_details := '{}'::jsonb;
    BEGIN
        IF pg_catalog.jsonb_typeof(v_payload) IS DISTINCT FROM 'object' THEN
            v_code := 'P05_INVALID_JOB_CONFIG';
            v_message := 'jobs.payload must be a JSON object';
        ELSIF v_payload ? 'model'
           AND (
               pg_catalog.jsonb_typeof(v_payload -> 'model') IS DISTINCT FROM 'string'
               OR pg_catalog.btrim(v_payload ->> 'model') = ''
           ) THEN
            v_code := 'P05_INVALID_JOB_CONFIG';
            v_message := 'jobs.payload.model must be a nonblank string';
        ELSIF v_payload ? 'llm_params'
           AND pg_catalog.jsonb_typeof(v_payload -> 'llm_params') IS DISTINCT FROM 'object' THEN
            v_code := 'P05_INVALID_JOB_CONFIG';
            v_message := 'jobs.payload.llm_params must be a JSON object';
        ELSIF v_payload ? 'tools'
           AND pg_catalog.jsonb_typeof(v_payload -> 'tools') IS DISTINCT FROM 'array' THEN
            v_code := 'P05_INVALID_JOB_CONFIG';
            v_message := 'jobs.payload.tools must be a JSON array';
        ELSIF v_payload ? 'max_steps' THEN
            IF pg_catalog.jsonb_typeof(v_payload -> 'max_steps') IS DISTINCT FROM 'number' THEN
                v_code := 'P05_INVALID_JOB_CONFIG';
                v_message := 'jobs.payload.max_steps must be a positive integer';
            ELSE
                v_max_txt := v_payload ->> 'max_steps';
                IF v_max_txt IS NULL OR v_max_txt !~ '^[1-9][0-9]*$' THEN
                    v_code := 'P05_INVALID_JOB_CONFIG';
                    v_message := 'jobs.payload.max_steps must be a positive integer';
                ELSE
                    v_max_big := v_max_txt::bigint;
                    IF v_max_big > 2147483647 THEN
                        v_code := 'P05_INVALID_JOB_CONFIG';
                        v_message := 'jobs.payload.max_steps must fit integer';
                    ELSE
                        v_max_steps := v_max_txt::integer;
                    END IF;
                END IF;
            END IF;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        v_code := 'P05_INVALID_JOB_CONFIG';
        GET STACKED DIAGNOSTICS v_sqlerrm = MESSAGE_TEXT;
        v_message := pg_catalog.left(v_sqlerrm, 1000);
    END;
    IF v_code IS NOT NULL THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', v_code,
            'details', v_details,
            'message', v_message,
            'step_name', pg_catalog.to_jsonb(NULL::text)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, NULL, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;

    IF v_payload ? 'model' THEN
        v_model := v_payload ->> 'model';
    ELSE
        v_model := 'mock';
    END IF;
    IF v_payload ? 'llm_params' THEN
        v_params := v_payload -> 'llm_params';
    ELSE
        v_params := '{}'::jsonb;
    END IF;
    IF v_payload ? 'tools' THEN
        v_tools := v_payload -> 'tools';
    ELSE
        v_tools := '[{"effect_class":"read_only","name":"mock.observe"}]'::jsonb;
    END IF;
    IF v_payload ? 'input' THEN
        v_input := v_payload -> 'input';
    ELSE
        v_input := 'null'::jsonb;
    END IF;
    IF v_max_steps IS NULL THEN
        v_max_steps := 10;
    END IF;

    SELECT count(*)::integer
      INTO v_steps_used
      FROM cordis.agent_steps AS s
     WHERE s.run_id = p_run_id
       AND s.kind = 'llm';

    v_step_name := cordis.next_step_name(p_run_id);

    SELECT s.*
      INTO v_ckpt
      FROM cordis.llm_checkpoint(p_run_id, v_step_name) AS s;
    IF FOUND THEN
        v_ckpt_seq := v_ckpt.seq;
    ELSE
        v_ckpt_seq := NULL;
    END IF;

    IF v_ckpt_seq IS NULL AND v_steps_used >= v_max_steps THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', 'P05_MAX_STEPS_EXCEEDED',
            'details', pg_catalog.jsonb_build_object(
                'max_steps', v_max_steps,
                'step_name', v_step_name,
                'steps_used', v_steps_used
            ),
            'message', 'committed LLM count reached max_steps',
            'step_name', pg_catalog.to_jsonb(v_step_name)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;

    IF v_ckpt_seq IS NULL AND EXISTS (
        SELECT 1
          FROM cordis.agent_steps AS s
         WHERE s.run_id = p_run_id
           AND s.step_name IS NOT DISTINCT FROM v_step_name
           AND s.kind IN ('tool', 'final')
    ) THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', 'P05_INVALID_HISTORY',
            'details', pg_catalog.jsonb_build_object(
                'step_name', v_step_name
            ),
            'message', 'tool or final exists without an llm checkpoint',
            'step_name', pg_catalog.to_jsonb(v_step_name)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;

    SELECT coalesce(pg_catalog.jsonb_agg(elem ORDER BY seq), '[]'::jsonb)
      INTO v_history
      FROM (
        SELECT
            s.seq,
            pg_catalog.jsonb_build_object(
                'kind', s.kind,
                'payload', s.payload,
                'seq', s.seq,
                'step_name', pg_catalog.to_jsonb(s.step_name)
            ) AS elem
          FROM cordis.agent_steps AS s
         WHERE s.run_id = p_run_id
           AND (v_ckpt_seq IS NULL OR s.seq < v_ckpt_seq)
      ) AS hist;

    v_request := pg_catalog.jsonb_build_object(
        'history', v_history,
        'input', v_input,
        'job_type', v_job_type,
        'model', v_model,
        'parameters', v_params,
        'protocol', 'cordis.p05.mock.v1',
        'run_id', p_run_id,
        'step_name', v_step_name,
        'tools', v_tools
    );
    v_provider_key := pg_catalog.md5(p_run_id || '/' || v_step_name);
    v_fingerprint := pg_catalog.md5(v_request::text);

    IF v_ckpt_seq IS NOT NULL THEN
        IF pg_catalog.jsonb_typeof(v_ckpt.payload) IS DISTINCT FROM 'object'
           OR pg_catalog.jsonb_typeof(v_ckpt.payload -> 'protocol') IS DISTINCT FROM 'string'
           OR (v_ckpt.payload ->> 'protocol') IS DISTINCT FROM 'cordis.p05.mock.v1'
           OR pg_catalog.jsonb_typeof(v_ckpt.payload -> 'raw') IS DISTINCT FROM 'object'
           OR pg_catalog.jsonb_typeof(v_ckpt.payload -> 'fingerprint') IS DISTINCT FROM 'string'
           OR (v_ckpt.payload ->> 'fingerprint') IS DISTINCT FROM v_fingerprint
           OR pg_catalog.jsonb_typeof(v_ckpt.payload -> 'provider_key') IS DISTINCT FROM 'string'
           OR (v_ckpt.payload ->> 'provider_key') IS DISTINCT FROM v_provider_key
           OR pg_catalog.jsonb_typeof(v_ckpt.payload -> 'model') IS DISTINCT FROM 'string'
           OR (v_ckpt.payload ->> 'model') IS DISTINCT FROM v_model THEN
            v_err := pg_catalog.jsonb_build_object(
                'code', 'P05_LLM_CHECKPOINT_MISMATCH',
                'details', pg_catalog.jsonb_build_object(
                    'expected_fingerprint', v_fingerprint,
                    'expected_provider_key', v_provider_key,
                    'stored_fingerprint', v_ckpt.payload -> 'fingerprint',
                    'stored_provider_key', v_ckpt.payload -> 'provider_key'
                ),
                'message', 'llm checkpoint does not match reconstructed request',
                'step_name', pg_catalog.to_jsonb(v_step_name)
            );
            IF NOT cordis.emit_step_claimed(
                p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
            ) THEN
                RETURN 'lost_claim';
            END IF;
            RETURN 'fail';
        END IF;
        v_decision := v_ckpt.payload -> 'raw';
    ELSE
        captured := pg_catalog.clock_timestamp();
        SELECT TRUE
          INTO v_live
          FROM cordis.jobs AS j
         WHERE j.run_id = p_run_id
           AND j.claim_token = p_claim_token
           AND j.status = 'RUNNING'
           AND j.claim_expires_at > captured;
        IF v_live IS NOT TRUE THEN
            RETURN 'lost_claim';
        END IF;

        BEGIN
            v_decision := cordis.invoke_llm(
                p_run_id, v_step_name, v_request, v_provider_key
            );
        EXCEPTION WHEN OTHERS THEN
            GET STACKED DIAGNOSTICS
                v_sqlstate = RETURNED_SQLSTATE,
                v_sqlerrm = MESSAGE_TEXT;
            v_err := pg_catalog.jsonb_build_object(
                'code', 'P05_LLM_INVOCATION_FAILED',
                'details', pg_catalog.jsonb_build_object(
                    'provider_key', v_provider_key,
                    'sqlstate', v_sqlstate
                ),
                'message', pg_catalog.left(v_sqlerrm, 1000),
                'step_name', pg_catalog.to_jsonb(v_step_name)
            );
            IF NOT cordis.emit_step_claimed(
                p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
            ) THEN
                RETURN 'lost_claim';
            END IF;
            RETURN 'fail';
        END;

        IF v_decision IS NULL
           OR pg_catalog.jsonb_typeof(v_decision) IS DISTINCT FROM 'object' THEN
            v_err := pg_catalog.jsonb_build_object(
                'code', 'P05_LLM_INVOCATION_FAILED',
                'details', pg_catalog.jsonb_build_object(
                    'provider_key', v_provider_key,
                    'reason', 'non_object_response'
                ),
                'message', 'invoke_llm must return a JSON object',
                'step_name', pg_catalog.to_jsonb(v_step_name)
            );
            IF NOT cordis.emit_step_claimed(
                p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
            ) THEN
                RETURN 'lost_claim';
            END IF;
            RETURN 'fail';
        END IF;

        v_llm_payload := pg_catalog.jsonb_build_object(
            'fingerprint', v_fingerprint,
            'model', v_model,
            'protocol', 'cordis.p05.mock.v1',
            'provider_key', v_provider_key,
            'raw', v_decision
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token,
            p_run_id,
            'llm',
            v_llm_payload,
            v_step_name,
            p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
    END IF;

    IF pg_catalog.jsonb_typeof(v_decision -> 'action') IS DISTINCT FROM 'string'
       OR (v_decision ->> 'action') NOT IN ('tool', 'final', 'wait') THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', 'P05_INVALID_LLM_DECISION',
            'details', pg_catalog.jsonb_build_object(
                'action', v_decision -> 'action'
            ),
            'message', 'decision.action must be tool, final, or wait',
            'step_name', pg_catalog.to_jsonb(v_step_name)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;
    v_action := v_decision ->> 'action';

    IF v_action = 'wait' THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', 'P05_WAIT_UNSUPPORTED',
            'details', '{}'::jsonb,
            'message', 'wait is not supported in P05',
            'step_name', pg_catalog.to_jsonb(v_step_name)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;

    IF v_action = 'final' THEN
        IF pg_catalog.jsonb_typeof(v_decision -> 'answer') IS DISTINCT FROM 'string' THEN
            v_err := pg_catalog.jsonb_build_object(
                'code', 'P05_INVALID_LLM_DECISION',
                'details', '{}'::jsonb,
                'message', 'final decision requires a string answer',
                'step_name', pg_catalog.to_jsonb(v_step_name)
            );
            IF NOT cordis.emit_step_claimed(
                p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
            ) THEN
                RETURN 'lost_claim';
            END IF;
            RETURN 'fail';
        END IF;
        IF NOT cordis.emit_step_claimed(
            p_claim_token,
            p_run_id,
            'final',
            pg_catalog.jsonb_build_object(
                'answer', v_decision ->> 'answer',
                'source', 'p05.mock'
            ),
            v_step_name,
            p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'complete';
    END IF;

    IF pg_catalog.jsonb_typeof(v_decision -> 'tool_name') IS DISTINCT FROM 'string'
       OR (v_decision ->> 'tool_name') IS DISTINCT FROM 'mock.observe' THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', 'P05_INVALID_LLM_DECISION',
            'details', pg_catalog.jsonb_build_object(
                'tool_name', v_decision -> 'tool_name'
            ),
            'message', 'P05 supports only mock.observe',
            'step_name', pg_catalog.to_jsonb(v_step_name)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;
    IF v_decision ? 'arguments' THEN
        IF pg_catalog.jsonb_typeof(v_decision -> 'arguments') IS DISTINCT FROM 'object' THEN
            v_err := pg_catalog.jsonb_build_object(
                'code', 'P05_INVALID_LLM_DECISION',
                'details', '{}'::jsonb,
                'message', 'tool arguments must be a JSON object',
                'step_name', pg_catalog.to_jsonb(v_step_name)
            );
            IF NOT cordis.emit_step_claimed(
                p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
            ) THEN
                RETURN 'lost_claim';
            END IF;
            RETURN 'fail';
        END IF;
        v_args := v_decision -> 'arguments';
    ELSE
        v_args := '{}'::jsonb;
    END IF;

    v_obs_root := v_payload #> '{mock_tools,observations}';
    IF pg_catalog.jsonb_typeof(v_obs_root) IS DISTINCT FROM 'object'
       OR NOT (v_obs_root ? v_step_name) THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', 'P05_MOCK_TOOL_OBSERVATION_MISSING',
            'details', pg_catalog.jsonb_build_object(
                'step_name', v_step_name
            ),
            'message', 'mock tool observation for step is missing',
            'step_name', pg_catalog.to_jsonb(v_step_name)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;
    v_obs := v_obs_root -> v_step_name;

    IF NOT cordis.emit_step_claimed(
        p_claim_token,
        p_run_id,
        'tool',
        pg_catalog.jsonb_build_object(
            'arguments', v_args,
            'mock', true,
            'observation', v_obs,
            'tool_name', 'mock.observe'
        ),
        v_step_name,
        p_extend_seconds
    ) THEN
        RETURN 'lost_claim';
    END IF;

    SELECT count(*)::integer
      INTO v_steps_used
      FROM cordis.agent_steps AS s
     WHERE s.run_id = p_run_id
       AND s.kind = 'llm';
    IF v_steps_used >= v_max_steps THEN
        v_err := pg_catalog.jsonb_build_object(
            'code', 'P05_MAX_STEPS_EXCEEDED',
            'details', pg_catalog.jsonb_build_object(
                'max_steps', v_max_steps,
                'step_name', v_step_name,
                'steps_used', v_steps_used
            ),
            'message', 'committed LLM count reached max_steps',
            'step_name', pg_catalog.to_jsonb(v_step_name)
        );
        IF NOT cordis.emit_step_claimed(
            p_claim_token, p_run_id, 'error', v_err, v_step_name, p_extend_seconds
        ) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'fail';
    END IF;

    RETURN 'yield';
END;
$p05$;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p05'::text;
$$;
