## Final Prompt
<taskname="P11 alternating-claim deep plan"/>

<task>
Write the complete, implementation-ready deep plan for pg_cordis **P11 — dual-worker alternating claim proof**, replacing the lightweight scaffold `docs/plans/P11-alternating-claim-2026-08-25.md` with a full specification an implementing agent can execute with zero prior conversation context. This is zcordis-pgembed; product is `pg_cordis`, SQL namespace is schema `cordis`. Plan only — do not implement, do not edit `sql/` or `tests/` in this pass.

P11 proves skeleton proof 1 on one `cordis.jobs` row: an in-database worker and a host process alternate claims on the same coding run (in-db step → host step → in-db step, or the reverse), and a stale lease is taken over by the other locus. Done when an automated pytest for that proof is green. No functional plugins, no host worker loop, no second queue.

Build on the scaffold's curated `## Background` (seams, file:line refs, prior art) rather than re-deriving it — its findings are accurate; verify line refs only where a decision hinges on them.
</task>

<hard_constraints>
- Do not reopen D1–D9 or architecture snapshot §4 (both locked; snapshot included in full).
- No CREATE EXTENSION; do not lift `scratch/` to ABI; no second queue; no host worker loop; do not call `cordis.worker_step` from the host client; P11 uses **targeted run IDs** (P10 forbids unattended global polling).
- Reuse `tests/conftest.py` fixtures (`run_apply`, `psql`, `psql_session`, session `pgdata`); do not invent a second apply/start-Postgres stack. Host client (`pg_cordis_host/`) and `cordis.worker_step` already exist — P11 wires them together in a test, it does not build new runtime.
- P04 sleep is unshipped (only `.p19-backup/p04-wip/`); `client.sleep_claim` raises `CordisFeatureUnavailable` — the plan must not depend on it.
- Subsequent Px append higher-numbered SQL files only. Default: P11 ships **no numbered SQL**, keeps marker `p21`, does not retarget `tests/test_p00_sql_source.py` (same stance as P10) — unless the plan demonstrates a real kernel gap.
- Follow AGENTS.md (included): Status must be "ready to implement" after critique fold; include Do/Don't lists; name exact tests and pytest commands (shape: `uv run pytest tests/test_p11_*.py -q`).
- Match P10's deep-plan heading shape (P10 plan included in full — use it as the exemplar): Summary, Goal, Explicit non-goals, Contract, Status, Architecture (invariants, state/data ownership, concurrency), Deliverables, Work items with Verify (W11x numbering), Risks, File inventory, Implementation order, Outstanding concerns, References. Additionally give every work item an **execution index**: Goal, Done when, Key files, Dependencies, Size.
</hard_constraints>

<decisions_required>
Resolve each scaffold `## Open Questions` with an explicit decision plus rejected alternatives, grounded in the included code (cite file:line):
1. Tests-only vs numbered SQL (default tests-only unless a concrete kernel gap is shown).
2. What counts as an in-db "step": (A) `cordis.worker_step` on a `kernel.step_once` enqueue, (B) custom yield-only queue handler, (C) raw `claim_job` via psql without `worker_step`. Skeleton says a coding run — leans (A).
3. What counts as a host "step": (A) P10 verbs claim + `next_step_name`/`provider_idempotency_key` + `emit_step_scoped` + yield on the same run, (B) claim + yield only. Host must NOT use `cordis.step_once` as entrypoint (P10 rule).
4. Whether the P09 three-step mock must *complete* across loci vs proving claim ownership + `claimed_by` flipping + log writes from both loci. Decide explicitly so tests don't over-couple to P05 folding (`next_step_name` semantics are in the P02 slice).
5. Lease-steal in both directions. Host→in-db is natural (host holds a live token in Python; backdate `claim_expires_at`, `release_stale`, in-db takes over). In-db→host cannot ride a completed `worker_step` (atomic from Python; no live token survives) — pick a named mechanism: raw in-db `claim_job` left RUNNING then expired, or the `lost_claim` leftover path (job stays RUNNING with dead token).
6. Job setup: P09 `_enqueue` (queue handler + paradigm) vs P10 trusted INSERT. A `worker_step`-driven step requires a registered handler; a host-only insert has none.
</decisions_required>

<architecture>
- `cordis.jobs` (P01): `UNIQUE (run_id)` — one queue row per run for its lifetime; steps live in `cordis.agent_steps`. RUNNING requires claim_token + claimed_by + claim_expires_at; non-RUNNING requires all three null.
- `cordis.claim_job(p_run_id, p_worker_id, p_lease_seconds DEFAULT 90)`: `release_stale` first, then `FOR UPDATE SKIP LOCKED` on one PENDING row (`available_at <= now`, optional run_id filter); stamps fresh token, `claimed_by = p_worker_id`, lease. No "must differ from previous owner" check. `yield_claim` returns to PENDING with fields cleared. `release_stale` reaps expired RUNNING rows → PENDING, `attempt += 1`.
- In-db locus (P09, marker p21): `cordis.worker_step(p_worker_id, p_run_id DEFAULT NULL, p_lease_seconds DEFAULT 90)` → `(job_id, run_id, outcome ∈ idle|yield|wait|complete|fail|lost_claim)`. One call = one claim + one handler invoke + one P01/P03 transition; does not expose the live claim_token (why hosts can't use it). Handler resolution is catalog-based; `cordis.step_once` is registered directly as `kernel.step_once` via COMMENT metadata.
- `cordis.step_once` (P05): the mock three-step conversation — llm/s-1 → tool/s-1 → llm/s-2 → tool/s-2 → llm/s-3 → final/s-3 — advanced one event pair per invocation, appending through P02 claim-fenced log verbs.
- `cordis.emit_step_claimed` (P02): rechecks claim_token + run_id + RUNNING + unexpired lease, **extends** `claim_expires_at`, then appends; returns false on dead token. `cordis.emit_step_scoped` (P08) wraps it behind P07 slice+run grant checks and `p08_scope` stamping. `cordis.next_step_name` derives s-N from the llm log.
- Host locus (P10): `pg_cordis_host/client.py` `CordisHostClient(dsn, worker_id, *, psql_path, command_timeout_seconds)` — synchronous psql subprocess, no DB driver imports. Worker id `host:<service>:<32-hex>`. Verbs: claim_job, renew_claim, yield_claim, complete_claim, fail_claim, get_job, checkpoint, emit_step_scoped, next_step_name, llm_checkpoint, run_state, provider_idempotency_key, await_event, sleep_claim (raises until P04), catalog/authorize helpers.
</architecture>

<selected_context>
- docs/plans/P11-alternating-claim-2026-08-25.md — the scaffold being replaced (full): Goal, curated Background with file:line refs, Open Questions, References. Your output document replaces this file's content.
- docs/plans/P10-host-sql-seam-2026-08-25.md — full deep plan: the heading-shape exemplar, host-seam contract, mid-flow locks, "targeted run IDs" rule, acceptance-test patterns (`test_p10_host_process_claims_and_appends_one_scoped_step`, `test_p10_two_clients_share_p01_claim_fencing`).
- docs/plans/P09-in-db-worker-2026-08-25.md — full deep plan: `worker_step` ABI, outcome mapping, `enqueue_job`/handler registration, P09 proof test shape.
- docs/plans/2026-08-23-pg-cordis-development.md — roadmap skeleton (Chinese): P11 entry (lines ~239-245), five-proof table (~54-58).
- docs/analysis/2026-08-23-i-architecture-snapshot.md — locked architecture; §4 D1–D9 (D8 host seam), §7 must-prove #1.
- sql/0001_p01_claim.sql — jobs DDL, claim invariant checks, `claim_job`/`yield_claim`/`release_stale`/renew (full).
- sql/0021_p09_in_db_worker.sql — `enqueue_job`, handler resolver, `worker_step`, outcome transitions (full).
- sql/0005_p05_one_step_driver.sql — `step_once` mock driver + step/event semantics (full).
- sql/0002_p02_log.sql (slices) — `emit_step_claimed` (72-156), `next_step_name` (279-343).
- sql/0020_p08_four_seam_enforcement.sql (slice) — `_require_isolation_feature` + `emit_step_scoped` (120-243): why the host step needs a P07 grant before appending.
- pg_cordis_host/client.py — full host client implementation (verb signatures, error taxonomy, worker-id format, psql invocation).
- tests/conftest.py — `run_apply`, `psql`, `psql_session`, session `pgdata` fixtures (full).
- tests/test_p09_in_db_worker.py — full: helpers `_reset`/`_enqueue`/`_step`, P09 proof `test_p09_single_worker_yields_reclaims_and_completes_mock_run` (650-679), `lost_claim` transition test.
- tests/test_p10_host_sql_seam.py — full: `_client`/`_insert_job`/`_slice`/`_issue` helpers, P10 acceptance + two-client fencing tests.
- tests/test_p01_claim.py — full: claim/fencing semantics, `test_stale_reap_and_auto_claim` (338-401).
- tests/test_p00_sql_source.py (slice 78-113) — p21 marker + apply file-list pin; stays untouched if no SQL ships.
- sql/README.md — append-only numbered-file rules and apply command contract.
- AGENTS.md — repo agent rules: plan-before-edit, Do/Don't, named tests/commands, critique/oracle flow.
</selected_context>

<relationships>
- In-db step: `worker_step(worker-id, run_id)` → `claim_job` → handler `kernel.step_once` → P02 `emit_step_claimed` appends under the claim → P01/P03 transition (`yield`→PENDING, `complete`→DONE, `lost_claim`→stays RUNNING).
- Host step: `CordisHostClient.claim_job(run_id)` holds token in Python → P07 grant → `next_step_name` → `emit_step_scoped` (→ `emit_step_claimed`, extends lease) → `yield_claim` → row PENDING for the other locus.
- Alternation hinges on `yield_claim`/`release_stale` returning the single `UNIQUE (run_id)` row to PENDING so either locus's next claim wins; `claimed_by` observably flips between an in-db worker_id (any non-blank text, e.g. 'worker-a') and a `host:<service>:<32-hex>` id.
- Lease steal: expired RUNNING row → `release_stale` inside the next `claim_job` (either side) → new owner; `attempt` increments.
- Tests reuse conftest fixtures; P09 helpers drive psql, P10 helpers build clients against `server.get_uri(db)` + `POSTGRES_BIN_PATH / "psql"`.
</relationships>

<not_included>
Exists in repo but deliberately not selected: `docs/plans/P0{1,2,5,8}*` and P19 plan docs (their shipped SQL/tests that matter are included), `docs/decisions/2026-08-23-pending.md` (D1–D9 locked — snapshot §4 included instead), `docs/host-sql-seam.md` (P10's user-facing verb doc; client.py + P10 plan cover it), `tests/test_p05_one_step_driver.py` (mock flow quoted in P09 plan), `docs/reviews/*` (P09/P10 plan critiques — their folds are already inside the P09/P10 plans), `.p19-backup/p04-wip/` (NOT product SQL — P04 unshipped), `scratch/yield_walkthrough/` (not ABI), `tools/apply_pg_cordis.py` (apply mechanics; README covers the contract). Do not treat any of these as available context; the selection is the universe.
</not_included>

<ambiguities>
None blocking — the scaffold's Background is current and the six Open Questions are the genuine decision points the plan must close. Factual notes the plan should carry: (a) `worker_step` never returns a live token, so in-db→host steal needs the raw-`claim_job`-left-RUNNING or `lost_claim`-leftover mechanism; (b) SQL does not enforce the host worker-id regex in-db, so `claimed_by` distinguishes loci only observationally; (c) if the host emits an llm event via `emit_step_scoped` mid-mock, P05 folding on the next `worker_step` depends on `next_step_name`'s llm/tool pairing — decide Q4 before naming assertions.
</ambiguities>

## Selection
- Files: 18 total (15 full, 3 slice)
- Total tokens: 107655 (Auto view)
- Token breakdown: full 105293, slice 2362
- Token accounting: incomplete from active_tab_published; refresh pending; incomplete: files

### Files
### Selected Files
zcordis-pgembed/
├── docs/
│   ├── analysis/
│   │   └── 2026-08-23-i-architecture-snapshot.md — 3,610 tokens (full)
│   └── plans/
│       ├── 2026-08-23-pg-cordis-development.md — 4,379 tokens (full)
│       ├── P09-in-db-worker-2026-08-25.md — 20,703 tokens (full)
│       ├── P10-host-sql-seam-2026-08-25.md — 23,033 tokens (full)
│       └── P11-alternating-claim-2026-08-25.md — 0 tokens (full)
├── pg_cordis_host/
│   └── client.py — 10,691 tokens (full)
├── sql/
│   ├── 0001_p01_claim.sql — 2,118 tokens (full)
│   ├── 0002_p02_log.sql — 1,092 tokens (lines 72-156 (emit_step_claimed: claim-fenced append + lease extension), 279-343 (next_step_name: s-N computation from agent_steps llm events))
│   ├── 0005_p05_one_step_driver.sql — 6,070 tokens (full)
│   ├── 0020_p08_four_seam_enforcement.sql — 966 tokens (lines 120-243 (emit_step_scoped: P07 grant-gated, lease-fenced scoped append))
│   ├── 0021_p09_in_db_worker.sql — 4,837 tokens (full)
│   └── README.md — 2,649 tokens (full)
├── tests/
│   ├── conftest.py — 1,253 tokens (full)
│   ├── test_p00_sql_source.py — 304 tokens (lines 78-113 (p21 marker pin and apply file-list assertion))
│   ├── test_p01_claim.py — 5,733 tokens (full)
│   ├── test_p09_in_db_worker.py — 10,786 tokens (full)
│   └── test_p10_host_sql_seam.py — 7,200 tokens (full)
└── AGENTS.md — 2,231 tokens (full)


---

## Generated Plan

## Chat Send ✅
- **Chat**: `p11-alternating-claim-de-B0FC36` | **Mode**: plan

### Response


# P11 — Dual-worker alternating claim proof

Date: 2026-08-25  
Status: **ready to implement**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P11  
Depends on: P09 (`f6b3d70`) and P10 (`7911644`), both on `main`  
Contract: skeleton proof 1; one `cordis.jobs` queue, one P01 claim protocol, two execution loci  
Primary deliverable: `tests/test_p11_alternating_claim.py`  
SQL marker: **none** — P11 adds no numbered SQL; the current product marker remains **`p21`**  
Plan critique gate: `docs/reviews/2026-08-25-p11-plan-critique.md` must exist with no open P0/P1 before test implementation begins  
Implementation review gate: `docs/reviews/2026-08-25-p11-implementation-oracle.md`  
Involvement: Mid-flow decisions and all six scaffold questions are folded into this specification

> The supplied planning context does not include a P11 plan-critique artifact. Per `AGENTS.md`, the implementing agent must verify or create that artifact before editing tests. If critique changes any behavior below, fold it into this plan and retain `ready to implement` only after all P0/P1 findings are closed.

---

## Summary

P11 is a targeted, tests-only integration proof, not a kernel or host-client refactor. One P09-enqueued `kernel.step_once` coding run is advanced by an actual `cordis.worker_step`, claimed by a real `CordisHostClient` for a scoped host checkpoint and yield, then advanced by `worker_step` again. The same `cordis.jobs` row is subsequently used to prove stale-lease takeover in both directions: host-owned lease to in-database identity, then in-database-owned lease to host identity. The acceptance test asserts one stable `job_id`, fresh claim tokens, exact `claimed_by` flips, `attempt` increments only on stale release, claim-fenced log writes from both loci, and final cleanup back to `PENDING`. The host writes a scoped `run/yield` proof checkpoint rather than an `llm` event so it does not corrupt P05’s `llm`/`tool` pairing or force P11 to complete the three-step mock. Existing P01, P02, P07–P10 interfaces already cover the complete behavior, so no numbered SQL, runtime API, marker update, host loop, or plugin is added.

---

## Goal

Prove skeleton proof 1 on one `cordis.jobs` row:

```text
P09 enqueue of one kernel.step_once coding run
  → in-db worker_step: claim + P05 s-1 step + yield
  → host client: claim + derive s-2/provider key
                + scoped host checkpoint + yield
  → in-db worker_step: claim + P05 s-2 step + yield
  → host live lease expires
  → same in-db identity takes over
  → in-db live lease expires
  → same host identity takes over
  → final cleanup leaves the same row PENDING
```

The proof is complete when the automated P11 pytest establishes:

1. only one `cordis.jobs` row exists for the run throughout;
2. every claim and transition targets the explicit run ID;
3. both real in-database steps execute through `cordis.worker_step`;
4. the host step uses only existing P10 methods and receives the live P01 token;
5. the host emits one P08-scoped durable event before yielding;
6. the in-database and host loci alternate ownership of the same `job_id`;
7. stale leases are taken over in both directions;
8. each takeover creates a new claim token and fences the previous token;
9. `claimed_by` visibly flips between the exact in-database and host worker IDs at the live-claim boundaries;
10. stale release increments `jobs.attempt` exactly once per expired lease;
11. the run is deliberately not completed or failed by P11;
12. no runtime or SQL surface is added.

### Do

- Use `cordis.enqueue_job` with handler `kernel.step_once`, paradigm `codeact`, and a local deterministic P05 mock payload.
- Use one explicit in-database worker identity and one explicit host worker identity throughout the proof.
- Use `cordis.worker_step(in_db_worker_id, run_id, lease)` for both in-database coding steps.
- Use `CordisHostClient.claim_job(run_id)` for the host coding-proof step and host takeover.
- Use `next_step_name`, `llm_checkpoint`, `provider_idempotency_key`, `emit_step_scoped`, and `yield_claim` for the host step.
- Give the host checkpoint a P07 slice with a live `run` grant.
- Use the same `job_id` and run for the alternation and both stale-takeover directions.
- Create expired leases deterministically by backdating only `claim_expires_at` in the disposable test database.
- Let the next targeted `claim_job` perform automatic stale release; assert the resulting `attempt`.
- Reuse `run_apply`, `psql`, the session-scoped `pgdata` fixture, `get_server`, and the embedded `psql` binary.
- Run the P11 focused, cross-protocol, and full regression suites before implementation review.

---

## Explicit non-goals

P11 does **not**:

- add `sql/0022_*.sql` or any other numbered SQL file;
- modify historical numbered SQL;
- advance `cordis.get_schema_version()` beyond `p21`;
- retarget `tests/test_p00_sql_source.py`;
- add or modify a PostgreSQL table, column, function, type, index, COMMENT, catalog row, trigger, role, or grant;
- add a Python runtime method or modify `pg_cordis_host/`;
- call `cordis.worker_step` from `CordisHostClient`;
- add a host `worker_step`, host worker loop, poller, daemon, handler registry, or scheduler;
- use global `claim_job(NULL, ...)` or `worker_step(..., NULL, ...)`;
- create a second queue or a replacement jobs row;
- use `cordis.step_once` as a host entrypoint;
- have the host call P05 `invoke_llm`;
- register a new queue handler, host plugin, or functional plugin;
- use a custom yield-only queue handler as the P11 coding proof;
- treat a raw P01 claim as one of the required coding steps;
- complete the P09 three-step mock across loci;
- claim that the host proof event is an external LLM call or external-provider idempotency proof;
- append a host `llm` checkpoint that P05 would later interpret as its own current step;
- rely on P04, `sleep_claim`, wall-clock sleeping, retry, or dead-letter behavior;
- import or copy `.p19-backup/p04-wip/`;
- import or copy `scratch/yield_walkthrough/`;
- add `CREATE EXTENSION`, transaction-control SQL, another apply command, or another PostgreSQL fixture stack;
- interpret `claimed_by` as authority; the claim token remains authoritative;
- claim that SQL authenticates a worker locus from the formatting of `claimed_by`;
- prove D2 host effects, D5 cross-project isolation, D9 spawn, file mutation, or host plugin execution.

---

## Contract

### Canonical worker identities

The acceptance test uses exactly two stable observational identities:

- in-database worker: a nonblank fixed string such as `in-db:p11:worker-a`;
- host worker: one deterministic `new_host_worker_id("p11proof", fixed_uuid)` value matching `host:<service>:<32-hex>`.

The same two values are reused in the alternating-step and stale-takeover phases. This demonstrates two worker loci rather than relying on a succession of unrelated worker identities.

The identity strings are observational only:

- P01 records them in `jobs.claimed_by`;
- P01 does not enforce a locus grammar;
- P10 locally enforces the host format;
- possession of the live `claim_token`, not equality of `claimed_by`, authorizes transitions.

### Canonical job setup

The test creates the job through:

```text
cordis.enqueue_job(
    run_id,
    'kernel.step_once',
    'codeact',
    deterministic P05 mock payload,
    priority 0
)
```

This is required because `worker_step` resolves `jobs.job_type` through the P06 catalog and revalidates `payload.paradigm` (`sql/0021_p09_in_db_worker.sql`). A trusted P10-style direct `INSERT` would not establish the P09 handler/paradigm contract.

The payload is local to `tests/test_p11_alternating_claim.py` and contains the same logical three-step mock shape used by the P09 acceptance:

```text
s-1 → mock.observe → yield
s-2 → mock.observe → yield
s-3 → final("ok")  → complete
```

P11 executes only the first two P05 steps. The fixture must include `s-3` so it remains a valid canonical P05 coding payload, but P11 does not invoke it.

The P11-local payload is intentional test-fixture duplication. `PROOF_PAYLOAD` in `tests/test_p09_in_db_worker.py` is a private module constant, not a shared fixture contract; importing one test module from another or refactoring existing P09 tests into shared support would broaden P11 unnecessarily.

### Canonical host step

After the first in-database step has produced `llm/s-1` and `tool/s-1`, the host performs:

1. targeted `claim_job(run_id)`;
2. assert the returned `job_id` matches the enqueue result;
3. assert `claimed_by` equals the canonical host worker ID;
4. `next_step_name(run_id)` → `s-2`;
5. `llm_checkpoint(run_id, "s-2")` → `None`;
6. `provider_idempotency_key(run_id, "s-2")` → 32 lowercase hexadecimal characters;
7. `emit_step_scoped(...)` with:
   - `kind = "run/yield"`;
   - SQL `step_name = NULL`;
   - no corpus IDs;
   - a payload shaped as:

     ```text
     {
       protocol: "cordis.p11.alternating_claim.v1",
       locus: "host",
       worker_id: <canonical host worker ID>,
       action: "checkpoint_then_yield",
       logical_step_name: "s-2",
       provider_key: <database-derived key>
     }
     ```

   - no caller-provided `p08_scope`; P08 adds it;
8. assert `next_step_name(run_id)` is still `s-2`;
9. `yield_claim(token)` → `True`.

`run/yield` is selected deliberately:

- P02 permits it without a named step (`sql/0002_p02_log.sql:72-156`);
- P08 can scope and claim-fence it (`sql/0020_p08_four_seam_enforcement.sql:145-243`);
- it is a durable host checkpoint before ownership release;
- it does not create an incomplete `llm/s-2` row;
- it does not change P02’s `next_step_name` calculation, which only advances from paired `llm` history (`sql/0002_p02_log.sql:279-343`);
- it avoids fabricating a P05 request fingerprint or pretending the host called P05’s mock provider.

The P09 rule that `worker_step` does not emit `run/yield` remains unchanged; P11’s event is explicitly emitted by the host step.

### Canonical alternation assertions

After enqueue:

| Phase | Claim path | Expected durable result |
|---|---|---|
| In-db step 1 | targeted `worker_step` | outcome `yield`; row `PENDING`; P05 appends `llm/s-1`, `tool/s-1` |
| Host step | targeted P10 methods | scoped `run/yield` proof event; row `PENDING` after yield |
| In-db step 2 | targeted `worker_step` | outcome `yield`; row `PENDING`; P05 appends `llm/s-2`, `tool/s-2` |

The run’s relevant log order must be exactly:

```text
llm/s-1
tool/s-1
run/yield/NULL       -- P11 host event with p08_scope
llm/s-2
tool/s-2
```

After the second in-database step:

- `next_step_name(run_id) = "s-3"`;
- no `final` event exists;
- no `error` event exists;
- `jobs.status = 'PENDING'`;
- `jobs.attempt = 1`;
- all claim fields are null.

P11 does not assert the full P09 `yield, yield, complete` outcome sequence. P09 already owns that proof. Completing it across loci would require the host to mimic P05’s `llm`/`tool` protocol and would couple P11 to P05 checkpoint fingerprint reconstruction rather than the dual-claim contract.

### Canonical stale-takeover assertions

Stale takeover uses the same row after the alternating steps.

#### Host → in-database

1. The canonical host client claims the targeted run.
2. Assert:
   - same `job_id`;
   - `attempt = 1`;
   - `claimed_by = host_worker_id`;
   - status `RUNNING`.
3. A targeted raw `cordis.claim_job(run_id, in_db_worker_id, lease)` returns no row while the host lease is live.
4. Trusted fixture SQL backdates that exact token’s `claim_expires_at`.
5. A second targeted raw `cordis.claim_job(run_id, in_db_worker_id, lease)`:
   - automatically invokes `release_stale`;
   - reclaims the same `job_id`;
   - returns `attempt = 2`;
   - records `claimed_by = in_db_worker_id`;
   - returns a fresh token.
6. The old host token is fenced: `host_client.yield_claim(old_host_token) = False`.
7. Yield the new in-database token through the existing P01 verb, returning the row to `PENDING`.

#### In-database → host

1. A targeted raw `cordis.claim_job(run_id, in_db_worker_id, lease)` creates a committed, live in-database-owned claim:
   - same `job_id`;
   - `attempt = 2`;
   - `claimed_by = in_db_worker_id`.
2. The canonical host client’s targeted `claim_job(run_id)` returns `None` while that lease is live.
3. Trusted fixture SQL backdates the exact in-database token’s lease.
4. The canonical host client’s next targeted `claim_job(run_id)`:
   - automatically reaps the stale claim;
   - reclaims the same `job_id`;
   - returns `attempt = 3`;
   - records `claimed_by = host_worker_id`;
   - returns a fresh token.
5. The old in-database token is fenced: `cordis.yield_claim(old_db_token) = false`.
6. The host yields the new token and returns the row to `PENDING`.

The raw in-database claims are stale-lease staging and takeover primitives only. They do not count as either required coding step. `worker_step` cannot hold a committed live token across Python calls because its claim, handler invocation, and transition are one statement and it never returns the token (`sql/0021_p09_in_db_worker.sql`; P09 worker ABI).

### Final one-row invariant

At test completion:

- exactly one `cordis.jobs` row exists for the run;
- its `job_id` equals the enqueue result and every subsequent claim result;
- status is `PENDING`;
- `attempt = 3`;
- `claim_token`, `claimed_by`, and `claim_expires_at` are null;
- `result`, `error`, and `completed_at` are null;
- the P11/P05 five-event sequence remains intact;
- no replacement job or second queue row was created.

---

## Status

### Skeleton and architecture status

P11 closes proof 1 from `docs/plans/2026-08-23-pg-cordis-development.md:54-58,239-245` and must-prove item 1 from `docs/analysis/2026-08-23-i-architecture-snapshot.md:198`.

The following are already implemented and are dependencies rather than P11 deliverables:

- P09 in-database worker and `kernel.step_once`;
- P10 synchronous host SQL seam;
- P01 stale release and token fencing;
- P02 claimed/scoped append and step naming;
- P07 slice/run grants;
- P08 scoped append;
- marker `p21`.

### Plan-critique gate

This specification resolves every open design question from the P11 scaffold. Before tests are edited, `docs/reviews/2026-08-25-p11-plan-critique.md` must be created or verified and all P0/P1 findings folded here. If the critique changes the event kind, test topology, stale mechanism, or file inventory, update this plan first.

### Implementation gate

After implementation:

1. focused, cross-protocol, and full suites must pass;
2. an Oracle implementation review must have no open P0/P1;
3. the review verdict must be recorded;
4. the P11-only ship set must be committed and pushed immediately.

P11 must not be described as complete before the push succeeds.

---

## Current-state analysis

### Existing responsibilities and ownership

| State or behavior | Current owner | Relevant mutation/read path |
|---|---|---|
| One scheduler row per run | `cordis.jobs` | `UNIQUE (run_id)` in `sql/0001_p01_claim.sql:3-22` |
| Claim capability | `jobs.claim_token` | generated by `cordis.claim_job`; consumed by fenced transitions |
| Observational owner identity | `jobs.claimed_by` | set from `p_worker_id`; cleared when ownership ends |
| Hard lease | `jobs.claim_expires_at` | claim/renew/claimed append; compared to database clock |
| Stale recovery | P01 | `release_stale` resets expired RUNNING to PENDING and increments `attempt` |
| In-database queue execution | P09 | `worker_step` claims, invokes one catalog handler, maps one outcome |
| Canonical mock coding step | P05 | `step_once` appends one LLM/tool pair or final/error |
| Historical truth | `cordis.agent_steps` | P02 append monopoly reached through claimed/scoped functions |
| Host claim lifecycle | P10 | `CordisHostClient` wraps P01 verbs through synchronous `psql` |
| Host scoped append | P10/P08 | client `emit_step_scoped` → P08 grant checks → P02 claimed append |
| Host provider key | P10/P05 | client asks PostgreSQL for `md5(run_id || '/' || step_name)` |
| Slice grant | P07 | trusted `create_slice` and `issue_grant` fixture setup |
| Test process/server lifecycle | shared pytest fixtures | `run_apply`, `psql`, session `pgdata`, `get_server` |

The kernel already enforces all state-machine invariants needed by P11:

- RUNNING rows have all three claim fields;
- non-RUNNING rows have none;
- `claim_job` invokes stale release before selecting a PENDING row;
- targeted claims filter by exact `run_id`;
- a successful yield clears ownership;
- an expired token cannot renew, append, yield, complete, or fail;
- every successful new claim gets a fresh UUID.

### Existing end-to-end in-database flow

```text
test producer
  → cordis.enqueue_job(run, kernel.step_once, codeact, payload)
  → one PENDING jobs row

targeted cordis.worker_step(in_db_id, run, 90)
  → _require_isolation_feature
  → claim_job(run, in_db_id, 90)
  → resolve jobs.job_type as kernel.step_once
  → step_once(run, internal_token, 90)
  → emit_step_claimed(llm/tool)
  → yield_claim(internal_token)
  → one result {job_id, run_id, outcome=yield}
```

The live token is intentionally local to the SQL statement and is never returned by `worker_step`. On normal `yield`, no observable live `claimed_by` remains after the statement commits because P01 clears all claim fields.

### Existing end-to-end host flow

```text
CordisHostClient.claim_job(run)
  → one psql process / committed P01 claim
  → ClaimedJob including live token and claimed_by

next_step_name / llm_checkpoint / provider_idempotency_key
  → independent read statements

emit_step_scoped(token, run, slice, run/yield, payload)
  → P08 exact slice/run grant checks
  → p08_scope attached by SQL
  → emit_step_claimed token/lease fence
  → one durable agent_steps event

yield_claim(token)
  → jobs PENDING, claim fields cleared
```

Unlike `worker_step`, the host claim remains live between Python method calls because each P10 method is a separate committed `psql` subprocess.

### Existing stale flow

```text
RUNNING row with expired claim_expires_at
  → next targeted claim_job
      → release_stale(run)
          → PENDING
          → attempt += 1
          → old claim fields cleared
      → same claim_job selects that row
          → RUNNING
          → fresh token
          → new claimed_by
```

No separate P11 stale-release function is necessary. P01’s `test_stale_reap_and_auto_claim` already proves the same primitive for SQL workers; P11 adds the cross-locus acceptance.

### Current transformation boundaries

#### Enqueue

```text
Python fixture JSON
  → trusted psql SQL literal
  → enqueue validation
  → catalog handler + paradigm normalization
  → jobs.payload / jobs.job_type
```

#### In-database step

```text
target run and worker ID
  → worker_step
  → internal ClaimedJob row/token
  → P05 event payloads
  → P02 agent_steps
  → P01 yield
```

#### Host step

```text
Python values
  → P10 local validation and JSON envelope
  → fixed SQL template
  → P01/P02/P08
  → typed Python result
```

#### Stale fixture

```text
known live token
  → trusted test-only UPDATE of claim_expires_at
  → next ordinary targeted claim_job
  → automatic P01 stale release
  → new typed/raw claimed row
```

The test-only backdate creates the boundary condition; it does not perform the takeover itself.

### Reuse instead of duplication

P11 reuses:

- `cordis.enqueue_job` rather than direct jobs insertion;
- `kernel.step_once` rather than a P11 queue handler;
- `cordis.worker_step` rather than a test worker implementation;
- `CordisHostClient` rather than P10-like raw SQL for host operations;
- `emit_step_scoped` rather than direct `agent_steps` insertion;
- P07 slice/grant functions rather than direct grant-table writes;
- `claim_job` automatic stale release rather than manually rebuilding the state transition;
- `yield_claim` rather than direct status updates;
- the shared pgembed/apply/psql fixtures.

Private SQL quoting and row-parsing helpers remain local to the P11 test because existing P09/P10 helpers are private test-module details. P11 must not import one test module from another or refactor shipped P09/P10 tests merely to share a few fixture helpers.

### Blocking gap

The only missing artifact is cross-locus acceptance coverage. There is no kernel or host-client gap:

- P09 can target and step the run;
- P10 can target and hold the same P01 claim;
- both operate on the same jobs row;
- P08 can record the host checkpoint;
- P01 can reap either identity’s stale claim;
- tokens already fence old owners.

This is therefore best solved by one focused integration test. A numbered SQL wrapper or broader abstraction would duplicate existing behavior and create a parallel path without adding capability.

---

## Design

### Resolved decisions

| # | Decision | Rationale | Rejected alternatives |
|---:|---|---|---|
| 1 | **P11 is tests-only. It adds no numbered SQL and keeps marker `p21`.** | P01 already supports targeted claim/yield/stale takeover; P09 and P10 already expose the two loci. The missing requirement is only their combined proof. | Add `0022` as a wrapper or marker-only migration; modify P01/P09/P10; retarget P00 pins. These duplicate shipped interfaces without closing a kernel gap. |
| 2 | **Each required in-database step is option A: targeted `cordis.worker_step` on a P09 `kernel.step_once` enqueue.** | The skeleton calls this a coding run. P09 directly registers the P05 mock body and already proves one invocation per claim (`sql/0021_p09_in_db_worker.sql`; `tests/test_p09_in_db_worker.py:test_p09_single_worker_yields_reclaims_and_completes_mock_run`). | A custom yield-only handler proves fixture plumbing, not the canonical coding path. Raw `claim_job` proves ownership but not P09 queue execution and is used only to stage stale leases. |
| 3 | **The host step is option A: claim, step-name/checkpoint reads, provider-key derivation, scoped append, then yield.** The scoped event is `run/yield` with SQL `step_name=NULL`. | P10’s contract is a verb seam, not `step_once` or a host loop. A durable scoped host checkpoint proves a real host write while avoiding interference with P05’s current `llm` checkpoint. | Claim+yield only does not prove host log write or provider-key seam. Host `step_once` is explicitly forbidden. A host `llm/s-2` alone would make the next P05 step treat it as a resume checkpoint and reject its protocol/fingerprint. |
| 4 | **P11 does not complete the three-step P05 mock.** It proves alternating ownership, two successful in-db coding steps, one host scoped write, and live `claimed_by` flips during stale takeover. | Proof 1 concerns one queue and two executors. Completion would require the host to emulate P05’s private mock checkpoint/fingerprint or append a synthetic `llm`/`tool` pair, coupling P11 to behavior already proven by P09. | Complete the conversation across loci; require final answer `ok`; let the post-host worker fail on a mismatched host LLM checkpoint. Both obscure the claim proof. |
| 5 | **Prove stale takeover in both directions. Use a raw targeted P01 claim left RUNNING for the in-database-owned lease.** | `worker_step` normally consumes or releases its token in one statement and never returns it, so it cannot stage a committed live lease. A raw P01 claim is the minimal deterministic staging mechanism and directly exercises the shared protocol. | A custom `lost_claim` queue handler would add catalog fixture complexity and manufacture a protocol failure. Waiting for a real lease wastes time and introduces flakiness. Testing only host→in-db leaves the reverse direction unproven. |
| 6 | **Set up the job with `cordis.enqueue_job`, not a P10-style trusted INSERT.** | `worker_step` requires a catalog-compatible `job_type` and valid `payload.paradigm`; enqueue owns both validations. | Direct INSERT is sufficient for host-only P10 tests but can create a row that P09 terminalizes as an unavailable handler or invalid payload. A new producer API is unnecessary. |

### Targeted change versus refactor

This is a targeted integration addition. No refactor is justified because the runtime already has one authoritative queue, one complete claim protocol, both executor seams, scoped logging, and stale recovery. The implementation should add only a P11 test module and review artifacts; extracting shared test infrastructure or adding a cross-locus runtime coordinator would make the proof less direct.

---

## Architecture

### Invariants

The P11 test must preserve and assert these invariants:

1. **One run, one jobs row:** `jobs_run_id_key` remains the sole row identity boundary.
2. **One job ID:** enqueue, every worker result, and every claimed row refer to the same `job_id`.
3. **Targeted only:** every `worker_step` and `claim_job` supplies the exact run ID.
4. **Token authority:** every accepted mutation uses the current token; stale tokens return false.
5. **Identity is observational:** `claimed_by` proves which test locus held the live lease but never replaces token fencing.
6. **Fresh claim per ownership period:** all returned tokens differ.
7. **Yield does not increment attempt:** the alternating coding phases remain at attempt 1.
8. **Stale recovery increments attempt:** host→in-db produces attempt 2; in-db→host produces attempt 3.
9. **Host event does not consume `s-2`:** the event has no SQL step name, so the second in-database call still executes `s-2`.
10. **No terminalization:** P11 leaves no `final` or `error` event and no DONE/ERROR jobs state.
11. **No hidden scheduler:** all ordering is explicit in one pytest process.
12. **No second source of truth:** log history stays in `agent_steps`; lease truth stays in `jobs`.

### State and data ownership

| State | Owner | P11 mutation |
|---|---|---|
| `jobs.job_id`, `run_id`, handler payload | PostgreSQL | created once through `enqueue_job` |
| `jobs.status` and claim fields | P01 | only existing claim/yield/stale functions, except test-only lease timestamp backdate |
| `jobs.attempt` | P01 stale release | observed, never directly assigned by P11 |
| P05 in-db events | P05/P02 | emitted inside `worker_step` |
| P11 host proof event | P10/P08/P02 | emitted through `emit_step_scoped` |
| P08 scope | P08 | attached by SQL; never constructed by Python |
| P07 slice/grant | P07 | created by trusted fixture calls |
| Host token | one `ClaimedJob` value in test scope | discarded after yield or takeover |
| Raw in-db token | private test result value | discarded after yield or takeover |
| Worker IDs | test constants | reused throughout; non-secret |

P11 adds no persistent application state. All data is in a disposable test database.

### Alternating-step data flow

#### Phase A — first in-database coding step

```text
P11 fixture
  → enqueue_job
  → jobs(PENDING, attempt=1)

_worker_step(in_db_id, run_id)
  → claim_job
  → jobs(RUNNING, claimed_by=in_db_id, internal token)
  → kernel.step_once
  → emit_step_claimed(llm/s-1)
  → emit_step_claimed(tool/s-1)
  → yield_claim
  → jobs(PENDING, attempt=1, claim fields null)
  → outcome=yield
```

The claim is not externally observable while live because claim and yield occur in one statement. Ownership is established by the `worker_step` path, returned outcome, matching job ID, and resulting P05 events.

#### Phase B — host checkpoint step

```text
host_client.claim_job(run_id)
  → jobs(RUNNING, claimed_by=host_id, token=host_token)

next_step_name(run_id)
  → s-2

llm_checkpoint(run_id, s-2)
  → absent

provider_idempotency_key(run_id, s-2)
  → PostgreSQL md5

emit_step_scoped(host_token, run, slice, run/yield, payload)
  → P08 run-grant validation
  → p08_scope attachment
  → P02 live-token check and lease extension
  → agent_steps append

yield_claim(host_token)
  → jobs(PENDING, attempt=1)
```

#### Phase C — second in-database coding step

```text
_worker_step(in_db_id, run_id)
  → claim same job
  → next_step_name sees latest llm/tool pair at s-1
     and ignores host run/yield for naming
  → kernel.step_once executes s-2
  → emits llm/s-2 and tool/s-2
  → yields
  → jobs(PENDING, attempt=1)
```

### Stale-takeover data flow

#### Host → in-database

```text
host targeted claim
  → RUNNING, attempt=1, claimed_by=host_id, token=H1

competing targeted in-db claim
  → no row; state unchanged

trusted fixture expires H1
  → RUNNING remains structurally valid, but lease is dead

targeted raw in-db claim
  → claim_job calls release_stale
  → PENDING, attempt=2
  → immediately claims same row
  → RUNNING, claimed_by=in_db_id, token=D1

old H1 transition
  → false

yield D1
  → PENDING
```

#### In-database → host

```text
targeted raw in-db claim
  → RUNNING, attempt=2, claimed_by=in_db_id, token=D2

competing host targeted claim
  → None; state unchanged

trusted fixture expires D2

host targeted claim
  → claim_job calls release_stale
  → PENDING, attempt=3
  → immediately claims same row
  → RUNNING, claimed_by=host_id, token=H2

old D2 transition
  → false

yield H2
  → PENDING
```

### Concurrency and transaction boundaries

- The test is synchronous and intentionally serial; it is not a timing race test.
- Every `CordisHostClient` call starts one `psql` process and commits one statement.
- Every use of the shared `psql` helper likewise commits before returning.
- `worker_step` performs claim, handler invocation, and yield in one database transaction.
- Raw stale-staging claims use one-shot `psql`, not `psql_session`, so the RUNNING row is committed and visible to the competing locus.
- `psql_session` remains available but is not needed; holding an uncommitted claim would not model the cross-process lease P11 needs.
- The direct lease backdate runs only after the original claim has committed.
- The next targeted `claim_job` performs stale release and reclaim in its own statement.
- No `time.sleep`, polling loop, background task, thread, event notification, or host heartbeat is used.
- All calls use explicit run IDs, so another ready row cannot be selected accidentally.
- The test must not retry a failed mutating call automatically.

### Duplicate, out-of-order, and dropped operations

- A competing claim before expiry must return no row/`None`; this proves live mutual exclusion.
- A claim after expiry must return one row with a new token.
- Reusing the old token after takeover must return false; no fallback mutation occurs.
- Calling phases out of order causes explicit assertions to fail:
  - host step before `s-1` would observe `s-1`, not expected `s-2`;
  - host `llm` contamination would change `llm_checkpoint` or the next worker outcome;
  - an omitted yield would make the next live claim return no row;
  - an omitted stale backdate would preserve mutual exclusion and fail the takeover assertion.
- P10 already defines mutating timeouts as unknown outcomes. P11 does not inject response loss or cancellation; if an unexpected `CordisCommandTimeout` occurs, the test fails rather than replaying the mutation.
- On an assertion failure with a live token, the disposable database may retain RUNNING state until the next test reset. P11 does not add auto-yield cleanup that could obscure the original failure.

### Error handling and boundary conditions

| Condition | Expected P11 behavior |
|---|---|
| Apply/reset failure | Fail immediately with combined apply output |
| Enqueue failure | Fail; do not fall back to direct INSERT |
| Unexpected `worker_step` outcome | Fail with returned job/run/outcome details |
| Worker result has wrong job or run | Fail before host phase |
| Host claim returns `None` when row should be PENDING | Fail; do not poll |
| Competing claim succeeds before expiry | Fail mutual-exclusion assertion and release only through test cleanup/reset |
| Host scoped append denied | Fail with P08 SQL error; do not use checkpoint or direct log insert as fallback |
| Scoped append returns false | Fail as lost ownership |
| Host event changes `next_step_name` | Fail; do not adapt the expected P05 flow |
| Lease backdate affects zero/multiple rows | Fail; expiry helper must target exact run and token |
| Stale claimant returns zero/multiple rows | Fail |
| Takeover reuses old token | Fail |
| `attempt` differs from 1/2/3 sequence | Fail |
| Old token transition succeeds | Fail fencing assertion |
| Final cleanup is not PENDING | Fail |
| Extra jobs row exists for run | Fail one-row proof |
| `final` or `error` appears | Fail non-terminal proof contract |
| P04 sleep unavailable | Irrelevant; P11 never calls it |

### API and persistence impact

There are no runtime API changes.

Existing interfaces used unchanged:

```text
cordis.enqueue_job(text,text,text,jsonb,integer) → bigint
cordis.worker_step(text,text,integer)
    → table(job_id bigint, run_id text, outcome text)
cordis.claim_job(text,text,integer) → setof cordis.jobs
cordis.yield_claim(uuid) → boolean

CordisHostClient.claim_job(run_id, lease_seconds) → ClaimedJob | None
CordisHostClient.yield_claim(token) → bool
CordisHostClient.emit_step_scoped(...) → bool
CordisHostClient.next_step_name(run_id) → str
CordisHostClient.llm_checkpoint(run_id, step_name) → AgentStep | None
CordisHostClient.provider_idempotency_key(run_id, step_name) → str
```

No existing call site is modified. P11 adds only a new test consumer.

There is no schema or serialization migration. Existing databases remain readable by older code, and rolling back P11 removes only tests/docs/review artifacts.

---

## Deliverables

1. **Complete deep plan**
   - `docs/plans/P11-alternating-claim-2026-08-25.md`
   - Replaces the scaffold with this specification.

2. **Plan critique record**
   - `docs/reviews/2026-08-25-p11-plan-critique.md`
   - Required before test edits; must contain no open P0/P1 after fold.

3. **Canonical acceptance test**
   - `tests/test_p11_alternating_claim.py`
   - Contains one end-to-end named test on one run and one jobs row.

4. **Implementation Oracle record**
   - `docs/reviews/2026-08-25-p11-implementation-oracle.md`
   - Records exports, verdicts, and closure of all implementation findings.

5. **No runtime delivery**
   - No `sql/`, `pg_cordis_host/`, shared fixture, dependency, apply-tool, or marker changes.

---

## Execution index

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W110 | P11 disposable test harness and canonical coding fixture | A fresh P11 database can be reset, one canonical P09 job enqueued, one P07 slice/run grant issued, host client constructed, and targeted worker/raw claims parsed without importing private P09/P10 test helpers | `tests/test_p11_alternating_claim.py` | `tests/conftest.py`, P07, P09, P10 | Small |
| W111 | Real in-db → host → in-db alternation | The same job yields through `worker_step`, receives one scoped host checkpoint and yield, then yields through `worker_step` again; log order is `llm,tool,run/yield,llm,tool` and next step is `s-3` | same | W110, P02, P05, P08–P10 | Medium |
| W112 | Bidirectional stale takeover on the same row | Host→in-db and in-db→host takeover both use automatic stale release, preserve the same job ID, flip `claimed_by`, create fresh tokens, fence old tokens, and advance attempt 1→2→3 | same | W111, P01 | Medium |
| W113 | One-row, targeted, no-runtime-change acceptance gate | Final state is one PENDING row with attempt 3 and no claim/terminal fields; all calls are targeted; no SQL/runtime/shared-fixture changes are needed | test, plan, repository diff | W110–W112 | Small |
| W114 | Regression, Oracle, commit, and push gate | Focused/cross/full suites pass, latest Oracle review has no P0/P1, P11-only files are committed, and push succeeds | tests, review note | W110–W113 | Medium |

W110–W113 are one additive test delivery and must land together. There is no independently useful partial P11 proof.

---

## Work items and verification

### W110 — Test harness and canonical fixture

Create `tests/test_p11_alternating_claim.py`.

Private module-level fixtures and helpers:

- `P11_DB = "cordis_p11"`;
- fixed `RUN_ID`;
- fixed `IN_DB_WORKER_ID`;
- deterministic host UUID and `new_host_worker_id("p11proof", uuid)`;
- local canonical P05 mock payload;
- `_reset(pgdata)` using `run_apply(..., "--reset")`;
- `_client(server)` using:
  - `server.get_uri(P11_DB)`;
  - `POSTGRES_BIN_PATH / "psql"`;
- trusted SQL quoting/JSON helpers;
- `_enqueue(...) -> job_id`;
- `_create_slice_and_issue_run_grant(...) -> slice_id`;
- `_worker_step(...) -> {job_id, run_id, outcome}`;
- `_raw_claim(...) -> None | {job_id, run_id, attempt, token, claimed_by, status}`;
- `_expire_exact_claim(...)`;
- `_job_snapshot(...)`;
- `_log_rows(...)`.

Helper contracts:

- All claim/worker helpers require a nonoptional run ID.
- `_raw_claim` must distinguish zero rows from one row and fail on multiple rows.
- `_expire_exact_claim` targets both run ID and token and confirms exactly one returned row.
- No helper exposes a global polling mode.
- No helper performs a direct jobs status update.
- No helper inserts into `agent_steps`.
- No helper imports `tests.test_p09_in_db_worker` or `tests.test_p10_host_sql_seam`.
- No second server/apply fixture is introduced.
- No test plugin or fixture function is installed.

#### Verify

- Fresh reset reports the existing source tree through `0021`.
- `cordis.get_schema_version()` remains `p21`.
- Enqueue returns one job ID.
- Jobs row starts as:
  - status `PENDING`;
  - attempt 1;
  - `job_type = 'kernel.step_once'`;
  - `payload.paradigm = 'codeact'`;
  - claim fields null.
- The P07 slice belongs to the same run and has a live `run` grant.
- Host client’s worker ID matches the required host grammar.
- No P04 method is called.

### W111 — Alternating coding and host steps

Add the canonical named test:

```text
test_p11_in_db_host_in_db_alternation_and_bidirectional_stale_takeover
```

The first section of that test performs:

1. reset;
2. enqueue canonical run;
3. create slice and issue run grant;
4. first targeted in-database step;
5. host claim/checkpoint/yield;
6. second targeted in-database step.

Required assertions after in-database step 1:

- result contains the enqueue `job_id`;
- result run ID is exact;
- outcome is `yield`;
- jobs row is `PENDING`;
- attempt remains 1;
- claim fields are null;
- log contains exactly `llm/s-1`, `tool/s-1`;
- `next_step_name` is `s-2`.

Required host assertions:

- targeted claim returns `ClaimedJob`;
- same job ID;
- status RUNNING;
- attempt 1;
- `claimed_by == host_client.worker_id`;
- token differs from every earlier externally held token;
- `next_step_name == "s-2"`;
- `llm_checkpoint(run, "s-2") is None`;
- provider key matches 32 lowercase hex;
- scoped append returns true;
- stored P11 event has:
  - kind `run/yield`;
  - SQL step name null;
  - exact P11 protocol;
  - host locus;
  - exact host worker ID;
  - logical step `s-2`;
  - exact provider key;
  - P08 scope with the expected slice ID;
  - empty named-corpus list;
- `next_step_name` remains `s-2`;
- host yield returns true;
- jobs row returns to PENDING with attempt 1.

Required assertions after in-database step 2:

- same job and run;
- outcome `yield`;
- jobs row PENDING;
- attempt 1;
- claim fields null;
- `next_step_name == "s-3"`;
- exact relevant log order:

  ```text
  llm/s-1
  tool/s-1
  run/yield/NULL
  llm/s-2
  tool/s-2
  ```

- no final/error event exists.

#### Verify

Run:

```bash
uv run pytest tests/test_p11_*.py -q
```

The test must fail if the host emits an `llm` event, supplies a SQL step name for its proof event, skips the scoped append, or uses a global claim.

### W112 — Bidirectional stale takeover

Continue the same named test on the same PENDING row.

#### Host → in-database sequence

- Host targeted claim succeeds.
- Capture host token and assert same job ID, attempt 1, host `claimed_by`.
- Targeted raw in-database claim returns no row while live.
- Backdate the exact host token.
- Targeted raw in-database claim succeeds.
- Assert:
  - same job ID;
  - attempt 2;
  - RUNNING;
  - `claimed_by == IN_DB_WORKER_ID`;
  - new token differs from host token.
- Old host token’s `yield_claim` returns false.
- Raw yield of the new in-database token returns true.

#### In-database → host sequence

- Targeted raw in-database claim succeeds.
- Capture token and assert same job ID, attempt 2, in-database `claimed_by`.
- Host targeted claim returns `None` while live.
- Backdate the exact in-database token.
- Host targeted claim succeeds.
- Assert:
  - same job ID;
  - attempt 3;
  - RUNNING;
  - `claimed_by == host_client.worker_id`;
  - new token differs from all stale tokens.
- Raw yield with the old in-database token returns false.
- Host yield with the new token returns true.

The test must rely on `claim_job`’s internal `release_stale`; do not call `release_stale` separately. The attempt increments prove that stale release occurred.

#### Verify

After each takeover:

- the old owner cannot mutate with its stale token;
- the new owner can yield with its fresh token;
- no log event is added by raw claim, stale release, or yield;
- jobs row count remains one;
- no replacement job ID appears.

### W113 — Final contract and no-runtime-change gate

At the end of the canonical test, assert:

- one row for the run;
- same original job ID;
- status PENDING;
- attempt 3;
- claim token absent;
- claimed_by absent;
- expiry absent;
- completed_at absent;
- result/error absent;
- five expected agent-step events remain;
- no final/error events;
- next step remains `s-3`.

Review the implementation diff and enforce:

- no files under `sql/` changed or were created;
- no change to `tests/test_p00_sql_source.py`;
- no change to `tests/conftest.py`;
- no change to `pg_cordis_host/`;
- no change to `pyproject.toml` or `uv.lock`;
- no scratch or backup dependency;
- no second test server or apply path;
- no use of `worker_step` through the host client;
- no call with a null run ID;
- no host loop or repeated polling construct;
- no `sleep_claim`.

#### Verify

Run the focused test from a clean reset and inspect the staged path list. Marker verification is delegated to the existing P00/P10 tests; P11 does not add a duplicate future-brittle SQL inventory assertion.

### W114 — Regression and delivery gate

Focused P11 suite:

```bash
uv run pytest tests/test_p11_*.py -q
```

Cross-protocol suite:

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
  tests/test_p10_host_sql_seam.py \
  tests/test_p11_alternating_claim.py -q
```

Full suite:

```bash
PGCORDIS_PGDATA="$CORDIS_ROOT/.pgdata" uv run pytest -q
```

Delivery checks:

1. inspect working-tree diff;
2. inspect `git log @{u}..HEAD`;
3. ensure the range contains no unrelated or unreviewed changes;
4. obtain Oracle implementation review in `mode: "review"`;
5. record all findings and exports in `docs/reviews/2026-08-25-p11-implementation-oracle.md`;
6. close all P0/P1 in the same Oracle chat;
7. rerun affected tests after every behavioral change;
8. stage only P11 paths;
9. commit with an English P11 message;
10. push immediately;
11. do not claim completion before push success.

---

## File inventory and file-by-file impact

| File | Change | Why | Dependencies and ordering |
|---|---|---|---|
| `docs/plans/P11-alternating-claim-2026-08-25.md` | Replace the lightweight scaffold with this complete deep plan | Resolves all six design questions and satisfies the plan-before-test gate | First; this pass only |
| `docs/reviews/2026-08-25-p11-plan-critique.md` | Create during the plan gate; record critique verdict and P0/P1/P2 findings | `AGENTS.md` forbids implementation before critique blockers are folded | Before any test edit |
| `tests/test_p11_alternating_claim.py` | Create. Add local fixture helpers and the single canonical named test | Primary P11 proof | After plan critique; atomic with final plan/review |
| `docs/reviews/2026-08-25-p11-implementation-oracle.md` | Create after implementation and test success; record all Oracle rounds | Mandatory P completion gate | After tests, before commit |
| Referenced `prompt-exports/oracle-review-*.md` | Include only when cited by the implementation review record | Preserves the audited Oracle verdict | With review record if repository practice requires |
| `sql/0001_p01_claim.sql` | **No change** | Existing claim, stale release, attempt, and fencing semantics are sufficient | Regression only |
| `sql/0002_p02_log.sql` | **No change** | Existing claimed append and step naming are sufficient | Regression only |
| `sql/0005_p05_one_step_driver.sql` | **No change** | Existing canonical coding mock supplies both in-db steps | Regression only |
| `sql/0020_p08_four_seam_enforcement.sql` | **No change** | Existing scoped append supplies the host log boundary | Regression only |
| `sql/0021_p09_in_db_worker.sql` | **No change** | Existing enqueue/worker interfaces supply the in-db locus | Regression only |
| `sql/README.md` | **No change** | No numbered SQL or marker change | Protected |
| `tests/test_p00_sql_source.py` | **No change** | Current marker and file inventory remain `p21` | Must stay untouched |
| `tests/test_p01_claim.py` | **No change** | P11 composes, rather than revises, stale semantics | Regression only |
| `tests/test_p09_in_db_worker.py` | **No change** | Do not extract its private fixture constants/helpers | Regression only |
| `tests/test_p10_host_sql_seam.py` | **No change** | Do not extract its private client/slice helpers | Regression only |
| `tests/conftest.py` | **No change** | Existing fixtures are sufficient | Protected |
| `pg_cordis_host/client.py`, `pg_cordis_host/__init__.py` | **No change** | P11 consumes the shipped P10 API | Protected |
| `tools/apply_pg_cordis.py` | **No change** | Existing apply stack is reused | Protected |
| `pyproject.toml`, `uv.lock` | **No change** | No dependency or package change | Protected |
| `.p19-backup/`, `scratch/` | **No change and no import** | P04 WIP and research artifacts are not ABI | Must not enter ship set |

No `sql/0022_*.sql` file is reserved by P11. A later plan may use the next numeric prefix if it has a real kernel change.

---

## Risks and rollback

### Host proof event could interfere with P05 step naming

A host `llm/s-2` without its matching P05 fingerprint/tool would make the next `worker_step` resume and reject that checkpoint.

Mitigation: emit `run/yield` with SQL `step_name=NULL`; assert `next_step_name` remains `s-2` before the second in-database step.

### The host step could be dismissed as claim-and-yield only

A bare claim/yield would not prove P10’s durable write seam.

Mitigation: require step-name read, checkpoint absence read, database-derived provider key, a claim-fenced P08-scoped event, inspection of its persisted scope/payload, and only then yield.

### Raw claims could be mistaken for the required in-database coding steps

Raw P01 claims do not invoke the P09 handler.

Mitigation: both required coding steps use `worker_step`. Raw claims are explicitly confined to stale-lease staging/takeover, where `worker_step` cannot leave a host-visible token.

### Direct lease backdating bypasses a public verb

No public API intentionally shortens a live lease, and real-time waiting would make the suite slow and flaky.

Mitigation: the fixture changes only `claim_expires_at` for an exact run/token in a disposable database. Actual stale release, attempt increment, token replacement, and ownership transition still occur through ordinary `claim_job`.

### `claimed_by` does not authenticate a locus

SQL accepts any nonblank worker ID, so a raw SQL caller can choose a host-looking string.

Mitigation: use exact, visibly distinct test identities and state clearly that token fencing is authoritative. P11 proves protocol interoperability, not hostile-principal authentication.

### P11 depends on the P05 mock payload shape

The two in-database steps need valid `s-1` and `s-2` mock responses and observations.

Mitigation: keep one small local fixture matching the shipped P05/P09 proof. Do not assert final completion, request fingerprints, or unrelated P05 payload internals.

### Test length and failure cleanup

The canonical test contains several sequential phases. A mid-test assertion can leave the disposable row RUNNING.

Mitigation: each execution begins with `--reset`; the final successful path yields every live claim. Do not add broad cleanup that hides which phase violated the protocol.

### Future marker changes

A future numbered plan will advance the complete-tree marker beyond `p21`.

Mitigation: P11 does not add its own static file-list or marker pin. Existing P00/current-tree tests remain the canonical inventory assertions.

### Migration and rollback

P11 has no persistence migration or breaking API change.

Rollback is source-only:

- remove/revert the P11 test;
- revert the P11 plan/review artifacts if appropriate.

All database state created by the test lives in a resettable disposable database. Removing P11 does not affect an applied product database.

---

## Implementation order

1. Verify/create `docs/reviews/2026-08-25-p11-plan-critique.md`. Fold every P0/P1 into this plan before editing tests. If the critique reopens D1–D9 or snapshot §4, follow the conflict procedure in `AGENTS.md` instead of changing the architecture.
2. Confirm the implementation baseline contains shipped P09 and P10 and the current SQL tree reports `p21`. Do not modify marker pins.
3. Create `tests/test_p11_alternating_claim.py` with W110 only: database constant, deterministic identities, local P05 payload, reset/client/enqueue/grant/claim/expiry/read helpers.
4. Add the W111 alternation section to `test_p11_in_db_host_in_db_alternation_and_bidirectional_stale_takeover`.
5. Run the focused P11 test through the end of the second in-database step.
6. Add W112 host→in-db stale takeover to the same test and verify attempt 2 plus old-token fencing.
7. Add W112 in-db→host stale takeover to the same test and verify attempt 3 plus old-token fencing.
8. Add W113 final one-row, log-order, non-terminal, and cleanup assertions.
9. Inspect the test source for targeted run IDs only and ensure no global polling, loop, sleep, custom plugin, direct status update, or direct log insertion exists.
10. Run:

    ```bash
    uv run pytest tests/test_p11_*.py -q
    ```

11. Run the complete cross-protocol command from W114.
12. Run the full suite on a clean tree.
13. Inspect the complete diff. It must contain only the P11 plan, P11 test, and P11 review artifacts; no SQL, host client, shared fixture, dependency, P09, or P10 changes.
14. Follow the `AGENTS.md` Oracle implementation-review loop. Record all rounds in `docs/reviews/2026-08-25-p11-implementation-oracle.md`.
15. Fix every P0/P1, rerun affected tests, and continue in the same Oracle chat. Any behavioral change after a passing review requires another review.
16. After the latest review has no open P0/P1, stage only the P11 ship set.
17. Commit with an English message such as `Add pg_cordis P11 alternating claim proof.` and reference the implementation review record.
18. Recheck the working tree and `@{u}..HEAD` range.
19. Push immediately without force.
20. Report P11 complete only after push succeeds.

Steps 3–8 must land atomically because partial phases do not satisfy skeleton proof 1.

---

## Outstanding concerns

No implementation design decisions remain open.

The implementing agent must validate these baseline assumptions before editing:

1. `cordis.enqueue_job` still accepts `kernel.step_once` with paradigm `codeact`.
2. `emit_step_scoped` still accepts `kind='run/yield'` with no SQL step name.
3. `next_step_name` still ignores `run/yield` for named-step advancement.
4. `CordisHostClient.claim_job` still returns the live token and exact `claimed_by`.
5. `worker_step` still returns no token and produces `yield` for the first two canonical P05 mock steps.
6. The current tree still ends at `0021`/`p21`.

Validation approach: run the focused P09/P10 tests or inspect the installed function signatures before implementing P11. If a dependency has legitimately changed on `main`, update this plan against the new committed contract; do not add compensating P11 runtime code.

Explicitly deferred:

- successful sleep/retry and dead-letter behavior — P04;
- host workspace/worktree — P12;
- selection and prompt assembly — P13;
- path-fenced file mutation — P14;
- D5 two-project working example — P15;
- D2 call/result recovery — P16;
- asynchronous spawn — P17;
- context-builder child runs — P18;
- DuckDB plugin — P20;
- real host LLM transport, HTTP idempotency replay, and request fingerprints — later transport plan;
- role/RLS authentication of hostile SQL principals — later security work.

---

## References

- `AGENTS.md` — plan gate, shared fixtures, Oracle review, commit/push completion gate
- `docs/plans/2026-08-23-pg-cordis-development.md` — P11 skeleton and proof table
- `docs/plans/P09-in-db-worker-2026-08-25.md` — in-database worker ABI and P11 deferral
- `docs/plans/P10-host-sql-seam-2026-08-25.md` — host verb ABI, targeted-run rule, P11 deferral
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — locked D1–D9 architecture and must-prove item 1
- `sql/0001_p01_claim.sql` — one jobs row, claim fields, targeted claim, yield, stale release, attempt increment
- `sql/0002_p02_log.sql:72-156` — claim-fenced append and lease extension
- `sql/0002_p02_log.sql:279-343` — `next_step_name` semantics
- `sql/0005_p05_one_step_driver.sql` — canonical three-step mock coding body
- `sql/0007_p07_grant_registry.sql` — slice and run-grant fixture APIs
- `sql/0020_p08_four_seam_enforcement.sql:120-243` — readiness latch and scoped append
- `sql/0021_p09_in_db_worker.sql` — enqueue, handler resolution, one-step worker, token-hiding boundary
- `sql/README.md` — append-only SQL tree and current `p21` marker
- `pg_cordis_host/client.py` — P10 host claim, checkpoint, scoped append, provider key, and fencing methods
- `tests/conftest.py` — `run_apply`, `psql`, `psql_session`, and session `pgdata`
- `tests/test_p01_claim.py:test_stale_reap_and_auto_claim` — existing stale-release prior art
- `tests/test_p09_in_db_worker.py:test_p09_single_worker_yields_reclaims_and_completes_mock_run` — canonical P05/P09 coding fixture
- `tests/test_p09_in_db_worker.py:test_p09_transition_fence_returns_lost_claim` — reason `worker_step` can leave RUNNING only through an abnormal fixture path
- `tests/test_p10_host_sql_seam.py:test_p10_host_process_claims_and_appends_one_scoped_step` — host scoped-write pattern
- `tests/test_p10_host_sql_seam.py:test_p10_two_clients_share_p01_claim_fencing` — P10 shared-claim prior art
- `tests/test_p00_sql_source.py` — current source-tree and `p21` inventory pin, unchanged by P11


> 💡 Continue this plan conversation with ask_oracle(chat_id: "p11-alternating-claim-de-B0FC36", new_chat: false)