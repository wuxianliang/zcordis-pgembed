# P10 — Host minimal SQL seam

Date: 2026-08-25
Status: **ready to implement**
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P10
Depends on: P05 and P06 (implemented); consumes P01–P03, P07, P08, and P19. P09 is implemented on the same tree (`f6b3d70`) and remains a sibling, not a wrapper. P04 is optional at runtime and is **not** an implementation dependency.
Parallel with: P09 (already on `main`)
Contract: D8; one `cordis.jobs` queue and one P01 claim protocol across in-database and host loci; durable behavior remains in SQL
Primary deliverables: `pg_cordis_host/__init__.py`, `pg_cordis_host/client.py`, `docs/host-sql-seam.md`, `tests/test_p10_host_sql_seam.py`
Critique: `docs/reviews/2026-08-25-p10-plan-critique.md` (P0 none; P1 findings 1–3 and P2 findings 4–9 folded below)
SQL marker: **none** — P10 adds no numbered SQL. The installed marker remains **`p21`** (`sql/0021_p09_in_db_worker.sql`). `tests/test_p00_sql_source.py:80-102` already pins that tree; P10 does not retarget it.
PL/pgSQL dollar tag: **not applicable** — P10 adds no SQL function
Plan export: `prompt-exports/oracle-plan-2026-08-25-211740-p10-host-sql-seam-de-be2e.md`

The context_builder export contains two concatenated drafts. This document is the orchestrator integration: **version 2** (export `# P10` at line 984) is the preservation baseline because it contains the complete W100–W108 verification, named tests, state/data flow, file-by-file impact, tradeoffs, and risks. Version 1 (export line 151) is the same design; unique v1 details folded below (full `ClaimedJob` row fields including `status`, explicit stdlib import list, `VERBOSITY=verbose`, secret-redaction of exceptions, and the no-`refresh_plugins`-public-method rationale).

**Mid-flow lock (2026-08-25, user):** keep the synchronous `psql` subprocess transport; add no numbered SQL; keep `authorize_host_tool` authorize-only with no host callable execution; put the client at repo-root `pg_cordis_host/`. These match decisions 2, 3, 11, and 7.

**Plan-critique fold (2026-08-25):** `docs/reviews/2026-08-25-p10-plan-critique.md` P1.1 pins the implementation baseline to committed P09 (`f6b3d70`, marker `p21`) and drops the pre-P09 branch. P1.2 corrects verb `file:line` refs against current SQL. P1.3 pins W105 fixtures: trusted `INSERT` into `cordis.jobs`; fold tests use paradigm `codeact`; env tests use paradigm `rlm`; the second fold slice is same-run without a `run` grant and expects `42501 P08_FOLD_RUN_GRANT_REQUIRED`; slice/grant setup uses P07 `create_slice` + `issue_grant`. P2 nits folded: JSON `to_jsonb` wrapping; drop host-clock `claim_expires_at` future check; v1 non-goal that the fixture does not prove external provider idempotency; `next_step_name` resume semantics; SIGINT unknown-outcome; live `run_state` vocabulary including `awaiting`; stub-executable error injection.

---

## Summary

P10 is a targeted host-side addition, not a kernel refactor. It ships a small, synchronous Python 3.12 client that invokes existing `cordis` SQL verbs through the repository’s proven `psql` transport: one subprocess and one committed database statement per method. The client exposes claim lifecycle, log/checkpoint, wait, optional sleep, P08 isolation gates, and P06 catalog operations without a second scheduler, host worker loop, HTTP transport, plugin execution, or private persistence. Provider idempotency is canonicalized by asking PostgreSQL for the same `md5(run_id || '/' || step_name)` value P05 already enforces. The acceptance proof is a real Python host process that targets one run, claims its `cordis.jobs` row, derives `s-1` and the provider key, appends one claim-fenced P08-scoped log event, yields, and lets a second client reclaim the same row. Because every durable verb already exists and P04 sleep is unshipped, P10 adds no numbered SQL, no schema marker, and no new dependency.

---

## Goal

Ship the first canonical host-process seam:

```text
trusted host process
    → create a host worker identity
    → claim one existing cordis.jobs row through cordis.claim_job
    → read next_step_name / llm_checkpoint
    → derive the canonical provider idempotency key
    → write one claim-fenced checkpoint or scoped event
    → yield / await / complete / fail through existing kernel verbs
    → discard the claim token after ownership ends
```

The primary acceptance path is:

```text
trusted test producer creates one PENDING jobs row and one authorized slice
    → CordisHostClient claims the targeted run
    → next_step_name(run) returns s-1
    → provider_idempotency_key(run, s-1) matches P05
    → emit_step_scoped appends one llm event under the live claim
    → fold_slice_messages for the same slice observes the event
    → yield_claim clears ownership and returns the row to PENDING
    → a second host client reclaims the same job_id with a different token
```

The completed proof must establish all of the following:

1. the host process uses P01 claim ownership rather than a private lock;
2. the host writes through P02/P08 claim-fenced append functions rather than inserting into `agent_steps`;
3. the host uses P08’s explicit `run_id + slice_id` gates;
4. the host derives the same provider key as P05, independent of worker identity, claim token, attempt, or request fingerprint;
5. ownership is released before another host process reclaims;
6. no host log, job state, descriptor cache, or plugin execution state is kept as a second source of truth.

P10 also exposes a read-only host-tool control surface:

```text
catalog lookup
    → authorize_host_tool(run, slice, identity, bindings)
    → authorize_tool_dispatch
    → require host + host_tool + NULL entrypoint
    → require read_only / replayable / none
    → return a fresh descriptor
    → do not execute any host callable
```

### Explicit non-goals

P10 does **not**:

- add, replace, wrap, or overload any `cordis` SQL function;
- add `sql/0022_*.sql`, advance `cordis.get_schema_version()`, or retarget current-tree marker pins;
- depend on `.p19-backup/p04-wip/0004_p04_sleep_retry.sql` or copy any P04 WIP SQL into the product tree;
- require P04 to be present before the host client can be imported or used for non-sleep operations;
- call `cordis.worker_step`; that function owns in-database queue dispatch and does not return the live claim token;
- call or expose `cordis.enqueue_job`, `cordis.invoke_in_db_tool`, or `cordis._resolve_in_db_queue_handler`;
- use `cordis.step_once` as the host entrypoint;
- call P05’s `invoke_llm` as if it were host HTTP;
- implement an autonomous worker loop, queue poller daemon, handler registry, action parser, or outcome state machine;
- execute more than one agent step automatically;
- perform HTTP, LLM provider calls, retries, streaming, or provider-specific request construction;
- define a host request-fingerprint format beyond P05’s already locked provider-key rule;
- execute host plugins, even read-only ones; P10 only registers, looks up, and authorizes their descriptors;
- implement file reads, workspace access, Git worktrees, `apply_edits`, or any other host filesystem effect;
- implement D2 `tool/call` / `tool/result` recovery or claim that host effects are exactly once;
- claim that the acceptance fixture proves external provider idempotency — it proves host derivation of the same `md5(run_id || '/' || step_name)` expression as P05, not HTTP replay;
- create a local callable registry that binds catalog identities to Python functions;
- add `psycopg`, `psycopg2`, `asyncpg`, an ORM, a connection pool, or another runtime dependency;
- change `pgembed.PostgresServer.psql()` or introduce a second server/apply script;
- make `tools/` importable or put the host client under `tools/`;
- publish an installable wheel or change `[tool.uv] package = false`;
- use `scratch/yield_walkthrough/` or pg-agent SQL as an ABI or implementation source;
- keep an in-memory log, cursor, active-run table, descriptor cache, or session-affine database state;
- add a background heartbeat thread or timer;
- make raw P01/P02/P03/P06/P07/P09 control-plane functions model tools;
- expose P03 `await_event` or `emit_event` to the model without a catalog row and P08 authorization;
- expose the legacy `kernel.step_once` catalog row as a host tool;
- prove alternating in-database and host ownership; P11 owns that acceptance test;
- prove successful sleep scheduling, retry, or stale-lease dead-letter behavior; P04 owns those semantics;
- prove host file mutation or recovery; P12, P14, and P16 own those paths;
- add RLS, roles, privileges, `CREATE EXTENSION`, UI, DSH event compatibility, a DSH manifest migrator, or dynamic `node:vm`.

---

## Execution index

P08 used W80–W88. P09 used W90–W99. P10 continues at W100.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W100 | Host package and safe `psql` transport | A repo-local Python package imports without packaging changes; each call runs one fixed SQL template through `psql`, accepts one JSON argument envelope, returns one JSON document, and exposes no generic SQL execution API | `pg_cordis_host/__init__.py`, `pg_cordis_host/client.py` | Python 3.12, existing PostgreSQL client binary | Medium |
| W101 | Claim and scheduler lifecycle verbs | The client supports targeted/global claim, renew, yield, complete, fail, and read-only job reconciliation using P01 signatures and exact boolean/token fencing | same | W100, P01 | Medium |
| W102 | Log, scoped append, fold state, and provider key | The client wraps checkpoint, P08 scoped append, next-step, LLM checkpoint, run state, and the database-derived P05 provider-key expression; no direct log insert or host HTTP path exists | same | W100–W101, P02, P05, P08 | Medium |
| W103 | Await and optional sleep | P03 await supports immediate and suspending results; `sleep_claim` is a typed, presence-checked call that fails locally without mutation when P04 is absent | same | W100–W102, P03; optional P04 | Medium |
| W104 | P06 catalog and P08 host authorization | Trusted callers can register/unregister/lookup host metadata; all four P08 gates have explicit client methods; host authorization accepts only `host + host_tool + read_only/replayable/none + NULL entrypoint` and never executes it | same | W100, P06–P08 | Medium |
| W105 | Canonical host one-step proof | One Python process claims, derives `s-1` and the provider key, appends one scoped event, sees it through the same slice fold, yields, and a second client reclaims the same job | `tests/test_p10_host_sql_seam.py` | W101–W104 | Large |
| W106 | Operational and security documentation | Documentation defines transaction boundaries, lease/heartbeat policy, lost-response reconciliation, sleep degradation, model-tool denylist, P09 separation, and no-execution catalog behavior | `docs/host-sql-seam.md` | W100–W105 | Medium |
| W107 | Exhaustive client and boundary tests | Named tests cover transport, validation, fencing, await, sleep absence, P08 live grants, catalog drift, control-plane refusal, special-character data, concurrency, and source boundaries | `tests/test_p10_host_sql_seam.py` | W100–W106 | Large |
| W108 | Regression and delivery gate | Focused P10, cross-protocol, and full suites pass; no SQL tree or dependency changes occur; Oracle review has no open P0/P1; only the P10 ship set is committed and pushed | tests, plan, review note | W100–W107 | Medium |

W100–W107 form one additive delivery. The Python package, its documentation, and its tests must land atomically because there is no useful or verified partial host seam.

---

## Background

### Skeleton, D8, and architecture snapshot

The parent skeleton (`docs/plans/2026-08-23-pg-cordis-development.md:227-235`) requires:

- a thin host wrapper around claim, checkpoint, yield, sleep, await, and catalog lookup;
- the same provider idempotency-key rule as the in-database path;
- no thick SDK, DSH event compatibility, or UI;
- completion when a host process can claim and write back one step log (tool surface may be read-only first);
- the first SDK language to be selected in P10.

D8 (`docs/decisions/2026-08-23-pending.md:412-452`) locks option A plus the minimal plugin catalog:

- both worker loci speak the same SQL verbs;
- host code reads the same plugin metadata vocabulary (identity, locus, required grants, effect/retry class);
- no TypeScript plugin runtime, DSH session-event compatibility (`turn/start`), manifest-to-SQL migrator, dynamic `node:vm`, or postponed host path;
- durable behavior remains in PostgreSQL;
- the Absurd Python SDK (<2000 LOC) is the thin-client existence proof; DBOS’s ~40K LOC SDK is the anti-pattern.

The architecture snapshot (`docs/analysis/2026-08-23-i-architecture-snapshot.md`) reinforces:

- §4 worker/D8 (`:88-108`): one `cordis.jobs` queue and one claim protocol; SDK/habitat is outside the kernel (D4);
- §7 v0 scope (`:166-181`): host minimal seam verb list;
- §9 (`:207-220`): thick SDK / DSH event layer / plugin migrator are explicit non-goals;
- §10 (`:234`): first SDK language was left open for this plan;
- T7 (`:117`): legal pairs in-db+queue, in-db+session_select, host+host_tool.

The F protocol (`docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md`) requires:

- §2 (`:38-65`): at most one non-terminal `jobs` row per `run_id`;
- §3 (`:68-97`): claim / heartbeat / checkpoint / yield / wait / sleep / complete / fail / release_stale;
- §4 (`:99-137`): provider key `H(run_id, step_name)` is not attempt and not fingerprint; log checkpoint before yield; skip HTTP if the named LLM row exists; tools are **not** covered;
- §9 (`:228-241`): host claims over libpq with the same verbs and the same provider key for its own HTTP; host must not keep a private in-memory log as SoT.

### Existing kernel verbs the client reuses

| Concern | Existing SQL identity | Current behavior | P10 use |
|---|---|---|---|
| Claim | `cordis.claim_job(text,text,integer)` `sql/0001_p01_claim.sql:117` | Reaps stale claims, then claims one eligible PENDING row using `FOR UPDATE SKIP LOCKED`; NULL run polls globally | Direct synchronous client method; returns the live token only to the claiming host |
| Renew | `cordis.renew_claim(uuid,integer)` `:172` | Extends a live claim; false if ownership is absent or expired | Explicit heartbeat method; no background heartbeat |
| Yield | `cordis.yield_claim(uuid)` `:198` | Returns RUNNING to PENDING and clears ownership | Explicit end-of-step transition |
| Complete | `cordis.complete_claim(uuid,jsonb)` `:225` | Sets DONE and clears ownership | Called only after a durable final event exists |
| Fail | `cordis.fail_claim(uuid,jsonb)` `:252` | Current P01 implementation sets ERROR; P04 may later revise retry behavior under the same identity | Client delegates and does not infer terminal versus retry behavior |
| Stale reap | `cordis.release_stale(text,integer)` `:64` | Inside `claim_job` | P10 does not call it itself |
| Job reconciliation | direct read of `cordis.jobs` | Scheduler truth and current ownership metadata | Read-only `get_job`; deliberately omits the live token |
| Checkpoint | `cordis.checkpoint(uuid,jsonb,integer)` `sql/0002_p02_log.sql:147` | Validates one event array, fences by the live claim, extends the lease, appends through `emit_step` | Generic trusted-worker batch append |
| Claimed append | `cordis.emit_step_claimed(...)` `:72` | Claim-fenced insert via the `emit_step` monopoly (`:40`) | Not a public host method; used by P08 scoped append |
| Scoped append | `cordis.emit_step_scoped(uuid,text,uuid,text,jsonb,text,text[],integer)` `sql/0020_p08_four_seam_enforcement.sql:145-153` | Validates the calling slice and live grants, attaches `p08_scope`, delegates to claimed append | Required for isolated user-facing history |
| Step naming | `cordis.next_step_name(text)` `sql/0002_p02_log.sql:279` | No llm row → `s-1`; latest llm without a later same-name tool/final → **same** step name (resume); otherwise `s-(max+1)` (`:307-331`) | Host obtains the next *or resumed* logical step name |
| LLM recovery read | `cordis.llm_checkpoint(text,text)` `:335` | Returns the committed LLM row for one step if present (`LIMIT 1` at `:361-362`) | Host checks before a future HTTP call |
| Run projection | `cordis.run_state(text)` live in `sql/0003_p03_wait_event.sql:472` (P02 introduced it) | Status vocabulary `final` / `error` / `awaiting` / `in-progress` (`:517-522`) | Lost-response and terminal-state reconciliation |
| Await | `cordis.await_event(...)` `sql/0003_p03_wait_event.sql:64` | Immediate return if already emitted, otherwise atomically logs/registers wait, sets WAITING, clears claim | Trusted host worker method; not automatically model-facing |
| Event emit | `cordis.emit_event(...)` `:307` | Unauthorized fan-out | **Not wrapped**; tests may use `psql` for fixture setup |
| Sleep | `cordis.sleep_claim(uuid,text,timestamptz,integer)` | Defined only by the unshipped P04 plan (`docs/plans/P04-sleep-retry-2026-08-24.md`) | Presence-checked optional method |
| Catalog registration | `register_host_plugin(jsonb)` `sql/0006_p06_plugin_catalog.sql:716` / `unregister_host_plugin(text)` `:742` | Persists host definitions and calls `refresh_plugins()` | Trusted control-plane methods; P10 does **not** expose `refresh_plugins()` because register/unregister already refresh |
| Catalog lookup | direct read of `cordis.plugin_catalog` | Compiled metadata; host rows have NULL SQL entrypoint (`plugin_catalog_source_entrypoint_check` at `:77-93`) | Trusted metadata inspection |
| Four-seam gates | recall/fold/env/`authorize_tool_dispatch` `sql/0020_p08_four_seam_enforcement.sql` | Slice-bound live grants; common P08 readiness latch | Direct client methods with explicit run and slice IDs |

P10 does not copy validation or state transitions from these functions. The database remains responsible for token fencing, row locks, event lock order, log append constraints, and catalog validation.

### Provider idempotency

P05 (`sql/0005_p05_one_step_driver.sql:37-39`, `:363`) enforces:

```text
provider_key = md5(run_id || '/' || step_name)
```

The key excludes `claim_token`, `worker_id`, `jobs.attempt`, request fingerprint, model name, tool list, and retry number. Tools are **not** covered (snapshot LLM 幂等 row; F §4).

P05’s `llm_checkpoint` and unique LLM step index provide the second half of A+B: a future host LLM caller must read the log before HTTP and must reuse the same provider key after reclaim.

P10 does not define a host LLM request or fingerprint ABI. Its provider method delegates the hash expression to PostgreSQL so encoding and concatenation match the database that enforces P05.

### Current P05 host stand-in

Before P10, `tests/test_p05_one_step_driver.py` acts as orchestration glue:

```text
Python test → claim_job → step_once   -- body still executes in PostgreSQL
           → Python CASE → yield_claim | complete_claim | fail_claim
```

That is not a host step. P10 replaces the ad hoc SQL-subprocess calls with a reusable client and proves that the Python process itself constructs and submits the checkpoint event.

`scratch/yield_walkthrough/run.py` is research only (psycopg2 against pg-agent v2). It is not ABI.

### P08 constraints on the host path

P08 plan (`docs/plans/P08-four-seam-enforcement-2026-08-24.md:179`, `:571-573`):

- pass explicit `run_id` and `slice_id`;
- use the four public gates rather than reading run-union grants;
- never expose issue-family or log-writer functions as model tools;
- reauthorize each host tool dispatch; do not cache descriptors across claims;
- P08 does not authenticate a host callable because host catalog rows have `entrypoint IS NULL`; **P10 remains responsible for host impersonation**.

Hard denylist in `authorize_tool_dispatch` (`sql/0020_p08_four_seam_enforcement.sql:598` body; identity denylist `:647-673`): `issue_grant`, `approve_grant`, `deny_grant`, `revoke_grant`, `create_slice`, `register_named_corpus`, `emit_step`, `emit_step_claimed`, `emit_step_scoped`, `checkpoint` (bare and `cordis.`-prefixed).

P10 closes impersonation only for its authorize-only scope:

1. call `authorize_tool_dispatch`;
2. require returned identity equals the requested identity;
3. require `locus='host'`, `invocation='host_tool'`, JSON null `entrypoint`;
4. limit this release to `read_only` / `replayable` / `none`;
5. return metadata; execute nothing.

Actual binding from identity to a local callable is deferred to P12/P14/P16.

### P09 sibling boundary

P09 (`docs/plans/P09-in-db-worker-2026-08-25.md`) is parallel, not a wrapper around P10. Non-goal `:71`: does not implement P10 host bindings. Defers to P10 (`:1048-1050`): host SQL seam and provider canonicalization.

P09:

- claims and executes cataloged in-database queue handlers;
- exposes `worker_step`, which never returns its claim token (decision 9);
- executes only compatible in-database entrypoints via `invoke_in_db_tool`;
- rejects host-locus rows;
- registers the legacy P05 body as `kernel.step_once`.

P10:

- calls P01 claim verbs directly and receives the live token;
- does not invoke `worker_step`, `enqueue_job`, `invoke_in_db_tool`, or `_resolve_in_db_queue_handler`;
- does not advertise `kernel.step_once` as a host or isolated tool;
- does not wrap P09 functions even though `0021` is in the baseline tree.

HEAD is P09 (`f6b3d70 Add pg_cordis P09 in-database worker.`). P10 is implemented on that mainline. The P10 commit must contain none of P09's already-shipped paths.

### Current host-side stack

- Python ≥3.12, uv, `[tool.uv] package = false` (`pyproject.toml:1-17`); runtime dep only local `pgembed`; dev dep pytest.
- All SQL today is `psql` CLI via subprocess (`tests/conftest.py:41-57` `psql`; `:78+` `PsqlSession`; `tools/apply_pg_cordis.py`).
- No psycopg/asyncpg. No installable package. No HTTP dependency. No host daemon.
- AGENTS.md: do not turn `tools/` into a package; do not write a second apply/boot script; do not change `pgembed.PostgresServer.psql()` just to pick a client library; tests use `run_apply` / `psql` / `psql_session`.
- Stand-in host already exists as tests: `tests/test_p01_claim.py` two-session claim/yield/reclaim.

### SQL-tree and coordination state

P10 adds no numbered SQL. The implementation baseline is the committed P09 tree:

- files through `0021_p09_in_db_worker.sql`;
- marker **`p21`** (`tests/test_p00_sql_source.py:80-102`);
- no P10-specific marker or `$p10$` tag;
- no current-tree pin changes.

If a later critique requires a P10 SQL object, that is a material design change: revise this plan, take the next prefix (`0022`), advance the marker to `p22`, and retarget pins before implementation.

---

## Current-state analysis

### Current ownership and mutation points

| State | Owner | Mutation path |
|---|---|---|
| Scheduler eligibility and lease | `cordis.jobs` | P01 claim/renew/yield/complete/fail; P03 await; optional P04 sleep |
| Historical run truth | `cordis.agent_steps` | P02 `emit_step` monopoly, reached through claimed/scoped/checkpoint helpers |
| Event wait registration | `cordis.run_waits` / `run_events` | P03 functions only |
| Slice grants | P07 tables | trusted issue/revoke verbs; read through P07/P08 gates |
| Plugin source | `host_plugin_definitions` or COMMENT | P06 registration/refresh |
| Compiled plugin projection | `plugin_catalog` | P06 `refresh_plugins()` |
| Host process identity | Python process memory | non-secret worker ID; not authoritative |
| Host claim capability | returned claim token | authoritative only while the jobs row retains it |
| Provider key | deterministic projection | recomputed from run and step; not separately persisted by P10 |

The token, not the worker ID, is authoritative:

- `worker_id` is observable ownership metadata (`claimed_by`);
- `claim_token` is the capability required for mutation;
- no client method may infer ownership from `claimed_by`;
- a false transition result means the token is no longer authoritative.

The host package owns no durable state. Its only long-lived object is immutable connection configuration and a non-secret worker ID.

### Blocking gaps

- There is no importable host client outside test helpers.
- Existing `tests.conftest.psql` helpers are test-only and accept arbitrary SQL strings; they are not an SDK surface.
- No typed host API returns the live claim token and then fences subsequent host mutations.
- No host API fixes the provider-key formula independently of attempt/fingerprint.
- No host API calls all four P08 gates with explicit slices.
- No host-side boundary distinguishes an authorized host descriptor from an executable local callable.
- No host API has a defined behavior when P04 sleep is absent.
- Existing P05 Python orchestration still delegates the actual step to `cordis.step_once`.

### Transformation boundaries

```text
Python values
  → local shape validation
  → one JSON argument envelope
  → one fixed SQL template
  → existing cordis function
  → one JSON response document
  → protocol validation
  → typed Python result
```

The database remains authoritative at every mutation boundary. Python validation improves error quality but does not replace SQL validation.

### Reuse instead of duplication

P10 reuses P01 lease checks and transitions; P02 event validation, append order, and step naming; P03 wait atomicity and event lock order; P05 provider-key formula and skip-if-present read; P06 metadata validation and compiled catalog; P07 live grants; P08 readiness latch and exact target authorization; the existing `psql` transport pattern; and the existing pgembed and pytest fixtures.

P10 does not duplicate claim SQL, jobs state-transition predicates, log append SQL, P03 wait registration, P04 sleep implementation, plugin metadata validation, grant parsing, P08 descriptor construction, P09 worker outcome mapping, or the apply command / server bootstrap.

---

## Design

### Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | **The first host language is Python 3.12.** | Python, uv, pgembed, and pytest are the only in-repo host toolchain (`pyproject.toml`); D8 cites a small Python SDK as the desired shape. | Add TypeScript/Rust/Go tooling; reuse DSH TypeScript; leave the language open. |
| 2 | **The transport is synchronous `psql` subprocess execution using only the Python standard library.** Each method launches one `psql`, executes one fixed statement, and exits. | Proven repository transport (`tests/conftest.py`, `tools/apply_pg_cordis.py`); no dependency or pgembed change; naturally commits each verb before the next host call. | Add psycopg/asyncpg; alter pgembed; support two transports; use shell commands or an ORM. |
| 3 | **P10 adds no numbered SQL.** Provider canonicalization is a Python client method that asks PostgreSQL to evaluate the exact P05 expression. | Durable verbs already exist; P08 already provides authorization; a new wrapper would duplicate rather than unify P05 unless P05 were also replaced. D4: SDK is not kernel. Avoids marker churn and P09 file-number coupling. | Add `0022` solely to wrap existing verbs; add a host-tool executor; replace P05 to call a new helper; implement Python-local MD5 as the sole authority. |
| 4 | **Sleep is a typed optional method with a fresh runtime presence check.** If the exact P04 signature is absent, raise `CordisFeatureUnavailable` before mutation. If present, call it directly. | P04 is ready as a plan but `0004` is not in `sql/`. Backup WIP is non-product. Presence checking lets P10 land independently and automatically consume P04 later. P08 set the precedent of refusing an unshipped P04 dependency. | Require P04 first; copy WIP SQL; silently emulate sleep with yield; omit sleep from the API; cache absence for the client lifetime. |
| 5 | **The deliverable is a verb client plus a pytest host-process proof, not a host loop.** | Skeleton completion bar is one claim and one log write; P11 owns alternating workers; later plans own real host tools. | Add `host_worker_step`, a polling daemon, action parsing, callback routing, or P09-like outcome mapping. |
| 6 | **The acceptance test performs no HTTP and does not call P05 `invoke_llm` as transport.** It creates a deterministic test event in Python, stores the database-derived provider key, and checkpoints it. | P05’s hook is an in-database mock, not host HTTP. A mock server would expand P10 beyond the required seam. | Treat `invoke_llm` as host HTTP; add an HTTP server/client; omit provider-key proof; reuse `step_once` and prove only in-db execution. |
| 7 | **The importable module lives in top-level package `pg_cordis_host`.** | Repo-root pytest can import it without package installation or `sys.path` changes; `tools/` remains non-package; no pyproject packaging change is needed. | Put code in `tools/`; use `src/` plus path manipulation; place production client in tests; publish a wheel now. |
| 8 | **P09 is a sibling boundary, not an API dependency.** P10 neither calls nor exposes P09 functions. The baseline tree already includes `0021` / `p21` (`f6b3d70`); P10’s commit still contains none of those shipped P09 paths. | Both loci share P01; P09 is specifically in-database dispatch and withholds its token. | Wrap `worker_step`; use `enqueue_job` as the host producer ABI; absorb P09 files into the P10 commit. |
| 9 | **Host worker IDs use `host:<service>:<instance-uuid-hex>`.** Service matches `[a-z][a-z0-9_-]{0,63}`; UUID is lowercase 32-character hex, stable for one client/process lifetime. | `claimed_by` is observational; the token is authoritative. The convention gives P11 distinct, legible locus identities without exposing hostname or PID. | Use only PID/backend PID; reuse one global `host`; place secrets in worker ID; treat worker ID as authority. |
| 10 | **Default lease remains 90 seconds; P10 adds no heartbeat thread.** Before a blocking external operation, callers must renew and ensure lease ≥ operation timeout + 30 seconds; for long work they renew at intervals no greater than `min(30 seconds, lease/3)`. A false renew means cancel/discard and append nothing. | P01 defaults to 90; F §8 requires heartbeat during LLM and warns against lease shorter than HTTP timeout. P10’s acceptance has no blocking HTTP. | Hidden background threads; infinite leases; renew after the result; append after a false heartbeat. |
| 11 | **The P10 tool surface is catalog lookup plus authorization only.** `authorize_host_tool` accepts only host, host-tool, read-only/replayable/none descriptors with NULL SQL entrypoint; it returns metadata and never invokes a callable. | Skeleton permits read-only first; P08 authorizes but does not execute; P12/P14/P16 own host effects and recovery. | Execute registered Python callables; allow external/idempotent tools; map SQL entrypoints to host functions. |
| 12 | **The client has no generic raw-SQL public method.** All dynamic values travel in one JSON envelope embedded as a safely delimited SQL data literal into fixed internal templates; `shell=False` is mandatory. | A generic query API would bypass P08 and make control-plane exposure trivial. Standard input avoids placing claim tokens or payloads in command arguments. | Public `execute(sql)`; string interpolation per scalar; `shell=True`; pass claim tokens through command-line variables. |
| 13 | **Each method is one independently committed statement.** `checkpoint` must commit before `yield`; a crash between them leaves a durable checkpoint and a RUNNING row that stale recovery can reclaim. | Matches the subprocess model and log-based recovery. Database functions already make their internal multi-row changes atomic. | Keep a psql backend pinned across the run; combine a whole host step into a private transaction manager; yield before checkpoint. |
| 14 | **Database denials propagate as typed host SQL errors; boolean fencing remains boolean.** False claim transitions are not rewritten into success or generic exceptions. The client has no descriptor, grant, fold, or claim cache. | Existing SQL distinguishes validation exceptions from lost-claim booleans. P08 forbids descriptor reuse across claims. | Catch all errors and return false; cache plugin rows or grants; reuse an authorization after revoke; issue unfenced fallback updates. |
| 15 | **Response loss is reconciled from database state, not by blind replay.** Mutating timeouts are unknown outcomes until `get_job` / `run_state` / `llm_checkpoint` is consulted. No automatic mutation retry. | A database commit can precede response loss. Repeating claim/checkpoint/await blindly can duplicate work or hit unique constraints. | Assume subprocess failure means rollback; recover a lost claim token from an unfenced cache; retry every mutation automatically. |

No implementation design fork remains. Mid-flow confirmed the four recommended options. Plan critique P0/P1 findings are folded; Status is `ready to implement`.

---

## Component 1 — Python package, transport, and error model

### Package layout

```text
pg_cordis_host/
  __init__.py
  client.py
```

`pg_cordis_host/__init__.py` re-exports only the documented public API. It contains no SQL templates, connection setup, or import-time I/O.

`pg_cordis_host/client.py` uses only the Python standard library:

- `dataclasses`, `datetime`, `json`, `pathlib`, `re`, `secrets`/`uuid`, `subprocess`, `typing`.

It must not import `pgembed`, `tests.conftest`, `tools.apply_pg_cordis`, psycopg/asyncpg, HTTP libraries, scratch, or plugin implementation modules.

### Public construction

```text
CordisHostClient(
    dsn: str,
    worker_id: str,
    *,
    psql_path: str | Path = "psql",
    command_timeout_seconds: float = 30.0
)
```

Properties:

- synchronous;
- no context manager;
- no persistent child process or socket;
- no connection pool;
- no mutable claim registry;
- configuration is immutable; concurrent method calls are safe because each call owns its subprocess;
- stores DSN, worker ID, binary path, and default command timeout only;
- `repr` must not include DSN, claim tokens, request JSON, or SQL text.

`dsn` must be nonblank. Production documentation recommends credential-free URI/conninfo plus libpq environment or `.pgpass`; a password embedded in a URI may be observable in the `psql` process arguments.

`new_host_worker_id(service, instance_id=None)` returns the convention from decision 9. Supplying `instance_id` exists for deterministic tests; production defaults to UUID4. `CordisHostClient` rejects worker IDs outside this convention.

### Public result types

All are frozen dataclasses. Parsed nested JSON is owned by the returned object and treated as read-only by the client.

| Type | Fields |
|---|---|
| `ClaimedJob` | full claimed P01 row: `job_id`, `run_id`, `job_type`, `payload`, `status`, `priority`, `attempt`, `available_at`, `claim_token`, `claimed_by`, `claim_expires_at`, `result`, `error`, `created_at`, `completed_at` |
| `JobSnapshot` | same observable scheduler fields **except** `claim_token`; includes `claim_present: bool` |
| `CheckpointEvent` | `run_id`, `kind`, `payload`, optional `step_name` |
| `AgentStep` | `run_id`, `seq`, `kind`, `payload`, optional `step_name`, `created_at` |
| `RunState` | `status` (`final` / `error` / `awaiting` / `in-progress` from live `cordis.run_state`, `sql/0003_p03_wait_event.sql:517-522`), `steps_used`, optional `answer`, optional `error` |
| `AwaitEventResult` | `accepted`, `should_suspend`, optional `payload`, optional `source_run_id`, optional `source_seq` |
| `NamedCorpusRef` | `grant_id`, `corpus_id`, `label` |
| `PluginCatalogEntry` | all P06 compiled fields, including `source_kind` and optional `entrypoint` |
| `AuthorizedHostTool` | normalized requested identity, bindings, effect/retry/reconciliation, required grants, lifecycle/config metadata, and the raw P08 descriptor; **no executable callable** |

Timestamps are timezone-aware `datetime`; UUIDs are `uuid.UUID`; JSON remains standard Python JSON values.

### Error hierarchy

| Type | Meaning |
|---|---|
| `CordisHostError` | Base class |
| `CordisInputError` | Local validation or JSON serialization failed before starting psql |
| `CordisCommandTimeout` | The psql child exceeded the configured command timeout |
| `CordisSqlError` | psql exited nonzero; includes parsed SQLSTATE when available and at most 4 KiB of server output |
| `CordisProtocolError` | A successful command returned missing, extra, malformed, or contract-incompatible JSON |
| `CordisFeatureUnavailable` | Optional exact SQL capability is not installed, currently P04 sleep only |

Boolean-fenced kernel methods return `False` for lost claim exactly as SQL does; they do not convert that normal protocol result into an exception. P08/P19 denial codes remain `CordisSqlError` with the server SQLSTATE.

Exceptions must not preserve DSN, the dynamic JSON argument document, the full SQL query, or claim tokens in a structured field.

### Transport algorithm

Every public method delegates to one private JSON command runner:

1. Validate Python scalar and collection shapes.
2. Serialize all dynamic inputs into one compact JSON document using UTF-8, `allow_nan=false`, and no lossy default serializer. Reject NUL and unsupported Python objects.
3. Reject an argument envelope larger than **8 MiB**. Larger host checkpoints require a later transport plan.
4. Generate a random dollar-quote delimiter not present in the serialized JSON.
5. Place that one JSON data literal into a method-specific **fixed** SQL template. No caller-provided SQL identifier, expression, function name, or clause is interpolated. Every template wraps the kernel result as JSON so stdout is one JSON document: `to_jsonb(...)` for scalars (`boolean`, `text`) and `row_to_json` / `jsonb_build_object` for rows. Bare `SELECT cordis.yield_claim(...)` would print `t` under `psql -t -A` and must not be used.
6. Run `psql` with `shell=False`:

   ```text
   psql <dsn> --no-psqlrc -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -q -t -A
   ```

7. Send the statement on standard input. Claim tokens and event payloads must not be command-line arguments.
8. Require exit code zero.
9. Require exactly one JSON response document on standard output after surrounding whitespace is removed.
10. Parse and validate the method-specific response shape.
11. Return the typed result.

The client exposes no `execute`, `query`, SQL-fragment, identifier, or arbitrary-function method. Notices on stderr with exit code zero do not invalidate a response.

A random dollar quote is an internal data encoding mechanism, not a caller-programmable SQL surface. Tests must include quotes, backslashes, newlines, Unicode, dollar tags, and SQL-looking strings.

---

## Component 2 — Claim and scheduler lifecycle

### Public methods

```text
claim_job(run_id: str | None, lease_seconds: int = 90) -> ClaimedJob | None
renew_claim(claim_token: UUID, extend_seconds: int = 90) -> bool
yield_claim(claim_token: UUID) -> bool
complete_claim(claim_token: UUID, result: JsonValue | None = None) -> bool
fail_claim(claim_token: UUID, reason: Mapping[str, JsonValue]) -> bool
get_job(run_id: str) -> JobSnapshot | None
```

`claim_job` supplies the client’s owned `worker_id` to P01.

### Claim behavior

`claim_job` delegates exactly once to `cordis.claim_job(run_id, worker_id, lease)`.

- No rows → `None`.
- More than one row → `CordisProtocolError`.
- One row must have `status='RUNNING'`, non-null claim token, `claimed_by` equal to the client’s worker ID, and the requested run ID when non-null. Do **not** compare `claim_expires_at` against the host clock: that timestamp is produced by database `clock_timestamp()` (`sql/0001_p01_claim.sql:145,162`), and a lagging host clock would false-positive `CordisProtocolError`. `status` + token + `claimed_by` already identify this client’s live claim; SQL fencing owns expiry.
- The token is returned only in `ClaimedJob`.

The client does not call `release_stale` itself because `claim_job` owns that behavior.

`run_id=None` intentionally preserves P01 queue polling, but P10 provides no handler router. Documentation must mark global polling as an advanced trusted-scheduler operation. The P10 proof and P11 targeted alternation use explicit run IDs.

### Transition behavior

Renew/yield/complete/fail return the existing SQL boolean unchanged:

- `true` means the database accepted the token-fenced mutation;
- `false` means the caller no longer owns a live matching claim;
- after false, the caller must stop using the token and append nothing;
- no fallback `UPDATE` or automatic reclaim occurs;
- no method uses `claimed_by` as a fencing key;
- no method retries a false transition.

`complete_claim` is valid only after the host has durably appended a `final` event. `fail_claim` is valid only after an `error` event or when the caller intentionally delegates a scheduler-level failure reason. P10 does not enforce event presence because P01 does not; real host drivers must follow this ordering. The P10 acceptance does not exercise scheduler-only fail.

P04 may later change `fail_claim` from always-terminal to retry-or-terminal under the same signature. The client must return only the boolean and instruct callers to inspect `get_job` instead of assuming ERROR.

### Reconciliation read

`get_job` uses a fixed read query and never returns `claim_token`. It exposes current scheduler status, whether a claim exists, `claimed_by` and expiry, attempt and availability, and terminal result/error.

If a claim response is lost, the caller cannot recover the token through this API. It waits for expiry/recovery rather than assuming ownership.

---

## Component 3 — Log, scoped append, and provider idempotency

### Public methods

```text
checkpoint(claim_token, events, extend_seconds=90) -> bool
emit_step_scoped(claim_token, run_id, slice_id, kind, payload, *,
                 step_name=None, corpus_ids=(), extend_seconds=90) -> bool
next_step_name(run_id) -> str
llm_checkpoint(run_id, step_name) -> AgentStep | None
run_state(run_id) -> RunState
provider_idempotency_key(run_id, step_name) -> str
```

### Generic checkpoint

`checkpoint` serializes `CheckpointEvent` records into P02’s existing array shape `{run_id, kind, payload, step_name?}`. It does not locally recreate P02’s kind or cross-run validation; the database remains authoritative. It does not call `emit_step` or `emit_step_claimed` directly.

An empty event list is legal because P02 treats it as a claim-fenced lease extension. Callers should normally use `renew_claim` for a heartbeat; P10 preserves the underlying checkpoint capability rather than forbidding it.

`checkpoint` is a trusted kernel method. It is not an isolated model append and must not be used to smuggle a caller-chosen `p08_scope`.

A false result means no events committed.

### Scoped append

User-facing isolated history must use `emit_step_scoped` (`sql/0020_p08_four_seam_enforcement.sql:145-153`):

1. pass explicit run and slice IDs;
2. pass only a JSON object payload;
3. pass exact named corpus IDs used to construct the observation;
4. let P08 validate `run` and named-corpus grants and attach immutable `p08_scope`;
5. return the claimed append boolean unchanged.

The client must reject a caller payload containing top-level `p08_scope` **before SQL** (the database also owns that field at `:197-200`). It must not create scope envelopes locally. It serializes corpus IDs as a JSON array, then invokes P08’s existing `text[]` parameter.

P10 does not provide a multi-event scoped batch because no such kernel function exists. Adding one belongs in a later numbered SQL plan if it becomes necessary.

The acceptance test uses `emit_step_scoped`, not raw checkpoint, so the P08 fold can observe the host event.

### Step and recovery reads

`next_step_name` requires a nonblank run ID and validates the returned `s-N` format. Resume semantics (`sql/0002_p02_log.sql:307-331`): no llm row → `s-1`; latest llm without a later same-name `tool`/`final` → return **that same** step name; otherwise `s-(max+1)`. The future host LLM ordering (next_step_name → llm_checkpoint → skip-if-present) depends on this resume behavior: after a crash, reclaim yields the same `s-N` so `llm_checkpoint` can hit the committed row and skip HTTP. "Next" is not monotonically increasing.

`llm_checkpoint` requires `s-N` and accepts zero or one row. More than one is a protocol error even though the P02 unique index should prevent it.

### Provider-key canonicalization

`provider_idempotency_key` validates nonblank run ID and `step_name` matching `^s-[1-9][0-9]*$`, then asks the connected PostgreSQL server to return:

```text
md5(run_id || '/' || step_name)
```

Contract:

- exactly 32 lowercase hexadecimal characters;
- deterministic for the same run/step;
- unchanged across worker IDs, claim tokens, attempts, or retries;
- no attempt/fingerprint parameters exist in the API.

Using PostgreSQL instead of Python’s local MD5 avoids encoding drift and locks the host behavior to P05’s database expression without adding a new kernel function.

The acceptance stores this key in the synthetic `llm` fixture payload. P10 does not define a production host request-fingerprint format.

### Future host LLM ordering

P10 does not implement HTTP, but downstream callers must follow this sequence:

```text
next_step_name(run)
    → llm_checkpoint(run, step)
        → if a matching committed checkpoint exists:
              reuse it; do not call HTTP
        → otherwise:
              provider_idempotency_key(run, step)
              renew claim before blocking call
              HTTP with Idempotency-Key   -- deferred
              emit scoped llm event
              execute tools under their own retry contract  -- deferred; not covered by provider key
              append tool result
              yield
```

P10 returns the checkpoint row but does not decide whether its request fingerprint matches; the real host driver must define that request protocol before HTTP ships.

### Checkpoint/yield crash window

P10 uses separate committed statements:

```text
checkpoint or emit_step_scoped commits
    → yield_claim commits
```

If the process crashes between them: history is durable; jobs remains RUNNING until lease recovery; the next claim uses `llm_checkpoint` / `next_step_name`; it does not repeat the committed named event blindly. Yield-before-checkpoint is invalid caller behavior.

---

## Component 4 — Await and optional sleep

### `await_event`

```text
await_event(claim_token, run_id, event_scope_id, event_name, await_id, *,
            deadline=None, ui_metadata={}, extend_seconds=90) -> AwaitEventResult
```

Requirements: deadline must be timezone-aware when present; metadata must be an object; scope/name must be nonblank. P03 remains authoritative for deeper validation and locking.

| Result | Host behavior |
|---|---|
| `accepted=false` | Token was not accepted; stop using it |
| `accepted=true`, `should_suspend=false` | Event already existed; payload/source are available and the claim remains live |
| `accepted=true`, `should_suspend=true` | P03 committed `run/await`, `run_waits`, WAITING, and claim release; stop immediately |
| malformed combinations | `CordisProtocolError` |
| SQL error | No local fallback transition; inspect transaction outcome if response was lost |

`await_event` is a trusted worker verb, not a model tool. A future model action requesting an event wait must first be routed through an authorized catalog descriptor carrying the concrete `event` binding.

P10 does not wrap `emit_event`. Tests may use it as trusted fixture setup through the shared `psql` helper.

### `sleep_claim`

```text
sleep_claim(claim_token, run_id, until, extend_seconds=90) -> bool
```

Algorithm:

1. Validate an aware, finite `until`, run ID, token, and positive extension.
2. Query `to_regprocedure` for the exact identity `cordis.sleep_claim(uuid,text,timestamptz,integer)`.
3. Do not cache the result.
4. If absent, raise `CordisFeatureUnavailable` with stable code `P10_SLEEP_UNAVAILABLE`; no scheduler or log mutation occurs.
5. If present, call it once and return its boolean unchanged.

This method must not query `.p19-backup`, emulate sleep by yielding, insert `run/sleep`, update jobs directly, or assume how P04 later claims due sleepers.

The P10 baseline test proves the absent path. P04’s implementation tests own successful scheduler semantics; once P04 ships, P10 requires only a small compatibility assertion that the exact method delegates successfully.

---

## Component 5 — P08 gates and P06 catalog

### Four-seam methods

```text
recall_named_corpus(run_id, slice_id, corpus_id) -> NamedCorpusRef | None
fold_slice_messages(run_id, slice_id, paradigm) -> Mapping[str, JsonValue]
read_run_env(run_id, slice_id, paradigm, key) -> JsonValue
authorize_host_tool(run_id, slice_id, identity, bindings) -> AuthorizedHostTool
```

All call the existing P08 public functions directly. No grant result is cached. No method queries `grants` directly, substitutes a run-union scope, infers a default slice, retries an authorization after revoke, or rewrites P08 errors.

Current behavior:

- unauthorized/unknown valid recall target → `None`;
- fold returns one JSON object after `paradigm_policy` lookup; P19 seeds only `codeact` and `rlm` (`sql/0019_p19_paradigm_policies.sql`);
- `read_run_env` is paradigm-dependent (`sql/0020_p08_four_seam_enforcement.sql:579-594`): `codeact` (`env_enabled=false`, `env_workspace='none'`) raises `42501 P08_ENV_DISABLED`; `rlm` (`env_enabled=true`, `env_workspace='run_vars'`) reaches `55000 P08_ENV_WORKSPACE_UNAVAILABLE` after the run-grant check. P10 env tests must use paradigm `rlm` to hit the workspace-unavailable code;
- tool authorization returns a descriptor but executes nothing.

`read_run_env` retains a future successful return type but currently propagates the P08 error for the chosen paradigm.

### Host authorization validation

After `authorize_tool_dispatch` returns, `authorize_host_tool` requires:

- descriptor JSON object;
- returned identity exactly equals the normalized requested identity;
- `locus='host'`;
- `invocation='host_tool'`;
- `entrypoint` is JSON null;
- `effect_class='read_only'`;
- `retry_class='replayable'`;
- `reconciliation='none'`;
- bindings equal the requested normalized binding object;
- required grants are a list of P06 enum values.

Failures after P08 authorization raise `CordisProtocolError`, not a database policy error.

The method returns metadata only. There is deliberately no callable argument, Python handler registry, module import path, dynamic import, `execute_host_tool`, callback invocation, or result checkpointing.

An in-db queue row such as `kernel.step_once`, an in-db `session_select` row, or a host external/transactional row is refused here even if P08 would authorize it as a catalog identity.

### Catalog methods

```text
register_host_plugin(definition: Mapping[str, JsonValue]) -> str
unregister_host_plugin(identity: str) -> bool
get_plugin(identity: str) -> PluginCatalogEntry | None
```

Registration and unregistration are trusted control-plane operations. They are never model-facing. `register_host_plugin` delegates all metadata validation and refresh behavior to P06 (`sql/0006_p06_plugin_catalog.sql:716-739` already calls `refresh_plugins()`). P10 therefore does **not** expose `refresh_plugins` as a public method.

`get_plugin` is a trusted raw catalog lookup and may return any locus/invocation. Model routing must use `authorize_host_tool`, not `get_plugin`.

### Explicit non-model-tool boundary

No `CordisHostClient` method is automatically rendered as a model tool. In particular, the following identities and method families must never be placed in a model action schema by P10:

- P01 claim, renew, yield, complete, fail, and stale-release verbs;
- P02 `emit_step`, `emit_step_claimed`, `emit_step_scoped`, and `checkpoint`;
- P06 register/unregister/refresh functions;
- P07 register/create/issue/approve/deny/revoke functions and `create_slice`;
- P08 readiness latch and internal fold helpers;
- P09 `enqueue_job`, `worker_step`, `invoke_in_db_tool`, and `_resolve_in_db_queue_handler`;
- P03 `emit_event` and `await_event` unless represented by a catalog operation and authorized for the exact event scope;
- P05 `step_once` / catalog identity `kernel.step_once`;
- P05 `invoke_llm`.

`request_grant` remains a future model-request surface under P07 policy, but P10 does not expose it.

---

## State and data flow

### Normal host checkpoint

```text
trusted producer
  → existing jobs row PENDING

host process A
  → CordisHostClient.claim_job(run_id, lease)
      → psql process / one transaction
      → claim_job(run, host:svc:a, lease)
      → jobs RUNNING + token
  → ClaimedJob(token)

  → next_step_name(run)                 -- read
  → llm_checkpoint(run, step)           -- read
  → provider_idempotency_key(run, step) -- PostgreSQL md5 expression
  → emit_step_scoped(token, run, slice, "llm", payload, step)
      → P08 latch + grants
      → emit_step_claimed
      → agent_steps append + lease extension
  → yield_claim(token)
      → jobs PENDING, token cleared

host process B
  → claim_job(same run)
      → same job_id, new token, claimed_by host:svc:b
```

Every arrow that invokes `psql` is a separate transaction and backend. No backend-local state is reused.

### Future host LLM flow

P10 supplies only the boxed SQL seam:

```text
claim
  → fold_slice_messages
  → next_step_name
  → llm_checkpoint
       ├─ exists → validate stored request fingerprint in future driver; skip HTTP
       └─ absent → provider_idempotency_key
                   → renew before external call
                   → host HTTP [deferred]
                   → emit_step_scoped(llm)
  → host tools [deferred]
  → checkpoint/scoped append
  → yield
```

Tools are not covered by the provider key. P16 owns their call/result recovery.

### Await

```text
live host claim
  → await_event(token, run, scope, name, await_id, deadline)
       ├─ event already emitted → payload returned; claim remains RUNNING
       ├─ not emitted → run/await + run_waits + jobs WAITING; token cleared; host stops
       └─ claim rejected → accepted=false; host stops
```

### Optional sleep

```text
host asks to sleep
  → exact signature presence check
       ├─ absent → CordisFeatureUnavailable; state unchanged
       └─ present → sleep_claim(...) → P04 owns log + SLEEPING + release
```

### Host tool authorization

```text
model decision interpreted by trusted future host driver
  → authorize_host_tool(run, slice, identity, bindings)
      → authorize_tool_dispatch
      → live exact grant checks
      → host/read-only/NULL-entrypoint validation
      → AuthorizedHostTool metadata
  → no execution in P10
```

### Concurrency and ordering

- P01 `SKIP LOCKED` and token uniqueness remain the only claim-exclusion mechanism.
- Two clients with different worker IDs may target the same run; only one receives a claim.
- Reusing a worker ID does not transfer ownership.
- Checkpoint must precede yield/complete/fail.
- A second identical LLM checkpoint may raise existing `23505`; callers read `llm_checkpoint` before appending.
- P08 authorization and fold are fresh calls; revoke affects the next statement.
- The client retains no descriptor or grant cache.
- A client may issue methods concurrently, but callers must serialize mutations for one claim token.
- The package does not enforce one active token per client because the database is authoritative.

### Cancellation and dropped responses

If psql times out or is killed before commit, PostgreSQL normally rolls the statement back when the connection closes. The client still treats every mutating timeout as **unknown outcome**, because the database may have committed just before the response was lost.

Host-side cancellation is the same class: `subprocess.run` does not kill the child on `KeyboardInterrupt`, and SIGINT/SIGKILL of the host process can leave an in-flight `psql` that still commits. Treat that as unknown outcome; do not automatically retry or issue a compensating transition on the interrupt path.

| Lost response | Required reconciliation |
|---|---|
| Claim | `get_job`; never assume ownership because the token may be unknown; wait for lease recovery |
| Renew | Inspect job expiry; if uncertain, stop external work |
| Checkpoint/scoped append | Read `llm_checkpoint`, fold, or agent log by known run/step before replay |
| Yield | `get_job`; PENDING means transition committed, RUNNING may still be the old claim |
| Complete/fail | `get_job` and `run_state` |
| Await | Inspect jobs status, `run_state`, and P03 side tables through trusted diagnostics |
| Register/unregister plugin | `get_plugin` and source definition state |

The client never retries mutating commands automatically. A client object deleted with a live token does not auto-yield; lease expiry/recovery owns cleanup.

---

## API and persistence impact

### New Python interfaces

Public inventory exported by `pg_cordis_host`:

- `CordisHostClient`, `new_host_worker_id`
- `ClaimedJob`, `JobSnapshot`, `CheckpointEvent`, `AgentStep`, `RunState`, `AwaitEventResult`, `NamedCorpusRef`, `PluginCatalogEntry`, `AuthorizedHostTool`
- `CordisHostError`, `CordisInputError`, `CordisCommandTimeout`, `CordisSqlError`, `CordisProtocolError`, `CordisFeatureUnavailable`

No public generic SQL runner, transaction object, HTTP client, worker loop, plugin callable registry, or raw descriptor executor is exported.

### Existing SQL interfaces

No SQL signature changes. P10 calls P01 claim lifecycle, P02 checkpoint/read state, P03 await, optional P04 sleep, P06 host registration and catalog table, and P08 scoped append plus four public gates as-is. No SQL COMMENT is added, so the P06 catalog gains no P10 entry.

### Existing Python call sites

There are no production call sites. New tests import the package directly. P11 is the first planned downstream consumer. Existing test helpers remain unchanged and continue to own server setup and SQL fixture preparation. The package itself does not import them.

### Persistence

P10 adds no schema, migration, table, column, index, function, type, COMMENT, or schema version. Calls through the client may mutate existing state (`jobs`, `agent_steps`, P03 tables, host plugin definitions). The client stores none of this outside PostgreSQL.

### Backward compatibility

The change is additive: existing SQL consumers, apply tree, marker, pyproject dependencies, package mode, and P09 behavior are unaffected. Deleting the Python package does not make an applied database unreadable. Existing jobs, log rows, waits, grants, and host definitions created through the client remain valid kernel data.

The initial Python API is internal to this repository and not yet a published compatibility promise. P11 and later plans must treat the documented signatures as the P10 handoff.

---

## Error handling and edge cases

| Operation | Condition | Behavior |
|---|---|---|
| Client construction | Blank DSN, invalid worker ID, missing/invalid timeout | `CordisInputError`; no process |
| Any call | JSON contains NaN/Infinity, unsupported object, NUL, or exceeds 8 MiB | `CordisInputError`; no process |
| Any call | psql binary missing | `CordisHostError` with stable unavailable message; no database assumption |
| Any call | command timeout | `CordisCommandTimeout`; mutation outcome treated as unknown |
| Any call | PostgreSQL error | `CordisSqlError`, preserving SQLSTATE when parseable |
| Any call | zero/multiple/malformed success documents | `CordisProtocolError` |
| Claim | Empty queue or target not eligible | `None` |
| Claim | Claimed row does not match worker/run or lacks token | `CordisProtocolError` |
| Global claim | Host lacks a router for returned `job_type` | Caller must yield/fail according to trusted policy; documentation discourages global polling |
| Renew/yield/complete/fail | Token expired, replaced, or wrong | Return `false`; stop |
| Get job | Missing run | `None` |
| Checkpoint | Empty list | Delegates as claim-fenced no-event checkpoint |
| Checkpoint | Events span runs or have invalid kind/step | Preserve P02 SQL error; no append |
| Scoped append | Payload contains `p08_scope` | Local input error before SQL |
| Scoped append | Missing run/corpus grant | Preserve P08 `42501` |
| Scoped append | Lost claim | Return `false` |
| Next step | Empty history | `s-1` |
| LLM checkpoint | No row | `None` |
| LLM checkpoint | Duplicate rows despite invariant | `CordisProtocolError` |
| Provider key | Invalid run/step | `CordisInputError`; no SQL |
| Provider key | Non-32-hex response | `CordisProtocolError` |
| Await | Event already emitted | Accepted, no suspend, payload/source returned |
| Await | Event absent | Accepted, suspend, token considered released |
| Await | Lost token | `accepted=false`; stop |
| Await | Malformed result combination | `CordisProtocolError` |
| Sleep | P04 signature absent | `CordisFeatureUnavailable(P10_SLEEP_UNAVAILABLE)`; state unchanged |
| Sleep | Signature appears after client creation | Next call sees it because presence is not cached |
| Recall | Unauthorized or valid unknown corpus | `None`, preserving P08 non-oracle behavior |
| Fold | Empty authorized history | Valid empty fold object |
| Env | paradigm `codeact` (env disabled) | Preserve `42501 P08_ENV_DISABLED` |
| Env | paradigm `rlm`, authorized, no workspace store | Preserve `55000 P08_ENV_WORKSPACE_UNAVAILABLE` |
| Tool authorize | P08 grant denial | Preserve P08 SQL error |
| Tool authorize | In-db, queue, external, transactional, or non-replayable descriptor | `CordisProtocolError`; no execution |
| Catalog lookup | Unknown identity | `None` |
| Register | Existing identity | P06 upsert/refresh semantics |
| Unregister | Missing identity | `false` |
| Descriptor/catalog change | Changed after one call | Next call rereads; no cache |
| Client object deleted with live token | No automatic yield; lease expiry/recovery owns cleanup |
| Explicit outer transaction needed | Unsupported by this client; use existing test-only `psql_session` or a future transport plan |

Boundary conditions: empty event arrays; JSON null payload members; strings containing quotes, backslashes, Unicode, newlines, dollar signs, or SQL-looking text; first claim, reclaimed claim, and stale attempt; `deadline=None`; empty corpus list for scoped events; revoked grant between two gate calls; plugin unregistered after lookup but before authorization; psql warnings with a valid JSON result; P04 installed while a client instance remains alive; current source tree ending at `p21`.

---

## File-by-file impact

| File | Change | Why | Ordering |
|---|---|---|---|
| `docs/plans/P10-host-sql-seam-2026-08-25.md` | Replace scaffold with this deep plan; after critique, fold findings and set `ready to implement` | AGENTS plan-before-code gate | First |
| `docs/reviews/2026-08-25-p10-plan-critique.md` | **Already created.** P0 none; P1/P2 folded into this plan | Required before ready status | Done |
| `pg_cordis_host/__init__.py` | **Create.** Reexport the exact public inventory; no behavior or import-time I/O | Stable import surface without packaging changes | With `client.py` |
| `pg_cordis_host/client.py` | **Create.** Types, errors, worker ID helper, safe psql transport, existing-verb wrappers, provider key, catalog and P08 methods | Primary P10 implementation | After critique |
| `docs/host-sql-seam.md` | **Create.** Operational usage, transaction/lease rules, optional sleep, error/reconciliation behavior, model-tool boundary, no-execution guarantee | The plan is implementation guidance; this is the runtime consumer contract | After API signatures settle |
| `tests/test_p10_host_sql_seam.py` | **Create.** Unit/integration tests using shared apply/psql fixtures and the real client package | Acceptance and regression proof | Atomic with package |
| `docs/reviews/2026-08-25-p10-implementation-oracle.md` | **Create during implementation gate.** Record Oracle exports, verdict, and P0/P1/P2 closure | AGENTS completion gate | After tests pass |
| `pyproject.toml` | **No change.** No dependency and no packaging-mode change | Python stdlib + psql is sufficient | Protected |
| `uv.lock` | **No change** | No dependency change | Protected |
| `tests/conftest.py` | **No change.** Reuse `run_apply`, `psql`, `psql_session`; tests pass embedded psql path into the client | No second harness | Protected |
| `tools/apply_pg_cordis.py` | **No change** | No new SQL or apply path | Protected |
| `tests/test_p00_sql_source.py` | **No change.** No file-list, function inventory, or marker update | P10 adds no SQL | Regression only |
| `tests/test_p01_claim.py` through `tests/test_p09_in_db_worker.py` | **No change** | P10 consumes existing contracts without changing them | Regression only |
| `sql/README.md` | **No change** | SQL tree and marker are unchanged; host runtime documentation lives in `docs/host-sql-seam.md` | Protected |
| `sql/0000_kernel.sql` through current highest numbered SQL | **No change** | Targeted host-side implementation; append-only policy preserved | Protected |
| `sql/0021_p09_in_db_worker.sql`, `tests/test_p09_in_db_worker.py`, P09 review artifacts | **No P10 changes and never included in the P10 commit** | P09 already shipped at `f6b3d70`; sibling ship set | P10 works on main after P09; stage only P10 paths |
| `scratch/`, `.p19-backup/`, pg-agent repository | **No change and no runtime import** | Research/WIP is not ABI | Protected |
| `README.md`, `AGENTS.md` | **No change** | Existing repository and gate rules remain sufficient | Protected |

---

## Work items and verification

### W100 — Package and psql transport

Implement the package skeleton, public exports, dataclasses, errors, worker ID helper, and private fixed-template JSON transport.

Verify:

- import succeeds with `uv run python` from repository root;
- import performs no subprocess or database access;
- only standard-library imports appear in the package;
- psql executable and DSN are constructor inputs;
- `shell=False`;
- dynamic argument data goes through the single JSON data envelope;
- every SQL template wraps kernel results with `to_jsonb` / `row_to_json` so stdout is one JSON document;
- no public `execute`, `query`, `sql`, or transaction API exists;
- claim tokens and payloads are sent on standard input, not command arguments;
- malformed output, nonzero exit, timeout, missing executable, and oversized arguments map to exact error types;
- exception rendering excludes DSN, claim token, full SQL, and argument envelope.

### W101 — Claim lifecycle

Implement claim, renew, yield, complete, fail, and `get_job`.

Verify:

- targeted claim returns one typed `ClaimedJob`;
- empty/noneligible target returns `None`;
- two clients cannot both claim the same row;
- yielded row is reclaimed with the same job ID and a new token;
- wrong/old token transitions return false;
- `get_job` never returns the token;
- current P01 fail behavior is observed without hard-coding ERROR as a future invariant;
- no direct jobs update appears in the package.

### W102 — Log and provider operations

Implement checkpoint, scoped append, next step, LLM checkpoint, run state, and provider key.

Verify:

- checkpoint array ordering is preserved;
- false checkpoint appends nothing;
- scoped append is visible only through the authorized slice;
- a caller-provided `p08_scope` is rejected before SQL;
- next empty step is `s-1`;
- committed LLM event is returned by `llm_checkpoint`;
- provider key matches PostgreSQL and P05 for ASCII and Unicode run IDs;
- changing worker, token, or jobs attempt does not change the key;
- no HTTP, P05 `invoke_llm`, or direct `emit_step` call appears in the package.

### W103 — Await and sleep degradation

Implement `await_event` and the presence-checked `sleep_claim`.

Verify:

- emit-before-await returns immediately and keeps the claim live;
- absent event registers one wait, sets WAITING, and clears the claim;
- lost claim returns `accepted=false`;
- optional/null deadline and object metadata round-trip;
- current tree without P04 raises `P10_SLEEP_UNAVAILABLE`;
- the absence path leaves jobs and agent_steps unchanged;
- presence is checked per call, not cached;
- no backup/WIP path appears in imports or source strings.

### W104 — Catalog and P08 gates

Implement registration, unregistration, catalog lookup, recall, fold, env read, and host authorization.

Verify:

- registered host metadata is returned with `entrypoint=None` and `source_kind='host_registration'`;
- unregister removes the compiled row after P06 refresh;
- recall/fold use the exact supplied slice;
- env tests use paradigm `rlm` and reach `55000 P08_ENV_WORKSPACE_UNAVAILABLE`; a `codeact` env call is `42501 P08_ENV_DISABLED` and is not the W104 assertion;
- host authorization accepts one read-only host row;
- host authorization rejects in-db queue/session rows and host external/transactional rows;
- a revoke between two calls denies the second call;
- no descriptor cache or host callable execution exists.

### W105 — Host one-step acceptance

Use the real `CordisHostClient` against a database applied with the existing source tree.

Required sequence:

1. Through trusted `psql` fixture setup (not `CordisHostClient`, not `enqueue_job`):
   - `INSERT` one PENDING `cordis.jobs` row for a unique `run_id` (PENDING-direct insert is allowed by `sql/0001_p01_claim.sql` constraints; this also proves the host client does not need P09 `enqueue_job`);
   - create a slice on that run with P07 `create_slice` and issue a live `run` grant with `issue_grant` (`status='issued'`, `sql/0007_p07_grant_registry.sql`);
   - create a **second** slice on the **same** run with **no** `run` grant.
2. Create client A with worker ID `host:p10proof:<uuid-a>`.
3. Claim the exact run.
4. Read `s-1`.
5. Confirm `llm_checkpoint` is absent.
6. Derive the provider key.
7. Construct one deterministic test-only `llm` payload in Python containing protocol `cordis.p10.host.proof.v1`, the provider key, model `host-mock`, and a fixed raw response object. Storing the key in the payload does **not** prove external HTTP idempotency.
8. Append it through `emit_step_scoped`.
9. Fold the authorized slice with paradigm **`codeact`** and assert the event is present.
10. Fold the second same-run slice (no `run` grant) with paradigm `codeact` and assert `42501 P08_FOLD_RUN_GRANT_REQUIRED` (`sql/0020_p08_four_seam_enforcement.sql:484-486`). Do not use a slice from another run: that raises `slice does not belong to run` instead.
11. Yield.
12. Create client B with a distinct worker ID and reclaim the same job.
13. Assert same job ID, new token, claimed-by client B.
14. Cleanly yield or otherwise release the fixture claim.

The proof must not call `step_once`, `worker_step`, `invoke_llm`, or a host plugin callable.

### W106 — Documentation and source boundaries

Document: exact public API; one psql process/transaction per method; checkpoint-before-transition ordering; targeted claims as the P10 default usage; global poll routing hazard; worker ID convention; lease/heartbeat rule; unknown-outcome reconciliation including host SIGINT/orphan psql; no host-clock `claim_expires_at` comparison; no private log/cache; provider-key versus fingerprint distinction and that the fixture does not prove external HTTP idempotency; optional sleep behavior; P08 gate requirements; trusted catalog lookup versus authorized host descriptor; no-execution boundary; explicit model-tool denylist; P09 sibling separation; no packaging/dependency/SQL changes.

### W107 — Required named tests

Create `tests/test_p10_host_sql_seam.py` with these named tests:

| Test | Required proof |
|---|---|
| `test_p10_public_api_inventory_and_no_new_sql_marker` | Exact exported names; no P10 numbered SQL; `cordis.get_schema_version()` remains **`p21`**; no overload/catalog additions |
| `test_p10_worker_id_format_and_client_validation` | Exact host ID grammar, deterministic test UUID support, invalid inputs fail before psql |
| `test_p10_psql_transport_errors_and_output_validation` | Missing binary, timeout, nonzero exit/SQLSTATE, malformed/multiple output, and secret-redacted exception behavior. Timeout/malformed/nonzero injection uses a `psql_path` stub executable, not a second Postgres |
| `test_p10_special_character_arguments_are_data_not_sql` | Quotes, backslashes, Unicode, newlines, dollar tags, and SQL-looking payload text round-trip without executing injected SQL |
| `test_p10_provider_key_matches_postgres_and_p05_guard` | Host key equals PostgreSQL/P05 expression; correct key passes a P05 fixture guard; wrong key fails; attempt/worker/token do not affect it |
| `test_p10_two_clients_share_p01_claim_fencing` | Mutual exclusion, committed claim, yield, same job ID reclaim, new token, distinct host IDs |
| `test_p10_claim_transitions_preserve_boolean_fencing` | Old/wrong token renew/yield/complete/fail return false; no fallback state mutation |
| `test_p10_checkpoint_and_scoped_append_are_claim_fenced` | Live token writes; lost token writes nothing; checkpoint order preserved; scoped payload is kernel-owned |
| `test_p10_next_step_and_llm_checkpoint_support_skip_if_present` | `s-1`, committed LLM lookup, duplicate append behavior remains P02/P05-defined |
| `test_p10_host_process_claims_and_appends_one_scoped_step` | Full W105 acceptance path |
| `test_p10_await_event_immediate_and_suspend_paths` | Emit-before-await immediate path and durable WAITING path |
| `test_p10_sleep_is_typed_but_unavailable_without_p04` | Exact presence check, stable unavailable error, no state/log mutation, no WIP import |
| `test_p10_catalog_registration_lookup_and_unregister` | P06 host source and compiled row behavior through the client |
| `test_p10_authorize_host_tool_is_read_only_and_non_executing` | Exact host/read-only acceptance; in-db/effectful refusal; no execution API |
| `test_p10_four_seam_calls_are_slice_bound_and_not_cached` | Two same-run slices; recall/fold do not union; fold uses `codeact`; env uses `rlm` and preserves `55000 P08_ENV_WORKSPACE_UNAVAILABLE`; revoke affects next authorization |
| `test_p10_get_job_and_run_state_support_lost_response_reconciliation` | Non-secret scheduler snapshot plus log-derived terminal/in-progress state |
| `test_p10_has_no_p09_worker_or_control_plane_model_dispatch` | Package source does not invoke P09 functions, P05 step body, event emit, issue-family writers, or generic plugin execution |
| `test_p10_source_and_dependency_boundaries` | No SQL/tools/conftest/pyproject/uv-lock changes required; no pgembed import in the package; no scratch or backup dependency |

Test fixture rules:

1. Apply/reset only through `run_apply`.
2. Use `psql`/`psql_session` only for trusted fixture setup and direct database assertions.
3. Instantiate the host client with `server.get_uri(database)` and `POSTGRES_BIN_PATH / "psql"`.
4. Do not add a second server or apply fixture.
5. Reset before exact-inventory tests.
6. Register test host plugins through the P06 API, not direct compiled-catalog inserts.
7. Use test-only data/functions only in disposable databases and never copy P04 WIP.
8. Do not depend on test execution order; each stateful test owns or resets its database state.
9. Create PENDING jobs rows with trusted `psql` `INSERT`, not `enqueue_job` and not the host client.
10. Create slices and live grants with P07 `create_slice` + `issue_grant` (`status='issued'`). Second-slice fold denial uses a same-run slice without a `run` grant.

### W108 — Regression and delivery gate

Focused test:

```bash
uv run pytest tests/test_p10_host_sql_seam.py -q
```

Cross-protocol suite on the committed P09 tree (`p21`):

```bash
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
  tests/test_p09_in_db_worker.py \
  tests/test_p10_host_sql_seam.py -q
```

Full suite:

```bash
PGCORDIS_PGDATA="$CORDIS_ROOT/.pgdata" uv run pytest -q
```

The cross-protocol suite always includes `tests/test_p09_in_db_worker.py`. The baseline marker is `p21`. There is no supported pre-P09 implementation branch.

---

## Tradeoffs

1. **`psql` subprocess instead of psycopg.** Avoids a dependency and matches the repository, but adds process startup latency and lacks a persistent transaction/session API.
2. **No numbered SQL.** Keeps SDK concerns out of the kernel and avoids marker churn, but the provider expression remains locked by tests rather than a new shared SQL function called by P05.
3. **Database-derived provider key.** Guarantees P05 encoding parity, but costs one database round trip before a future host HTTP request.
4. **No worker loop.** The seam is small and testable, but applications must add routing and orchestration in later plans.
5. **One transaction per verb.** Claims and checkpoints survive host-process changes, but checkpoint and yield are not one atomic client transaction. A crash between them relies on stale recovery and log replay.
6. **No background heartbeat.** No hidden threads or lifecycle leaks, but future blocking operations must explicitly renew.
7. **Typed but unavailable sleep.** P10 satisfies the API boundary without stealing P04, but current callers cannot successfully sleep through this client until P04 ships.
8. **Authorize-only host tools.** P08 and host identity checks are proven without external effects, but P10 does not yet demonstrate useful host tool execution.
9. **Repo-local, uninstalled package.** Tests and P11 can import it immediately, but external projects cannot depend on a published SDK.
10. **Trusted same-role boundary.** The client avoids exposing dangerous methods to a model, but a database principal with arbitrary SQL can still bypass it, as already documented by P07/P08.

---

## Risks and rollback

### Process-per-call overhead

A real high-throughput host worker may find psql startup expensive. P10 accepts this because the goal is the minimum correct seam, not throughput.

Mitigation: keep the public semantic API transport-neutral internally, but do not introduce a second transport until a measured later plan.

### Unknown mutation outcome after client failure

A response can be lost after PostgreSQL commits. Automatic mutation retries could duplicate checkpoints or confuse ownership.

Mitigation: no automatic retry; document operation-specific reconciliation and use existing log/job reads.

### Credential exposure

A URI containing a password may be visible in the psql process command line.

Mitigation: documentation requires `.pgpass`, service files, or libpq environment configuration for non-test use; tests use local pgembed URIs. Claim tokens and payloads remain on standard input.

### Global polling can claim unsupported work

The underlying P01 call allows `run_id=NULL`, but P10 has no host queue-handler registry.

Mitigation: acceptance and P11 use targeted run IDs. Documentation forbids unattended global polling until a later host routing plan can classify every job type.

### Checkpoint/yield crash window

A committed checkpoint followed by a host crash leaves a live RUNNING claim until expiry.

Mitigation: the next recovery sees the checkpoint, reuses the step name, and yields or continues after stale release. The log remains authoritative.

### P04 absence

Sleep cannot succeed on the current product tree.

Mitigation: explicit local feature error and no emulation. P04 later satisfies the same exact method signature.

### Legacy P05 path remains unisolated

The P09 catalog contains `kernel.step_once`, but P10 could accidentally treat it as a tool if it used raw catalog rows.

Mitigation: `authorize_host_tool` requires host locus/host invocation/NULL entrypoint and never executes. Documentation lists `kernel.step_once` as prohibited.

### No actual host callable authentication yet

P10 validates a catalog descriptor but has no callable registry. A later implementation could incorrectly bind the authorized identity to the wrong function.

Mitigation: no execution in P10. P12/P14 must define exact local identity binding before executing host tools.

### P09 path leakage into the P10 commit

P09 is already on `main` (`f6b3d70`). The remaining risk is staging P09 files or docs as if they were P10.

Mitigation: stage explicit P10 paths only; inspect both working-tree diff and `git log @{u}..HEAD` before Oracle review/push.

### Rollback

P10 creates no database object or migration.

Rollback consists of: stop host processes; remove/revert `pg_cordis_host`, its documentation, and P10 tests in a later source commit; unregister any runtime host plugin definitions created by an application if they are no longer wanted.

Existing jobs, log rows, waits, grants, and host definitions created through the client remain valid kernel data. Removing the client does not rewrite them.

---

## Implementation order

1. Plan critique is recorded at `docs/reviews/2026-08-25-p10-plan-critique.md`; P0 none; P1/P2 folded; Status is `ready to implement`.
2. Implement on `main` after P09 (`f6b3d70`). Do not include P09 paths in the P10 commit.
3. Create `pg_cordis_host/__init__.py` and `client.py` with W100 only: public inventory, types, errors, worker ID, and private transport (`to_jsonb`/`row_to_json` wrappers).
4. Add transport-focused unit tests before scheduler methods, including a `psql_path` stub executable for timeout/malformed/nonzero injection.
5. Add W101 claim lifecycle and reconciliation methods; run the P01/P10 focused tests.
6. Add W102 checkpoint, scoped append, step reads, run state, and provider-key method; run P02/P05/P08/P10 tests.
7. Add W103 await and optional sleep; run P03/P10 tests.
8. Add W104 P06 catalog and P08 gate methods; run P06/P07/P08/P10 tests.
9. Add the W105 end-to-end host process proof using the pinned fixtures (trusted `INSERT`, P07 slice/grant, `codeact` fold, `rlm` env).
10. Write `docs/host-sql-seam.md` with the exact operational and security contract, including interrupt unknown-outcome and no host-clock expiry check.
11. Complete all W107 named tests, including source/dependency boundaries.
12. Run the focused P10 module.
13. Run the cross-protocol suite (includes `test_p09_in_db_worker.py`; marker `p21`).
14. Run the full suite on a clean tree.
15. Inspect the complete diff: no SQL changes; no dependency changes; no tools/conftest changes; no P09 ship-set files; no scratch/backup files; only the P10 package, documentation, tests, plan, and review artifacts.
16. Follow the `AGENTS.md` implementation Oracle loop: produce the P10-only diff artifact; select implementation, this plan, contracts, and relevant SQL/docs; request review with P10 completion criteria; record every verdict in `docs/reviews/2026-08-25-p10-implementation-oracle.md`; fix all P0/P1 findings and re-review in the same chat; rerun tests after behavioral changes.
17. After the latest Oracle review has no open P0/P1, stage only the P10 ship set, commit with an English P10 message, verify the upstream range, and immediately push.
18. Do not state that P10 is complete until the push succeeds.

Steps 3–11 must land together in the final commit. There is no independently releasable partial client without its contract and acceptance tests.

---

## Open questions

No P10 implementation decisions remain open. Mid-flow and plan critique P0/P1 are folded; Status is `ready to implement`.

Explicitly deferred:

- successful sleep, retry curves, stale-lease logging, and dead-letter behavior — P04;
- alternating in-database and host claims — P11;
- host workspace/worktree and local callable identity binding — P12;
- selection and real prompt assembly — P13;
- host file mutation and path fencing — P14;
- full two-project product proof — P15;
- nontransactional `tool/call` / `tool/result` recovery and indeterminate effects — P16;
- asynchronous spawn — P17;
- real host LLM HTTP transport, streaming, request fingerprint ABI, and provider-specific retries — later dedicated transport/driver plan;
- a persistent libpq driver or published SDK package — later, based on measured need;
- role/RLS authentication and hostile same-user SQL — later security plan outside the current SQL restrictions;
- global host queue routing and host queue-handler metadata — later worker plan;
- UI, habitat, DSH event compatibility, plugin migrator, and dynamic loading — explicitly out of the current architecture.

---

## References

- `AGENTS.md` — plan gate, shared fixtures, repo boundary, Oracle implementation gate, immediate commit/push
- `docs/plans/2026-08-23-pg-cordis-development.md` — P10 skeleton and P11/P12+ boundaries
- `docs/decisions/2026-08-23-pending.md` — D2, D4, D8, one queue, dual locus, provider idempotency
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — signed architecture, host minimal seam, explicit non-goals
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` — claim verbs, host happy path, provider key, failure ordering, dual locus
- `docs/plans/P04-sleep-retry-2026-08-24.md` — locked future sleep signature and retry ownership
- `.p19-backup/p04-wip/0004_p04_sleep_retry.sql` — non-product evidence only; never imported or copied
- `docs/plans/P05-one-step-driver-2026-08-24.md` — one-step and provider-key contracts
- `docs/plans/P06-plugin-catalog-2026-08-23.md` — host source registration and catalog metadata
- `docs/plans/P08-four-seam-enforcement-2026-08-24.md` — explicit P10 handoff, descriptor freshness, host impersonation boundary
- `docs/plans/P09-in-db-worker-2026-08-25.md` — sibling shape, in-database worker boundary, host/provider deferral
- `sql/0001_p01_claim.sql` — scheduler and lease verbs
- `sql/0002_p02_log.sql` — append monopoly, checkpoint, step reads, run state
- `sql/0003_p03_wait_event.sql` — atomic wait and WAITING transition
- `sql/0005_p05_one_step_driver.sql` — provider-key guard and unchanged SQL mock
- `sql/0006_p06_plugin_catalog.sql` — host definitions, compiled catalog, legal locus/invocation pairs
- `sql/0007_p07_grant_registry.sql` — slice-bound live grants
- `sql/0019_p19_paradigm_policies.sql` — policy lookup
- `sql/0020_p08_four_seam_enforcement.sql` — readiness latch, scoped append, four public gates
- `sql/0021_p09_in_db_worker.sql` — parallel sibling; never wrapped by P10
- `sql/README.md` — SQL source tree, apply and marker rules
- `pyproject.toml` — Python 3.12, package=false, dependency inventory
- `tools/apply_pg_cordis.py` — sole apply path
- `tests/conftest.py` — shared apply/psql/session helpers
- `tests/test_p01_claim.py` — two-connection claim/yield/reclaim proof
- `tests/test_p05_one_step_driver.py` — current stand-in Python orchestration and P05 proof payload
- `tests/test_p00_sql_source.py` — exact current SQL/function/marker pins
- `scratch/yield_walkthrough/run.py` — research-only prior art, not ABI
