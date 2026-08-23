# P02 — `cordis.agent_steps` Log and Checkpoint-as-Log

Date: 2026-08-23  
Status: **ready to implement**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P02  
Depends on: P00, implemented; P01 implemented in-tree (`sql/0001_p01_claim.sql`, `tests/test_p01_claim.py`)  
Parallel with: P06  
Do not edit `sql/0001_p01_claim.sql` (append-only numbered files; P01 verbs stay jobs-only)  
Primary deliverable: `sql/0002_p02_log.sql`, retargeted P00 source-tree tests, new `tests/test_p02_agent_steps.py`

## Summary

P02 adds the schema-qualified `cordis.agent_steps` append-only history log as the sole durable history source for a run. It adds the log writer, claim-aware append helpers, checkpoint batching through the log, named-step lookup, LLM checkpoint lookup, and the `run_state()` projection. On the product tree `cordis.jobs` already exists and claim-aware helpers fence through it; a P02-only temp sql-root (omit `0001`) still exercises the unfenced path. P02 does not create `agent_runs`, jobs, wait/sleep tables, projection-cache tables, checkpoint tables, HTTP functions, or a one-step driver. The implementation is a numbered SQL addition plus incremental test retargeting from the current P01 tree. The apply CLI is **unchanged**: `sanitize_sql_for_preflight` (`tools/apply_pg_cordis.py:112-217`) already blanks dollar-quoted plpgsql bodies and quoted literals before `FORBIDDEN_STMTS`. `tests/conftest.py` and `tests/test_p01_claim.py` already exist. W19 is a verify-only gate, not a loader rewrite.

---

## Goal

Implement the P02 contract from `docs/plans/2026-08-23-pg-cordis-development.md:118-126`:

- Create `cordis.agent_steps` as an append-only historical log.
- Keep the log as the unique history source of truth.
- Make checkpoint state a log event or log fold, never a separate `c_*` table.
- Provide one unfenced product writer, `cordis.emit_step`.
- Provide claim-aware append and checkpoint helpers that fence through P01 when `cordis.jobs` exists.
- Derive stable step names from the log.
- Provide a stable lookup for an existing `llm` event for a named step.
- Provide `run_state()` as a projection with F-shaped labels:
  - `final`
  - `error`
  - `in-progress`
- Reserve the future P03, P04, and P17 event kinds in the table constraint without implementing those subsystems.
- Keep P02 independently installable without `cordis.jobs` via a temp SQL root that omits `0001`. plpgsql bodies already apply (`test_plpgsql_end_inside_dollar_quotes_applies`).
- Avoid `CREATE SCHEMA absurd`, a second queue, `agent_runs`, `rlm_vars`, HTTP, or the scratch driver.

### 中文摘要

P02 在本仓规范 SQL 树中新增 `0002_p02_log.sql`，建立 `cordis.agent_steps` 追加式历史日志。日志是唯一历史真相；`run_state()`、下一步名称和 LLM checkpoint 都从日志折叠或查询得到，不建立独立 checkpoint 表。产品写入入口是 `cordis.emit_step`；当 P01 的 `cordis.jobs` 已存在时，`emit_step_claimed` 与 `checkpoint` 自动使用 `claim_token + RUNNING + 未过期 lease` 做 fencing，失去 claim 返回 `false` 且不追加日志。P02 不实现 worker、LLM、等待、sleep、retry、`agent_runs` 或 workspace。

---

## Execution index

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W19 | Confirm landed preflight still accepts plpgsql `0002` | `test_plpgsql_end_inside_dollar_quotes_applies` and `test_top_level_transaction_control_exits_2` stay green; no loader edit | `tools/apply_pg_cordis.py`, `tests/test_p00_sql_source.py` | P00, P01 | Small |
| W20 | Add the append-only log table and indexes | `cordis.agent_steps` has the exact envelope, named CHECKs, sequence, primary key, and LLM step lookup index; no `c_*` or `agent_runs` table exists | `sql/0002_p02_log.sql` | W19 | Medium |
| W21 | Add the unfenced writer | `cordis.emit_step` is the only product SQL function containing a direct insert into `cordis.agent_steps`, returns the inserted sequence, and is replay-safe | `sql/0002_p02_log.sql` | W19, W20 | Small |
| W22 | Add claim-aware append and checkpoint batching | P02 works without `cordis.jobs`; once a jobs-shaped table exists, live-token updates fence appends atomically; lost ownership returns `false` with no mutation; event `run_id` mismatch raises | `sql/0002_p02_log.sql` | W20–W21 | Medium |
| W23 | Add log projections and checkpoint lookup | `next_step_name`, `llm_checkpoint`, and `run_state` have the exact signatures and stable behavior for completed and crash-shaped histories | `sql/0002_p02_log.sql` | W20–W21 | Medium |
| W24 | Incrementally retarget P00/P01 source tests to the P02 tree | Fresh-apply lists `0002`, version `p02`, `agent_steps` present; forbidden-token and plpgsql probes unchanged | `tests/test_p00_sql_source.py` | W20 | Medium |
| W25 | Add P02 protocol tests | Replay, three-step folding, crash-prefix naming, checkpoint hit/miss, kind checks, no-`c_*`, no-public-log, claim behavior with and without jobs, and append monopoly all pass | `tests/test_p02_agent_steps.py` | W19–W24 | Medium |
| W26 | Update the source-tree marker documentation | The README distinguishes the `0000`-only `p00` marker from the current `0002` tree’s `p02` marker | `sql/README.md` | W20, W23 | Small |

---

# Background

## Signed architecture contracts

Do not reopen D1–D9 or snapshot §4. The following contracts bind P02:

- The append-only session/run log is the unique historical source of truth.
- Checkpoints are log events or folds of the log, not an authoritative `c_*` table.
- `cordis.jobs` owns scheduling eligibility and claims; it is not run history.
- The worker and host SDK use one claim protocol.
- `run_state()` and prompt/message folds are projections and are never authoritative.
- Workspace state such as `rlm_vars` is a separate run-owned execution tier and is outside P02.
- No `CREATE EXTENSION` is used in P00–P19.
- The repository SQL tree is the contract source; pg-agent and scratch are reference/test environments only.
- There is one logical queue. P02 must not introduce an execution queue or an Absurd-style parallel queue.

The signed sources are:

- `docs/decisions/2026-08-23-pending.md:31-49`
- `docs/analysis/2026-08-23-i-architecture-snapshot.md:61-70`
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md`
- `docs/analysis/2026-08-23-e-absurd-durable-execution.md`

## F protocol surface

The F protocol defines the semantics P02 supplies to later plans:

- `run_id` is the logical run identity.
- `agent_steps` is the append-only history.
- `step_name` is attempt-independent and normally has the form `s-N`.
- A retry of an incomplete step reuses the same `step_name`.
- A child run receives its own `run_id` and starts its own `s-1` sequence.
- A worker without the current live claim token must not append.
- A claim-aware append must use a mutating predicate equivalent to:

```text
claim_token = supplied token
AND status = 'RUNNING'
AND claim_expires_at > current wall-clock time
```

- Zero rows updated means lost ownership.
- `checkpoint` appends log events atomically with the ownership check.
- The `llm` event is written before tools when possible, so a crash after the provider call can skip a second provider call.
- Tools are not made exactly-once by P02.
- P03 and P04 will use reserved `run/await`, `run/wake`, `run/sleep`, and related event kinds.
- P17 will use reserved spawn kinds.

Relevant references:

- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:40-44`
- `:71-86`
- `:91-106`
- `:112-137`
- `:214-223`
- `:262-272`

## G and scratch are semantic analogs, not ABI

`docs/analysis/2026-08-23-g-rlm-one-step-driver.md` provides useful semantics but must not be copied into the product tree:

- `emit_step_claimed` checks a token and returns a lost-claim result.
- `rlm_next_step_name` is based on LLM-bearing log history rather than attempt number.
- `rlm_llm_checkpoint` finds an existing `llm` payload for a named step.
- Fingerprint mismatch is a P05 protocol error, not a P02 implementation.
- The one-step driver and HTTP call remain P05 scope.

`scratch/yield_walkthrough/REPORT.md` proves three claims and three named steps:

```text
llm, tool → s-1
llm, tool → s-2
llm, final → s-3
```

It does not prove claim-timeout fencing, real provider idempotency, or cross-yield workspace behavior. P02 must not depend on or promote the scratch SQL.

## Existing pg-agent precedent

`pg-agent/v2/pg_agent_functional.sql` is a morphology reference in another database and schema:

- `public.agent_steps` at approximately `:55-68` uses:
  - `run_id`
  - `seq bigserial`
  - `kind`
  - `payload jsonb`
  - `created_at`
  - composite primary key `(run_id, seq)`
- `emit_step` at approximately `:290-294` directly inserts without fencing.
- `run_state()` at approximately `:389-402` folds the log but uses `SUCCESS|ERROR|RUNNING`.
- The pg-agent table has a foreign key to `public.agent_runs`, which P02 intentionally does not copy.
- The pg-agent `jobs` table and `worker()` are in `public` and another database; they are not dependencies of the P02 SQL tree.

P02 reuses the useful envelope shape while correcting the missing contracts:

- schema qualification under `cordis`;
- an indexed `step_name` envelope field;
- reserved event kinds;
- claim-aware helpers;
- F-shaped projection labels;
- no second run-identity table.

## DSH envelope evidence

`deepseek-harness/packages/core/session/src/types.ts:339-440` shows a richer merge-extensible event envelope containing:

- event type;
- sequence;
- time;
- payload;
- `sourceEventSeqs`;
- `surfaceOp`;
- `ignorable`.

P02 deliberately does not add `ignorable`, `sourceEventSeqs`, or `surfaceOp` as columns. They remain future envelope extensions. P02 stores only the fields needed for the current durable-agent kernel and keeps the JSONB payload available for later event-specific metadata.

This is a deliberate scope boundary, not a rejection of the DSH contract. A later envelope expansion must be additive and must not turn projections into a second source of truth.

## Absurd comparison

`absurd/sql/absurd.sql:210-285` creates per-queue task, run, checkpoint, event, and wait tables. Its `c_*` checkpoint table is specifically the design P02 must avoid:

- it would create a second durable truth beside `agent_steps`;
- it would require synchronization between checkpoint rows and log rows;
- it would make named-step recovery independent of the historical record.

P02 instead makes checkpoint lookup a deterministic query over `cordis.agent_steps`. A future performance cache may be considered only as a non-authoritative projection, outside P02.

## P00 install contract

The product SQL tree currently contains:

```text
sql/0000_kernel.sql     → schema cordis; get_schema_version() body 'p00' if applied alone
sql/0001_p01_claim.sql  → cordis.jobs + claim verbs; replaces version body with 'p01'
```

A full apply of the current tree returns `'p01'`. `0000` is not edited; the last numbered file wins.

The apply command:

- discovers direct child files matching `NNNN_slug.sql`;
- requires `0000_kernel.sql`;
- sorts by numeric prefix;
- loads all files before starting PostgreSQL or creating the target database;
- applies the tree in one transaction;
- uses a target-database advisory lock;
- verifies only the schema and the zero-argument text-returning version function;
- does not pin the returned version string.

P02 adds `sql/0002_p02_log.sql`. Number `0002` remains correct now that `0001` exists. Taking `0001` would collide.

No loader, manifest, Python file list, or advisory-lock behavior changes. Preflight already strips dollar quotes before `FORBIDDEN_STMTS` (`tools/apply_pg_cordis.py:94-108`).

Relevant files:

- `sql/0000_kernel.sql`
- `sql/0001_p01_claim.sql`
- `sql/README.md`
- `tools/apply_pg_cordis.py:44-81`
- `tools/apply_pg_cordis.py:94-114`
- `tools/apply_pg_cordis.py:202-242`

## P00 tests that will break

The current `tests/test_p00_sql_source.py` already describes the **P01** tree (not the empty P00 kernel). P02 retargets incrementally:

- `test_fresh_apply_lists_current_tree_and_p01` (`:35-80`): files `0000_kernel.sql,0001_p01_claim.sql`, version `'p01'`, `cordis.jobs` present, `agent_steps`/`run_waits`/`run_events` count 0, P01 function list. Change to include `0002_p02_log.sql`, version `'p02'`, `agent_steps` count 1, plus the six P02 functions. Prefer renaming to `..._and_p02` in the same edit.
- Probe / later-table / invalid-tree / rollback fixtures already use `next_sql_prefix` (`tests/conftest.py`). Keep that; do not reintroduce hard-coded `0001_p01_probe.sql`.
- `test_sql_tree_has_no_forbidden_tokens` (`:355-369`) already imports `FORBIDDEN_STMTS` and allows `CREATE TABLE cordis.*` after dollar-quote strip. Do **not** rewrite it; `0002` must still pass it.
- `test_plpgsql_end_inside_dollar_quotes_applies` (`:177-207`) and `test_top_level_transaction_control_exits_2` (`:210+`) already encode W09. Keep them.
- Composition (`:383+`) expects version `'p01'` and `cordis.jobs`; bump version to `'p02'` and assert `cordis.agent_steps` in the cordis DB and still no `public.agent_steps`.

Do not re-extract `tests/conftest.py`. Do not weaken invalid-filename, nested SQL, GRANT, meta-command, database-DDL, no-database-mutation, or tree-wide rollback tests.

## P01 interaction

P01 is implemented. Treat `sql/0001_p01_claim.sql` as the frozen claim ABI. Do **not** edit it from P02 (`AGENTS.md`: later Px append higher-numbered files).

Landed objects (`sql/0001_p01_claim.sql`):

| Object | Contract |
|---|---|
| `cordis.jobs` | `jobs_pkey`, `jobs_run_id_key UNIQUE (run_id)` (including terminal rows), `jobs_claim_token_key UNIQUE (claim_token)`, `jobs_status_check`, `jobs_claim_fields_check` (RUNNING requires token + `claimed_by` + expiry; non-RUNNING nulls them) |
| `cordis.claim_job(text,text,integer)` | `SETOF cordis.jobs`; default lease 90s; `release_stale` then `FOR UPDATE SKIP LOCKED` on `PENDING` only |
| `cordis.renew_claim(uuid,integer)` | boolean; **absolute reset** `clock_timestamp() + make_interval`; default 90s |
| `cordis.yield_claim(uuid)` / `complete_claim(uuid,jsonb)` / `fail_claim(uuid,jsonb)` | boolean; live-token fence; `fail_claim` rejects SQL NULL `p_reason` |
| `cordis.release_stale(text,integer)` | integer rowcount; expired RUNNING → PENDING |
| Fence predicate | `claim_token = $1 AND status = 'RUNNING' AND claim_expires_at > clock_timestamp()` |
| Packaging | `LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path TO pg_catalog`; builtins `pg_catalog.*`; parameter errors `ERRCODE = 'invalid_parameter_value'` |
| Version | `get_schema_version() → 'p01'` (`LANGUAGE sql IMMUTABLE`) |

None of those functions reference `agent_steps` or `emit_step`. That is P01’s “jobs only” contract, not an unfinished stitch inside `0001`.

P02 composition:

- `0002` is the last version-marker writer → `'p02'`.
- Claim-aware P02 functions detect `cordis.jobs` at runtime (`to_regclass`). Full-tree tests create live rows with **`claim_job`**, not a 4-column stub `INSERT` (that fails `jobs_claim_fields_check`).
- P02-only tests copy `0000`+`0002` and omit `0001`; there they may use a synthetic jobs table.
- `0002` does not `CREATE OR REPLACE` P01 verbs. `tests/test_p01_claim.py` must stay green.

**Log effects of complete/fail/stale:** out of P02 SQL. A later numbered file (not `0002`, not P03) may `CREATE OR REPLACE` those three verbs to call `cordis.emit_step` in the same transaction. Until then, jobs `DONE`/`ERROR` with `run_state() = in-progress` is expected. Workers must not treat jobs status as history.

## Isolation and write monopoly

P07 will later own database grants and permissions. P02 cannot use `GRANT` or `REVOKE` because those statements are forbidden in numbered SQL files.

Therefore the P02 write monopoly is enforced at the product source level:

- `cordis.emit_step` is the only function containing a direct `INSERT INTO cordis.agent_steps`.
- `emit_step_claimed` and `checkpoint` call `emit_step`.
- Product SQL contains no direct `UPDATE` or `DELETE` against `cordis.agent_steps`.
- Tests scan the comment-stripped product SQL tree for violations.
- Direct SQL callers can still bypass the convention until P07 establishes the permission boundary; this is an explicit temporary limitation.

---

# Current-state analysis

## Existing responsibilities and ownership

| Component | Current responsibility | P02 implication |
|---|---|---|
| `sql/0000_kernel.sql` | Creates `cordis` and `get_schema_version()` only | Leave unchanged; append `0002_p02_log.sql` |
| `tools/apply_pg_cordis.py` | Discovers, preflights (dollar-quote-aware), applies, verifies | Unchanged in P02 |
| `sql/README.md` | Documents numbering, replay, qualification, and forbidden scope | Update marker wording and add the P02 log boundary |
| `tests/test_p00_sql_source.py` | Describes the current P01 tree (`0001`, version `p01`) | Incremental retarget to `0002` / `p02` / `agent_steps` |
| `pg-agent/v2/pg_agent_functional.sql` | Owns a separate `public.agent_steps` and unfenced writer in `da_agent` | Reference only; do not modify or copy |
| `scratch/yield_walkthrough/` | Proof-only lease/yield walkthrough | No dependency and no ABI reuse |
| `sql/0001_p01_claim.sql` | Owns `cordis.jobs` and claim verbs | Present; P02 detects it at runtime; verbs do not emit yet |
| Future P03/P04/P17 | Own wait, sleep, wake, retry, and spawn transitions | P02 reserves their event kinds but does not implement their tables or transitions |
| Future P05 | Owns `rlm_step_once`, HTTP idempotency, tool execution, and fingerprint mismatch policy | P02 supplies only the log primitives and lookup APIs |

## Current data/control flow

Before P02:

```text
apply_pg_cordis.py
  → discover 0000_kernel.sql, 0001_p01_claim.sql
  → create/use target database
  → apply one transaction
  → cordis schema, cordis.jobs, claim verbs, version p01
```

There is no product log, no product writer, no step lookup, and no run projection. Jobs status is eligibility only.

The pg-agent path is separate:

```text
pg-agent/v2/pg_agent_functional.sql
  → public.agent_runs
  → public.agent_steps
  → public.emit_step()
  → public.run_state()
```

That path is in `da_agent` and is not a dependency.

After P02, when applied alone:

```text
producer or test
  → cordis.emit_step(run_id, kind, payload, step_name)
  → cordis.agent_steps append row
  → next_step_name / llm_checkpoint / run_state read the log
```

After P01 is also present:

```text
worker with token
  → cordis.emit_step_claimed(token, run_id, kind, payload, step_name)
      → detect cordis.jobs
      → UPDATE jobs with live-token predicate
      → if zero rows: false, no log append
      → if one row: extend lease and call emit_step
  → COMMIT
```

Batch checkpoint path:

```text
checkpoint(token, events)
  → validate event-array shape
  → if cordis.jobs exists:
       UPDATE jobs using token + RUNNING + unexpired lease
       if zero rows: false, no append
       derive run_id from the claimed job
  → if cordis.jobs is absent:
       derive run_id from event envelopes
  → call cordis.emit_step once per event
  → return true
```

Projection path:

```text
cordis.agent_steps
  ├─ next_step_name(run_id)
  ├─ llm_checkpoint(run_id, step_name)
  └─ run_state(run_id)
```

No projection writes back to `agent_steps`, jobs, or workspace.

## Mutation points

P02 has exactly these product mutation points:

1. `cordis.emit_step`
   - validates through function parameters and table constraints;
   - allocates the `bigserial` sequence value;
   - appends one row.
2. `cordis.emit_step_claimed`
   - optionally updates the matching live jobs lease;
   - calls `emit_step` only after the fence succeeds.
3. `cordis.checkpoint`
   - optionally updates one live jobs lease;
   - calls `emit_step` for each event in the batch.
4. The version replacement at the end of `0002_p02_log.sql`
   - changes only the version function body from `p00` or `p01` to `p02`.

P02 does not update or delete log rows. It does not mutate `agent_runs`, `rlm_vars`, jobs status, wait rows, event rows, or external systems.

## Transformation boundaries

| Boundary | Input | Transformation | Output |
|---|---|---|---|
| Writer boundary | scalar function arguments | table constraints + sequence allocation | one `agent_steps` row |
| Checkpoint boundary | JSONB event array | envelope validation, optional claim fence, repeated writer calls | several ordered log rows or no mutation |
| Step-name boundary | committed log rows | count completed LLM-bearing steps and detect an incomplete trailing LLM | `s-N` text |
| Checkpoint lookup boundary | `run_id`, `step_name` | indexed `llm` event lookup | zero or one full log row |
| State projection boundary | all events for a run | final/error precedence and latest payload extraction | one `run_state` row |
| Claim boundary | token and jobs table presence | runtime relation detection and fenced update | boolean ownership result |

---

# Design

## Resolved decisions

| # | Decision | Rejected alternative | Rationale |
|---|---|---|---|
| 1 | Use `sql/0002_p02_log.sql` even if `0001_p01_claim.sql` is not yet present | Wait until P01 lands before numbering | Gaps are allowed, P00 names `0002` as the P02 example, and `0001` is reserved by P01 |
| 2 | Claim-aware functions call `to_regclass('cordis.jobs')` at runtime and fence only when the table exists | Raise when jobs is absent, or ship only an unfenced writer | P02 must install and test independently, then compose automatically with P01 |
| 3 | Use the five pg-agent envelope fields plus nullable indexed `step_name` | Add the full DSH envelope now | P02 needs named-step lookup but not future `ignorable`, `sourceEventSeqs`, or `surfaceOp` semantics |
| 4 | Add a `CHECK` for kernel and reserved event kinds | Comment-only vocabulary or a generalized append validator | P03/P04/P17 need the table shape now; broader semantic validation is outside P02 |
| 5 | Do not create `cordis.agent_runs`; use `run_id text NOT NULL` without a foreign key | Add a new run-identity table or FK to pg-agent tables | Run identity belongs to the log key for this item; P01 also keys jobs by `run_id` |
| 6 | Use `final`, `error`, and `in-progress` as `run_state` labels | Use pg-agent’s `SUCCESS|ERROR|RUNNING`, or add `awaiting` now | The labels match F; `awaiting` is not emitted until P03 |
| 7 | Replace the version function body with `p02` at the end of `0002` | Leave P00’s `p00`, or let P01’s `p01` remain final | Numeric apply order makes `0002` the last marker writer when both P01 and P02 exist |
| 8 | Use `bigserial` for `seq` | Use per-run `COUNT(*)+1` or an identity scheme | It matches the existing log precedent; sequence gaps after rollback are harmless because step naming does not use `seq` alone |
| 9 | Ship `emit_step`, `emit_step_claimed`, `checkpoint`, `next_step_name`, `llm_checkpoint`, and `run_state` | Add `rlm_step_once`, HTTP, or wait/sleep functions | Those later execution responsibilities belong to P03–P05 |
| 10 | P02 exposes an LLM-row lookup only; P05 owns HTTP skipping and fingerprint mismatch | Implement provider idempotency in P02 | P02 cannot own HTTP policy or provider behavior |
| 11 | P01 remains responsible for jobs mutation; P02 supplies the emit primitive that P01 can call | Edit P01’s jobs code from this plan | P02 is parallel with P01 and must not duplicate or rewrite its claim state machine |
| 12 | Add a separate `tests/test_p02_agent_steps.py`, while retargeting P00 tests | Put all log behavior into the P00 module | Loader/source tests and runtime log protocol tests have different responsibilities |
| 13 | Enforce the product writer monopoly by source-tree tests | Add `REVOKE` or role changes | Grant statements are forbidden until the later permission work |

### Mid-flow confirmations (2026-08-23)

The user confirmed these four remaining forks as drafted:

1. `next_step_name` resumes an incomplete trailing `llm` (not G’s `1+COUNT(llm)`).
2. `step_name` CHECK stays `^s-[1-9][0-9]*$`; `llm`/`tool` require a non-NULL matching name.
3. Every `checkpoint` event carries `run_id` (same JSON shape with and without `cordis.jobs`).
4. `run_state` status `final` beats a later `error` row; the error remains in the log.

## Component 1 — `sql/0002_p02_log.sql` and version composition

### File and ownership

**Kind:** numbered SQL migration/source file  
**Path:** `sql/0002_p02_log.sql`  
**Created by:** the SQL source tree; executed by `tools/apply_pg_cordis.py`  
**Ownership:** no runtime object owns the file; numeric filename order controls application

The file must:

- contain only schema-qualified `cordis` objects;
- contain no transaction-control statements;
- contain no psql meta-commands;
- contain no `GRANT`, `REVOKE`, role DDL, extension DDL, database DDL, or `absurd` schema;
- be safe to replay after P00 and after P01;
- not edit `sql/0000_kernel.sql`;
- not require `cordis.jobs` to exist during installation.

### Object ordering within the file

The implementation order inside the file is fixed:

1. `cordis.agent_steps` table.
2. Table indexes and constraints that are separate DDL objects.
3. `cordis.emit_step`.
4. `cordis.emit_step_claimed`.
5. `cordis.checkpoint`.
6. `cordis.next_step_name`.
7. `cordis.llm_checkpoint`.
8. `cordis.run_state`.
9. `cordis.get_schema_version()` replacement returning `p02`.

The version marker must be last so a failed earlier statement rolls back the marker replacement with the rest of the file.

### Function packaging

All P02 plpgsql functions match the landed P01 packaging:

- schema-qualified `cordis.*` names;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`;
- builtins written `pg_catalog.clock_timestamp()`, `pg_catalog.make_interval(secs => …)`, `pg_catalog.btrim(…)` (do not rely on the caller path);
- `VOLATILE` for writers, `STABLE` for log reads;
- parameter errors `RAISE EXCEPTION … USING ERRCODE = 'invalid_parameter_value'`.

Capture **one** `pg_catalog.clock_timestamp()` per claim-aware call (like `claim_job`’s `t_claim`) and use it in both the fence predicate and the lease `GREATEST`. Do not evaluate `clock_timestamp()` twice the way `renew_claim` currently does in SET vs WHERE.

No public aliases are added. No `heartbeat_claim` alias is added; lease renewal remains P01’s `renew_claim`.

The `cordis.get_schema_version()` replacement at the end of `0002` stays `LANGUAGE sql IMMUTABLE SECURITY INVOKER` with a zero-argument `text` identity (`sql/0000_kernel.sql:7-14`). Do not rewrite the version function as plpgsql.

### Loader compatibility (W19) — already landed

Do **not** edit `tools/apply_pg_cordis.py` in P02. Preflight uses `sanitize_sql_for_preflight` (`:112-217`), a SQL-state scanner that blanks comments, quotes, and dollar-quoted bodies before `FORBIDDEN_STMTS`. `strip_sql_dollar_quotes` is an alias of that sanitizer (`:206-207`). `test_plpgsql_end_inside_dollar_quotes_applies` and `test_top_level_transaction_control_exits_2` already lock plpgsql `END;` vs top-level `END;`.

Re-run those tests after `0002` exists. Do **not** adopt “omit the semicolon after `END`” as house style.

---

## Component 2 — `cordis.agent_steps` table

### Type and lifecycle

**Kind:** PostgreSQL table  
**Name:** `cordis.agent_steps`  
**Lifecycle:** one append-only row per committed historical event  
**Creator:** `0002_p02_log.sql` through `CREATE TABLE IF NOT EXISTS`  
**Owner:** the installing PostgreSQL role; P02 does not alter ownership or ACLs

The table is the sole P02 history source. It is not a queue, current-state table, run registry, or checkpoint cache.

### Exact columns

| Column | Type | Nullability/default | Contract |
|---|---|---|---|
| `run_id` | `text` | `NOT NULL` | Logical run identity; no FK |
| `seq` | `bigserial` / `bigint` | `NOT NULL` | Monotonic allocation sequence used for ordering within a run; gaps allowed |
| `kind` | `text` | `NOT NULL` | Kernel or reserved event kind |
| `payload` | `jsonb` | `NOT NULL` | Lossless event-specific data; JSONB `null` is allowed, SQL `NULL` is not |
| `step_name` | `text` | nullable | Named-step envelope field, normally `s-N` |
| `created_at` | `timestamptz` | `NOT NULL DEFAULT pg_catalog.clock_timestamp()` | Wall-clock append timestamp |

The composite primary key is:

```text
PRIMARY KEY (run_id, seq)
```

`seq` is a table-level `bigserial` sequence, not a per-run counter. PostgreSQL sequence values consumed by rolled-back inserts are not reused. The log therefore guarantees ordered committed rows, not contiguous per-run sequence numbers.

### Structural constraints

The table must include these **named** CHECKs (names are the replay/migration handle; later files `DROP CONSTRAINT IF EXISTS <name>` / `ADD CONSTRAINT`):

```text
agent_steps_run_id_check
  CHECK (btrim(run_id) <> '')

agent_steps_kind_check
  CHECK (kind IN (
    'llm', 'tool', 'final', 'error',
    'run/claim_timeout', 'run/await', 'run/sleep', 'run/wake', 'run/yield',
    'spawn/start', 'spawn/end', 'event/emit'
  ))

agent_steps_step_name_format_check
  CHECK (step_name IS NULL OR step_name ~ '^s-[1-9][0-9]*$')

agent_steps_step_name_presence_check
  CHECK (kind NOT IN ('llm', 'tool') OR step_name IS NOT NULL)
```

`agent_steps_kind_check` is the reserved-kind migration seam. Adding `run/cancel` or a retry kind later is a numbered-file `DROP CONSTRAINT IF EXISTS agent_steps_kind_check` + `ADD CONSTRAINT`, not an unnamed rewrite. Cancel is unassigned in P00–P19 (same note as P01); this name exists so that addition does not require table rebuild.

The kind set is exactly:

```text
llm
tool
final
error
run/claim_timeout
run/await
run/sleep
run/wake
run/yield
spawn/start
spawn/end
event/emit
```

The kind prefix is only a storage naming convention. It does not grant authorization or imply a PostgreSQL type hierarchy.

The table does not add:

- DSH `ignorable`;
- DSH `sourceEventSeqs`;
- DSH `surfaceOp`;
- turn or step enclosure checks;
- payload-schema validation;
- a foreign key to `agent_runs`;
- a foreign key to `jobs`;
- a status column;
- an authoritative checkpoint column;
- a `c_*` table.

The `llm` and `tool` step-name requirement is needed because P05 must be able to correlate a provider checkpoint and its tool observation to the same named step. `final`, `error`, and control-plane events may omit `step_name` because P01 and future control paths may not have a current model step.

### Indexes

The primary key supplies ordered lookup by `(run_id, seq)`.

Add one partial unique index. PostgreSQL does not accept a schema-qualified index name in `CREATE INDEX`; the index lives in schema `cordis` because the table does:

```text
CREATE UNIQUE INDEX IF NOT EXISTS agent_steps_llm_step_idx
  ON cordis.agent_steps (run_id, step_name)
  WHERE kind = 'llm'
```

This index has three purposes:

1. It makes `llm_checkpoint(run_id, step_name)` a direct indexed lookup.
2. It prevents two committed LLM checkpoints for the same named step.
3. It allows P05 to distinguish an existing checkpoint from a missing checkpoint without a second table.

Tool rows are not unique by `step_name`; a step may have multiple tool events in later policy extensions.

### Append-only policy

P02 does not create an update/delete trigger. The source-tree contract is:

- only `cordis.emit_step` contains a direct insert;
- helpers call `emit_step`;
- P02 contains no update/delete statement against `cordis.agent_steps`;
- P02 tests scan the product SQL tree after stripping comments.

The absence of an ACL boundary is intentional until P07. Direct role-level mutation remains possible in the interim and is a known risk.

---

## Component 3 — `cordis.emit_step`

### Interface

```text
cordis.emit_step(
    p_run_id     text,
    p_kind       text,
    p_payload    jsonb,
    p_step_name  text DEFAULT NULL
) RETURNS bigint
```

Catalog identity:

```text
cordis.emit_step(text,text,jsonb,text)
```

Execution contract:

- `LANGUAGE plpgsql`
- `VOLATILE`
- `SECURITY INVOKER`
- synchronous;
- raises on invalid input or table constraint failure;
- returns the inserted `seq`.

### Ownership

`emit_step` is the only product SQL writer that may directly insert into `cordis.agent_steps`.

Every other P02 writer calls this function. This keeps row construction, default handling, and returned sequence behavior in one place.

### Input behavior

The function must reject or allow inputs as follows:

| Input | Behavior |
|---|---|
| `p_run_id IS NULL` or blank after trim | Raise invalid-parameter error |
| `p_kind IS NULL` or not in the allowed set | Raise through validation/table check |
| `p_payload IS NULL` as SQL NULL | Raise not-null/invalid-parameter error |
| JSONB scalar, object, array, or JSON `null` payload | Accept |
| `p_step_name IS NULL` for non-`llm`/`tool` | Accept |
| `p_step_name` malformed | Raise through the step-name check |
| `p_step_name IS NULL` for `llm`/`tool` | Raise through the step-name check |
| duplicate `(run_id, step_name)` for `llm` | Raise unique-constraint error |

The function does not derive `step_name` from `payload`. The envelope column is canonical. P05 may duplicate the value inside payload for model-facing data, but the two values must be kept equal by the caller.

### Mutation and transaction behavior

The function inserts exactly one row and returns its sequence. It never commits. The caller’s transaction determines visibility and durability.

- Successful insert followed by caller rollback: no visible row; the sequence value remains consumed.
- Successful insert followed by caller commit: row is visible to later projections.
- Insert failure: no row is inserted.
- The function does not inspect `cordis.jobs` and does not fence ownership.

`emit_step` is therefore suitable for:

- P01 transitions that have already performed their own jobs-row fence;
- P02-only tests;
- future trusted append wrappers.

It is not the correct entry point for a worker that has not already established claim ownership once P01 is present.

---

## Component 4 — Claim-aware append and checkpoint functions

### Common fencing policy

When `pg_catalog.to_regclass('cordis.jobs')` is non-NULL, the helper uses the P01 jobs contract. The mutating update must contain the ownership predicate itself:

```text
claim_token = p_claim_token
AND status = 'RUNNING'
AND claim_expires_at > captured wall-clock time
```

No preliminary ownership `SELECT` is allowed.

Empty-array `checkpoint` (heartbeat-like) updates by token alone. That is well-defined only if a non-null token identifies at most one row: P01’s `jobs_claim_token_key UNIQUE (claim_token)`. Synthetic jobs tables in P02 tests must include the same unique. Interval math uses `make_interval(secs => p_extend_seconds)` or `p_extend_seconds * interval '1 second'`; do not add integer seconds to `timestamptz` directly.

**Validation vs lost-claim order (both functions):** parameter and shape errors **raise** and take priority over lost-claim. Null token, unknown token, expired token, non-`RUNNING`, and run mismatch on `emit_step_claimed` return `false` only after arguments are valid. A null token plus a malformed checkpoint array therefore **raises**, it does not return `false`.

**Lease vs P01 `renew_claim`:** P01 `renew_claim` sets `claim_expires_at = captured wall-clock + extend` and **must not** add the duration onto the old expiry (absolute reset; can shorten). P02 claim-aware helpers use `claim_expires_at = GREATEST(existing expiry, captured time + extend)` so a checkpoint does not shrink a longer live claim. These are intentionally different: `renew_claim` is the worker’s authority to reset the horizon; checkpoint’s extension is incidental and must not shorten. Worker authors must not treat the two as equivalent.

When `cordis.jobs` does not exist:

- P02 does not raise a missing-table error;
- no database ownership check is possible;
- a non-NULL token is treated as a compatibility token;
- the helper appends through `emit_step`;
- the function returns `true` if the append succeeds.

This unfenced mode exists only so P02 can be installed and tested independently of P01. It is not a production claim guarantee.

### `cordis.emit_step_claimed`

#### Interface

```text
cordis.emit_step_claimed(
    p_claim_token     uuid,
    p_run_id          text,
    p_kind            text,
    p_payload         jsonb,
    p_step_name       text DEFAULT NULL,
    p_extend_seconds  integer DEFAULT 90
) RETURNS boolean
```

Catalog identity:

```text
cordis.emit_step_claimed(uuid,text,text,jsonb,text,integer)
```

Execution contract:

- `LANGUAGE plpgsql`
- `VOLATILE`
- `SECURITY INVOKER`
- synchronous;
- `true` means the append occurred;
- `false` means the token was absent, unknown, expired, cleared, non-running, or associated with another run;
- invalid positive-duration and event arguments raise rather than return `false`.

#### Algorithm

1. Validate `p_extend_seconds > 0`.
2. Validate `p_run_id` is non-null and non-blank.
3. If `p_claim_token IS NULL`, return `false` without mutation.
4. Detect `cordis.jobs` using `to_regclass`.
5. If jobs is absent:
   - call `cordis.emit_step`;
   - return `true` if it succeeds.
6. If jobs is present:
   - capture one `clock_timestamp()` value;
   - update the jobs row with:
     - supplied token;
     - `run_id = p_run_id`;
     - `status = 'RUNNING'`;
     - `claim_expires_at > captured time`;
   - extend the lease to at least `captured time + p_extend_seconds`;
   - if zero rows are updated, return `false`;
   - call `cordis.emit_step`;
   - return `true`.

The lease update must not shorten a longer live lease. The implementation uses the later of the existing expiry and the requested heartbeat horizon.

The jobs update and log insert occur in the caller’s transaction. If the log insert fails, the lease update rolls back with it.

#### Ordering behavior

A stale reaper and `emit_step_claimed` race on the same row are resolved by the row lock:

- if the append helper updates first, the lease is extended and the stale reaper later sees a live claim;
- if the stale reaper updates first, the helper’s live-token predicate matches zero rows and returns `false`;
- no log event is appended by the losing caller.

### `cordis.checkpoint`

#### Interface

```text
cordis.checkpoint(
    p_claim_token     uuid,
    p_events          jsonb,
    p_extend_seconds  integer DEFAULT 90
) RETURNS boolean
```

Catalog identity:

```text
cordis.checkpoint(uuid,jsonb,integer)
```

Execution contract:

- `LANGUAGE plpgsql`
- `VOLATILE`
- `SECURITY INVOKER`
- synchronous;
- appends a batch atomically;
- returns `true` only when the batch is accepted;
- returns `false` for a missing or lost live claim when `cordis.jobs` exists;
- raises for malformed event input or invalid duration.

#### Event-array shape

Because P02 must also operate when `cordis.jobs` is absent, each event item carries its own `run_id`. The required logical shape is:

```text
[
  {
    "run_id": "...",
    "kind": "...",
    "payload": ...,
    "step_name": "s-1" | null
  },
  ...
]
```

The event array rules are:

- `p_events` must be a JSONB array;
- each element must be a JSONB object;
- each element must contain a non-empty `run_id`;
- each element must contain `kind`;
- each element must contain `payload`, including JSONB `null` when intentional;
- `step_name` is optional unless the table’s kind constraint requires it;
- every event in a batch must use the same `run_id`.

This redundant `run_id` is required because a token cannot resolve to a run without `cordis.jobs`. When P01 is present, the function additionally requires every event’s `run_id` to equal the run ID returned by the fenced jobs update.

#### Algorithm

Parameter and shape errors raise **before** any lost-claim `false` and **before** any jobs `UPDATE`.

1. Validate that `p_extend_seconds > 0` (raise).
2. Validate that `p_events` is a JSONB array (raise).
3. If the array is non-empty, validate object shape, required fields, and a single common `run_id` (raise on mixed or missing `run_id`).
4. If `p_claim_token IS NULL`, return `false` without appending (token is a lost-claim signal, not a shape error).
5. Detect `cordis.jobs`.
6. If jobs exists:
   - capture one wall-clock time;
   - `UPDATE … SET claim_expires_at = GREATEST(claim_expires_at, captured + make_interval(secs => p_extend_seconds)) WHERE claim_token = p_claim_token AND status = 'RUNNING' AND claim_expires_at > captured` `RETURNING run_id`;
   - if zero rows, return `false` (no append);
   - if the array is non-empty and the common event `run_id` ≠ returned `run_id`, **raise** invalid-parameter. This is the same class as mixed `run_id`. It is **not** `false`. The raise aborts the statement so the lease `UPDATE` does not commit.
7. If jobs is absent:
   - use the event-array `run_id` (empty array appends nothing and returns `true`);
   - do not perform a jobs update.
8. For each event in array order, call `cordis.emit_step`.
9. Return `true`.

An empty event array is a valid heartbeat-like checkpoint:

- with jobs, it must fence and extend the live lease;
- without jobs, a non-NULL token returns `true`;
- it appends no rows.

The function must not contain a direct insert into `cordis.agent_steps`; all inserts go through `emit_step`.

#### Atomicity

The jobs update and all event inserts are one caller transaction:

- any invalid event, kind check failure, duplicate LLM step, or insert error aborts the whole statement;
- no earlier event in the batch remains committed;
- the lease extension rolls back with the failed batch;
- a caller rollback removes the events and lease extension together.

P02 does not add an independent checkpoint table or checkpoint cache.

---

## Component 5 — Step-name and checkpoint projections

### `cordis.next_step_name`

#### Interface

```text
cordis.next_step_name(
    p_run_id text
) RETURNS text
```

Catalog identity:

```text
cordis.next_step_name(text)
```

Execution contract:

- `LANGUAGE plpgsql`
- `STABLE`
- `SECURITY INVOKER`
- read-only;
- returns a single `s-N` string;
- raises for null or blank `p_run_id`.

#### Algorithm

The nominal rule is:

```text
s-(1 + number of completed LLM-bearing steps)
```

A crash-shaped trailing LLM needs a resume override. Normative definitions:

- **Later** means the same `run_id`, a strictly higher `seq`, and the same `step_name`.
- An `llm` row is **completed** iff there exists a later `tool` or `final` row with that same `step_name`.
- A `final` or `error` row with `step_name IS NULL` does **not** complete any `llm` row.

Algorithm:

1. Find the latest committed `llm` row for the run by descending `seq`.
2. If no LLM row exists, return `s-1`.
3. If that latest LLM row is not completed, return its `step_name` (crash-shaped resume; mid-flow confirmed).
4. Otherwise return `'s-' || (1 + greatest existing LLM s-N suffix)::text` (numeric, not 32-bit integer).

On **protocol-shaped** histories (contiguous `s-1…s-N`, every `llm` paired with same-name `tool` or `final` before the next `llm`) step 4 equals `'s-' || (1 + COUNT(kind = 'llm'))`. That equality is a note, not the definition. Unfenced `emit_step` can write non-protocol histories (for example only `llm(s-5)` + `tool(s-5)`); the function then returns `s-6`, not `s-2`. The partial unique index prevents duplicate `llm` names; it does not densify names.

```text
llm(s-1), no later same-name tool/final → s-1
llm(s-1), later tool(s-1)               → s-2
llm(s-1), later final(s-1)              → s-2
llm(s-1), later final with NULL name    → s-1  (NULL final does not complete)
```

An `error` event does not complete an `llm` step. Calling `next_step_name` after `run_state` is `final` is not a continuation API; the function still returns the value from the rules above (after `llm+tool+final(s-3)` that is `s-4`). Tests assert that concrete value rather than leaving it blank.

A run already projected as `error` must not normally call this function for continuation; retaining an incomplete name preserves the retry contract if a later retry policy uses it.

The function reads only committed log rows visible in its transaction snapshot. It does not inspect `jobs.attempt`, worker identity, or sequence gaps.

### `cordis.llm_checkpoint`

#### Interface

```text
cordis.llm_checkpoint(
    p_run_id     text,
    p_step_name  text
) RETURNS SETOF cordis.agent_steps
```

Catalog identity:

```text
cordis.llm_checkpoint(text,text)
```

Execution contract:

- `LANGUAGE plpgsql`
- `STABLE`
- `SECURITY INVOKER`
- returns zero rows for a miss;
- returns one full `agent_steps` row for a hit;
- raises for null/blank run ID or malformed step name.

The partial unique index guarantees at most one `llm` row for a `(run_id, step_name)` pair. The query must still specify deterministic ordering by `seq` for defensive behavior against an incompatible pre-existing table.

This function is the entire P02 skip-if-present surface:

- hit: P05 can reuse the stored provider result and skip HTTP;
- miss: P05 may call the provider;
- fingerprint comparison and provider idempotency headers are P05 responsibilities;
- P02 does not interpret `payload->>'fingerprint'`, provider keys, raw model output, or tool state.

---

## Component 6 — `cordis.run_state`

### Interface

```text
cordis.run_state(
    p_run_id text
) RETURNS TABLE (
    status     text,
    steps_used integer,
    answer     text,
    error      text
)
```

Catalog identity:

```text
cordis.run_state(text)
```

Execution contract:

- `LANGUAGE plpgsql`
- `STABLE`
- `SECURITY INVOKER`
- read-only;
- raises for null or blank run ID;
- returns exactly one projection row, including for an empty log.

### Fold algorithm

For the requested `run_id`:

1. Count all `llm` rows as `steps_used`.
2. Determine status by precedence:
   - if any `final` row exists: `final`;
   - else if any `error` row exists: `error`;
   - else: `in-progress`.
3. Select the latest `final` row by descending `seq`.
4. Set `answer` to that row’s `payload->>'answer'`, or `NULL` when absent.
5. Select the latest `error` row by descending `seq`.
6. Set `error` to `payload->>'message'` when present; otherwise use the serialized JSON payload so structured failure information remains observable.
7. Return one row.

The status precedence intentionally lets a committed final event remain authoritative over a later diagnostic error event. The raw event history remains available for forensic inspection.

An empty run returns:

```text
status     = in-progress
steps_used = 0
answer     = NULL
error      = NULL
```

`run_state` does not write a status column and does not mutate the log. It does not return `awaiting`; P03 owns that state after it introduces `run/await`.

---

## Component 7 — State and data flow

### Normal append

```text
producer
  → emit_step(run_id, kind, payload, optional step_name)
  → validate arguments and table constraints
  → allocate seq
  → insert one agent_steps row
  → return seq
  → caller commits
```

No callback, notification, LISTEN/NOTIFY, or published property is introduced.

### LLM checkpoint and tool continuation

```text
worker claims run outside P02
  → next_step_name(run_id)
  → llm_checkpoint(run_id, step_name)
      ├─ hit: P05 reuses stored LLM payload
      └─ miss: P05 performs provider call
  → emit_step_claimed(..., 'llm', ..., step_name)
  → execute tools in P05
  → emit_step_claimed(..., 'tool', ..., step_name)
  → yield through P01
```

If the worker crashes after the `llm` event but before the `tool` event:

```text
next_step_name(run_id) → same step_name
llm_checkpoint(run_id, same step_name) → hit
```

If the worker commits both `llm` and `tool`:

```text
next_step_name(run_id) → next s-N
```

P02 does not execute the LLM or tools and does not decide whether tool replay is safe.

### Checkpoint batch

```text
checkpoint(token, event_array)
  → optional jobs fence
  → lease extension
  → event-array validation
  → emit_step for each event
  → caller commits all events and lease extension together
```

If any event fails, the entire batch is rolled back. There is no partial batch visibility.

### P01 composition

When P01 is present today, complete/fail/stale mutate **jobs only**. The future stitch (later numbered file, not `0002`) is:

```text
P01 complete/fail/stale transition     -- current: jobs row only
  → emit_step(final/error/run-claim_timeout)   -- deferred
  → caller commits both jobs and log effects
```

P02 does not create or replace the P01 functions.

### Projection observation

Consumers observe P02 through ordinary SQL:

- `SELECT * FROM cordis.agent_steps WHERE run_id = ... ORDER BY seq`
- `SELECT * FROM cordis.next_step_name(...)`
- `SELECT * FROM cordis.llm_checkpoint(...)`
- `SELECT * FROM cordis.run_state(...)`

No materialized projection table or notification channel is added.

---

## Component 8 — Concurrency, lifecycle, and transaction boundaries

### Execution model

All P02 functions are synchronous PostgreSQL functions executing in the caller’s backend and transaction.

P02 creates:

- no background process;
- no timer;
- no worker;
- no asynchronous task;
- no connection pool;
- no session affinity.

A later host worker may call the same SQL functions over libpq.

### Claim-aware race behavior

With P01’s jobs table present:

- `emit_step_claimed` and `checkpoint` acquire the jobs-row lock through the fenced update.
- A stale reaper and append helper serialize on that row.
- The first successful update determines ownership.
- The losing operation returns `false` and appends nothing.
- A caller receiving `false` must stop claim-owned work and must not retry with the old token.

Without the jobs table:

- no ownership race can be detected;
- the helper behaves as an installation-compatible append wrapper;
- this mode must not be used as a production claim guarantee.

### Sequence lifecycle

`bigserial` sequence values are allocated independently of transaction commit:

- rollback leaves gaps;
- sequence values are not used to derive `s-N`;
- `seq` ordering remains sufficient for committed rows in ordinary single-writer claim usage;
- no contiguous-sequence assertion belongs in P02 tests.

### Multiple writers

P02 assumes one claim-owned writer per run once P01 exists. Direct unfenced `emit_step` calls can violate that assumption until P07 permission controls exist. The source-tree monopoly test documents and detects product violations but cannot prevent arbitrary SQL from a superuser.

---

## Component 9 — Error handling and edge cases

### Parameter errors that raise

The following are caller contract errors:

- null or blank `run_id` for writer/projection APIs;
- null or blank `step_name` where a step name is required;
- malformed `step_name`;
- non-positive `p_extend_seconds`;
- `p_events` not a JSONB array;
- event array item not a JSONB object;
- missing event `run_id`, `kind`, or `payload`;
- mixed `run_id` values within one checkpoint batch;
- any checkpoint event `run_id` ≠ the claimed jobs row’s `run_id` when `cordis.jobs` exists;
- SQL `NULL` payload;
- unknown event kind;
- duplicate LLM checkpoint for the same `(run_id, step_name)`.

These errors abort the current statement. If a caller has already started an explicit transaction, the caller must roll it back before issuing further commands.

### Lost ownership that returns `false`

The claim-aware functions return `false`, without appending, for:

- null token;
- unknown token;
- token belonging to another run;
- token on a non-`RUNNING` row;
- expired token;
- token cleared by yield, complete, fail, or stale-reap;
- jobs table present but no row satisfies the live-token predicate.

`false` is not a parameter-validation exception. The worker interprets it as `lost_claim`.

### Empty and missing histories

- `next_step_name` on a valid run with no events returns `s-1`.
- `llm_checkpoint` on a missing run or missing step returns zero rows.
- `run_state` on a missing run returns `in-progress`, zero steps, and null answer/error.
- P02 does not require a corresponding `agent_runs` row.

### Duplicate and out-of-order operations

| Situation | Required behavior |
|---|---|
| Duplicate `llm` event for same run/step | Unique-index error |
| Duplicate `tool` event | Allowed; P02 does not define tool idempotency |
| `llm` without `tool` | `next_step_name` returns the existing step name |
| `llm` followed by `tool` | Next step name advances |
| `final` followed by `error` | `run_state.status` remains `final`; raw error remains in log |
| Checkpoint batch with invalid later event | All earlier batch inserts and lease update roll back |
| Claimed append transaction rolls back | Jobs lease extension and log row both roll back |
| Projection query sees uncommitted append | It does not; normal PostgreSQL visibility applies |
| Sequence value lost after rollback | Accepted; no step-name impact |
| P03/P04 reserved kind inserted with valid payload | Accepted by kind check; no P02 transition is performed |
| Unknown kind inserted directly | Rejected by the table check |
| `cordis.jobs` appears after function creation | Next invocation detects it dynamically |
| `cordis.jobs` exists with incompatible columns | PostgreSQL execution error; P02 does not silently fall back |

### Degraded behavior

If P01 is not installed, P02 can still append and project history, but claim-aware APIs cannot provide ownership guarantees. Tests must expose this explicitly rather than treating the compatibility mode as fenced execution.

If a worker loses its claim after an external side effect, P02 cannot undo that side effect. P05/P16 own tool idempotency and recovery policy.

---

## Component 10 — Persistence and replay

### Fresh install

On a fresh P00 database:

1. `0000_kernel.sql` creates `cordis`.
2. `0002_p02_log.sql` creates `agent_steps`, its sequence, primary key, constraints, index, and functions.
3. The version function becomes `p02`.
4. No jobs, run registry, waits, events, or public objects are created.

If P01 is present, `0001` runs before `0002`; P02 does not require or alter P01’s table.

### In-place replay

Every P02 object must be replay-safe:

- table: `CREATE TABLE IF NOT EXISTS`;
- index: `CREATE [UNIQUE] INDEX IF NOT EXISTS`;
- functions: `CREATE OR REPLACE FUNCTION`;
- version function: `CREATE OR REPLACE FUNCTION`.

A second apply must:

- preserve all existing log rows;
- preserve `run_id`, `seq`, payload, and timestamps;
- preserve existing synthetic or public sentinel objects;
- leave the version at `p02`.

P02 must not drop or rebuild an existing table. If a pre-existing incompatible `cordis.agent_steps` exists, the apply may fail with PostgreSQL’s compatibility error; it must not silently destroy data.

### Rollback

The apply CLI wraps the entire source tree in one transaction:

- a P02 syntax or dependency error rolls back the table, sequence, indexes, functions, and version marker;
- the target database itself may remain because database creation happens before the tree transaction;
- a failed runtime append rolls back only the caller’s transaction.

### Downgrade

Applying an older source tree to a P02 database is unsupported. `--reset` on a disposable database is the supported way to test an older source tree. Deleting `0002_p02_log.sql` must not be treated as an uninstall or data migration.

---

## Component 11 — API compatibility

### New functions

| Function | Signature identity | Return | Volatility |
|---|---|---|---|
| `emit_step` | `cordis.emit_step(text,text,jsonb,text)` | `bigint` | `VOLATILE` |
| `emit_step_claimed` | `cordis.emit_step_claimed(uuid,text,text,jsonb,text,integer)` | `boolean` | `VOLATILE` |
| `checkpoint` | `cordis.checkpoint(uuid,jsonb,integer)` | `boolean` | `VOLATILE` |
| `next_step_name` | `cordis.next_step_name(text)` | `text` | `STABLE` |
| `llm_checkpoint` | `cordis.llm_checkpoint(text,text)` | `SETOF cordis.agent_steps` | `STABLE` |
| `run_state` | `cordis.run_state(text)` | table projection | `STABLE` |

Defaults permit the shorter common calls while preserving one catalog identity per function. No overloads or aliases are added.

### Modified existing function

Before P02:

```text
cordis.get_schema_version() RETURNS text → p00
```

After P02:

```text
cordis.get_schema_version() RETURNS text → p02
```

The schema, zero-argument signature, `text` return type, `IMMUTABLE`, and `SECURITY INVOKER` identity remain unchanged.

### Call-site impact

No existing production call sites exist in the P02 tree.

Future callers must use:

- `emit_step` for trusted already-fenced append;
- `emit_step_claimed` for one event under a token;
- `checkpoint` for batch events under a token;
- `next_step_name` and `llm_checkpoint` for P05 recovery;
- `run_state` for human/agent status projection.

No changes are made to pg-agent, scratch, pgembed, or the apply CLI.

---

# Work items

## W20 — Add `cordis.agent_steps` DDL

**File:** `sql/0002_p02_log.sql`

Add:

- `cordis.agent_steps`;
- `run_id`, `seq`, `kind`, `payload`, `step_name`, `created_at`;
- composite primary key `(run_id, seq)`;
- named CHECKs `agent_steps_run_id_check`, `agent_steps_kind_check`, `agent_steps_step_name_format_check`, `agent_steps_step_name_presence_check`;
- exact twelve-value kind list on `agent_steps_kind_check`;
- partial unique LLM step index;
- no foreign key to `agent_runs`;
- no checkpoint or queue tables.

**Done when:**

- a P02-only tree installs with no `cordis.jobs`;
- catalog shape matches the exact contract;
- `cordis.agent_steps` is the only user table created by P02;
- no `c_*`, `agent_runs`, `run_waits`, `run_events`, or public runtime tables appear.

## W21 — Add the unfenced writer

**File:** `sql/0002_p02_log.sql`

Add `cordis.emit_step` with the exact signature and return behavior. It must be the only direct insert path in product SQL.

**Done when:**

- one valid call returns the inserted `seq`;
- the row is visible after commit;
- invalid kinds, malformed step names, null payloads, and duplicate LLM step names fail;
- source-tree scan finds exactly one direct `INSERT INTO cordis.agent_steps`, inside `emit_step`.

## W22 — Add claim-aware append and checkpoint batching

**File:** `sql/0002_p02_log.sql`

Add:

- dynamic `to_regclass('cordis.jobs')` detection;
- `emit_step_claimed`;
- `checkpoint`;
- runtime fencing through the P01 jobs columns;
- compatibility behavior without jobs;
- lease extension with a positive default of 90 seconds;
- no direct inserts outside `emit_step`.

**Done when:**

- P02 applies without `cordis.jobs`;
- `emit_step_claimed` appends with a non-null token when jobs is absent;
- a synthetic jobs table causes live-token append success;
- expired, unknown, cleared, or mismatched tokens return `false`;
- checkpoint batches append atomically;
- invalid batch members roll back all events and lease extension;
- no lost-claim path appends.

## W23 — Add projections and lookup

**File:** `sql/0002_p02_log.sql`

Add:

- crash-aware `next_step_name`;
- indexed `llm_checkpoint`;
- F-shaped `run_state`;
- final/error precedence and empty-history behavior.

**Done when:**

- no history returns `s-1`;
- `llm` without `tool` resumes the same step;
- `llm` plus `tool` advances to the next step;
- `llm_checkpoint` produces a hit/miss result;
- three-step history yields the expected `run_state` transitions;
- projections do not create or mutate state.

## W24 — Retarget P00 source-tree tests

**Files:**

- `tests/test_p00_sql_source.py` (already P01-shaped)
- existing `tests/conftest.py` (do not re-extract)

Retarget incrementally from the P01 assertions already in the file:

- rename `test_fresh_apply_lists_current_tree_and_p01` → `..._and_p02`;
- file list `0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql`;
- version `'p02'`;
- `cordis.jobs` still present; `cordis.agent_steps` count 1; still no `run_waits`/`run_events`;
- `P01_FUNCTIONS` (or successor name) becomes this exact sorted `proname` list:

```text
cordis.checkpoint
cordis.claim_job
cordis.complete_claim
cordis.emit_step
cordis.emit_step_claimed
cordis.fail_claim
cordis.get_schema_version
cordis.llm_checkpoint
cordis.next_step_name
cordis.release_stale
cordis.renew_claim
cordis.run_state
cordis.yield_claim
```
- composition version `'p02'` and `cordis.agent_steps` in the cordis DB, still no `public.agent_steps`;
- keep `next_sql_prefix` fixtures, plpgsql `END;` probe, top-level transaction-control probe, and `FORBIDDEN_STMTS` import (already dollar-quote-aware, already allows `CREATE TABLE cordis.*`);
- add the monopoly scan (comment-strip only; **do not** strip dollar-quoted bodies). Locate the unique `INSERT INTO cordis.agent_steps` inside `emit_step`’s `$tag$` span.

`psql()` in `tests/conftest.py` keeps raising `RuntimeError` on non-zero exit. Failure cases use `pytest.raises(RuntimeError)`.

## W25 — Add P02 runtime protocol tests

**File:** `tests/test_p02_agent_steps.py`

The module must use the shared subprocess/psql/pgembed harness and apply a P02-only SQL tree for tests that need P01 absent. That tree is a temporary copy containing `0000_kernel.sql` and `0002_p02_log.sql`; it intentionally excludes `0001` if P01 has landed, so the no-jobs path remains tested independently.

Required tests:

1. Catalog shape and function identities.
2. Fresh apply and replay with existing log data.
3. Three-step history and `run_state`.
4. Crash-shaped step-name behavior.
5. LLM checkpoint hit/miss.
6. Unknown-kind rejection and reserved-kind acceptance.
7. Duplicate LLM step rejection.
8. No `c_*` table and no `agent_runs`.
9. No `public.agent_steps`.
10. Unfenced claimed append when jobs is absent.
11. Fenced claimed append with a synthetic jobs table (P02-only tree) and with real `cordis.jobs` (full tree).
12. Lost-token behavior.
13. Batch checkpoint success and rollback.
14. Product-source append monopoly.
15. Sequence gaps after rollback are tolerated and do not change step naming.

## W26 — Update README and version documentation

**Files:**

- `sql/README.md`
- `sql/0002_p02_log.sql`

Change the namespace/version section from wording that only says the P00-only tree returns `p00` to wording that distinguishes:

```text
0000-only tree                         → p00
tree through 0001_p01_claim.sql        → p01  (current product tree)
tree including 0002_p02_log.sql        → p02
```

Document that the latest numbered file wins. Add a short P02 scope note:

- `agent_steps` is the append-only history SoT;
- checkpoint is a log operation, not a `c_*` table;
- P02 does not create `agent_runs` or public objects;
- P01 is discovered by numeric order if present.

---

# File-by-file impact

## `sql/0002_p02_log.sql` — added

### Changes

Add:

- `cordis.agent_steps`;
- table constraints;
- `cordis.agent_steps_llm_step_idx`;
- `cordis.emit_step`;
- `cordis.emit_step_claimed`;
- `cordis.checkpoint`;
- `cordis.next_step_name`;
- `cordis.llm_checkpoint`;
- `cordis.run_state`;
- replacement `cordis.get_schema_version()` returning `p02`.

### Why

This is the complete P02 runtime surface. Keeping it in one numbered file preserves the loader’s append-only file model and makes the table/functions/version marker part of one apply transaction.

### Ordering constraints

- Table and index before functions returning or querying `cordis.agent_steps`.
- `emit_step` before helpers that call it.
- Version replacement last.
- No dependency on `cordis.jobs` at file parse or function-creation time.

## `sql/0000_kernel.sql` — unchanged

P02 must not edit the P00 historical file. The existing `p00` body remains the base marker for a `0000`-only source tree.

## `sql/README.md` — modified

### Changes

- Preserve the statement that a `0000`-only tree returns `p00`.
- Add the current P02 marker behavior: the tree containing `0002_p02_log.sql` returns `p02`.
- Document that `0002` is intentional even when `0001` is absent.
- Document `agent_steps` as log SoT and checkpoint-as-log.
- State that no `c_*` table or `agent_runs` table is created.
- Keep the existing no-public/no-extension/no-grant/no-transaction-control rules.

### Dependencies

The README wording must match the actual version replacement in `0002`. It does not affect execution.

## `tools/apply_pg_cordis.py` — unchanged

Discovery, dollar-quote-aware preflight, apply transaction, advisory lock, database-name validation, and `verify_bootstrap` stay unchanged. Do not edit this file in P02.

## `tests/test_p00_sql_source.py` — modified

### Fresh-install test

Rename the empty-kernel-focused test to a current-tree name, such as:

```text
test_fresh_apply_lists_current_tree_and_p02
```

Assert:

- output lists `0002_p02_log.sql`;
- output includes any already-landed `0001_p01_claim.sql`;
- version is `p02`;
- `cordis.agent_steps` exists;
- `public.agent_steps` does not exist;
- `cordis` does not contain P03/P04 tables;
- `pg_cordis` extension count is zero;
- `cordis.get_schema_version()` remains the expected zero-argument text function;
- public user-table isolation remains intact.

Do not assert that `cordis` contains zero tables or one function.

### Numbered-file extension test

Derive a prefix greater than every prefix in the copied tree. Add a temporary probe file under that prefix and assert:

- the probe is discovered;
- the probe runs;
- the product `sql/` tree remains unchanged.

### Later-table preflight test

Use the same dynamic-prefix helper and create a temporary `cordis` table. Keep the assertion that later `cordis` table DDL is allowed.

### Invalid-tree parametrization

Use dynamically unused valid prefixes for:

- duplicate-prefix cases;
- nested-file cases;
- psql meta-command cases;
- GRANT cases;
- database-DDL cases.

Keep all assertions that invalid source trees exit 2 before target database creation.

### Rollback test

Use a dynamically unused prefix above the product tree. Preserve the exact distinction:

- target database creation may remain;
- schema and objects created inside the failed tree transaction must not remain.

### Forbidden-token test

Keep `test_sql_tree_has_no_forbidden_tokens` as landed (`:355-369`): import `FORBIDDEN_STMTS`, dollar-quote strip, allow only `CREATE TABLE cordis.*`. `0002` must pass it. Do not revert to a blanket `CREATE TABLE` ban.

### Composition test

Expect:

```text
cordis target → cordis schema, p02 marker, cordis.agent_steps
da_agent      → public.jobs and pg-agent objects
```

Assert:

- `da_agent` does not contain `cordis`;
- the P02 database has no `public.agent_steps`;
- no pg-agent SQL is copied into the product SQL directory.

## `tests/conftest.py` — reused, not rewritten

Already present (`Shared P00/P01 pytest harness`). P02 imports `run_apply`, `psql`, `next_sql_prefix`, `SQL`, `pgdata`. `psql` raises `RuntimeError` on non-zero exit (`tests/conftest.py:41-56`). Do not re-extract. Do not import helpers from another test module.

## `tests/test_p02_agent_steps.py` — added

Add catalog, runtime, projection, fencing, replay, and source-monopoly tests described in W25.

The module must use:

- subprocess invocation of `tools/apply_pg_cordis.py`;
- bundled `psql`;
- disposable database names;
- serial test execution against the embedded server;
- a P02-only temporary source tree (`0000`+`0002`) for no-jobs behavior;
- a synthetic jobs table (`UNIQUE (claim_token)`) on that tree;
- the real `cordis.jobs` from `0001` on the full product tree for fenced append.

## `docs/plans/P02-agent-steps-log-2026-08-23.md` — rewritten by this task

This file becomes the implementation-ready plan. It is documentation only and is not loaded by the SQL apply command.

## Unchanged files

Do not modify:

- `pg-agent/v2/pg_agent_functional.sql`;
- `scratch/yield_walkthrough/*`;
- `sql/0000_kernel.sql`;
- `sql/0001_p01_claim.sql` (P02 does not edit it; optional emit stitch is a separate follow-on);
- `tools/apply_pg_cordis.py`;
- `deepseek-harness/packages/core/session/src/types.ts`;
- `absurd/sql/absurd.sql`;
- P01 jobs SQL, if it has landed.

---

# Risks and migration

## Number gap and combined version markers

`0002` may be applied without `0001`. This is supported by the loader and required for parallel P01/P02 development.

When both files exist:

```text
0001 → p01
0002 → p02
```

The later file’s marker is authoritative for the full source tree. A tree containing only P01 but not P02 reports `p01`; a tree containing P02 reports `p02`.

## No data migration

There is no existing product `cordis.agent_steps` table. The pg-agent `public.agent_steps` table is in another database and is not migrated.

P02 must not:

- copy pg-agent rows;
- add a migration from `public.agent_steps`;
- create an FK to pg-agent’s `agent_runs`;
- create a second history table.

## Replay and incompatible pre-existing tables

`CREATE TABLE IF NOT EXISTS` protects normal replay but does not reconcile an incompatible pre-existing table. If a user has manually created a conflicting `cordis.agent_steps`, PostgreSQL may reject the index or function definitions. P02 must report the failure rather than drop or rebuild the table.

## Dynamic jobs detection

Runtime `to_regclass` makes P02 independently installable but creates two execution modes:

- unfenced compatibility mode without `cordis.jobs`;
- fenced mode with P01’s expected table shape.

The unfenced mode is not security. It exists only to preserve the P01/P02 parallel landing order. Tests must assert the distinction so future code cannot mistake it for production ownership.

## P01 verb → log wiring gap

P01 is complete and jobs-only. `complete_claim` / `fail_claim` / `release_stale` will not emit until a **later numbered file** replaces those verbs. Until then jobs `DONE`/`ERROR` with `run_state() = in-progress` is expected. P02 tests do not go through P01 verbs. Do not treat jobs status as history. Do not patch `0001` from this item.

## Log retention unassigned

`agent_steps` is append-only with no prune, partition, or GDPR policy in P00–P19. Snapshot §10 still leaves log partitioning / pruning open. P02 does not add retention. Recorded here so a later item can own it; projections that scan a whole run remain acceptable at v0 scale.

## Permission boundary

Until P07:

- a superuser or sufficiently privileged role can insert directly into `cordis.agent_steps`;
- source-tree tests can detect product SQL violations but cannot prevent arbitrary SQL;
- no `REVOKE` or role DDL may be added to P02.

## Sequence gaps

`bigserial` values are consumed even on rollback and may be allocated before transaction commit. This is accepted. Step names and checkpoint identity use `step_name`, not contiguous `seq` values.

## Future envelope expansion

DSH fields such as `ignorable`, `sourceEventSeqs`, and `surfaceOp` are intentionally absent. Future plans may add columns or payload conventions, but must preserve:

- append-only history;
- projection non-authority;
- unknown-event policy;
- compatibility with existing P02 rows.

## External side effects

P02 only writes PostgreSQL log rows. It does not guarantee exactly-once execution of LLM calls or tools. P05 owns provider idempotency and P16 owns non-transactional tool recovery.

## Rollback behavior

A failed P02 apply rolls back the full schema change. A failed runtime checkpoint rolls back the jobs lease extension and all log rows in that batch. The target database itself may remain after a failed apply because database creation is outside the tree transaction.

---

# Implementation order

1. Reserve `0002_p02_log.sql`. Do not alter `0000_kernel.sql` or `tools/apply_pg_cordis.py`. Confirm W19: existing plpgsql and top-level-`END;` tests still pass.
2. Add the `cordis.agent_steps` table with all columns, **named** CHECKs, composite primary key, and `CREATE UNIQUE INDEX IF NOT EXISTS agent_steps_llm_step_idx`.
3. Add `cordis.emit_step` (`LANGUAGE plpgsql`); smoke-apply on the current tree (`0000`+`0001`+`0002`); verify direct append, returned sequence, table constraints, and replay behavior.
4. Add `cordis.emit_step_claimed` with dynamic jobs detection, live-token predicate, lease extension, and no-jobs compatibility behavior.
5. Add `cordis.checkpoint` with the explicit event-array shape, batch validation, optional jobs fence, and calls through `emit_step`.
6. Add `next_step_name`, including the incomplete trailing-LLM resume override.
7. Add `llm_checkpoint` and verify the partial unique index is used for the named-step lookup.
8. Add `run_state` with F-shaped labels and empty-history behavior.
9. At the end of `0002_p02_log.sql`, replace `get_schema_version()` with the `p02` body.
10. Update `sql/README.md` to distinguish the `p00` P00-only tree from the `p02` current tree.
11. Retarget P00 source-tree tests:
    - current file list;
    - version;
    - expected `cordis.agent_steps`;
    - dynamic temporary prefixes;
    - allowed `cordis` table DDL;
    - preserved invalid-tree and rollback assertions.
12. Reuse `tests/conftest.py`; do not re-extract.
13. Add `tests/test_p02_agent_steps.py` against a P02-only temporary tree (`0000`+`0002`) for the no-jobs path.
14. Add fenced-append tests against the **real** `cordis.jobs` on the full tree, plus synthetic-jobs tests on the P02-only tree.
15. Incrementally retarget `tests/test_p00_sql_source.py` from P01 to P02 assertions.
16. Run `uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py -q` serially.
17. Land `0002`, README, P00 retargeting, and P02 tests together. Existing P01 assertions otherwise describe the wrong source tree.

---

# Verification

Pytest modules: `tests/test_p00_sql_source.py` (retargeted) and `tests/test_p02_agent_steps.py` (new). Command:

```bash
uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py -q
```

P02 protocol tests (exact names):

| Test | Covers |
|---|---|
| `test_p02_fresh_apply_catalog_and_version` | §1–2 fresh install + catalog |
| `test_p02_emit_step_and_replay` | §3 |
| `test_p02_three_step_history_and_run_state` | §4 |
| `test_p02_crash_shaped_next_step_name` | §5 |
| `test_p02_llm_checkpoint_hit_miss_duplicate` | §6 |
| `test_p02_kind_and_step_name_checks` | §7 |
| `test_p02_claimed_append_without_jobs` | §8 |
| `test_p02_claimed_append_with_synthetic_jobs` | §9 |
| `test_p02_checkpoint_batch_atomicity` | §10 |
| `test_p02_no_second_queue_or_public_log` | §11 |
| `test_p02_source_tree_append_monopoly` | §12 |
| `test_p02_sequence_gap_does_not_change_step_name` | §15 in W25 |

`psql()` on SQL failure raises `RuntimeError`. Constraint/kind failures use `pytest.raises(RuntimeError)`.

## 1. Fresh P02-only installation

Use a temporary SQL root containing only:

```text
0000_kernel.sql
0002_p02_log.sql
```

Apply with `--reset`.

Expected:

- exit code `0`;
- output lists both files in numeric order;
- version is `p02`;
- schema `cordis` exists;
- `cordis.agent_steps` exists;
- `cordis.jobs` does not exist;
- `cordis.agent_runs` does not exist;
- `cordis.run_waits` does not exist;
- `cordis.run_events` does not exist;
- no `public.agent_steps`;
- no `pg_cordis` extension;
- no `absurd` schema.

## 2. Catalog shape

Query `information_schema.columns` or `pg_attribute` and assert the exact columns in order:

```text
run_id      text                       NOT NULL
seq         bigint                     NOT NULL
kind        text                       NOT NULL
payload     jsonb                      NOT NULL
step_name   text                       NULLABLE
created_at  timestamp with time zone  NOT NULL
```

Assert:

- primary key columns are `(run_id, seq)`;
- `seq` has a `nextval(...)` default;
- `created_at` has a wall-clock default;
- named CHECKs exist: `agent_steps_run_id_check` (`btrim(run_id) <> ''`), `agent_steps_kind_check` (exact twelve-value `IN` list), `agent_steps_step_name_format_check` (`step_name IS NULL OR step_name ~ '^s-[1-9][0-9]*$'`), `agent_steps_step_name_presence_check` (`kind NOT IN ('llm','tool') OR step_name IS NOT NULL`);
- `run_id` rejects blank and whitespace-only values;
- `agent_steps_llm_step_idx` is unique and partial on `kind = 'llm'`;
- no `cordis` table with a name matching `c_%`;
- no `cordis.agent_runs`.

Assert exact function identities:

```text
cordis.emit_step(text,text,jsonb,text)
cordis.emit_step_claimed(uuid,text,text,jsonb,text,integer)
cordis.checkpoint(uuid,jsonb,integer)
cordis.next_step_name(text)
cordis.llm_checkpoint(text,text)
cordis.run_state(text)
```

Query `pg_proc` and assert:

- writer functions are `VOLATILE`;
- projection functions are `STABLE`;
- all are `SECURITY INVOKER`;
- no unintended overloads exist.

## 3. Basic append and replay

Insert a valid event through `cordis.emit_step`:

```text
run_id    = p02-run-basic
kind      = llm
step_name = s-1
payload   = JSON containing raw model data
```

Assert:

- the function returns a sequence;
- one row exists after commit;
- `run_id`, `kind`, `step_name`, and payload match;
- a second full-tree apply succeeds;
- the same sequence, payload, and timestamps remain;
- the version remains `p02`.

## 4. Three-step history projection

Append these events in order:

```text
llm    s-1
tool   s-1
llm    s-2
tool   s-2
llm    s-3
final  optional s-3
```

After each relevant prefix assert:

| Prefix | `run_state.status` | `steps_used` | `next_step_name` |
|---|---|---:|---|
| no rows | `in-progress` | 0 | `s-1` |
| first `llm` | `in-progress` | 1 | `s-1` |
| first `llm` + `tool` | `in-progress` | 1 | `s-2` |
| through second tool | `in-progress` | 2 | `s-3` |
| final appended | `final` | 3 | no continuation is required |

After `final` with `step_name = s-3`, `next_step_name` still returns `s-4` (continuation is not an API; the value is defined). Assert the final answer is extracted from the latest final payload.

Use a separate error history to assert:

- no final plus one error → `error`;
- error payload message is projected;
- final plus later error → status remains `final`.

## 5. Crash-shaped prefix

Create a run with only:

```text
llm s-1
```

Assert:

- `next_step_name(run_id) = 's-1'`;
- `llm_checkpoint(run_id, 's-1')` returns one row;
- `llm_checkpoint(run_id, 's-2')` returns zero rows.

Append `tool s-1`, then assert:

```text
next_step_name(run_id) = 's-2'
```

This proves P02 resumes the incomplete named step rather than skipping it.

## 6. Checkpoint hit/miss

Assert:

- before an LLM event, `llm_checkpoint` returns zero rows;
- after commit, it returns the complete log row;
- payload fields remain available to P05;
- a duplicate LLM event for the same `(run_id, step_name)` fails;
- a different run or step is independently addressable.

Do not test HTTP calls or fingerprint mismatch here; those belong to P05.

## 7. Kind and structural constraints

Assert that:

- all twelve permitted kinds insert successfully with valid required fields;
- `llm` and `tool` without `step_name` fail;
- malformed `step_name` fails;
- unknown kind fails;
- blank `run_id` fails;
- SQL `NULL` payload fails;
- JSONB `null` payload is accepted if supplied as a JSONB value;
- duplicate LLM step fails;
- reserved `run/await`, `run/sleep`, `run/wake`, `run/yield`, spawn, and event kinds do not create any wait/event/spawn tables.

## 8. Claim-aware append without `cordis.jobs`

On a P02-only database:

1. Confirm `to_regclass('cordis.jobs') IS NULL`.
2. Call `emit_step_claimed` with a random non-null UUID, valid run ID, `llm`, payload, and `s-1`.
3. Assert it returns `true`.
4. Assert exactly one log row was appended.
5. Call `checkpoint` with a valid event array and the random token.
6. Assert it returns `true` and appends all events.
7. Call with a null token and assert `false` with no new row.

This test documents compatibility mode and must not be interpreted as a production fencing proof.

## 9. Claim-aware append with a synthetic jobs table

**P02-only tree (no `0001`):** create a test-only `cordis.jobs` with at least:

```text
run_id text
claim_token uuid
status text
claim_expires_at timestamptz
UNIQUE (claim_token)
```

Insert a live `RUNNING` row with a future expiry and token.

**Full product tree (`0001` present):** do **not** INSERT a stub row. Landed `jobs_claim_fields_check` requires RUNNING to have `claimed_by` and a non-null expiry. Insert `PENDING` then:

```text
SELECT * FROM cordis.claim_job(run_id, worker_id, 90)
```

and use the returned `claim_token`.

Assert:

1. Matching token and run ID:
   - returns `true`;
   - appends exactly one event;
   - extends or preserves the lease horizon.
2. Random token:
   - returns `false`;
   - appends no event.
3. Mismatched run ID:
   - returns `false`;
   - appends no event.
4. Expired row:
   - returns `false`;
   - appends no event.
5. Non-`RUNNING` row:
   - returns `false`;
   - appends no event.
6. Null token:
   - returns `false`;
   - appends no event.

## 10. Checkpoint batch atomicity

With a live synthetic jobs row:

- submit two valid events;
- assert both append and the lease update is visible after commit;
- submit a batch whose second event has an unknown kind;
- assert the function fails;
- assert neither event from the failed batch exists;
- assert the lease extension from the failed batch did not commit;
- submit a batch whose event `run_id` ≠ the claimed job’s `run_id`;
- assert the call **raises** (not `false`);
- assert neither event exists;
- assert the lease was **not** extended (statement abort rolls back the UPDATE).

## 11. No second queue or public objects

Run catalog assertions:

```text
cordis.agent_steps exists
cordis.jobs absent in the P02-only database
cordis.agent_runs absent
cordis.run_waits absent
cordis.run_events absent
no cordis table whose name begins c_
public.agent_steps absent
public.jobs absent in the P02 target
```

The pg-agent composition test separately verifies that `da_agent.public.jobs` remains present and isolated.

## 12. Source-tree append monopoly

Read every product `sql/*.sql` file, remove SQL comments, and assert:

- exactly one direct `INSERT INTO cordis.agent_steps`;
- that occurrence is inside the `emit_step` definition;
- no direct `UPDATE cordis.agent_steps`;
- no direct `DELETE FROM cordis.agent_steps`;
- no unqualified `INSERT INTO agent_steps`;
- no `public.agent_steps`.

This test must not scan documentation files as product SQL. Strip `--` / `/* */` comments only. Do **not** strip `$tag$…$tag$` bodies: the unique `INSERT INTO cordis.agent_steps` lives inside `emit_step`’s dollar-quoted body. Identify that function by its `CREATE … FUNCTION cordis.emit_step` header plus closing `$tag$;`.

## 13. P00 source/apply validation

Run:

```bash
uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py -q
```

Expected preservation:

- invalid source trees exit `2`;
- invalid source trees do not create target databases;
- SQL failure exits `1`;
- failed source-tree apply leaves no committed `cordis` objects;
- in-place replay succeeds;
- public sentinels survive;
- dynamic probe prefixes are discovered;
- no forbidden scope is weakened.

## 14. Combined P01/P02 tree, when P01 is present

Apply the full product tree containing:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
```

Assert:

- version is `p02`;
- P01 jobs and P02 log coexist under `cordis`;
- `emit_step_claimed` detects the actual P01 jobs table without function replacement;
- a live P01 claim can append a P02 event;
- stale or cleared P01 tokens cannot append;
- P02 does not `CREATE OR REPLACE` P01 verbs. If P01 has already wired `to_regprocedure('cordis.emit_step(text,text,jsonb,text)')` into `complete_claim` / `fail_claim` / `release_stale`, a jobs transition plus log event commit atomically. If not, jobs `DONE`/`ERROR` with `run_state() = in-progress` is the documented gap, not a P02 test failure.

---

# Open questions

None remain for P02.

The scaffold’s eight questions are resolved as follows:

1. File number: `0002_p02_log.sql`.
2. Claim composition: runtime `to_regclass('cordis.jobs')` detection.
3. Envelope: five base fields plus nullable indexed `step_name`.
4. Kind vocabulary: twelve-value `CHECK`, no generalized validator.
5. Run identity: no `cordis.agent_runs`; `run_id text NOT NULL`.
6. Projection labels: `final`, `error`, `in-progress`.
7. Version marker: `p02` at the end of `0002`.
8. Sequence: `bigserial`, with rollback gaps accepted.

Mid-flow (2026-08-23) confirmed the draft on: crash-shaped resume, `s-N` CHECK, `run_id` on every checkpoint event, `final` beats a later `error`.

Critique folded, then aligned to **landed P01**: `0001` is frozen jobs-only ABI (no emit stitch inside it); plpgsql packaging copies `SET search_path TO pg_catalog` + `pg_catalog.*` builtins; full-tree fence tests use `claim_job`; W19 cites `sanitize_sql_for_preflight`; P00 `P01_FUNCTIONS` list is extended in place; `test_p01_claim.py` stays green.

The remaining P03–P05 concerns are intentionally outside this plan:

- wait/event table design;
- sleep/retry state machine;
- HTTP idempotency headers;
- fingerprint mismatch behavior;
- one-step driver;
- workspace state;
- permission grants;
- model-backed projections;
- DSH envelope expansion.

---

# References

- `docs/plans/2026-08-23-pg-cordis-development.md:118-126` — P02 parent contract
- `docs/plans/P00-sql-source-2026-08-23.md` — numbered SQL tree, apply semantics, test conventions
- `docs/plans/P01-jobs-claim-2026-08-23.md` — parallel jobs claim contract and deferred log effects
- `docs/decisions/2026-08-23-pending.md:31-49` — signed SoT, queue, checkpoint, and dual-worker decisions
- `docs/analysis/2026-08-23-i-architecture-snapshot.md:61-70` — log/projection/workspace layering and signed contracts
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:40-44` — run identity and log role
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:71-86` — step naming and fencing
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:91-106` — claim/checkpoint/yield protocol
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:112-137` — step lookup and HTTP skip contract
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:214-223` — stale claims
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:262-272` — scheduler state machine
- `docs/analysis/2026-08-23-g-rlm-one-step-driver.md:72-153` — research analog for claimed append and LLM checkpoint lookup
- `docs/analysis/2026-08-23-g-rlm-one-step-driver.md:1-3` — explicit non-ABI warning
- `docs/analysis/2026-08-23-b-log-and-projection-contract.md` — TB1 envelope, TB2 event durability, TB3 invariant layering, and projection contract
- `docs/analysis/2026-08-23-e-absurd-durable-execution.md` — `c_*` checkpoint-table anti-pattern and lease/checkpoint semantics
- `sql/0000_kernel.sql` — implemented P00 namespace and version function
- `sql/README.md` — filename, replay, namespace, and forbidden-scope contract
- `tools/apply_pg_cordis.py:44-81` — SQL discovery and numeric ordering
- `tools/apply_pg_cordis.py:112-217` — `sanitize_sql_for_preflight` (plpgsql bodies + quoted literals)
- `tools/apply_pg_cordis.py:202-242` — transactional apply and bootstrap verification
- `tests/test_p00_sql_source.py` — source-tree, replay, rollback, and composition tests to retarget
- `docs/reviews/2026-08-23-p00-plan-critique.md` — precision requirements for deep plans
- `docs/reviews/2026-08-23-p02-plan-critique.md` — P02 completeness critique (loader, wiring, checkpoint mismatch, named CHECKs)
- `docs/reviews/2026-08-23-p00-implementation-oracle.md` — landed P00 preflight and verification behavior
- `scratch/yield_walkthrough/REPORT.md` — proof-only three-claim walkthrough
- `pg-agent/v2/pg_agent_functional.sql:55-68` — prior-art `agent_steps` shape
- `pg-agent/v2/pg_agent_functional.sql:290-294` — prior-art unfenced writer
- `pg-agent/v2/pg_agent_functional.sql:389-402` — prior-art state fold
- `absurd/sql/absurd.sql:210-285` — per-queue checkpoint-table morphology
- `deepseek-harness/packages/core/session/src/types.ts:339-440` — richer future event envelope fields


