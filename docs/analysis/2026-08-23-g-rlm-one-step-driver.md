# G — `rlm_loop` one-step driver sketch

Date: 2026-08-23 · Series: A→I · Status: **research SQL, not product.** Scratch 9/9 remains the proof. Sleep/event/retry tables closed as kernel (D4) but **not** implemented here. Do not promote this file or `scratch/yield_walkthrough/` to ABI. Snapshot: `2026-08-23-i-architecture-snapshot.md`.

Inherits F and oracle Q1 D / Q2 A+B / Q3 C / Q4 C.

---

## 1. Mapping from today

| Today | One-step sketch |
|---|---|
| `rlm_loop(run_id)` — pins session until `final`/`error` | `rlm_step_once(run_id, claim_token)` — at most one `s-N` |
| `agent_run_rlm` — INSERT run then `rlm_loop` | INSERT run + INSERT `jobs` PENDING; return `run_id` |
| `h_rlm_run` — calls `agent_run_rlm`, then `UPDATE jobs DONE` using `ORDER BY created_at DESC` | `h_rlm_continue` — assumes worker already claimed; one `rlm_step_once`; returns outcome, does **not** mark DONE unless `complete` |
| `worker()` — claim job, run **entire** handler | `worker_step()` — reap stale, claim, handler **one step**, then `yield` / `wait` / `complete` / `fail` |
| `rlm_spawn` → nested `rlm_loop(child)` | sync if under policy; else enqueue child jobs row and return (F §6) |
| `emit_step` — unfenced INSERT | `emit_step_claimed` — no-op / raise if token lost |

The old `rlm_loop` can remain as a **compatibility wrapper** that loops `rlm_step_once` **only in tests that opt into session-pinning**. Production path is worker × one-step.

---

## 2. Outcomes

```sql
-- Illustrative; not a migration.
DO $$ BEGIN
  CREATE TYPE rlm_step_outcome AS ENUM (
    'yield',       -- step finished; jobs → PENDING
    'complete',    -- final_answer accepted
    'fail',        -- error / max_steps
    'wait',        -- await-user / await-event (registration already durable)
    'lost_claim'   -- token fenced; caller must stop without appending
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

---

## 3. Claim fence (jobs is authoritative)

Column names match F §2.2; **DDL is contract, not shipped**.

```sql
-- Fence: 0 rows means lost ownership. Must run in the same transaction as emit.
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
```

If `emit_step_claimed` returns false, `rlm_step_once` returns `lost_claim` and **must not** touch `rlm_vars` further.

---

## 4. Step identity and Q2 skip

```sql
-- Attempt-independent: count of llm-bearing steps already in the log.
CREATE OR REPLACE FUNCTION rlm_next_step_name(p_run_id text)
RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT 's-' || (1 + COUNT(*) FILTER (WHERE kind = 'llm'))::text
    FROM agent_steps
   WHERE run_id = p_run_id
$$;

-- Q2 B: reuse raw if this step already has an llm event.
CREATE OR REPLACE FUNCTION rlm_llm_checkpoint(p_run_id text, p_step_name text)
RETURNS jsonb  -- {raw, fingerprint, provider_key} or NULL
LANGUAGE sql STABLE AS $$
  SELECT payload
    FROM agent_steps
   WHERE run_id = p_run_id
     AND kind = 'llm'
     AND payload->>'step_name' = p_step_name
   ORDER BY seq
   LIMIT 1
$$;
```

Provider key (Q2 A): `H(run_id, step_name)` — **not** attempt, not fingerprint. Fingerprint covers messages+model+tools; mismatch against a stored checkpoint is a protocol error, not a new step.

`http_call_llm` today has no `Idempotency-Key` header (`v2/pg_agent_functional.sql:231–240`). The sketch calls a **notional** `http_call_llm_idempotent(p_messages, p_key)` wrapping the same POST. Until that exists, A is a hole; B still works once the `llm` row is in the log.

---

## 5. `rlm_step_once` — body of today’s `WHILE` iteration

This is the current loop body (`:429–494`) **once**, plus F’s durability seam (write `llm` before tools).

```sql
CREATE OR REPLACE FUNCTION rlm_step_once(
  p_run_id text,
  p_token  uuid
)
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

  -- Already done? Idempotent complete.
  IF EXISTS (
       SELECT 1 FROM agent_steps
        WHERE run_id = p_run_id AND kind = 'final'
     ) THEN
    RETURN 'complete';
  END IF;

  v_max    := COALESCE(r.max_steps, 10);
  v_da     := COALESCE(r.paradigm, 'rlm') = 'data_analysis';
  v_has_ctx := EXISTS (SELECT 1 FROM rlm_vars WHERE run_id = p_run_id AND name = 'context');
  SELECT COUNT(*) FILTER (WHERE kind = 'llm') INTO v_n_llm
    FROM agent_steps WHERE run_id = p_run_id;
  IF v_n_llm >= v_max THEN
    PERFORM emit_step_claimed(p_token, p_run_id, 'error',
            jsonb_build_object('message', '达到最大步数'));
    RETURN 'fail';
  END IF;

  -- data_analysis latch: any successful tool observation already in the log
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

  SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                            ORDER BY seq), '[]'::jsonb)
    INTO v_steps FROM agent_steps WHERE run_id = p_run_id;
  v_msgs := fold_rlm_messages(v_system, v_user, v_steps);

  v_step := rlm_next_step_name(p_run_id);
  v_ckpt := rlm_llm_checkpoint(p_run_id, v_step);
  -- fingerprint: research stub; production would canonicalize v_msgs+model+tools
  v_fp   := md5(v_msgs::text);
  v_key  := md5(p_run_id || '/' || v_step);  -- Q2 A: H(run_id, step_name)

  IF v_ckpt IS NOT NULL THEN
    IF v_ckpt->>'fingerprint' IS NOT NULL
       AND v_ckpt->>'fingerprint' <> v_fp THEN
      PERFORM emit_step_claimed(p_token, p_run_id, 'error',
              jsonb_build_object('message', 'step fingerprint mismatch',
                                 'step_name', v_step));
      RETURN 'fail';
    END IF;
    v_raw := v_ckpt->>'raw';          -- Q2 B: skip HTTP
  ELSE
    IF NOT heartbeat_claim(p_token) THEN
      RETURN 'lost_claim';
    END IF;
    BEGIN
      -- NOTIONAL: today's http_call_llm has no key argument.
      v_raw := sql_retry('http_call_llm(jsonb)'::regprocedure, v_msgs, 2) ->> 'raw';
    EXCEPTION WHEN OTHERS THEN
      PERFORM emit_step_claimed(p_token, p_run_id, 'error',
              jsonb_build_object('message', 'LLM 调用失败: '||SQLERRM,
                                 'step_name', v_step, 'provider_key', v_key));
      RETURN 'fail';
    END;
    -- Durability seam (F §4): llm event BEFORE tools.
    IF NOT emit_step_claimed(p_token, p_run_id, 'llm',
            jsonb_build_object('raw', v_raw, 'step_name', v_step,
                               'fingerprint', v_fp, 'provider_key', v_key)) THEN
      RETURN 'lost_claim';
    END IF;
  END IF;

  BEGIN
    v_dec := parse_rlm_output(v_raw);
  EXCEPTION WHEN OTHERS THEN
    PERFORM emit_step_claimed(p_token, p_run_id, 'error',
            jsonb_build_object('message', 'LLM 返回非法 JSON: '||left(v_raw,300),
                               'step_name', v_step));
    RETURN 'fail';
  END;

  -- If we skipped HTTP, thought/code may already be on the llm row; still parse.

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
        'error', '必须先成功执行至少一条 SELECT 才能 final_answer',
        'Type', 'PROTOCOL', 'Phase', 'Finalization',
        'Problem', '尚未成功查库',
        'Solution', '先 SELECT information_schema 或业务表，再作答。');
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
    -- Resume path: llm present, tool absent → re-enter here (F §5).
    PERFORM set_config('rlm.run_id', p_run_id, false);

    -- Spawn policy hook (F §6). Detect rlm_spawn/rlm_map in the SQL.
    -- Research stub: if over threshold, rlm_spawn_enqueue instead of rlm_eval.
    v_spawn := rlm_maybe_async_spawn(p_run_id, p_token, v_dec.code);
    IF v_spawn IS NOT NULL THEN
      -- Child jobs row inserted; parent observation recorded inside helper.
      RETURN CASE WHEN v_spawn->>'mode' = 'wait_child' THEN 'wait' ELSE 'yield' END;
    END IF;

    v_obs := rlm_eval(p_run_id, v_dec.code, COALESCE(r.max_rows, 50));
  END IF;

  IF v_da THEN
    v_obs := da_wrap_obs(v_obs);
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
```

`rlm_maybe_async_spawn` is a stub: parse whether `code` calls `rlm_spawn`/`rlm_map`; if depth/cost over policy, INSERT child `agent_runs` + `jobs` PENDING, `emit_step_claimed` `spawn/start`, do **not** call `rlm_loop(child)`. Under policy, today’s synchronous `rlm_spawn` remains, still pinning **this** claim for a bounded subtree.

Await-user: if `code` (or a future tool) means wait, call F `wait()` after `run/await` is durable and return `'wait'`. Not expanded here (placement open).

---

## 6. Worker: one claim, one step, then yield

Today `h_rlm_run` runs the whole agent then `UPDATE jobs … ORDER BY created_at DESC` (`:805–818`) — race-prone, same family as `codeact_spawn`.

```sql
CREATE OR REPLACE FUNCTION h_rlm_continue(p_job jobs)
RETURNS void
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_run   text := p_job.run_id;
  v_token uuid := p_job.claim_token;  -- worker stuffed this after claim
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
             claim_token = NULL
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
      NULL; -- fenced; do not mutate jobs
  END CASE;
END;
$$;
COMMENT ON FUNCTION h_rlm_continue(jobs) IS '{"job_handler":"rlm_continue"}';
```

```sql
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
  -- Reap (F §8)
  UPDATE jobs
     SET status = 'PENDING',
         available_at = clock_timestamp(),
         claim_token = NULL,
         claimed_by = NULL,
         claim_expires_at = NULL
   WHERE status = 'RUNNING'
     AND claim_expires_at IS NOT NULL
     AND claim_expires_at <= clock_timestamp();
  -- (Also emit_step run/claim_timeout on the fenced run_id — omitted for brevity.)

  SELECT * INTO v_job FROM jobs
   WHERE status = 'PENDING'
     AND COALESCE(available_at, '-infinity'::timestamptz) <= clock_timestamp()
   ORDER BY priority DESC, job_id
   FOR UPDATE SKIP LOCKED
   LIMIT 1;
  IF NOT FOUND THEN
    RETURN format('Worker %s: 队列已空', p_worker_id);
  END IF;

  UPDATE jobs
     SET status = 'RUNNING',
         worker_id = p_worker_id,
         claimed_by = p_worker_id,
         claim_token = v_token,
         claim_expires_at = clock_timestamp() + make_interval(secs => p_lease_s)
   WHERE job_id = v_job.job_id
  RETURNING * INTO v_job;

  SELECT fn INTO v_fn FROM handlers WHERE job_type = v_job.job_type;
  IF v_fn IS NULL THEN
    UPDATE jobs SET status = 'ERROR', error_msg = '未注册 job_type',
                    completed_at = clock_timestamp()
     WHERE job_id = v_job.job_id AND claim_token = v_token;
    RETURN 'error';
  END IF;

  EXECUTE format('SELECT %s($1)', v_fn) USING v_job;
  RETURN format('Worker %s: job %s stepped', p_worker_id, v_job.job_id);
END;
$$;
```

Enqueue a new RLM (replaces `agent_run_rlm`’s inner `rlm_loop`):

```sql
-- Returns run_id; does not run the loop.
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
```

Host worker: same `claim` SQL, then either call `rlm_step_once` over SQL or replay the same fold/LLM/tool/checkpoint verbs in-process writing the same `agent_steps`.

---

## 7. Compatibility wrapper (tests only)

```sql
-- Pins the session again. Not the production path.
CREATE OR REPLACE FUNCTION rlm_loop(p_run_id text)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_token uuid;
  v_out   rlm_step_outcome;
  v_job   bigint;
BEGIN
  -- Would mint a fake claim on a jobs row for this run — details omitted.
  LOOP
    v_out := rlm_step_once(p_run_id, v_token);
    EXIT WHEN v_out IN ('complete', 'fail', 'lost_claim', 'wait');
    -- 'yield' → immediately next step in the same session (opt-in pin)
  END LOOP;
  RETURN (SELECT payload->>'answer' FROM agent_steps
           WHERE run_id = p_run_id AND kind = 'final'
           ORDER BY seq DESC LIMIT 1);
END;
$$;
```

---

## 8. Walk-through: three steps, three claims

1. `rlm_enqueue('有多少张表？')` → `jobs` PENDING.
2. `worker_step()` claims, `h_rlm_continue` → `rlm_step_once` → `llm s-1` + `tool` (SELECT) → `yield` → jobs PENDING.
3. Another `worker_step()` (maybe another backend) claims, fold sees `s-1`, next `s-2`, skip HTTP if `s-2` llm exists else call, tools, yield.
4. Third claim: model returns `final_answer`, `complete`, jobs DONE.
5. If worker dies after HTTP but before `llm` row: next claim, Q2 A same key (once `http_call_llm_idempotent` exists); if `llm` exists without `tool`, skip HTTP, re-`rlm_eval`.

TEMP VIEW from `plugin_temp_views.sql` does **not** survive step 2→3 (F §5). data_analysis workbench across yields is still an open redesign.

---

## 9. Intentionally not in this SQL

- Real `ALTER TABLE jobs ADD claim_token …` applied to the repo
- `http_call_llm` header change
- Wait-registration table (Q4)
- Numeric spawn threshold
- `agent_run_hybrid` WHILE (same surgery, separate pass)
- Fencing `run/claim_timeout` log events on reap

---

## 10. Scratch walkthrough (2026-08-23)

Ran on isolated DB `yield_scratch` (pgembed; not `da_agent`):
`scratch/yield_walkthrough/run.py` → **9/9 PASS**.
Three claims, three tokens, kinds `llm,tool,llm,tool,llm,final`, names `s-1,s-1,s-2,s-2,s-3,s-3`, jobs `DONE`.
See `scratch/yield_walkthrough/REPORT.md`.

Next: hybrid WHILE surgery, or claim-timeout fencing, still not TE1 freeze.
