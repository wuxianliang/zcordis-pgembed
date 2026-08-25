## Final Prompt
<taskname="P09 in-db worker plan"/>

<task>
Write the complete implementation-ready deep plan for pg_cordis P09 (in-database worker). The orchestrator will integrate your output into `docs/plans/P09-in-db-worker-2026-08-25.md`. Produce a full specification, not a short approach or checklist.

This is plan-only. Do not implement SQL or tests. Honor locked contracts D1–D9 and architecture snapshot §4; do not reopen them. Do not lift `scratch/` or `docs/analysis/2026-08-23-g-rlm-one-step-driver.md` SQL as ABI (semantics only). Do not `CREATE EXTENSION`. Do not add a second jobs queue. Do not pin `pg_temp` / session TEMP. Do not implement P10 host SDK, P11 dual-worker proof, P04 sleep/retry SQL, P17 spawn, or file-editing plugins. Do not wrap or replace `cordis.step_once` (P08 mid-flow lock). Append-only SQL: new file `sql/0021_p09_in_db_worker.sql`; replace `cordis.get_schema_version()` in that new file so the full tree reports `p21`; dollar-tag `$p09$` by plan number (P08 precedent: file `0020` reports `p20`, tag `$p08$`).

Parent skeleton P09 (`docs/plans/2026-08-23-pg-cordis-development.md:216-224`): `worker_step` = claim → one step → yield/wait/complete; only `locus=in-db` tools; no file edits; no session TEMP; done when a single worker drives mock coding/readonly to yield then reclaim.

Resolve the scaffold's five open questions from existing evidence and name the pick plus rejected alternative. Follow the full output structure and specificity of your planning instructions: current-state analysis, component and interface design (exact function signatures, return vocabulary, error codes, transaction/lease behavior), file-by-file impact, state and data flow, errors and edge cases, tradeoffs, risks, implementation order, and verification. Preserve detailed rationale. Use W90–W99 for execution-index work items unless a collision forces otherwise.

Existing tests/helpers to reuse: `run_apply`, `psql`, `psql_session` in `tests/conftest.py`. New tests go in `tests/test_p09_in_db_worker.py`. Retarget `tests/test_p00_sql_source.py` current-tree pins (`p20` → `p21`, add `0021`). Do not create a second apply path.

Follow the house deep-plan shape used by P08 (`docs/plans/P08-four-seam-enforcement-2026-08-24.md`): header metadata, Summary, Goal / non-goals, Execution index, Background, Design (resolved decisions table with rejected alternatives), Work items with verification, Risks, References. Status in your output can be `ready to implement` pending critique; the orchestrator owns the file.
</task>

<architecture>
pg_cordis ships as a canonical, append-only tree of numbered SQL files (`sql/0000`…`0020`) in schema `cordis`, applied whole-tree by one apply path (exercised in tests via `run_apply`/`psql`/`psql_session` from `tests/conftest.py`). Each file replaces `cordis.get_schema_version()`; the highest prefix wins (`p20` today → P09 makes it `p21`). Layering the worker sits on top of:

- **P01 claim protocol** (`sql/0001`): `cordis.jobs` is the single queue and authority (`claim_token`/`claimed_by`/`claim_expires_at`). Verbs: `claim_job(p_run_id,p_worker,p_lease DEFAULT 90) RETURNS SETOF cordis.jobs` (NULL run_id = any PENDING), `renew_claim`, `yield_claim`, `complete_claim`, `fail_claim` (all boolean, fenced on `status='RUNNING' AND claim_expires_at > clock_timestamp()`), `release_stale`. No enqueue function exists; tests INSERT directly.
- **P02 log** (`sql/0002`): `cordis.agent_steps` append-only log; `emit_step_claimed` is the authoritative mutation fence (extends lease, fails closed on dead claim); `next_step_name`, `llm_checkpoint`, `run_state`. Kinds include `run/yield`, `run/await` (reserved).
- **P03 wait** (`sql/0003`): `await_event` sets `status='WAITING'` and clears claim; `claim_job` only picks PENDING.
- **P05 step body** (`sql/0005`): `cordis.step_once(p_run_id,p_claim_token,p_extend DEFAULT 90) RETURNS text` — runs at most one step, **never mutates jobs.status**, returns `yield|complete|fail|wait|lost_claim` (`wait` unreachable/fail-closed today). Mock LLM via `cordis.invoke_llm` hook reading `jobs.payload.mock_llm`; mock tool `mock.observe` from `jobs.payload.mock_tools`. P05 decisions 11/19: the **caller** (P09) owns the outcome→verb state machine and serialization.
- **P06 catalog** (`sql/0006`): `cordis.plugin_catalog` — `locus ∈ {in-db, host}`, legal pairs in-db+`queue`/`session_select`, host+`host_tool`; in-db rows have non-null `entrypoint regprocedure`; host rows have **no SQL stub** (must never be EXECUTE'd). `refresh_plugins()` compiles from COMMENT-on-function + `host_plugin_definitions`.
- **P19 policies** (`sql/0019`): `cordis.paradigm_policy(identity)` is the kernel ABI (STABLE, full row, 22023 on unknown) — kernel SQL must call the function, never SELECT the table or CASE the identity. Seeds `codeact`, `rlm`.
- **P08 seams** (`sql/0020`): `authorize_tool_dispatch(...) RETURNS jsonb` descriptor (includes locus/entrypoint; **executes nothing**; does not filter locus) and `fold_slice_messages`. Mid-flow lock: do not wrap/replace `step_once`. No descriptor caching across claims.

P09 adds the missing outer loop: `worker_step` = claim → one `step_once` → P01 verb transition, plus the enqueue and in-db `EXECUTE` dispatch story. Nothing above it changes.
</architecture>

<selected_context>
Ground truth (full files):
- `docs/plans/P09-in-db-worker-2026-08-25.md` — **the scaffold you build on**: curated Background (file:line evidence, ownership table) + five Open Questions + References. Start here.
- `docs/plans/P08-four-seam-enforcement-2026-08-24.md` — full house deep-plan shape to mirror (header, Summary, Goal/non-goals, Execution index, Background, Design w/ rejected alternatives, Work items+verification, Risks, References); also the seams P09 must consume.
- `docs/plans/2026-08-23-pg-cordis-development.md` — parent skeleton P00–P20 (P09 at :216-224; P10/P11/P17 dependencies).
- `docs/decisions/2026-08-23-pending.md` — locked D1–D9 + Worker/Queue rows. Do not reopen.
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — §4 locked contracts.
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` — §9 dual-locus, §11 state machine, §12 chaining unfrozen.
- `sql/0000_kernel.sql` … `sql/0020_p08_four_seam_enforcement.sql` + `sql/README.md` — the entire product tree (all files listed in architecture above; README covers numbering/apply conventions).
- `tests/conftest.py`, `tests/test_p00_sql_source.py` (retarget target: pins at :76-97), `tests/test_p05_one_step_driver.py` (closest test template: `_claim`→`_step`→`_map_outcome` stitching at :102-149, fixtures :91-98), `AGENTS.md` (house rules; rule 5 append-only).
Decision tables (slices):
- `docs/plans/P05-one-step-driver-2026-08-24.md` :380-450 (decisions 1-20 + G/scratch difference list) and :1530-1572 (edge cases: 23505 propagation, rollback, dropped transition; tradeoffs incl. P09 exhaustive-CASE duty).
- `docs/plans/P06-plugin-catalog-2026-08-23.md` :243-289 (hard constraints + resolved questions) and :506-535 (host registration: why no stub functions).
- `docs/plans/P19-paradigm-policies-2026-08-24.md` :224-247 (decisions 1-13), :466-501 (`paradigm_policy` exact ABI), :739-751 (consumer handoff).
- `tests/test_p01_claim.py` :1-56 (module conventions) and :133-189 (`test_mutual_exclusion_and_yield_reclaim` — the two-session yield/reclaim proof your done-when mirrors).
</selected_context>

<relationships>
- worker_step(p_worker, p_lease[, p_run_id]) → `claim_job` (or NULL-poll) → `step_once(run_id, token, extend)` → exhaustive CASE on text outcome → `yield_claim` / `complete_claim` / `fail_claim` (P01 verbs, boolean-fenced).
- Tool dispatch path (open question 1/5): `authorize_tool_dispatch` → descriptor.locus must be `in-db` → `EXECUTE format(... entrypoint ...)`; host rows refused. `fold_slice_messages` on the fold side. `paradigm_policy(identity)` if/where policy is read on that path.
- `step_once` internally fences every append through `emit_step_claimed` (P02), which also extends the lease — the worker adds no second heartbeat (P05 decision 17).
- `claim_job` picks only PENDING; `await_event` (P03) is the only WAITING entry point — relevant to open question 4 (`wait` mapping).
- Tests: `run_apply` applies the whole tree → `psql_session` for two-connection proofs → assert via `cordis.run_state` / `jobs` / `agent_steps`.
</relationships>

<ambiguities>
None introduced by curation. The scaffold's five Open Questions (worker body vs step_once vs catalog EXECUTE; enqueue shape; poll vs named run_id; `wait` mapping; paradigm_policy/fold usage in this P) are genuine and are yours to resolve from the included evidence — each with a named pick and rejected alternative.
</ambiguities>

<curation_notes>
- Full P01/P05/P06/P19 plan docs were pruned for budget: their load-bearing decision tables and edge-case sections are included as slices; their background/current-state prose duplicates what the P09 scaffold Background already cites with file:line anchors (trust the scaffold's citations — they were verified against these files).
- `docs/analysis/2026-08-23-g-rlm-one-step-driver.md` and `scratch/yield_walkthrough/` are deliberately **excluded** (research SQL, banned as ABI; the scaffold summarizes the semantics you may borrow).
- `sql/0007_p07_grant_registry.sql` excluded: P08's `authorize_tool_dispatch` does not consult it (verified), and the scaffold assigns no grant work to P09.
- Deliverable is the plan document content only (status `ready to implement`); the orchestrator writes `docs/plans/P09-in-db-worker-2026-08-25.md`. Do not edit files.
</curation_notes>

## Selection
- Files: 23 total (19 full, 4 slice)
- Total tokens: 108075 (Auto view)
- Token breakdown: full 99611, slice 8464
- Token accounting: incomplete from active_tab_published; refresh pending; incomplete: codemap_presentation

### Files
### Selected Files
zcordis-pgembed/
├── docs/
│   ├── analysis/
│   │   ├── 2026-08-23-f-yield-loop-protocol-sketch.md — 4,340 tokens (full)
│   │   └── 2026-08-23-i-architecture-snapshot.md — 3,610 tokens (full)
│   ├── decisions/
│   │   └── 2026-08-23-pending.md — 8,250 tokens (full)
│   └── plans/
│       ├── 2026-08-23-pg-cordis-development.md — 4,379 tokens (full)
│       ├── P05-one-step-driver-2026-08-24.md — 3,696 tokens (lines 380-450 (P05 locked decisions 1-20 (step_once name, wait fail-closed, enqueue parked to P09, invoke_llm hook, outcome text vocabulary, no status mutation, one-execution-per-claim), user mid-flow confirmations, and the G/scratch-to-P05 difference table (why rlm_enqueue/worker_step/compat loops are non-product). Direct constraints on P09's worker state machine and outcome mapping.), 1530-1572 (P05 edge cases the worker inherits: duplicate execution with one token (unique-violation 23505 propagates unchanged), transaction rollback semantics, dropped transition response (read jobs/log by run_id), and tradeoffs 1-10 including the exhaustive-CASE requirement for P09 outcome mapping.))
│       ├── P06-plugin-catalog-2026-08-23.md — 1,665 tokens (lines 243-289 (P06 hard constraints (append-only, no GRANT/EXTENSION/tx-control, catalog rows are declarative metadata that cause no execution, comment-source vs host-registration semantics) and the resolved-questions table (locus/invocation legal pairs, host tools have no stub functions so they are not SQL-executable).), 506-535 (P06 Component 4: register_host_plugin/unregister_host_plugin contract — why host tools have no stub function (P09 must not treat them as in-db executable) and why direct INSERT into plugin_catalog is invalid.))
│       ├── P08-four-seam-enforcement-2026-08-24.md — 16,066 tokens (full)
│       ├── P09-in-db-worker-2026-08-25.md — 2,742 tokens (full)
│       └── P19-paradigm-policies-2026-08-24.md — 2,228 tokens (lines 224-247 (P19 resolved decisions 1-13 (paradigm_policies table, filename/marker convention, identity grammar open not enum, dispatch ABI is function slots, jobs.job_type is handler label not paradigm, env declarative, spawn admission, seed/replay ownership).), 466-501 (P19 cordis.paradigm_policy(text) exact ABI: STABLE, RETURNS TABLE of all columns, errcode 22023 on unknown identity — the function P09/P05/P10 must call instead of SELECTing the table or CASEing the identity string; plus exact signature and volatility/prosecdev assertion list.), 739-751 (P19 'What P05 must consume' handoff section: how driver-side consumers are expected to use paradigm_policy and the dispatch slots.))
├── sql/
│   ├── 0000_kernel.sql — 97 tokens (full)
│   ├── 0001_p01_claim.sql — 2,118 tokens (full)
│   ├── 0002_p02_log.sql — 3,446 tokens (full)
│   ├── 0003_p03_wait_event.sql — 4,673 tokens (full)
│   ├── 0005_p05_one_step_driver.sql — 6,070 tokens (full)
│   ├── 0006_p06_plugin_catalog.sql — 6,867 tokens (full)
│   ├── 0019_p19_paradigm_policies.sql — 6,564 tokens (full)
│   ├── 0020_p08_four_seam_enforcement.sql — 7,493 tokens (full)
│   └── README.md — 2,205 tokens (full)
├── tests/
│   ├── conftest.py — 1,253 tokens (full)
│   ├── test_p00_sql_source.py — 5,156 tokens (full)
│   ├── test_p01_claim.py — 875 tokens (lines 1-56 (P01 test module header: imports (psql, psql_session, run_apply from conftest), P01_DB name, NAMED_CONSTRAINTS and FUNCTION_IDS assertion tuples, and the _ensure_p01 apply-or-reset helper. Shows the house test conventions the new tests/test_p09_in_db_worker.py must follow.), 133-189 (test_mutual_exclusion_and_yield_reclaim: the existing two-connection proof (session A claims, session B fenced out, A yields, B reclaims) that P09's worker_step yield-then-reclaim done-when is built on. Direct template for the P09 single-worker mock walk test.))
│   └── test_p05_one_step_driver.py — 12,051 tokens (full)
└── AGENTS.md — 2,231 tokens (full)


---

## Generated Plan

## Chat Send ✅
- **Chat**: `p09-in-db-worker-plan-F828E4` | **Mode**: plan

### Response


# P09 — In-database worker

Date: 2026-08-25  
Status: **ready to implement pending plan critique**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P09  
Depends on: P05, P06 (implemented); P08 and P19 are present in the current product tree and constrain dispatch and policy lookup  
Parallel with: P10  
Contract: one `cordis.jobs` queue; in-database and host workers share P01 claim verbs; one worker invocation executes at most one step; in-database tool execution permits only catalog entries with `locus='in-db'`  
Primary deliverable: `sql/0021_p09_in_db_worker.sql`  
Critique: `docs/reviews/2026-08-25-p09-plan-critique.md` — must exist and have all P0/P1 findings folded into this plan before implementation  
Implementation review: `docs/reviews/2026-08-25-p09-implementation-oracle.md`  
SQL marker: `p21`  
PL/pgSQL dollar tag: `$p09$`

## Summary

P09 adds a targeted scheduler and dispatch layer over the existing kernel rather than refactoring the P05 step body. It introduces a handler-aware `enqueue_job`, a single-call `worker_step` that performs `claim_job → one catalog-selected queue handler invocation → exhaustive outcome transition`, and a claim-bound `invoke_in_db_tool` path that authorizes a read-only `session_select` plugin through P08 before dynamically executing it. The existing `cordis.step_once` function is neither replaced nor wrapped; P09 registers that exact function as the canonical `kernel.step_once` queue handler through P06 COMMENT metadata so the worker can reproduce the P05 three-step proof. P09 validates the run’s stored paradigm through `cordis.paradigm_policy`, but deliberately does not pretend that the legacy P05 fold is P08-isolated. No queue, table, retry machine, host SDK, file tool, TEMP state, or second loop engine is added.

---

## Goal

Ship an in-database worker surface that:

1. enqueues an immediately claimable job against a validated in-database queue handler;
2. claims at most one eligible row from the existing `cordis.jobs` queue;
3. invokes exactly one queue-handler execution under that claim;
4. maps the handler’s result through the existing P01/P03 state machine;
5. yields after one P05 step so the same row can be reclaimed by a later worker invocation;
6. validates in-database tool descriptors through P08 and refuses host, queue, mutating, or ABI-incompatible tool entries;
7. records no duplicate scheduler state and does not bypass the existing claim/log mutation fences.

The acceptance proof is one run enqueued for `kernel.step_once`, processed by three separate `worker_step` calls with outcomes `yield`, `yield`, and `complete`, producing the existing P05 log sequence:

```text
llm/s-1 → tool/s-1 → llm/s-2 → tool/s-2 → llm/s-3 → final/s-3
```

The first two calls must return the job to `PENDING`; the third must leave the same jobs row `DONE`.

### Explicit non-goals

P09 does **not**:

- create a second jobs table, queue, scheduler, or claim protocol;
- create or replace `cordis.step_once`;
- create a wrapper that copies or delegates the P05 step state machine;
- copy SQL from `scratch/yield_walkthrough/` or `docs/analysis/2026-08-23-g-rlm-one-step-driver.md`;
- add P04 sleep, backoff, retry, deadline expiry, or dead-letter behavior;
- implement a host SDK or P10 SQL client wrapper;
- prove in-database/host alternation; P11 owns that proof;
- implement file edits, worktrees, host tools, external effects, or P16 call/result recovery;
- implement spawn or child admission; P17 owns it;
- add `pg_temp`, TEMP views, backend affinity, or a session-pinned loop;
- add an env store or `rlm_vars`;
- add a new isolated fold or call-and-discard a P08 fold result;
- expose grant-requiring queue handlers through the P09 v1 queue ABI;
- execute `plugin_catalog` rows with `locus='host'`;
- execute transactional or external `session_select` tools;
- call `await_event` on behalf of a textual `wait` outcome;
- create an extension, role, privilege, public object, or transaction-control statement;
- change historical numbered SQL files as the release mechanism.

---

## Execution index

P08 used W80–W88. P09 uses W90–W99.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W90 | Define and validate the P09 queue-handler ABI | `_resolve_in_db_queue_handler` accepts only grant-free, P09-compatible, in-database `queue` handlers with exact `(text,uuid,integer) → text` ABI; `cordis.step_once` is registered directly as `kernel.step_once` without replacement or wrapper | `sql/0021_p09_in_db_worker.sql` | P05, P06 | Medium |
| W91 | Add handler-aware enqueue | `enqueue_job` validates run, handler, paradigm, payload, and priority; stores the normalized paradigm in `jobs.payload`; inserts exactly one PENDING row into the existing queue | same | W90, P01, P19 | Medium |
| W92 | Add authorized read-only in-database tool invocation | `invoke_in_db_tool` verifies a live claim, calls `authorize_tool_dispatch`, admits only in-db `session_select` read-only plugins with exact `(jsonb) → jsonb` ABI, executes once, and rejects a result if the claim expires before return | same | P01, P06, P08 | Large |
| W93 | Add one-claim/one-handler worker orchestration | `worker_step` validates input, requires the P08 latch, calls `claim_job` once, validates the stored paradigm and queue handler, invokes the handler once, and never loops | same | W90–W91, P01, P05, P19 | Large |
| W94 | Complete exhaustive outcome mapping | `yield`, `complete`, `fail`, `wait`, `lost_claim`, NULL, and unknown handler outcomes have the exact transitions and failure contracts specified below | same | W93, P01–P03 | Medium |
| W95 | Publish P09 metadata and version | P09 COMMENT metadata compiles to one canonical `kernel.step_once` row; replay preserves other plugin sources; full tree reports `p21`; README documents the API and isolation boundary | `sql/0021_p09_in_db_worker.sql`, `sql/README.md` | W90–W94 | Small |
| W96 | Retarget current-tree test pins | Every test using the full current SQL tree expects `0021`/`p21`; intentionally truncated P01/P03/P05/P07/P19 trees retain their own earlier marker | existing test modules | W95 | Medium |
| W97 | Add catalog and enqueue tests | New P09 module proves signatures, metadata, handler validation, paradigm storage, duplicate-run behavior, and replay | `tests/test_p09_in_db_worker.py` | W90–W91, W95 | Medium |
| W98 | Add worker and tool-dispatch protocol tests | New module proves idle polling, one-job/one-step behavior, yield/reclaim, terminal mapping, wait acknowledgement, exception rollback, exact tool target/locus/effect/ABI checks, and lease fencing | `tests/test_p09_in_db_worker.py` | W92–W94 | Large |
| W99 | Source-boundary and regression gate | P09 source contains no forbidden architecture, existing P01/P02/P03/P05/P06/P07/P08/P19 behavior remains green, full suite passes, then the AGENTS implementation Oracle gate is completed | SQL/docs/tests/review | W90–W98 | Medium |

W90–W95 form one numbered-file contract and must land atomically. The final implementation commit must also include W96–W98 because current-tree source tests will fail after `0021` exists but before their catalog and marker pins are updated.

---

## Background

### Locked architecture

The following are inherited and not reopened:

- `cordis.jobs` is the one scheduler and authoritative claim owner.
- The append-only `cordis.agent_steps` log remains the sole historical truth.
- Both in-database and host workers use the same P01 verbs and fencing rules.
- One step is one LLM response plus its ordinary tools; P09 does not chain steps under one claim.
- Child runs always enqueue, but spawn itself is outside P09.
- No session affinity or `pg_temp` state may survive a yield.
- P09 remains canonical SQL in this repository and does not introduce `CREATE EXTENSION`.
- Host and external tool recovery remain later plans.
- P08’s four-seam latch remains fail-closed.
- P19 policies are obtained through `cordis.paradigm_policy(text)`, not by querying `paradigm_policies` directly or branching on `codeact`/`rlm`.

### Existing kernel responsibilities

| Existing component | Current responsibility | P09 use |
|---|---|---|
| `cordis.jobs` | One row per run; scheduling and live claim state | Reused unchanged; P09 inserts through `enqueue_job`, claims through `claim_job`, and transitions through P01 verbs |
| `claim_job` | Reaps stale claims, then atomically claims one eligible PENDING job using `FOR UPDATE SKIP LOCKED`; NULL run means queue poll | Called exactly once per `worker_step` |
| `yield_claim` | `RUNNING → PENDING`, clears claim fields | Maps successful handler `yield` |
| `complete_claim` | `RUNNING → DONE`, stores result, clears claim | Maps valid handler `complete` |
| `fail_claim` | `RUNNING → ERROR`, stores reason, clears claim | Maps handler or worker protocol failure |
| `agent_steps` / `emit_step_claimed` | Append-only log and authoritative claim-fenced append | Existing P05 handler writes through it; P09 synthetic failures also use it |
| `step_once` | Runs at most one P05 mock step and returns a text outcome without mutating jobs status | Registered directly as the first P09 queue handler and invoked dynamically |
| `await_event` | Atomically appends `run/await`, creates `run_waits`, changes job to WAITING, clears claim | P09 does not call it; a future-compatible handler may call it before returning `wait` |
| `plugin_catalog` | Compiled metadata; in-db rows have SQL entrypoints, host rows do not | Queue resolution and tool execution use the existing catalog |
| `authorize_tool_dispatch` | Checks calling slice’s concrete live bindings and returns a descriptor; does not execute | Mandatory authorization boundary for `invoke_in_db_tool` |
| `paradigm_policy` | Validates and returns the current loop policy row | Enqueue and every claimed execution validate the stored paradigm through this ABI |
| `fold_slice_messages` | Slice-aware isolated fold | Not invoked by P09’s unchanged P05 proof body; see resolved decision 5 |

### Current end-to-end flow

Before P09, the production SQL tree stops after the step body:

```text
test/client INSERT jobs
  → claim_job
  → step_once
  → Python test CASE
      → yield_claim | complete_claim | fail_claim
```

The transition mapping exists only in `tests/test_p05_one_step_driver.py`. There is no producer API that validates `job_type`, no worker function, and no SQL-owned dynamic execution of queue handlers. P06 catalog rows are declarative only. P08 authorizes a tool descriptor but deliberately does not execute it.

The missing layer is therefore an outer scheduler and dispatch seam, not another LLM loop implementation.

---

## Current-state analysis

### Ownership and mutation points

1. **Job creation**
   - Current tests insert directly into `cordis.jobs`.
   - `job_type` is not validated and can be blank or refer to no catalog row.
   - `jobs.payload` may be any non-null JSONB shape; P05 performs its own mock validation.
   - P19 has no guaranteed run discriminator because P05 did not own enqueue.

2. **Claim**
   - `claim_job` owns stale release, queue ordering, token generation, and claim expiry.
   - It returns zero rows if no job is eligible.
   - It supports both named-run claims and queue polling without an overload.

3. **Step execution**
   - `step_once` performs an exact claim read and appends through `emit_step_claimed`.
   - It never changes `jobs.status`.
   - It may return `yield`, `complete`, `fail`, or `lost_claim`; `wait` remains part of the documented vocabulary but is unreachable because P05 converts a wait action into `P05_WAIT_UNSUPPORTED` and returns `fail`.
   - Unhandled invariant failures such as duplicate LLM append `23505` propagate.

4. **Outcome transition**
   - P01 transition functions all return boolean and fence on the live token and lease.
   - P05 tests currently perform the CASE in Python.
   - A false transition means ownership was lost; no alternate update is permitted.

5. **Queue-handler metadata**
   - P06 allows `in-db + queue` but imposes no queue function signature.
   - Host plugins have no SQL entrypoint.
   - A P09 worker therefore needs a stricter executable ABI layered over P06 metadata rather than changing P06’s table or validator.

6. **Tool metadata**
   - P08 authorization returns `locus`, `invocation`, `effect_class`, `retry_class`, `reconciliation`, and `entrypoint`.
   - It does not filter locus and does not execute.
   - P09 must revalidate the descriptor for in-database execution and must not cache it across claims.

7. **Isolation**
   - P05 `step_once` still folds all run history and appends unscoped events.
   - P08 explicitly left it unchanged and tests that it remains legacy/unfiltered.
   - Calling `fold_slice_messages` and discarding its output would not make `step_once` isolated. P09 must not claim otherwise.

### Blocking gaps

- No SQL function owns the claim → step → transition sequence.
- No trusted enqueue API binds a job to a real queue handler and a valid paradigm.
- No exact executable ABI distinguishes valid queue entrypoints from arbitrary P06 functions.
- No in-database tool invocation chokepoint combines P08 authorization with locus/effect/function-shape enforcement.
- No SQL-level handling exists for idle polling, handler disappearance, unknown outcomes, wait acknowledgements, or dropped transition ownership.

### Reuse instead of duplication

P09 must reuse:

- `claim_job(NULL, ...)` for polling;
- P01 transition verbs without reproducing their `UPDATE` predicates;
- `emit_step_claimed` for any synthetic worker error;
- `step_once` as the canonical initial queue body;
- `paradigm_policy` for policy identity;
- `authorize_tool_dispatch` for concrete slice-bound tool grants;
- `plugin_catalog.entrypoint regprocedure`;
- `refresh_plugins()` and COMMENT metadata;
- the existing apply loader and test fixtures.

P09 must not duplicate:

- stale-claim reaping;
- token generation or lease math;
- step-name/checkpoint/fingerprint logic;
- P05 mock LLM/tool logic;
- P08 grant parsing;
- P19 identity branching;
- P03 wait registration;
- an install/apply path.

---

## Design

## Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | **One catalog-selected queue-handler ABI; register the existing `cordis.step_once` directly as `kernel.step_once`.** P09 does not create a wrapper. `worker_step` resolves one `plugin_catalog` queue row and dynamically calls its entrypoint once. | P06 assigned dynamic in-db execution to P09, while P05 decisions 11/19 assign the outer transition and one-execution serialization to P09. COMMENT metadata can register the existing function without changing its body or signature. | Hard-code `worker_step → step_once` and ignore `job_type`; create `p09_step_once` as a second driver; copy the P05 body; replace P05; lift the G/scratch handler SQL. |
| 2 | **Add `cordis.enqueue_job`; `job_type` is a P09-compatible catalog identity and paradigm is an explicit enqueue argument stored in `jobs.payload.paradigm`.** | P05 explicitly parked handler-aware enqueue on P09. P19 requires the producer path to store a policy identity. Validating both at enqueue prevents silently creating poison jobs while retaining one jobs row. | Continue direct INSERT as the product ABI; accept arbitrary `job_type`; infer paradigm from `job_type`; add a `jobs.paradigm` column; create `agent_runs`; upsert duplicate runs. |
| 3 | **Use one poll-first `worker_step` signature with optional `p_run_id`, not overloads.** `p_run_id=NULL` delegates to `claim_job(NULL,...)`; a non-null value targets one run. | P01 already defines both behaviors in one signature. A single worker ABI is easier for P10/P11 and avoids overload ambiguity. | Separate `worker_step()` and `worker_step_run()` functions; always require a run id; reimplement queue polling. |
| 4 | **A `wait` outcome acknowledges a wait that the queue handler has already made durable through P03. P09 never derives event parameters and never calls `await_event`.** Valid WAITING state returns `wait`; a live RUNNING claim returning `wait` is converted to terminal `P09_WAIT_NOT_REGISTERED`. | `await_event` owns the only atomic log + side-table + WAITING transition. The textual handler result has no event key, await id, deadline, or metadata. P05 wait remains unreachable today, but the worker outcome vocabulary can safely support a future handler that performs P03 first. | Have the worker call `await_event` with invented/default parameters; treat every wait as yield; remove wait from the CASE; accept `wait` without checking durable state. |
| 5 | **Validate the stored paradigm through `paradigm_policy` at enqueue and on every claim. Do not call `fold_slice_messages` from the legacy P05 path.** P09 consumes P08 on actual tool dispatch through `invoke_in_db_tool`; the unchanged `kernel.step_once` queue handler remains explicitly non-isolated proof infrastructure. | P08 forbids replacing/wrapping `step_once`, and its tests prove the P05 fold is unfiltered. Calling the isolated fold without feeding its result into the driver would be security theater. P19 still requires kernel consumers to use its policy lookup ABI. | Query `paradigm_policies` directly; CASE on `codeact`/`rlm`; call and discard `fold_slice_messages`; claim that P05 becomes isolated because the latch is enabled; build a second isolated step driver in P09. |
| 6 | **P09 queue handlers must be grant-free and explicitly opt into `config.worker_abi='cordis.p09.queue.v1'`.** | The v1 queue signature has no `slice_id` or concrete grant bindings. Executing a grant-requiring queue handler would bypass P08. An explicit config marker prevents accidental execution of any P06 `queue` function that happens to share the same SQL signature. | Treat all `in-db + queue` rows as executable; union run grants; infer a slice; add slice arguments to `step_once`; authorize queue handlers through tool dispatch with fake bindings. |
| 7 | **Add a separate claim-bound `invoke_in_db_tool` for actual tool entrypoints. It permits only `in-db + session_select + read_only/replayable/none` descriptors with exact `(jsonb) → jsonb` ABI.** | P06 distinguishes queue handlers from session-select tools; P08 authorizes descriptors but executes nothing. Restricting P09 to read-only tools avoids stealing P16’s non-transactional recovery work and makes stale-result discard safe. | Execute host tools as SQL; execute queue handlers as tools; allow transactional/external effects without call/result recovery; let callers execute descriptor text themselves; add fake SQL stubs for host tools. |
| 8 | **`worker_step` returns one row with `{job_id, run_id, outcome}` and a closed outcome vocabulary.** | Polling needs an explicit `idle` result and callers need the selected run identity without receiving a live claim token. A result row is simpler to inspect than querying `claimed_by` during the same call. | Return only boolean; return the claim token; return zero rows on idle; expose arbitrary handler output; return a PostgreSQL enum. |
| 9 | **Unhandled queue-handler exceptions propagate unchanged and roll back the entire worker statement.** Expected configuration/dispatch failures detected before invocation are converted to durable P09 errors. | P05 requires invariant failures such as `23505` to propagate unchanged. Catching all executor errors would terminally consume transient failures before P04 exists. PostgreSQL rollback removes the claim and in-transaction log changes. | `EXCEPTION WHEN OTHERS` around the handler and `fail_claim`; swallow errors as `lost_claim`; add retry/backoff here. |
| 10 | **No direct jobs status mutation in P09.** Enqueue inserts PENDING; all post-claim status changes use P01 verbs or are already performed by P03 inside the handler. | Keeps one claim state machine and one authoritative set of fencing predicates. | Inline `UPDATE cordis.jobs SET status=...`; copy P01 predicates; add a worker status table. |
| 11 | **One `worker_step` SQL call is one transaction-local claim, handler invocation, and transition. Workers must commit after each non-idle call before calling again.** | Numbered SQL cannot issue transaction control. Autocommit gives the required step boundary; an explicit outer transaction remains the caller’s responsibility. | Commit inside PL/pgSQL; loop multiple claims in one call; hold one claim across multiple `step_once` invocations. |
| 12 | **P09 adds no run/yield log event.** | P05 decision 9 and P01’s existing `yield_claim` contract intentionally leave scheduler yield out of the log. P09 should not introduce a partial scheduler-history change. | Append `run/yield` before every `yield_claim`; replace P01 to combine both. |
| 13 | **The P08 feature latch is required before enqueue or claim.** | P09 is installed after P08 and must not continue offering worker entrypoints if the four-seam installation is later damaged. Requiring the latch does not falsely claim that the P05 body is isolated. | Ignore a missing P08 seam; perform a partial latch check; duplicate the readiness manifest. |

No implementation fork remains open after these decisions.

---

## Component 1 — Queue-handler resolution and canonical P05 registration

### `cordis._resolve_in_db_queue_handler`

**Kind:** internal SQL kernel function  
**Path:** `sql/0021_p09_in_db_worker.sql`  
**Owner:** called by `enqueue_job` and `worker_step`  
**Lifecycle:** stateless catalog lookup; no cached descriptor  
**Signature:**

```text
cordis._resolve_in_db_queue_handler(
    p_identity text
) RETURNS regprocedure
```

Properties:

- `STABLE`;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`;
- no overload.

Validation:

1. Trim `p_identity`.
2. Reject NULL, blank, >128-byte, or non-P06 identity grammar with `22023 P09_UNKNOWN_JOB_HANDLER`.
3. Read exactly one `cordis.plugin_catalog` row.
4. Missing row → `22023 P09_UNKNOWN_JOB_HANDLER`.
5. Require:
   - `locus = 'in-db'`;
   - `invocation = 'queue'`;
   - `entrypoint IS NOT NULL`;
   - `required_grants = ARRAY[]::text[]`;
   - `config->>'worker_abi' = 'cordis.p09.queue.v1'`.
6. Resolve the `regprocedure` to `pg_proc` and require:
   - ordinary function (`prokind='f'`);
   - not set-returning;
   - identity arguments exactly `(text, uuid, integer)`;
   - result exactly `text`;
   - `VOLATILE`;
   - `SECURITY INVOKER`;
   - pinned `search_path=pg_catalog`.
7. Return the exact `regprocedure`.

Failure groups:

| Failure | SQLSTATE | Stable fragment |
|---|---:|---|
| Invalid or missing identity | `22023` | `P09_UNKNOWN_JOB_HANDLER` |
| Wrong locus/invocation or non-empty required grants | `0A000` | `P09_JOB_HANDLER_NOT_IN_DB_QUEUE` |
| Missing compatibility marker or SQL ABI mismatch | `55000` | `P09_JOB_HANDLER_ABI_MISMATCH` |

The function reads `plugin_catalog` directly because this is trusted scheduler handler resolution, not a model-facing tool dispatch. It must not call `authorize_tool_dispatch` with fabricated slice bindings.

### Canonical queue-handler registration

P09 adds COMMENT metadata to the **existing** function identity:

```text
cordis.step_once(text,uuid,integer)
```

Compiled plugin identity:

```text
kernel.step_once
```

Required metadata decisions:

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
| `config.isolation` | `legacy_unscoped` |

The description must state that the current entrypoint is the P05 mock/proof body and is not the user-facing isolated driver.

After installing the COMMENT, `0021` calls the existing `cordis.refresh_plugins()` once. This rebuilds `plugin_catalog` from COMMENT sources plus existing `host_plugin_definitions`; it must not directly insert into the compiled catalog.

Replay reasserts the canonical COMMENT and rebuilds the catalog. Existing host registrations remain because their source rows are preserved.

---

## Component 2 — Handler-aware enqueue

### Interface

```text
cordis.enqueue_job(
    p_run_id     text,
    p_job_type   text,
    p_paradigm   text,
    p_payload    jsonb DEFAULT '{}'::jsonb,
    p_priority   integer DEFAULT 0
) RETURNS bigint
```

Properties:

- `VOLATILE`;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`;
- no overload;
- inserts into the existing `cordis.jobs` table only.

### Contract

1. Validate:
   - `p_run_id` is non-null and nonblank; preserve bytes exactly;
   - `p_payload` is a JSON object;
   - `p_priority` is non-null;
   - `p_paradigm` matches P19/P06 identity grammar after trimming;
   - caller payload does not already contain top-level `paradigm`.
2. Require the P08 isolation latch through `_require_isolation_feature()`.
3. Resolve `p_job_type` through `_resolve_in_db_queue_handler`.
4. Call `cordis.paradigm_policy(normalized_paradigm)`.
   - Do not query `cordis.paradigm_policies`.
   - Do not branch on known seed identities.
5. Construct stored payload by adding:
   - `paradigm: <normalized identity>`.
6. Insert one row:
   - `run_id = p_run_id`;
   - `job_type = normalized handler identity`;
   - `payload = augmented object`;
   - `priority = p_priority`;
   - rely on P01 defaults for `PENDING`, `attempt=1`, and immediate eligibility.
7. Return `job_id`.

P09 does not add `available_at` to this API. Delayed enqueue, sleep, and retry scheduling remain P04/P17 concerns.

### Persistence behavior

P09 adds no schema column. It establishes these producer contracts:

```text
jobs.job_type          = plugin_catalog.identity for a P09 queue handler
jobs.payload.paradigm  = normalized P19 policy identity
```

Older rows inserted manually remain valid P01 data, but `worker_step` treats a missing/invalid paradigm or non-catalog handler as a durable P09 protocol failure. No migration is required because no production worker existed before P09.

Duplicate `run_id` propagates the existing `jobs_run_id_key` `23505`. P09 must not convert duplicate enqueue into an upsert or silently reuse a terminal row.

### Concurrency

Handler and paradigm validation use the enqueue transaction’s snapshots. A later catalog refresh or policy unregister may invalidate them before execution; `worker_step` repeats both validations after claim. The jobs row remains authoritative rather than the enqueue-time lookup.

---

## Component 3 — Read-only in-database tool execution

### Interface

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

Properties:

- `VOLATILE`, because it dynamically invokes a catalog entrypoint even though admitted entries are read-only;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`;
- no overload;
- no descriptor cache;
- does not append log events or change jobs status.

### Why this is separate from `worker_step`

`worker_step` dispatches a trusted queue handler. A queue handler may eventually parse a model decision and request a tool. P08’s `authorize_tool_dispatch` is the mandatory model/tool authorization boundary. Combining queue and tool invocation would either require fake slice bindings for the queue handler or would allow tools to bypass P08.

### Algorithm

1. Validate:
   - run id nonblank;
   - token and slice id non-null;
   - plugin identity grammar;
   - bindings is a JSON object;
   - arguments is a JSON object.
2. Require the P08 latch.
3. Perform a non-mutating exact claim check:
   - same `run_id`;
   - same `claim_token`;
   - `status='RUNNING'`;
   - `claim_expires_at > clock_timestamp()`.
   - Missing/dead claim → `42501 P09_TOOL_CLAIM_REQUIRED`.
4. Call:

   ```text
   authorize_tool_dispatch(run_id, slice_id, identity, bindings)
   ```

   Preserve its `22023`/`42501` errors unchanged.
5. Validate the returned descriptor:
   - `locus = 'in-db'`;
   - `invocation = 'session_select'`;
   - `effect_class = 'read_only'`;
   - `retry_class = 'replayable'`;
   - `reconciliation = 'none'`;
   - non-null `entrypoint`.
6. Resolve the exact entrypoint and inspect `pg_proc`:
   - ordinary function;
   - one identity argument of type `jsonb`;
   - result `jsonb`;
   - not set-returning;
   - volatility `STABLE` or `IMMUTABLE`;
   - `SECURITY INVOKER`;
   - pinned `search_path=pg_catalog`.
7. Dynamically invoke the resolved schema-qualified function once with `p_arguments`.
   - Use the resolved `regprocedure`/OID to determine namespace and name.
   - Do not interpolate argument JSON into SQL text.
8. Reject SQL NULL result with `55000 P09_IN_DB_TOOL_INVALID_RESULT`. JSONB scalar/array/object values are permitted because P06 only promises JSONB.
9. Repeat the exact non-mutating claim check.
   - If the lease expired during execution, raise `55000 P09_TOOL_CLAIM_LOST`.
   - The tool is read-only, so discarding its result is safe and replayable.
10. Return an object shaped as:

```text
{
  "protocol": "cordis.p09.in_db_tool.v1",
  "identity": <catalog identity>,
  "descriptor": <fresh P08 descriptor>,
  "result": <entrypoint JSONB result>
}
```

### Error contract

| Condition | SQLSTATE | Stable fragment |
|---|---:|---|
| Invalid scalar/JSON argument | `22023` | `P09_INVALID_TOOL_REQUEST` |
| No live matching claim before execution | `42501` | `P09_TOOL_CLAIM_REQUIRED` |
| P08 latch/grant/control-plane denial | Preserve P08 state | Preserve P08 fragment |
| Host descriptor | `42501` | `P09_IN_DB_TOOL_LOCUS_REQUIRED` |
| Queue or host-tool invocation | `0A000` | `P09_IN_DB_TOOL_INVOCATION_UNSUPPORTED` |
| Transactional/external or non-replayable tool | `0A000` | `P09_IN_DB_TOOL_EFFECT_UNSUPPORTED` |
| Function-shape/security/search-path mismatch | `55000` | `P09_IN_DB_TOOL_ABI_MISMATCH` |
| SQL NULL result | `55000` | `P09_IN_DB_TOOL_INVALID_RESULT` |
| Claim expires during tool call | `55000` | `P09_TOOL_CLAIM_LOST` |

The entrypoint’s own SQL exception propagates unchanged. P09 does not classify or retry it.

### Log ownership

This helper returns a result but does not append `tool` history. The calling step body remains responsible for appending through `emit_step_scoped` or a later D2 call/result protocol. P09 only admits read-only replayable tools, so a crash before the caller records the result does not produce an unclassified mutation.

---

## Component 4 — In-database worker

### Interface

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

Properties:

- `VOLATILE`;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`;
- no overload;
- returns exactly one row per invocation.

Public outcome vocabulary:

```text
idle | yield | wait | complete | fail | lost_claim
```

`worker_step` never returns the live claim token.

### Input and polling

1. Validate worker id nonblank, optional run id nonblank when supplied, and positive lease.
2. Require the P08 isolation latch before claiming.
3. Call exactly once:

```text
claim_job(p_run_id, p_worker_id, p_lease_seconds)
```

4. If no row is returned:

```text
job_id = NULL
run_id = NULL
outcome = 'idle'
```

5. If a row is returned, retain its job id, run id, token, job type, and payload locally for this function invocation only.

No loop, retry, sleep, or second claim occurs inside the same call.

### Claimed-job validation

Before invoking the handler:

1. Require `jobs.payload` to be a JSON object.
2. Require `payload.paradigm` to be a valid nonblank identity string.
3. Call `cordis.paradigm_policy(payload.paradigm)`.
4. Resolve `jobs.job_type` through `_resolve_in_db_queue_handler`.

Expected validation failures are converted to a durable worker failure:

| Condition | Log payload code |
|---|---|
| Non-object payload or missing/invalid paradigm | `P09_JOB_PAYLOAD_INVALID` |
| `paradigm_policy` reports unknown/invalid identity | `P09_PARADIGM_UNAVAILABLE` |
| Handler missing, wrong locus/invocation/grants, or incompatible ABI | `P09_HANDLER_UNAVAILABLE` |

For these failures:

1. Build one error payload using protocol `cordis.p09.worker.v1`.
2. Append it as `kind='error'`, `step_name=NULL` using `emit_step_claimed`.
3. If append returns false, return `lost_claim`.
4. Call `fail_claim(token, same_error_payload)`.
5. Return `fail` if true, otherwise `lost_claim`.

Only the documented lookup/validation SQLSTATEs are caught in these narrow blocks. No broad exception handler surrounds the queue entrypoint.

### Handler invocation

Dynamically invoke the resolved handler exactly once:

```text
handler(run_id, claim_token, lease_seconds) → text
```

The canonical `kernel.step_once` row resolves directly to `cordis.step_once(text,uuid,integer)`.

The handler:

- owns its one-step log work;
- must not map jobs status except for an atomic P03 wait registration;
- must not loop;
- may return the documented step outcomes;
- may raise an exception, which propagates and rolls back the worker statement.

P09 does not call `renew_claim` before the handler. P05 retains its existing exact-read and `emit_step_claimed` fencing behavior.

---

## Component 5 — Outcome state machine

### Mapping

```text
PENDING --worker_step/claim_job--> RUNNING

handler "yield"
  → yield_claim(token)
  → PENDING
  → worker outcome "yield"

handler "complete"
  → require final log payload
  → complete_claim(token, final.payload)
  → DONE
  → worker outcome "complete"

handler "fail"
  → require latest error payload, or synthesize one
  → fail_claim(token, error.payload)
  → ERROR
  → worker outcome "fail"

handler "wait"
  → require handler already made P03 wait durable
  → WAITING with no claim and one matching run_waits row
  → worker outcome "wait"

handler "lost_claim"
  → no transition
  → worker outcome "lost_claim"

NULL/unknown handler result
  → append P09 protocol error
  → fail_claim
  → ERROR
  → worker outcome "fail"
```

### `yield`

- Call `yield_claim(token)` once.
- True → return `yield`.
- False → return `lost_claim`.
- Do not append `run/yield`.

### `complete`

1. Read the latest `final` event for the run.
2. If present:
   - call `complete_claim(token, final.payload)`;
   - true → `complete`;
   - false → `lost_claim`.
3. If absent:
   - synthesize `P09_COMPLETE_WITHOUT_FINAL`;
   - append/fail using the live token;
   - return `fail` or `lost_claim`.

A handler cannot mark a job DONE based only on its textual return.

### `fail`

1. Read the latest `error` event for the run.
2. If present, pass its payload to `fail_claim`.
3. If absent:
   - synthesize `P09_FAIL_WITHOUT_ERROR`;
   - append it through `emit_step_claimed`;
   - then call `fail_claim`.
4. Successful transition → `fail`; false fence → `lost_claim`.

### `wait`

P09 does not call `await_event`.

After the handler returns `wait`, read the current scheduler and wait state by run id:

Valid acknowledgement requires all of:

- `jobs.status='WAITING'`;
- `claim_token`, `claimed_by`, and `claim_expires_at` are NULL;
- exactly one `run_waits` row exists for the run;
- the jobs and wait rows satisfy the existing P03 foreign-key/state contract.

Valid state → return `wait`.

If the job is still RUNNING with the same live token:

- synthesize and append `P09_WAIT_NOT_REGISTERED`;
- call `fail_claim`;
- return `fail` or `lost_claim`.

If ownership/state has otherwise changed, return `lost_claim`. Do not overwrite a WAITING, PENDING, or terminal row using the old token.

### `lost_claim`

Return immediately without appending or transitioning. The next eligible claim or `release_stale` owns recovery.

### NULL or unknown outcome

- Build `P09_INVALID_STEP_OUTCOME` with the raw value represented as JSON null/string.
- Append through `emit_step_claimed`.
- Call `fail_claim`.
- Never treat an unknown value as yield.

This is the exhaustive CASE required by P05 decision 7.

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

---

## State and data flow

### Enqueue

```text
trusted producer
  → enqueue_job(run, handler, paradigm, payload, priority)
  → P08 readiness check
  → P06 queue-handler resolution
  → P19 paradigm_policy lookup
  → payload + immutable enqueue discriminator
  → INSERT cordis.jobs(status=PENDING)
```

Execution context: caller transaction. There is no autonomous commit. Duplicate runs are rejected by the existing unique constraint.

### Normal P05 worker call

```text
worker caller
  → worker_step(worker, optional run, lease)
  → P08 readiness check
  → claim_job
      → release_stale
      → SKIP LOCKED claim
  → jobs.payload.paradigm
  → paradigm_policy
  → jobs.job_type
  → _resolve_in_db_queue_handler
  → dynamic kernel.step_once(run, token, lease)
      → next_step_name / llm_checkpoint
      → invoke_llm mock
      → emit_step_claimed
  → exhaustive outcome CASE
  → P01 transition
  → return {job_id, run_id, outcome}
  → caller commits
```

All steps occur in the caller’s transaction and backend. No state depends on using that backend again after commit.

### In-database tool call

```text
claimed queue handler
  → invoke_in_db_tool(token, run, slice, tool, bindings, arguments)
  → exact claim read
  → authorize_tool_dispatch
      → current slice live grants
      → fresh descriptor
  → require in-db/session_select/read_only
  → validate regprocedure ABI
  → execute once
  → exact post-execution claim read
  → return descriptor + result
  → caller later appends observation under the same claim
```

P08 authorization is repeated per invocation. Neither descriptor nor grant result is persisted or cached by P09.

### Concurrency and ordering

- Two workers calling `worker_step(NULL run)` use the existing `SKIP LOCKED` mutual exclusion.
- One `worker_step` claims at most one row.
- Reusing the same worker id has no ownership effect; token identity remains authoritative.
- Yield clears the token before the worker result commits.
- Another worker may claim the row only after that transaction commits.
- Repeated worker calls after a successful yield see the next named step through P02/P05 log folding.
- An expired claim is reaped by the next `claim_job`; P09 does not add a timer.
- Catalog or grant changes committed after a statement snapshot affect the next resolver/authorization call. No descriptor is reused.
- A duplicate tool request may rerun only a read-only entrypoint; mutation classes are refused.

### Cancellation and rollback

If the worker SQL statement is cancelled or its handler raises:

- the claim update made by `claim_job` rolls back;
- P05 log rows and lease extensions in that transaction roll back;
- the jobs row returns to its pre-call state, normally PENDING;
- sequence gaps are acceptable;
- an external LLM implementation could still have accepted a stable provider key, which remains P05’s documented recovery model.

If a caller invokes `worker_step` inside a larger explicit transaction and does not commit, other workers cannot observe the yielded or terminal transition. The worker contract therefore requires one commit per non-idle call. P09 does not and cannot commit internally.

### Dropped responses

If the database commits but the client loses the `worker_step` response:

- inspect `cordis.jobs` by run id;
- inspect `agent_steps`/`run_state`;
- do not repeat a transition with an old token, which is never returned by P09 anyway.

---

## API changes

### Additive functions

| New identity | Result | Volatility |
|---|---|---|
| `cordis._resolve_in_db_queue_handler(text)` | `regprocedure` | STABLE |
| `cordis.enqueue_job(text,text,text,jsonb,integer)` | `bigint` | VOLATILE |
| `cordis.invoke_in_db_tool(uuid,text,uuid,text,jsonb,jsonb)` | `jsonb` | VOLATILE |
| `cordis.worker_step(text,text,integer)` | table `(job_id bigint, run_id text, outcome text)` | VOLATILE |

All are `SECURITY INVOKER`, pin `search_path TO pg_catalog`, and have no overloads.

### Modified interfaces

No existing callable signature changes.

The new file changes only these existing surfaces:

1. `COMMENT ON FUNCTION cordis.step_once(text,uuid,integer)` gains canonical P09 plugin metadata.
2. `cordis.refresh_plugins()` is invoked during apply, causing `kernel.step_once` to appear in the compiled catalog.
3. `cordis.get_schema_version()` changes from current-tree `p20` to `p21` in the new file.

### Backward compatibility

- P01/P03/P05-only trees retain their historical function behavior and markers.
- Direct `INSERT` into jobs remains possible for tests/control-plane SQL, but P09 only guarantees execution for rows satisfying its handler/paradigm contract.
- Existing `step_once` callers are unaffected because neither its signature nor body changes.
- P08’s `isolation_seams.gate_fn` OIDs remain valid because P09 does not replace any P08 function.
- Host plugin registrations remain source rows and are preserved across the P09 `refresh_plugins()` call.

---

## Error handling and edge cases

| Operation | Edge/failure | Behavior |
|---|---|---|
| Enqueue | Empty run or invalid scalar | `22023`; no row |
| Enqueue | Unknown/invalid handler | Resolver error; no row |
| Enqueue | Unknown paradigm | Preserve `paradigm_policy` `22023`; no row |
| Enqueue | Payload already has `paradigm` | `22023`; caller must use the explicit argument |
| Enqueue | Duplicate run | Existing `23505` propagates |
| Worker | No eligible job | One row, NULL ids, `idle` |
| Worker | Invalid input | `22023` before claim |
| Worker | P08 latch closed | `42501 P08_ISOLATION_FEATURE_CLOSED` before claim |
| Worker | Manually inserted malformed payload | Claimed job gets terminal `P09_JOB_PAYLOAD_INVALID` |
| Worker | Policy removed after enqueue | Claimed job gets terminal `P09_PARADIGM_UNAVAILABLE` |
| Worker | Handler removed/reclassified after enqueue | Claimed job gets terminal `P09_HANDLER_UNAVAILABLE` |
| Worker | Handler raises `23505` or another unhandled error | Exception propagates; whole worker statement rolls back |
| Worker | Handler returns NULL/unknown | Terminal `P09_INVALID_STEP_OUTCOME` |
| Worker | `complete` without final | Terminal `P09_COMPLETE_WITHOUT_FINAL` |
| Worker | `fail` without error | Terminal `P09_FAIL_WITHOUT_ERROR` |
| Worker | `wait` without P03 registration | Terminal `P09_WAIT_NOT_REGISTERED` if token remains live |
| Worker | Transition returns false | Return `lost_claim`; do not issue an unfenced fallback update |
| Worker | Existing final/error | Canonical P05 handler returns matching terminal outcome; worker maps latest payload |
| Tool | Unauthorized exact corpus/event target | Preserve P08 `42501` |
| Tool | Host plugin | `42501 P09_IN_DB_TOOL_LOCUS_REQUIRED` |
| Tool | Queue handler passed as tool | `0A000 P09_IN_DB_TOOL_INVOCATION_UNSUPPORTED` |
| Tool | Transactional/external effect | `0A000 P09_IN_DB_TOOL_EFFECT_UNSUPPORTED` |
| Tool | Entry function dropped or changed | `55000 P09_IN_DB_TOOL_ABI_MISMATCH` |
| Tool | Lease expires during read | `55000 P09_TOOL_CLAIM_LOST`; discard result |
| Catalog refresh | Changes handler between enqueue and claim | Worker revalidates and fails closed |
| Empty log | `complete`/`fail` cannot trust text alone | Synthetic protocol failure |
| Repeated apply | Canonical COMMENT restored; source rows/log/jobs preserved | Version remains `p21` |

---

## File-by-file impact

### `docs/plans/P09-in-db-worker-2026-08-25.md`

**Change**

- Replace the draft scaffold with this implementation-ready plan.
- Set final status to `ready to implement` only after the plan critique has no unresolved P0/P1.
- Retain the curated evidence and references where useful; remove the five open questions because they are resolved above.

**Why**

AGENTS requires a reviewed deep plan before SQL/test implementation.

**Ordering**

First. The implementation and tests must follow the resolved decisions, not the earlier scaffold alternatives.

### `sql/0021_p09_in_db_worker.sql`

**Create**

- `_resolve_in_db_queue_handler`;
- `enqueue_job`;
- `invoke_in_db_tool`;
- `worker_step`;
- COMMENT metadata on the existing `step_once`;
- apply-time `SELECT cordis.refresh_plugins()`;
- replacement `get_schema_version()` returning `p21`.

**Do not add**

- tables, columns, types, views, triggers, roles, grants, transaction control;
- replacement bodies for P01/P03/P05/P08/P19 functions;
- direct `UPDATE cordis.jobs SET status`;
- direct `INSERT INTO cordis.agent_steps`;
- loops over multiple claims or steps.

**Why**

This is the smallest additive layer that closes P09’s scheduler and in-database dispatch responsibilities.

**Ordering**

All contents land atomically. PL/pgSQL bodies use `$p09$`; metadata may use a distinct quoted JSON delimiter but must not change the plan-number body tag.

### `sql/README.md`

**Modify**

- Add `0021_p09_in_db_worker.sql → p21` to the version ladder.
- State the current product tree ends at `0021`.
- Document the four P09 functions and exact outcome vocabulary.
- Document `jobs.job_type` and `payload.paradigm` enqueue contracts.
- Document the `kernel.step_once` catalog row and `cordis.p09.queue.v1` marker.
- State that the canonical P05 body remains legacy/unscoped and is not advertised as P08-isolated.
- State that grant-requiring queue handlers are rejected in P09 v1.
- State that `invoke_in_db_tool` permits only read-only replayable in-db `session_select` entries.
- State that `wait` is an acknowledgement of an already durable P03 wait.
- State that callers commit after each worker call.
- Record `$p09$`, file prefix `0021`, and marker `p21`.

**Why**

The README is the install and current-tree contract.

**Ordering**

After exact signatures and metadata fields are final.

### `tests/test_p09_in_db_worker.py`

**Create**

- Catalog/signature/version tests.
- Enqueue tests.
- Worker state-machine tests.
- P03 wait acknowledgement tests.
- Dynamic read-only tool tests.
- Concurrency/lease/rollback tests.
- Replay and source-boundary tests.

**Reuse**

Only `run_apply`, `psql`, `psql_session`, and where needed `next_sql_prefix` from `tests.conftest.py`. Do not import `tools` or create another server/apply fixture.

**Why**

P09 requires a named protocol proof and failure-contract coverage beyond P05’s manually stitched Python mapping.

**Ordering**

Atomic with the SQL and current-tree pin updates.

### `tests/test_p00_sql_source.py`

**Modify**

- Rename/retarget the current-tree test from `p20` to `p21`.
- Add `0021_p09_in_db_worker.sql` to exact file-list assertions and numbered-file extension assertions.
- Add the four P09 function names to `KERNEL_FUNCTIONS` in lexical order:
  - `cordis._resolve_in_db_queue_handler`
  - `cordis.enqueue_job`
  - `cordis.invoke_in_db_tool`
  - `cordis.worker_step`
- Keep existing table-count assertions unchanged.
- Update the pg-agent separate-database composition marker to `p21`.
- Preserve no-extension/public-object assertions.

**Why**

P00 owns current-tree discovery and exact catalog pins.

**Ordering**

Must land with `0021`.

### `tests/test_p01_claim.py`

**Modify only if the module contains a full-current-tree marker assertion**

- Change full-tree `p20` to `p21`.
- Do not change P01-only behavior, signatures, or its two-session claim tests.

**Why**

Highest-numbered file wins only on the full tree.

### `tests/test_p02_agent_steps.py`

**Modify**

- Retarget full-tree version assertions to `p21`.
- Keep P02-only marker expectations unchanged.
- Keep the source-tree append monopoly expecting the sole direct `INSERT INTO cordis.agent_steps` in `0002_p02_log.sql`.

**Why**

P09 synthetic errors delegate to `emit_step_claimed`; it must not create a second append site.

### `tests/test_p03_wait_event.py`

**No behavioral change**

- A deliberately truncated P03 tree remains `p03`.
- Existing event/wait tests remain unchanged.
- Only change a marker if the test explicitly applies the full current SQL root.

**Why**

P09 does not replace or call `await_event` itself.

### `tests/test_p05_one_step_driver.py`

**No change expected**

- P05-only tree remains `p05`.
- `step_once` signature/body tests remain unchanged.
- Existing source-boundary test must continue to see no `worker_step` in `0005` and one append monopoly in the whole SQL tree.
- The P09 test module owns worker tests.

**Why**

P09 registers but does not replace/wrap the P05 driver.

### `tests/test_p06_plugin_catalog.py`

**Modify**

- Retarget full-current-tree marker assertions to `p21`.
- Where full-tree tests assert catalog identities/counts, include canonical `kernel.step_once`.
- Keep P06-only tree expectations unchanged.
- Preserve the proof that host registrations have no SQL entrypoint.

**Why**

P09 adds one COMMENT-sourced in-db queue handler and refreshes the compiled catalog.

### `tests/test_p07_grant_registry.py`

**No behavior change**

- P07-only tree remains `p07`.
- Full-tree marker assertions, if any, become `p21`.
- Existing exact-target grant behavior remains unchanged.

**Why**

P09 uses P08 rather than duplicating P07 grant parsing.

### `tests/test_p08_four_seam_enforcement.py`

**Modify**

- Retarget tests that apply the full current tree from `p20` to `p21`.
- Include `0021` in exact full-tree file lists.
- Drop-one-seam probe tests that copy the current tree now retain marker `p21`.
- Preserve P08 blank-context fold, legacy `step_once`, denylist, latch, and replay behavior.
- Add no assertion that P09’s P05 handler is isolated.

**Why**

P08 remains behaviorally unchanged but is no longer the last numbered file.

### `tests/test_p19_paradigm_policies.py`

**Modify**

- Retarget full-tree marker assertions to `p21`.
- Allow `next_sql_prefix`-based probes to advance naturally to `0022`; do not hard-code a stale sentinel prefix.
- Preserve P19-only `p19` tests and all slot signatures.

**Why**

P09 consumes `paradigm_policy` without changing P19.

### `tests/conftest.py` and `tools/apply_pg_cordis.py`

**No change**

The current subprocess apply path and PostgreSQL helpers already cover P09.

### Historical SQL files `sql/0000`–`0020`

**No change**

P09 is append-only. The only interaction with `step_once` is COMMENT metadata in `0021`.

### Validation note for version pins

Before implementation review, search all tests for literal `p20` and `0020_p08_four_seam_enforcement.sql`. Classify each occurrence by the SQL root used:

- full current root → update to `p21`/include `0021`;
- intentionally truncated tree ending at P08 → retain `p20`;
- prose/source fixture describing P08 itself → retain if it is not a current-tree assertion.

This validation resolves version fallout without blindly rewriting historical-prefix tests.

---

## Work items and verification

## W90 — Queue ABI and canonical handler

Implement `_resolve_in_db_queue_handler`, apply COMMENT metadata to `step_once`, and refresh the catalog.

Done when:

- `kernel.step_once` resolves to `cordis.step_once(text,uuid,integer)`;
- the function body and `pg_proc` identity of `step_once` are unchanged;
- resolver accepts the canonical row;
- resolver rejects host, session-select, grant-requiring, missing-marker, and wrong-signature rows;
- no wrapper function exists.

Verification tests:

- `test_p09_fresh_apply_catalogReconnecting... 1/5<chatName="P09 in-database worker deep plan"/>

# P09 — In-database worker

Date: 2026-08-25  
Status: **ready to implement pending plan critique**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P09  
Depends on: P05, P06 (implemented); P08 and P19 are in the current product tree and constrain dispatch and policy lookup  
Parallel with: P10  
Contract: dual-locus workers share the P01 claim protocol and the single `cordis.jobs` queue; the in-database worker executes only `locus='in-db'` entries  
Primary deliverable: `sql/0021_p09_in_db_worker.sql`  
Critique: `docs/reviews/2026-08-25-p09-plan-critique.md`  
Implementation review: `docs/reviews/2026-08-25-p09-implementation-oracle.md`  
Version marker: `p21`  
PL/pgSQL dollar tag: `$p09$`

## Summary

P09 adds a targeted scheduling and dispatch layer above the existing kernel rather than refactoring the P05 step body. It introduces a handler-aware `enqueue_job`, a catalog resolver for P09-compatible in-database queue handlers, a claim-to-one-step `worker_step`, and a claim-bound read-only in-database tool invoker that always passes through P08 authorization. The existing `cordis.step_once` is registered directly as the canonical P09 queue handler by COMMENT metadata; it is neither wrapped nor replaced. Each `worker_step` invocation claims at most one `cordis.jobs` row, invokes exactly one handler once, maps the returned outcome through P01/P03 state transitions, and returns. The file is appended as `sql/0021_p09_in_db_worker.sql`, refreshes the existing P06 catalog, and advances the full-tree marker from `p20` to `p21`.

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

The canonical acceptance path is:

```text
enqueue kernel.step_once
    → worker_step
    → P05 mock LLM + mock.observe
    → yield_claim
    → a later worker_step reclaims the same jobs row
    → final step
    → complete_claim
```

P09 also closes the P06 execution handoff for read-only in-database tools:

```text
live claim
    → authorize_tool_dispatch
    → require locus=in-db and invocation=session_select
    → require read_only/replayable/none
    → execute one jsonb→jsonb entrypoint
    → recheck claim
    → return result
```

### Explicit non-goals

P09 does **not**:

- replace, wrap, overload, or rewrite `cordis.step_once`;
- copy SQL from `scratch/yield_walkthrough/` or the G research sketch;
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

W90–W95 are one numbered-file delivery and must not be released partially. The final commit must include the SQL, documentation, current-tree pin updates, and P09 tests together.

---

## Background

### Parent and locked contracts

The parent P09 skeleton requires:

- `worker_step = claim → one step → yield/wait/complete`;
- only in-database execution for this worker;
- no file editing or TEMP-backed session state;
- a single worker proving yield followed by reclaim.

The following are locked and are not reopened:

- `cordis.jobs` is the only queue.
- The authoritative claim is the P01 jobs row and current `claim_token`.
- In-database and host workers use the same P01 claim verbs.
- One default step is one LLM invocation plus its tools.
- Child runs always enqueue and are outside P09.
- PostgreSQL session affinity and `pg_temp` workspaces are forbidden.
- P08’s four-seam feature remains fail-closed.
- `agent_steps` remains the history source of truth.
- P09 is appended as a higher-numbered SQL source file and does not create an extension.

### Current kernel functions P09 must reuse

| Existing component | Current responsibility | P09 use |
|---|---|---|
| `cordis.claim_job` | Reaps stale claims, then claims one eligible PENDING jobs row with SKIP LOCKED | Sole claim operation |
| `yield_claim`, `complete_claim`, `fail_claim` | Fenced P01 scheduler transitions | Sole direct worker transitions |
| `cordis.step_once` | Runs at most one P05 mock step and returns text; never changes jobs status | Canonical P09 queue handler |
| `emit_step_claimed` | Claim-fenced append and lease extension | Used for P09-generated terminal protocol errors |
| `run_state`, `agent_steps` | Log-derived state and result/error payloads | Read after handler outcomes |
| `await_event` | Atomically records a wait and clears the claim into WAITING | May be called by a future queue handler; P09 only verifies its completed state |
| `plugin_catalog` | Compiled plugin metadata and in-db entrypoint identity | Queue/tool resolution |
| `refresh_plugins` | Rebuilds the compiled catalog from COMMENT and host sources | Installs the canonical P09 handler row |
| `paradigm_policy` | Validates and resolves an open paradigm identity | Enqueue-time and claim-time discriminator validation |
| `authorize_tool_dispatch` | Slice/live-grant authorization and current descriptor | Mandatory tool-dispatch gate |
| `_require_isolation_feature` | Closes all P08 surfaces if the four-seam manifest is incomplete | Called before enqueue/worker activity |

---

## Current-state analysis

### Existing ownership and mutation points

`cordis.jobs` owns scheduler state. Its mutating paths are currently:

```text
producer SQL INSERT
    → status=PENDING

claim_job
    → status=RUNNING
    → token, claimed_by, expiry populated

yield_claim
    → status=PENDING
    → claim fields cleared

complete_claim
    → status=DONE
    → result and completed_at set

fail_claim
    → status=ERROR
    → error and completed_at set

await_event
    → status=WAITING
    → run_waits row and run/await log
    → claim fields cleared
```

P09 must not update these state fields directly. `enqueue_job` is the only new direct insert into `cordis.jobs`; every post-claim transition reuses P01 or recognizes a transition already performed by P03.

`cordis.agent_steps` remains append-only. P09 does not insert into it directly. A synthetic worker protocol failure follows:

```text
emit_step_claimed(error payload)
    → fail_claim(the same payload)
```

This preserves P02’s append monopoly and keeps the log terminal event ahead of the scheduler terminal state in the same transaction.

### Existing execution flow

P05 tests currently implement the missing worker manually in Python:

```text
claim_job
    → step_once
    → Python CASE
        yield    → yield_claim
        complete → complete_claim(latest final payload)
        fail     → fail_claim(latest error payload)
```

This is reusable behavior, but the orchestration itself is not a product SQL API. P09 moves that outer state machine into one SQL function without copying the P05 step body.

### Catalog state

P06 compiles COMMENT-backed in-database entries and host registration rows into one catalog. It deliberately does not execute either. Important existing distinctions are:

- in-db rows have a real `entrypoint regprocedure`;
- host rows have no SQL entrypoint;
- `invocation='queue'` denotes a queue handler;
- `invocation='session_select'` denotes an in-database tool surface;
- metadata alone does not prove a function has the ABI P09 expects.

P09 therefore adds runtime ABI checks rather than changing P06’s table or validator.

### Paradigm state

P19 owns the open paradigm registry. `jobs.job_type` is a handler identity and must not be overloaded as the paradigm. No run-owned paradigm column exists. P09 therefore stores the validated identity in `jobs.payload.paradigm` through its enqueue API and validates it again before each execution.

The canonical P05 body does not consume P19’s fold/parser slots. P09 must not fake integration by calling `fold_slice_messages` and discarding the result, and it must not create a second step body to adapt P05. The P09 worker is consequently a scheduler and proof path, not yet the model-facing isolated coding worker.

### P08 boundary

P08 explicitly leaves `step_once` unwrapped and documents it as a legacy, unfiltered proof path. P09 preserves that boundary:

- queue resolution is trusted scheduler control-plane resolution, not model tool authorization;
- P09’s separate in-db tool function always calls `authorize_tool_dispatch`;
- grant-requiring queue handlers are rejected by P09 v1 because the queue ABI has no explicit slice/bindings arguments;
- `kernel.step_once` is registered with no required grants and is documented as the P05 proof body, not an isolated user-facing entrypoint;
- no caller may advertise `worker_step` plus `kernel.step_once` as satisfying P08 fold isolation.

This closes rather than hides the mismatch: P09 does not permit an ostensibly grant-requiring queue handler to bypass P08 through the no-slice queue ABI.

---

## Design

### Resolved decisions

| # | Decision | Rationale | Rejected alternative |
|---:|---|---|---|
| 1 | Use one catalog-selected queue-handler path. Register the existing `cordis.step_once(text,uuid,integer)` directly as `kernel.step_once` by COMMENT metadata. Do not create an adapter function. | P05 already owns the one-step body; P06 assigned queue entrypoint execution to P09. Direct registration avoids a second loop and honors the no-wrap/no-replace lock. | Hard-code `worker_step` to call `step_once` without catalog resolution; create `p09_step_once` wrapper; copy P05 or G into a new driver. |
| 2 | Add `cordis.enqueue_job(text,text,text,jsonb,integer)` and make `job_type` a P06 queue-handler identity. Require an explicit paradigm argument and store it as `payload.paradigm`. | P05 parked producer/handler integration on P09. An explicit API prevents arbitrary blank labels and meets P19’s handoff without adding a jobs column. | Continue requiring direct INSERT; infer paradigm from `job_type`; add `jobs.paradigm`; upsert duplicate runs. |
| 3 | Use one poll-first `worker_step` signature with optional `p_run_id`, not overloads. | `claim_job(NULL,...)` already implements queue polling. One function avoids overloaded defaults and still gives deterministic named-run tests. | Separate `worker_step()` and `worker_step_run()` functions; require every worker to know a run ID; add another queue scanner. |
| 4 | A handler outcome `wait` is accepted only if the handler has already atomically completed P03 registration and left the job WAITING. `worker_step` never invents event parameters or calls `await_event`. A `wait` returned while the claim remains RUNNING becomes terminal `P09_WAIT_NOT_REGISTERED`. | The text outcome carries no scope/name/await ID. P03 is the only valid WAITING transition and already owns atomicity. This preserves a forward-compatible outcome without activating P05’s unsupported wait. | Treat `wait` as `yield`; have P09 construct an event wait from ad hoc payload keys; reject all wait outcomes even when a handler has correctly called P03. |
| 5 | Validate `paradigm_policy` at enqueue and again after claim. Do not call `fold_slice_messages` in the unchanged P05 proof path. Use P08 authorization only on the actual tool-dispatch path. | The paradigm registry can change between enqueue and claim. Calling a fold and ignoring it provides no isolation, while consuming it would require changing or duplicating the P05 driver. | Select `paradigm_policies` directly; `CASE` on `codeact`/`rlm`; call fold and throw the result away; create a second isolated step body in P09. |
| 6 | Queue handler ABI v1 is exactly `(text,uuid,integer) → text`, ordinary, non-set-returning, VOLATILE, SECURITY INVOKER, and pinned to `search_path=pg_catalog`. The catalog row must set `config.worker_abi='cordis.p09.queue.v1'` and have no `required_grants`. | Exact runtime validation prevents execution of a coincidentally tagged function. Rejecting required grants prevents the no-slice queue ABI from bypassing P08. | Execute every `invocation='queue'` function regardless of signature; accept grant-requiring handlers and trust them to find a slice in arbitrary payload. |
| 7 | `worker_step` dynamically invokes the resolved handler once and exhaustively maps the returned text. It never catches handler exceptions broadly. | P05 requires unique violations and invariant errors such as `23505` to propagate. A broad catch would turn transactional faults into terminal agent history and consume potentially retryable work before P04 exists. | `EXCEPTION WHEN OTHERS` followed by `fail_claim`; an internal loop that retries the handler. |
| 8 | Add `invoke_in_db_tool` as a separate read-only tool seam. It calls `authorize_tool_dispatch`, requires `locus='in-db'`, `invocation='session_select'`, and `read_only/replayable/none`, then executes exactly one compatible `jsonb → jsonb` function. | This fulfills P06/P08’s tool execution handoff without extending P05 or entering P16’s mutation/recovery scope. | Execute host rows; execute queue handlers as tools; support transactional/external tools without call/result recovery; let handlers read `plugin_catalog` and execute entrypoints directly. |
| 9 | The read-only tool helper performs a non-mutating exact-claim check both before and after execution and does not heartbeat. | P05 already owns lease extension through claimed appends. Read-only results are replayable; a post-call stale result is rejected without adding a second heartbeat or holding a jobs-row lock through execution. | `renew_claim` before or after every tool; no post-execution fence; log a result after claim loss. |
| 10 | `worker_step` returns one table row with `(job_id, run_id, outcome)`. The closed outcomes are `idle`, `yield`, `wait`, `complete`, `fail`, and `lost_claim`. | A poller needs to identify which run it processed; returning a token would leak a cleared or live capability. One row for idle avoids using zero rows ambiguously. | Return only text; return the claim token; return zero rows when idle; return arbitrary handler text. |
| 11 | Each `worker_step` call is one transaction-scoped claim/body/transition operation. P09 contains no transaction control. Operational callers must commit or autocommit after each non-idle call before invoking the worker again. | The SQL apply rules forbid transaction control, and PostgreSQL function calls cannot autonomously commit. A caller-side loop in one transaction would hide yield and recreate multi-step session pinning. | Procedure-level commits; a PL/pgSQL `LOOP`; documenting multiple calls in one transaction as supported. |
| 12 | Synthetic worker protocol failures append a canonical P09 error through `emit_step_claimed`, then use `fail_claim` with that same payload. | History remains authoritative and P01 remains the scheduler state mutator. | Direct `INSERT` into `agent_steps`; direct `UPDATE jobs SET status='ERROR'`; fail the jobs row without an error event. |
| 13 | Handler/catalog/policy disappearance after enqueue is a durable terminal admission failure for that job; exceptions thrown by the handler body itself propagate and roll back the worker call. | A missing handler cannot make progress without operator repair, while arbitrary handler exceptions cannot yet be classified for P04 retry. The distinction prevents poison jobs caused by stale catalog metadata while preserving database invariants. | Let missing catalog rows roll back forever; catch and terminalize every exception from the handler. |
| 14 | P09 is a targeted additive layer. It introduces no table or column migration. | Existing P01/P02/P03/P05/P06/P08/P19 APIs already provide all required state and extension points. | Broader worker/driver/log/catalog refactor; adding `agent_runs`; adding a separate handler table. |

No implementation fork remains open after this table.

---

## Component 1 — P09-compatible queue-handler resolution

### `cordis._resolve_in_db_queue_handler`

**Kind:** internal catalog resolver  
**Location:** `sql/0021_p09_in_db_worker.sql`  
**Owner:** kernel; called by `enqueue_job` and `worker_step`  
**Signature:**

```text
cordis._resolve_in_db_queue_handler(p_identity text)
RETURNS regprocedure
```

Properties:

- `LANGUAGE plpgsql`
- `STABLE`
- `SECURITY INVOKER`
- `SET search_path TO pg_catalog`
- no overloads

Validation order:

1. Require a normalized P06 identity:
   - non-null and nonblank after `btrim`;
   - at most 128 bytes;
   - P06 dotted identity grammar.
2. Resolve exactly one `plugin_catalog` row by normalized identity.
3. Require:
   - `locus='in-db'`;
   - `invocation='queue'`;
   - non-null `entrypoint`;
   - empty `required_grants`;
   - `config` is an object and `config.worker_abi='cordis.p09.queue.v1'`.
4. Inspect the `regprocedure` target in `pg_proc`:
   - ordinary function, not procedure/aggregate/window;
   - exact identity arguments `text, uuid, integer`;
   - not set-returning;
   - result type `text`;
   - volatility `VOLATILE`;
   - `SECURITY INVOKER`;
   - pinned function configuration includes `search_path=pg_catalog`.
5. Return the validated `regprocedure`.

Errors:

| Condition | SQLSTATE | Stable fragment |
|---|---:|---|
| Invalid identity or no catalog row | `22023` | `P09_UNKNOWN_JOB_HANDLER` |
| Wrong locus/invocation or non-empty grants | `0A000` | `P09_JOB_HANDLER_UNSUPPORTED` |
| Missing/mismatched function ABI | `55000` | `P09_JOB_HANDLER_ABI_MISMATCH` |

The resolver does not execute the handler and does not cache the result across claims.

### Canonical handler registration

`0021` adds COMMENT metadata to the existing function identity:

```text
cordis.step_once(text,uuid,integer)
```

Compiled catalog identity:

```text
identity        = kernel.step_once
version         = 0.1.0
locus           = in-db
invocation      = queue
required_grants = {}
effect_class    = transactional
retry_class     = idempotent
reconciliation  = none
session_scope   = run
config.worker_abi = cordis.p09.queue.v1
config.protocol   = cordis.p05.mock.v1
config.isolated   = false
```

The exact description must state that this is the P05 mock/proof body and is not P08 slice-isolated.

After the COMMENT is installed, `0021` calls the existing `cordis.refresh_plugins()`. This preserves P06’s single compiler and source-of-truth rules:

- the function COMMENT remains the in-db source;
- runtime host registrations remain in `host_plugin_definitions`;
- the compiled table is rebuilt, not directly patched;
- replay restores the canonical `kernel.step_once` metadata without replacing the function body.

---

## Component 2 — Handler-aware enqueue

### `cordis.enqueue_job`

**Kind:** trusted producer API  
**Location:** `sql/0021_p09_in_db_worker.sql`  
**Signature:**

```text
cordis.enqueue_job(
    p_run_id     text,
    p_job_type   text,
    p_paradigm   text,
    p_payload    jsonb DEFAULT '{}'::jsonb,
    p_priority   integer DEFAULT 0
) RETURNS bigint
```

Properties:

- `VOLATILE`
- `SECURITY INVOKER`
- `SET search_path TO pg_catalog`
- immediately claimable; no delayed scheduling argument
- no model-tool catalog registration

Algorithm:

1. Validate `p_run_id` as non-null/nonblank. Preserve its bytes exactly; do not trim before storage.
2. Validate `p_payload` is a JSON object.
3. Reject a caller payload already containing top-level `paradigm`; the explicit argument is the only P09 enqueue source for that field.
4. Validate `p_priority` is non-null. Any PostgreSQL integer value remains legal because P01 already defines ordering and no narrower range exists.
5. Require the P08 readiness latch before creating work.
6. Normalize and validate `p_paradigm` by calling:
   ```text
   SELECT * FROM cordis.paradigm_policy(p_paradigm)
   ```
   Do not query `paradigm_policies` directly.
7. Resolve `p_job_type` with `_resolve_in_db_queue_handler`.
8. Insert one `cordis.jobs` row:
   - `run_id = p_run_id`;
   - `job_type = normalized handler identity`;
   - `payload = p_payload` plus canonical normalized `paradigm`;
   - `priority = p_priority`;
   - all claim/status/timing fields use P01 defaults.
9. Return the inserted `job_id`.

Persistence contract:

```text
jobs.job_type          = P06 queue-handler identity
jobs.payload.paradigm  = normalized P19 policy identity
```

`enqueue_job` does not add `slice_id`, grant bindings, retry data, event data, or spawn lineage.

Duplicate `run_id` propagates P01’s `jobs_run_id_key` `23505`. P09 does not upsert or return an existing job because no idempotent producer key has been defined.

Catalog and policy are revalidated after claim; successful enqueue is not a permanent authorization token.

---

## Component 3 — Read-only in-database tool execution

### `cordis.invoke_in_db_tool`

**Kind:** claim-bound read-only tool dispatcher  
**Location:** `sql/0021_p09_in_db_worker.sql`  
**Signature:**

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

Properties:

- `VOLATILE`, because it dynamically invokes a catalog entrypoint even though accepted entrypoints are read-only;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`;
- does not append a log event;
- does not cache the P08 descriptor;
- does not apply P19 observation policy.

Input validation:

- run ID non-null/nonblank;
- claim token and slice ID non-null;
- arguments must be a JSON object;
- plugin identity and grant-binding validation remain owned by `authorize_tool_dispatch`.

Algorithm:

1. Check the exact live claim without modifying it:
   ```text
   jobs.run_id = p_run_id
   jobs.claim_token = p_claim_token
   jobs.status = RUNNING
   jobs.claim_expires_at > clock_timestamp()
   ```
   Missing/dead claim raises `42501 P09_TOOL_CLAIM_REQUIRED`.
2. Call `authorize_tool_dispatch(run, slice, identity, bindings)`.
   - Preserve P08’s `22023`/`42501` failures unchanged.
   - Do not read `plugin_catalog` first and do not cache an older descriptor.
3. Require descriptor:
   - `locus='in-db'`;
   - `invocation='session_select'`;
   - `effect_class='read_only'`;
   - `retry_class='replayable'`;
   - `reconciliation='none'`;
   - non-null entrypoint.
4. Resolve the returned entrypoint and verify:
   - exact arguments `jsonb`;
   - result `jsonb`;
   - ordinary, non-set-returning function;
   - volatility `STABLE` or `IMMUTABLE`;
   - `SECURITY INVOKER`;
   - pinned `search_path=pg_catalog`.
5. Invoke that exact schema-qualified function once with `p_arguments`. Dynamic SQL uses the validated `regprocedure` and identifier quoting; it never concatenates caller SQL.
6. Reject SQL NULL result with `55000 P09_IN_DB_TOOL_INVALID_RESULT`. JSON null remains valid JSON if explicitly returned.
7. Recheck the same live claim without extending it.
   - If it expired or was otherwise lost, raise `55000 P09_TOOL_CLAIM_LOST`.
8. Return an object shaped as:

```text
{
  protocol:   "cordis.p09.in_db_tool.v1",
  identity:   <authorized normalized identity>,
  descriptor: <the current P08 descriptor>,
  result:     <entrypoint jsonb result>
}
```

Restrictions and rationale:

- Host rows are rejected before attempting resolution; P06 host tools have no SQL stub.
- Queue handlers are rejected as tools.
- Transactional and external effects are rejected. P09 has not defined tool/call/result recovery or an atomic scoped result append; P16 owns that work.
- Read-only results may be recomputed after failure. The caller that later folds or checkpoints a tool result must use `emit_step_scoped`; P09 does not create a parallel unscoped logging path.
- P19 observe/clip functions remain a step-driver responsibility. Applying them here would couple generic execution to a paradigm without an env workspace.

Errors:

| Condition | SQLSTATE | Stable fragment |
|---|---:|---|
| Missing/dead initial claim | `42501` | `P09_TOOL_CLAIM_REQUIRED` |
| Authorized descriptor has host locus | `42501` | `P09_IN_DB_TOOL_LOCUS_REQUIRED` |
| Invocation is not `session_select` | `0A000` | `P09_IN_DB_TOOL_INVOCATION_UNSUPPORTED` |
| Effect/retry/reconciliation not read-only shape | `0A000` | `P09_IN_DB_TOOL_EFFECT_UNSUPPORTED` |
| Entrypoint ABI/security mismatch | `55000` | `P09_IN_DB_TOOL_ABI_MISMATCH` |
| Entrypoint returns SQL NULL | `55000` | `P09_IN_DB_TOOL_INVALID_RESULT` |
| Claim lost during execution | `55000` | `P09_TOOL_CLAIM_LOST` |

Exceptions raised by the tool function itself propagate unchanged.

---

## Component 4 — Worker state machine

### `cordis.worker_step`

**Kind:** one-job in-database worker operation  
**Location:** `sql/0021_p09_in_db_worker.sql`  
**Signature:**

```text
cordis.worker_step(
    p_worker_id      text,
    p_run_id         text DEFAULT NULL,
    p_lease_seconds  integer DEFAULT 90
) RETURNS TABLE (
    job_id   bigint,
    run_id   text,
    outcome  text
)
```

Properties:

- `VOLATILE`
- `SECURITY INVOKER`
- `SET search_path TO pg_catalog`
- exactly one returned row
- no overloads
- no internal loop

Closed returned outcomes:

| Outcome | Meaning at return |
|---|---|
| `idle` | No eligible job was claimed; IDs are NULL |
| `yield` | Handler returned `yield` and `yield_claim` succeeded |
| `wait` | Handler returned `wait` after atomically leaving a consistent P03 WAITING state |
| `complete` | Handler returned `complete`, a final log row existed, and `complete_claim` succeeded |
| `fail` | A terminal handler or P09 protocol failure was logged and `fail_claim` succeeded |
| `lost_claim` | Handler or transition observed that the token was no longer authoritative |

### Validation and claim

1. Validate:
   - worker ID non-null/nonblank;
   - optional run ID is either NULL or nonblank;
   - lease is positive.
2. Require `_require_isolation_feature()` before claiming.
3. Call:
   ```text
   claim_job(p_run_id, p_worker_id, p_lease_seconds)
   ```
4. If no row is returned, emit one result row:
   ```text
   job_id=NULL, run_id=NULL, outcome='idle'
   ```
   and return.
5. Retain the claimed row locally, including its job ID, run ID, payload, handler identity, and claim token.

Only `claim_job` scans the queue. P09 adds no second readiness query.

### Post-claim admission

Before invoking the handler:

1. Require claimed `payload` to be a JSON object with a nonblank string `paradigm`.
2. Call `paradigm_policy(payload->>'paradigm')`.
3. Resolve `job_type` through `_resolve_in_db_queue_handler`.
4. Do not use the returned policy row to branch on identity.
5. Do not call `fold_slice_messages`; the registered P05 body does not accept a fold result.

Expected admission failures are converted to a durable worker error:

| Failure | Error payload code |
|---|---|
| Missing/invalid payload paradigm | `P09_JOB_PAYLOAD_INVALID` |
| Paradigm removed/unknown at claim time | `P09_PARADIGM_UNAVAILABLE` |
| Handler missing, wrong locus/invocation/grants, or incompatible ABI | `P09_HANDLER_UNAVAILABLE` |

The generated error payload is:

```text
{
  protocol:  "cordis.p09.worker.v1",
  code:      <code above>,
  message:   <bounded stable message>,
  details: {
    job_type: <jobs.job_type>,
    sqlstate: <underlying expected resolver/policy SQLSTATE when applicable>
  },
  step_name: null
}
```

The worker calls `emit_step_claimed(..., kind='error', step_name=NULL)` and then `fail_claim` with the same payload. If either fenced operation reports loss before the terminal transition, return `lost_claim`.

Only the narrow expected admission errors are converted. Handler execution is outside those exception blocks.

### Handler invocation

Invoke the resolved queue entrypoint exactly once with:

```text
(run_id, claim_token, p_lease_seconds)
```

The handler’s text return is kept as the raw step outcome.

The worker does not:

- call `renew_claim` before execution;
- hold a separate heartbeat;
- invoke a second handler;
- rerun the same handler on exception;
- append a yield event;
- call any tool entrypoint itself unless the handler explicitly uses `invoke_in_db_tool`.

### Outcome mapping

#### `yield`

Call `yield_claim(claim_token)`.

- `true` → return `yield`;
- `false` → return `lost_claim`.

No `run/yield` event is added, preserving the P01/P05 boundary.

#### `complete`

Read the newest `agent_steps` row for the claimed run with `kind='final'`.

- If found, call `complete_claim(claim_token, final.payload)`.
  - `true` → return `complete`;
  - `false` → return `lost_claim`.
- If absent, generate `P09_COMPLETE_WITHOUT_FINAL`, append it through `emit_step_claimed`, and fail the claim. Return `fail` only if both fences succeed.

The scheduler result is therefore derived from the canonical final log payload rather than the handler’s return text.

#### `fail`

Read the newest `agent_steps` row for the claimed run with `kind='error'`.

- If found, call `fail_claim(claim_token, error.payload)`.
  - `true` → return `fail`;
  - `false` → return `lost_claim`.
- If absent, generate `P09_FAIL_WITHOUT_ERROR`, append it through `emit_step_claimed`, and fail the claim.

P05’s existing fail paths already provide an error row; the synthetic branch protects the generic queue ABI.

#### `wait`

The handler is responsible for calling P03 `await_event` before returning `wait`. P09 verifies, by run ID, all of:

- jobs status is `WAITING`;
- `claim_token`, `claimed_by`, and `claim_expires_at` are NULL;
- exactly one matching `run_waits` row exists for the run;
- that row references the same jobs row through the existing foreign key.

If consistent, return `wait` without another transition.

If the jobs row is still RUNNING under the same live token, generate `P09_WAIT_NOT_REGISTERED`, append it, and fail the claim. P09 does not silently yield.

If the token is gone but the WAITING state is inconsistent, raise `55000 P09_WAIT_STATE_INVALID`. Because handler execution and verification are in one transaction, this rolls back the malformed wait registration and the original claim together.

This branch is unreachable through the current P05 `step_once`, which converts a mock wait decision into `fail`.

#### `lost_claim`

Perform no transition and return `lost_claim`.

The next claimant relies on P01 `release_stale` and P02/P05 checkpoints. P09 does not append an additional error because the worker is no longer authoritative.

#### NULL or unknown value

Generate `P09_INVALID_STEP_OUTCOME`, including the returned value as JSON or null in `details`, then append and terminally fail through the standard synthetic-error sequence.

There is no pass-through of arbitrary handler text.

### Exception behavior

Exceptions thrown from the dynamically invoked handler propagate unchanged. In particular:

- a P05 duplicate LLM append keeps SQLSTATE `23505`;
- SQL cancellation/statement timeout propagates;
- an invariant violation is not rewritten as a P09 error event.

Because claim, handler, and transition execute in the caller’s transaction, propagation rolls back:

- the claim;
- P05/P09 log writes made in that call;
- jobs transitions made in that call;
- in-database transactional effects made by the handler.

If the handler performed an external provider operation before rollback, P05’s stable provider key remains the recovery mechanism. P09 adds no new external retry semantics.

---

## State and data flow

### Enqueue flow

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

### Worker happy path

```text
worker caller
  → worker_step(worker_id, optional run_id, lease)
      → P08 readiness latch
      → claim_job
          → optional stale release
          → SKIP LOCKED claim of one PENDING row
      → paradigm_policy(payload.paradigm)
      → _resolve_in_db_queue_handler(job_type)
      → dynamic queue entrypoint invocation once
          → canonical path: step_once
              → P05 log/checkpoint logic
              → emit_step_claimed extends/fences claim
      → exhaustive outcome mapping
          yield    → yield_claim
          complete → latest final payload → complete_claim
          fail     → latest error payload → fail_claim
          wait     → verify P03 already transitioned
      → one result row
```

Execution context: the complete function invocation runs in the caller’s PostgreSQL transaction. Workers should use autocommit or explicitly commit immediately after each non-idle call.

### Read-only tool flow

```text
queue handler holding a live claim
  → invoke_in_db_tool(token, run, slice, identity, bindings, args)
      → exact live-claim check
      → authorize_tool_dispatch
          → live P07 grants and P08 latch
      → descriptor locus/invocation/effect/ABI checks
      → execute one read-only jsonb function
      → exact post-call claim check
      → descriptor + result
  → caller may scope/checkpoint the result
```

No result is accepted after claim loss. No tool descriptor survives the call.

### Concurrency and ordering

- Two workers calling `worker_step` concurrently contend only through `claim_job`; SKIP LOCKED permits at most one claim per jobs row.
- `p_run_id=NULL` polls global PENDING work in P01 priority order.
- A named run uses the same claim path and does not bypass readiness or locking.
- A yielded row has its claim cleared and becomes eligible for a later call, potentially by another worker.
- Repeated or duplicated worker calls cannot reuse the cleared token because P01 transition verbs fence it.
- Catalog changes after enqueue are observed at claim-time revalidation.
- P08 grants for a tool are read during each `invoke_in_db_tool` call. A returned descriptor is not reusable.
- No background notification is required; an idle worker may poll again according to its external scheduling policy.

### Dropped responses and cancellation

If `worker_step` commits but the SQL response is dropped, the caller recovers by reading:

- `cordis.jobs` by `run_id`;
- `cordis.run_state(run_id)`;
- ordered `cordis.agent_steps`.

It must not blindly assume the old call failed.

If the SQL statement is cancelled before commit, PostgreSQL rolls back the claim and database mutations. The job remains or becomes visible as PENDING according to its pre-call state; no explicit cancellation row is written.

---

## API and persistence impact

### New interfaces

```text
cordis._resolve_in_db_queue_handler(text)
    RETURNS regprocedure

cordis.enqueue_job(text,text,text,jsonb,integer)
    RETURNS bigint

cordis.invoke_in_db_tool(uuid,text,uuid,text,jsonb,jsonb)
    RETURNS jsonb

cordis.worker_step(text,text,integer)
    RETURNS TABLE(job_id bigint, run_id text, outcome text)
```

Defaulted arguments do not create overloads.

### Modified existing interfaces

No existing function signature changes.

The body and signature of `cordis.step_once` remain untouched. Its object receives COMMENT metadata only.

`cordis.get_schema_version()` keeps its zero-argument `RETURNS text`, SQL, IMMUTABLE, SECURITY INVOKER shape; the new file changes only its literal result:

```text
before full tree: p20
after full tree:  p21
```

### Stored data

No table or column is added.

P09 establishes these producer conventions for rows created through `enqueue_job`:

| Field | Type | Meaning |
|---|---|---|
| `jobs.job_type` | `text` | P06 queue-handler identity |
| `jobs.payload.paradigm` | JSON string | normalized P19 identity |
| `jobs.priority` | integer | existing P01 ordering field |

Existing rows inserted before P09 are not rewritten. If such a row is passed to `worker_step` and lacks the P09 contract, it fails durably as `P09_JOB_PAYLOAD_INVALID` or `P09_HANDLER_UNAVAILABLE`. There is no migration because no product worker previously consumed those rows.

### Exact new catalog/function inventory

The full-tree `KERNEL_FUNCTIONS` pin gains:

```text
cordis._resolve_in_db_queue_handler
cordis.enqueue_job
cordis.invoke_in_db_tool
cordis.worker_step
```

No new tables or types are added. The P06 compiled catalog gains the canonical identity `kernel.step_once`.

---

## Error handling and edge cases

| Operation | Condition | Behavior |
|---|---|---|
| `enqueue_job` | Invalid run/payload/paradigm/handler syntax | `22023`; no row |
| `enqueue_job` | P08 latch closed | P08 `42501`; no row |
| `enqueue_job` | Unknown paradigm | P19 `22023`; no row |
| `enqueue_job` | Handler wrong locus/invocation/grants | `0A000 P09_JOB_HANDLER_UNSUPPORTED` |
| `enqueue_job` | Handler ABI mismatch | `55000 P09_JOB_HANDLER_ABI_MISMATCH` |
| `enqueue_job` | Duplicate run | Existing `23505`; no upsert |
| `worker_step` | Invalid worker/run/lease | `22023`; claim not attempted |
| `worker_step` | No ready job | One `idle` result row |
| `worker_step` | Catalog/policy removed after enqueue | Append P09 error; jobs → ERROR |
| `worker_step` | Handler raises | Exception propagates; entire call rolls back |
| `worker_step` | Handler returns `yield`, transition loses token | `lost_claim` |
| `worker_step` | `complete` without final log | Append `P09_COMPLETE_WITHOUT_FINAL`; jobs → ERROR |
| `worker_step` | `fail` without error log | Append `P09_FAIL_WITHOUT_ERROR`; jobs → ERROR |
| `worker_step` | `wait` with valid P03 state | Return `wait`; jobs remains WAITING |
| `worker_step` | `wait` while claim still RUNNING | Append `P09_WAIT_NOT_REGISTERED`; jobs → ERROR |
| `worker_step` | malformed WAITING state | `55000 P09_WAIT_STATE_INVALID`; call rolls back |
| `worker_step` | NULL/unknown outcome | Append `P09_INVALID_STEP_OUTCOME`; jobs → ERROR |
| `invoke_in_db_tool` | P08 authorization fails | Preserve P08 error |
| `invoke_in_db_tool` | Host or queue entry | Refuse before execution |
| `invoke_in_db_tool` | Transactional/external effect | `0A000`; no execution |
| `invoke_in_db_tool` | Claim expires during read | Reject result with `55000 P09_TOOL_CLAIM_LOST` |
| Any P09 call | SQL cancellation | Propagate; transaction rollback |

Boundary conditions:

- Empty queue: `idle`, not an exception.
- Future `available_at`: not claimed; poll returns `idle` if no other work exists.
- WAITING/SLEEPING/DONE/ERROR rows: not selected because `claim_job` claims only PENDING.
- Blank historical `job_type`: durable handler-unavailable failure after claim.
- JSON array/scalar historical payload: durable payload-invalid failure.
- Empty grants on `kernel.step_once`: accepted only as a legacy proof handler; not represented as an isolated surface.
- Runtime unregister of the P19 seed used by a queued job: durable paradigm-unavailable failure.
- Runtime catalog refresh between enqueue and claim: claim-time resolver result wins.
- Catalog refresh during one invocation: PostgreSQL snapshots and the resolved function OID govern that call; the next claim re-resolves.
- Multiple `worker_step` calls in one outer transaction are unsupported operational usage even though PostgreSQL permits function calls. Tests and worker callers use autocommit or one call per explicit transaction.

---

## File-by-file impact

| File | Change | Why | Dependencies / ordering |
|---|---|---|---|
| `docs/plans/P09-in-db-worker-2026-08-25.md` | Replace the draft scaffold with this complete deep plan; set final status only after critique blockers are folded | AGENTS plan-before-code gate | First |
| `sql/0021_p09_in_db_worker.sql` | **Create.** Add resolver, enqueue API, read-only tool invoker, worker state machine, COMMENT metadata on existing `step_once`, catalog refresh, and `p21` marker | Primary P09 implementation | One atomic numbered file after `0020` |
| `sql/README.md` | Add `0021`/`p21`, new APIs, queue ABI, outcome vocabulary, transaction boundary, P05 legacy-isolation warning, read-only tool restriction, and `$p09$` tag | Canonical install/runtime contract | After signatures are fixed |
| `tests/test_p09_in_db_worker.py` | **Create.** Catalog, enqueue, worker, wait, concurrency, tool dispatch, replay, and source-boundary acceptance tests | P09 completion proof | Uses existing shared harness only |
| `tests/test_p00_sql_source.py` | Rename current-tree test to `p21`; append `0021` in exact file-list assertions; expect `p21`; add the four function names to `KERNEL_FUNCTIONS`; update probe/composition file lists and version checks | P00 owns full source-tree/catalog pins | Atomic with SQL |
| `tests/test_p01_claim.py` | Update only assertions that apply the complete SQL root from `p20` to `p21`; P01-only expectations remain `p01` | Highest file wins | After SQL |
| `tests/test_p02_agent_steps.py` | Update complete-tree marker to `p21`; retain P02-only `p02`; append-monopoly expectation remains exactly one direct insert in `0002` | P09 synthetic errors delegate to P02 | After SQL |
| `tests/test_p03_wait_event.py` | No behavior change. Update a version assertion only if it applies the complete SQL root; P03-only tree remains `p03` | P09 only verifies completed P03 waits | Regression |
| `tests/test_p05_one_step_driver.py` | No production behavior change and no P05-only marker change. Existing source test must continue proving `0005` contains no worker or COMMENT registration | `step_once` body remains untouched | Regression |
| `tests/test_p06_plugin_catalog.py` | Update complete-tree marker to `p21`; update full-tree exact catalog counts/identity lists to include `kernel.step_once`; P06-only tree remains `p06` | P09 adds one canonical COMMENT source | Atomic with SQL |
| `tests/test_p07_grant_registry.py` | No behavior change. Update only complete-root version assertions if present; P07-only tree remains `p07` | Tool dispatch consumes P08/P07 indirectly | Regression |
| `tests/test_p08_four_seam_enforcement.py` | Update complete-tree file/version assertions and later-probe expectations to `0021`/`p21`; retain explicit tree-ending-at-`0020` expectations as `p20`; add P09 function names to any exact full-tree function list | P09 is after P08 but does not change seam signatures | Atomic with SQL |
| `tests/test_p19_paradigm_policies.py` | Update complete-tree markers to `p21`; sentinel probe prefix becomes `0022` through `next_sql_prefix`; truncated P19 tree remains `p19` | P09 consumes policy lookup without changing P19 ABI | Atomic with SQL |
| `tests/conftest.py` | **No change** | Existing `run_apply`, `psql`, `psql_session`, and `next_sql_prefix` are sufficient | — |
| `tools/apply_pg_cordis.py` | **No change** | No second apply path or loader behavior | — |
| `sql/0000_kernel.sql` through `sql/0020_p08_four_seam_enforcement.sql` | **No edits** | Append-only release policy | — |
| `sql/0004_p04_sleep_retry.sql`, `.p19-backup/`, `scratch/` | **No change and no dependency** | Outside P09 ship set | Must not enter the P09 commit |

Implementation must search all tests for literal `p20`, `0020_p08_four_seam_enforcement.sql`, and full-tree file lists. Retarget only assertions using the current complete `SQL` root; tests that deliberately copy a truncated tree keep the marker of that tree.

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
- payload fixture fields remain unchanged;
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
- README distinguishes:
  - plan P09;
  - SQL marker `p21`;
  - queue handler versus tool invocation;
  - legacy P05 fold versus P08-isolated folds;
  - one call per transaction.

### W96 — Current-tree pins

Update only complete-tree expectations.

Verification approach:

```text
search tests/ for:
  p20
  0020_p08_four_seam_enforcement.sql
  KERNEL_FUNCTIONS
  exact plugin_catalog counts or identities
```

Classify every hit as:

- full current tree → update to `p21`/`0021`;
- deliberately truncated tree → leave unchanged.

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
| `test_p09_single_worker_yields_reclaims_and_completes_mock_run` | Same worker ID calls three times over the P05 proof payload and observes `yield`, `yield`, `complete`; one jobs row; ordered `llm,tool,llm,tool,llm,final`; final result `ok` |
| `test_p09_worker_revalidates_paradigm_and_handler_after_enqueue` | Runtime policy/handler removal before claim produces the exact durable P09 failure |
| `test_p09_worker_maps_p05_failure_to_terminal_job` | Invalid P05 config logs P05 error; worker copies it into `jobs.error`; outcome `fail` |
| `test_p09_complete_and_fail_without_log_are_protocol_failures` | Custom ABI-compatible handlers returning terminal words without log rows produce P09 synthetic errors |
| `test_p09_unknown_and_null_handler_outcomes_fail_durably` | Closed outcome vocabulary enforced |
| `test_p09_wait_requires_completed_p03_registration` | One test handler calls `await_event` then returns `wait`, leaving a valid WAITING row; another returns `wait` without registration and becomes ERROR |
| `test_p09_handler_exception_propagates_and_rolls_back_claim` | Custom handler raises; worker SQL fails; claim/log changes from the call are absent and job remains PENDING |
| `test_p09_transition_fence_returns_lost_claim` | Controlled handler expires/loses its claim before a requested transition; worker does not claim success |
| `test_p09_in_db_tool_authorizes_and_executes_read_only_entrypoint` | P08-authorized in-db stable `jsonb→jsonb` function executes once and returns protocol/descriptor/result |
| `test_p09_in_db_tool_refuses_host_queue_and_effectful_entries` | Host rows, queue rows, transactional rows, and external rows are never invoked |
| `test_p09_in_db_tool_checks_claim_before_and_after_execution` | Dead initial claim fails; a read-only test function that outlives a short lease has its result rejected |
| `test_p09_in_db_tool_does_not_cache_authorization` | Revoke between calls makes the next invocation fail through P08 |
| `test_p09_replay_preserves_jobs_logs_runtime_catalog_and_policies` | In-place replay preserves scheduler/log data, host definitions, runtime policy upserts, and reports `p21`; canonical COMMENT row is restored |
| `test_p09_source_boundaries` | No historical-file edits, direct status UPDATE, direct agent_steps INSERT, loop, TEMP, host SDK, spawn, extension, roles, transaction control, or `CREATE OR REPLACE step_once` in `0021` |

Test-defined queue/tool functions may be installed in the disposable test database and registered through COMMENT plus `refresh_plugins()`. They are fixtures, not product SQL.

### W99 — Regression and delivery gate

Run:

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

Mitigations:

- queue resolver rejects handlers that declare required grants;
- tool execution uses P08 authorization;
- no P09 statement claims that `worker_step` itself closes the fold seam;
- a later real driver must consume `fold_slice_messages` rather than replacing this warning with documentation.

### One transaction can hold database resources during handler execution

The current canonical handler uses a bounded SQL mock, so P09 does not solve long external transport transactions. A future in-db HTTP handler must not be enabled merely because it matches the queue signature; its transaction/lease behavior requires a later plan.

### Trusted control-plane APIs

A database principal with arbitrary SQL can call `enqueue_job`, modify COMMENT metadata, or invoke `worker_step`. P09 follows P07/P08’s current same-role trust boundary and does not claim SQL-level tenant authentication.

Mitigation: P10 and later model-tool routing must not expose P09 control-plane functions as tools.

### Runtime catalog drift

A queued job may reference a handler removed by a later catalog refresh. P09 terminalizes this as `P09_HANDLER_UNAVAILABLE`. Repair requires a new run because P01 keeps one unique jobs row per run and no retry machine exists.

### In-place rollback

Removing `0021` from a source directory and replaying in place will not remove already-created functions or the COMMENT. Supported rollback is:

- reset/recreate the database; or
- append a later reversal SQL file.

Do not edit or delete `0021` as a release migration.

### Migration

There is no table/schema migration and no external public API compatibility promise before P09. Existing jobs rows are preserved. They become worker-compatible only if their `job_type` and payload satisfy the P09 contract.

---

## Implementation order

1. Complete the P09 plan critique and fold every P0/P1 into this document. Do not start SQL while the status is still critique-pending.
2. Create `sql/0021_p09_in_db_worker.sql` with W90–W95 as one coherent file:
   1. queue resolver;
   2. enqueue API;
   3. read-only tool dispatcher;
   4. worker state machine;
   5. COMMENT metadata on the existing `step_once`;
   6. `refresh_plugins()`;
   7. `get_schema_version() → 'p21'`.
3. Apply to a disposable database and smoke-check:
   - `p21`;
   - canonical catalog row;
   - direct step entrypoint OID;
   - enqueue → one `yield`;
   - no new table/type/extension.
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

None remain for P09 implementation.

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
- `tests/test_p05_one_step_driver.py` — current manual claim/step/outcome mapping
- `tests/test_p00_sql_source.py` — current-tree file, function, and marker pins


> 💡 Continue this plan conversation with ask_oracle(chat_id: "p09-in-db-worker-plan-F828E4", new_chat: false)