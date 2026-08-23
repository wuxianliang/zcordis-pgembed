# F — Yield-loop protocol sketch

Date: 2026-08-23 · Series: sequential research A→I · Status: **protocol sketch (still not product SQL).** TE1 placement later closed by D4; spawn threshold by D9. Working hypotheses: `2026-08-23-i-architecture-snapshot.md`. Ordering and ownership semantics in this sketch remain the claim protocol.

Inherits A–E and the four oracle verdicts (synthesis CONFIRMED):

| Pin | Source |
|---|---|
| Session log is unique SoT; checkpoints are log events/folds | B, E, Q4 |
| Upgrade existing `jobs`/`worker()`, no second queue | E, Q4 |
| In-DB loop **and** host SDK worker, one claim protocol | E, Q4 |
| **Q1 D:** default yield after a **completed LLM+tools step**; async/yield when spawn depth/cost exceeds policy | oracle-plan `…7f1a8d…` |
| **Q2 A+B:** provider `Idempotency-Key = H(run_id, step_name)` **and** log skip-if-present with request fingerprint. Tools are **not** covered | oracle-plan `…637755…` |
| **Q3 C+constrained B:** emit/await are grant capabilities on `(event_scope_id, event_name)`; prefix is storage | oracle-plan `…357406…` |
| **Q4 C:** freeze one jobs queue + one claim protocol + log-backed checkpoints; leave sleep/event/retry *placement* open | oracle-plan `…63121b…` |

---

## 1. What this sketch is for

Today `rlm_loop` (`v2/pg_agent_rlm.sql:395–499`) is one `WHILE` that pins the Postgres session from first fold to `final`/`error`. `worker()` (`v2/pg_agent_functional.sql:465–493`) claims a `jobs` row for the **entire handler**, with no lease. `rlm_spawn` (`:502–567`) runs the child by calling `rlm_loop` inside the parent transaction.

The sketch replaces that with:

```text
claim → fold log → (maybe skip LLM) → LLM → tools → append checkpoint →
    { continue in-claim | yield | wait | complete | fail }
```

A later worker (SQL or host) must be able to pick the same `run_id` up and not redo completed named steps.

It does **not** decide: SQL catalog vs `CREATE EXTENSION` (A T5); whether wait rows live in `jobs` or a plugin table; habitat/SDK packaging.

---

## 2. Objects

### 2.1 Logical run (identity)

`agent_runs.run_id` is the **logical run identity**. All protocol keys (`step_name`, provider idempotency, grants, event scopes) hang off it.

`agent_steps` (today: `kind ∈ llm|tool|final|error`, PK `(run_id, seq)`) remains the append-only history. New kinds below are **envelope extensions**, not a second log (C TC4 / B TB1(c)).

`run_state()` stays a **fold**. Do not add a stored `agent_runs.status` as SoT. Scheduling needs a *claimable* row; that is the jobs row, not a second history.

### 2.2 Jobs row (claimable work)

One logical queue: existing `jobs`. Upgrade in place (columns below are **contract**, not a migration script):

| Concern | Today | Protocol |
|---|---|---|
| Identity | `job_id` | keep; also `run_id` **NOT NULL** for agent work |
| Handler | `job_type` → `handlers.fn` | keep COMMENT/`job_handler` |
| Schedulability | `status PENDING\|RUNNING\|DONE\|ERROR` | add `WAITING`, `SLEEPING` (names illustrative) |
| Claim | `worker_id` only | add `claim_token`, `claimed_by`, `claim_expires_at`, `attempt` |
| Wake | — | `available_at`; optional `wake_event_scope`, `wake_event_name` |
| Payload | `payload jsonb` | includes `step_cursor` / next `step_name` hint (cache, not SoT) |

**Invariant:** at most **one non-terminal jobs row** per `run_id` (PENDING/RUNNING/WAITING/SLEEPING). Terminal DONE/ERROR rows are history of *claims*, not a second SoT — or they are deleted/archived; the log already has `final`/`error`. Opinion: keep the latest jobs row as the scheduler handle; do not accumulate one job per step (that would be a second queue in spirit).

### 2.3 Step (yield unit — Q1 D)

A **step** is one named unit:

1. Fold prior log into messages (deterministic projection; C TC6 opinion).
2. LLM call (or skip via Q2 B).
3. Parse; if `code`/`tool_calls`, execute tools **in this claim**.
4. Append checkpoint-capable log events.
5. Then either loop (same claim, next step), yield, wait, complete, or fail.

`step_name` is attempt-independent and stable, e.g. `s-{n}` where `n` is the count of completed LLM-bearing steps already in the log (not `attempt`, not worker id). Ronacher’s `iteration#N` is this counter. Spawn children get their **own** `run_id` and their own `s-1…`.

Default boundary is **LLM + its tools**, not per-token and not whole-run. If a tool is itself a spawn that exceeds policy, that tool **must not** finish inside this step — see §6.

### 2.4 Claim (ownership)

**Authoritative claim lives on the jobs row**, keyed by `run_id`. `agent_runs` does not grow a competing owner column (synthesis P1). Mapping:

```text
jobs.run_id  =  agent_runs.run_id     -- 1:1 for live agent work
jobs.claim_token                      -- random; required on every mutating verb
jobs.claimed_by                       -- worker id (SQL backend pid / host worker id)
jobs.claim_expires_at                 -- lease; heartbeat / checkpoint extends it
```

A worker that does not hold the current `claim_token` **must not** `emit_step`. Fencing: `UPDATE … WHERE claim_token = $token AND claim_expires_at > now()`; 0 rows ⇒ lost ownership, stop without appending.

---

## 3. Claim protocol (verbs)

Both loci speak these. Placement of the SQL functions vs host RPCs is open; the **effects on jobs + log** are not.

| Verb | Jobs effect | Log effect | Notes |
|---|---|---|---|
| `claim(run_id, worker_id, lease)` | SKIP LOCKED where status ∈ (PENDING) or (WAITING/SLEEPING and `available_at ≤ now()`); set RUNNING, token, expiry | none | At most one winner. Expired RUNNING is failed-claim, then reaped (§8). |
| `heartbeat(token, extend)` | extend `claim_expires_at` | none | LLM in flight. |
| `checkpoint(token, events[])` | extend lease; optional `payload.step_cursor` | **append** events (atomic with token check) | Only owner appends. |
| `yield(token)` | status PENDING, `available_at = now()`, clear token | optional `run/yield` | Same worker or another may claim next. |
| `wait(token, event_scope, event_name, deadline)` | status WAITING, store wake keys, clear token **after** log+registration durable | `run/await` | Q3. Placement of wait index open. |
| `sleep(token, until)` | status SLEEPING, `available_at = until`, clear token | `run/sleep` | Placement of scheduler open (`pg_cron` vs jobs poll). |
| `complete(token, result)` | DONE | `final` | |
| `fail(token, reason)` | ERROR or requeue per retry policy | `error` | Retry **policy** placement open; if requeued, new attempt, **same** `step_name` for incomplete step (Q2). |
| `release_stale(run_id)` | RUNNING ∧ expiry ≤ now() → fail-claim / requeue | `run/claim_timeout` | Absurd `$ClaimTimeout`. |

`checkpoint` then `yield` in one transaction is the normal end-of-step path when the worker does not immediately start `s-(n+1)` (host workers should yield each step; an in-DB worker *may* hold the claim across several steps in one session **only if** lease remains valid — opinion: in-DB should still yield per step so dual locus stays honest).

---

## 4. Normal iteration (happy path)

```text
1. claim
2. fold agent_steps → messages, completed step_names, run_state
3. if fold shows `final` → complete (idempotent)
4. next step_name := s-{n+1}
5. if log already has committed checkpoint for this step_name
      with matching request fingerprint → reuse payload; skip HTTP (Q2 B)
   else
      fingerprint := H(canonical messages + model + tools + params)
      provider_key := H(run_id, step_name)   -- NOT attempt, NOT fingerprint
      heartbeat
      http_call_llm(..., Idempotency-Key=provider_key)
      sql_retry MUST reuse the same key (Q2 residual 4)
6. parse; emit_step llm {raw, thought, code, step_name, fingerprint, provider_key}
7. if final_answer and protocol latch ok → emit final; complete
8. if code/tools:
      execute tools in this claim
      emit_step tool {code, observation, step_name}
      NOTE: tool execution is NOT covered by Q2. See §5.
9. checkpoint (steps 6–8 in one append batch preferred)
10. if max_steps reached → fail
    else yield (or immediately loop to 2 with same token if in-DB and lease ok)
```

Step 6 **before** tools: if the process dies after LLM success but before tool events, Q2 A should return the same completion on retry; Q2 B will not skip until the llm event is logged. **Order of durability:** write `llm` event (and fingerprint) **before** starting tools when possible, so a retry does not re-call the provider. Opinion: split the checkpoint into `llm` then `tool`, still one step_name; skip HTTP if `llm` exists, re-run tools unless a tool idempotency contract says otherwise (§5).

This is the Q1 “completed LLM+tools” unit with an internal durability seam for the HTTP call.

---

## 5. Tool overlap (explicit residual)

Q1’s yield unit includes tools; Q2 does **not** make tools exactly-once. Under lease expiry mid-tool:

| Tool class | Protocol (opinion, not freeze) |
|---|---|
| Read-only SQL (`capability=read_only` workbench) | Re-run on retry |
| Session TEMP VIEW mutation (`temp_view_mutation`) | **Cannot** assume same PG session after yield. D already: run scope ≠ backend session. These tools are illegal across a yield unless TEMP is replaced by run-scoped workspace (C TC3). **Opinion:** yield **invalidates** `pg_temp`; workbench session_scope must be redesigned or such tools must not span yields |
| HTTP / paid / emit-event | Need their own idempotency key or “non-retryable” flag; unspecified here |
| Spawn (§6) | Not a normal tool; policy branch |

A worker that loses the token **mid-tool** must stop; the next claim sees `llm` present, `tool` absent, and re-enters §4 step 8.

---

## 6. Spawn policy (Q1 D overlay)

Today `rlm_spawn` inserts child, binds GUC, `rlm_loop(child)` in-process (`:540–553`), caps depth≥4 / 16 children / `max_steps=LEAST(parent,6)`.

**Shallow / cheap (sync, same claim — allowed):** child finishes inside the parent’s current step. Parent log gets `spawn/start` + `spawn/end` with `child_run_id` (C/D P4; no `created_at DESC`). Child has its own `run_id` and steps. Parent session stays pinned for the child — this is the remaining pin, **bounded** by policy.

**Over threshold (async, must yield the child out of this step):**

```text
checkpoint spawn/start {child_run_id, prompt, grants, policy}
INSERT jobs (job_type=agent_continue, run_id=child, PENDING)
-- do not call rlm_loop(child) here
emit tool observation {spawned: child_run_id, mode: async}
yield parent   -- or continue parent step only if policy says parent may proceed
```

Child becomes a **separate claimable jobs row**. Parent must not assume the child’s `final` in the same step. Waiting for the child is `wait` on a scoped event `spawn.completed:{child_run_id}` **or** a fold of the child’s log — event placement open; **lineage in the parent log is not**.

Threshold numbers stay paradigm policy (C TC2), not this protocol. The protocol only requires: **unbounded sync spawn is illegal.**

`codeact_spawn`’s `ORDER BY created_at DESC LIMIT 1` (`v2/pg_agent_rlm.sql:688–692`) is replaced by returning `child_run_id` from the insert. Always.

---

## 7. Await-user / await-event (Q3 semantics, placement open)

Does **not** choose `w_`/`e_` tables vs jobs columns vs plugin. Does choose **order**:

```text
1. Active slice must have event.await on (event_scope_id, event_name)
2. If event already committed (first-emit-wins) → resolve immediately, no yield
3. Append run/await {await_id, event_scope_id, event_name, deadline, ui metadata}
4. Persist wait registration (WHEREVER it lives) in the SAME transaction
5. wait() verb: jobs → WAITING, clear token
6. COMMIT; session/lease gone
```

Emit path (UI / callback, **not** the waiting worker):

```text
1. event.emit on the exact resource (opaque scope for one-shot user channels)
2. First-emit-wins uniqueness on (event_scope_id, event_name)
3. Append event/emit {payload} then run/wake {await_id, source_seq} — emitter does not write run/wake; kernel does
4. jobs: WAITING → PENDING, available_at=now()
```

Resume: `claim` → fold sees `run/await`+`run/wake` → continuation gets payload or timeout. Unauthorized lookup must not be an existence oracle.

Sleep is the same shape with `available_at = until` and no emitter; **who ticks the clock** (`pg_cron`, worker poll) is placement.

---

## 8. Stale workers and claim timeout

Absurd: expired claim → `fail_run` `$ClaimTimeout` → new attempt, checkpoints reused.

Here:

```text
claim() first reaps: RUNNING ∧ claim_expires_at ≤ now()
  → append run/claim_timeout {old_token, worker}
  → fence old token (any later emit_step with old token affects 0 rows)
  → status PENDING, available_at=now(), new attempt
```

The **logical step_name does not change**. Q2 A+B then skip or replay the in-flight LLM. The old worker, if still alive, fails the token check and **must exit**.

Heartbeat during LLM is mandatory; lease < expected HTTP timeout is a footgun (pg-agent curlopt 90s). Opinion: lease ≥ HTTP timeout + heartbeat slack.

---

## 9. Dual locus

| | In-DB (`worker()` + SQL loop) | Host SDK |
|---|---|---|
| Claim | `SELECT … FOR UPDATE SKIP LOCKED` on `jobs` | same SQL verbs over libpq |
| Fold | `fold_rlm_messages` / registered projection | same SQL fold or equivalent read of `agent_steps` |
| LLM | `http_call_llm` with provider key | host HTTP with **same** key |
| Tools | `rlm_eval` / workbench functions | host tools **or** SQL RPC; grants still apply |
| Checkpoint | `emit_step` under token | same |
| Yield / wait | verbs in §3 | same |

Host must not keep a private in-memory log as SoT (B). Host **may** cache folds. Grants: host presents the run’s slice grants on each claim (D P5/P8); how they are stored on the jobs/run row is open, but claim without grants is illegal for retrieval/tools/events.

In-DB `rlm_loop` as a single function that never calls `yield` is **non-compliant**. The replacement is a function that performs **at most one step** (or a bounded number under a still-valid lease) and returns.

---

## 10. Failure ordering (cheat sheet)

| Crash / race | What the next claim must do |
|---|---|
| Before LLM | start step normally |
| After provider accepted, before `llm` event | Q2 A: same key; then append `llm` |
| After `llm` event, before/during tools | skip HTTP (Q2 B); re-enter tools (§5) |
| After `tool` events, before yield | treat step complete; next `step_name` |
| Lost token mid-step | stop; do not append |
| Two claims of same run | impossible if invariant holds; if broken, token fence + log conflict on `(run_id, step_name, fingerprint)` (Q2) |
| Emit vs timeout | one atomic resolution; loser does not wake twice |
| Await registered, claim not released | illegal; wait() is one transaction with registration |
| Claim released, await not durable | illegal; opposite order |

---

## 11. State machine (scheduler view of jobs)

```text
PENDING  --claim--> RUNNING
RUNNING  --yield--> PENDING
RUNNING  --wait-->  WAITING
RUNNING  --sleep--> SLEEPING
RUNNING  --complete--> DONE
RUNNING  --fail--> ERROR | PENDING (retry policy)
RUNNING  --lease expire--> PENDING  (+ claim_timeout log)
WAITING  --authorized emit/timeout--> PENDING
SLEEPING --available_at--> PENDING
```

Run-level “status” for humans/agents is still `run_state()` over the log (`final` / `error` / in-progress / awaiting). Jobs status is **eligibility to claim**, not history.

---

## 12. What this does not freeze

- TE1 full kernel list (sleep/event/retry as kernel vs plugin)
- A T5 packaging
- Exact `jobs` DDL
- Numeric spawn thresholds and budget pooling vs child slice (D residual)
- Tool idempotency classes beyond the table in §5
- Provider behavior when keys are unsupported (Q2 residual 1)
- TEMP VIEW replacement by run-scoped workspace
- Whether in-DB may chain multiple steps in one claim

---

## 13. Next (if this sketch is accepted)

1. Yield-compliant **one-step** SQL driver replacing the body of `rlm_loop`’s `WHILE` (research SQL or pseudocode in-tree, still not product).
2. `jobs` column-level upgrade note (claim_token, available_at, WAITING).
3. Await-user walk-through against D’s two-project example (grants on the wait channel).
4. Only then revisit TE1 placement for sleep/event/retry.

Until (1) exists, Q4’s “wait for a yield-loop sketch” is satisfied **as protocol**, not as proof the SQL loop can actually yield.
