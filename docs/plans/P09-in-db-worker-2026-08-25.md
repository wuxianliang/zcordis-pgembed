# P09 — In-database worker

Date: 2026-08-25
Status: **ready to implement**
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P09
Depends on: P05, P06 (implemented); P08 and P19 are in the current product tree and constrain dispatch and policy lookup
Parallel with: P10
Contract: one `cordis.jobs` queue; in-database and host workers share P01 claim verbs; one worker invocation executes at most one step; in-database tool execution permits only catalog entries with `locus='in-db'`
Primary deliverable: `sql/0021_p09_in_db_worker.sql`
Critique: `docs/reviews/2026-08-25-p09-plan-critique.md` (P0 none; P1 fixture discipline and P2 nits folded below)
Implementation review: `docs/reviews/2026-08-25-p09-implementation-oracle.md`
SQL marker: `p21`
PL/pgSQL dollar tag: `$p09$`
Plan export: `prompt-exports/oracle-plan-2026-08-25-201110-p09-in-db-worker-pla-5a29.md`

The context_builder export contains two concatenated drafts. This document is the orchestrator integration: **version 2** (export `# P09` at line 1273) is the preservation baseline because it contains the complete W90–W99 verification, named tests, tradeoffs, and risks. Version 1 (export line 118) is the same design; unique v1 details are folded below (fuller synthetic error envelope, 1000-character bound, `P09_INVALID_TOOL_REQUEST`, file-by-file pin notes). Naming conflicts resolved toward v2: `P09_JOB_HANDLER_UNSUPPORTED` (not v1 `P09_JOB_HANDLER_NOT_IN_DB_QUEUE`); machine-readable `config.isolated=false` with description language `legacy_unscoped` (not a second config key).

**Mid-flow lock (2026-08-25, user):** keep `invoke_in_db_tool` in P09; keep wait-as-P03-acknowledgement; register the existing `cordis.step_once` directly as `kernel.step_once` by COMMENT metadata (no wrapper, no special-case). These match decisions 7, 4, and 1.

---

## Summary

P09 adds a targeted scheduler and dispatch layer over the existing kernel rather than refactoring the P05 step body. It introduces a handler-aware `enqueue_job`, a catalog resolver for P09-compatible in-database queue handlers, a claim-to-one-step `worker_step`, and a claim-bound read-only in-database tool invoker that always passes through P08 authorization. The existing `cordis.step_once` is registered directly as the canonical P09 queue handler by COMMENT metadata; it is neither wrapped nor replaced. Each `worker_step` invocation claims at most one `cordis.jobs` row, invokes exactly one handler once, maps the returned outcome through P01/P03 state transitions, and returns. The file is appended as `sql/0021_p09_in_db_worker.sql`, refreshes the existing P06 catalog, and advances the full-tree marker from `p20` to `p21`.

---

## Goal

Ship the first canonical in-database worker path:

```text
enqueue trusted in-db queue handler
    → worker_step claims one PENDING job
    → validate stored paradigm through paradigm_policy()
    → resolve one P06 in-db queue entrypoint
    → invoke that entrypoint exactly once
    → map its outcome through P01/P03 state
    → return without looping
```

The canonical acceptance path is one run enqueued for `kernel.step_once`, processed by three separate `worker_step` calls with outcomes `yield`, `yield`, and `complete`, reproducing the P05 proof (`tests/test_p05_one_step_driver.py:28-54`, `:356-417`):

```text
llm/s-1 → tool/s-1 → llm/s-2 → tool/s-2 → llm/s-3 → final/s-3
```

The first two calls must return the job to `PENDING`; the third must leave the same jobs row `DONE` with `result.answer = 'ok'`. No `run/yield` log events.

P09 also closes the P06 execution handoff for read-only in-database tools:

```text
live claim
    → authorize_tool_dispatch
    → require locus=in-db and invocation=session_select
    → require read_only / replayable / none
    → execute one jsonb → jsonb entrypoint
    → recheck claim
    → return result
```

### Explicit non-goals

P09 does **not**:

- replace, wrap, overload, or rewrite `cordis.step_once`;
- copy SQL from `scratch/yield_walkthrough/` or `docs/analysis/2026-08-23-g-rlm-one-step-driver.md`;
- add a second queue, run table, claim protocol, scheduler loop, or worker daemon;
- execute more than one queue handler per `worker_step` call;
- loop over multiple P05 steps while retaining one claim;
- implement P10 host bindings or SDK code;
- implement P11’s in-db/host alternating-worker proof;
- implement P04 sleep, retry curves, retry exhaustion, or dead-letter behavior;
- call `await_event` on behalf of an executor or invent wait parameters;
- implement P17 spawn or synchronous child runs;
- execute host-locus catalog rows as SQL;
- execute transactional or external tools through the P09 tool helper;
- implement file edits, worktrees, HTTP tools, or any external effect;
- create `rlm_vars`, a real RLM environment, TEMP tables, `pg_temp` state, or session affinity;
- make the legacy P05 mock fold slice-isolated;
- call `fold_slice_messages` and discard its result merely to claim compliance;
- expose `enqueue_job`, `worker_step`, or the P05 queue handler as model tools;
- expose grant-requiring queue handlers through the P09 v1 queue ABI;
- add RLS, roles, privileges, `CREATE EXTENSION`, or transaction-control SQL;
- edit historical numbered SQL files as the release mechanism.

---

## Execution index

P08 used W80–W88. P09 uses W90–W99.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W90 | P09 queue-handler ABI and canonical catalog registration | `_resolve_in_db_queue_handler` accepts only P09-compatible, no-grant, in-db queue handlers; `cordis.step_once` is directly registered as `kernel.step_once` without replacement or wrapper | `sql/0021_p09_in_db_worker.sql` | P05, P06 | Medium |
| W91 | Handler-aware enqueue | `enqueue_job` validates run, paradigm, payload, and handler; inserts one immediately claimable P01 jobs row with a canonical `payload.paradigm` | same | W90, P01, P19 | Medium |
| W92 | Read-only in-db tool execution | `invoke_in_db_tool` requires a live claim, calls P08 authorization, rejects host/queue/effectful rows, dynamically executes one compatible `jsonb → jsonb` entrypoint, and rechecks the claim | same | P01, P06, P08 | Medium |
| W93 | Worker claim and one-handler invocation | `worker_step` polls or targets one run, claims at most one job, revalidates paradigm and handler, invokes the queue entrypoint once, and never loops | same | W90–W91, P01, P05, P19 | Medium |
| W94 | Exhaustive outcome mapping | `yield`, `complete`, `fail`, `wait`, `lost_claim`, NULL, and unknown outputs have exact behavior; valid wait means the handler already completed the P03 wait transaction | same | W93, P02, P03 | Large |
| W95 | Catalog refresh, source version, and SQL documentation | Fresh/replay apply installs the canonical COMMENT row, preserves runtime sources, and reports `p21`; README records all P09 boundaries | `sql/0021_p09_in_db_worker.sql`, `sql/README.md` | W90–W94 | Small |
| W96 | Retarget current-tree assertions | All tests using the complete SQL root expect `0021`/`p21`; deliberately truncated trees retain their historical marker | existing test modules | W95 | Medium |
| W97 | P09 catalog and enqueue tests | New tests prove signatures, canonical metadata, enqueue validation, catalog drift handling, duplicate-run behavior, and source boundaries | `tests/test_p09_in_db_worker.py` | W90–W96 | Medium |
| W98 | P09 worker and tool-dispatch tests | New tests prove one-step yield/reclaim/complete, idle polling, terminal mapping, P03 wait acknowledgement, exception rollback, host refusal, and read-only tool invocation | same | W92–W97 | Large |
| W99 | Replay and regression gate | Replay preserves jobs/logs/runtime catalog state; P00/P01/P02/P03/P05/P06/P07/P08/P19/P09 tests and full suite pass | tests and docs | W90–W98 | Medium |

W90–W95 are one numbered-file delivery and must not be released partially. The final commit must include the SQL, documentation, current-tree pin updates, and P09 tests together, because current-tree source tests fail after `0021` exists but before their catalog and marker pins are updated.

---

## Background

### Skeleton, contract, snapshot

- Skeleton P09 (`docs/plans/2026-08-23-pg-cordis-development.md:216-224`): **do** `worker_step` = claim → one step → yield/wait/complete; only `locus = in-db` tools. **Don't** file edits or session TEMP. **Done when** a single worker walks mock coding/readonly to yield then reclaim.
- P09 depends on P05+P06; parallel with P10; P11 and P17 depend on P09 (`:78-88`, `:241`, `:308`).
- Locked: in-db and host speak **one claim protocol** on one `jobs` queue (`docs/decisions/2026-08-23-pending.md` Worker / Queue / D8 rows; snapshot §4 `docs/analysis/2026-08-23-i-architecture-snapshot.md:86-100`). Authority is the `jobs` row (`claim_token` / `claimed_by` / `claim_expires_at`), keyed by `run_id` (F sketch `:78-86`).
- D1 forbids session affinity / `pg_temp` across yield. D7 forbids `CREATE EXTENSION` in this series. D9 forbids sync child loops (P17).
- F §9 dual locus (`docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:228-241`): same SQL verbs; in-db `rlm_loop` that never yields is non-compliant. F §12 (`:287`) still lists chaining as unfrozen; P05 already closed it for the driver (decisions 11 and 19, `docs/plans/P05-one-step-driver-2026-08-24.md:397`, `:405`). Skeleton P09 wording is “一步”.
- G `worker_step` / `h_rlm_continue` / `rlm_enqueue` (`docs/analysis/2026-08-23-g-rlm-one-step-driver.md:389-454`) is **research SQL, not product** (`:1-3`). Do not lift it.

### Current kernel P09 must reuse

| Existing component | Current responsibility | P09 use |
|---|---|---|
| `cordis.jobs` | One row per run; scheduling and live claim state (`sql/0001_p01_claim.sql:23-25`) | Reused unchanged; P09 inserts through `enqueue_job`, claims through `claim_job`, transitions through P01 verbs |
| `claim_job(text,text,integer DEFAULT 90)` | Reaps stale claims, then claims one eligible PENDING job using `FOR UPDATE SKIP LOCKED`; **`p_run_id` NULL already means queue poll** (`sql/0001_p01_claim.sql:117-170`, `:153`) | Called exactly once per `worker_step` |
| `yield_claim` / `complete_claim` / `fail_claim` | Boolean-fenced `RUNNING` + live token + unexpired lease | Sole direct worker transitions |
| `agent_steps` / `emit_step_claimed` | Append-only log and claim-fenced append (extends lease) | P05 handler writes through it; P09 synthetic failures also use it |
| `step_once(text,uuid,integer DEFAULT 90) RETURNS text` | At most one P05 mock step; **never mutates `jobs.status`** (`sql/0005_p05_one_step_driver.sql:69-74`, `:128-138`) | Registered directly as the first P09 queue handler and invoked dynamically |
| `await_event` | Atomically appends `run/await`, creates `run_waits`, sets `WAITING`, clears claim (`sql/0003_p03_wait_event.sql:64-81`, `:227-237`) | P09 does not call it; a future-compatible handler may call it before returning `wait` |
| `plugin_catalog` | Compiled metadata; in-db rows have SQL entrypoints, host rows do not (`sql/0006_p06_plugin_catalog.sql:35-41`, `:77-87`) | Queue resolution and tool execution |
| `authorize_tool_dispatch` | Slice live-grant check; returns descriptor including `locus`/`entrypoint`; **executes nothing**; **does not filter locus** (`sql/0020_p08_four_seam_enforcement.sql:598-604`, `:752-774`) | Mandatory authorization for `invoke_in_db_tool` |
| `paradigm_policy(text)` | STABLE policy lookup; `22023` on unknown (`sql/0019_p19_paradigm_policies.sql:477-528`) | Enqueue and every claimed execution. Kernel SQL must call this function, not `SELECT` the table or `CASE` the identity (P19 plan `:476`) |
| `fold_slice_messages` | Slice-aware isolated fold | **Not** invoked by P09’s unchanged P05 proof body |
| `_require_isolation_feature` | Closes all P08 surfaces if the four-seam manifest is incomplete (`sql/0020_p08_four_seam_enforcement.sql:121`) | Called before enqueue/worker/tool activity |
| `refresh_plugins()` | Rebuilds compiled catalog from COMMENT + host sources | Installs the canonical `kernel.step_once` row |

### Ownership already assigned to P09

| Responsibility | Assigned by |
|---|---|
| `worker_step` (claim → one step → P01 transition) | Skeleton P09; P05 plan `:75`, `:302`, `:442` |
| Exhaustive outcome CASE including unknown → fail | P05 `:393`, `:1551` |
| Handler-aware enqueue | P05 decision 3 `:389`; rejected `rlm_enqueue` `:441` |
| In-db `EXECUTE` of catalog entrypoints | P06 `:159` |
| Refuse host-locus rows as executable SQL | P06 `:270`, `:509` |
| Call `fold_slice_messages` + `authorize_tool_dispatch` when dispatching tools | P08 `:178` |
| Do not cache tool descriptors across claims | P08 `:573` |
| Call `paradigm_policy(identity)` | P19 `:476` |
| Empty `job_type` validation | P01 `:704` |
| Do not wrap/replace `step_once` | P08 mid-flow `:15`, decision 3 `:195` |

### Current end-to-end flow

Before P09, the production SQL tree stops after the step body:

```text
test/client INSERT jobs   -- job_type 'p05_test', no paradigm
  → claim_job
  → step_once
  → Python CASE in tests/test_p05_one_step_driver.py:122-149
      → yield_claim | complete_claim | fail_claim
```

Observed `step_once` returns: `lost_claim`, `complete`, `fail`, `yield`. `action='wait'` is fail-closed: emit `P05_WAIT_UNSUPPORTED` then `RETURN 'fail'` (`sql/0005_p05_one_step_driver.sql:491-503`). P05 decision 7 still lists `wait` in the closed text set.

There is no producer API that validates `job_type`, no worker function, and no SQL-owned dynamic execution of queue handlers. P06 catalog rows are declarative only. P08 authorizes a tool descriptor but deliberately does not execute it. No `worker()` / `worker_step()` exists under `sql/`.

P04 sleep/retry is **plan-only** (no `sql/0004_*.sql` in the product tree).

### SQL tree / numbering

- Current product tree ends at `0020_p08_four_seam_enforcement.sql`, marker **`p20`** (`sql/README.md:49-51`; `sql/0020_p08_four_seam_enforcement.sql:847-854`; `tests/test_p00_sql_source.py:76-97`).
- Next file is `0021_*.sql`; full-tree marker follows highest prefix → **`p21`** (P08 precedent: file `0020` reports `p20`, dollar-tag `$p08$`).
- Append only; replace `get_schema_version()` in the **new** file (`sql/README.md:25-27`; AGENTS.md rule 5).
- Tests use existing `run_apply` / `psql` / `psql_session` (`tests/conftest.py`). Two connections already proven by P01 `test_mutual_exclusion_and_yield_reclaim`.

---

## Current-state analysis

### Existing ownership and mutation points

`cordis.jobs` owns scheduler state. Its mutating paths are currently:

```text
producer SQL INSERT     → PENDING
claim_job               → RUNNING + token/claimed_by/expiry
yield_claim             → PENDING, claim fields cleared
complete_claim          → DONE, result + completed_at
fail_claim              → ERROR, error + completed_at
await_event             → WAITING + run_waits + run/await log, claim cleared
```

P09 must not update these state fields directly. `enqueue_job` is the only new direct insert into `cordis.jobs`; every post-claim transition reuses P01 or recognizes a transition already performed by P03.

`cordis.agent_steps` remains append-only. P09 does not insert into it directly. A synthetic worker protocol failure follows `emit_step_claimed(error)` then `fail_claim(same payload)`.

### Catalog state

P06 compiles COMMENT-backed in-database entries and host registration rows into one catalog. It deliberately does not execute either.

- in-db rows have a real `entrypoint regprocedure`; host rows have none (`sql/0006_p06_plugin_catalog.sql:77-87`);
- legal pairs: in-db+`queue`/`session_select`, host+`host_tool` (`:39-41`);
- `invocation='queue'` denotes a queue handler; `session_select` denotes an in-database tool surface;
- metadata alone does not prove a function has the ABI P09 expects;
- effect/retry/reconciliation matrix already allows `transactional` + `idempotent` + `none` (queue) and `read_only` + `replayable` + `none` (readonly tools) (`:43-56`);
- identity grammar `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` admits `kernel.step_once` (`:27-29`);
- description ≤ 500 characters (`:267-270`).

P09 therefore adds runtime ABI checks rather than changing P06’s table or validator. Direct `INSERT` into `plugin_catalog` is invalid (next `refresh_plugins()` wipes it).

### Paradigm state

P19 owns the open paradigm registry. `jobs.job_type` is a handler identity and must not be overloaded as the paradigm (P19 decision 12). No run-owned paradigm column exists. P09 stores the validated identity in `jobs.payload.paradigm` through enqueue and validates it again before each execution.

The canonical P05 body does not consume P19’s fold/parser slots. P09 must not fake integration by calling `fold_slice_messages` and discarding the result, and it must not create a second step body to adapt P05.

### P08 boundary

P08 explicitly leaves `step_once` unwrapped and documents it as a legacy, unfiltered proof path (P08 plan `:15`, `:178`, decision 3 `:195`). P09 preserves that boundary:

- queue resolution is trusted scheduler control-plane resolution, not model tool authorization;
- P09’s separate in-db tool function always calls `authorize_tool_dispatch`;
- grant-requiring queue handlers are rejected by P09 v1 because the queue ABI has no explicit slice/bindings arguments;
- `kernel.step_once` is registered with no required grants and is documented as the P05 proof body, not an isolated user-facing entrypoint;
- no caller may advertise `worker_step` plus `kernel.step_once` as satisfying P08 fold isolation.

### Blocking gaps

- No SQL function owns the claim → step → transition sequence.
- No trusted enqueue API binds a job to a real queue handler and a valid paradigm.
- No exact executable ABI distinguishes valid queue entrypoints from arbitrary P06 functions.
- No in-database tool invocation chokepoint combines P08 authorization with locus/effect/function-shape enforcement.
- No SQL-level handling exists for idle polling, handler disappearance, unknown outcomes, wait acknowledgements, or dropped transition ownership.

### Reuse instead of duplication

P09 must reuse: `claim_job(NULL, ...)`; P01 transition verbs without reproducing their `UPDATE` predicates; `emit_step_claimed` for synthetic worker errors; `step_once` as the canonical initial queue body; `paradigm_policy`; `authorize_tool_dispatch`; `plugin_catalog.entrypoint`; `refresh_plugins()` and COMMENT metadata; the existing apply loader and test fixtures.

P09 must not duplicate: stale-claim reaping; token generation or lease math; step-name/checkpoint/fingerprint logic; P05 mock LLM/tool logic; P08 grant parsing; P19 identity branching; P03 wait registration; an install/apply path.

---

## Design

### Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | **One catalog-selected queue-handler ABI; register the existing `cordis.step_once(text,uuid,integer)` directly as `kernel.step_once` by COMMENT metadata. Do not create an adapter.** `worker_step` resolves one `plugin_catalog` queue row and dynamically calls its entrypoint once. | P06 assigned dynamic in-db execution to P09 (`:159`). P05 decisions 11/19 assign the outer transition and one-execution serialization to P09. COMMENT metadata can register the existing function without changing its body or signature. Honors the P08 no-wrap lock. | Hard-code `worker_step → step_once` and ignore `job_type`; create `p09_step_once` as a second driver; copy the P05 body; replace P05; lift the G/scratch handler SQL. |
| 2 | **Add `cordis.enqueue_job`; `job_type` is a P09-compatible catalog identity; paradigm is an explicit enqueue argument stored in `jobs.payload.paradigm`.** | P05 parked handler-aware enqueue on P09 (`:389`). P19 requires the producer path to store a policy identity. Validating both at enqueue prevents silently creating poison jobs while retaining one jobs row. No `jobs.paradigm` column. | Continue direct INSERT as the product ABI; accept arbitrary `job_type`; infer paradigm from `job_type`; add a `jobs.paradigm` column; create `agent_runs`; upsert duplicate runs. |
| 3 | **Use one poll-first `worker_step` signature with optional `p_run_id`, not overloads.** `p_run_id=NULL` delegates to `claim_job(NULL,...)`; a non-null value targets one run. | P01 already defines both behaviors in one signature (`sql/0001_p01_claim.sql:153`). A single worker ABI is easier for P10/P11. | Separate `worker_step()` and `worker_step_run()`; always require a run id; reimplement queue polling. |
| 4 | **A `wait` outcome acknowledges a wait the queue handler has already made durable through P03. P09 never derives event parameters and never calls `await_event`.** Valid WAITING state returns `wait`; a live RUNNING claim returning `wait` becomes terminal `P09_WAIT_NOT_REGISTERED`. | `await_event` owns the only atomic log + side-table + WAITING transition. The textual handler result has no event key, await id, deadline, or metadata. P05 wait remains unreachable today (`sql/0005:491-503`), but the worker vocabulary can support a future handler that performs P03 first. | Have the worker call `await_event` with invented parameters; treat every wait as yield; remove wait from the CASE; accept `wait` without checking durable state. |
| 5 | **Validate the stored paradigm through `paradigm_policy` at enqueue and on every claim. Do not call `fold_slice_messages` from the legacy P05 path.** P09 consumes P08 on actual tool dispatch through `invoke_in_db_tool`; `kernel.step_once` remains explicitly non-isolated proof infrastructure. | P08 forbids replacing/wrapping `step_once`. Calling the isolated fold without feeding its result into the driver would be security theater. P19 still requires kernel consumers to use its lookup ABI. | Query `paradigm_policies` directly; CASE on `codeact`/`rlm`; call and discard `fold_slice_messages`; claim that P05 becomes isolated because the latch is enabled; build a second isolated step driver in P09. |
| 6 | **P09 queue handlers must be grant-free, opt into `config.worker_abi='cordis.p09.queue.v1'`, and match exact `(text,uuid,integer) → text` ABI** (ordinary, non-set-returning, VOLATILE, SECURITY INVOKER, `search_path=pg_catalog`). | The v1 queue signature has no `slice_id` or concrete grant bindings. Executing a grant-requiring queue handler would bypass P08. An explicit config marker prevents accidental execution of any P06 `queue` function that happens to share the SQL signature. | Treat all `in-db + queue` rows as executable; union run grants; infer a slice; add slice arguments to `step_once`; authorize queue handlers through tool dispatch with fake bindings. |
| 7 | **Add a separate claim-bound `invoke_in_db_tool` for actual tool entrypoints. It permits only `in-db + session_select + read_only/replayable/none` descriptors with exact `(jsonb) → jsonb` ABI.** | P06 distinguishes queue handlers from session-select tools; P08 authorizes descriptors but executes nothing. Restricting P09 to read-only tools avoids stealing P16’s non-transactional recovery work and makes stale-result discard safe. | Execute host tools as SQL; execute queue handlers as tools; allow transactional/external effects without call/result recovery; let callers execute descriptor text themselves; add fake SQL stubs for host tools. |
| 8 | **The read-only tool helper performs a non-mutating exact-claim check both before and after execution and does not heartbeat.** | P05 already owns lease extension through claimed appends. Read-only results are replayable; a post-call stale result is rejected without adding a second heartbeat. | `renew_claim` before or after every tool; no post-execution fence; log a result after claim loss. |
| 9 | **`worker_step` returns one table row with `(job_id, run_id, outcome)`.** Closed outcomes: `idle`, `yield`, `wait`, `complete`, `fail`, `lost_claim`. Never returns the live claim token. | Polling needs an explicit `idle` result and the selected run identity. Returning a token would leak a capability. One row for idle avoids using zero rows ambiguously. | Return only text; return the claim token; return zero rows on idle; expose arbitrary handler output; return a PostgreSQL enum. |
| 10 | **Unhandled queue-handler exceptions propagate unchanged and roll back the entire worker statement.** Expected configuration/dispatch failures detected **before** invocation are converted to durable P09 errors. | P05 requires invariant failures such as `23505` to propagate unchanged. Catching all executor errors would terminally consume transient failures before P04 exists. | `EXCEPTION WHEN OTHERS` around the handler and `fail_claim`; swallow errors as `lost_claim`; add retry/backoff here. |
| 11 | **No direct jobs status mutation in P09.** Enqueue inserts PENDING; all post-claim status changes use P01 verbs or are already performed by P03 inside the handler. | Keeps one claim state machine and one authoritative set of fencing predicates. | Inline `UPDATE cordis.jobs SET status=...`; copy P01 predicates; add a worker status table. |
| 12 | **One `worker_step` SQL call is one transaction-local claim, handler invocation, and transition. Workers must commit after each non-idle call before calling again.** Numbered SQL cannot issue transaction control. | Autocommit gives the required step boundary; an explicit outer transaction remains the caller’s responsibility. A caller-side loop in one transaction would hide yield and recreate multi-step session pinning. | Commit inside PL/pgSQL; loop multiple claims in one call; hold one claim across multiple `step_once` invocations. |
| 13 | **P09 adds no `run/yield` log event.** Synthetic worker protocol failures append a canonical P09 error through `emit_step_claimed`, then `fail_claim` with that same payload. | P05 decision 9 and P01’s `yield_claim` contract leave scheduler yield out of the log. History remains authoritative. | Append `run/yield` before every `yield_claim`; direct `INSERT` into `agent_steps`; fail the jobs row without an error event. |
| 14 | **The P08 feature latch is required before enqueue, claim, or tool invocation. P09 adds no table or column migration.** | P09 is installed after P08 and must not offer worker entrypoints if the four-seam installation is later damaged. Requiring the latch does not falsely claim that the P05 body is isolated. Existing APIs already provide required state. | Ignore a missing P08 seam; perform a partial latch check; add `agent_runs` or a handler table. |

No implementation fork remains open after these decisions. Mid-flow (2026-08-25) confirmed decisions 1, 4, and 7.

---

## Component 1 — Queue-handler resolution and canonical P05 registration

### `cordis._resolve_in_db_queue_handler`

**Kind:** internal catalog resolver
**Location:** `sql/0021_p09_in_db_worker.sql`
**Owner:** kernel; called by `enqueue_job` and `worker_step`
**Lifecycle:** stateless catalog lookup; no cached descriptor

```text
cordis._resolve_in_db_queue_handler(p_identity text)
RETURNS regprocedure
```

Properties: `LANGUAGE plpgsql`, `STABLE`, `SECURITY INVOKER`, `SET search_path TO pg_catalog`, no overloads.

Validation order:

1. Trim `p_identity`. Reject NULL, blank, >128-byte, or non-P06 identity grammar with `22023 P09_UNKNOWN_JOB_HANDLER`.
2. Read exactly one `cordis.plugin_catalog` row by normalized identity. Missing row → same `22023`.
3. Require:
   - `locus = 'in-db'`;
   - `invocation = 'queue'`;
   - `entrypoint IS NOT NULL`;
   - `required_grants = ARRAY[]::text[]` (empty);
   - `config` is a JSON object and `config->>'worker_abi' = 'cordis.p09.queue.v1'`.
4. Resolve the `regprocedure` in `pg_proc` and require:
   - ordinary function (`prokind='f'`), not procedure/aggregate/window;
   - not set-returning;
   - identity arguments exactly `(text, uuid, integer)`;
   - result exactly `text`;
   - `VOLATILE`;
   - `SECURITY INVOKER`;
   - pinned function configuration includes `search_path=pg_catalog`.
5. Return the exact `regprocedure`.

| Condition | SQLSTATE | Stable fragment |
|---|---:|---|
| Invalid identity or no catalog row | `22023` | `P09_UNKNOWN_JOB_HANDLER` |
| Wrong locus/invocation or non-empty required grants | `0A000` | `P09_JOB_HANDLER_UNSUPPORTED` |
| Missing compatibility marker or SQL ABI mismatch | `55000` | `P09_JOB_HANDLER_ABI_MISMATCH` |

The function reads `plugin_catalog` directly because this is trusted scheduler handler resolution, not a model-facing tool dispatch. It must not call `authorize_tool_dispatch` with fabricated slice bindings. It does not execute the handler and does not cache the result across claims.

**v1 payload contract:** the queue ABI is `(run_id, claim_token, lease_seconds) → text`. The worker does not pass `jobs.payload`. A v1 handler reads the claimed `cordis.jobs` row itself (the canonical `step_once` already does this at `sql/0005_p05_one_step_driver.sql:129-138`). Fixture handlers in W98 must do the same.

### Canonical queue-handler registration

P09 adds COMMENT metadata to the **existing** function identity `cordis.step_once(text,uuid,integer)`. The COMMENT must start with `{` and be a valid `cordis_plugin` definition (P06 scan rule, `sql/README.md:59`). Description ≤ 500 characters and must state that the current entrypoint is the P05 mock/proof body, is **not** the user-facing isolated driver, and include the token `legacy_unscoped`.

| Field | Value |
|---|---|
| `identity` | `kernel.step_once` |
| `version` | `0.1.0` |
| `locus` | `in-db` |
| `invocation` | `queue` |
| `required_grants` | `[]` |
| `effect_class` | `transactional` |
| `retry_class` | `idempotent` |
| `reconciliation` | `none` |
| `session_scope` | `run` |
| `config.worker_abi` | `cordis.p09.queue.v1` |
| `config.protocol` | `cordis.p05.mock.v1` |
| `config.isolated` | `false` |

After installing the COMMENT, `0021` calls the existing `cordis.refresh_plugins()` once. This rebuilds `plugin_catalog` from COMMENT sources plus existing `host_plugin_definitions`; it must not directly insert into the compiled catalog.

Replay reasserts the canonical COMMENT and rebuilds the catalog. Existing host registrations remain because their source rows are preserved. The function body and `pg_proc` identity of `step_once` are unchanged.

---

## Component 2 — Handler-aware enqueue

```text
cordis.enqueue_job(
    p_run_id     text,
    p_job_type   text,
    p_paradigm   text,
    p_payload    jsonb DEFAULT '{}'::jsonb,
    p_priority   integer DEFAULT 0
) RETURNS bigint
```

Properties: `VOLATILE`, `SECURITY INVOKER`, `SET search_path TO pg_catalog`, no overload. Immediately claimable; no delayed scheduling argument; no model-tool catalog registration.

Algorithm:

1. Validate `p_run_id` as non-null/nonblank. **Preserve its bytes exactly; do not trim before storage.**
2. Validate `p_payload` is a JSON object.
3. Reject a caller payload already containing top-level `paradigm` (`22023`); the explicit argument is the only P09 enqueue source for that field.
4. Validate `p_priority` is non-null. Any PostgreSQL integer remains legal because P01 already defines ordering.
5. Require `_require_isolation_feature()` before creating work.
6. Normalize and validate `p_paradigm` by `SELECT * FROM cordis.paradigm_policy(p_paradigm)`. Do not query `paradigm_policies`. Do not branch on known seed identities. Preserve P19 `22023` on unknown.
7. Resolve `p_job_type` through `_resolve_in_db_queue_handler`.
8. Insert one `cordis.jobs` row:
   - `run_id = p_run_id`;
   - `job_type = normalized handler identity`;
   - `payload = p_payload` plus canonical normalized `paradigm`;
   - `priority = p_priority`;
   - claim/status/timing fields use P01 defaults (`PENDING`, `attempt=1`, immediate `available_at`).
9. Return the inserted `job_id`.

P09 does not add `available_at` to this API. Delayed enqueue, sleep, and retry scheduling remain P04/P17 concerns. `enqueue_job` does not add `slice_id`, grant bindings, retry data, event data, or spawn lineage.

Persistence contract:

```text
jobs.job_type          = plugin_catalog.identity for a P09 queue handler
jobs.payload.paradigm  = normalized P19 policy identity
```

Duplicate `run_id` propagates the existing `jobs_run_id_key` `23505`. P09 must not convert duplicate enqueue into an upsert or silently reuse a terminal row.

Older rows inserted manually remain valid P01 data, but `worker_step` treats a missing/invalid paradigm or non-catalog handler as a durable P09 protocol failure. No migration is required because no production worker existed before P09.

Handler and paradigm validation use the enqueue transaction’s snapshots. A later catalog refresh or policy unregister may invalidate them before execution; `worker_step` repeats both validations after claim.

---

## Component 3 — Read-only in-database tool execution

```text
cordis.invoke_in_db_tool(
    p_claim_token  uuid,
    p_run_id       text,
    p_slice_id     uuid,
    p_identity     text,
    p_bindings     jsonb,
    p_arguments    jsonb
) RETURNS jsonb
```

Properties: `VOLATILE` (dynamic invocation even though admitted entries are read-only), `SECURITY INVOKER`, `SET search_path TO pg_catalog`, no overload, no descriptor cache, does not append log events or change jobs status, does not apply P19 observation policy.

**Why this is separate from `worker_step`:** `worker_step` dispatches a trusted queue handler. A queue handler may eventually parse a model decision and request a tool. Combining queue and tool invocation would either require fake slice bindings for the queue handler or would allow tools to bypass P08.

Algorithm:

1. Validate: run id nonblank; token and slice id non-null; plugin identity grammar; bindings and arguments are JSON objects. Invalid scalar/JSON → `22023 P09_INVALID_TOOL_REQUEST`.
2. Require `_require_isolation_feature()` **before** the claim check. `authorize_tool_dispatch` also latches internally (`sql/0020_p08_four_seam_enforcement.sql:638`); the extra call is an intentional error-precedence choice so a closed isolation feature raises `42501 P08_ISOLATION_FEATURE_CLOSED` rather than `P09_TOOL_CLAIM_REQUIRED`. Do not delete it as redundant.
3. Non-mutating exact claim check: same `run_id`, same `claim_token`, `status='RUNNING'`, `claim_expires_at > clock_timestamp()`. Missing/dead claim → `42501 P09_TOOL_CLAIM_REQUIRED`.
4. Call `authorize_tool_dispatch(run_id, slice_id, identity, bindings)`. Preserve its `22023`/`42501` errors unchanged. Do not read `plugin_catalog` first and do not cache an older descriptor.
5. Validate the returned descriptor:
   - `locus = 'in-db'`;
   - `invocation = 'session_select'`;
   - `effect_class = 'read_only'`;
   - `retry_class = 'replayable'`;
   - `reconciliation = 'none'`;
   - non-null `entrypoint`.
6. Resolve the exact entrypoint and inspect `pg_proc`:
   - ordinary, non-set-returning function;
   - one identity argument of type `jsonb`;
   - result `jsonb`;
   - volatility `STABLE` or `IMMUTABLE`;
   - `SECURITY INVOKER`;
   - pinned `search_path=pg_catalog`.
7. Dynamically invoke the resolved schema-qualified function once with `p_arguments`. Use the validated `regprocedure`/OID; never interpolate argument JSON or caller SQL into the command text.
8. Reject SQL NULL result with `55000 P09_IN_DB_TOOL_INVALID_RESULT`. JSONB scalar/array/object values (including JSON `null`) are permitted because P06 only promises JSONB.
9. Repeat the exact non-mutating claim check. If the lease expired during execution, raise `55000 P09_TOOL_CLAIM_LOST`. The tool is read-only, so discarding its result is safe and replayable.
10. Return:

```text
{
  "protocol": "cordis.p09.in_db_tool.v1",
  "identity": <authorized normalized identity>,
  "descriptor": <fresh P08 descriptor>,
  "result": <entrypoint JSONB result>
}
```

| Condition | SQLSTATE | Stable fragment |
|---|---:|---|
| Invalid scalar/JSON argument | `22023` | `P09_INVALID_TOOL_REQUEST` |
| No live matching claim before execution | `42501` | `P09_TOOL_CLAIM_REQUIRED` |
| P08 latch/grant/control-plane denial | Preserve P08 | Preserve P08 fragment |
| Host descriptor | `42501` | `P09_IN_DB_TOOL_LOCUS_REQUIRED` |
| Queue or host-tool invocation | `0A000` | `P09_IN_DB_TOOL_INVOCATION_UNSUPPORTED` |
| Transactional/external or non-replayable tool | `0A000` | `P09_IN_DB_TOOL_EFFECT_UNSUPPORTED` |
| Function-shape/security/search-path mismatch | `55000` | `P09_IN_DB_TOOL_ABI_MISMATCH` |
| SQL NULL result | `55000` | `P09_IN_DB_TOOL_INVALID_RESULT` |
| Claim expires during tool call | `55000` | `P09_TOOL_CLAIM_LOST` |

The entrypoint’s own SQL exception propagates unchanged. P09 does not classify or retry it.

This helper returns a result but does not append `tool` history. The calling step body remains responsible for appending through `emit_step_scoped` or a later D2 call/result protocol. P19 observe/clip functions remain a step-driver responsibility.

---

## Component 4 — In-database worker

```text
cordis.worker_step(
    p_worker_id     text,
    p_run_id        text DEFAULT NULL,
    p_lease_seconds integer DEFAULT 90
) RETURNS TABLE (
    job_id   bigint,
    run_id   text,
    outcome  text
)
```

Properties: `VOLATILE`, `SECURITY INVOKER`, `SET search_path TO pg_catalog`, no overload, exactly one returned row, no internal loop. Never returns the live claim token. Does not call `renew_claim` before the handler.

Closed returned outcomes:

| Outcome | Meaning at return |
|---|---|
| `idle` | No eligible job was claimed; IDs are NULL |
| `yield` | Handler returned `yield` and `yield_claim` succeeded |
| `wait` | Handler returned `wait` after atomically leaving a consistent P03 WAITING state |
| `complete` | Handler returned `complete`, a final log row existed, and `complete_claim` succeeded |
| `fail` | A terminal handler or P09 protocol failure was logged and `fail_claim` succeeded |
| `lost_claim` | Handler or transition observed that the token was no longer authoritative |

### Input and claim

1. Validate worker id non-null/nonblank; optional run id is either NULL or nonblank; lease is positive. Invalid → `22023` before claim.
2. Require `_require_isolation_feature()` before claiming.
3. Call exactly once: `claim_job(p_run_id, p_worker_id, p_lease_seconds)`.
4. If no row: return `(NULL, NULL, 'idle')`.
5. If a row is returned, retain job id, run id, token, job type, and payload locally for this invocation only.

No loop, retry, sleep, or second claim occurs inside the same call. Only `claim_job` scans the queue.

### Post-claim admission

Before invoking the handler:

1. Require claimed `payload` to be a JSON object with a nonblank string `paradigm`.
2. Call `paradigm_policy(payload->>'paradigm')`. Do not use the returned policy row to branch on identity. Do not call `fold_slice_messages`.
3. Resolve `jobs.job_type` through `_resolve_in_db_queue_handler`.

Expected admission failures become a durable worker error:

| Condition | Log payload code |
|---|---|
| Non-object payload or missing/invalid paradigm | `P09_JOB_PAYLOAD_INVALID` |
| `paradigm_policy` reports unknown/invalid identity | `P09_PARADIGM_UNAVAILABLE` |
| Handler missing, wrong locus/invocation/grants, or incompatible ABI | `P09_HANDLER_UNAVAILABLE` |

For these failures: build one error payload using protocol `cordis.p09.worker.v1`; append it as `kind='error'`, `step_name=NULL` using `emit_step_claimed(..., p_extend_seconds => p_lease_seconds)` (pass the worker’s lease, do not rely on the default 90); if append returns false, return `lost_claim`; call `fail_claim(token, same_error_payload)`; return `fail` if true, otherwise `lost_claim`. Every other P09 synthetic append (`P09_COMPLETE_WITHOUT_FINAL`, `P09_FAIL_WITHOUT_ERROR`, `P09_WAIT_NOT_REGISTERED`, `P09_INVALID_STEP_OUTCOME`) uses the same sixth-argument rule.

Only the documented lookup/validation SQLSTATEs are caught in these narrow blocks. No broad exception handler surrounds the queue entrypoint.

### Handler invocation

Dynamically invoke the resolved handler exactly once:

```text
handler(run_id, claim_token, lease_seconds) → text
```

The canonical `kernel.step_once` row resolves directly to `cordis.step_once(text,uuid,integer)`.

The handler owns its one-step log work; must not map jobs status except for an atomic P03 wait registration; must not loop; may return the documented step outcomes; may raise an exception, which propagates and rolls back the worker statement.

The worker does not: call `renew_claim` before execution; hold a separate heartbeat; invoke a second handler; rerun the same handler on exception; append a yield event; call any tool entrypoint itself unless the handler explicitly uses `invoke_in_db_tool`.

---

## Component 5 — Outcome state machine

```text
PENDING --worker_step/claim_job--> RUNNING

handler "yield"      → yield_claim(token) → PENDING → outcome "yield"
handler "complete"   → require final log → complete_claim(token, final.payload) → DONE → "complete"
handler "fail"       → require latest error, or synthesize → fail_claim → ERROR → "fail"
handler "wait"       → require handler already made P03 wait durable → WAITING → "wait"
handler "lost_claim" → no transition → "lost_claim"
NULL/unknown         → append P09 protocol error → fail_claim → ERROR → "fail"
```

### `yield`

Call `yield_claim(token)` once. True → `yield`. False → `lost_claim`. Do not append `run/yield`.

### `complete`

1. Read the latest `final` event for the run.
2. If present: `complete_claim(token, final.payload)`; true → `complete`; false → `lost_claim`.
3. If absent: synthesize `P09_COMPLETE_WITHOUT_FINAL`; append/fail using the live token; return `fail` or `lost_claim`.

A handler cannot mark a job DONE based only on its textual return. The scheduler result is the canonical final log payload (P05 tests copy `payload` from the latest `final` row: `tests/test_p05_one_step_driver.py:129-138`).

### `fail`

1. Read the latest `error` event for the run.
2. If present, pass its payload to `fail_claim`.
3. If absent: synthesize `P09_FAIL_WITHOUT_ERROR`; append through `emit_step_claimed`; then `fail_claim`.
4. Successful transition → `fail`; false fence → `lost_claim`.

P05’s existing fail paths already provide an error row; the synthetic branch protects the generic queue ABI.

### `wait`

P09 does not call `await_event`.

After the handler returns `wait`, read the current scheduler and wait state by run id. Valid acknowledgement requires all of:

- `jobs.status='WAITING'`;
- `claim_token`, `claimed_by`, and `claim_expires_at` are NULL;
- exactly one `run_waits` row exists for the run;
- that row references the same jobs row through the existing P03 foreign key.

Valid state → return `wait` without another transition.

If the job is still RUNNING with the same live token: synthesize and append `P09_WAIT_NOT_REGISTERED`; `fail_claim`; return `fail` or `lost_claim`. Do not silently yield.

If the token is gone but the WAITING state is inconsistent, raise `55000 P09_WAIT_STATE_INVALID`. Because handler execution and verification are in one transaction, this rolls back the malformed wait registration and the original claim together.

This branch is unreachable through the current P05 `step_once`, which converts a mock wait decision into `fail`. Tests use a fixture handler that calls `await_event` then returns `wait`.

### `lost_claim`

Return immediately without appending or transitioning. The next eligible claim or `release_stale` owns recovery. P09 does not append an additional error because the worker is no longer authoritative.

### NULL or unknown outcome

Build `P09_INVALID_STEP_OUTCOME` with the raw value represented as JSON null/string in `details`; append through `emit_step_claimed`; `fail_claim`. Never treat an unknown value as yield. This is the exhaustive CASE required by P05 decision 7.

### Synthetic error envelope

Every P09-created error uses:

```text
{
  "protocol": "cordis.p09.worker.v1",
  "code": <stable P09 code>,
  "message": <bounded human-readable text>,
  "details": {
    "job_type": <identity or null>,
    "paradigm": <identity or null>,
    "handler_outcome": <text or null>,
    "source_sqlstate": <text or null>
  },
  "step_name": null
}
```

Messages copied from caught catalog/policy validation errors must be bounded to 1000 characters. Do not persist a claim token, worker secret, or SQL function OID in the log payload.

### Exception behavior

Exceptions thrown from the dynamically invoked handler propagate unchanged. In particular: a P05 duplicate LLM append keeps SQLSTATE `23505`; SQL cancellation/statement timeout propagates; an invariant violation is not rewritten as a P09 error event.

Because claim, handler, and transition execute in the caller’s transaction, propagation rolls back the claim, P05/P09 log writes, jobs transitions, and in-database transactional effects made by the handler. If the handler performed an external provider operation before rollback, P05’s stable provider key remains the recovery mechanism. P09 adds no new external retry semantics.

---

## State and data flow

### Enqueue

```text
trusted producer
  → enqueue_job(run, handler, paradigm, payload, priority)
      → P08 readiness latch
      → paradigm_policy(paradigm)
      → _resolve_in_db_queue_handler(handler)
      → payload + canonical paradigm
      → INSERT cordis.jobs(PENDING)
  → job_id
```

Execution context: one caller transaction. Failure before the insert leaves no row. A duplicate `run_id` aborts with `23505`.

### Normal P05 worker call

```text
worker caller
  → worker_step(worker_id, optional run_id, lease)
      → P08 readiness latch
      → claim_job → release_stale → SKIP LOCKED claim of one PENDING row
      → paradigm_policy(payload.paradigm)
      → _resolve_in_db_queue_handler(job_type)
      → dynamic queue entrypoint once
          → canonical path: step_once
              → next_step_name / llm_checkpoint
              → invoke_llm mock
              → emit_step_claimed (extends/fences claim)
      → exhaustive outcome mapping
      → one result row {job_id, run_id, outcome}
  → caller commits
```

All steps occur in the caller’s transaction and backend. No state depends on using that backend again after commit.

### In-database tool call

```text
claimed queue handler
  → invoke_in_db_tool(token, run, slice, tool, bindings, arguments)
      → exact live-claim check
      → authorize_tool_dispatch (current slice live grants, fresh descriptor)
      → require in-db/session_select/read_only
      → validate regprocedure ABI
      → execute once
      → exact post-execution claim check
      → descriptor + result
  → caller later appends observation under the same claim
```

P08 authorization is repeated per invocation. Neither descriptor nor grant result is persisted or cached by P09.

### Concurrency and ordering

- Two workers calling `worker_step(NULL run)` use the existing `SKIP LOCKED` mutual exclusion.
- One `worker_step` claims at most one row.
- `p_run_id=NULL` polls global PENDING work in P01 order (`priority DESC, available_at ASC, job_id ASC`).
- Reusing the same worker id has no ownership effect; token identity remains authoritative.
- Yield clears the token before the worker result commits. Another worker may claim the row only after that transaction commits.
- Repeated worker calls after a successful yield see the next named step through P02/P05 log folding.
- An expired claim is reaped by the next `claim_job`; P09 does not add a timer.
- Catalog or grant changes committed after a statement snapshot affect the next resolver/authorization call. No descriptor is reused.
- A duplicate tool request may rerun only a read-only entrypoint; mutation classes are refused.
- No background notification is required; an idle worker may poll again according to its external scheduling policy.

### Cancellation, rollback, dropped responses

If the worker SQL statement is cancelled or its handler raises: the claim update made by `claim_job` rolls back; P05 log rows and lease extensions in that transaction roll back; the jobs row returns to its pre-call state, normally PENDING; sequence gaps are acceptable; an external LLM implementation could still have accepted a stable provider key (P05’s documented recovery model).

If a caller invokes `worker_step` inside a larger explicit transaction and does not commit, other workers cannot observe the yielded or terminal transition. The worker contract therefore requires one commit per non-idle call. P09 does not and cannot commit internally. Multiple `worker_step` calls in one outer transaction are unsupported operational usage even though PostgreSQL permits function calls. Tests and worker callers use autocommit or one call per explicit transaction.

If the database commits but the client loses the `worker_step` response: inspect `cordis.jobs` by run id; inspect `agent_steps`/`run_state`; do not repeat a transition with an old token, which is never returned by P09 anyway.

---

## API and persistence impact

### New interfaces

| New identity | Result | Volatility |
|---|---|---|
| `cordis._resolve_in_db_queue_handler(text)` | `regprocedure` | STABLE |
| `cordis.enqueue_job(text,text,text,jsonb,integer)` | `bigint` | VOLATILE |
| `cordis.invoke_in_db_tool(uuid,text,uuid,text,jsonb,jsonb)` | `jsonb` | VOLATILE |
| `cordis.worker_step(text,text,integer)` | table `(job_id bigint, run_id text, outcome text)` | VOLATILE |

All are `SECURITY INVOKER`, pin `search_path TO pg_catalog`, and have no overloads. Defaulted arguments do not create overloads.

### Modified existing interfaces

No existing callable signature changes.

1. `COMMENT ON FUNCTION cordis.step_once(text,uuid,integer)` gains canonical P09 plugin metadata (in `0021`, not by editing `0005`).
2. `cordis.refresh_plugins()` is invoked during apply, causing `kernel.step_once` to appear in the compiled catalog.
3. `cordis.get_schema_version()` keeps its zero-argument `RETURNS text`, SQL, IMMUTABLE, SECURITY INVOKER shape; the new file changes only the literal from `p20` to `p21`.

### Stored data

No table or column is added. P09 establishes producer conventions for rows created through `enqueue_job` (`job_type`, `payload.paradigm`, `priority`). Existing rows inserted before P09 are not rewritten; if passed to `worker_step` without the P09 contract they fail durably as `P09_JOB_PAYLOAD_INVALID` or `P09_HANDLER_UNAVAILABLE`.

### Exact new catalog/function inventory

Full-tree `KERNEL_FUNCTIONS` (`tests/test_p00_sql_source.py:23-73`) gains, in lexical order:

- `cordis._resolve_in_db_queue_handler` (after `_require_isolation_feature`)
- `cordis.enqueue_job` (after `emit_step_scoped`)
- `cordis.invoke_in_db_tool` (before `invoke_llm`; lexical `in` < `ll`)
- `cordis.worker_step` (after `unregister_paradigm_policy`)

No new tables or types. The P06 compiled catalog gains identity `kernel.step_once`.

### Backward compatibility

- P01/P03/P05-only trees retain their historical function behavior and markers.
- Direct `INSERT` into jobs remains possible for tests/control-plane SQL, but P09 only guarantees execution for rows satisfying its handler/paradigm contract.
- Existing `step_once` callers are unaffected because neither its signature nor body changes.
- P08’s `isolation_seams.gate_fn` OIDs remain valid because P09 does not replace any P08 function.
- Host plugin registrations remain source rows and are preserved across the P09 `refresh_plugins()` call.

---

## Error handling and edge cases

| Operation | Condition | Behavior |
|---|---|---|
| `enqueue_job` | Invalid run/payload/paradigm/handler syntax | `22023`; no row |
| `enqueue_job` | Payload already has top-level `paradigm` | `22023`; no row |
| `enqueue_job` | P08 latch closed | P08 `42501`; no row |
| `enqueue_job` | Unknown paradigm | P19 `22023`; no row |
| `enqueue_job` | Handler wrong locus/invocation/grants | `0A000 P09_JOB_HANDLER_UNSUPPORTED` |
| `enqueue_job` | Handler ABI mismatch | `55000 P09_JOB_HANDLER_ABI_MISMATCH` |
| `enqueue_job` | Duplicate run | Existing `23505`; no upsert |
| `worker_step` | Invalid worker/run/lease | `22023`; claim not attempted |
| `worker_step` | P08 latch closed | `42501 P08_ISOLATION_FEATURE_CLOSED` before claim |
| `worker_step` | No ready job | One `idle` result row |
| `worker_step` | Manually inserted malformed payload | Claimed job gets terminal `P09_JOB_PAYLOAD_INVALID` |
| `worker_step` | Catalog/policy removed after enqueue | Append P09 error; jobs → ERROR |
| `worker_step` | Handler raises `23505` or another unhandled error | Exception propagates; whole worker statement rolls back |
| `worker_step` | Handler returns `yield`, transition loses token | `lost_claim` |
| `worker_step` | `complete` without final log | Append `P09_COMPLETE_WITHOUT_FINAL`; jobs → ERROR |
| `worker_step` | `fail` without error log | Append `P09_FAIL_WITHOUT_ERROR`; jobs → ERROR |
| `worker_step` | `wait` with valid P03 state | Return `wait`; jobs remains WAITING |
| `worker_step` | `wait` while claim still RUNNING | Append `P09_WAIT_NOT_REGISTERED`; jobs → ERROR |
| `worker_step` | malformed WAITING state | `55000 P09_WAIT_STATE_INVALID`; call rolls back |
| `worker_step` | NULL/unknown outcome | Append `P09_INVALID_STEP_OUTCOME`; jobs → ERROR |
| `worker_step` | Transition returns false | Return `lost_claim`; no unfenced fallback update |
| `worker_step` | Existing final/error | Canonical P05 handler returns matching terminal outcome; worker maps latest payload |
| `invoke_in_db_tool` | Unauthorized exact corpus/event target | Preserve P08 `42501` |
| `invoke_in_db_tool` | Host plugin | `42501 P09_IN_DB_TOOL_LOCUS_REQUIRED` |
| `invoke_in_db_tool` | Queue handler passed as tool | `0A000 P09_IN_DB_TOOL_INVOCATION_UNSUPPORTED` |
| `invoke_in_db_tool` | Transactional/external effect | `0A000 P09_IN_DB_TOOL_EFFECT_UNSUPPORTED` |
| `invoke_in_db_tool` | Entry function dropped or changed | `55000 P09_IN_DB_TOOL_ABI_MISMATCH` |
| `invoke_in_db_tool` | Lease expires during read | `55000 P09_TOOL_CLAIM_LOST`; discard result |
| Any P09 call | SQL cancellation | Propagate; transaction rollback |
| Catalog refresh | Changes handler between enqueue and claim | Worker revalidates and fails closed |
| Repeated apply | Canonical COMMENT restored; source rows/log/jobs preserved | Version remains `p21` |

Boundary conditions:

- Empty queue: `idle`, not an exception.
- Future `available_at`: not claimed; poll returns `idle` if no other work exists.
- WAITING/SLEEPING/DONE/ERROR rows: not selected because `claim_job` claims only PENDING.
- Blank historical `job_type`: durable handler-unavailable failure after claim.
- JSON array/scalar historical payload: durable payload-invalid failure.
- Empty grants on `kernel.step_once`: accepted only as a legacy proof handler; not represented as an isolated surface.
- Runtime unregister of the P19 seed used by a queued job: durable paradigm-unavailable failure.
- Catalog refresh during one invocation: PostgreSQL snapshots and the resolved function OID govern that call; the next claim re-resolves.

---

## File-by-file impact

| File | Change | Why | Ordering |
|---|---|---|---|
| `docs/plans/P09-in-db-worker-2026-08-25.md` | Replace the scaffold with this complete deep plan; set `ready to implement` only after critique P0/P1 are folded | AGENTS plan-before-code gate | First |
| `sql/0021_p09_in_db_worker.sql` | **Create.** Resolver, enqueue, read-only tool invoker, worker state machine, COMMENT on existing `step_once`, `refresh_plugins()`, `get_schema_version() → p21`. PL/pgSQL bodies use `$p09$`. Do **not** add tables/columns/types/views/triggers/roles/grants/tx-control; do not replace P01/P03/P05/P08/P19 bodies; no direct `UPDATE jobs SET status`; no direct `INSERT INTO agent_steps`; no loops over multiple claims or steps | Primary P09 implementation | One atomic numbered file after `0020` |
| `sql/README.md` | Add `0021`/`p21` to the version ladder; document the four P09 functions, outcome vocabulary, `jobs.job_type` / `payload.paradigm` enqueue contracts, that a v1 queue handler reads `cordis.jobs` itself for payload, `kernel.step_once` catalog row and `cordis.p09.queue.v1` marker, that the canonical P05 body remains `legacy_unscoped`, that grant-requiring queue handlers are rejected, that `invoke_in_db_tool` permits only read-only replayable in-db `session_select` entries, that `wait` is an acknowledgement of an already durable P03 wait, that callers commit after each worker call, `$p09$` / prefix `0021` / marker `p21` | Canonical install/runtime contract | After signatures are fixed |
| `tests/test_p09_in_db_worker.py` | **Create.** Catalog, enqueue, worker, wait, concurrency, tool dispatch, replay, and source-boundary tests. Reuse only `run_apply`, `psql`, `psql_session`, and where needed `next_sql_prefix` from `tests.conftest.py`. Do not import `tools` or create another server/apply fixture | P09 completion proof | Atomic with SQL |
| `tests/test_p00_sql_source.py` | Rename/retarget `test_fresh_apply_lists_current_tree_and_p20` to `p21`; append `0021_p09_in_db_worker.sql` in exact file-list assertions; expect `p21`; add the four function names to `KERNEL_FUNCTIONS` in lexical order; update probe/composition file lists and the pg-agent separate-database composition marker | P00 owns full source-tree/catalog pins | Atomic with SQL |
| `tests/test_p01_claim.py` | Update only assertions that apply the complete SQL root from `p20` to `p21`; P01-only expectations remain `p01`; do not change two-session claim tests | Highest file wins | After SQL |
| `tests/test_p02_agent_steps.py` | Update complete-tree marker to `p21`; retain P02-only `p02`; append-monopoly expectation remains exactly one direct insert in `0002_p02_log.sql` | P09 synthetic errors delegate to P02 | After SQL |
| `tests/test_p03_wait_event.py` | No behavior change. Update a version assertion only if it applies the complete SQL root; P03-only tree remains `p03` | P09 only verifies completed P03 waits | Regression |
| `tests/test_p05_one_step_driver.py` | No production behavior change and no P05-only marker change. Existing source test must continue proving `0005` contains no worker, enqueue, or COMMENT registration | `step_once` body remains untouched; COMMENT lives in `0021` | Regression |
| `tests/test_p06_plugin_catalog.py` | Update complete-tree marker to `p21`; update full-tree exact catalog counts/identity lists to include `kernel.step_once`; P06-only tree remains `p06`; preserve proof that host registrations have no SQL entrypoint | P09 adds one COMMENT-sourced in-db queue handler | Atomic with SQL |
| `tests/test_p07_grant_registry.py` | No behavior change. Update only complete-root version assertions if present; P07-only tree remains `p07` | Tool dispatch consumes P08/P07 indirectly | Regression |
| `tests/test_p08_four_seam_enforcement.py` | Update complete-tree file/version assertions and later-probe expectations to `0021`/`p21`; retain explicit tree-ending-at-`0020` expectations as `p20`; add P09 function names to any exact full-tree function list; drop-one-seam probe copies of the current tree now retain marker `p21`; preserve P08 blank-context fold, legacy `step_once`, denylist, latch, and replay behavior; add **no** assertion that P09’s P05 handler is isolated | P09 is after P08 but does not change seam signatures | Atomic with SQL |
| `tests/test_p19_paradigm_policies.py` | Update complete-tree markers to `p21`; sentinel probe prefix becomes `0022` through `next_sql_prefix`; truncated P19 tree remains `p19`; preserve all slot signatures | P09 consumes policy lookup without changing P19 ABI | Atomic with SQL |
| `tests/conftest.py` | **No change** | Existing helpers are sufficient | — |
| `tools/apply_pg_cordis.py` | **No change** | No second apply path | — |
| `sql/0000_kernel.sql` through `sql/0020_p08_four_seam_enforcement.sql` | **No edits** | Append-only release policy. The only interaction with `step_once` is COMMENT metadata in `0021` | — |
| `sql/0004_p04_sleep_retry.sql`, `.p19-backup/`, `scratch/` | **No change and no dependency** | Outside P09 ship set | Must not enter the P09 commit |

Before implementation review, search all tests for literal `p20` and `0020_p08_four_seam_enforcement.sql`. Classify each occurrence by the SQL root used:

- full current root → update to `p21`/include `0021`;
- intentionally truncated tree ending at P08 → retain `p20`;
- prose/source fixture describing P08 itself → retain if it is not a current-tree assertion.

---

## Work items and verification

### W90 — Queue-handler ABI and canonical registration

Implement `_resolve_in_db_queue_handler`, COMMENT metadata for `cordis.step_once`, and the final `refresh_plugins()` call.

Verify:

- `kernel.step_once` resolves to the existing P05 function OID;
- the P05 function body and signature are unchanged;
- resolver accepts the canonical row;
- host, `session_select`, nonempty-grant, mismatched-signature, set-returning, SECURITY DEFINER, unpinned-search-path, and non-VOLATILE handlers are rejected;
- replay does not duplicate the catalog row;
- no P09 function is accidentally cataloged as a model/session tool.

### W91 — Enqueue

Implement `enqueue_job`.

Verify:

- valid handler/paradigm creates one PENDING row;
- returned ID matches the inserted jobs row;
- stored `job_type` and `payload.paradigm` are normalized;
- payload fixture fields remain unchanged (P05 `PROOF_PAYLOAD` keys survive);
- caller-supplied `payload.paradigm` is rejected;
- duplicate run propagates `23505`;
- unknown/host/session-select/incompatible handler inserts nothing;
- unknown paradigm inserts nothing.

### W92 — Read-only tool invocation

Implement `invoke_in_db_tool`.

Verify:

- live run grant and exact binding authorize one in-db session-select tool;
- host-locus descriptor is never executed;
- queue entrypoint is never executed as a tool;
- exact grant target remains enforced by P08;
- transactional/external catalog classifications are rejected;
- incompatible function signatures are rejected;
- SQL NULL result is rejected;
- pre-expired and post-expired claims reject execution/result as specified;
- entrypoint exceptions propagate.

### W93 — Claim and one-handler invocation

Implement the worker’s validation, claim, policy revalidation, handler resolution, and one dynamic invocation.

Verify:

- empty queue returns exactly one `idle` row;
- NULL run ID follows P01 priority order;
- named run ID only targets that run;
- one call advances at most one jobs row and at most one P05 step;
- no internal loop or second claim occurs;
- stale claims are handled only through `claim_job`/`release_stale`;
- no descriptor or handler OID is persisted in jobs payload.

### W94 — Exhaustive outcomes

Implement every mapping branch.

Verify:

- `yield` clears the claim and permits later reclaim;
- `complete` copies the latest final payload to `jobs.result`;
- `fail` copies the latest error payload to `jobs.error`;
- missing final/error produces the exact P09 synthetic event and ERROR state;
- valid handler-performed P03 wait returns `wait`;
- unregistered wait becomes terminal;
- malformed wait state rolls back;
- `lost_claim` performs no transition;
- NULL/unknown outcome becomes terminal;
- handler `23505` and arbitrary exceptions propagate and roll back the claim.

### W95 — Version and README

Verify:

- exact current file order ends in `0020,0021`;
- full-tree `get_schema_version()` returns `p21`;
- `0021` uses `$p09$` for PL/pgSQL;
- no forbidden SQL token appears after preflight sanitization;
- README distinguishes plan P09 vs SQL marker `p21`; queue handler versus tool invocation; legacy P05 fold versus P08-isolated folds; one call per transaction.

### W96 — Current-tree pins

Search `tests/` for `p20`, `0020_p08_four_seam_enforcement.sql`, `KERNEL_FUNCTIONS`, and exact plugin_catalog counts or identities. Classify every hit as full current tree → update to `p21`/`0021`, or deliberately truncated tree → leave unchanged.

### W97–W98 — New P09 tests

Create `tests/test_p09_in_db_worker.py` using only the shared helpers.

Required named tests:

| Test | Required proof |
|---|---|
| `test_p09_fresh_apply_catalog_version_and_signatures` | Full file list ends `0021`; marker `p21`; exact four new identities, argument/result types, volatility, invoker security, pinned search path; no overloads/types/tables/extensions |
| `test_p09_kernel_step_once_is_direct_queue_handler` | Catalog identity points directly to `cordis.step_once(text,uuid,integer)`; config ABI exact; no wrapper function; `config.isolated=false` |
| `test_p09_queue_handler_resolver_rejects_wrong_shape` | Host/session-select/grant-requiring/wrong-signature/SECURITY DEFINER/unpinned entries fail with the specified category |
| `test_p09_enqueue_validates_handler_paradigm_and_payload` | Valid insert plus all no-mutation failures, including caller-supplied payload paradigm |
| `test_p09_enqueue_duplicate_run_propagates_unique_violation` | Second enqueue is `23505`; original row unchanged |
| `test_p09_worker_step_idle_and_named_run_polling` | Empty queue returns `idle`; named call cannot claim a different run |
| `test_p09_worker_step_claims_at_most_one_ready_job` | Two ready jobs, one call advances exactly one according to P01 order |
| `test_p09_single_worker_yields_reclaims_and_completes_mock_run` | Same worker ID calls three times over the P05 proof payload (`PROOF_PAYLOAD` + explicit paradigm, e.g. `codeact`) and observes `yield`, `yield`, `complete`; one jobs row; ordered `llm,tool,llm,tool,llm,final`; `run_state` `final\|3\|ok`; `jobs.result.answer = 'ok'`; zero `run/yield` events |
| `test_p09_worker_revalidates_paradigm_and_handler_after_enqueue` | Runtime policy/handler removal before claim produces the exact durable P09 failure |
| `test_p09_worker_maps_p05_failure_to_terminal_job` | Invalid P05 config logs P05 error; worker copies it into `jobs.error`; outcome `fail` |
| `test_p09_complete_and_fail_without_log_are_protocol_failures` | Custom ABI-compatible handlers returning terminal words without log rows produce P09 synthetic errors |
| `test_p09_unknown_and_null_handler_outcomes_fail_durably` | Closed outcome vocabulary enforced |
| `test_p09_wait_requires_completed_p03_registration` | One test handler calls `await_event` then returns `wait`, leaving a valid WAITING row; another returns `wait` without registration and becomes ERROR |
| `test_p09_handler_exception_propagates_and_rolls_back_claim` | Custom handler raises; worker SQL fails; claim/log changes from the call are absent and job remains PENDING |
| `test_p09_transition_fence_returns_lost_claim` | Controlled handler expires/loses its claim before a requested transition; worker does not claim success |
| `test_p09_in_db_tool_authorizes_and_executes_read_only_entrypoint` | P08-authorized in-db stable `jsonb→jsonb` function executes once and returns protocol/descriptor/result |
| `test_p09_in_db_tool_refuses_host_queue_and_effectful_entries` | Host rows, queue rows, transactional rows, and external rows are never invoked |
| `test_p09_in_db_tool_checks_claim_before_and_after_execution` | Dead initial claim fails; a read-only test function that outlives a short lease has its result rejected. Construct post-expiry with a 1s lease plus `pg_sleep` inside the STABLE fixture (PostgreSQL does not enforce declared volatility). Do not try to shorten a live lease from a second connection; P01 has no such verb |
| `test_p09_in_db_tool_does_not_cache_authorization` | Revoke between calls makes the next invocation fail through P08 |
| `test_p09_replay_preserves_jobs_logs_runtime_catalog_and_policies` | In-place replay preserves scheduler/log data, host definitions, runtime policy upserts, and reports `p21`; canonical COMMENT row is restored |
| `test_p09_source_boundaries` | No historical-file edits, direct status UPDATE, direct agent_steps INSERT, loop, TEMP, host SDK, spawn, extension, roles, transaction control, or `CREATE OR REPLACE` of `step_once` in `0021` |

Test-defined queue/tool functions may be installed in the disposable test database and registered through COMMENT plus `refresh_plugins()`. They are fixtures, not product SQL. Fixture discipline:

1. **Schema `cordis` only.** `refresh_plugins` scans `ns.nspname = 'cordis'` (`sql/0006_p06_plugin_catalog.sql:495-496`). A fixture in another schema is silently omitted and resolver tests will see `P09_UNKNOWN_JOB_HANDLER` instead of the intended shape error.
2. **Inventory tests before fixtures.** `test_p09_fresh_apply_catalog_version_and_signatures` (and any P06 full-tree exact catalog-count assertion) must run against a fresh `--reset` apply with no fixture functions installed. If the module shares one applied database, run the exact-inventory tests first, or use a separate database for fixture-backed tests. Extra `cordis` functions and catalog rows will fail exact-count pins.
3. **Every fixture COMMENT must be a complete valid `cordis_plugin` object.** A `{`-prefixed unparseable comment aborts the whole `refresh_plugins()` (P06 `test_unrelated_bad_comment_blocks_register_and_preserves_rows`). Negative resolver cases are built from **legal metadata + illegal function shape**, never from bad JSON.

`test_p09_source_boundaries` (or the module’s apply helper) must document that apply/reset order: inventory on a clean tree, then fixture install, then protocol tests.

Canonical acceptance payload: reuse P05 `PROOF_PAYLOAD` (`tests/test_p05_one_step_driver.py:28-54`) via `enqueue_job(..., p_job_type => 'kernel.step_once', p_paradigm => 'codeact', p_payload => PROOF_PAYLOAD)` — do not put `paradigm` inside the payload object.

### W99 — Regression and delivery gate

```bash
uv run pytest tests/test_p09_in_db_worker.py -q

uv run pytest \
  tests/test_p00_sql_source.py \
  tests/test_p01_claim.py \
  tests/test_p02_agent_steps.py \
  tests/test_p03_wait_event.py \
  tests/test_p05_one_step_driver.py \
  tests/test_p06_plugin_catalog.py \
  tests/test_p07_grant_registry.py \
  tests/test_p08_four_seam_enforcement.py \
  tests/test_p19_paradigm_policies.py \
  tests/test_p09_in_db_worker.py -q

PGCORDIS_PGDATA="$CORDIS_ROOT/.pgdata" uv run pytest -q
```

Because P09 changes the numbered SQL tree and compiled plugin catalog, all three levels are mandatory before implementation review.

---

## Tradeoffs

1. **Catalog-selected handler versus direct call.** The resolver adds a small runtime lookup, but it fulfills P06’s queue-dispatch ownership and avoids hard-coding a second handler registry.
2. **Direct COMMENT on `step_once`.** This preserves one step body and one function identity, but the canonical P09 acceptance handler remains a P05 mock rather than a complete isolated coding driver.
3. **No-grant queue ABI.** This deliberately limits P09 handlers, but it prevents a handler requiring slice grants from bypassing P08 through an ABI that has no slice argument.
4. **Paradigm validation without fold consumption.** The stored discriminator is real and revalidated, while fold/parser integration remains incomplete. Calling and discarding a fold would be worse because it would falsely imply isolation.
5. **Read-only tool helper only.** It proves in-db catalog execution and host refusal without entering P16 recovery semantics. Transactional tools must wait for an atomic scoped-result contract.
6. **One SQL transaction per worker call.** This gives clean rollback for the current mock and in-db effects but is not a proof for long external HTTP calls. P10 and later transport work must preserve stable provider keys and short transaction boundaries.
7. **Wait as acknowledgement, not instruction.** This supports a correct P03-aware handler without inventing an incomplete event payload ABI.
8. **Handler exceptions propagate.** Poison handlers can remain pending until repaired, but P09 does not misclassify unbounded database failures before P04 retry exists.
9. **One row for idle.** Polling is explicit and observable, at the cost of one nullable result shape.

---

## Risks and rollback

### Legacy P05 path is not isolated

`kernel.step_once` still folds all run history and emits unscoped events. The P09 catalog description, README, and tests must label it as a proof handler. It must not be offered as a user-facing isolated coding worker.

Mitigations: queue resolver rejects handlers that declare required grants; tool execution uses P08 authorization; no P09 statement claims that `worker_step` itself closes the fold seam; a later real driver must consume `fold_slice_messages` rather than replacing this warning with documentation.

### One transaction can hold database resources during handler execution

The current canonical handler uses a bounded SQL mock, so P09 does not solve long external transport transactions. A future in-db HTTP handler must not be enabled merely because it matches the queue signature; its transaction/lease behavior requires a later plan.

### Trusted control-plane APIs

A database principal with arbitrary SQL can call `enqueue_job`, modify COMMENT metadata, or invoke `worker_step`. P09 follows P07/P08’s current same-role trust boundary and does not claim SQL-level tenant authentication.

Mitigation: P10 and later model-tool routing must not expose P09 control-plane functions as tools.

### Runtime catalog drift

A queued job may reference a handler removed by a later catalog refresh. P09 terminalizes this as `P09_HANDLER_UNAVAILABLE`. Repair requires a new run because P01 keeps one unique jobs row per run and no retry machine exists.

### In-place rollback

Removing `0021` from a source directory and replaying in place will not remove already-created functions or the COMMENT. Supported rollback is reset/recreate the database, or append a later reversal SQL file. Do not edit or delete `0021` as a release migration.

### Migration

There is no table/schema migration and no external public API compatibility promise before P09. Existing jobs rows are preserved. They become worker-compatible only if their `job_type` and payload satisfy the P09 contract.

---

## Implementation order

1. Complete the P09 plan critique and fold every P0/P1 into this document. **Done:** `docs/reviews/2026-08-25-p09-plan-critique.md`; P1 fixture discipline and P2 nits folded. Do not start SQL until this document stays `ready to implement`.
2. Create `sql/0021_p09_in_db_worker.sql` with W90–W95 as one coherent file: queue resolver; enqueue API; read-only tool dispatcher; worker state machine; COMMENT metadata on the existing `step_once`; `refresh_plugins()`; `get_schema_version() → 'p21'`.
3. Apply to a disposable database and smoke-check: `p21`; canonical catalog row; direct step entrypoint OID; enqueue → one `yield`; no new table/type/extension.
4. Update `sql/README.md`.
5. Retarget complete-tree test pins and exact catalog/function inventories. Keep all truncated-tree markers unchanged.
6. Add `tests/test_p09_in_db_worker.py`, first covering catalog/enqueue, then worker outcomes, then tool dispatch, replay, and source boundaries.
7. Run the focused P09 module.
8. Run the cross-version protocol suite.
9. Run the full suite on a clean tree.
10. Inspect the complete diff and ensure the ship set contains only P09 files and required current-tree assertion updates.
11. Follow the `AGENTS.md` implementation Oracle loop. Record the latest verdict in `docs/reviews/2026-08-25-p09-implementation-oracle.md`.
12. After a passing Oracle review, commit and push the P09 ship set immediately. Any behavioral change after the passing review requires another review.

Steps 2, 5, and 6 must be atomic in the final commit because the current-tree catalog/file pins cannot pass with only one side landed.

---

## Open questions

None remain for P09 implementation. Mid-flow confirmed: `invoke_in_db_tool` ships; wait is P03 acknowledgement; `step_once` is COMMENT-registered as `kernel.step_once`.

Explicitly deferred:

- host SQL seam and provider canonicalization — P10;
- alternating in-db/host claim proof — P11;
- real selection and prompt-fold consumption — P13/P15 or a dedicated later driver file;
- transactional/external tool call/result recovery — P16;
- async spawn — P17;
- retry and sleep state machine — P04;
- run-level paradigm column or admission record;
- run-scoped RLM env store;
- role/RLS authentication;
- a production isolated replacement for the P05 mock body.

---

## References

- `AGENTS.md` — plan gate, append-only SQL, test harness, Oracle implementation gate
- `docs/plans/2026-08-23-pg-cordis-development.md` — P09 skeleton and P10/P11/P17 boundaries
- `docs/decisions/2026-08-23-pending.md` — locked queue, worker, D1–D9 contracts
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — §4 locked architecture
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` — dual locus and scheduler state machine
- `docs/analysis/2026-08-23-g-rlm-one-step-driver.md` — research SQL only; do not lift as ABI
- `docs/plans/P01-jobs-claim-2026-08-23.md` — jobs/claim ownership
- `docs/plans/P05-one-step-driver-2026-08-24.md` — decisions 1–20, one invocation per claim, exhaustive outcome handoff, exception behavior
- `docs/plans/P06-plugin-catalog-2026-08-23.md` — catalog metadata, locus/invocation pairs, host rows without SQL stubs
- `docs/plans/P08-four-seam-enforcement-2026-08-24.md` — dispatch authorization, fold boundary, no `step_once` wrapper
- `docs/plans/P19-paradigm-policies-2026-08-24.md` — `paradigm_policy` ABI and consumer handoff
- `sql/0001_p01_claim.sql` — claim and scheduler transitions
- `sql/0002_p02_log.sql` — claimed append and log-derived state
- `sql/0003_p03_wait_event.sql` — atomic wait registration and WAITING transition
- `sql/0005_p05_one_step_driver.sql` — unchanged one-step body
- `sql/0006_p06_plugin_catalog.sql` — compiled catalog and refresh
- `sql/0019_p19_paradigm_policies.sql` — policy lookup
- `sql/0020_p08_four_seam_enforcement.sql` — tool authorization and readiness latch
- `sql/README.md` — numbered-tree and release rules
- `tests/conftest.py` — shared apply/psql/session helpers
- `tests/test_p01_claim.py` — mutual exclusion and yield/reclaim pattern
- `tests/test_p05_one_step_driver.py` — current manual claim/step/outcome mapping and `PROOF_PAYLOAD`
- `tests/test_p00_sql_source.py` — current-tree file, function, and marker pins
- `docs/reviews/2026-08-25-p09-plan-critique.md` — plan critique; P1/P2 folded into this document
