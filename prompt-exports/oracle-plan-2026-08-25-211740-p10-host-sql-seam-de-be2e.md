## Final Prompt
<taskname="P10 host SQL seam deep plan"/>
<task>
Rewrite `docs/plans/P10-host-sql-seam-2026-08-25.md` from its current draft-scaffold state into the **complete P10 deep plan** — a full, implementation-ready specification for pg_cordis's host minimal SQL seam (skeleton P10 in `docs/plans/2026-08-23-pg-cordis-development.md:227-235`). An implementer must be able to execute it without this conversation.

**This is plan-only.** Do not implement, do not create SQL or test files, do not touch `tools/`, `tests/`, or `sql/`. The single deliverable is the rewritten plan document (plus, optionally, nothing else).

**Method:** the scaffold's `## Background` already holds curated explore-agent findings (verb inventory with file:line refs, P08 constraints, P09 sibling analysis, host-stack facts, SQL-tree conventions) plus Goal and Open Questions 1–8. Build on that material — fold it into the full spec, preserving and extending the current-state analysis rather than re-deriving or dropping it. All sources it cites are in the selection below.

**Document shape** — match the P09 deep plan (`docs/plans/P09-in-db-worker-2026-08-25.md`) section-for-section:
1. Header block: Date, Status, Parent, Depends on, Parallel with, Contract, Primary deliverable(s), Critique, SQL marker, PL/pgSQL dollar tag. Set Status `ready to implement` **only if every material decision is resolved in the document**; otherwise leave Status as the orchestrator will set it (e.g. `draft (Phase 3)` with a note naming the unresolved items).
2. Summary, Goal, **explicit non-goals** (bulleted, negative-space as detailed as P09's).
3. Execution index table (W-numbers, goal, done-when, key files, dependencies, size) — **continue the W series after P09: W100+** (P08 used W80–W88, P09 used W90–W99).
4. Background (skeleton/contract/snapshot + current-state analysis; reuse the scaffold's).
5. **Resolved decisions table** — numbered, each with Decision / Evidence and rationale / Rejected alternative. Must close all 8 scaffold open questions that evidence can close (see evidence map below); state explicitly that no implementation fork remains if true.
6. Component-by-component design (Python/SQL surfaces, exact signatures, algorithms, properties, error tables).
7. State and data flow (ASCII flows), API/persistence impact, exact function/module inventory.
8. Error handling and edge cases table; boundary conditions.
9. File-by-file impact table (change / why / ordering) covering every file in the ship set, including "no change" rows for protected paths.
10. Work items W1xx with **named tests** and per-item verification bullets; final regression gate with exact `uv run pytest` commands.
11. Tradeoffs (numbered, honest), Risks and rollback, Implementation order (numbered steps ending in the AGENTS.md Oracle-loop gate and immediate commit/push), Open questions (only if genuinely unresolvable from evidence — otherwise a "deferred to Pxx" list like P09's).
12. References list.

</task>
<architecture>
Repo `zcordis-pgembed` = canonical pg_cordis SQL source tree (schema **`cordis`**; product name pg_cordis; NO `CREATE EXTENSION`). Numbered append-only files in `sql/` applied whole-tree in one transaction by `tools/apply_pg_cordis.py` onto an embedded Postgres started via local `pgembed`. Python ≥3.12, uv, `package = false`, runtime dep only `pgembed`; dev dep pytest. All SQL execution today is `psql` CLI subprocess (`tests/conftest.py`: `run_apply`, `psql`, `psql_session`; `next_sql_prefix()` = max prefix + 1).

Kernel layers (by plan): P01 claim verbs on `cordis.jobs` (`claim_job`/`renew_claim`/`yield_claim`/`complete_claim`/`fail_claim`/`release_stale`); P02 append-only `agent_steps` log (`emit_step` monopoly, `emit_step_claimed`, `checkpoint`, `next_step_name`, `llm_checkpoint`, `run_state`); P03 `run_events`/`run_waits` + `await_event`/`emit_event` (unauthorized); P05 `step_once` one-step mock driver + `invoke_llm` SQL mock, provider key `md5(run_id || '/' || step_name)`; P06 `plugin_catalog` (COMMENT + `register_host_plugin` sources, `refresh_plugins()`; legal pairs in-db+queue / in-db+session_select / host+host_tool, host rows `entrypoint IS NULL`); P07 grant registry (slice-bound); P08 four-seam gates (`recall_named_corpus`, `fold_slice_messages`, `read_run_env`, `authorize_tool_dispatch`) + readiness latch; P19 paradigm policies; P09 (uncommitted working tree) in-db worker `worker_step`/`enqueue_job`/`invoke_in_db_tool`.

P10 is the **dual-locus host side**: a thin host-process seam speaking the same SQL verbs (claim / checkpoint / yield / sleep / await / catalog lookup), same provider-key rule, host worker claims the same `cordis.jobs` rows with a distinct `worker_id`. D4: habitat/SDK is **not** kernel — durable behavior stays in SQL; host code is a client. D8 existence proof: absurd Python SDK <2000 LOC; anti-pattern: DBOS ~40K LOC thick SDK.
</architecture>
<selected_context>
**The document being written and its two shape models (read first):**
- `docs/plans/P10-host-sql-seam-2026-08-25.md` — the scaffold to expand: Goal, curated Background (verb inventory with file:line, P08/P09 constraints, host-stack facts, tree conventions), Open Questions 1–8, References.
- `docs/plans/P09-in-db-worker-2026-08-25.md` (full) — the primary shape model AND the parallel sibling. Note its header format, non-goals depth, decisions table with Evidence/Rejected, named-test tables, tradeoffs/risks, implementation order, "deferred to P10: host SQL seam and provider canonicalization" (`:1048-1050`).
- `docs/plans/P08-four-seam-enforcement-2026-08-24.md` (full) — second shape model; owns the gates P10 must consume. Key lines: downstream-consumers table assigns P10 "must pass explicit slice_id, use the four public gates, hide P07 issue-family SQL from model tools"; Component 6 end: "The in-db entrypoint/identity check does not authenticate a host tool with `entrypoint IS NULL`; **P10 remains responsible for host impersonation**. … Returned descriptor is valid for the current dispatch only. P09/P10 must not cache it across claims."

**Locked contracts & architecture (do not reopen; cite, don't restate at length):**
- `docs/decisions/2026-08-23-pending.md` — D1–D9 all signed. D8 = option A + minimal plugin catalog (same SQL verbs claim/checkpoint/yield/sleep/await + catalog lookup; no DSH event layer, no manifest→SQL migrator, no postponing host path, no dynamic `node:vm`). D2 = tool A+C recovery (P16). D4 five-piece kernel, SDK not kernel. §"已锁定" table: one queue, one claim protocol both loci, LLM idempotency A+B (`Idempotency-Key = H(run_id, step_name)`, **tools not covered**).
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — §4 signed contracts table; §7 v0 scope (host minimal seam verb list); §9 explicit non-goals (thick host SDK / DSH event compat / plugin migrator); §10.3 "first SDK language" was deliberately left open → **P10's job to lock**.
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` — the claim protocol. §3 verbs table (claim/heartbeat=checkpoint-extension/yield/wait/sleep/complete/fail/release_stale); §4 happy path (provider key NOT attempt, NOT fingerprint); §9 dual-locus table (host claims over libpq with same verbs, same provider key for its own HTTP, host must not keep private in-memory log as SoT, may cache folds); §10 failure-ordering cheat sheet; §11 jobs state machine.
- `docs/plans/2026-08-23-pg-cordis-development.md` — P10 skeleton (`:227-235`): thin wrapper, same provider-key rule; **not** thick SDK / DSH compat / UI; **done when** a host process can claim and write back one-step log (tool surface may be read-only first); first SDK language decided at implementation. Also P11 (alternating-claim proof, depends P09+P10) and P12+ (host plugins after P10) — P10's boundaries.

**Kernel SQL the seam wraps (full implementations):**
- `sql/0001_p01_claim.sql` — `claim_job(text,text,integer DEFAULT 90) → SETOF cordis.jobs` (SKIP LOCKED; `p_run_id NULL` = poll; reaps stale first), `renew_claim`, `yield_claim`, `complete_claim(token,result)`, `fail_claim(token,reason)`, `release_stale`; `jobs` constraints (claim fields iff RUNNING; unique `run_id`, unique `claim_token`).
- `sql/0002_p02_log.sql` — `emit_step` (sole INSERT), `emit_step_claimed(token,run_id,kind,payload,step_name,extend)` (claim-fenced, extends lease, returns false on lost claim), `checkpoint(token,jsonb-array,extend)` (validates events, fences, loops emit_step), `next_step_name(run_id)` (s-N naming), `llm_checkpoint(run_id,step_name)` (skip-HTTP read), `run_state`.
- `sql/0005_p05_one_step_driver.sql` — `invoke_llm(run_id,step_name,request,provider_key)` **replaceable SQL mock**; guard `p_provider_key = md5(run_id || '/' || step_name)` at `:37-39` (this is the canonicalization P10 reuses); `step_once(run_id,token,extend) → text` outcomes `lost_claim|complete|fail|yield`, never mutates jobs.status; request carries `protocol: cordis.p05.mock.v1`; llm payload envelope `{fingerprint, model, protocol, provider_key, raw}`.
- `sql/0003_p03_wait_event.sql` (slice 60-280) — `await_event(token,run_id,scope,name,await_id,deadline,ui_metadata,extend) → (accepted, should_suspend, payload, source_run_id, source_seq)`; atomic wait registration + WAITING.
- `sql/0006_p06_plugin_catalog.sql` (slices) — `plugin_catalog`/`host_plugin_definitions` DDL (legal pairs; host rows `entrypoint IS NULL`, `source_kind='host_registration'`); `register_host_plugin(jsonb) → text`, `unregister_host_plugin`, `refresh_plugins()` (DELETE+insert compiled catalog from COMMENT + host sources).
- `sql/0020_p08_four_seam_enforcement.sql` (slices) — `_require_isolation_feature()` latch; `authorize_tool_dispatch(run_id,slice_id,identity,bindings) → jsonb descriptor` — authorization ONLY (never executes), control-plane denylist, bindings key-set must equal `required_grants`, descriptor excludes raw `metadata`/`source_kind`.
- `sql/0021_p09_in_db_worker.sql` (full, **uncommitted working tree**) — the sibling. `worker_step(text,text,integer) → TABLE(job_id,run_id,outcome)` is the in-db queue dispatcher; host must NOT call it as its entrypoint. `enqueue_job`, `invoke_in_db_tool` (rejects host-locus rows), `_resolve_in_db_queue_handler`, COMMENT registering `kernel.step_once`, `refresh_plugins()`, marker `p21`, tag `$p09$`.

**Sleep evidence (Open Question 4):**
- `docs/plans/P04-sleep-retry-2026-08-24.md` (slice 1-130) — Status `ready to implement`; mid-flow lock: `sleep_claim(uuid, text, timestamptz, integer)` matching `await_event`/`emit_step_claimed` shape; `max_attempts=3`. **`0004` is NOT in `sql/`** — P04 is plan-only; P08 explicitly refused to depend on it, same discipline applies.
- `.p19-backup/p04-wip/0004_p04_sleep_retry.sql` (slice 380-560) — WIP (not product): `sleep_claim` emits `run/sleep` via `emit_step_claimed`, sets SLEEPING + `available_at=until`, clears claim, returns boolean; plus `retry_delay_seconds`. P04 also revises `fail_claim`/`release_stale`/`claim_job` (claims due SLEEPING rows, wakes with `run/wake`).

**Host-stack & harness evidence (Open Questions 1, 2, 6, 7):**
- `pyproject.toml` — name `pg-cordis`, `requires-python >=3.12`, deps only `pgembed>=0.3.0rc1` (editable local path), dev pytest, `package = false`. No psycopg/asyncpg.
- `tests/conftest.py` — `run_apply`, `psql(server,db,sql)` (subprocess, ON_ERROR_STOP, `-t -A`), `psql_session` context manager (persistent psql process, sentinel-delimited `execute`, explicit `commit()`/`rollback()`, auto-rollback on exit), `next_sql_prefix`, `load_apply_module`.
- `tools/apply_pg_cordis.py` — the only apply path; preflight rejects CREATE EXTENSION/GRANT/role/tx-control/public tables/psql meta; single transaction; verifies zero-arg `get_schema_version() → text`.
- `tests/test_p01_claim.py` (slice) — `test_mutual_exclusion_and_yield_reclaim`: two `psql_session` connections proving mutual exclusion and reclaim — the exact pattern a P10 host-worker test reuses.
- `tests/test_p05_one_step_driver.py` (slice) — `PROOF_PAYLOAD` (3-step mock run: llm/tool×2 then final 'ok'), literal helpers, truncated-tree apply, and the Python-side claim → `step_once` → outcome mapping through P01 verbs — the de-facto stand-in host that P10 formalizes.
- `tests/test_p00_sql_source.py` (slice) — `KERNEL_FUNCTIONS` exact tuple (working tree already includes the four P09 names) and `test_fresh_apply_lists_current_tree_and_p21` file-list pin — the current-tree pins any P10 numbered SQL must retarget.
- `scratch/yield_walkthrough/run.py` (full) — **research only, banned as ABI** (AGENTS.md + sql/README.md). Prior host-loop proof in Python: psycopg2 against pg-agent v2 SQL (different repo/env), loop of enqueue → 3× claim/step/transition. Useful as prior art for the host-loop question only; must not be lifted or imported.
- `AGENTS.md` — the gates: plan-before-code (Status `ready to implement` + plan-critique folded before any code); contracts beat Oracle; repo boundary (don't touch pgembed's `PostgresServer.psql()` just to pick a client library); append-only SQL tree; tests must use existing `run_apply`/`psql`/`psql_session`; do NOT make `tools/` a package; do NOT write a second apply/boot script; per-P Oracle review → immediate commit/push; commit contains only that P's ship set.
- `sql/README.md` — filename contract, forbidden tokens, version ladder (current tree ends `0021`/`p21`), P06 envelope JSON, apply commands.
</selected_context>
<relationships>
- Host worker ↔ kernel: host Python calls `cordis.claim_job(run_id?, worker_id, lease)` → gets `claim_token`; reads step state via `next_step_name`/`llm_checkpoint`; writes log via `emit_step_claimed`/`checkpoint` (claim-fenced, lease-extending); transitions via `yield_claim`/`complete_claim`/`fail_claim`; optionally `await_event` (P03) / `sleep_claim` (P04, absent). One claim = one step (F §3/§9).
- Provider key: same `md5(run_id || '/' || step_name)` on host as in SQL — guarded in `invoke_llm` (`sql/0005:37-39`); host LLM HTTP (when it exists) must reuse it; skip-if-present via `llm_checkpoint`; tools NOT covered (P16's problem).
- Host tools ↔ P08: any model-facing tool dispatch goes through `cordis.authorize_tool_dispatch(run_id, slice_id, identity, bindings)` → descriptor (authorization only; host rows have `entrypoint IS NULL` so P08 cannot authenticate them — host impersonation/identity is P10's); descriptor never cached across claims.
- Host ↔ P06 catalog: `register_host_plugin(jsonb)` / `unregister_host_plugin` / `refresh_plugins()` for registration; catalog lookup is plain `SELECT` on `cordis.plugin_catalog` (no dedicated lookup function exists).
- P09 ↔ P10: parallel siblings on the same `cordis.jobs` queue. Host must NOT enter through `cordis.worker_step` (it dispatches in-db queue handlers only and never returns the live claim token); host uses P01 verbs directly with a distinct `p_worker_id`. P11 later proves alternating claims. P09 deferred "host SQL seam and provider canonicalization" to P10.
- Tree/versioning: committed HEAD is P08 (`sql/0020`, marker `p20`); P09 (`sql/0021`, `p21`) is uncommitted in the working tree — **P10 must not absorb the P09 ship set**. If the tree P10 applies to includes `0021`, any new P10 numbered SQL is `0022_p10_*.sql`, marker `p22`, dollar tag `$p10$` (tag follows plan number, P08 precedent: file 0020/tag `$p08$`).
</relationships>
<evidence_map>
Resolve each scaffold Open Question with a numbered decision (Decision / Evidence / Rejected). Working evidence notes — verify against the selected files, don't take on faith:
1. **First SDK language** — repo toolchain is Python ≥3.12 + uv + pgembed + pytest; absurd Python SDK <2000 LOC is D8's existence proof; no other language toolchain exists in-repo. Snapshot §10.3 left it open for exactly this plan.
2. **Transport** — D8/F say libpq/SQL verbs. Proven in-repo transport is `psql` subprocess (`conftest.psql`/`PsqlSession`, apply tool). AGENTS.md forbids changing `pgembed.PostgresServer.psql()` to select a library but does not forbid a new client dep in this repo; scratch used psycopg2 only via pg-agent's env. Note each psql statement is its own transaction (autocommit), which matches P09 decision 12's one-commit-per-call worker contract; `PsqlSession.commit()/rollback()` exist for explicit blocks.
3. **Does P10 add numbered SQL at all?** — skeleton verbs all exist except `sleep_claim` (P04, absent). P09 deferred "provider canonicalization" to P10. Options span: Python-only (no new SQL), a small `0022` with host-facing helpers (e.g. a canonical provider-key SQL function mirroring the `invoke_llm` guard; authorize-without-execute already exists), up to a host-tool SQL counterpart that still never runs host code. Decide; document marker/README/test-pin consequences either way (including the no-SQL case).
4. **Sleep** — P04 is `ready to implement` but unshipped; `.p19-backup/p04-wip/` SQL is not product. The plan must NOT silently require uncommitted P04 SQL (P08 set the precedent of refusing the dependency). Pick: typed call landing only after P04 / presence-checked wrapper / documented deferral — with the corresponding test strategy.
5. **Host loop vs verb library** — done-when is *one claim + one log write*. Decide deliverable shape: verb/client library + pytest host process proving the bar (minimal, absurd-style), vs also a host `host_step`-style loop mapping outcomes like P09's `worker_step` — **without** calling `cordis.worker_step`. P11 (alternating claims) is the later proof.
6. **LLM path in the acceptance test** — P05 `invoke_llm` is a SQL mock; reusing it proves no host HTTP. Options: reuse P05 mock from host; emit llm/tool/checkpoint from Python without HTTP under the canonical key; or a host HTTP hook with `Idempotency-Key = md5(run_id || '/' || step_name)` against a mock server (heavier; real HTTP is later transport work — see P09 tradeoff 6).
7. **Module location** — `package = false`; `tools/` must not become a package; no second apply/boot script. Tests already import `tests.conftest` (repo root on sys.path via the `tests` package). A new importable location must let pytest import it without packaging pyproject changes — decide the exact directory/file layout and import story.
8. **P09 working-tree coupling** — plan targets the next free prefix **after the tree it applies to** (`next_sql_prefix()` = max+1 → `0022` if `0021` present); treat P09 APIs as sibling boundaries (do-not-call / do-not-expose lists), never as wrapped internals; ship set must exclude P09's uncommitted diff.
Also decide and pin: worker_id convention for the host; lease/heartbeat policy for host steps (F §8: lease ≥ expected HTTP timeout); what "tool surface read-only first" means concretely (catalog lookup + authorize-only, no host file-tool execution — host file mutation is P12+, D2 recovery P16); and the explicit not-a-model-tool list (issue-family, `emit_step`/`emit_step_claimed`/`emit_step_scoped`/`checkpoint`, `enqueue_job`, `worker_step`, `invoke_in_db_tool`, `_resolve_in_db_queue_handler`, P03 `emit_event`/`await_event` unless routed via catalog row + authorize, legacy `step_once`).
</evidence_map>
<ambiguities>
- **Tree sequencing**: whether P09 (`sql/0021`/`p21`) is committed before P10 work starts is an orchestrator decision outside this plan's control. Handle conditionally as instructed: "if the tree P10 applies to includes 0021, P10's numbered SQL (if any) is 0022 / p22 / $p10$". The plan's file-by-file impact and pin-retarget items must state both cases or pin to the expected post-P09 tree explicitly.
- **P04 availability**: `sleep_claim` exists only as plan + WIP backup; whether P04 ships before P10 is likewise external. The sleep decision (OQ4) must degrade gracefully either way.
- Everything else in the scaffold's Open Questions 1–8 is resolvable from the selected evidence; if you conclude one is not, keep it in Open Questions with the exact missing evidence named.
</ambiguities>

## Selection
- Files: 25 total (17 full, 8 slice)
- Total tokens: 101109 (Auto view)
- Token breakdown: full 88689, slice 12420
- Token accounting: stale from active_tab_published; refresh pending

### Files
### Selected Files
zcordis-pgembed/
├── .p19-backup/
│   └── p04-wip/
│       └── 0004_p04_sleep_retry.sql — 1,486 tokens (lines 380-560 (WIP (not product) P04 SQL: retry_delay_seconds and sleep_claim — emits run/sleep via emit_step_claimed, sets SLEEPING + available_at, clears claim. Evidence of the sleep verb shape P10 would wrap))
├── docs/
│   ├── analysis/
│   │   ├── 2026-08-23-f-yield-loop-protocol-sketch.md — 4,340 tokens (full)
│   │   └── 2026-08-23-i-architecture-snapshot.md — 3,610 tokens (full)
│   ├── decisions/
│   │   └── 2026-08-23-pending.md — 8,250 tokens (full)
│   └── plans/
│       ├── 2026-08-23-pg-cordis-development.md — 4,379 tokens (full)
│       ├── P04-sleep-retry-2026-08-24.md — 2,653 tokens (lines 1-130 (P04 plan header, mid-flow checkpoint (sleep_claim(uuid,text,timestamptz,integer), max_attempts=3), summary, W34-W41 execution index — P04 is ready-to-implement but NOT in the product tree; needed to resolve the sleep open question))
│       ├── P08-four-seam-enforcement-2026-08-24.md — 16,066 tokens (full)
│       ├── P09-in-db-worker-2026-08-25.md — 20,703 tokens (full)
│       └── P10-host-sql-seam-2026-08-25.md — 3,827 tokens (full)
├── scratch/
│   └── yield_walkthrough/
│       └── run.py — 1,558 tokens (full)
├── sql/
│   ├── 0001_p01_claim.sql — 2,118 tokens (full)
│   ├── 0002_p02_log.sql — 3,446 tokens (full)
│   ├── 0003_p03_wait_event.sql — 1,835 tokens (lines 60-280 (P03 await_event signature/algorithm and emit_event — await is the verb the host seam wraps; emit_event is unauthorized and must not become a model tool))
│   ├── 0005_p05_one_step_driver.sql — 6,070 tokens (full)
│   ├── 0006_p06_plugin_catalog.sql — 1,765 tokens (lines 1-130 (plugin_catalog + host_plugin_definitions DDL: legal locus/invocation pairs, effect/retry/reconciliation classification matrix, entrypoint IS NULL for host registrations), 700-779 (register_host_plugin / unregister_host_plugin / refresh_plugins tail — the host catalog registration verbs the host seam calls; refresh_plugins is invoked at file end))
│   ├── 0020_p08_four_seam_enforcement.sql — 2,113 tokens (lines 100-145 (_require_isolation_feature latch — every P08-gated call host seam makes goes through this), 595-784 (authorize_tool_dispatch implementation: identity/denylist checks, bindings key-set equality, slice_has_grant AND-check, returned descriptor JSON shape — authorization-only, never executes; host rows have entrypoint IS NULL))
│   ├── 0021_p09_in_db_worker.sql — 4,647 tokens (full)
│   └── README.md — 2,649 tokens (full)
├── tests/
│   ├── conftest.py — 1,253 tokens (full)
│   ├── test_p00_sql_source.py — 738 tokens (lines 1-100 (KERNEL_FUNCTIONS exact tuple (already includes P09 names in working tree) and test_fresh_apply_lists_current_tree_and_p21 file-list pin — the current-tree pins any P10 numbered SQL must retarget))
│   ├── test_p01_claim.py — 699 tokens (lines 110-190 (test_mutual_exclusion_and_yield_reclaim — the existing two-session psql_session proof that a second connection can claim after yield; the pattern the P10 host-worker test reuses))
│   └── test_p05_one_step_driver.py — 1,131 tokens (lines 1-160 (PROOF_PAYLOAD fixture (3-step mock run), SQL literal helpers, truncated-tree apply pattern, and the Python-side claim → step_once → outcome mapping through P01 verbs — the stand-in host driver P10 replaces))
├── tools/
│   └── apply_pg_cordis.py — 3,453 tokens (full)
├── AGENTS.md — 2,231 tokens (full)
└── pyproject.toml — 89 tokens (full)


---

## Generated Plan

## Chat Send ✅
- **Chat**: `p10-host-sql-seam-deep-p-8DDC72` | **Mode**: plan

### Response


# P10 — Host minimal SQL seam

Date: 2026-08-25  
Status: **draft (Phase 3; design complete, awaiting plan critique before `ready to implement`)**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P10  
Depends on: P05 and P06; consumes P01–P03 and the current P07/P08 contracts; P04 is optional at runtime and is **not** a dependency  
Parallel with: P09  
Contract: D8; dual loci use one `cordis.jobs` queue and one P01 claim protocol; durable behavior remains in SQL  
Primary deliverables: `pg_cordis_host/__init__.py`, `pg_cordis_host/client.py`, `docs/host-sql-seam.md`, `tests/test_p10_host_sql_seam.py`  
Critique: `docs/reviews/2026-08-25-p10-plan-critique.md` — not yet created; all P0/P1 findings must be folded into this plan before changing Status to `ready to implement`  
SQL marker: **none added by P10**; the installed marker remains the baseline marker (`p21` when P09’s `0021` is present, otherwise `p20`)  
PL/pgSQL dollar tag: **not applicable**; P10 adds no numbered SQL or PL/pgSQL body  

The implementation is intentionally Python-only. P10 is the host-side habitat/seam, not another kernel layer. It wraps existing SQL verbs through a synchronous `psql` subprocess client, adds no database objects, and does not change the numbered SQL source tree.

---

## Summary

P10 adds a targeted, thin Python client for trusted host workers rather than refactoring the kernel or introducing a host worker engine. The new `pg_cordis_host` package invokes the existing P01/P02/P03/P06/P08 SQL functions using fixed query templates over `psql`: it can claim one `cordis.jobs` row, renew or release its claim, append claim-fenced log events, complete/fail/yield, await an event, conditionally sleep when P04 is installed, read the plugin catalog, and call all four P08 isolation gates with an explicit slice. Provider idempotency keys are canonicalized against PostgreSQL’s existing `md5(run_id || '/' || step_name)` expression, matching P05 without adding a duplicate kernel function. P10 deliberately ships no polling loop, LLM HTTP transport, host-tool executor, file mutation, private log, SQL migration, or dependency on P09; a pytest process is the acceptance host and proves one targeted claim can append one slice-scoped step and yield for another claimant.

---

## Goal

Ship the first canonical host-process path:

```text
trusted host process
    → creates a host worker identity
    → claims one existing cordis.jobs row through P01
    → reads next step/checkpoint state through P02
    → derives the P05-compatible provider idempotency key
    → appends one claim-fenced, slice-scoped step
    → yields/completes/fails through P01
    → exits without retaining database-local state
```

The canonical acceptance path is:

```text
test/control plane prepares one PENDING job and one authorized slice
    → CordisHostClient claims that exact run
    → next_step_name returns s-1
    → provider_idempotency_key returns md5(run_id || '/s-1')
    → emit_step_scoped appends one llm fixture event under the live claim
    → fold_slice_messages sees that event only on the authorized slice
    → yield_claim returns the same jobs row to PENDING
    → a second host client reclaims it with a different token
```

This proves the P10 skeleton completion condition: a host process can claim and write back one step log using the same database-owned protocol as an in-database worker.

P10 also exposes a read-only host-tool control surface:

```text
catalog lookup
    → P08 authorize_tool_dispatch(run, slice, identity, bindings)
    → require host + host_tool + no SQL entrypoint
    → require read_only / replayable / none
    → return a fresh descriptor
    → do not execute any host callable
```

### Explicit non-goals

P10 does **not**:

- add or modify any file under `sql/`;
- add a P10 schema marker, SQL wrapper function, table, view, type, trigger, role, RLS policy, extension, or migration;
- change `cordis.get_schema_version()`;
- change `tools/apply_pg_cordis.py` or create a second apply/startup path;
- add `psycopg`, `psycopg2`, `asyncpg`, an ORM, a connection pool, or another runtime dependency;
- change `pgembed.PostgresServer.psql()` or require changes in the sibling `pgembed` repository;
- make `tools/` importable or place the host client under `tools/`;
- copy or import `scratch/yield_walkthrough/`, pg-agent v2 SQL, or `.p19-backup/p04-wip/`;
- call `cordis.worker_step`; that function is the P09 in-database queue dispatcher and does not return its claim token;
- wrap or expose `cordis._resolve_in_db_queue_handler`, `cordis.enqueue_job`, or `cordis.invoke_in_db_tool`;
- call `cordis.step_once` as the host execution path;
- call `cordis.invoke_llm` as host HTTP; it remains the P05 SQL mock;
- add a host polling daemon, scheduler loop, queue-handler registry, outcome state machine, or callback framework;
- execute more than the explicit SQL verb requested by one client method;
- implement real LLM HTTP, streaming, retries, provider adapters, or request-fingerprint policy;
- claim that the acceptance fixture proves external provider idempotency;
- execute host tools, even read-only ones; P10 authorizes and returns descriptors only;
- implement file reads, file edits, worktrees, Context Builder, selection, DuckDB, or any external effect;
- implement D2 `tool/call` / `tool/result` recovery; that remains P16;
- load dynamic TypeScript, `node:vm`, DSH manifests, or DSH session-event compatibility;
- implement P11’s alternating in-database/host-worker proof;
- add a private in-memory history or make host state authoritative over `agent_steps`;
- cache folds, plugin descriptors, grants, claims, or authorization results across calls;
- automatically expose any `CordisHostClient` method as a model tool;
- expose P01 lifecycle verbs, P02 writers, P06 registration, P07 issuer verbs, P09 worker control functions, P03 event functions, or legacy `step_once` to the model;
- silently depend on P04’s unshipped `sleep_claim`;
- issue transaction control inside numbered SQL;
- publish or install `pg_cordis_host` as a wheel; the first seam is an in-repository Python package under the existing `package = false` project.

---

## Execution index

P08 used W80–W88. P09 used W90–W99. P10 continues with W100–W108.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W100 | Host package and safe `psql` transport | `CordisHostClient` executes fixed SQL templates synchronously, parses one JSON result, exposes no raw-query API, and uses only the Python standard library | `pg_cordis_host/__init__.py`, `pg_cordis_host/client.py` | Existing project/runtime | Medium |
| W101 | P01 claim lifecycle wrappers | Targeted/global claim, renew, yield, complete, fail, and job inspection preserve P01 return/fencing semantics | same | W100, P01 | Medium |
| W102 | P02 log, step, and provider-key wrappers | Checkpoint, scoped append, next-step, LLM-checkpoint, run-state, and provider-key methods use existing SQL contracts; acceptance never calls `step_once` or `invoke_llm` as its executor | same | W100–W101, P02, P05, P08 | Medium |
| W103 | P03 await and optional P04 sleep | `await_event` returns the complete P03 result; `sleep_claim` checks the exact P04 signature on every call and fails locally without mutation when absent | same | W100–W102, P03; optional P04 | Medium |
| W104 | P06 catalog and P08 isolation surface | Host registration/lookup plus recall/fold/env/tool authorization are available; host authorization accepts only fresh read-only host descriptors and executes nothing | same | W100, P06–P08 | Large |
| W105 | Canonical host one-step proof | A real Python test process claims one run, writes one scoped `s-1` event with the canonical provider key, yields, and a second host identity reclaims it | `tests/test_p10_host_sql_seam.py` | W101–W104 | Large |
| W106 | Host usage and security documentation | Documentation fixes worker identity, lease/heartbeat, transaction, response-loss, sleep, P08, and not-a-model-tool rules | `docs/host-sql-seam.md` | W100–W105 | Small |
| W107 | Error, concurrency, and source-boundary tests | Tests cover input safety, SQL errors, malformed output, timeouts, claim loss, immediate/suspending wait, live authorization, no execution surface, and no SQL-tree change | `tests/test_p10_host_sql_seam.py` | W100–W106 | Large |
| W108 | Regression and delivery gate | P00–P10 relevant suites pass; the P10 diff excludes P09 and protected paths; Oracle review passes before immediate commit/push | tests, plan, review note | W100–W107 | Medium |

W100–W107 form one additive host seam and must land together in the final P10 commit. There is no partial database deployment because P10 adds no SQL.

---

## Background

### Skeleton, D8, and architecture snapshot

The parent skeleton in `docs/plans/2026-08-23-pg-cordis-development.md` assigns P10:

- a thin host wrapper over claim, checkpoint, yield, sleep, await, and catalog lookup;
- the same provider idempotency-key rule as P05;
- no thick SDK, DSH event compatibility, or UI;
- completion when a host process can claim and write back one step log;
- first SDK language as a P10 implementation decision.

D8 in `docs/decisions/2026-08-23-pending.md` locks option A plus the minimal plugin catalog:

- host and in-database workers speak the same SQL verbs;
- plugin metadata includes identity, locus, required grants, and effect/retry classification;
- no DSH event-shape compatibility, manifest-to-SQL migrator, dynamic `node:vm`, or postponed host path;
- durable behavior belongs in SQL rather than a large SDK.

The architecture snapshot adds:

- one `cordis.jobs` queue and one claim protocol for both loci;
- host SDK/habitat is outside the kernel;
- host state must not become a second log SoT;
- host retrieval and dispatch must use explicit slices and the P08 gates;
- Python/SDK language was intentionally left for this plan.

The F protocol requires:

- provider key `H(run_id, step_name)`, independent of claim attempt and request fingerprint;
- a log checkpoint before yield;
- claim fencing on every mutation;
- heartbeat before/during blocking host operations;
- the host to stop and discard an unfinished result after losing its token;
- the next claim to inspect log state rather than repeat a committed named step blindly.

### Kernel verbs P10 reuses

| Area | Existing SQL | P10 use |
|---|---|---|
| Claim | `claim_job(text,text,integer)` | Claims zero or one PENDING row and returns the live token |
| Heartbeat | `renew_claim(uuid,integer)` | Explicit lease extension; no background heartbeat thread |
| Yield | `yield_claim(uuid)` | Returns the same jobs row to PENDING |
| Complete | `complete_claim(uuid,jsonb)` | Marks DONE after a final log event is durable |
| Fail | `fail_claim(uuid,jsonb)` | Uses current P01/P04 behavior installed in the database |
| Job recovery | `release_stale(text,integer)` inside claim | P10 does not duplicate stale-claim logic |
| Checkpoint | `checkpoint(uuid,jsonb,integer)` | Atomic batch append and lease extension |
| Scoped append | `emit_step_scoped(uuid,text,uuid,text,jsonb,text,text[],integer)` | Canonical isolated host append |
| Step naming | `next_step_name(text)` | Determines stable `s-N` |
| LLM recovery | `llm_checkpoint(text,text)` | Detects a committed LLM row before HTTP |
| Run fold | `run_state(text)` | Reconciliation and terminal-state inspection |
| Await | `await_event(uuid,text,text,text,uuid,timestamptz,jsonb,integer)` | Immediate resolve or atomic WAITING transition |
| Sleep | `sleep_claim(uuid,text,timestamptz,integer)` | Optional typed call only when P04’s exact function exists |
| Catalog source | `register_host_plugin(jsonb)` / `unregister_host_plugin(text)` | Trusted host plugin registration |
| Catalog lookup | `cordis.plugin_catalog` | Trusted metadata lookup |
| Recall | `recall_named_corpus(text,uuid,text)` | P08 metadata gate |
| Fold | `fold_slice_messages(text,uuid,text)` | P08 isolated prompt projection |
| Env | `read_run_env(text,uuid,text,text)` | P08 fail-closed env seam |
| Tool authorization | `authorize_tool_dispatch(text,uuid,text,jsonb)` | Fresh authorization and descriptor, no execution |

P10 must not reproduce any validation, lease predicate, append logic, event lock ordering, catalog compiler, grant check, or fold policy already owned by these functions.

### Current P05 host stand-in

Before P10, `tests/test_p05_one_step_driver.py` effectively acts as orchestration glue:

```text
Python test
    → claim_job
    → step_once                 # the step itself still executes in PostgreSQL
    → Python CASE
        → yield_claim | complete_claim | fail_claim
```

That is not a host step. The host process does not produce the LLM or tool event; it only invokes the in-database P05 body.

P10 replaces that stand-in for its acceptance proof with:

```text
Python host client
    → claim_job
    → next_step_name / provider key
    → emit_step_scoped or checkpoint
    → yield_claim
```

The fixture response remains synthetic and local. P10 does not pretend this is HTTP.

### P08 constraints on the host path

P08 requires explicit `(run_id, slice_id)` for recall, fold, env, and tool dispatch. `authorize_tool_dispatch`:

- validates current live grants;
- returns a descriptor only;
- never executes an entrypoint;
- omits raw compiler fields;
- must be called again after claim/grant/catalog changes;
- does not authenticate a host callable because host catalog rows have `entrypoint IS NULL`.

P10 closes its current part of the host-impersonation boundary by refusing to execute any callable at all and by validating that an authorized descriptor is exactly:

```text
identity = requested identity
locus = host
invocation = host_tool
entrypoint = null
effect_class = read_only
retry_class = replayable
reconciliation = none
```

Actual binding of an identity to local executable code remains deferred to the host plugin that owns that code. P12/P14/P16 must define that registry and recovery path before execution is added.

### P09 sibling boundary

P09 and P10 are parallel consumers of the same P01 queue, not wrappers around one another.

P09:

- claims and dynamically invokes `locus='in-db'`, `invocation='queue'` handlers;
- owns `worker_step`, `enqueue_job`, and `invoke_in_db_tool`;
- registers legacy `step_once` as `kernel.step_once`;
- deliberately does not return the live claim token from `worker_step`.

P10:

- uses P01 claim functions directly;
- receives the live token only from `claim_job`;
- does not call or expose P09 functions;
- does not resolve a P09 queue handler;
- has no dependency on the presence of `0021`.

If P09 is still uncommitted when implementation starts, P10 must be developed in a clean separate worktree or after P09 is committed/removed. The P10 commit must not absorb P09 files.

### Current host stack

The repository already provides:

- Python 3.12;
- uv;
- pytest;
- embedded PostgreSQL through `pgembed`;
- `psql` subprocess patterns in `tests/conftest.py` and `tools/apply_pg_cordis.py`;
- persistent test sessions through `PsqlSession` when explicit transaction tests are needed.

It does not provide:

- an installed Python package;
- a Python PostgreSQL driver;
- an async runtime;
- an HTTP dependency;
- a host daemon.

The first seam therefore uses the existing `psql` transport and the Python standard library. Adding a database-driver dependency solely for P10 would expand packaging and connection-lifecycle decisions without improving the one-step proof.

### SQL tree and release coordination

P10 adds no SQL, so it does not consume a numeric prefix:

- if the implementation baseline contains P09’s `0021`, the marker stays `p21`;
- if implemented before P09, the marker stays `p20`;
- no P10 test may expect `p10`, `p22`, or any P10-specific database marker;
- `tests/test_p00_sql_source.py` and other current-tree pins are unchanged by P10.

If a later critique requires a P10 SQL object, that is a material design change: this plan must be revised, the next prefix chosen from the implementation baseline (`0022` after P09), the marker advanced, and all current-tree pins retargeted before Status can become `ready to implement`.

---

## Current-state analysis

### Existing ownership and mutation points

`cordis.jobs` owns scheduler eligibility and claim authority:

```text
PENDING
  → claim_job
RUNNING + claim_token + claimed_by + claim_expires_at
  → renew_claim
RUNNING with extended lease
  → yield_claim / complete_claim / fail_claim / await_event / sleep_claim
PENDING / DONE / ERROR / WAITING / SLEEPING
```

The token, not the worker ID, is authoritative. P10 must preserve that distinction:

- `worker_id` is observable ownership metadata;
- `claim_token` is the capability required for mutation;
- no client method may infer ownership from `claimed_by`;
- a false transition result means the token is no longer authoritative.

`cordis.agent_steps` remains the only historical SoT. P10 writes only through:

- `checkpoint` for generic kernel batches;
- `emit_step_scoped` for isolated user-facing history.

P10 never inserts into `agent_steps`, updates a prior row, or keeps a private durable history.

P03 owns the complete await transaction. P10 passes parameters and returns the result; it does not recreate wait/event locking or mutate `run_waits`.

P06 owns catalog registration and compilation. P10 calls registration functions or reads the compiled table; it does not maintain a second host manifest.

P08 owns grant authorization. P10 does not inspect `cordis.grants` directly.

### Blocking gaps

- There is no importable host client outside test helpers.
- Existing `tests.conftest.psql` helpers are test-only and accept arbitrary SQL strings; they are not an SDK surface.
- No typed host API returns the live claim token and then fences subsequent host mutations.
- No host API fixes the provider-key formula independently of attempt/fingerprint.
- No host API calls all four P08 gates with explicit slices.
- No host-side boundary distinguishes an authorized host descriptor from an executable local callable.
- No host API has a defined behavior when P04 sleep is absent.
- Existing P05 Python orchestration still delegates the actual step to `cordis.step_once`.

### Reuse instead of duplication

P10 reuses:

- the P01 claim and transition predicates;
- P02 event validation, append ordering, and step-name logic;
- P03 atomic wait implementation;
- P05’s provider-key formula;
- P06 registration and catalog rows;
- P07/P08 live authorization;
- the existing `psql` binary and subprocess conventions;
- the existing test server/apply fixtures.

P10 does not duplicate:

- stale claim reaping;
- lease token generation;
- log sequence allocation;
- checkpoint validation;
- event first-write-wins behavior;
- P08 binding/grant checks;
- P09 queue-handler resolution or outcome mapping;
- P04 SQL from backup;
- apply/bootstrap logic.

---

## Design

### Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | **The first host language is Python 3.12.** | It is the only in-repository language/runtime, already used by uv, pytest, pgembed, and existing host-like proofs. D8 cites a small Python SDK as the desired shape. | Add Node/TypeScript, Rust, or another toolchain; defer the language again. |
| 2 | **Transport is one synchronous `psql` subprocess per client method. No new driver dependency.** | `psql` is the proven libpq-backed transport in this repository. One process/statement gives an explicit transaction boundary and no connection/session affinity. | Add psycopg/asyncpg; reuse test helpers in production; modify pgembed; support two transports in v1. |
| 3 | **P10 adds no numbered SQL.** Provider-key canonicalization is a host client method that asks PostgreSQL to evaluate the existing expression `md5(run_id || '/' || step_name)`. | Every durable P10 verb already exists except optional P04 sleep. A SQL wrapper would duplicate P01/P02/P08, churn the marker, and still not make P05 call the new helper. D4 says the SDK is not kernel. | Add `0022` with wrapper verbs; add a host-tool executor SQL function; add a provider-key function that P05 does not consume. |
| 4 | **Sleep is a typed, presence-gated method.** Before each call, resolve exactly `cordis.sleep_claim(uuid,text,timestamptz,integer)`. Missing → `CordisFeatureUnavailable` with no mutation. Present → invoke it normally. | P04 is ready as a plan but absent from the product tree. Runtime lookup allows P04 to land later without a P10 code change and never imports WIP SQL. | Depend on `.p19-backup`; silently omit sleep; make P04 a hard dependency; emulate SLEEPING from Python. |
| 5 | **Deliver a verb client plus pytest host process, not a host worker loop.** | The skeleton’s completion bar is one claim and one log write. A loop requires handler routing, LLM transport, outcomes, cancellation, and retry policy that belong to later plans. | Add `host_worker_step`, a daemon, a callback registry, or copy P09’s state machine. |
| 6 | **The acceptance path uses an injected deterministic fixture response and appends the event from Python. It performs no HTTP and does not call P05 `invoke_llm` or `step_once`.** | This proves host ownership of the step while keeping HTTP/provider adapters out of P10. Provider-key parity is tested separately against P05’s guard. | Reuse `step_once` and prove only in-db execution; add a mock HTTP server and prematurely define provider transport. |
| 7 | **The module lives in top-level package `pg_cordis_host`.** `__init__.py` re-exports a small public API; `client.py` owns all implementation. | The repository root is on pytest’s import path. This works under `package = false`, avoids turning `tools/` into a package, and needs no pyproject packaging change. | Put production code in `tests/` or `tools/`; add `src/` path manipulation; publish a package now. |
| 8 | **P10 is runtime-independent of P09 and adds no file-number coordination.** It never calls P09 functions. Its commit excludes every P09 path. | The plans are parallel. P09’s worker is in-db-only and withholds its token. No P10 SQL means P09 presence changes only the baseline marker used by existing tests. | Wrap `worker_step`; reuse `invoke_in_db_tool`; absorb uncommitted `0021`; require P09 at runtime. |
| 9 | **Host worker IDs use `host:<service>:<uuidhex>`.** `service` matches `[a-z][a-z0-9_-]{0,63}`; UUID is lowercase 32-hex and is generated once per host process/client identity. | The ID is observable, non-secret metadata; a fresh process identity avoids pretending restart continuity. Tokens remain authoritative. | Use PID/backend PID as authority; place hostnames/secrets in the ID; use one global constant worker name. |
| 10 | **Default lease is 90 seconds and there is no background heartbeat.** Before a blocking operation, the caller renews and ensures lease ≥ operation timeout + 30 seconds; for longer operations the future caller renews at intervals no greater than `min(30s, lease/3)`. | Matches P01 defaults and F §8 while keeping P10 free of threads/timers. The P10 acceptance has no blocking HTTP and needs no heartbeat loop. | Start a hidden background thread; assume a 90-second lease covers arbitrary HTTP; renew after an operation. |
| 11 | **The initial host-tool surface is catalog lookup plus fresh authorization only.** `authorize_host_tool` accepts only host/host_tool/read_only/replayable/none with null entrypoint and returns metadata; no local function executes. | P08 authorizes but cannot authenticate a host callable. Refusing execution closes the v1 impersonation path without stealing P12/P14/P16. | Execute arbitrary identity-to-callback mappings; permit external/mutating tools without D2 recovery; treat a descriptor as code. |
| 12 | **No client method is model-facing by default.** The documentation includes an explicit control-plane denylist; only a future router may render an already authorized host-tool descriptor. | Same-role SQL is trusted control-plane. Exposing claim/log/grant/event functions as model tools would bypass P08 or let the model seize scheduler authority. | Auto-generate model tools from public methods or every catalog row. |
| 13 | **Each client call is an independent committed database statement.** Checkpoint must occur before yield; P10 does not add a composite transaction helper. | This matches the subprocess transport and leaves a recoverable crash window: committed checkpoint + RUNNING claim is reaped and resumed from log. Durable semantics already handle it. | Keep a persistent transaction across host work; add SQL transaction control; combine arbitrary callbacks into one DB transaction. |
| 14 | **The client has no descriptor, grant, fold, or claim cache.** Every authorization and catalog/fold read executes fresh SQL. | P08 explicitly forbids descriptor reuse across claims. Stateless subprocess calls naturally satisfy this. | Cache plugin rows or grants for process lifetime; reuse an authorization after revoke. |
| 15 | **Response loss is reconciled from database state, not by blind replay.** Mutating methods preserve boolean/result semantics; command timeout or dropped response leaves outcome unknown until `get_job`, `run_state`, or `llm_checkpoint` is consulted. | A database commit can precede response loss. Repeating claim/checkpoint/await blindly can duplicate work or hit unique constraints. | Assume subprocess failure means rollback; recover a lost claim token from an unfenced cache; retry every mutation automatically. |

No implementation design fork remains. The only reason Status is not yet `ready to implement` is the required plan-critique gate.

---

## Component 1 — Python package, data types, and transport

### Package layout

```text
pg_cordis_host/
├── __init__.py
└── client.py
```

`pg_cordis_host.__init__` re-exports only the documented public API. It contains no SQL templates or behavior.

`pg_cordis_host.client` uses only standard-library modules such as:

- `dataclasses`;
- `datetime`;
- `json`;
- `pathlib`;
- `re`;
- `secrets`/`uuid`;
- `subprocess`;
- `typing`.

It must not import `pgembed`, `tests.conftest`, `tools`, psycopg, or scratch code.

### Public client

Illustrative signature:

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
- no persistent process or socket;
- no context manager;
- no background task;
- no mutable claim registry;
- safe for concurrent calls because each call owns its subprocess and local data;
- stores DSN, worker ID, binary path, and default command timeout only;
- must not include DSN, claim tokens, request JSON, or SQL text in `repr`.

`dsn` must be nonblank. Production documentation recommends credential-free URI/conninfo plus libpq environment or `.pgpass`; a password embedded in a URI may be observable in the `psql` process arguments.

### Public data records

All records are frozen dataclasses. Nested JSON values are parsed into new Python objects and treated as read-only by the client.

| Type | Fields |
|---|---|
| `ClaimedJob` | full claimed P01 row fields, including `job_id`, `run_id`, `job_type`, `payload`, `status`, `priority`, `attempt`, `available_at`, `claim_token`, `claimed_by`, `claim_expires_at`, `result`, `error`, `created_at`, `completed_at` |
| `JobSnapshot` | same observable scheduler fields but no token value; includes `claim_present: bool` |
| `CheckpointEvent` | `run_id`, `kind`, `payload`, optional `step_name` |
| `AgentStep` | `run_id`, `seq`, `kind`, `payload`, `step_name`, `created_at` |
| `RunState` | `status`, `steps_used`, `answer`, `error` |
| `AwaitEventResult` | `accepted`, `should_suspend`, `payload`, `source_run_id`, `source_seq` |
| `NamedCorpusRef` | `grant_id`, `corpus_id`, `label` |
| `PluginCatalogEntry` | all P06 catalog columns, including source kind and optional SQL entrypoint |
| `AuthorizedHostTool` | normalized P08 descriptor fields and bindings; no executable callable |

Timestamps parse as timezone-aware `datetime`. UUIDs parse as `uuid.UUID`. `payload`, `result`, `error`, metadata, and descriptor fields remain JSON values.

### Worker identity

```text
new_host_worker_id(service: str, instance_id: UUID | None = None) -> str
```

Output:

```text
host:<service>:<uuidhex>
```

The optional UUID exists for deterministic tests only. `CordisHostClient` rejects worker IDs outside this convention.

### Error types

| Type | Purpose |
|---|---|
| `CordisHostError` | Base exception |
| `CordisInputError` | Invalid local scalar, UUID, timestamp, JSON, identity, worker ID, or timeout |
| `CordisSqlError` | Nonzero `psql` result; includes parsed SQLSTATE when available and bounded server output |
| `CordisProtocolError` | Successful command returned missing, extra, malformed, or semantically incompatible JSON |
| `CordisFeatureUnavailable` | Optional exact SQL surface, currently P04 sleep, is absent |
| `CordisCommandTimeout` | `psql` exceeded the configured command timeout |

Boolean-fenced kernel methods return `False` for lost claim exactly as SQL does; they do not convert that normal protocol result into an exception.

### Safe subprocess algorithm

Every public method delegates to one private JSON command runner:

1. Validate and normalize local inputs.
2. Serialize all dynamic arguments into one compact JSON object with:
   - UTF-8;
   - `allow_nan=false`;
   - no lossy default serializer;
   - rejection of NUL and unsupported Python objects.
3. Place that JSON in one internally generated dollar-quoted SQL data literal whose random delimiter is verified absent from the serialized value.
4. Combine the data literal with a **fixed, private query template**. No caller supplies SQL, identifiers, clauses, or function names.
5. Invoke:

   ```text
   psql <dsn> --no-psqlrc -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -q -t -A
   ```

   using `subprocess.run` with `shell=False`, SQL on stdin, captured stdout/stderr, and the method timeout.
6. Require zero exit status.
7. Require stdout to contain exactly one JSON document after surrounding whitespace is removed.
8. Parse and validate the operation-specific shape.
9. Return the typed result.

The client exposes no `execute`, `query`, SQL-fragment, identifier, or arbitrary-function method.

A random dollar quote is an internal data encoding mechanism, not a caller-programmable SQL surface. Tests must include quotes, backslashes, newlines, Unicode, dollar tags, and SQL-looking strings.

### SQL error propagation

`psql` verbose output is parsed for a five-character SQLSTATE. `CordisSqlError` preserves:

- SQLSTATE if recognized;
- return code;
- at most 4,000 characters of server output.

It does not preserve:

- the DSN;
- the dynamic JSON argument document;
- the full SQL query;
- claim tokens in a structured exception field.

The server’s P01/P03/P06/P08/P19 SQLSTATE and stable message fragments remain visible in the bounded output.

---

## Component 2 — Claim lifecycle

### Public interfaces

```text
claim_job(run_id: str | None, lease_seconds: int = 90) -> ClaimedJob | None
renew_claim(claim_token: UUID, extend_seconds: int = 90) -> bool
yield_claim(claim_token: UUID) -> bool
complete_claim(claim_token: UUID, result: JSON value | None = None) -> bool
fail_claim(claim_token: UUID, reason: JSON object) -> bool
get_job(run_id: str) -> JobSnapshot | None
```

`claim_job` supplies the client’s owned `worker_id` to P01.

A `None` run ID explicitly enables global P01 queue polling. P10 itself provides no global worker loop or job-type router; production callers must not globally poll unless they can safely route every job they might claim. The P10 acceptance and P11 alternating proof use a concrete run ID.

### Claim algorithm

1. Validate optional run ID and positive lease.
2. Call exactly one `cordis.claim_job`.
3. Zero rows → `None`.
4. One row → require:
   - `status='RUNNING'`;
   - non-null token;
   - `claimed_by == client.worker_id`;
   - future/parseable expiry.
5. More than one row or malformed fields → `CordisProtocolError`.
6. Return `ClaimedJob`.

The client does not call `release_stale` itself because `claim_job` owns that behavior.

### Transition contracts

- `renew_claim=False`: stop using the token.
- `yield_claim=False`: do not claim successful yield.
- `complete_claim=False`: inspect jobs/log state; do not update jobs directly.
- `fail_claim=False`: inspect jobs/log state; do not retry using the old token.
- No method uses `claimed_by` as a fencing key.
- No method retries a false transition.

`complete_claim` must be called only after a final event is durable. `fail_claim` must be called only after an error event is durable unless the caller is intentionally using P01’s job-level reason as the only terminal scheduler payload; the P10 acceptance does not exercise that exceptional form.

### Job inspection

`get_job` returns scheduler/reconciliation state without revealing `claim_token`. It reports only whether claim fields are present. A host that lost the response to `claim_job` cannot recover and appropriate an unknown token through this API; it waits for expiry/recovery.

---

## Component 3 — Log, step recovery, and provider key

### Public interfaces

```text
checkpoint(
    claim_token: UUID,
    events: Sequence[CheckpointEvent],
    extend_seconds: int = 90
) -> bool

emit_step_scoped(
    claim_token: UUID,
    run_id: str,
    slice_id: UUID,
    kind: str,
    payload: JSON object,
    step_name: str | None = None,
    corpus_ids: Sequence[str] = (),
    extend_seconds: int = 90
) -> bool

next_step_name(run_id: str) -> str
llm_checkpoint(run_id: str, step_name: str) -> AgentStep | None
run_state(run_id: str) -> RunState
provider_idempotency_key(run_id: str, step_name: str) -> str
```

### Generic checkpoint

`checkpoint` converts `CheckpointEvent` records to the existing P02 event-array shape. It does not locally recreate P02’s kind or cross-run validation; the database remains authoritative. It validates only that inputs can be represented as JSON and that `extend_seconds` is positive.

An empty event sequence is legal and retains P02’s lease-extension behavior.

`checkpoint` is a trusted kernel method. It is not an isolated model append and must not be used to smuggle a caller-chosen `p08_scope`.

### Scoped append

`emit_step_scoped` is the canonical P10 append for isolated user-facing history:

```text
host claim
    → explicit run_id + slice_id
    → live P08 run/corpus grants
    → immutable p08_scope
    → emit_step_claimed
```

The client:

- requires object payload;
- rejects a caller payload already containing `p08_scope`;
- serializes corpus IDs as a JSON array, then invokes P08’s existing text-array parameter;
- returns P08/P02’s boolean fence unchanged;
- performs no follow-up append after `False`.

The acceptance test uses `emit_step_scoped`, not raw checkpoint, so the P08 fold can observe the host event.

### Provider-key canonicalization

`provider_idempotency_key` validates:

- nonblank run ID;
- `step_name` matching `^s-[1-9][0-9]*$`.

It asks PostgreSQL to evaluate:

```text
md5(run_id || '/' || step_name)
```

and requires a lowercase 32-hex result.

This intentionally uses the server expression rather than a Python hash:

- it exactly matches P05’s guard;
- it avoids a server-encoding mismatch;
- it cannot accidentally include attempt, worker, claim token, model, fingerprint, or tool data.

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
              HTTP with Idempotency-Key
              emit scoped llm event
              execute tools under their own retry contract
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

If the process crashes between them:

- history is durable;
- jobs remains RUNNING until lease recovery;
- the next claim uses `llm_checkpoint` / `next_step_name`;
- it does not repeat the committed named event blindly.

Yield-before-checkpoint is invalid caller behavior.

---

## Component 4 — Await and optional sleep

### Await interface

```text
await_event(
    claim_token: UUID,
    run_id: str,
    event_scope_id: str,
    event_name: str,
    await_id: UUID,
    deadline: datetime | None = None,
    ui_metadata: JSON object = {},
    extend_seconds: int = 90
) -> AwaitEventResult
```

Requirements:

- deadline must be timezone-aware when present;
- metadata must be an object;
- scope/name must be nonblank;
- P03 remains authoritative for all deeper validation and locking.

Result handling:

| Result | Host behavior |
|---|---|
| `accepted=false` | Token was not accepted; stop using it |
| `accepted=true`, `should_suspend=false` | Event already existed; payload/source are available and the claim remains live |
| `accepted=true`, `should_suspend=true` | P03 committed `run/await`, `run_waits`, WAITING, and claim release; stop immediately |
| SQL error | No local fallback transition; inspect transaction outcome if response was lost |

`await_event` is a trusted worker verb, not a model tool. A future model action requesting an event wait must first be routed through an authorized catalog descriptor carrying the concrete `event` binding.

P10 does not wrap `emit_event`.

### Sleep interface

```text
sleep_claim(
    claim_token: UUID,
    run_id: str,
    until: datetime,
    extend_seconds: int = 90
) -> bool
```

Algorithm:

1. Validate aware, finite `until`, run ID, token, and positive extension.
2. Resolve exact signature:

   ```text
   cordis.sleep_claim(uuid,text,timestamptz,integer)
   ```

3. If missing, raise `CordisFeatureUnavailable("P04_SLEEP_UNAVAILABLE")`.
4. If present, call it once and return its boolean.
5. Do not cache function presence; an in-place P04 apply becomes visible on the next call.
6. Do not emulate sleep with `yield_claim`, direct jobs updates, or client timers.

The P10 baseline test proves absence is safe and leaves jobs/log state unchanged. Successful sleep semantics remain P04’s acceptance responsibility.

---

## Component 5 — P08 isolation and P06 catalog

### P08 interfaces

```text
recall_named_corpus(
    run_id: str,
    slice_id: UUID,
    corpus_id: str
) -> NamedCorpusRef | None

fold_slice_messages(
    run_id: str,
    slice_id: UUID,
    paradigm: str
) -> JSON object

read_run_env(
    run_id: str,
    slice_id: UUID,
    paradigm: str,
    key: str
) -> JSON value

authorize_host_tool(
    run_id: str,
    slice_id: UUID,
    identity: str,
    bindings: JSON object
) -> AuthorizedHostTool
```

Each method directly calls its P08 function for every invocation. No method:

- queries `grants` directly;
- substitutes a run-union scope;
- infers a default slice;
- caches live-grant results;
- retries an authorization after revoke;
- rewrites P08 errors.

`read_run_env` has a return type for future compatibility, but on the current tree the authorized path surfaces `55000 P08_ENV_WORKSPACE_UNAVAILABLE` as `CordisSqlError`.

### Host-tool authorization

Algorithm:

1. Validate run, slice, identity, and bindings object.
2. Call `authorize_tool_dispatch`.
3. Preserve P08 denial/errors.
4. Validate the successful descriptor:
   - returned identity exactly matches the requested normalized identity;
   - `locus='host'`;
   - `invocation='host_tool'`;
   - `entrypoint` is JSON null;
   - `effect_class='read_only'`;
   - `retry_class='replayable'`;
   - `reconciliation='none'`;
   - required descriptor fields and bindings are present.
5. Otherwise raise `CordisProtocolError`.
6. Return `AuthorizedHostTool`.
7. Execute nothing.

An in-db queue row such as `kernel.step_once`, an in-db `session_select` row,Reconnecting... 1/5<chatName="P10 host SQL seam deep plan"/>

# P10 — Host minimal SQL seam

Date: 2026-08-25  
Status: **draft (Phase 3; design complete, awaiting plan critique before `ready to implement`)**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P10  
Depends on: P05 and P06 implemented; consumes P01–P03, P07, P08, and P19; P04 is optional at runtime and is **not** an implementation dependency  
Parallel with: P09  
Contract: D8; one `cordis.jobs` queue and one P01 claim protocol across in-database and host loci  
Primary deliverables: `pg_cordis_host/__init__.py`, `pg_cordis_host/client.py`, `docs/host-sql-seam.md`, `tests/test_p10_host_sql_seam.py`  
Critique: `docs/reviews/2026-08-25-p10-plan-critique.md` — not yet present; create it and fold all P0/P1 findings before changing this status to `ready to implement`  
SQL marker: **none** — P10 adds no numbered SQL and leaves the baseline marker unchanged (`p21` when `0021_p09_in_db_worker.sql` is present; otherwise `p20`)  
PL/pgSQL dollar tag: **not applicable** — P10 adds no SQL function  

---

## Summary

P10 is a targeted, host-side addition rather than a kernel refactor. It adds a small, synchronous Python 3.12 client that invokes the existing `cordis` SQL verbs through the repository’s proven `psql` transport, with one subprocess and one committed database statement per method call. The client exposes claim lifecycle, log/checkpoint, wait, optional sleep, P08 isolation gates, and P06 catalog operations without introducing a second scheduler, a host worker loop, HTTP transport, plugin execution, or private persistence. Provider idempotency is canonicalized by a host method that asks PostgreSQL for the same `md5(run_id || '/' || step_name)` value enforced by P05. The acceptance proof is an actual Python host process that targets one run, claims its existing `cordis.jobs` row, derives `s-1` and the provider key, appends one claim-fenced P08-scoped log event, yields, and permits another client to reclaim the same row. Because all durable verbs already exist and P04 sleep is not shipped, P10 deliberately adds no numbered SQL, no schema marker, and no new dependency.

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
2. the host writes through P02/P08 claim-fenced append functions rather than directly inserting into `agent_steps`;
3. the host uses P08’s explicit `run_id + slice_id` gates;
4. the host derives the same provider key as P05, independent of worker identity, claim token, attempt, or request fingerprint;
5. ownership is released before another host process reclaims;
6. no host log, job state, descriptor cache, or plugin execution state is kept as a second source of truth.

### Explicit non-goals

P10 does **not**:

- add, replace, wrap, or overload any `cordis` SQL function;
- add `sql/0022_*.sql`, advance `get_schema_version()`, or retarget current-tree marker pins;
- depend on `.p19-backup/p04-wip/0004_p04_sleep_retry.sql` or copy any P04 WIP SQL into the product tree;
- require P04 to be present before the host client can be imported or used for non-sleep operations;
- call `cordis.worker_step`; that function owns in-database queue dispatch and does not return the live claim token;
- call or expose `cordis.invoke_in_db_tool` or `_resolve_in_db_queue_handler`;
- use `cordis.step_once` as the host entrypoint;
- call P05’s `invoke_llm` as if it were host HTTP;
- implement an autonomous worker loop, queue poller daemon, handler registry, action parser, or outcome state machine;
- execute more than one agent step automatically;
- perform HTTP, LLM provider calls, retries, streaming, or provider-specific request construction;
- define a host request-fingerprint format beyond P05’s already locked provider-key rule;
- execute host plugins, even read-only ones; P10 only registers, looks up, and authorizes their descriptors;
- implement file reads, workspace access, Git worktrees, `apply_edits`, or any other host filesystem effect;
- implement D2 `tool/call` / `tool/result` recovery or claim that host effects are exactly once;
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

P08 used W80–W88 and P09 used W90–W99. P10 continues at W100.

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

The parent skeleton (`docs/plans/2026-08-23-pg-cordis-development.md`, P10) requires:

- a thin host wrapper around claim, checkpoint, yield, sleep, await, and catalog lookup;
- the same provider idempotency-key rule as the in-database path;
- no thick SDK, DSH event compatibility, or UI;
- completion when a host process can claim and write back one step log;
- the first SDK language to be selected in P10.

D8 in `docs/decisions/2026-08-23-pending.md` locks option A plus the minimal plugin catalog:

- both worker loci speak the same SQL verbs;
- host code reads the same plugin metadata vocabulary;
- no TypeScript plugin runtime, DSH migration layer, or dynamic `node:vm`;
- durable behavior remains in PostgreSQL;
- the Absurd Python SDK is the thin-client existence proof, while DBOS’s large SDK is the anti-pattern.

The architecture snapshot reinforces:

- one `cordis.jobs` queue and one claim protocol;
- `agent_steps` remains the sole history source of truth;
- SDK/habitat code is outside the kernel;
- host workspace and coding plugins start after P10;
- P11, not P10, proves alternating in-database and host workers.

### Existing kernel verbs the client reuses

| Concern | Existing SQL identity | Current behavior | P10 use |
|---|---|---|---|
| Claim | `cordis.claim_job(text,text,integer)` | Reaps stale claims, then claims one eligible PENDING row using `FOR UPDATE SKIP LOCKED`; NULL run polls globally | Direct synchronous client method; returns the live token only to the claiming host |
| Renew | `cordis.renew_claim(uuid,integer)` | Extends a live claim; false if ownership is absent or expired | Explicit heartbeat method; no background heartbeat |
| Yield | `cordis.yield_claim(uuid)` | Returns RUNNING to PENDING and clears ownership | Explicit end-of-step transition |
| Complete | `cordis.complete_claim(uuid,jsonb)` | Sets DONE and clears ownership | Called only after a durable final event exists |
| Fail | `cordis.fail_claim(uuid,jsonb)` | Current P01 implementation sets ERROR; P04 may later revise retry behavior under the same identity | Client delegates and does not infer terminal versus retry behavior |
| Job reconciliation | direct read of `cordis.jobs` | Scheduler truth and current ownership metadata | Read-only `get_job`; deliberately omits the live token |
| Checkpoint | `cordis.checkpoint(uuid,jsonb,integer)` | Validates one event array, fences by the live claim, extends the lease, appends through `emit_step` | Generic trusted-worker batch append |
| Scoped append | `cordis.emit_step_scoped(uuid,text,uuid,text,jsonb,text,text[],integer)` | Validates the calling slice and live grants, attaches `p08_scope`, delegates to claimed append | Required for isolated user-facing history |
| Step naming | `cordis.next_step_name(text)` | Returns stable `s-N` based on committed log state | Host obtains the next logical step name |
| LLM recovery read | `cordis.llm_checkpoint(text,text)` | Returns the committed LLM row for one step if present | Host checks before a future HTTP call |
| Run projection | `cordis.run_state(text)` | Folds final/error/current LLM count from the log | Lost-response and terminal-state reconciliation |
| Await | `cordis.await_event(uuid,text,text,text,uuid,timestamptz,jsonb,integer)` | Immediate return if already emitted, otherwise atomically logs/registers wait, sets WAITING, clears claim | Trusted host worker method; not automatically model-facing |
| Sleep | `cordis.sleep_claim(uuid,text,timestamptz,integer)` | Defined only by the unshipped P04 plan/WIP | Presence-checked optional method |
| Catalog registration | `register_host_plugin(jsonb)` / `unregister_host_plugin(text)` | Persists host definitions and refreshes compiled catalog | Trusted control-plane methods |
| Catalog lookup | direct read of `cordis.plugin_catalog` | Compiled metadata; host rows have NULL SQL entrypoint | Trusted metadata inspection |
| Four-seam gates | recall/fold/env/tool authorization | Slice-bound live grants; common P08 readiness latch | Direct client methods with explicit run and slice IDs |

P10 does not copy validation or state transitions from these functions. The database remains responsible for token fencing, row locks, event lock order, log append constraints, and catalog validation.

### Provider idempotency

P05 enforces:

```text
provider_key = md5(run_id || '/' || step_name)
```

The key excludes:

- `claim_token`;
- `worker_id`;
- `jobs.attempt`;
- request fingerprint;
- model name;
- tool list;
- retry number.

P05’s `llm_checkpoint` and unique LLM step index provide the second half of A+B: a future host LLM caller must read the log before HTTP and must reuse the same provider key after reclaim.

P10 does not define a host LLM request or fingerprint ABI. Its provider method delegates the hash expression to PostgreSQL, so encoding and string concatenation match the database that enforces P05.

### P08 host constraints

P08 assigns P10 these responsibilities:

- pass explicit `run_id` and `slice_id`;
- call the four public gates rather than reading run-union grants;
- never expose issue-family or log-writer functions as model tools;
- reauthorize each host tool dispatch rather than caching descriptors;
- reject host impersonation: a descriptor authorized by P08 must still be verified as a host row before any host routing occurs.

P10 closes the host-impersonation problem only for its authorize-only scope:

1. it calls `authorize_tool_dispatch`;
2. it requires the returned identity to equal the requested identity;
3. it requires `locus='host'`, `invocation='host_tool'`, and JSON null `entrypoint`;
4. it limits this release to `read_only/replayable/none`;
5. it returns metadata and has no execution or handler-binding method.

Actual binding from identity to a local callable is deferred because P10 performs no host tool execution.

### P09 sibling boundary

P09 and P10 are parallel clients of the same P01 queue, not wrappers around each other.

P09:

- claims and executes cataloged in-database queue handlers;
- exposes `worker_step`, which never returns its claim token;
- executes only compatible in-database entrypoints;
- rejects host-locus rows;
- registers the legacy P05 body as `kernel.step_once`.

P10:

- calls P01 claim verbs directly;
- receives the claim token because it must make later SQL calls from a separate process;
- does not invoke `worker_step`, `enqueue_job`, `invoke_in_db_tool`, or `_resolve_in_db_queue_handler`;
- does not advertise `kernel.step_once` as a host or isolated tool;
- does not implement a generic queue loop that might steal an unsupported P09 job.

The P10 acceptance proof always targets a known `run_id`. Although the low-level claim method preserves P01’s explicit `run_id=None` polling behavior, P10 provides no global routing loop; callers must not poll globally unless they can safely route every claimed `job_type`.

### Current host-side stack

The repository already uses:

- Python 3.12;
- uv with `[tool.uv] package = false`;
- `pgembed` only as the runtime dependency;
- pytest as the development dependency;
- `psql` subprocesses for all SQL execution;
- `PsqlSession` for explicit test transactions;
- no psycopg/asyncpg driver;
- no installable Python package.

`tests/test_p05_one_step_driver.py` currently acts as a stand-in host orchestrator:

```text
Python → claim_job → step_once → Python outcome CASE → P01 transition
```

That does not prove a host-executed step: the step body still runs in PostgreSQL. P10 replaces the ad hoc SQL-subprocess calls with a reusable host client and proves that the Python process itself constructs and submits the checkpoint event.

`scratch/yield_walkthrough/run.py` is prior research only. Its psycopg2 dependency, pg-agent imports, SQL objects, queue loop, and TEMP mock are not reused.

### SQL-tree and coordination state

P10 adds no numbered SQL, so source numbering does not create a P09 dependency:

- if P09 is present, the tree remains `0021` / `p21`;
- if P09 is absent, the tree remains `0020` / `p20`;
- no P10-specific marker exists;
- no PL/pgSQL dollar tag exists;
- no existing current-tree pin changes.

Before implementation, the working tree must still be cleanly separated:

- either land P09 first;
- or implement P10 in a clean worktree based on a branch without the uncommitted P09 ship set.

P10 must never commit P09’s SQL, tests, plan changes, or review artifacts as part of its own ship set.

---

## Current-state analysis

### Current ownership and mutation points

The relevant state owners are:

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

The host package owns no durable state. Its only long-lived object is immutable connection configuration and a non-secret worker ID.

### Existing control flow before P10

```text
pytest helper
  → subprocess psql
  → claim_job
  → subprocess psql
  → step_once                -- body is still in database
  → Python maps returned text
  → subprocess psql
  → yield_claim / complete_claim / fail_claim
```

Gaps:

- there is no importable host client;
- each test builds SQL strings independently;
- there is no fixed public host API or error model;
- no host method derives and locks the provider-key rule;
- no host path wraps all P08 gates;
- no host-side distinction exists between trusted catalog lookup and authorized model dispatch;
- no typed sleep degradation exists while P04 is absent;
- the tests do not prove host construction of a claim-fenced step event.

### Transformation boundaries

The new end-to-end boundary is:

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

P10 reuses:

- P01 lease checks and transitions;
- P02 event validation, append order, and step naming;
- P03 wait atomicity and event lock order;
- P05 provider-key formula and skip-if-present read;
- P06 metadata validation and compiled catalog;
- P07 live grants;
- P08 readiness latch and exact target authorization;
- the existing `psql` transport pattern;
- the existing pgembed and pytest fixtures.

P10 does not duplicate:

- claim SQL;
- jobs state transition predicates;
- log append SQL;
- P03 wait registration;
- P04 sleep implementation;
- plugin metadata validation;
- grant parsing;
- P08 descriptor construction;
- P09 worker outcome mapping;
- the apply command or server bootstrap.

---

## Design

### Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | **The first host language is Python 3.12.** | Python, uv, pgembed, and pytest are the only in-repo host toolchain; D8 cites a small Python SDK as the desired shape. | Add TypeScript/Rust/Go tooling; reuse DSH TypeScript; leave the language open. |
| 2 | **The transport is synchronous `psql` subprocess execution using only the Python standard library.** Each method launches one `psql`, executes one fixed statement, and exits. | This is the proven repository transport, requires no dependency or pgembed change, and naturally commits each verb before the next host call. | Add psycopg/asyncpg; alter pgembed; support two transports; use shell commands or an ORM. |
| 3 | **P10 adds no numbered SQL.** Provider canonicalization is a Python client method that asks PostgreSQL to evaluate the exact P05 expression. | Durable verbs already exist; P08 already provides authorization; a new wrapper function would duplicate rather than unify P05 unless P05 were also replaced. Avoiding SQL preserves P10 as habitat rather than kernel and eliminates marker churn. | Add `0022` solely to wrap existing verbs; add a host-tool executor; replace P05 to call a new helper; implement Python-local MD5 as the sole authority. |
| 4 | **Sleep is a typed optional method with a fresh runtime presence check.** If the exact P04 signature is absent, raise `CordisFeatureUnavailable` before mutation. If present, call it directly. | P04 is ready as a plan but not shipped; backup WIP is explicitly non-product. Presence checking lets P10 land independently and automatically consume P04 later. | Require P04 first; copy WIP SQL; silently emulate sleep with yield; omit sleep from the API; cache absence for the client lifetime. |
| 5 | **The deliverable is a verb client plus a pytest host-process proof, not a host loop.** | P10’s completion bar is one claim and one log write; P11 owns alternating workers and later plans own real host tools. | Add `host_worker_step`, a polling daemon, action parsing, callback routing, or P09-like outcome mapping. |
| 6 | **The acceptance test performs no HTTP and does not call P05 `invoke_llm` as transport.** It creates a deterministic test event in Python, stores the database-derived provider key, and checkpoints it. | P05’s hook is an in-database mock, not host HTTP. A mock server or HTTP library would expand P10 beyond the required seam. | Treat `invoke_llm` as host HTTP; add an HTTP server/client; omit provider-key proof. |
| 7 | **The importable module lives in top-level package `pg_cordis_host`.** | Repo-root pytest can import it without package installation or `sys.path` changes; `tools/` remains non-package; no pyproject packaging change is needed. | Put code in `tools/`; use `src/` plus path manipulation; place production client in tests; publish a wheel now. |
| 8 | **P09 is a sibling boundary, not an API dependency.** P10 neither calls nor exposes P09 functions. No SQL means P10’s implementation is source-order independent, but its commit must be isolated from P09’s uncommitted ship set. | Both loci share P01, while P09 is specifically in-database dispatch. | Wrap `worker_step`; use `enqueue_job` as the host producer ABI; absorb `0021` into P10; wait for P09 semantically. |
| 9 | **Host worker IDs use `host:<service>:<instance-uuid-hex>`.** The service matches `[a-z][a-z0-9_-]{0,63}`; the UUID is lowercase 32-character UUID4 hex and is stable for one client/process lifetime. | `claimed_by` is observational, while the token is authoritative. The convention gives P11 distinct, legible locus identities without exposing hostname or PID. | Use only PID/backend PID; reuse one global `host`; place secrets in worker ID; treat worker ID as authority. |
| 10 | **Default lease remains 90 seconds; P10 adds no heartbeat thread.** Before a blocking external operation, callers must renew and ensure lease ≥ operation timeout + 30 seconds; for long work they renew at intervals no greater than `min(30 seconds, lease/3)`. A false renew means cancel/discard and append nothing. | P01 defaults to 90; F requires heartbeat during LLM and warns against lease shorter than HTTP timeout. P10 has no external operation requiring automation. | Hidden background threads; infinite leases; renew after the result; append after a false heartbeat. |
| 11 | **The P10 tool surface is catalog lookup plus authorization only.** `authorize_host_tool` accepts only host, host-tool, read-only/replayable/none descriptors with NULL SQL entrypoint; it returns metadata and never invokes a callable. | The skeleton permits read-only first; P08 authorizes but does not execute; P12/P14/P16 own host effects and recovery. | Execute registered Python callables; allow external/idempotent tools; map SQL entrypoints to host functions. |
| 12 | **The client has no generic raw-SQL public method.** All dynamic values travel in one JSON envelope embedded as a safely delimited SQL data literal into fixed internal templates; `shell=False` is mandatory. | A generic query API would bypass P08 and make control-plane exposure trivial. Standard input avoids placing claim tokens or payloads in command arguments. | Public `execute(sql)`; string interpolation per scalar; `shell=True`; pass claim tokens through command-line variables. |
| 13 | **Each method is one independently committed statement.** `checkpoint` must commit before `yield`; a crash between them leaves a durable checkpoint and a RUNNING row that stale recovery can reclaim. | This matches the existing subprocess model and log-based recovery. The database functions already make their internal multi-row changes atomic. | Keep a psql backend pinned across the run; combine a whole host step into a private transaction manager; yield before checkpoint. |
| 14 | **Database denials propagate as typed host SQL errors; boolean fencing remains boolean.** False claim transitions are not rewritten into success or generic exceptions. | Existing SQL deliberately distinguishes validation exceptions from lost-claim booleans. | Catch all errors and return false; infer SQLSTATE from message text only; issue unfenced fallback updates. |
| 15 | **No implementation fork remains.** The only pre-code gate is the required plan critique; there are no unresolved architecture or API decisions. | Open Questions 1–8 and the additional worker/lease/tool decisions are closed above. | Retain design choices for the implementer. |

---

## Component 1 — Python package, transport, and error model

### Package layout

```text
pg_cordis_host/
  __init__.py
  client.py
```

`pg_cordis_host/__init__.py` reexports only the supported public API. It contains no behavior, connection setup, or import-time database access.

`pg_cordis_host/client.py` contains:

- JSON type aliases;
- result dataclasses;
- exception classes;
- `new_host_worker_id`;
- `CordisHostClient`;
- private validation, serialization, response parsing, and SQL-template helpers.

The package must not import:

- `pgembed`;
- `tests.conftest`;
- `tools.apply_pg_cordis`;
- psycopg/asyncpg;
- HTTP libraries;
- workspace or plugin implementation modules.

### Public construction

Illustrative interface shape:

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
- no persistent child process;
- no database connection pool;
- no active-claim collection;
- safe for concurrent method calls because configuration is immutable and every call has its own subprocess;
- never includes the DSN, claim token, SQL body, or argument envelope in `repr`.

`new_host_worker_id(service, instance_id=None)` returns the exact convention from decision 9. Supplying `instance_id` exists for deterministic tests; production defaults to UUID4.

### Public result types

All are frozen dataclasses. Parsed nested JSON is owned by the returned object and treated as read-only by the client.

| Type | Fields |
|---|---|
| `ClaimedJob` | `job_id`, `run_id`, `job_type`, `payload`, `priority`, `attempt`, `available_at`, `claim_token`, `claimed_by`, `claim_expires_at`, `created_at` |
| `JobSnapshot` | same non-secret scheduler fields plus `status`, `claim_present`, `completed_at`, `result`, `error`; no claim token |
| `CheckpointEvent` | `run_id`, `kind`, `payload`, optional `step_name` |
| `AgentStep` | `run_id`, `seq`, `kind`, `payload`, optional `step_name`, `created_at` |
| `RunState` | `status`, `steps_used`, optional `answer`, optional `error` |
| `AwaitEventResult` | `accepted`, `should_suspend`, optional `payload`, optional `source_run_id`, optional `source_seq` |
| `NamedCorpusRef` | `grant_id`, `corpus_id`, `label` |
| `PluginCatalogEntry` | all P06 compiled fields, including `source_kind` and optional `entrypoint` |
| `AuthorizedHostTool` | normalized requested identity, bindings, effect/retry/reconciliation, required grants, lifecycle/config metadata, and the raw P08 descriptor |

Timestamp fields are timezone-aware `datetime`; UUID fields are `uuid.UUID`; JSON remains standard Python JSON values.

### Error hierarchy

| Type | Meaning |
|---|---|
| `CordisHostError` | Base class |
| `CordisInputError` | Local validation or JSON serialization failed before starting psql |
| `CordisCommandTimeout` | The psql child exceeded the configured command timeout |
| `CordisSqlError` | psql exited nonzero; includes parsed SQLSTATE when available and bounded server output |
| `CordisProtocolError` | A successful command returned missing, extra, malformed, or contract-incompatible JSON |
| `CordisFeatureUnavailable` | Optional exact SQL capability is not installed, currently P04 sleep only |

The client does not translate P08/P19 denial codes into a second policy hierarchy. They remain `CordisSqlError` with the server SQLSTATE and stable message fragment.

### Transport algorithm

For every public method:

1. Validate Python scalar and collection shapes.
2. Serialize all dynamic inputs into one compact JSON document using UTF-8, `allow_nan=false`, and no lossy string conversion.
3. Reject NUL characters and an argument envelope larger than the documented client limit. Set the limit to **8 MiB** for P10; larger host checkpoints require a later transport plan rather than an unbounded subprocess command.
4. Generate a random dollar-quote delimiter not present in the serialized JSON.
5. Place that one JSON data literal into a method-specific fixed SQL template. No caller-provided SQL identifier, expression, function name, or clause is interpolated.
6. Run `psql` with:
   - exact configured executable;
   - configured DSN;
   - `--no-psqlrc`;
   - `ON_ERROR_STOP=1`;
   - quiet, tuples-only, unaligned output;
   - verbose error reporting;
   - `shell=False`.
7. Send the statement on standard input. Claim tokens and event payloads must not be command-line arguments.
8. Require exit code zero.
9. Require exactly one non-empty JSON response document on standard output.
10. Parse and validate the method-specific response shape.
11. Return the typed result.

Notices on standard error with exit code zero do not invalidate a response. Nonzero exits retain at most 4 KiB of combined output in the exception and parse the first verbose five-character SQLSTATE if present.

---

## Component 2 — Claim and scheduler lifecycle

### Public methods

```text
claim_job(run_id: str | None, lease_seconds: int = 90)
    -> ClaimedJob | None

renew_claim(claim_token: UUID, extend_seconds: int = 90)
    -> bool

yield_claim(claim_token: UUID)
    -> bool

complete_claim(claim_token: UUID, result: JsonValue | None = None)
    -> bool

fail_claim(claim_token: UUID, reason: Mapping[str, JsonValue])
    -> bool

get_job(run_id: str)
    -> JobSnapshot | None
```

All are synchronous and can raise transport, SQL, or protocol errors.

### Claim behavior

`claim_job` delegates exactly once to `cordis.claim_job(run_id, worker_id, lease)`.

- No rows → `None`.
- More than one row → `CordisProtocolError`.
- One row must have:
  - `status='RUNNING'`;
  - non-null claim token;
  - `claimed_by` equal to the client’s worker ID;
  - future `claim_expires_at`;
  - requested run ID when non-null.
- The token is returned only in `ClaimedJob`.

`run_id=None` intentionally preserves P01 queue polling, but P10 provides no handler router. The documentation must mark global polling as an advanced trusted-scheduler operation. The P10 proof and P11 targeted alternation use explicit run IDs.

### Transition behavior

Renew/yield/complete/fail return the existing SQL boolean unchanged:

- `true` means the database accepted the token-fenced mutation;
- `false` means the caller no longer owns a live matching claim;
- after false, the caller must stop using the token and append nothing;
- no fallback `UPDATE` or automatic reclaim occurs.

`complete_claim` is valid only after the host has durably appended a `final` event. `fail_claim` is valid only after an `error` event or when the caller intentionally delegates a scheduler-level failure reason. P10 does not enforce event presence because P01 does not; real host drivers must follow this ordering.

P04 may later change `fail_claim` from always-terminal to retry-or-terminal under the same signature. The client must return only the boolean and instruct callers to inspect `get_job` instead of assuming ERROR.

### Reconciliation read

`get_job` uses a fixed read query and never returns `claim_token`. It exposes:

- current scheduler status;
- whether a claim exists;
- `claimed_by` and expiry;
- attempt and availability;
- terminal result/error.

If a claim response is lost, the caller cannot recover the token through this API. It waits for expiry/recovery rather than assuming ownership.

---

## Component 3 — Log, scoped append, and provider idempotency

### Public methods

```text
checkpoint(
    claim_token: UUID,
    events: Sequence[CheckpointEvent],
    extend_seconds: int = 90
) -> bool

emit_step_scoped(
    claim_token: UUID,
    run_id: str,
    slice_id: UUID,
    kind: str,
    payload: Mapping[str, JsonValue],
    *,
    step_name: str | None = None,
    corpus_ids: Sequence[str] = (),
    extend_seconds: int = 90
) -> bool

next_step_name(run_id: str) -> str

llm_checkpoint(run_id: str, step_name: str)
    -> AgentStep | None

run_state(run_id: str)
    -> RunState

provider_idempotency_key(run_id: str, step_name: str)
    -> str
```

### Generic checkpoint

`checkpoint` serializes events into P02’s existing array shape:

```text
{
  run_id,
  kind,
  payload,
  step_name? 
}
```

It does not directly call `emit_step` or `emit_step_claimed`.

An empty event list is legal because P02 treats it as a claim-fenced lease extension. Callers should normally use `renew_claim` for a heartbeat; P10 preserves the underlying checkpoint capability rather than forbidding it.

A false result means no events committed.

### Scoped append

User-facing isolated history must use `emit_step_scoped`:

1. pass explicit run and slice IDs;
2. pass only a JSON object payload;
3. pass exact named corpus IDs used to construct the observation;
4. let P08 validate `run` and named-corpus grants;
5. return the claimed append boolean unchanged.

The client must reject a caller payload containing top-level `p08_scope`; the database also owns that field. It must not create scope envelopes locally.

P10 does not provide a multi-event scoped batch because no such kernel function exists. Adding one belongs in a later numbered SQL plan if it becomes necessary.

### Step and recovery reads

`next_step_name` requires a nonblank run ID and validates the returned `s-N` format.

`llm_checkpoint` requires `s-N` and accepts zero or one row. More than one is a protocol error even though the P02 unique index should prevent it.

A future host LLM flow must use:

```text
next_step_name
    → llm_checkpoint
        → existing row: validate/reuse; do not call provider
        → absent: derive provider key, renew claim, call provider, append llm row
```

P10 implements only the reads and key derivation, not request reconstruction or HTTP.

### Provider-key canonicalization

`provider_idempotency_key` validates the same nonblank run and `s-N` step format, then asks the connected PostgreSQL server to return:

```text
md5(run_id || '/' || step_name)
```

Contract:

- exactly 32 lowercase hexadecimal characters;
- deterministic for the same run/step;
- unchanged across worker IDs, claim tokens, attempts, or retries;
- no attempt/fingerprint parameters exist in the API.

Using PostgreSQL instead of Python’s local MD5 avoids encoding drift and directly locks the host behavior to P05’s database expression without adding a new kernel function.

---

## Component 4 — Await and optional sleep

### `await_event`

```text
await_event(
    claim_token: UUID,
    run_id: str,
    event_scope_id: str,
    event_name: str,
    await_id: UUID,
    *,
    deadline: datetime | None = None,
    ui_metadata: Mapping[str, JsonValue] = {},
    extend_seconds: int = 90
) -> AwaitEventResult
```

The implementation calls the exact P03 function once.

Result handling:

| Result | Host behavior |
|---|---|
| `accepted=false` | Treat as lost claim; stop using the token |
| `accepted=true`, `should_suspend=false` | Event already exists; claim remains live; use payload/source pointer and continue |
| `accepted=true`, `should_suspend=true` | P03 has committed `run/await`, `run_waits`, WAITING, and claim release; discard token and return from the host step |
| malformed combinations | `CordisProtocolError` |

The method is a trusted worker primitive, not a model tool. A model-directed event wait must eventually be represented by an authorized catalog operation with an exact `event` binding before trusted host code calls this method.

P10 does not expose `emit_event`. Tests may use it as trusted fixture setup through the shared `psql` helper.

### `sleep_claim`

```text
sleep_claim(
    claim_token: UUID,
    run_id: str,
    until: datetime,
    extend_seconds: int = 90
) -> bool
```

Algorithm:

1. Validate an aware, finite timestamp.
2. Query `to_regprocedure` for the exact identity:
   `cordis.sleep_claim(uuid,text,timestamptz,integer)`.
3. Do not cache the result.
4. If absent, raise `CordisFeatureUnavailable` with stable code `P10_SLEEP_UNAVAILABLE`; no scheduler or log mutation occurs.
5. If present, call it once and return its boolean unchanged.

This method must not:

- query `.p19-backup`;
- emulate sleep by yielding;
- insert `run/sleep`;
- update jobs directly;
- assume how P04 later claims due sleepers.

The P10 baseline test proves the absent path. P04’s implementation tests own the successful scheduler semantics; once P04 ships, P10 requires only a small compatibility assertion that the exact method delegates successfully.

---

## Component 5 — P08 gates and P06 catalog

### Four-seam methods

```text
recall_named_corpus(run_id, slice_id, corpus_id)
    -> NamedCorpusRef | None

fold_slice_messages(run_id, slice_id, paradigm)
    -> Mapping[str, JsonValue]

read_run_env(run_id, slice_id, paradigm, key)
    -> JsonValue

authorize_host_tool(run_id, slice_id, identity, bindings)
    -> AuthorizedHostTool
```

All call the existing P08 public functions directly. No grant result is cached.

Current behavior:

- unauthorized/unknown valid recall target → `None`;
- fold returns one JSON object;
- authorized env currently raises `55000 P08_ENV_WORKSPACE_UNAVAILABLE`;
- tool authorization returns a descriptor but executes nothing.

`read_run_env` retains a future successful return type but currently propagates the P08 unavailable error.

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

The method returns metadata only. There is deliberately no:

- callable argument;
- Python handler registry;
- module import path;
- dynamic import;
- `execute_host_tool`;
- callback invocation;
- result checkpointing.

### Catalog methods

```text
register_host_plugin(definition: Mapping[str, JsonValue]) -> str

unregister_host_plugin(identity: str) -> bool

get_plugin(identity: str) -> PluginCatalogEntry | None
```

Registration and unregistration are trusted control-plane operations. They are never model-facing. `register_host_plugin` delegates all metadata validation and refresh behavior to P06.

`get_plugin` is a trusted raw catalog lookup and may return any locus/invocation. Model routing must use `authorize_host_tool`, not `get_plugin`.

### Explicit non-model-tool boundary

No `CordisHostClient` method is automatically rendered as a model tool. In particular, the following identities and method families must never be placed in a model action schema by P10:

- P01 claim, renew, yield, complete, fail, and stale-release verbs;
- P02 `emit_step`, `emit_step_claimed`, `emit_step_scoped`, and `checkpoint`;
- P06 register/unregister/refresh functions;
- P07 register/create/issue/approve/deny/revoke functions;
- P08 readiness and internal fold helpers;
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
       ├─ exists → validate stored request fingerprint in future driver
       │           skip HTTP
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
       ├─ event already emitted
       │    → payload returned
       │    → claim remains RUNNING
       ├─ not emitted
       │    → run/await + run_waits + jobs WAITING
       │    → token cleared
       │    → host stops
       └─ claim rejected
            → accepted=false
            → host stops
```

### Optional sleep

```text
host asks to sleep
  → exact signature presence check
       ├─ absent → CordisFeatureUnavailable; state unchanged
       └─ present → sleep_claim(...)
                    → P04 owns log + SLEEPING + release
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

Recovery by operation:

| Lost response | Required reconciliation |
|---|---|
| Claim | `get_job`; never assume ownership because the token may be unknown; wait for lease recovery |
| Renew | Inspect job expiry; if uncertain, stop external work |
| Checkpoint/scoped append | Read `llm_checkpoint`, fold, or agent log by known run/step before replay |
| Yield | `get_job`; PENDING means transition committed, RUNNING may still be the old claim |
| Complete/fail | `get_job` and `run_state` |
| Await | Inspect jobs status, `run_state`, and P03 side tables through trusted diagnostics |
| Register/unregister plugin | `get_plugin` and source definition state |

The client never retries mutating commands automatically.

---

## API and persistence impact

### New Python interfaces

Public inventory exported by `pg_cordis_host`:

- `CordisHostClient`
- `new_host_worker_id`
- `ClaimedJob`
- `JobSnapshot`
- `CheckpointEvent`
- `AgentStep`
- `RunState`
- `AwaitEventResult`
- `NamedCorpusRef`
- `PluginCatalogEntry`
- `AuthorizedHostTool`
- `CordisHostError`
- `CordisInputError`
- `CordisCommandTimeout`
- `CordisSqlError`
- `CordisProtocolError`
- `CordisFeatureUnavailable`

No public generic SQL runner, transaction object, HTTP client, worker loop, plugin callable registry, or raw descriptor executor is exported.

### Existing SQL interfaces

No SQL signature changes.

P10 calls these identities as-is:

- P01 claim lifecycle;
- P02 checkpoint/read state;
- P03 await;
- optional P04 sleep;
- P06 host registration and catalog table;
- P08 scoped append and four public gates.

No SQL COMMENT is added, so the P06 catalog gains no P10 entry.

### Existing Python call sites

There are no production call sites. New tests import the package directly. P11 is the first planned downstream consumer.

Existing test helpers remain unchanged and continue to own server setup and SQL fixture preparation. The package itself does not import them.

### Persistence

P10 adds no schema, migration, table, column, index, function, type, COMMENT, or schema version.

Calls through the client may mutate existing state:

- claims and transitions mutate `cordis.jobs`;
- checkpoint/scoped append writes `agent_steps` through existing functions;
- await mutates P03 tables and jobs;
- optional sleep mutates jobs/log through P04;
- host registration mutates `host_plugin_definitions` and compiled `plugin_catalog`.

The client stores none of this outside PostgreSQL.

### Backward compatibility

The change is additive:

- existing SQL consumers are unaffected;
- the apply tree and marker are unchanged;
- pyproject dependencies and package mode are unchanged;
- P09 behavior and tests are unaffected;
- deleting the Python package does not make an applied database unreadable.

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
| Global claim | Host lacks a router for returned `job_type` | Caller must yield/fail according to trusted policy; P10 documentation discourages global polling |
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
| Env | Authorized but no workspace | Preserve `55000 P08_ENV_WORKSPACE_UNAVAILABLE` |
| Tool authorize | P08 grant denial | Preserve P08 SQL error |
| Tool authorize | In-db, queue, external, transactional, or non-replayable descriptor | `CordisProtocolError`; no execution |
| Catalog lookup | Unknown identity | `None` |
| Register | Existing identity | P06 upsert/refresh semantics |
| Unregister | Missing identity | `false` |
| Descriptor/catalog change | Changed after one call | Next call rereads; no cache |
| Client object deleted with live token | No automatic yield; lease expiry/recovery owns cleanup |
| Explicit outer transaction needed | Unsupported by this client; use existing test-only `psql_session` or a future transport plan |

Boundary conditions:

- empty event arrays;
- JSON null payload members;
- strings containing quotes, backslashes, Unicode, newlines, dollar signs, or SQL-looking text;
- first claim, reclaimed claim, and stale attempt;
- `deadline=None`;
- empty corpus list for scoped events;
- revoked grant between two gate calls;
- plugin unregistered after lookup but before authorization;
- psql warnings with a valid JSON result;
- P04 installed while a client instance remains alive;
- current source tree ending at either p20 or p21.

---

## File-by-file impact

| File | Change | Why | Ordering |
|---|---|---|---|
| `docs/plans/P10-host-sql-seam-2026-08-25.md` | Replace scaffold with this deep plan; after critique, fold findings and set `ready to implement` | AGENTS plan-before-code gate | First |
| `docs/reviews/2026-08-25-p10-plan-critique.md` | **Create before implementation.** Record plan critique and closure of all P0/P1 findings | Required before ready status | Before production files |
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
| `sql/0021_p09_in_db_worker.sql`, `tests/test_p09_in_db_worker.py`, P09 review artifacts | **No P10 changes and never included in the P10 commit** | P09 is a sibling ship set | Must be committed separately or isolated in another worktree |
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
- env reaches the existing P08 unavailable error;
- host authorization accepts one read-only host row;
- host authorization rejects in-db queue/session rows and host external/transactional rows;
- a revoke between two calls denies the second call;
- no descriptor cache or host callable execution exists.

### W105 — Host one-step acceptance

Use the real `CordisHostClient` against a database applied with the existing source tree.

Required sequence:

1. Through trusted test setup, create:
   - one PENDING jobs row;
   - one slice for the same run;
   - a live `run` grant for that slice.
2. Create client A with worker ID `host:p10proof:<uuid-a>`.
3. Claim the exact run.
4. Read `s-1`.
5. Confirm `llm_checkpoint` is absent.
6. Derive the provider key.
7. Construct one deterministic test-only `llm` payload in Python containing:
   - protocol `cordis.p10.host.proof.v1`;
   - provider key;
   - model `host-mock`;
   - a fixed raw response object.
8. Append it through `emit_step_scoped`.
9. Fold the same slice and assert the event is present.
10. Fold another slice without access and assert it is absent or denied according to P08 setup.
11. Yield.
12. Create client B with a distinct worker ID and reclaim the same job.
13. Assert same job ID, new token, claimed-by client B.
14. Cleanly yield or otherwise release the fixture claim.

The proof must not call `step_once`, `worker_step`, `invoke_llm`, or a host plugin callable.

### W106 — Documentation and source boundaries

Document:

- exact public API;
- one psql process/transaction per method;
- checkpoint-before-transition ordering;
- targeted claims as the P10 default usage;
- global poll routing hazard;
- worker ID convention;
- lease/heartbeat rule;
- unknown-outcome reconciliation;
- no private log/cache;
- provider-key versus fingerprint distinction;
- optional sleep behavior;
- P08 gate requirements;
- trusted catalog lookup versus authorized host descriptor;
- no-execution boundary;
- explicit model-tool denylist;
- P09 sibling separation;
- no packaging/dependency/SQL changes.

### W107 — Required named tests

Create `tests/test_p10_host_sql_seam.py` with these named tests:

| Test | Required proof |
|---|---|
| `test_p10_public_api_inventory_and_no_new_sql_marker` | Exact exported names; no P10 numbered SQL; existing schema marker remains the baseline marker; no overload/catalog additions |
| `test_p10_worker_id_format_and_client_validation` | Exact host ID grammar, deterministic test UUID support, invalid inputs fail before psql |
| `test_p10_psql_transport_errors_and_output_validation` | Missing binary, timeout, nonzero exit/SQLSTATE, malformed/multiple output, and secret-redacted exception behavior |
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
| `test_p10_four_seam_calls_are_slice_bound_and_not_cached` | Two slices/corpora; recall/fold do not union; env error preserved; revoke affects next authorization |
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

### W108 — Regression and delivery gate

Focused test:

```bash
uv run pytest tests/test_p10_host_sql_seam.py -q
```

Cross-protocol suite on the expected post-P09 tree:

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

If implementation occurs on a clean pre-P09 branch, omit only the nonexistent `tests/test_p09_in_db_worker.py` from the second command. P10 behavior and files do not otherwise change, and the marker remains `p20` rather than `p21`.

---

## Tradeoffs

1. **`psql` subprocess instead of psycopg.** This avoids a dependency and matches the repository, but adds process startup latency and lacks a persistent transaction/session API.
2. **No numbered SQL.** This keeps SDK concerns out of the kernel and avoids marker churn, but the provider expression remains locked by tests rather than a new shared SQL function called by P05.
3. **Database-derived provider key.** It guarantees P05 encoding parity, but costs one database round trip before a future host HTTP request.
4. **No worker loop.** The seam is small and testable, but applications must add routing and orchestration in later plans.
5. **One transaction per verb.** Claims and checkpoints survive host-process changes, but checkpoint and yield are not one atomic client transaction. A crash between them relies on stale recovery and log replay.
6. **No background heartbeat.** There are no hidden threads or lifecycle leaks, but future blocking operations must explicitly renew.
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

### P09 working-tree contamination

P09 is currently a parallel uncommitted ship set in the supplied working tree.

Mitigation: commit P09 first or use a clean worktree; stage explicit P10 paths only; inspect both working-tree diff and upstream commit range before Oracle review/push.

### Rollback

P10 creates no database object or migration.

Rollback consists of:

- stop host processes;
- remove/revert `pg_cordis_host`, its documentation, and P10 tests in a later source commit;
- unregister any runtime host plugin definitions created by an application if they are no longer wanted.

Existing jobs, log rows, waits, grants, and host definitions created through the client remain valid kernel data. Removing the client does not rewrite them.

---

## Implementation order

1. Create `docs/reviews/2026-08-25-p10-plan-critique.md` through the required plan-review process.
2. Fold every P0/P1 finding into this plan. If no material decision changes remain, update the header status to `ready to implement`.
3. Ensure the implementation workspace contains only one coherent baseline:
   - P09 committed separately, or
   - a clean P10 worktree without P09’s uncommitted ship set.
4. Create `pg_cordis_host/__init__.py` and `client.py` with W100 only: public inventory, types, errors, worker ID, and private transport.
5. Add transport-focused unit tests before scheduler methods.
6. Add W101 claim lifecycle and reconciliation methods; run the P01/P10 focused tests.
7. Add W102 checkpoint, scoped append, step reads, run state, and provider-key method; run P02/P05/P08/P10 tests.
8. Add W103 await and optional sleep; run P03/P10 tests.
9. Add W104 P06 catalog and P08 gate methods; run P06/P07/P08/P10 tests.
10. Add the W105 end-to-end host process proof.
11. Write `docs/host-sql-seam.md` with the exact operational and security contract.
12. Complete all W107 named tests, including source/dependency boundaries.
13. Run the focused P10 module.
14. Run the cross-protocol suite.
15. Run the full suite on a clean tree.
16. Inspect the complete diff:
    - no SQL changes;
    - no dependency changes;
    - no tools/conftest changes;
    - no P09 ship-set files;
    - no scratch/backup files;
    - only the P10 package, documentation, tests, plan, and review artifacts.
17. Follow the `AGENTS.md` implementation Oracle loop:
    - produce the P10-only diff artifact;
    - select implementation, this plan, contracts, and relevant SQL/docs;
    - request review with P10 completion criteria;
    - record every verdict in `docs/reviews/2026-08-25-p10-implementation-oracle.md`;
    - fix all P0/P1 findings and re-review in the same chat;
    - rerun tests after behavioral changes.
18. After the latest Oracle review has no open P0/P1, stage only the P10 ship set, commit with an English P10 message, verify the upstream range, and immediately push.
19. Do not state that P10 is complete until the push succeeds.

Steps 4–12 must land together in the final commit. There is no independently releasable partial client without its contract and acceptance tests.

---

## Open questions

No P10 implementation decisions remain open. The status is draft only because the required plan critique has not yet been performed.

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
- `sql/0003_p03_wait_event.sql` — atomic await and WAITING transition
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


> 💡 Continue this plan conversation with ask_oracle(chat_id: "p10-host-sql-seam-deep-p-8DDC72", new_chat: false)