-- Scratch-only yield driver. Do not apply to da_agent.
-- Requires v2 pg_agent_functional.sql + pg_agent_rlm.sql already loaded.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claim_token uuid;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_by text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claim_expires_at timestamptz;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT '-infinity'::timestamptz;

CREATE TABLE IF NOT EXISTS yield_claim_audit (
    id          serial PRIMARY KEY,
    job_id      bigint,
    run_id      text,
    claim_token uuid,
    worker_id   text,
    claimed_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);

DO $$ BEGIN
    CREATE TYPE rlm_step_outcome AS ENUM (
        'yield', 'complete', 'fail', 'wait', 'lost_claim'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION claim_is_live(p_token uuid)
RETURNS boolean
LANGUAGE sql VOLATILE AS $$
    SELECT EXISTS (
        SELECT 1 FROM jobs
         WHERE claim_token = p_token
           AND status = 'RUNNING'
           AND claim_expires_at > clock_timestamp()
    );
$$;

CREATE OR REPLACE FUNCTION heartbeat_claim(p_token uuid, p_extend_seconds int DEFAULT 90)
RETURNS boolean
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    UPDATE jobs
       SET claim_expires_at = clock_timestamp() + make_interval(secs => p_extend_seconds)
     WHERE claim_token = p_token
       AND status = 'RUNNING'
       AND claim_expires_at > clock_timestamp();
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION emit_step_claimed(
    p_token   uuid,
    p_run_id  text,
    p_kind    text,
    p_payload jsonb
)
RETURNS boolean
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    IF NOT claim_is_live(p_token) THEN
        RETURN false;
    END IF;
    INSERT INTO agent_steps (run_id, kind, payload)
    VALUES (p_run_id, p_kind, p_payload);
    PERFORM heartbeat_claim(p_token);
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION rlm_next_step_name(p_run_id text)
RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT 's-' || (1 + COUNT(*) FILTER (WHERE kind = 'llm'))::text
      FROM agent_steps
     WHERE run_id = p_run_id
$$;

CREATE OR REPLACE FUNCTION rlm_llm_checkpoint(p_run_id text, p_step_name text)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT payload
      FROM agent_steps
     WHERE run_id = p_run_id
       AND kind = 'llm'
       AND payload->>'step_name' = p_step_name
     ORDER BY seq
     LIMIT 1
$$;

CREATE OR REPLACE FUNCTION rlm_maybe_async_spawn(
    p_run_id text, p_token uuid, p_code text
)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT NULL::jsonb
$$;

CREATE OR REPLACE FUNCTION rlm_step_once(p_run_id text, p_token uuid)
RETURNS rlm_step_outcome
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    r          record;
    v_dec      rlm_decision;
    v_raw      text;
    v_msgs     jsonb;
    v_system   text;
    v_user     text;
    v_steps    jsonb;
    v_obs      jsonb;
    v_has_ctx  boolean;
    v_da       boolean;
    v_got_q    boolean;
    v_step     text;
    v_ckpt     jsonb;
    v_fp       text;
    v_key      text;
    v_n_llm    int;
    v_max      int;
    v_spawn    jsonb;
BEGIN
    IF NOT claim_is_live(p_token) THEN
        RETURN 'lost_claim';
    END IF;

    SELECT * INTO r FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        PERFORM emit_step_claimed(p_token, p_run_id, 'error',
                jsonb_build_object('message', 'run_id 不存在'));
        RETURN 'fail';
    END IF;

    IF EXISTS (
           SELECT 1 FROM agent_steps
            WHERE run_id = p_run_id AND kind = 'final'
       ) THEN
        RETURN 'complete';
    END IF;

    v_max := COALESCE(r.max_steps, 10);
    v_da := COALESCE(r.paradigm, 'rlm') = 'data_analysis';
    v_has_ctx := EXISTS (
        SELECT 1 FROM rlm_vars WHERE run_id = p_run_id AND name = 'context');
    SELECT COUNT(*) FILTER (WHERE kind = 'llm') INTO v_n_llm
      FROM agent_steps WHERE run_id = p_run_id;
    IF v_n_llm >= v_max THEN
        PERFORM emit_step_claimed(p_token, p_run_id, 'error',
                jsonb_build_object('message', '达到最大步数'));
        RETURN 'fail';
    END IF;

    v_got_q := EXISTS (
        SELECT 1 FROM agent_steps
         WHERE run_id = p_run_id AND kind = 'tool'
           AND (payload->'observation'->>'success') = 'true'
    );

    IF v_da THEN
        v_system := da_system_prompt(p_run_id);
    ELSE
        v_system := make_rlm_prompt(COALESCE(r.depth,0), COALESCE(r.max_depth,1),
                                   COALESCE(r.max_rows,50), v_has_ctx);
    END IF;
    v_user := make_rlm_user(r.question, v_has_ctx);

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'seq',seq,'kind',kind,'payload',payload) ORDER BY seq), '[]'::jsonb)
      INTO v_steps FROM agent_steps WHERE run_id = p_run_id;
    v_msgs := fold_rlm_messages(v_system, v_user, v_steps);

    v_step := rlm_next_step_name(p_run_id);
    v_ckpt := rlm_llm_checkpoint(p_run_id, v_step);
    v_fp   := md5(v_msgs::text);
    v_key  := md5(p_run_id || '/' || v_step);

    IF v_ckpt IS NOT NULL THEN
        IF v_ckpt->>'fingerprint' IS NOT NULL
           AND v_ckpt->>'fingerprint' <> v_fp THEN
            PERFORM emit_step_claimed(p_token, p_run_id, 'error',
                    jsonb_build_object('message', 'step fingerprint mismatch',
                                       'step_name', v_step));
            RETURN 'fail';
        END IF;
        v_raw := v_ckpt->>'raw';
    ELSE
        IF NOT heartbeat_claim(p_token) THEN
            RETURN 'lost_claim';
        END IF;
        BEGIN
            v_raw := sql_retry('http_call_llm(jsonb)'::regprocedure, v_msgs, 2)
                     ->> 'raw';
        EXCEPTION WHEN OTHERS THEN
            PERFORM emit_step_claimed(p_token, p_run_id, 'error',
                    jsonb_build_object('message', 'LLM 调用失败: '||SQLERRM,
                                       'step_name', v_step,
                                       'provider_key', v_key));
            RETURN 'fail';
        END;
        IF NOT emit_step_claimed(p_token, p_run_id, 'llm',
                jsonb_build_object('raw', v_raw,
                                   'thought', NULL,
                                   'code', NULL,
                                   'step_name', v_step,
                                   'fingerprint', v_fp,
                                   'provider_key', v_key)) THEN
            RETURN 'lost_claim';
        END IF;
    END IF;

    BEGIN
        v_dec := parse_rlm_output(v_raw);
    EXCEPTION WHEN OTHERS THEN
        PERFORM emit_step_claimed(p_token, p_run_id, 'error',
                jsonb_build_object('message',
                    'LLM 返回非法 JSON: '||left(v_raw,300),
                    'step_name', v_step));
        RETURN 'fail';
    END;

    IF v_dec.final_answer IS NOT NULL AND v_dec.code IS NULL THEN
        IF (NOT v_da) OR v_got_q THEN
            IF NOT emit_step_claimed(p_token, p_run_id, 'final',
                    jsonb_build_object('answer', v_dec.final_answer,
                                       'step_name', v_step)) THEN
                RETURN 'lost_claim';
            END IF;
            RETURN 'complete';
        END IF;
        v_obs := jsonb_build_object(
            'success', false,
            'error', '必须先成功执行至少一条 SELECT 才能 final_answer');
        PERFORM set_config('rlm.run_id', p_run_id, false);
        PERFORM env_set_json('last_obs', v_obs);
        IF NOT emit_step_claimed(p_token, p_run_id, 'tool',
                jsonb_build_object('code', NULL,
                                   'observation', rlm_clip(v_obs, 4000),
                                   'step_name', v_step)) THEN
            RETURN 'lost_claim';
        END IF;
        RETURN 'yield';
    END IF;

    IF v_dec.code IS NULL THEN
        v_obs := jsonb_build_object('success', false,
                                   'error', '必须提供 code 或 final_answer');
    ELSE
        PERFORM set_config('rlm.run_id', p_run_id, false);
        v_spawn := rlm_maybe_async_spawn(p_run_id, p_token, v_dec.code);
        IF v_spawn IS NOT NULL THEN
            RETURN CASE WHEN v_spawn->>'mode' = 'wait_child'
                        THEN 'wait' ELSE 'yield' END;
        END IF;
        v_obs := rlm_eval(p_run_id, v_dec.code, COALESCE(r.max_rows, 50));
    END IF;

    PERFORM set_config('rlm.run_id', p_run_id, false);
    PERFORM env_set_json('last_obs', v_obs);

    IF NOT emit_step_claimed(p_token, p_run_id, 'tool',
            jsonb_build_object('code', v_dec.code,
                               'observation', rlm_clip(v_obs, 4000),
                               'step_name', v_step)) THEN
        RETURN 'lost_claim';
    END IF;

    RETURN 'yield';
END;
$$;

CREATE OR REPLACE FUNCTION h_rlm_continue(p_job jobs)
RETURNS void
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run   text := p_job.run_id;
    v_token uuid := p_job.claim_token;
    v_out   rlm_step_outcome;
BEGIN
    IF v_run IS NULL OR v_token IS NULL THEN
        RAISE EXCEPTION 'h_rlm_continue requires jobs.run_id and claim_token';
    END IF;

    v_out := rlm_step_once(v_run, v_token);

    CASE v_out
        WHEN 'yield' THEN
            UPDATE jobs
               SET status = 'PENDING',
                   available_at = clock_timestamp(),
                   claim_token = NULL,
                   claimed_by = NULL,
                   claim_expires_at = NULL
             WHERE job_id = p_job.job_id
               AND claim_token = v_token;
        WHEN 'complete' THEN
            UPDATE jobs
               SET status = 'DONE',
                   result = (SELECT payload FROM agent_steps
                              WHERE run_id = v_run AND kind = 'final'
                              ORDER BY seq DESC LIMIT 1),
                   completed_at = clock_timestamp(),
                   claim_token = NULL,
                   claimed_by = NULL,
                   claim_expires_at = NULL
             WHERE job_id = p_job.job_id
               AND claim_token = v_token;
        WHEN 'fail' THEN
            UPDATE jobs
               SET status = 'ERROR',
                   error_msg = 'rlm_step_once fail',
                   completed_at = clock_timestamp(),
                   claim_token = NULL
             WHERE job_id = p_job.job_id
               AND claim_token = v_token;
        WHEN 'wait' THEN
            UPDATE jobs
               SET status = 'WAITING',
                   claim_token = NULL,
                   claimed_by = NULL,
                   claim_expires_at = NULL
             WHERE job_id = p_job.job_id
               AND claim_token = v_token;
        WHEN 'lost_claim' THEN
            NULL;
    END CASE;
END;
$$;
COMMENT ON FUNCTION h_rlm_continue(jobs) IS '{"job_handler":"rlm_continue"}';

CREATE OR REPLACE FUNCTION worker_step(
    p_worker_id text DEFAULT 'worker-' || gen_random_uuid()::text,
    p_lease_s   int  DEFAULT 90
)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_job   jobs;
    v_fn    regproc;
    v_token uuid := gen_random_uuid();
BEGIN
    UPDATE jobs
       SET status = 'PENDING',
           available_at = clock_timestamp(),
           claim_token = NULL,
           claimed_by = NULL,
           claim_expires_at = NULL
     WHERE status = 'RUNNING'
       AND claim_expires_at IS NOT NULL
       AND claim_expires_at <= clock_timestamp();

    SELECT * INTO v_job FROM jobs
     WHERE status = 'PENDING'
       AND COALESCE(available_at, '-infinity'::timestamptz) <= clock_timestamp()
     ORDER BY priority DESC, job_id
     FOR UPDATE SKIP LOCKED
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN format('Worker %s: empty', p_worker_id);
    END IF;

    UPDATE jobs
       SET status = 'RUNNING',
           worker_id = p_worker_id,
           claimed_by = p_worker_id,
           claim_token = v_token,
           claim_expires_at = clock_timestamp() + make_interval(secs => p_lease_s)
     WHERE job_id = v_job.job_id
    RETURNING * INTO v_job;

    INSERT INTO yield_claim_audit (job_id, run_id, claim_token, worker_id)
    VALUES (v_job.job_id, v_job.run_id, v_token, p_worker_id);

    SELECT fn INTO v_fn FROM handlers WHERE job_type = v_job.job_type;
    IF v_fn IS NULL THEN
        UPDATE jobs SET status = 'ERROR', error_msg = 'unregistered job_type',
                        completed_at = clock_timestamp()
         WHERE job_id = v_job.job_id AND claim_token = v_token;
        RETURN 'error: no handler';
    END IF;

    EXECUTE format('SELECT %s($1)', v_fn) USING v_job;
    RETURN format('Worker %s: job %s stepped token=%s',
                  p_worker_id, v_job.job_id, v_token);
END;
$$;

CREATE OR REPLACE FUNCTION rlm_enqueue(
    p_question  text,
    p_context   text DEFAULT NULL,
    p_max_steps int  DEFAULT 10,
    p_max_depth int  DEFAULT 1
)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run text := gen_random_uuid()::text;
BEGIN
    INSERT INTO agent_runs (run_id, question, max_steps, paradigm, depth, max_depth, name)
    VALUES (v_run, p_question, p_max_steps, 'rlm', 0, p_max_depth, 'root');
    PERFORM set_config('rlm.run_id', v_run, false);
    PERFORM env_set_text('question', p_question);
    IF p_context IS NOT NULL AND p_context <> '' THEN
        PERFORM env_set_text('context', p_context);
    END IF;
    INSERT INTO jobs (job_type, payload, status, run_id, available_at)
    VALUES ('rlm_continue', jsonb_build_object('run_id', v_run),
            'PENDING', v_run, clock_timestamp());
    RETURN v_run;
END;
$$;

SELECT refresh_handlers();
