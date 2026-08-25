## Final Prompt
<taskname="P04 sleep-retry deep plan"/>

<task>
Write the complete, implementation-ready deep plan for pg_cordis **P04 — sleep + task-level retry state machine** and replace the scaffold at `docs/plans/P04-sleep-retry-2026-08-24.md` (same path, full rewrite; keep its curated Background evidence as the factual base — verify file:line refs you rely on against the selected sources).

Deliverable is **the plan document only** — no implementation. Per `AGENTS.md` rule 1, SQL/tests are written only after the plan's Status line reads `ready to implement`. Your plan sets that Status. Do not touch `sql/`, `tests/`, or `tools/` in this task.

The plan must match the executable depth and full output structure of `docs/plans/P03-wait-event-2026-08-24.md` (selected in full — use it as the structural template):
- Header block: Date 2026-08-24, Status **ready to implement**, Parent `docs/plans/2026-08-23-pg-cordis-development.md` P04, Depends on P01+P03 implemented, Parallel with P06/P07/P19, Primary deliverables `sql/0004_p04_*.sql`, retargeted `tests/test_p00_sql_source.py`, new `tests/test_p04_*.py`
- Summary, Goal, **Execution index**, **Resolved decisions with rejected alternatives**, current-state analysis, component & interface design (named SQL functions with full signatures, argument validation, SQLSTATEs), file-by-file impact, lock order, state and data flow, log kinds and payload shapes, error and edge cases, tradeoffs, risks, implementation order, **work items numbered W34+** (P03 used W27–W33, P06 used W60–W66 — do not reuse), verification with named test cases.
</task>

<locked_constraints>
Non-negotiable. Violations are contract conflicts, per AGENTS.md rule 2:
- D1–D9 and architecture snapshot §4 are locked — do not reopen. D4 A: five-piece kernel is claim, log checkpoint, **sleep**, scoped event, **task-level retry**. Retry **state** (attempt, next available_at, dead-letter `MAX_RECOVERY_ATTEMPTS_EXCEEDED` — the D4-named dead-letter reason) is kernel; retry **curve** is paradigm-parameterized. P06 `retry_class` (`replayable`/`idempotent`/`non_retryable`) classifies tools; it must NOT drive P04 retry curves.
- No `CREATE EXTENSION`; no second queue — retry mutates the **same** `cordis.jobs` row, same `run_id` (`jobs.run_id` is UNIQUE; Absurd's new-run-row retry is explicitly not copyable); do not promote `scratch/` to ABI; do not copy pg-agent SQL; do not edit historical numbered SQL files as the release mechanism; no new apply script.
- New SQL goes in a new file `sql/0004_p04_<slug>.sql` (four-digit unique prefix; gaps allowed, `0006` already exists). `get_schema_version()` returns `'p04'` **in the new file** (never edit `0000_kernel.sql`); full product tree still ends at `0006` and reports `p06` (latest prefix wins — see selected 0006 tail).
- Functions: schema `cordis`, `SECURITY INVOKER`, `SET search_path TO pg_catalog`, SQLSTATE conventions `invalid_parameter_value` / `object_not_in_prerequisite_state` (P03 also defined private SQLSTATE `P0301` — precedent for a `P04xx` if needed, decide explicitly).
- Tests use existing fixtures only: `run_apply`, `psql`, `psql_session` (+ `load_apply_module`, `next_sql_prefix` in test_p00). Retarget `tests/test_p00_sql_source.py`: `KERNEL_FUNCTIONS` tuple (currently 19 names, C-collation sort via `ORDER BY 1` — `_validate…` sorts first) gains the new P04 function names; the `files=0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,0003_p03_wait_event.sql,0006_p06_plugin_catalog.sql` assertions gain `0004_p04_*.sql` in numeric position.
- No dollar-quote leaks of bare `BEGIN`/`COMMIT`/`GRANT`/`END` outside function bodies (P06 lesson); every file replay-safe, schema-qualified, valid inside one tree-wide transaction.
- Cancel is **out of scope** unless a named invariant requires it (state why or why not).
</locked_constraints>

<must_cover>
Every item needs a named decision with rationale and rejected alternative — no material forks left hanging:
1. **Sleep verb.** `SLEEPING` status + `jobs.available_at` wake time, claim-fenced (token + RUNNING, like `yield_claim`/`fail_claim`), logs `run/sleep` — decide exact payload fields (e.g. `until`, serialized how? P03 precedent: `pg_catalog.to_jsonb(timestamptz)`) and whether via `emit_step` then fence, or one `emit_step_claimed` call. Kinds `run/sleep`, `run/wake`, `run/claim_timeout` already exist in the `agent_steps_kind_check` CHECK (0002) with **no emission path yet** — P04 wires them; P02's `emit_step_claimed`/`checkpoint` remain the sole log writers (do not add a second writer to `cordis.agent_steps`).
2. **Wait-deadline timeout resolution.** Resolve due `run_waits.deadline` rows reusing P03's global lock order **event row → jobs row(s) by run_id → wait row** and the `WAITING` + `await_id` fence; exactly one winner vs `emit_event` (F sketch §10 illegal state: emit and a future timeout must not both wake the same wait). Semantics for past deadlines and `±infinity` (deadline column is stored as given, never ticked — P03 decision 12 means WAITING never writes `jobs.available_at`; do NOT copy Absurd's coalesce-deadline-onto-available_at single-sleeping-state design — pg_cordis split WAITING vs SLEEPING deliberately). Decide the verb shape (e.g. a `resolve_due_waits(now)` sweep vs piggybacking on claim/release paths) and its log row (`run/wake` with timeout marker? decide payload discriminator vs emit-wake).
3. **Task-level retry on fail.** `fail_claim` requeue vs terminal `ERROR`; parameterized backoff (kernel state machine, curve parameterized — decide default formula/parameters; Absurd prior art: base 30s exponential, factor 2, cap 86400s, exponent = attempt−1); max attempts (decide default; NULL semantics); dead-letter reason key `MAX_RECOVERY_ATTEMPTS_EXCEEDED`; requeue keeps **same run_id, same jobs row, same `step_name`** for the incomplete step (F §3 fail: next `next_step_name` must return the same step). Whether requeue lands `PENDING` with `available_at = now+backoff` or `SLEEPING`.
4. **`fail_claim` revision vs new verb.** P01 plan (`:349`, `:571`) explicitly allows revising `fail_claim` in place while retaining the token fence — pick one, justify (current signature `fail_claim(p_run_id text, p_claim_token uuid, p_error jsonb)` always → ERROR terminal, no log, no attempt bump). If revised: decide new signature (retry policy params? defaults? JSONB policy?) and SQLSTATE behavior for lost claims; if new verb added, it joins `KERNEL_FUNCTIONS`.
5. **Sleep eligibility.** Expand `claim_job` to also claim due `SLEEPING` rows (`available_at <= t_claim`, like Absurd; P01 left the door open — `jobs_ready_idx` is currently PENDING-only, decide index retarget in 0004) vs a SLEEPING→PENDING ticker. Do **not** claim `WAITING` directly (P03 decision 11 — needs event-row lock first).
6. **`jobs.attempt` semantics.** Shared between `release_stale` lease-reap (already does `attempt+1`, `available_at = t0`) and fail-retry? (Absurd shares one counter; D4 names a single attempt column; splitting needs a new column — decide).
7. **`release_stale` logging + terminality.** Does it emit `run/claim_timeout` (kind reserved since 0002, never emitted)? Does over-limit stale reap go terminal (ERROR, dead-letter reason) rather than always requeue?
8. **Five-proof row 5** (shared P03+P04): emit-before-wait, duplicate events, retry, lease expiry — still one jobs queue. Name the proof tests.
</must_cover>

<architecture>
Selected sources (canonical order):
- `sql/0001_p01_claim.sql` — `cordis.jobs` DDL: status CHECK already `PENDING|RUNNING|WAITING|SLEEPING|DONE|ERROR`; `attempt int NOT NULL DEFAULT 1 CHECK (attempt>=1)`; `available_at timestamptz NOT NULL DEFAULT '-infinity'`; claim fields iff RUNNING (`jobs_claim_fields_check`); terminals need `completed_at`; `claim_job` PENDING-only with `available_at <= t_claim`; `release_stale` (RUNNING ∧ expired → requeue, attempt+1, no log); `fail_claim` (always terminal ERROR); `renew_claim`, `complete_claim`, `yield_claim`; indexes `jobs_ready_idx` (PENDING), `jobs_stale_claim_idx` (RUNNING).
- `sql/0002_p02_log.sql` — `cordis.agent_steps` (append-only SoT, PK `(run_id, seq)`, kind CHECK incl. `run/sleep`,`run/wake`,`run/claim_timeout`), `emit_step`, `emit_step_claimed` (fence = UPDATE jobs lease then emit), `checkpoint`, `next_step_name`, `llm_checkpoint`, `run_state` (log fold; counts `kind='llm'` only — new kinds don't pollute `steps_used`).
- `sql/0003_p03_wait_event.sql` — `run_events` (payload-NULL first-write fence), `run_waits` (PK `(run_id)`; `await_id uuid` unique while active; `deadline` stored as given, nullable), `await_event` (claim-fenced; locks event FOR SHARE → jobs → wait; appends `run/await`; WAITING + clears lease, **does not touch available_at** — decision 12), `emit_event` (unfenced; event FOR UPDATE → jobs FOR UPDATE → wait; `WAITING→PENDING`, `available_at = captured emit time`, deletes wait, appends `run/wake`, canonical `event/emit` on internal `@event/<uuid>` stream). Global lock order event→jobs→wait; private SQLSTATE `P0301`.
- `docs/plans/P03-wait-event-2026-08-24.md` — the depth/structure template: 12 resolved decisions each with rejected alternative, W27–W33, named tests, lock-order proofs (incl. "fan-out target set ∩ claim-held set = ∅" deadlock argument), deadline left to P04.
- `docs/plans/P01-jobs-claim-2026-08-23.md` — precedent for attempt/fail/requeue semantics and the standing P04 permissions (revise `fail_claim` w/ token fence; replace claim eligibility later).
- `docs/plans/2026-08-23-pg-cordis-development.md` — parent skeleton: P04 do/don't/done (`:142-150`), five-proof row 5 (`:62`), plan must decide default backoff, max attempts, dead-letter name.
- `docs/decisions/2026-08-23-pending.md` — D1–D9 locked text (D4 A five-piece kernel, `MAX_RECOVERY_ATTEMPTS_EXCEEDED`).
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` — semantic contract: sleep/fail/release_stale verbs (`:96-104`), failure ordering cheat sheet §10 (emit-vs-timeout single wake), scheduler state machine §11 (`RUNNING --sleep--> SLEEPING --available_at--> PENDING`; `RUNNING --fail--> ERROR|PENDING`), jobs status is claim eligibility not history.
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — §4 locked contract summary, §9 one-queue rule.
- `docs/reviews/2026-08-24-p03-plan-critique.md` — finding 5 (until P04, a never-emitted WAITING run is unreachable to complete/fail/yield/renew/release_stale — P04 timeout is the sanctioned recovery path); finding 7 (deadline JSON serialization precedent); finding 1 (deadlock argument pattern to reuse for any new verb touching event+jobs locks).
- `sql/0000_kernel.sql` (schema + version fn origin), `sql/README.md` (filename contract, release policy, forbidden statements, version table), `sql/0006_p06_plugin_catalog.sql` tail slice (version-wins mechanism + `refresh_plugins()` trailing call), `AGENTS.md` (repo rules: plan-gate, contract-beats-oracle, test fixtures, version bump location, P-completion gate).
- Tests: `tests/conftest.py` (harness), `tests/test_p00_sql_source.py` (KERNEL_FUNCTIONS + files= assertions to retarget), `tests/test_p01_claim.py` (claim/release/fail patterns; inserts reserved SLEEPING/WAITING rows and asserts `claim_job` skips them — `:413`; P04 must retarget this if claim eligibility changes), `tests/test_p03_wait_event.py` (two-`psql_session` concurrency test shapes, `run/await`/`run/wake` payload assertions — largest and closest test template).
- Absurd prior art (slices, shape only — not ABI, and its two decisions pg_cordis rejects are marked in the slice descriptions): `retry_delay_seconds` backoff formula; `claim_task` reap+claim (pending∪sleeping due, no ticker); `schedule_run` sleep; `fail_run` new-run-row retry (**forbidden** here); wait one-winner machinery.
</architecture>

<relationships>
- P04 verbs sit on the P01 fence (`claim_token` + RUNNING) exactly like `yield_claim`; any new logging goes through `emit_step`/`emit_step_claimed` — no second writer to `agent_steps`.
- Any path that can touch a wait (timeout resolution) must take P03's lock order **event → jobs → wait** and win or lose atomically against `emit_event` on the `WAITING`+`await_id` fence; a timeout winner does what emit does minus payload (WAITING→PENDING, delete wait, `run/wake`) — decide the payload discriminator.
- `fail_claim`-revision and `release_stale`-changes are in-place edits delivered **inside 0004** via `CREATE OR REPLACE` (historical files stay untouched; CREATE OR REPLACE is the sanctioned mechanism — check P01→P03 precedent of overriding in later files).
- Retry requeue feeds `next_step_name` (same `step_name` because the step's `llm` row is completed only by a later `tool`/`final`); sleep-wake feeds `claim_job` eligibility; both converge on the same `jobs` row — the five-proof's "still one queue".
- Schema version: 0000(p00)→0001(p01)→0002(p02)→0003(p03)→**0004(p04)**→0006(p06, product).
</relationships>

<open_questions>
The scaffold's six Open Questions map to must-cover items 1–6 above. Resolve each with a picked decision, rationale, and the rejected alternative(s) named — the plan's Resolved decisions section should carry them (P03 style: numbered, each with "Rejected:" line). Also decide: `run/sleep` payload exact fields; whether timeout-wake reuses kind `run/wake` (and how a reader distinguishes it from an emit-wake); whether `release_stale`'s existing requeue path adopts the same backoff curve; whether requeue-on-fail and sleep share `available_at` semantics (PENDING-at-future-time vs SLEEPING).
</open_questions>

<not_selected>
Available in the repo but not in context — cite by path if needed, don't invent contents: `docs/plans/P02-agent-steps-log-2026-08-23.md` (P02 decisions; 0002 SQL is ground truth here), `docs/plans/P06-plugin-catalog-2026-08-23.md` (retry_class boundary), `tests/test_p02_agent_steps.py` / `tests/test_p06_plugin_catalog.py` (more test patterns), `tools/apply_pg_cordis.py` (loader: FORBIDDEN_STMTS preflight, files= output format), `docs/plans/P00-sql-source-2026-08-23.md`, `docs/reviews/2026-08-24-p03-implementation-oracle.md`.
</not_selected>

<ambiguities>
None material — the scaffold's evidence tables were spot-checked against the selected sources and held. Two things to decide fresh (not ambiguities in sources): default max-attempts value and whether deadline `'-infinity'`/past deadlines resolve immediately on first sweep (sources only establish the column stores them unmodified).
</ambiguities>

## Selection
- Files: 20 total (18 full, 2 slice)
- Total tokens: 106453 (Auto view)
- Token breakdown: full 102032, slice 4421
- Token accounting: stale from active_tab_published; refresh pending

### Files
### Selected Files
├── absurd/
│   └── sql/
│       └── absurd.sql — 4,365 tokens (lines 56-110 (absurd.retry_delay_seconds(p_strategy jsonb, p_attempt integer) — neighbor backoff prior art: kind none|fixed|exponential; default base 60 fixed / 30 exponential seconds, factor 2, hard cap 86400s; exponent = attempt-1; invalid strategy raises AB003. Shape reference only, not ABI.), 975-1062 (absurd.claim_task lease-reap + due-row claim: reaper selects state='running' AND claim_expires_at <= now FOR UPDATE SKIP LOCKED and calls fail_run with '$ClaimTimeout' reason (attempt carried in reason payload, counter shared with fail-retry); candidate CTE claims state IN (pending,sleeping) AND available_at <= now directly with no ticker, sets available_at = claim time.), 1135-1310 (absurd.schedule_run — sleep verb prior art: sets state='sleeping', available_at = p_wake_at, clears claim fields (claim_expires_at = null, wake_event = null).; absurd.fail_run — retry prior art pg_cordis must NOT copy: on retryable fail it INSERTS A NEW RUN ROW (new run_id, attempt+1, state sleeping|pending by next_available vs now) — pg_cordis has UNIQUE(run_id) on cordis.jobs and forbids a second queue, so retry must mutate the same jobs row. Also shows max_attempts gate (null = unlimited), retry_delay_seconds use, cancellation via max_duration.), 1705-1945 (absurd wait/wake one-winner machinery: await uses v_available_at := coalesce(p_timeout, 'infinity') on the SAME sleeping state; payload IS NULL event sentinel; lock order event row FOR SHARE then run row FOR UPDATE; timeout-resume detection (wake_event matches + payload null) clears wake_event and returns without re-sleeping; emit flips only still-sleeping rows so first of emit vs timeout wins. Reference for P04 wait-deadline resolution semantics.))
└── zcordis-pgembed/
    ├── docs/
    │   ├── analysis/
    │   │   ├── 2026-08-23-f-yield-loop-protocol-sketch.md — 4,340 tokens (full)
    │   │   └── 2026-08-23-i-architecture-snapshot.md — 3,610 tokens (full)
    │   ├── decisions/
    │   │   └── 2026-08-23-pending.md — 8,250 tokens (full)
    │   ├── plans/
    │   │   ├── 2026-08-23-pg-cordis-development.md — 4,379 tokens (full)
    │   │   ├── P01-jobs-claim-2026-08-23.md — 16,808 tokens (full)
    │   │   ├── P03-wait-event-2026-08-24.md — 21,711 tokens (full)
    │   │   └── P04-sleep-retry-2026-08-24.md — 3,143 tokens (full)
    │   └── reviews/
    │       └── 2026-08-24-p03-plan-critique.md — 3,543 tokens (full)
    ├── sql/
    │   ├── 0000_kernel.sql — 97 tokens (full)
    │   ├── 0001_p01_claim.sql — 2,118 tokens (full)
    │   ├── 0002_p02_log.sql — 3,446 tokens (full)
    │   ├── 0003_p03_wait_event.sql — 4,673 tokens (full)
    │   ├── 0006_p06_plugin_catalog.sql — 56 tokens (lines 765-779 (P06 get_schema_version tail — latest numbered file wins; the new 0004_p04 file must add its own p04 override while 0006 (still last) keeps the full product tree reporting p06. Ends with SELECT cordis.refresh_plugins();))
    │   └── README.md — 1,394 tokens (full)
    ├── tests/
    │   ├── conftest.py — 1,253 tokens (full)
    │   ├── test_p00_sql_source.py — 4,565 tokens (full)
    │   ├── test_p01_claim.py — 5,733 tokens (full)
    │   └── test_p03_wait_event.py — 10,738 tokens (full)
    └── AGENTS.md — 2,231 tokens (full)


---

## Generated Plan

## Chat Send ✅
- **Chat**: `p04-sleep-retry-deep-pla-3B7B91` | **Mode**: plan

### Response
# P04 — sleep and task-level retry state machine

Date: 2026-08-24  
Status: **ready to implement**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P04  
Depends on: P01 and P03, implemented  
Parallel with: P06, P07, P19  
Primary deliverables: `sql/0004_p04_sleep_retry.sql`, retargeted `tests/test_p00_sql_source.py` and `tests/test_p01_claim.py`, new `tests/test_p04_sleep_retry.py`

---

## 1. Summary

P04 completes the remaining timer and recovery transitions on the existing `cordis.jobs` scheduler row. It adds a claim-fenced `cordis.sleep_claim(...)`, makes due `SLEEPING` rows directly claimable without a ticker, resolves P03 wait deadlines through a bounded `cordis.resolve_due_waits(...)` sweep using the existing **event row → jobs row → wait row** lock order, and revises `fail_claim`, `release_stale`, and `claim_job` in `0004` without editing historical SQL. Retry configuration is persisted per jobs row as a generic kernel backoff policy plus `max_attempts`; the default is three total attempts with deterministic exponential backoff of 30 seconds, factor 2, capped at 86,400 seconds. Recoverable failures mutate the same row and same `run_id` to `SLEEPING`; terminal exhaustion writes `ERROR` with the canonical reason `MAX_RECOVERY_ATTEMPTS_EXCEEDED`. All history is appended through P02’s `cordis.emit_step`; P04 adds no direct `agent_steps` writer, no second queue, no plugin-specific retry mapping, and no background timer. This is a targeted numbered-SQL migration and function replacement, not a jobs/log/event architecture refactor.

### Goal

Implement the P04 contract from `docs/plans/2026-08-23-pg-cordis-development.md:142-150`:

- Add claim-fenced sleep using the existing `SLEEPING` status and `jobs.available_at`.
- Make due sleeping jobs claimable through the existing queue.
- Resolve due P03 waits without copying their deadlines onto `jobs.available_at`.
- Guarantee that timeout and event emission can produce at most one `run/wake` for a given active wait.
- Add a task-level retry state machine driven by `jobs.attempt`, `jobs.max_attempts`, and a parameterized backoff policy.
- Use the same jobs row and `run_id` for every retry.
- Make explicit failure and lease expiry share the same recovery-attempt counter and backoff semantics.
- Emit `run/sleep`, timer `run/wake`, `run/claim_timeout`, and terminal `error` history through `cordis.emit_step`.
- Terminally fail exhausted jobs with `error.reason = 'MAX_RECOVERY_ATTEMPTS_EXCEEDED'`.
- Preserve the P03 event protocol and P02 append monopoly.
- Complete the shared five-proof requirement: emit-before-wait, duplicate event, retry, and lease expiry all operate through one `cordis.jobs` queue.

P04 is complete when automated tests prove:

1. a live claim can atomically append `run/sleep`, enter `SLEEPING`, store its wake time, and clear ownership;
2. a due sleeping row is claimed directly and receives exactly one timer `run/wake`;
3. a future sleeping row and every `WAITING` row remain unclaimable;
4. an explicit failure retries the same jobs row and same incomplete step name;
5. attempt exhaustion produces terminal `ERROR` with the canonical dead-letter envelope;
6. stale-lease recovery uses the same attempt counter, policy, and terminal limit;
7. due waits are returned to `PENDING` with one timeout `run/wake`;
8. timeout and event emit races have exactly one wake winner;
9. P03 emit-before-wait and duplicate-event behavior still composes with retry and lease recovery without creating another queue.

### Execution index

P03 used `W27`–`W33`; P04 continues with `W34`–`W41`. P06’s `W60`–`W66` remain separate.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W34 | Add retry policy storage and deterministic delay helper | Existing jobs receive valid defaults; policy validation and delay calculation are replay-safe and deterministic | `sql/0004_p04_sleep_retry.sql` | P01 | Medium |
| W35 | Add wait-deadline resolution | Due waits resolve through event → jobs → wait locking; timeout and emit cannot both wake one wait | `sql/0004_p04_sleep_retry.sql` | P03, W34 | Large |
| W36 | Add claim-fenced sleep | A live claim appends `run/sleep`, enters `SLEEPING`, stores a finite wake time, and clears ownership atomically | `sql/0004_p04_sleep_retry.sql` | P01, P02 | Medium |
| W37 | Revise failure and stale-lease recovery | `fail_claim` and `release_stale` share attempts, policy, retry scheduling, logging, and terminal dead-letter semantics | `sql/0004_p04_sleep_retry.sql` | W34 | Large |
| W38 | Expand claim maintenance and eligibility | `claim_job` runs bounded wait/stale maintenance, claims due `PENDING` or `SLEEPING`, never claims `WAITING`, and logs timer wake | `sql/0004_p04_sleep_retry.sql` | W35–W37 | Large |
| W39 | Advance and document the P04 marker | A tree ending at `0004` reports `p04`; the full tree ending at `0006` still reports `p06` | `sql/0004_p04_sleep_retry.sql`, `sql/README.md` | W34–W38 | Small |
| W40 | Retarget current-tree and P01 protocol assertions | Current file/function lists include P04; P01 tests reflect full-tree sleep/retry semantics without changing P01-only SQL | `tests/test_p00_sql_source.py`, `tests/test_p01_claim.py` | W34–W39 | Medium |
| W41 | Add P04 catalog, state-machine, atomicity, and race tests | Sleep, retry, stale recovery, timeout resolution, one-winner races, replay, and five-proof composition pass | `tests/test_p04_sleep_retry.py` | W34–W40 | Large |

---

## 2. Current-state analysis

### Curated background and locked evidence

#### Parent skeleton and signed contracts

| Fact | Source |
|---|---|
| P04 owns `SLEEPING`, `available_at`, attempts, next eligibility, terminal failure, default backoff, maximum attempts, and the dead-letter name | `docs/plans/2026-08-23-pg-cordis-development.md:142-150` |
| The fifth required proof is shared by P03 and P04: emit-before-wait, duplicate events, retry, and lease expiry still use one queue | `docs/plans/2026-08-23-pg-cordis-development.md:62` |
| D4 A places claim, log checkpoint, sleep, scoped event, and task-level retry in the kernel | `docs/decisions/2026-08-23-pending.md` D4; `docs/analysis/2026-08-23-i-architecture-snapshot.md` §4 |
| Retry state belongs in the kernel; retry curves are parameters rather than plugin-specific hard-coded behavior | `docs/decisions/2026-08-23-pending.md` D4 |
| `MAX_RECOVERY_ATTEMPTS_EXCEEDED` is the D4-named dead-letter reason | `docs/decisions/2026-08-23-pending.md` D4 |
| A second queue and an Absurd-style new run row per retry are prohibited | `docs/decisions/2026-08-23-pending.md`; `docs/analysis/2026-08-23-i-architecture-snapshot.md` §§4, 9 |

D1–D9 and architecture snapshot §4 remain closed. This plan selects only P04 implementation details.

P06’s `retry_class` values—`replayable`, `idempotent`, and `non_retryable`—classify tool replay safety. P04 functions must not read `cordis.plugin_catalog`, derive a jobs retry curve from `retry_class`, or reference P06 objects. A trusted producer or future enqueue API may choose the generic jobs-row retry policy based on higher-level policy, but that mapping is outside P04.

#### F protocol contract

`docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` is semantic ordering, not product DDL:

- `sleep(token, until)` appends `run/sleep`, sets `SLEEPING`, stores `available_at = until`, and clears ownership.
- `fail(token, reason)` either retries or becomes terminal; a requeued incomplete step retains the same logical `step_name`.
- `release_stale` converts an expired `RUNNING` claim into retry/terminal recovery and appends `run/claim_timeout`.
- The scheduler view includes `RUNNING → SLEEPING`, timer eligibility, `RUNNING → ERROR|retry`, and `WAITING → PENDING` by event or timeout.
- Emit and timeout waking the same wait is illegal.
- Jobs status remains scheduler eligibility rather than historical truth.

The older sketch’s generic claim predicate included due `WAITING` and `SLEEPING`. P03 subsequently locked the wait-specific rule: `WAITING` cannot be claimed directly because its resolution must acquire the event row first. P04 therefore adopts direct due-`SLEEPING` claim only.

#### P01 state and mutation points

`sql/0001_p01_claim.sql` already provides:

- one `cordis.jobs` row per unique `run_id`;
- statuses `PENDING`, `RUNNING`, `WAITING`, `SLEEPING`, `DONE`, and `ERROR`;
- `attempt integer NOT NULL DEFAULT 1` with `attempt >= 1`;
- `available_at timestamptz NOT NULL DEFAULT '-infinity'`;
- claim fields present exactly while `RUNNING`;
- terminal `completed_at` present exactly for `DONE` and `ERROR`;
- `jobs_ready_idx`, currently restricted to `PENDING`;
- `jobs_stale_claim_idx`, restricted to `RUNNING`;
- PENDING-only `claim_job`;
- stale recovery that always increments `attempt` and immediately returns the row to `PENDING`;
- terminal-only `fail_claim(uuid,jsonb)`;
- claim-fenced `renew_claim`, `yield_claim`, `complete_claim`, and `fail_claim`.

P01 deliberately reserved `WAITING` and `SLEEPING` without implementing them. Its deep plan explicitly assigns P04 permission to revise `fail_claim`, stale recovery, and claim eligibility while retaining the token fence.

#### P02 log ownership

`sql/0002_p02_log.sql` owns:

- append-only `cordis.agent_steps`;
- the sole direct `INSERT INTO cordis.agent_steps`, inside `cordis.emit_step`;
- `emit_step_claimed` and `checkpoint`, which fence a live jobs claim before calling `emit_step`;
- reserved kinds including `run/sleep`, `run/wake`, and `run/claim_timeout`;
- `next_step_name`, which keeps the latest LLM step name until a later `tool` or `final` completes it;
- `run_state`, which counts only `llm` rows as `steps_used`.

P04 must call `cordis.emit_step`; it must not insert, update, or delete `agent_steps` directly. P04 does not add a second log writer or a new retry event kind.

#### P03 wait/event handoff

`sql/0003_p03_wait_event.sql` supplies:

- `run_events`, keyed by `(event_scope_id, event_name)`, with a payload-NULL first-write fence;
- `run_waits`, one active wait per `run_id`, with `await_id`, nullable `deadline`, and a pointer to the `run/await` log row;
- `await_event`, which locks event → jobs → wait, appends `run/await`, enters `WAITING`, clears the claim, and deliberately leaves `jobs.available_at` unchanged;
- `emit_event`, which locks event → jobs → wait, appends canonical `event/emit` plus one `run/wake`, returns matching jobs to `PENDING`, sets `available_at` to emit time, and deletes active waits;
- an `awaiting` log projection matched by `await_id`.

P04 must use exactly the same lock order for timeout resolution. It must not copy `run_waits.deadline` onto `jobs.available_at`, claim `WAITING` directly, or implement a second wait-resolution representation.

P03 accepted deadlines exactly as supplied:

- SQL `NULL`;
- past timestamps;
- `-infinity`;
- `+infinity`.

P04 owns their timer semantics.

#### SQL tree and test harness

The numbered source order after P04 is:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0004_p04_sleep_retry.sql
0006_p06_plugin_catalog.sql
```

A truncated tree ending at `0004` reports `p04`. The full tree executes `0006` afterward and reports `p06`.

Tests continue to use:

- `run_apply`;
- `psql`;
- `psql_session`;
- `load_apply_module`;
- existing embedded PostgreSQL from `tests/conftest.py`.

No new loader, package, database client, server fixture, or apply script is needed.

### Existing responsibilities and P04 extensions

| Component | Current responsibility | P04 extension |
|---|---|---|
| `cordis.jobs` | Scheduler eligibility, ownership, attempt, available time, terminal scheduler fields | Add persisted retry limits/curve; add sleep, retry, timeout-resume, and exhausted-recovery transitions |
| `cordis.claim_job` | Reap stale claims, then claim one due `PENDING` row | Resolve due waits, apply revised stale recovery, then claim due `PENDING` or `SLEEPING` |
| `cordis.release_stale` | Expired `RUNNING` → immediate `PENDING`, attempt+1 | Log timeout; retry to `SLEEPING` with backoff or terminally dead-letter |
| `cordis.fail_claim` | Live `RUNNING` → terminal `ERROR` | Use jobs-row retry policy; retry to `SLEEPING` or terminally dead-letter |
| `cordis.emit_step` | Sole direct log insert | Reused for all P04 history |
| `cordis.next_step_name` | Fold latest incomplete LLM step | Reused unchanged; P04 retry rows carry no `step_name` |
| `cordis.run_state` | Log projection including P03 `awaiting` | Reused unchanged; timeout `run/wake` closes an await by matching `await_id` |
| `cordis.run_waits` | Active event waits and deadline storage | Scanned by the new bounded timeout resolver |
| `cordis.emit_event` | First-write event resolution | Reused unchanged; event-row locking serializes it against timeout |
| P06 plugin catalog | Tool metadata and replay classification | No P04 dependency or lookup |

### Current end-to-end gaps

Before P04:

```text
RUNNING --wait--> WAITING
  → exact event emit can recover it
  → deadline alone does nothing

RUNNING --fail_claim--> ERROR
  → no retry policy or backoff

RUNNING --lease expiry--> PENDING
  → attempt increments
  → no backoff, timeout log, or maximum-attempt terminality

SLEEPING
  → accepted by the table constraint
  → never produced by a product verb
  → never claimed
```

After P04:

```text
RUNNING --sleep_claim--> SLEEPING
SLEEPING + due --claim_job--> RUNNING

RUNNING --fail_claim, retries remain--> SLEEPING
RUNNING --fail_claim, exhausted--> ERROR

RUNNING + expired --release_stale, retries remain--> SLEEPING
RUNNING + expired --release_stale, exhausted--> ERROR

WAITING + due deadline --resolve_due_waits--> PENDING
WAITING + event emit -----------------------> PENDING
```

All paths mutate the same jobs row. No transition inserts another scheduler row.

### Why this remains a targeted change

P01 already contains every scheduler column needed for timing and ownership, while P02 and P03 already provide the log and wait/event extension points. P04 needs two small jobs configuration fields, two indexes, three new functions, and three later-file function replacements. A broader jobs/log/event refactor would duplicate locked responsibilities and create migration risk without adding correctness.

---

## 3. Design

### Resolved decisions

#### 1. Retry configuration is persisted on each jobs row

Add:

- `max_attempts integer DEFAULT 3`, nullable;
- `retry_policy jsonb NOT NULL` with the default exponential policy described below.

`max_attempts` is retry state configuration and remains a first-class scheduler field. The curve stays a parameter object so paradigms can choose a generic curve without adding plugin-specific columns.

`max_attempts = 3` means three total execution attempts: initial attempt 1 plus at most two retries. Explicit SQL `NULL` means unlimited retries subject to the representational ceiling of the `integer` attempt column.

The trusted producer sets these fields when inserting the jobs row. P04 adds no enqueue or policy-mutation verb. P04 runtime functions read but never rewrite the policy. Direct policy changes after execution begins are unsupported out-of-band mutation until a future enqueue/configuration API defines that lifecycle.

**Rationale:** stale recovery must use the same policy even when performed by a different worker; passing policy only to `fail_claim` would leave `release_stale` unable to reproduce the task’s configured behavior.

**Rejected:**

- Pass a retry policy only as a new `fail_claim` argument: lease recovery would not know the same policy.
- Derive the curve from P06 `retry_class`: tool replay safety is not task retry scheduling.
- Store policy only in an external plugin table: that would make kernel recovery depend on P06/P19 availability.
- Add separate base/factor/cap columns: JSONB keeps the generic curve extensible while `max_attempts` remains an explicit kernel state limit.

#### 2. Default retry policy is deterministic exponential backoff

Exact default:

```json
{
  "kind": "exponential",
  "base_seconds": 30,
  "factor": 2,
  "max_seconds": 86400
}
```

Supported `kind` values:

- `none`;
- `fixed`;
- `exponential`.

Defaults for omitted policy fields are the same values above. For `fixed`, the delay is `min(base_seconds, max_seconds)`. For `none`, it is zero. For `exponential`, the failed attempt `a` produces:

```text
min(max_seconds, base_seconds × factor^(a - 1))
```

Therefore failures of attempts 1, 2, and 3 under the default policy schedule 30, 60, and 120 seconds respectively.

There is no jitter. The delay is deterministic so replay, tests, and operator reasoning do not depend on process-local randomness.

**Rationale:** this matches the selected Absurd morphology while keeping its curve as row data rather than hard-coding plugin policy.

**Rejected:**

- Immediate retry by default: it creates hot failure loops.
- Jitter in the kernel: it makes deterministic tests and replay harder and belongs in higher-level policy if later required.
- Unbounded exponential arithmetic: the 86,400-second cap prevents timestamp/interval growth and retry starvation.
- Absurd’s separate 60-second fixed default: P04 has one documented 30-second base across fixed and exponential modes.

#### 3. `cordis.retry_delay_seconds(jsonb,integer)` is the single curve evaluator

New interface:

```text
cordis.retry_delay_seconds(
    p_strategy jsonb,
    p_attempt  integer
) RETURNS double precision
```

Properties:

- `LANGUAGE plpgsql`;
- `IMMUTABLE`;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`;
- synchronous;
- raises on malformed input;
- never returns less than 0 or more than 86,400.

Validation:

- `p_strategy` must be a non-null JSON object;
- unknown top-level keys are rejected;
- `kind` must be absent or one of `none|fixed|exponential`;
- supplied numeric fields must be JSON numbers;
- `base_seconds` and `max_seconds` must be finite and within `[0, 86400]`;
- `factor` must be finite and at least `1`;
- `p_attempt` must be at least `1`;
- cast/range errors are caught and re-raised as `invalid_parameter_value`.

Exponential evaluation must cap before evaluating an exponent known to exceed the cap, avoiding overflow for very large attempt values. The helper runs in O(1) time and O(1) space.

The jobs retry-policy constraint invokes this immutable helper with attempt 1, making malformed persisted policies impossible through normal inserts/updates.

**Rationale:** both explicit failure and stale recovery need exactly the same validated calculation.

**Rejected:**

- Duplicate calculations in `fail_claim` and `release_stale`: they could diverge.
- A policy validator plus a second delay function: one immutable evaluator is sufficient.
- A PL/pgSQL state-transition helper callable without a token: that would expose an unsafe path around claim fencing.

#### 4. Sleep uses a new claim-fenced `sleep_claim` verb

New interface:

```text
cordis.sleep_claim(
    p_claim_token uuid,
    p_until       timestamptz
) RETURNS boolean
```

Properties:

- `LANGUAGE plpgsql`;
- `VOLATILE`;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`.

Validation:

- `p_until` must be non-null and finite;
- a finite past timestamp or the current timestamp is accepted and becomes immediately claimable;
- `+infinity` and `-infinity` are rejected with `invalid_parameter_value`;
- after timestamp validation, a null, unknown, expired, or non-running token returns `false`.

Algorithm:

1. Capture `clock_timestamp()`.
2. Lock the exact jobs row with a predicate on `claim_token`, `status='RUNNING'`, and `claim_expires_at > captured`.
3. If no row matches, return `false`.
4. Append `run/sleep` through `cordis.emit_step`.
5. Update the same locked row to:
   - `status = 'SLEEPING'`;
   - `available_at = p_until`;
   - all claim fields null;
   - `completed_at = NULL`;
   - `result = NULL`;
   - `error = NULL`;
   - `attempt` unchanged.
6. Require one transitioned row; an impossible mismatch raises `object_not_in_prerequisite_state`.
7. Return `true`.

The function does not call `emit_step_claimed`: it already owns a stronger multi-effect transaction, derives `run_id` from the locked jobs row, and must append history before releasing ownership. `emit_step_claimed` would repeat the lease update and requires a caller-supplied run ID.

**Rationale:** the P03 pattern—lock/fence, append through `emit_step`, then release ownership—keeps history and scheduler state atomic without duplicating the direct log writer.

**Rejected:**

- `emit_step` before acquiring the jobs fence: a lost worker could append sleep history.
- A single `emit_step_claimed` call followed by an unfenced status update: it obscures the multi-object invariant and performs redundant ownership work.
- Reusing `yield_claim` with future `available_at`: yield and sleep have different history and status.
- Infinite sleep: without a P04 cancel verb it would be an unrecoverable scheduler state.

#### 5. Due sleeping rows are claimed directly; no ticker changes them to PENDING

`claim_job` will select rows satisfying:

```text
status IN (PENDING, SLEEPING)
AND available_at <= captured claim time
```

It must never select `WAITING`.

A due `SLEEPING` row moves directly to `RUNNING` in the claim transaction. There is no separately visible `SLEEPING → PENDING` ticker. The timer edge is represented by a `run/wake` append immediately before the locked row is changed to `RUNNING`.

The existing `jobs_ready_idx` is dropped and recreated in `0004` under the same name and ordering, with a partial predicate covering `PENDING` and `SLEEPING`. P01-only trees retain the original PENDING-only index.

**Rationale:** direct claim is one indexed operation, avoids a write-only ticker, and follows the selected Absurd shape without copying its second queue.

**Rejected:**

- A SLEEPING-to-PENDING sweep: it adds another maintenance transition and write amplification without improving exclusivity.
- Treat all future retries as future-dated PENDING: it loses the explicit sleeping scheduler state.
- Claim due `WAITING`: wait resolution requires the P03 event lock and active-wait fence.

#### 6. A timer wake is logged when `claim_job` claims a sleeping row

For a selected `SLEEPING` candidate, `claim_job` captures the prior `available_at`, appends `run/wake`, then changes the locked row to `RUNNING` and returns it.

If the wake append or jobs update fails, the whole claim rolls back and the row remains `SLEEPING`.

A PENDING row does not receive a timer wake. In particular, a wait timeout already appends its own `run/wake` while changing `WAITING → PENDING`; the subsequent claim must not append another wake.

**Rationale:** `run/sleep` needs a matching historical wake while the jobs status remains only scheduler state.

**Rejected:**

- Log no wake for sleep: the append-only history would show an unmatched timer suspension.
- Append wake in a separate ticker transaction: it creates a log/status split and a second timing mechanism.

#### 7. `fail_claim(uuid,jsonb)` is revised in place with the same signature

Before and after identity:

```text
cordis.fail_claim(uuid,jsonb) RETURNS boolean
```

P04 uses `CREATE OR REPLACE FUNCTION` in `0004`; it does not drop the identity or add a parallel failure verb.

Behavior changes from “always terminal” to “retry when another attempt is available, otherwise terminal.” The persisted jobs policy supplies parameters, so no overload or JSON policy argument is needed.

Validation remains:

- SQL NULL `p_reason` raises `invalid_parameter_value`;
- JSON `null` remains a valid JSONB reason;
- a null, unknown, expired, or non-running token returns `false`.

**Rationale:** P01 explicitly reserved this extension point, and keeping the identity preserves every caller while unifying failure under one state machine.

**Rejected:**

- Add `retry_claim` and leave `fail_claim` terminal: callers would need to choose between parallel state paths.
- Add a defaulted overload: PostgreSQL function resolution and current catalog-name assertions would become unnecessarily complex.
- Put policy inside `p_reason`: it conflates failure data with scheduler configuration.

#### 8. Recoverable failure always enters `SLEEPING`

For a live failed attempt `a`:

1. Compute `next_attempt = a + 1`.
2. Retry is allowed when:
   - `max_attempts IS NULL` and `a` is below the maximum representable integer; or
   - `next_attempt <= max_attempts`.
3. Compute delay from `retry_policy` and failed attempt `a`.
4. Set `retry_at = captured + delay`.
5. Append a retry-backoff `run/sleep`.
6. Mutate the same jobs row:
   - `status = 'SLEEPING'`;
   - `attempt = next_attempt`;
   - `available_at = retry_at`;
   - claim fields null;
   - `completed_at = NULL`;
   - `result = NULL`;
   - `error = p_reason`.

Even a zero-second retry uses `SLEEPING`; it is immediately due and can be claimed directly. `jobs.error` is a non-authoritative current-failure cache while sleeping and is cleared by the next successful claim. The canonical retry history is the `run/sleep` row.

**Rationale:** one state represents all timer-gated recovery and feeds the same due-sleep claim path.

**Rejected:**

- Future-dated `PENDING`: it uses PENDING for a row that is intentionally sleeping.
- PENDING for zero delay and SLEEPING otherwise: two equivalent retry paths complicate tests and observation.
- Insert a new jobs row like Absurd: `jobs.run_id` is unique and the one-queue contract forbids it.

#### 9. `jobs.attempt` is the shared recovery-attempt counter

Exact semantics:

- initial row: `attempt = 1`;
- ordinary yield: unchanged;
- requested sleep: unchanged;
- wait and wait timeout: unchanged;
- claim of PENDING/SLEEPING: unchanged;
- recoverable explicit failure: increment by one;
- recoverable lease timeout: increment by one;
- terminal exhaustion: retain the current attempt because no next execution attempt is created.

A null `max_attempts` means unlimited retries only while another `integer` attempt can be represented. At `2147483647`, recovery terminally dead-letters rather than overflowing.

**Rationale:** D4 names one attempt column, and P01 already increments it for lease recovery.

**Rejected:**

- Separate lease and task-failure counters: it requires another column and makes maximum recovery attempts ambiguous.
- Increment on every claim or yield: attempt is recovery, not ordinary scheduling.
- Increment on terminal exhaustion: that would record an attempt that never ran.

#### 10. Exhaustion uses one canonical dead-letter envelope

When no next attempt is permitted, explicit failure and stale recovery both append an `error` row and update `jobs.error` to:

```json
{
  "reason": "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
  "message": "maximum recovery attempts exceeded",
  "failure_kind": "task_failure | claim_timeout",
  "last_failure": "<original JSON value>",
  "attempt": 3,
  "max_attempts": 3
}
```

For explicit unlimited policy exhausted only by the integer ceiling, `max_attempts` is JSON null and the message may additionally state that the attempt counter cannot advance; the `reason` remains the D4-locked value.

Terminal jobs mutation:

- `status = 'ERROR'`;
- claim fields null;
- `result = NULL`;
- `error = dead-letter envelope`;
- `completed_at = captured`;
- `attempt` unchanged;
- `available_at` unchanged because terminal rows are not eligible.

The terminal `error` append occurs before the jobs mutation in the same transaction. Existing `run_state` therefore reports `error` after commit.

Recoverable failure must not append kind `error`, because P03’s current `run_state` gives any error row terminal precedence.

**Rationale:** the same discriminator and shape make explicit failure and lease exhaustion observable through one contract without changing `run_state`.

**Rejected:**

- Store only the original reason: it does not distinguish recovery exhaustion.
- Append `error` for each recoverable attempt: the current fold would permanently project the run as terminal.
- Add a new `run/retry` kind: `run/sleep` already represents the durable backoff state and avoids replacing P02’s kind constraints and append validators.

#### 11. `release_stale(text,integer)` is revised to use the same policy

Identity remains:

```text
cordis.release_stale(
    p_run_id text DEFAULT NULL,
    p_limit  integer DEFAULT 100
) RETURNS integer
```

Its return value becomes the number of expired claims resolved, whether each row retried or became terminal.

For every selected expired `RUNNING` row, ordered by `claim_expires_at, job_id` and locked with `FOR UPDATE SKIP LOCKED`:

1. Build the timeout reason from the old token, worker, expiry, and current attempt.
2. Append `run/claim_timeout`.
3. Apply the same retry-permitted test and delay helper as `fail_claim`.
4. If retrying, append retry-backoff `run/sleep` and move the same row to `SLEEPING`.
5. If exhausted, append `error` and move the row to terminal `ERROR`.
6. Clear the old ownership fields in either branch.

The stale timeout itself is historical even when the same failure terminally exhausts recovery, so terminal stale recovery appends `run/claim_timeout` followed by `error`.

**Rationale:** claim timeout is a task recovery failure, not a special unlimited requeue path.

**Rejected:**

- Preserve immediate PENDING stale recovery: it bypasses configured backoff.
- Always requeue stale claims: it makes `max_attempts` ineffective for crashed workers.
- Call revised `fail_claim` with the expired token: the live-token fence must reject expired ownership.
- Use a different stale retry curve: one jobs row owns one recovery policy.

#### 12. Wait deadlines use a standalone bounded resolver called by `claim_job`

New interface:

```text
cordis.resolve_due_waits(
    p_run_id text DEFAULT NULL,
    p_limit  integer DEFAULT 100
) RETURNS integer
```

Properties:

- `LANGUAGE plpgsql`;
- `VOLATILE`;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`.

Validation:

- a non-null `p_run_id` must not be blank;
- `p_limit` must be positive;
- malformed inputs raise `invalid_parameter_value`.

The function captures its own `clock_timestamp()`. It does not accept caller-supplied “now,” preventing callers from resolving future waits early.

`claim_job` invokes `resolve_due_waits(p_run_id, 100)` before claiming. Operators or future workers may also invoke it directly. There is no background process; if no worker polls and no explicit resolver runs, time passing alone does not execute SQL.

A partial deadline index is added:

```text
run_waits_deadline_idx
  on deadline, event_scope_id, event_name, run_id
  where deadline is not null
```

**Rationale:** timeout is maintenance analogous to stale reap and composes naturally with polling claimers.

**Rejected:**

- Copy deadline into `jobs.available_at`: P03 decision 12 deliberately keeps WAITING separate from SLEEPING.
- Claim WAITING when deadline is due: it bypasses event serialization and wait deletion.
- Add a background worker, `pg_cron`, LISTEN/NOTIFY, or a second scheduler.
- Resolve every due wait without a limit: one claim call must not perform unbounded maintenance.

#### 13. Due deadline semantics are readiness-based, not strict event precedence

Deadline selection is:

```text
deadline IS NOT NULL
AND deadline <= captured
```

Consequences:

- a past finite deadline resolves on the first sweep;
- `-infinity` resolves on the first sweep;
- `+infinity` never becomes due;
- SQL `NULL` never times out;
- equality with captured time is due.

Once due, timeout and emit compete for the event-row lock. The first transaction to acquire and complete the P03 fence wins. A due timestamp does not retroactively force timeout to beat an event transaction that acquired the event lock first.

**Rationale:** P03’s event row already provides a complete single-winner serialization point; strict deadline priority would require replacing `emit_event` with a second deadline-checking branch.

**Rejected:**

- “Timeout always wins after wall clock crosses deadline”: P03 `emit_event` would need to duplicate timeout resolution, increasing lock and behavior surface.
- “Emit always wins if an event exists eventually”: that makes stored deadlines ineffective.
- Reject P03’s historical past or infinite values during migration: they were accepted deliberately and must receive defined semantics.

#### 14. Timeout resolution reuses the exact P03 lock order and fence

For each candidate snapshot row, ordered by deadline, event key, and run ID:

1. Read candidate identity without locking `run_waits`.
2. Lock `run_events(event_scope_id,event_name) FOR UPDATE`.
3. Lock `cordis.jobs(run_id) FOR UPDATE`.
4. Lock `cordis.run_waits(run_id) FOR UPDATE`.
5. Revalidate:
   - the wait still exists;
   - `await_id` and event key match the candidate;
   - deadline is still non-null and due;
   - jobs status is exactly `WAITING`;
   - all claim fields are null.
6. Append timeout `run/wake`.
7. Update jobs to `PENDING`, set `available_at = captured`, and clear terminal result/error fields.
8. Delete `run_waits` by both `run_id` and `await_id`.
9. Increment the return count.

If the wait disappeared while the resolver was waiting for the event lock, that is the normal emit-winner case and the candidate is skipped. If the same active wait remains but event/jobs/wait state is inconsistent, raise `object_not_in_prerequisite_state`; the resolver invocation rolls back rather than silently committing partial maintenance.

The event row remains un-emitted when timeout wins. A later emit may still commit the event and return `woken_count = 0`; it cannot append a second wake for the deleted await.

**Rationale:** this is the only lock order proven by P03 and directly enforces `WAITING + await_id` as the resolution fence.

**Rejected:**

- Lock `run_waits` first because it supplies the event key: that creates a wait/jobs/event inversion.
- Delete the wait before locking jobs: it permits partial visibility.
- Treat an emitted event plus an active wait as a normal timeout: that would conceal a P03 invariant violation.

#### 15. Timeout and timer wakes reuse `run/wake` with explicit discriminators

P04 does not add another wake kind.

- P03 event wakes remain identified by `source_run_id` and `source_seq`.
- P04 timeout wakes include `wake_reason = 'wait_timeout'` and the same `await_id`.
- P04 sleeping timer wakes include `wake_reason = 'sleep_deadline'` and no `await_id`.

`run_state` already matches a wait wake by `await_id`, so timeout wakes close the latest await without changing the projection function. Sleep wakes cannot accidentally close an await because they carry no `await_id`.

**Rationale:** one wake kind represents the scheduler edge while payload fields identify its cause.

**Rejected:**

- Add `run/timeout` or `run/sleep_wake`: it requires expanding P02’s closed kind checks and validators.
- Reuse event wake source fields with null values: absence is less explicit than a cause discriminator.
- Put a fake event payload on timeout: no event was emitted.

#### 16. P04 adds no private SQLSTATE

P04 uses:

- `invalid_parameter_value` for malformed caller inputs and malformed retry policies;
- `object_not_in_prerequisite_state` for impossible cross-table or locked-state invariants;
- `false` for lost claim ownership.

No `P04xx` SQLSTATE is required because no inner subtransaction needs an exception solely for control flow, unlike P03’s `P0301` lock-release technique.

**Rationale:** existing standard SQLSTATEs distinguish contract errors, ownership loss, and persistent invariant failures.

**Rejected:** add a private timeout-race SQLSTATE; losing a normal event/timeout race is a zero-row skip, not an exception.

#### 17. Cancel remains out of scope

P04 adds no `CANCELLED` status and no force-cancel verb.

Named invariants do not require cancel:

- finite requested sleep eventually becomes eligible;
- finite/past wait deadlines can time out;
- null or `+infinity` waits remain intentionally event-only and can still be resolved by exact-key emit;
- retries are bounded by default;
- explicit unlimited retries are a producer policy choice.

**Rationale:** cancel is not part of the P04 skeleton or D4 five-piece and would require a separate status, jobs CHECK migration, wait/event lock semantics, and log contract.

**Rejected:** add cancellation merely to recover malformed direct SQL states; product functions and constraints should prevent those states instead.

---

### Component 1 — `sql/0004_p04_sleep_retry.sql`

**Kind:** numbered SQL migration and function replacement  
**Path:** `sql/0004_p04_sleep_retry.sql`  
**Applied:** after P03 and before P06

Required statement order:

1. create `cordis.retry_delay_seconds`;
2. add jobs retry fields;
3. add named jobs constraints;
4. retarget `jobs_ready_idx`;
5. add `run_waits_deadline_idx`;
6. add `cordis.resolve_due_waits`;
7. add `cordis.sleep_claim`;
8. replace `cordis.release_stale`;
9. replace `cordis.fail_claim`;
10. replace `cordis.claim_job`;
11. replace `cordis.get_schema_version` with `p04`.

All runtime writers are `SECURITY INVOKER` and pin `search_path` to `pg_catalog`. Every table, function, operator-sensitive builtin, and cast target must be schema-qualified where PostgreSQL syntax permits.

The file must contain:

- no top-level transaction control;
- no `CREATE EXTENSION`;
- no GRANT/REVOKE or role DDL;
- no public object;
- no P06 reference;
- no direct `agent_steps` insert;
- no comment beginning with `{`.

Replay uses `CREATE OR REPLACE FUNCTION`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, replay-safe named-constraint checks, `DROP INDEX IF EXISTS` followed by recreation for `jobs_ready_idx`, and `CREATE INDEX IF NOT EXISTS` for the new wait deadline index.

### Component 2 — Jobs retry schema

#### Added columns

| Column | Type | Null/default | Ownership and meaning |
|---|---|---|---|
| `max_attempts` | `integer` | nullable, `DEFAULT 3` | Maximum total execution attempts; SQL NULL means unlimited subject to integer capacity |
| `retry_policy` | `jsonb` | `NOT NULL`, default exponential object | Generic deterministic backoff curve used by both failure paths |

Existing rows receive the defaults during `0004` application. No existing status, claim, attempt, timing, result, or identity field is transformed.

#### Added named constraints

| Name | Contract |
|---|---|
| `jobs_max_attempts_check` | `max_attempts IS NULL OR max_attempts >= 1` |
| `jobs_retry_policy_check` | the immutable delay evaluator accepts `retry_policy` for attempt 1 and returns a value in `[0,86400]` |

Constraint installation must be replay-safe by checking `pg_constraint` for the exact name before adding it. An incompatible manually-created column or constraint is not migrated silently; apply must fail rather than drop runtime data.

#### Index changes

Replace `jobs_ready_idx` with the same ordering:

```text
priority DESC, available_at ASC, job_id ASC
```

and a predicate covering exactly `PENDING` and `SLEEPING`.

Add `run_waits_deadline_idx` with the shape specified in decision 12.

Keep `jobs_stale_claim_idx` unchanged.

### Component 3 — Retry policy evaluator

#### Input shape

```json
{
  "kind": "none | fixed | exponential",
  "base_seconds": 30,
  "factor": 2,
  "max_seconds": 86400
}
```

Allowed keys are exactly:

- `kind`;
- `base_seconds`;
- `factor`;
- `max_seconds`.

Omitted fields use defaults. JSON `null` for any supplied field is invalid rather than “use default”; omission is the default mechanism.

#### Calculation invariants

- `none` returns `0`;
- `fixed` returns `min(base_seconds, max_seconds)`;
- `exponential` uses the failed attempt, not the next attempt;
- every result is finite and between 0 and 86,400 inclusive;
- factor 1 produces constant delay;
- base 0 produces zero delay;
- no process time, random value, database row, or plugin metadata is read.

### Component 4 — Sleep and sleeping wake flow

#### `run/sleep` requested-sleep payload

```json
{
  "sleep_reason": "requested",
  "until": "<to_jsonb(timestamptz)>"
}
```

`until` must be serialized with `pg_catalog.to_jsonb(p_until)`. `step_name` is SQL NULL.

#### Retry-backoff `run/sleep` payload

```json
{
  "sleep_reason": "retry_backoff",
  "failure_kind": "task_failure | claim_timeout",
  "until": "<to_jsonb(timestamptz)>",
  "failed_attempt": 1,
  "next_attempt": 2,
  "failure": "<original JSON failure value>"
}
```

This payload is used by both revised failure paths. It is the durable record of a recoverable failure and its next eligibility time.

#### Sleeping timer `run/wake` payload

```json
{
  "wake_reason": "sleep_deadline",
  "scheduled_for": "<to_jsonb(previous available_at)>",
  "woken_at": "<to_jsonb(claim time)>"
}
```

It is appended only when a SLEEPING row is actually claimed. A due row skipped by `SKIP LOCKED` receives no wake until the winning claim transaction.

#### Thread/transaction context

All operations are synchronous inside the caller’s PostgreSQL transaction. There is no worker thread or timer. A rollback after `sleep_claim` restores the live RUNNING claim and removes the `run/sleep`. A rollback after claiming a sleeper removes its `run/wake` and restores `SLEEPING`.

### Component 5 — Explicit failure state machine

#### Before and after API

Before:

```text
fail_claim(uuid,jsonb) → live RUNNING always becomes terminal ERROR
```

After:

```text
fail_claim(uuid,jsonb) → live RUNNING becomes SLEEPING or terminal ERROR
```

The function returns:

- `true` if it owned and resolved the live claim;
- `false` for lost ownership;
- an exception for invalid `p_reason` or an invariant failure.

#### Recoverable branch

```text
source:
  live RUNNING jobs row
transform:
  read persisted max_attempts and retry_policy
  compute delay from current attempt
  append retry run/sleep
destination:
  same job_id and run_id
  SLEEPING, next attempt, retry_at, no claim
```

No `error` kind is appended.

#### Exhausted branch

```text
source:
  live RUNNING jobs row
transform:
  wrap last failure in canonical dead-letter envelope
  append terminal error
destination:
  same job_id and run_id
  ERROR, completed_at, no claim
```

#### Same-step invariant

P04 does not assign `step_name` to sleep, wake, timeout, or error rows. `next_step_name` therefore continues to inspect only the latest LLM and later `tool|final` rows:

- if the failed LLM-bearing step has no later `tool` or `final`, the next claim receives the same step name;
- if a tool/final already committed, that step was complete and `next_step_name` may advance.

Attempt number is never used as a step name.

### Component 6 — Stale-claim recovery

#### `run/claim_timeout` payload

```json
{
  "reason": "CLAIM_TIMEOUT",
  "message": "worker did not finish before claim expiry",
  "claim_token": "<expired UUID>",
  "claimed_by": "<worker id>",
  "claim_expires_at": "<to_jsonb(timestamptz)>",
  "attempt": 1
}
```

The token is already expired and is logged only as a historical fence identifier. `step_name` is SQL NULL.

The same object is supplied as the `failure` in a retry-backoff `run/sleep`, or as `last_failure` in the terminal dead-letter envelope.

#### Concurrency

`release_stale` captures one wall-clock timestamp for candidate eligibility and all transitions in that invocation. It processes at most `p_limit` rows with `FOR UPDATE SKIP LOCKED`.

A concurrent `renew_claim` can win only before the stale row is locked and revalidated. Once `release_stale` locks an expired row, the old token is resolved atomically. A later renew/yield/fail with that token returns false.

### Component 7 — Wait timeout resolution

#### Timeout `run/wake` payload

```json
{
  "await_id": "<UUID string>",
  "event_scope_id": "<opaque scope>",
  "event_name": "<name>",
  "wake_reason": "wait_timeout",
  "deadline": "<to_jsonb(timestamptz)>",
  "woken_at": "<to_jsonb(captured resolver time)>"
}
```

It contains no `source_run_id`, `source_seq`, or event payload because no event emission caused the wake.

#### State flow

```text
due run_waits row
  → event FOR UPDATE
  → jobs FOR UPDATE
  → wait FOR UPDATE
  → append timeout run/wake
  → jobs WAITING → PENDING, available_at = captured
  → delete active wait
```

Downstream observation:

- `run_state` changes from `awaiting` to `in-progress`;
- `claim_job` can claim the PENDING row;
- the old pre-wait token remains invalid;
- the event sentinel remains available for a later first emission.

#### Race outcomes

**Timeout wins:**

```text
resolver locks event
  → emit blocks
  → resolver wakes/deletes wait and commits
  → emit commits event with woken_count 0
```

Exactly one `run/wake` with that `await_id` exists.

**Emit wins:**

```text
emit locks event
  → resolver blocks
  → emit appends event wake, transitions job, deletes wait, commits
  → resolver sees missing wait and resolves zero rows
```

Exactly one event-source `run/wake` with that `await_id` exists.

### Component 8 — Revised claim flow

Exact logical order inside `claim_job`:

1. Validate worker, optional run ID, and lease as P01 does.
2. Call `resolve_due_waits(p_run_id, 100)`.
3. Call revised `release_stale(p_run_id, 100)`.
4. Capture a fresh claim timestamp.
5. Select one due `PENDING` or `SLEEPING` row using priority, available time, and job ID order with `FOR UPDATE SKIP LOCKED`.
6. If none exists, return zero rows.
7. If prior status was SLEEPING, append timer `run/wake`.
8. Update the exact locked row to RUNNING:
   - fresh UUID token;
   - requested worker;
   - lease expiry;
   - result and error cleared;
   - completed time null;
   - attempt and policy unchanged.
9. Require one updated row.
10. Return the updated jobs composite.

The maintenance sweeps and claim occur in the caller’s transaction. A caller must commit before long-running work.

### Component 9 — Lock ordering and deadlock analysis

#### Global order for wait-aware paths

```text
run_events row
→ jobs row(s), deterministic run order
→ run_waits row
→ log/status mutations
```

Both `emit_event` and `resolve_due_waits` use event `FOR UPDATE`. `await_event` uses event `FOR SHARE`.

#### Jobs-only paths

- `sleep_claim`: one RUNNING jobs row;
- `fail_claim`: one RUNNING jobs row;
- `release_stale`: expired RUNNING jobs rows in stale-index order;
- claim candidate: PENDING or SLEEPING jobs row.

They never request an event row after taking their jobs lock.

#### Transactions that already hold a RUNNING claim and call `emit_event`

As established by the P03 critique, such a transaction introduces a jobs → event edge. It still cannot deadlock with timeout fan-out:

- a claim-fenced writer can hold only a RUNNING row;
- timeout/emit fan-out targets only a WAITING row with null claim fields;
- these target sets are disjoint under `jobs_claim_fields_check`.

A `claim_job` transaction may retain event locks acquired by timeout maintenance before selecting a PENDING/SLEEPING candidate. It cannot then wait on a claim-held RUNNING row because RUNNING rows are not candidates.

#### Multiple timeout sweepers

Candidate ordering is:

```text
deadline, event_scope_id, event_name, run_id
```

Reconnecting... 1/5

# P04 — sleep 与任务级 retry 状态机

Date: 2026-08-24  
Status: **ready to implement**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P04  
Depends on: P01 and P03, implemented  
Parallel with: P06, P07, P19  
Primary deliverables: `sql/0004_p04_sleep_retry.sql`, retargeted `tests/test_p00_sql_source.py`, new `tests/test_p04_sleep_retry.py`

## Summary

P04 completes the kernel scheduler state machine on the existing `cordis.jobs` row. It adds a claim-fenced `cordis.sleep_claim(...)`, makes due `SLEEPING` rows directly claimable without a ticker, resolves P03 wait deadlines through a bounded `cordis.resolve_due_waits(...)` sweep using the existing **event row → jobs row → wait row** lock order, and revises the existing `fail_claim`, `release_stale`, and `claim_job` definitions from a new `0004` file. Retry policy is durable per jobs row: three total attempts by default, deterministic exponential backoff with defaults `30s × 2^(attempt−1)` capped at 86400 seconds, and `NULL max_attempts` meaning unlimited. Retry and lease recovery share the existing `jobs.attempt` counter, mutate the same jobs row and `run_id`, and become terminal `ERROR` with the required `MAX_RECOVERY_ATTEMPTS_EXCEEDED` dead-letter reason when no next attempt is allowed. All history is appended through P02’s existing `emit_step` or `emit_step_claimed`; P04 adds no direct writer, queue, background worker, plugin retry coupling, cancellation path, or apply mechanism.

---

## Goal

Implement the P04 contract from `docs/plans/2026-08-23-pg-cordis-development.md:142-150`:

- Add claim-fenced kernel sleep using the already-reserved `SLEEPING` status and `jobs.available_at`.
- Append `run/sleep` before clearing the claim.
- Make due `SLEEPING` rows eligible through the existing `claim_job`, without a separate ticker or queue.
- Resolve due P03 wait deadlines and guarantee that timeout and event emission cannot both wake one `await_id`.
- Revise task failure from always-terminal behavior to retry-or-terminal behavior.
- Persist retry parameters on the same jobs row so explicit failure and stale-lease recovery use one policy.
- Share the existing `attempt` counter between explicit failure recovery and lease recovery.
- Append `run/claim_timeout` for every stale lease processed.
- Produce terminal `ERROR` plus an `error` log row when attempts are exhausted.
- Preserve the same `job_id`, `run_id`, and incomplete `step_name` across recovery.
- Keep `cordis.jobs` as the only scheduler queue.
- Keep P06 `retry_class` independent from scheduler backoff.

P04 is complete when automated tests prove:

1. sleep intent, `SLEEPING`, wake time, and claim release commit or roll back together;
2. a due sleeper is claimed once and receives one timer `run/wake`;
3. past and `-infinity` wait deadlines time out on the first sweep, while `NULL` and `+infinity` do not;
4. emit and timeout races commit exactly one `run/wake` for an `await_id`;
5. explicit failure retries the same jobs row with deterministic backoff;
6. exhausted explicit failure becomes terminal with `MAX_RECOVERY_ATTEMPTS_EXCEEDED`;
7. stale claims use the same attempt/backoff/dead-letter policy and append `run/claim_timeout`;
8. the shared P03+P04 proof covers emit-before-wait, duplicate events, retry, and lease expiry while retaining one jobs queue.

---

P03 used `W27`–`W33`. P04 continues with `W34`–`W41`. P06’s `W60`–`W66` range is not reused.

## Execution index

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W34 | Add durable retry policy and curve evaluator | Existing and new jobs rows have validated policy defaults; the deterministic curve returns bounded delays; ready index covers PENDING and SLEEPING | `sql/0004_p04_sleep_retry.sql` | P01 | Medium |
| W35 | Add claim-fenced sleep | A live claim appends `run/sleep`, enters `SLEEPING`, stores `available_at`, and clears ownership atomically | `sql/0004_p04_sleep_retry.sql` | W34, P02 | Medium |
| W36 | Add wait-deadline resolution | Due waits use event→jobs→wait locking, append timeout `run/wake`, become PENDING, and are deleted once | `sql/0004_p04_sleep_retry.sql` | P03 | Large |
| W37 | Revise explicit failure | `fail_claim(uuid,jsonb)` retries or dead-letters under the row’s durable policy without changing its identity | `sql/0004_p04_sleep_retry.sql` | W34, P02 | Large |
| W38 | Revise stale recovery and claiming | Stale claims log and retry/dead-letter; claim piggybacks timeout/stale sweeps and claims due sleepers with one timer wake | `sql/0004_p04_sleep_retry.sql` | W34–W37 | Large |
| W39 | Advance and document the P04 marker | A tree ending at 0004 reports p04; the full tree ending at 0006 reports p06; README describes P04 state | `sql/0004_p04_sleep_retry.sql`, `sql/README.md` | W34–W38 | Small |
| W40 | Retarget current-tree and P01-era assertions | File/function lists, ready-index predicate, fail expectations, stale timing, and due-SLEEPING behavior match P04 | `tests/test_p00_sql_source.py`, `tests/test_p01_claim.py` | W34–W39 | Medium |
| W41 | Add P04 protocol and concurrency tests | Catalog, sleep, timeout race, retry, dead-letter, stale logging, shared attempts, replay, and one-queue proofs pass | `tests/test_p04_sleep_retry.py` | W34–W40 | Large |

---

## Background

### Skeleton and locked contracts

| Fact | Verified source |
|---|---|
| P04 adds `SLEEPING + available_at`, attempt/next-claim/terminal-fail state, parameterized retry curves, and must decide defaults and dead-letter naming | `docs/plans/2026-08-23-pg-cordis-development.md:142-150` |
| Shared proof row 5 is emit-before-wait, duplicate events, retry, and lease expiry while retaining one queue | `docs/plans/2026-08-23-pg-cordis-development.md:62` |
| D4 A puts claim, log checkpoint, sleep, scoped event, and task-level retry in the kernel | `docs/decisions/2026-08-23-pending.md`, D4 |
| Retry state is the jobs attempt/next-time/dead-letter state; `MAX_RECOVERY_ATTEMPTS_EXCEEDED` is the D4-named dead-letter reason | `docs/decisions/2026-08-23-pending.md`, D4 |
| Retry curves remain parameterized policy rather than plugin-specific kernel branches | `docs/decisions/2026-08-23-pending.md`, D4; `docs/analysis/2026-08-23-i-architecture-snapshot.md` §4 |
| There is one `cordis.jobs` queue; P03 side tables are not another scheduler | `docs/analysis/2026-08-23-i-architecture-snapshot.md` §4 and §9 |
| P06 `retry_class` classifies tool replay safety and does not configure task backoff | `docs/plans/P06-plugin-catalog-2026-08-23.md`; P06 contract summarized in the P04 scaffold |

D1–D9 and architecture snapshot §4 remain closed. P04 does not reinterpret P06 metadata, create a second queue, or copy Absurd’s per-attempt run-row insertion.

### F protocol semantics

`docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` is the semantic order, not a frozen SQL ABI.

| Fact | Verified source |
|---|---|
| Sleep changes RUNNING to SLEEPING, writes `available_at`, clears the claim, and logs `run/sleep` | F §3 sleep verb and §11 state machine |
| Failure becomes `ERROR` or requeues; an incomplete step keeps the same `step_name` | F §3 fail verb |
| Stale release is a failed claim/recovery path and logs `run/claim_timeout` | F §3 and §8 |
| Claim eligibility may include due SLEEPING rows | F §3 claim verb |
| Timeout and emit must not both wake the same wait | F §10 |
| Jobs status is claim eligibility, not historical run truth | F §11 |

P04 retains P03’s separate `WAITING` and `SLEEPING` states. It does not copy Absurd’s design in which both event waits and timer sleeps use one sleeping state and one `available_at` clock.

### What P01 already shipped

`sql/0001_p01_claim.sql` is the scheduler substrate P04 revises from a later numbered file:

- `cordis.jobs.status` already permits `PENDING`, `RUNNING`, `WAITING`, `SLEEPING`, `DONE`, and `ERROR` (`jobs_status_check`).
- `attempt integer NOT NULL DEFAULT 1` with `attempt >= 1`.
- `available_at timestamptz NOT NULL DEFAULT '-infinity'`.
- claim fields are present exactly for `RUNNING`.
- terminal states require `completed_at`; nonterminal states forbid it.
- `jobs.run_id` and `jobs.claim_token` are unique.
- `jobs_ready_idx` currently covers only `status='PENDING'`.
- `claim_job` selects only due PENDING rows.
- `release_stale` currently requeues every expired RUNNING row immediately, increments `attempt`, and appends no log.
- `yield_claim` preserves `attempt`.
- `fail_claim` currently has the actual catalog identity:

  ```text
  cordis.fail_claim(uuid,jsonb)
  ```

  It always changes a live claim to terminal `ERROR`, does not increment `attempt`, does not write `available_at`, and appends no log.

The three-argument `fail_claim(p_run_id, p_claim_token, p_error)` wording in the task prompt is not present in the selected SQL. The selected source is authoritative: P04 revises the existing two-argument identity.

The P01 plan explicitly reserves P04’s right to revise `fail_claim` while retaining token fencing and to revise claim eligibility later.

### What P02 already shipped

`sql/0002_p02_log.sql` provides:

- append-only `cordis.agent_steps`, keyed by `(run_id, seq)`;
- existing kinds `run/sleep`, `run/wake`, and `run/claim_timeout`;
- `cordis.emit_step`, the sole direct `INSERT INTO cordis.agent_steps`;
- `cordis.emit_step_claimed`, which extends a live claim and delegates to `emit_step`;
- `next_step_name`, which advances only when the latest LLM step has a later `tool` or `final` for that step;
- `run_state`, whose `steps_used` counts only `llm`.

P04 does not add a direct log writer or a new event kind. It uses:

- `emit_step_claimed` for explicit sleep, while the claim is live;
- `emit_step` after P04 itself has locked/fenced a jobs row for failure, timeout, or stale recovery.

A retry log must not use `error`, because P03’s `run_state` gives any `error` terminal precedence. Retry is represented by a `run/sleep` payload with `reason="retry"`; terminal exhaustion uses `error`.

### What P03 already shipped

`sql/0003_p03_wait_event.sql` supplies the timeout inputs and lock protocol:

- `run_waits` has one active wait per `run_id`, an active-unique `await_id`, an event key, and nullable `deadline`.
- Deadline is stored exactly as supplied; past values and `±infinity` are accepted.
- Suspended wait leaves `jobs.available_at` unchanged.
- `await_event` takes the event row before the jobs row.
- `emit_event` takes the event row `FOR UPDATE`, then each jobs row, then its wait row.
- Emit revalidates `WAITING`, `await_id`, and null claim fields before wake.
- Event wake appends `run/wake`, changes the job to due `PENDING`, and deletes the wait atomically.
- An event row’s SQL-NULL payload is the not-emitted sentinel.
- Event wake payloads contain `await_id`, event key, and canonical `source_run_id`/`source_seq`.

P04 timeout must use the same event→jobs→wait order and the same `WAITING + await_id` fence. It must not introduce a parallel timeout flag, copy deadline into jobs, or claim WAITING directly.

The P03 critique explicitly identifies P04 timeout as the sanctioned recovery path for a finite-deadline waiter that is otherwise unreachable to claim, yield, fail, complete, renew, or stale release.

### SQL tree and tests

Current product order is:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0006_p06_plugin_catalog.sql
```

P04 adds:

```text
0004_p04_sleep_retry.sql
```

Numeric order makes the version sequence:

```text
0000 → p00
0001 → p01
0002 → p02
0003 → p03
0004 → p04
0006 → p06
```

A P04-only test tree excludes `0006`; the full product continues to report `p06`.

Tests reuse only `run_apply`, `psql`, `psql_session`, and, for source inspection, `load_apply_module`. No new PostgreSQL client, server fixture, apply script, or package is introduced.

### Neighbor prior art: shape only

Absurd demonstrates useful morphology:

- direct claim of due pending or sleeping rows without a ticker;
- exponential delay with base 30, factor 2, exponent `attempt−1`, and 86400-second cap;
- stale-lease failure sharing the same attempt counter;
- event-row serialization for emit/timeout races.

P04 does **not** copy:

- a new run row for every retry;
- a second queue or dynamic queue tables;
- one state for both event waits and timer sleeps;
- wait deadlines copied into the scheduler row;
- plugin-specific retry curves;
- cancellation or max-duration behavior.

---

## Current-state analysis

### Existing responsibilities and ownership

| Component | Current responsibility | P04 extension |
|---|---|---|
| `cordis.jobs` | Sole scheduler row, claim ownership, attempt, eligibility time, terminal result/error | Adds durable retry policy; P04 performs sleep, retry, terminal exhaustion, and due-sleeper claiming |
| `cordis.claim_job` | Bounded stale reap, then one due PENDING claim | Also resolves due waits, applies revised stale recovery, and claims due PENDING or SLEEPING |
| `cordis.release_stale` | Expired RUNNING → immediate PENDING, attempt+1 | Logs timeout and applies retry/backoff/dead-letter policy |
| `cordis.fail_claim` | Live RUNNING → unconditional ERROR | Live RUNNING → retry or dead-letter using persisted policy |
| `cordis.agent_steps` | Historical source of truth | Receives sleep, timer wake, timeout wake, claim timeout, retry, and terminal error events through existing writers |
| `cordis.emit_step` | Sole direct append implementation | Reused after P04 holds the relevant jobs/event locks |
| `cordis.emit_step_claimed` | Claim-fenced append with lease extension | Reused by `sleep_claim` before claim release |
| `cordis.run_waits` | One active event wait per run, optional deadline | P04 deletes a due registration only after timeout wake and jobs transition |
| `cordis.run_events` | Event-key serialization and first-write fence | P04 locks the same row but does not mark the event emitted |
| `cordis.emit_event` | Event-first winner and fan-out wake | Remains unchanged; timeout races it on the same event row |
| `cordis.run_state` | Log-derived final/error/awaiting/in-progress projection | Remains unchanged; timeout wake closes an await and retry emits no terminal error |
| P06 plugin catalog | Tool/plugin execution metadata | No P04 read or dependency |

### Current control flow and blocking gaps

#### Sleep

`SLEEPING` is accepted by the jobs constraint but no product function creates it. P01’s claim predicate skips it even when `available_at` is due. There is no `run/sleep` emission path.

#### Wait timeout

P03 persists deadlines but no function reads them. A finite-deadline wait remains `WAITING` forever unless its event is emitted. Because the claim fields are null, all claim-owned verbs reject it, and stale release cannot see it.

#### Failure

A live `fail_claim` is always terminal. There is no backoff, max-attempt evaluation, dead-letter wrapper, or retry history.

#### Stale lease

`release_stale` increments the attempt and immediately requeues, independently of any max-attempt or backoff policy. It does not append `run/claim_timeout`.

### P04 end-to-end flow

```text
explicit sleep:
  live RUNNING claim
    → emit_step_claimed(run/sleep)
    → jobs SLEEPING + available_at=until + claim cleared
    → later claim_job sees due SLEEPING
    → jobs RUNNING + new token
    → emit_step(run/wake, wake_reason=sleep)

wait timeout:
  claim_job or maintenance call
    → resolve_due_waits
    → event row lock
    → jobs row lock
    → wait row lock
    → run/wake(wake_reason=timeout)
    → jobs WAITING→PENDING
    → delete run_waits
    → normal claim path

explicit failure:
  live RUNNING claim
    → lock/fence jobs row
    → evaluate current attempt and durable retry policy
    → either:
         run/sleep(reason=retry)
         + same jobs row PENDING|SLEEPING
         + attempt+1
       or:
         error(MAX_RECOVERY_ATTEMPTS_EXCEEDED)
         + same jobs row ERROR

lease expiry:
  release_stale
    → lock expired RUNNING row
    → run/claim_timeout
    → same retry/dead-letter decision as explicit failure
    → optional terminal error log
```

### Mutation points

P04 adds or revises exactly these mutation paths:

1. `sleep_claim`:
   - appends `run/sleep`;
   - changes one live `RUNNING` row to `SLEEPING`;
   - sets `available_at`;
   - clears claim ownership.

2. `resolve_due_waits`:
   - appends one timeout `run/wake`;
   - changes matching `WAITING` to due `PENDING`;
   - deletes the exact active wait.

3. `fail_claim`:
   - appends retry `run/sleep` or terminal `error`;
   - either increments attempt and requeues, or terminalizes.

4. `release_stale`:
   - appends `run/claim_timeout`;
   - applies the same retry decision;
   - appends `error` when terminal.

5. `claim_job`:
   - invokes bounded timeout and stale sweeps;
   - claims due PENDING or SLEEPING;
   - appends one timer `run/wake` only when the pre-claim status was SLEEPING.

6. retry-policy DDL and `jobs_ready_idx`:
   - add durable configuration;
   - broaden indexed claim eligibility to PENDING and SLEEPING.

No P04 function mutates P03 event payloads or writes `agent_steps` directly.

### Why this is a targeted extension

P01 already owns the queue and attempt column, P02 already owns all required log kinds and append behavior, and P03 already owns wait/event serialization. P04 needs one new numbered file that adds policy columns, three functions, and later definitions of three existing functions. A new retry service, policy table, queue, worker, event mechanism, or log abstraction would duplicate existing ownership and violate the locked architecture.

---

# Design

## Resolved decisions

| # | Decision | Rationale | Rejected alternatives |
|---:|---|---|---|
| 1 | Retry policy is durable on each `cordis.jobs` row as scalar columns: nullable `max_attempts` plus base/factor/cap fields. | Stale recovery has no caller-supplied policy, so explicit failure and lease recovery can share one policy only if it is stored with the scheduler row. Scalar columns provide constraint-checked values without a JSON policy parser. | Passing policy only to `fail_claim`, because `release_stale` could not reproduce it; a JSONB policy, because it adds validation/parser complexity; deriving it from P06 `retry_class`, which violates the tool/task boundary. |
| 2 | Default `max_attempts` is 3 total attempts, including the initial attempt. SQL NULL means unlimited. | Three attempts gives two recoveries, matches common task semantics, and makes the counter’s meaning explicit. NULL is the deliberate opt-in for unlimited recovery. | Default unlimited, which can leave permanently failing work cycling forever; “max retries” excluding the initial attempt, which would conflict with the existing attempt value starting at 1. |
| 3 | Backoff is deterministic exponential: `min(cap, base × factor^(attempt−1))`, with defaults base 30 seconds, factor 2, cap 86400 seconds, and no jitter. | It matches the selected prior-art shape, is easy to test/replay, and keeps the curve parameterized without putting plugin-specific branches in the kernel. | Hard-coded delays; randomized jitter, which makes deterministic protocol tests and projections harder; arbitrary curve kinds or executable policy. |
| 4 | `fail_claim(uuid,jsonb)` is revised in place with the same catalog identity. It reads policy from the locked jobs row. | Existing SQL callers remain source-compatible, stale recovery can use the same durable policy, and P01 explicitly reserved this P04 revision. | A new retry verb plus unchanged terminal `fail_claim`, which creates parallel failure paths; adding policy arguments and dropping the old function, which is unnecessarily breaking and still does not solve stale recovery. |
| 5 | Retry and explicit sleep use `SLEEPING` when their wake time is in the future; zero-delay retry uses due `PENDING`. | `SLEEPING` becomes an observable timer state instead of disguising backoff as future PENDING. Zero delay need not make a transient sleeping state. | Always future PENDING, which leaves the reserved SLEEPING state mostly unused; always SLEEPING, including zero delay, which adds a meaningless state transition. |
| 6 | `claim_job` directly claims due PENDING or SLEEPING rows. No SLEEPING→PENDING ticker is added. | Eligibility can be decided in the same `FOR UPDATE SKIP LOCKED` candidate statement, as allowed by P01 and F. It avoids another worker, table scan, or transition race. | A timer/background ticker; a separate wake queue; claiming WAITING directly, which violates P03’s event-lock requirement. |
| 7 | Claiming a due SLEEPING row appends `run/wake` with `wake_reason="sleep"` in the same transaction as the new claim. | The sleep interval has a durable close event and cannot produce a wake without a successful claim. The previous `available_at` is captured in the wake payload. | Waking sleepers in a preliminary ticker; omitting wake history; changing P03 event wake payloads retroactively. |
| 8 | `sleep_claim(uuid,text,timestamptz,integer)` uses one `emit_step_claimed` call, then changes the locked row to SLEEPING and clears ownership. | It reuses P02’s claim-aware append and guarantees `run/sleep` is durable before claim release. The explicit run ID matches `emit_step_claimed` and `await_event` patterns. | Direct log insertion; changing status before logging; a token-only API that first performs an unfenced run-ID lookup; emitting after the claim is cleared. |
| 9 | Wait deadlines are resolved by `resolve_due_waits(p_run_id DEFAULT NULL, p_limit DEFAULT 100)`, and `claim_job` calls that same function before stale reap and candidate selection. | There is one timeout mechanism usable both for explicit maintenance and ordinary worker polling. A bounded piggyback ensures progress without a background timer. | Timeout logic duplicated inside claim; an independent daemon; copying deadline into jobs; a second wait-resolution table or flag. |
| 10 | Timeout and emit use lock acquisition as the winner rule. A due deadline is eligible for timeout, but an event transaction that obtains the event-row lock first may still win. | PostgreSQL has no background clock edge; the event-row lock gives one atomic winner without rewriting P03 `emit_event`. This is precise and testable. | Timestamp-priority emit rewriting, which would broaden P04 into a replacement of P03 emission; allowing both outcomes to append wake; relying on notifications. |
| 11 | Due means `deadline IS NOT NULL AND deadline <= captured clock_timestamp()`. Past and `-infinity` are immediately due; `+infinity` and NULL are never due. | P03 deliberately stored all these values unchanged, so P04 must consume them rather than retroactively rejecting persisted rows. | Migrating deadlines onto jobs; rejecting old past/infinite values during apply; treating +infinity as due. |
| 12 | Timeout reuses kind `run/wake`, includes the same `await_id`, and is distinguished by `wake_reason="timeout"` plus deadline and wake time. | `run_state` already closes an await by matching `await_id`; a separate kind would require P02 CHECK and projection changes. | A new `run/timeout` kind; an `error` row, which would make timeout terminal; an event source pointer with no canonical emitted event. |
| 13 | `jobs.attempt` is the single shared execution-attempt number for explicit failure and stale-lease recovery. It increments only when a next attempt is created. | D4 names one attempt state, P01 already increments it for stale recovery, and splitting counters would need another schema and ambiguous limits. | Separate failure and lease counters; incrementing on ordinary yield, sleep, wait, or claim. |
| 14 | Exhaustion occurs when the current attempt is already `>= max_attempts`, or the integer counter cannot be incremented. The terminal row retains the last executed attempt number. | No nonexistent attempt should be recorded. Policy reduction below a current attempt must terminalize safely. | Incrementing to `max_attempts+1` before terminal failure; permitting integer overflow; resetting attempts after successful sleep or wait. |
| 15 | The terminal reason is an `error` payload and `jobs.error` object whose `name` is exactly `MAX_RECOVERY_ATTEMPTS_EXCEEDED`; the original cause is nested under `cause`. | It satisfies D4, preserves the initiating reason, and makes the log and scheduler terminal payload agree. | Storing only the raw last error; a separate dead-letter queue; a renamed reason. |
| 16 | Every stale lease appends `run/claim_timeout`. Recoverable stale leases use the same curve and attempt limit as `fail_claim`; exhausted stale leases additionally append terminal `error`. | Lease loss is one recovery source, not a special unlimited retry path. The timeout event remains durable even when the outcome is terminal. | Keeping immediate unconditional requeue; logging only terminal timeouts; using a separate stale-attempt budget. |
| 17 | P04 adds no new agent-step kind and no direct `agent_steps` writer. | Existing `run/sleep`, `run/wake`, `run/claim_timeout`, and `error` can represent every transition while preserving P02’s insert monopoly. | Adding `run/retry`; direct inserts for performance; treating `jobs.error` as historical truth. |
| 18 | P04 defines no private `P04xx` SQLSTATE. | Lost claims return false, stale candidate races skip, and invariant failures fit `object_not_in_prerequisite_state`. P03’s private code was needed to roll back a subtransaction and release an event lock; P04 has no equivalent branch. | Adding a private code without a distinct recovery contract. |
| 19 | Cancellation remains out of scope. | Timeout resolves finite waits, but D4 and the P04 parent contract do not include general cancellation. Null/+infinity waits and deliberate long sleeps remain durable until their event/time or later cancellation work. No P04 invariant requires a seventh status. | Adding CANCELLED, force-fail, or a general wake API; treating timeout as cancellation. |
| 20 | The full change is delivered in `0004_p04_sleep_retry.sql`; historical SQL remains unchanged. | Later numbered overrides are the repository’s migration mechanism. `0006` still wins the full-tree version marker. | Editing 0001/0002/0003; changing the loader or adding a manifest. |

---

## Component 1 — Durable retry policy on `cordis.jobs`

### Schema additions

`sql/0004_p04_sleep_retry.sql` appends these columns to `cordis.jobs`:

| Column | Type | Null/default | Meaning |
|---|---|---|---|
| `max_attempts` | `integer` | nullable, `DEFAULT 3` | Total allowed attempts including attempt 1; NULL means unlimited |
| `retry_backoff_base_seconds` | `double precision` | `NOT NULL DEFAULT 30` | Delay for failure of attempt 1 |
| `retry_backoff_factor` | `double precision` | `NOT NULL DEFAULT 2` | Exponential multiplier; 1 means fixed delay |
| `retry_backoff_max_seconds` | `double precision` | `NOT NULL DEFAULT 86400` | Per-retry delay cap |

Existing rows receive the defaults. No data is imported from pg-agent, Absurd, plugin metadata, or scratch.

### Named constraints

| Name | Contract |
|---|---|
| `jobs_max_attempts_check` | `max_attempts IS NULL OR max_attempts >= 1` |
| `jobs_retry_backoff_base_check` | base is finite and in `[0, 86400]` |
| `jobs_retry_backoff_factor_check` | factor is finite and `>= 1` |
| `jobs_retry_backoff_max_check` | max is finite and in `[0, 86400]` |
| `jobs_retry_backoff_bounds_check` | base is `<=` max |

The finite checks must reject PostgreSQL float `NaN`, `Infinity`, and `-Infinity`, not merely negative numbers.

Columns use `ADD COLUMN IF NOT EXISTS`. Constraints are added through replay-safe named catalog guards; replay must not drop and recreate them on every apply. If a manually-created column has an incompatible type or an existing constraint with incompatible semantics, apply fails rather than silently rebuilding the table.

### Ready index replacement

The old PENDING-only `jobs_ready_idx` is replaced in `0004` with the same ordering:

```text
(priority DESC, available_at ASC, job_id ASC)
```

and a partial predicate covering exactly:

```text
status IN ('PENDING', 'SLEEPING')
```

The new file drops and recreates this named index so `CREATE INDEX IF NOT EXISTS` cannot preserve the old predicate accidentally. `WAITING` remains excluded.

`jobs_stale_claim_idx` remains unchanged.

### Lifecycle

Policy values are read under the jobs row lock at failure time. Direct policy changes committed before that lock take effect; later changes block behind the transition. P04 adds no policy-update function. Future enqueue code must populate these columns or accept the defaults.

---

## Component 2 — `cordis.retry_delay_seconds`

### Interface

```text
cordis.retry_delay_seconds(
    p_attempt     integer,
    p_base_seconds double precision DEFAULT 30,
    p_factor       double precision DEFAULT 2,
    p_max_seconds  double precision DEFAULT 86400
) RETURNS double precision
```

Catalog identity:

```text
cordis.retry_delay_seconds(integer,double precision,double precision,double precision)
```

Packaging:

- `LANGUAGE plpgsql`
- `IMMUTABLE`
- `SECURITY INVOKER`
- `SET search_path TO pg_catalog`

### Input meaning

`p_attempt` is the attempt that just failed, not the next attempt. Therefore:

| Failed attempt | Default exponent | Default delay |
|---:|---:|---:|
| 1 | 0 | 30 seconds |
| 2 | 1 | 60 seconds |
| 3 | 2 | 120 seconds |
| … | … | capped at 86400 |

### Validation

Raise `invalid_parameter_value` for:

- null or `< 1` attempt;
- null/non-finite base, factor, or max;
- base or max outside `[0, 86400]`;
- factor `< 1`;
- base greater than max.

### Algorithm

Compute:

```text
exponent = p_attempt - 1
delay = min(p_max_seconds, p_base_seconds × p_factor^exponent)
```

Required special cases:

- base or max 0 → 0;
- factor 1 → fixed base delay;
- saturation is detected before a floating-point power can overflow;
- return is always finite and in `[0, 86400]`.

An O(1) logarithmic threshold comparison is preferred over an attempt-count loop. It prevents pathological runtime if an unlimited job reaches a large attempt number.

---

## Component 3 — Claim-fenced sleep

### Interface

```text
cordis.sleep_claim(
    p_claim_token    uuid,
    p_run_id         text,
    p_until          timestamptz,
    p_extend_seconds integer DEFAULT 90
) RETURNS boolean
```

Catalog identity:

```text
cordis.sleep_claim(uuid,text,timestamp with time zone,integer)
```

Packaging:

- `LANGUAGE plpgsql`
- `VOLATILE`
- `SECURITY INVOKER`
- `SET search_path TO pg_catalog`

### Validation and return contract

Validate before ownership classification:

- `p_run_id` non-null and nonblank;
- `p_until` non-null and finite;
- `p_extend_seconds > 0`.

Past finite timestamps are accepted and create an immediately due SLEEPING row. Infinite explicit sleeps are rejected because P04 has no cancellation API; P03’s already-persisted infinite wait deadlines remain supported separately.

After scalar validation:

- null, unknown, mismatched, expired, or non-RUNNING token → `false`;
- successful sleep → `true`;
- impossible post-log transition → `object_not_in_prerequisite_state`, rolling back the log append.

### `run/sleep` payload

Explicit sleep appends:

```json
{
  "reason": "sleep",
  "until": "<timestamptz JSON string>"
}
```

`until` is built with `pg_catalog.to_jsonb(p_until)`, matching the P03 deadline serialization precedent.

### Mutation order

1. Call `cordis.emit_step_claimed` with:
   - token and run ID;
   - kind `run/sleep`;
   - the exact payload above;
   - `step_name = NULL`;
   - caller’s extension duration.
2. If it returns false, return false with no state change or log.
3. The `emit_step_claimed` jobs update retains the row lock.
4. Update the exact jobs row, guarded by token, run ID, and `status='RUNNING'`:
   - `status = 'SLEEPING'`;
   - `available_at = p_until`;
   - claim fields = NULL;
   - `completed_at`, `result`, and `error` = NULL;
   - preserve `attempt`, retry policy, priority, payload, and identity.
5. Require one row.
6. Return true.

The log and scheduler transition are in the caller’s transaction. Rollback restores the original claim and removes the `run/sleep`.

---

## Component 4 — Wait-deadline timeout resolution

### Interface

```text
cordis.resolve_due_waits(
    p_run_id text DEFAULT NULL,
    p_limit  integer DEFAULT 100
) RETURNS integer
```

Catalog identity:

```text
cordis.resolve_due_waits(text,integer)
```

Packaging:

- `LANGUAGE plpgsql`
- `VOLATILE`
- `SECURITY INVOKER`
- `SET search_path TO pg_catalog`

Return value is the number of waits resolved by this call. A race-lost or stale candidate does not increment the count.

### Validation

Raise `invalid_parameter_value` for:

- non-null blank `p_run_id`;
- null or non-positive `p_limit`.

`p_run_id=NULL` scans globally. A non-null run ID limits the sweep to that scheduler row.

### Deadline index

Add:

```text
run_waits_deadline_idx
  ON cordis.run_waits
     (deadline ASC, event_scope_id, event_name, run_id)
  WHERE deadline IS NOT NULL
```

This supports the global due scan. Targeted scans may continue to use `run_waits_pkey`.

### Candidate selection

1. Capture one finite `t0 = pg_catalog.clock_timestamp()`.
2. Read at most `p_limit` candidate registrations satisfying:
   - optional run filter;
   - `deadline IS NOT NULL`;
   - `deadline <= t0`.
3. Order by:
   - `event_scope_id`;
   - `event_name`;
   - `run_id`.
4. Do not lock `run_waits` during candidate discovery, because locking it before the event/jobs rows would violate P03’s global order.

Candidate rows are hints. Every field is revalidated after the correct locks are acquired.

### Per-candidate lock and resolution algorithm

For each candidate:

1. Lock the exact `run_events` row `FOR UPDATE`.
   - Missing row is an invariant error because `run_waits_event_fkey` requires it.
2. Lock the candidate jobs row `FOR UPDATE`.
3. Lock the current `run_waits` row for that run `FOR UPDATE`.
4. If the wait row is absent, skip; another emit/timeout already won.
5. If its `await_id` or event key differs from the candidate, skip; the candidate became stale and a later logical wait now occupies the run.
6. Revalidate deadline:
   - null or `> t0` → skip;
   - past, `-infinity`, or equal to `t0` → due.
7. Require:
   - event payload still SQL NULL;
   - jobs status exactly `WAITING`;
   - all jobs claim fields null.
8. If the exact wait still exists but those invariants fail, raise `object_not_in_prerequisite_state`.
9. Append timeout `run/wake` through `cordis.emit_step`.
10. Update jobs:
    - `WAITING → PENDING`;
    - `available_at = t0`;
    - claim fields remain null;
    - `completed_at`, `result`, and `error` = NULL.
11. Guard the update by run ID and `status='WAITING'`; require one row.
12. Delete `run_waits` by both run ID and await ID; require one row.
13. Increment the returned count.

### Timeout `run/wake` payload

```json
{
  "await_id": "<UUID string>",
  "event_scope_id": "<opaque scope>",
  "event_name": "<name>",
  "wake_reason": "timeout",
  "deadline": "<timestamptz JSON string>",
  "woken_at": "<timestamptz JSON string>"
}
```

Both timestamps use `pg_catalog.to_jsonb`.

This differs structurally from P03 event wake:

- event wake has `source_run_id` and `source_seq`;
- timeout wake has `wake_reason="timeout"` and no source pointer.

`run_state` requires no change because both payloads include the same awaited `await_id`.

### Event versus timeout winner

Both paths acquire the event row first with `FOR UPDATE`.

#### Timeout wins first

```text
timeout:
  event lock
  → jobs lock
  → wait lock
  → timeout wake + PENDING + wait delete
  → commit

emit:
  waits for event lock
  → event becomes emitted
  → finds no active wait
  → returns emitted=true, woken_count=0
```

The run has one timeout wake.

#### Emit wins first

```text
emit:
  event lock
  → event/emit + event wake
  → PENDING + wait delete
  → commit

timeout:
  obtains event lock afterward
  → current wait absent
  → skips candidate
```

The run has one event wake.

An event can win after the deadline has passed if no timeout transaction acquired the event lock first. Deadlines are durable eligibility for the timeout sweep, not an independent wall-clock interrupt.

### Piggybacking

The revised `claim_job` calls:

```text
resolve_due_waits(p_run_id, 100)
```

before stale release and candidate selection. This is the same public resolver, not a duplicate code path.

A targeted claim of a due WAITING run can therefore:

```text
resolve timeout → PENDING → claim the same row
```

within one transaction.

---

## Component 5 — Revised task-level failure

### Interface compatibility

Before and after P04:

```text
cordis.fail_claim(
    p_claim_token uuid,
    p_reason      jsonb
) RETURNS boolean
```

The catalog identity, return type, volatility, and security remain unchanged. Only behavior changes.

### Validation and lost claim

- SQL NULL reason raises `invalid_parameter_value`.
- JSONB `null` remains a valid structured cause.
- Null, unknown, expired, or non-RUNNING token returns false.
- Parameter validation occurs before lost-claim classification.

### Fencing and row ownership

1. Capture `t0`.
2. Lock the one row matching:
   - token;
   - `status='RUNNING'`;
   - `claim_expires_at > t0`.
3. If absent after waiting/recheck, return false.
4. Read under that lock:
   - run ID;
   - current attempt;
   - max attempts;
   - backoff parameters.
5. All log appends and the final update occur while retaining this lock.
6. The final update repeats the job ID/token/status fence and requires one row.

The captured `t0` defines whether the claim was live at operation entry. Stale reap cannot change the row after the lock is acquired.

### Retry eligibility

A next attempt is allowed only if:

```text
current attempt < integer maximum
AND
(max_attempts IS NULL OR current attempt < max_attempts)
```

If allowed:

```text
next_attempt = current attempt + 1
delay = retry_delay_seconds(current attempt, row policy)
retry_at = t0 + delay
status = SLEEPING if delay > 0 else PENDING
```

### Retry `run/sleep` payload

```json
{
  "reason": "retry",
  "failed_attempt": 1,
  "next_attempt": 2,
  "until": "<retry_at timestamptz JSON string>",
  "delay_seconds": 30,
  "error": "<original p_reason JSON value>"
}
```

`step_name` is NULL.

After the append, update the same jobs row:

- status as computed;
- `available_at = retry_at`;
- `attempt = next_attempt`;
- claim fields = NULL;
- `completed_at`, `result`, and `error` = NULL;
- preserve `job_id`, `run_id`, job type, payload, priority, retry policy, and creation time.

The retry cause is historical in the log. `jobs.error` remains null because the scheduler row is nonterminal.

### Incomplete step identity

P04 does not write `tool` or `final` on retry. Therefore P02’s existing `next_step_name` behavior remains:

- latest LLM with no later same-step `tool`/`final` → return the same step name;
- a step whose tool/final already committed before failure remains complete and may advance.

Neither `attempt`, worker identity, nor claim token is part of `step_name`.

### Terminal exhaustion

If no next attempt is allowed, construct:

```json
{
  "name": "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
  "message": "task exceeded max recovery attempts",
  "failure_source": "fail_claim",
  "attempt": 3,
  "max_attempts": 3,
  "cause": "<original p_reason JSON value>"
}
```

For attempt-counter exhaustion under `max_attempts=NULL`, include:

```json
{
  "limit": "attempt_counter_exhausted"
}
```

and keep `max_attempts` as JSON null.

Append this exact object as kind `error`, then update jobs:

- `status = 'ERROR'`;
- `error` = the same object;
- `result = NULL`;
- `completed_at = t0`;
- claim fields = NULL;
- retain the current attempt number;
- leave `available_at` unchanged because terminal eligibility is irrelevant.

A failure while appending or updating rolls back both log and jobs state.

### Duplicate and dropped responses

- Repeating `fail_claim` with the old token after a committed retry or terminal failure returns false.
- If the response is dropped, the caller reads the jobs row by run ID:
  - incremented attempt and PENDING/SLEEPING means retry committed;
  - ERROR plus dead-letter means terminal failure committed;
  - RUNNING with the same token means the transaction did not commit.

---

## Component 6 — Revised stale-lease recovery

### Interface compatibility

Before and after P04:

```text
cordis.release_stale(
    p_run_id text DEFAULT NULL,
    p_limit  integer DEFAULT 100
) RETURNS integer
```

The return count now includes every expired RUNNING row successfully processed, whether it becomes retryable or terminal.

Validation remains:

- non-null run ID must be nonblank;
- limit must be positive.

### Selection and locking

1. Capture one `t0`.
2. Select expired RUNNING rows:
   - `claim_expires_at <= t0`;
   - optional run filter.
3. Order by claim expiry then job ID.
4. `FOR UPDATE SKIP LOCKED`.
5. Limit to `p_limit`.
6. Process each locked row independently inside the function’s transaction.

Per-row processing is required because each row has its own policy and log payload. Complexity is O(processed rows), bounded by the limit.

### Timeout cause

The stale cause object is:

```json
{
  "name": "CLAIM_TIMEOUT",
  "message": "worker did not finish before claim expiry",
  "claim_token": "<expired UUID>",
  "claimed_by": "<worker ID>",
  "claim_expires_at": "<timestamptz JSON string>"
}
```

The old token is logged only in the same transaction that clears it. It is expired before selection and has no authority after commit.

### Recoverable stale claim

Evaluate retry eligibility and delay exactly as `fail_claim`.

Append `run/claim_timeout`:

```json
{
  "reason": "claim_timeout",
  "claim_token": "<expired UUID>",
  "claimed_by": "<worker ID>",
  "claim_expires_at": "<timestamptz JSON string>",
  "failed_attempt": 1,
  "outcome": "retry",
  "next_attempt": 2,
  "retry_at": "<timestamptz JSON string>",
  "delay_seconds": 30
}
```

Then update the same jobs row:

- increment attempt;
- PENDING for zero delay, otherwise SLEEPING;
- set `available_at=retry_at`;
- clear claim fields;
- clear terminal/result/error fields.

Do not additionally append `run/sleep`; the claim-timeout row already carries the retry scheduling data. A later due claim appends the timer `run/wake`.

### Exhausted stale claim

Construct the same dead-letter envelope with:

```json
{
  "name": "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
  "message": "task exceeded max recovery attempts",
  "failure_source": "claim_timeout",
  "attempt": 3,
  "max_attempts": 3,
  "cause": {
    "name": "CLAIM_TIMEOUT",
    "...": "..."
  }
}
```

Append, in order:

1. `run/claim_timeout` with `outcome="terminal"` and the dead-letter object nested under `dead_letter`;
2. `error` with the exact dead-letter object.

Then update jobs to terminal ERROR exactly as explicit exhaustion.

### Atomicity

If either log append or jobs update fails, the row remains expired RUNNING and no timeout history commits. A later sweep can retry the complete transition. Sequence gaps from rolled-back appends are accepted.

---

## Component 7 — Revised `cordis.claim_job`

### Interface compatibility

The signature remains:

```text
cordis.claim_job(
    p_run_id        text,
    p_worker_id     text,
    p_lease_seconds integer DEFAULT 90
) RETURNS SETOF cordis.jobs
```

Validation and zero-or-one return behavior remain unchanged.

### Revised operation order

1. Validate worker ID, optional run ID, and lease duration.
2. `PERFORM cordis.resolve_due_waits(p_run_id, 100)`.
3. `PERFORM cordis.release_stale(p_run_id, 100)`.
4. Capture a fresh `t_claim`.
5. Select one candidate:
   - status in PENDING or SLEEPING;
   - `available_at <= t_claim`;
   - optional run filter.
6. Preserve ordering:
   - priority descending;
   - available time ascending;
   - job ID ascending.
7. `FOR UPDATE SKIP LOCKED`.
8. Capture the candidate’s prior status and prior `available_at`.
9. Update to RUNNING with:
   - new server-generated token;
   - requested worker;
   - lease expiry;
   - terminal fields cleared.
10. Preserve `attempt`, policy, priority, payload, and `available_at`.
11. If prior status was SLEEPING, append timer `run/wake`.
12. Return the updated jobs row.

`WAITING`, DONE, and ERROR remain ineligible regardless of `available_at`.

### Timer wake payload

```json
{
  "wake_reason": "sleep",
  "scheduled_for": "<previous available_at timestamptz JSON string>",
  "woken_at": "<t_claim timestamptz JSON string>"
}
```

This payload intentionally has no `await_id`:

- event wake: `await_id` + source pointer;
- timeout wake: `await_id` + `wake_reason="timeout"`;
- timer wake: no await ID + `wake_reason="sleep"`.

The append occurs after the jobs update has acquired the claim, but both commit atomically. If append fails, the claim update rolls back.

### Lock interactions

All maintenance runs before candidate claiming. Timeout resolution may retain event/jobs locks until transaction end, but later stale and candidate selection use `SKIP LOCKED`, so they do not wait while closing a jobs→event cycle.

A transaction that already holds a claim-fenced RUNNING jobs row may call `resolve_due_waits` directly. Its held RUNNING row cannot be one of the resolver’s WAITING targets, matching the P03 disjoint-set argument:

```text
claim-held target set: RUNNING
timeout target set: WAITING with active run_waits
intersection: empty
```

---

## Component 8 — Log payload variants and projection behavior

### `run/sleep`

Two closed payload variants:

#### Explicit sleep

```json
{
  "reason": "sleep",
  "until": "<timestamp>"
}
```

#### Retry delay

```json
{
  "reason": "retry",
  "failed_attempt": 1,
  "next_attempt": 2,
  "until": "<timestamp>",
  "delay_seconds": 30,
  "error": {}
}
```

### `run/wake`

Three structural variants exist after P04:

| Source | Distinguishing fields |
|---|---|
| P03 event | `await_id`, `source_run_id`, `source_seq`; no `wake_reason` required |
| P04 wait timeout | `await_id`, `wake_reason="timeout"`, `deadline`, `woken_at` |
| P04 due sleep | `wake_reason="sleep"`, `scheduled_for`, `woken_at`; no `await_id` |

P04 does not replace P03 `emit_event` merely to add `wake_reason="event"`.

### `run/claim_timeout`

Every stale claim produces one row. `outcome` is the discriminator:

```text
retry | terminal
```

The retry variant includes next attempt/time/delay. The terminal variant includes the dead-letter object.

### `error`

P04 emits `error` only for terminal explicit failure or terminal stale recovery. Retry must never append `error`, preserving `run_state` correctness.

### Projection effects

`cordis.run_state` remains unchanged:

- explicit sleep and retry backoff remain `in-progress`;
- a timeout wake matches the latest await ID, changing `awaiting` to `in-progress`;
- timer wake has no await ID and does not falsely close an await;
- terminal exhaustion appends `error`, yielding `error`;
- `steps_used` remains the count of `llm` rows only.

---

## Component 9 — API changes and call sites

### New interfaces

```text
cordis.retry_delay_seconds(
  integer,double precision,double precision,double precision
) RETURNS double precision

cordis.sleep_claim(
  uuid,text,timestamp with time zone,integer
) RETURNS boolean

cordis.resolve_due_waits(
  text,integer
) RETURNS integer
```

### Modified behavior, stable identities

```text
cordis.claim_job(text,text,integer) RETURNS SETOF cordis.jobs
cordis.release_stale(text,integer) RETURNS integer
cordis.fail_claim(uuid,jsonb) RETURNS boolean
```

### Unchanged interfaces

```text
cordis.renew_claim(uuid,integer)
cordis.yield_claim(uuid)
cordis.complete_claim(uuid,jsonb)
cordis.await_event(...)
cordis.emit_event(...)
cordis.run_state(text)
cordis.next_step_name(text)
```

### Internal call graph

```text
claim_job
  → resolve_due_waits
  → release_stale
  → retry_delay_seconds (indirectly through release_stale)
  → emit_step for due-sleep wake

sleep_claim
  → emit_step_claimed
      → emit_step

fail_claim
  → retry_delay_seconds when retryable
  → emit_step

release_stale
  → retry_delay_seconds when retryable
  → emit_step
```

### Test call sites

- `tests/test_p00_sql_source.py`
  - adds the three new function names;
  - adds the 0004 file to exact file-list assertions.
- `tests/test_p01_claim.py`
  - retains the existing two-argument `fail_claim` calls;
  - changes fixture policy where terminal or zero-delay behavior is required;
  - updates SLEEPING eligibility and ready-index assertions.
- `tests/test_p04_sleep_retry.py`
  - exercises all new behavior.
- P03-only tests remain unchanged because their truncated tree excludes 0004.

No production Python, host SDK, pg-agent, or scratch call site exists yet.

### Exact full-tree function-name list

`tests/test_p00_sql_source.py::KERNEL_FUNCTIONS` becomes this C-collation-ordered list:

```text
cordis._validate_plugin_definition
cordis.await_event
cordis.checkpoint
cordis.claim_job
cordis.complete_claim
cordis.emit_event
cordis.emit_step
cordis.emit_step_claimed
cordis.fail_claim
cordis.get_schema_version
cordis.llm_checkpoint
cordis.next_step_name
cordis.refresh_plugins
cordis.register_host_plugin
cordis.release_stale
cordis.renew_claim
cordis.resolve_due_waits
cordis.retry_delay_seconds
cordis.run_state
cordis.sleep_claim
cordis.unregister_host_plugin
cordis.yield_claim
```

No overload is added for any new P04 function.

---

## Concurrency and lifecycle

### Execution model

All P04 functions are synchronous PostgreSQL functions running in the caller’s transaction.

P04 creates no:

- process or background worker;
- timer;
- polling thread;
- notification dependency;
- session affinity;
- cancellation task;
- separate maintenance connection.

Worker polling drives bounded timeout and stale recovery through `claim_job`. Operators may invoke either sweep explicitly.

### Lock order

Paths that do not touch waits lock only jobs rows:

```text
sleep/fail/stale/claim:
  jobs row
  → append log
  → jobs transition
```

Timeout retains P03’s global order:

```text
run_events row
→ cordis.jobs rows ordered by run_id
→ matching run_waits row
→ log/status/delete mutations
```

The candidate discovery query takes no wait-row lock.

### Potential races

#### Sleep versus stale release

- `sleep_claim`’s `emit_step_claimed` locks and extends a live claim before logging.
- `release_stale` can select only expired RUNNING rows.
- Whichever locks the jobs row first determines the observed predicate.
- Successful sleep clears the claim and becomes SLEEPING, so stale release skips it.
- If stale recovery commits first, `sleep_claim` returns false.

#### Fail versus stale release

Both lock the same jobs row. A live `fail_claim` excludes stale selection at its captured boundary; stale release excludes a later live-token failure after it clears the token. Only one transition/log sequence commits.

#### Two stale sweepers

Both use `FOR UPDATE SKIP LOCKED`, so one processes a row and the other skips it.

#### Two timeout sweepers

Both may discover the same unlocked candidate. They serialize on the event row. The loser sees the wait absent or changed and returns no resolution for it.

#### Claiming a due sleeper

Candidate selection uses `FOR UPDATE SKIP LOCKED`. Only one claimant transitions the SLEEPING row and appends its timer wake.

#### Claim transaction rollback

A claimed sleeper’s RUNNING transition and timer wake both roll back. It remains SLEEPING and can be claimed again later without a committed duplicate wake.

### Cancellation and interruption

If a SQL statement is canceled or the connection drops before commit, PostgreSQL rolls back every P04 log and jobs mutation in that transaction.

There is no application-level cancellation. Finite wait deadlines provide timeout recovery; NULL/+infinity waits and deliberate durable states require their normal event or future cancellation work.

---

## State and data flow

### Explicit sleep

Trigger: a worker holding a live claim calls `sleep_claim`.

```text
token/run/until
  → scalar validation
  → emit_step_claimed fence + lease extension
  → run/sleep append
  → jobs RUNNING→SLEEPING
  → available_at=until
  → claim fields null
  → caller commit
```

Downstream observation:

- scheduler row is not claimable before `until`;
- `run_state` remains in-progress;
- due claim creates a new token and one timer wake.

### Due sleeper claim

Trigger: targeted or general worker polling at or after `available_at`.

```text
claim_job
  → timeout sweep
  → stale sweep
  → select due PENDING|SLEEPING
  → SLEEPING→RUNNING
  → new token
  → run/wake(wake_reason=sleep)
  → return claimed row
```

No PENDING intermediate state is committed.

### Wait timeout

Trigger: explicit timeout maintenance or any claim poll.

```text
run_waits.deadline <= captured time
  → event lock
  → jobs lock
  → wait lock/revalidation
  → run/wake(wake_reason=timeout)
  → jobs WAITING→PENDING
  → delete run_waits
  → caller commit
```

A targeted `claim_job(run_id, ...)` may immediately continue:

```text
PENDING→RUNNING + new token
```

in the same transaction.

### Explicit retry

Trigger: `fail_claim` under a live claim and remaining attempt budget.

```text
jobs lock/fence
  → current attempt + policy
  → deterministic delay
  → run/sleep(reason=retry)
  → same jobs row:
      attempt+1
      SLEEPING|PENDING
      available_at=retry_at
      claim cleared
```

Later claim preserves the same run ID and uses P02’s existing step fold.

### Terminal failure

Trigger: explicit or stale failure with no permitted next attempt.

```text
jobs lock
  → construct MAX_RECOVERY_ATTEMPTS_EXCEEDED
  → optional run/claim_timeout
  → error append
  → jobs ERROR + same error + completed_at
  → claim cleared
```

### Lease recovery

Trigger: explicit `release_stale` or claim polling observes an expired RUNNING row.

```text
expired RUNNING
  → jobs lock SKIP LOCKED
  → run/claim_timeout
  → shared retry decision
  → same row retry or terminal ERROR
```

### Out-of-order, duplicate, and dropped operations

| Situation | Result |
|---|---|
| Duplicate sleep with old token | First may succeed; later call returns false |
| Sleep response dropped | Read jobs/log; token clearance makes repetition safe |
| Two claims for one due sleeper | One RUNNING row and one committed timer wake |
| Duplicate timeout sweep | First winner returns 1; later returns 0 |
| Event and timeout race | Exactly one wake for the await ID |
| Event emitted after timeout | Event persists with zero wake; timed-out run stays resumed |
| Fail repeated with old token | First retry/terminal transition wins; later false |
| Stale sweep repeated | Processed row is no longer expired RUNNING; later count excludes it |
| Retry transaction rollback | Original RUNNING claim and attempt remain; no retry log |
| Timeout transaction rollback | WAITING row and registration remain; no wake log |
| Dropped claim response | Caller reads jobs by run ID; returned token remains authoritative only if transaction committed |

---

## Error handling and edge cases

### Parameter errors

Raise `invalid_parameter_value`:

- invalid sleep run ID, non-finite/null `until`, or non-positive extension;
- invalid timeout run filter or limit;
- invalid delay-function attempt or backoff numbers;
- SQL NULL fail reason;
- existing P01 claim/release validation failures.

Parameter errors occur before lost-claim false returns.

### Lost ownership

`sleep_claim` and `fail_claim` return false for:

- null token;
- unknown token;
- token for another run where applicable;
- non-RUNNING row;
- expired claim;
- token already cleared by yield, wait, sleep, failure, completion, or stale recovery.

No durable log or scheduler mutation occurs.

### Retry boundaries

- `max_attempts=1`: first failure is terminal.
- Default 3:
  - attempt 1 failure → attempt 2 after 30s;
  - attempt 2 failure → attempt 3 after 60s;
  - attempt 3 failure → terminal.
- `max_attempts=NULL`: unlimited until the integer attempt counter is exhausted.
- Lowering max below the current attempt causes terminal failure on the next failure.
- Base 0 yields immediate PENDING retry.
- Factor 1 yields fixed delay.
- Base equal to cap remains fixed at the cap.
- Delay never exceeds 86400 seconds.

### Timestamp boundaries

#### Sleep

- finite past timestamp: SLEEPING but immediately claimable;
- exact current timestamp: immediately claimable after the sleep transaction;
- infinity values: rejected;
- null: rejected.

#### Wait deadline

- NULL: no timeout;
- finite future: due when a later sweep captures `t0 >= deadline`;
- finite past: due on first sweep;
- `-infinity`: due on first sweep;
- `+infinity`: never due;
- an event can still win a due wait if it takes the event lock first.

### Invariant failures

Raise `object_not_in_prerequisite_state` and roll back when:

- sleep log succeeded but the exact RUNNING claim cannot be transitioned;
- a matching timeout wait exists without a jobs row;
- matching wait/jobs state is not `WAITING` with null claim fields;
- an emitted event still has the exact active matching wait;
- a guarded jobs update or wait delete affects a count other than one;
- failure logging succeeds but the locked claim row cannot be updated.

Stale candidate disappearance or replacement during timeout is a normal race and is skipped rather than raised.

### Empty collections

- no due waits → resolver returns 0;
- no stale claims → release returns 0;
- no eligible PENDING/SLEEPING job → claim returns no row;
- first emit after a timeout may succeed with wake count 0.

### Storage overflow

- delay is bounded and cannot overflow timestamp arithmetic at current dates;
- if `attempt` is already the maximum integer, recovery becomes terminal instead of attempting `attempt+1`;
- malformed manually-written policy rows are rejected by table constraints before a transition can consume them.

### No cancel path

A NULL/+infinity wait may remain WAITING indefinitely, and a finite but distant sleeper remains SLEEPING until due. This is intentional P04 scope. Direct SQL by the install role remains possible before P07 permission hardening but is not a product recovery verb.

---

## Algorithmic and performance tradeoffs

### Bounded maintenance on claim

Each `claim_job` performs:

- at most 100 timeout candidate resolutions;
- at most 100 stale-claim resolutions;
- one candidate claim.

This increases worst-case claim work, but guarantees progress without a second scheduler. Both sweep limits already match P01’s bounded maintenance style.

### Per-row stale processing

P01 used one bulk update. P04 processes stale rows individually because each row can have a different policy and must append one or two log records.

Complexity:

- time: O(S) for S processed stale rows, bounded by `p_limit`;
- log growth: one row per stale retry, two per terminal stale failure;
- locks: one jobs row at a time, retained until transaction end.

### Timeout resolution

For W selected due waits:

- candidate scan uses the deadline index;
- each candidate takes one event, jobs, and wait lock;
- time is O(W), bounded by the limit.

All-or-nothing remains per caller transaction. A failure on one invariant rolls back earlier resolutions in the same call. This matches P03’s transactional correctness preference; P04 does not introduce partial commits inside one sweep.

### Deterministic backoff

No jitter means many identical jobs can become due together. This is accepted for the kernel’s first retry state machine. Producers can vary base/factor/cap per job. Randomized fleet smoothing is policy work, not required for P04 correctness.

---

## Work items

### W34 — Durable retry policy, curve, and ready index

**File:** `sql/0004_p04_sleep_retry.sql`

Add:

- four jobs policy columns;
- exact named constraints;
- `cordis.retry_delay_seconds`;
- PENDING+SLEEPING `jobs_ready_idx`;
- `run_waits_deadline_idx`.

**Done when:**

- existing jobs rows have defaults;
- NULL max attempts is accepted;
- malformed policy values are rejected;
- delay defaults and cap are exact;
- replay preserves rows and policies;
- WAITING remains absent from the ready index.

### W35 — Claim-fenced sleep

**File:** `sql/0004_p04_sleep_retry.sql`

Add `cordis.sleep_claim` with:

- exact signature;
- parameter/lost-claim behavior;
- `emit_step_claimed` append;
- exact payload;
- atomic RUNNING→SLEEPING;
- finite timestamp rule.

**Done when:**

- sleep commits log/state/claim release together;
- rollback preserves the claim;
- old/expired token returns false;
- past sleep is immediately eligible but still logged.

### W36 — Wait timeout resolver

**File:** `sql/0004_p04_sleep_retry.sql`

Add `cordis.resolve_due_waits` with:

- exact signature;
- bounded candidate scan;
- event→jobs→wait locks;
- candidate revalidation;
- timeout wake;
- WAITING→PENDING;
- exact wait deletion.

**Done when:**

- past and `-infinity` deadlines resolve;
- NULL and `+infinity` do not;
- duplicate resolution is a no-op;
- event/timeout race produces one wake;
- no `jobs.available_at` deadline copy is introduced.

### W37 — Retry-aware `fail_claim`

**File:** `sql/0004_p04_sleep_retry.sql`

Replace the P01 body using `CREATE OR REPLACE` with the same identity.

**Done when:**

- default failure retries attempts 1 and 2;
- attempt 3 becomes terminal;
- zero-delay policy returns PENDING;
- unlimited policy is accepted;
- retry preserves row/run identity and incomplete step name;
- dead-letter payload is exact.

### W38 — Retry-aware stale release and due-sleeper claim

**File:** `sql/0004_p04_sleep_retry.sql`

Replace:

- `release_stale`;
- `claim_job`.

Implement:

- stale `run/claim_timeout`;
- shared retry/dead-letter state machine;
- timeout sweep before stale sweep;
- due PENDING/SLEEPING selection;
- one timer wake for claimed SLEEPING rows.

**Done when:**

- stale retry uses the configured delay;
- exhausted stale recovery appends timeout+error and terminalizes;
- a due sleeper is claimed once;
- WAITING remains unclaimable except through timeout/event transition;
- default stale recovery no longer immediately claims unless policy delay is zero.

### W39 — Version and SQL README

**Files:**

- `sql/0004_p04_sleep_retry.sql`
- `sql/README.md`

At the end of 0004, replace `get_schema_version()` with the unchanged zero-argument identity returning `p04`.

README documents:

- the P04-only marker;
- full-tree p06 marker;
- policy defaults and NULL max semantics;
- direct due-SLEEPING claims;
- timeout resolver and one-winner lock order;
- same-row retry and dead-letter;
- no relationship between P04 curve fields and P06 `retry_class`.

### W40 — Retarget existing tests

**Files:**

- `tests/test_p00_sql_source.py`
- `tests/test_p01_claim.py`

Apply only the changes enumerated under **Verification → Existing assertion change/stay matrix**.

### W41 — P04 tests

**File:** `tests/test_p04_sleep_retry.py`

Use:

- a P04-ending tree containing 0000–0004 and excluding 0006;
- the full tree only for current product/version and cross-phase checks;
- `psql_session` plus a Python thread for blocking race tests;
- finite `statement_timeout` for deadlock regressions.

No new fixture or client.

---

## File-by-file impact

### `docs/plans/P04-sleep-retry-2026-08-24.md` — rewritten by this planning task

- Status changes from scaffold to `ready to implement`.
- All scaffold questions are resolved.
- Exact APIs, policy schema, lock order, log payloads, tests, and migration behavior are specified.
- No runtime implementation is included in this task.

### `sql/0004_p04_sleep_retry.sql` — added during implementation

Adds:

- jobs retry-policy columns and named constraints;
- replacement ready index;
- wait-deadline index;
- `retry_delay_seconds`;
- `sleep_claim`;
- `resolve_due_waits`;
- revised `fail_claim`;
- revised `release_stale`;
- revised `claim_job`;
- `get_schema_version()` returning p04.

Dependencies:

- P01 jobs table and functions;
- P02 log writers and kind CHECK;
- P03 run events/waits;
- no P06 object.

Ordering in the file:

1. jobs columns and constraints;
2. indexes;
3. delay evaluator;
4. sleep verb;
5. wait resolver;
6. revised fail;
7. revised stale release;
8. revised claim;
9. version replacement.

The functions called by `claim_job` must be defined before its replacement.

### `sql/README.md` — modified during implementation

Add the P04 version and behavior summary. Preserve the statement that the current full tree ends at 0006 and reports p06.

### `tests/test_p00_sql_source.py` — modified during implementation

- Insert `0004_p04_sleep_retry.sql` into both exact current-tree file-list assertions:
  - fresh apply;
  - dynamic next-number probe.
- Add the three P04 function names to `KERNEL_FUNCTIONS`.
- Keep current-tree version p06.
- Keep table counts and forbidden-source rules otherwise unchanged.

### `tests/test_p01_claim.py` — modified during implementation

Retarget current-tree expectations affected by P04:

- terminal fail fixture explicitly inserts `max_attempts=1`;
- terminal error expectation checks the dead-letter wrapper and nested original cause;
- stale immediate-requeue fixtures explicitly use zero base/max backoff;
- auto-claim after stale expiry uses zero-delay policy;
- reserved-status test becomes:
  - WAITING remains unclaimable;
  - due SLEEPING is claimable;
  - future SLEEPING is not;
- ready-index predicate expects PENDING and SLEEPING;
- existing token fencing, mutual exclusion, uniqueness, replay, null-token, and parameter tests remain.

Do not convert the module to a P01-only truncated tree; it currently exercises the full product and should continue to detect later protocol revisions.

### `tests/test_p04_sleep_retry.py` — added during implementation

Contains all P04 catalog, algorithm, state, atomicity, concurrency, replay, and one-queue tests.

### Files explicitly unchanged

- `sql/0000_kernel.sql`
- `sql/0001_p01_claim.sql`
- `sql/0002_p02_log.sql`
- `sql/0003_p03_wait_event.sql`
- `sql/0006_p06_plugin_catalog.sql`
- `tools/apply_pg_cordis.py`
- `tests/conftest.py`
- `tests/test_p03_wait_event.py`
- P06 plugin SQL/tests
- pg-agent SQL
- `scratch/yield_walkthrough/*`
- `absurd/sql/absurd.sql`

---

## Risks and migration

### Behavioral change to `fail_claim`

The function identity remains compatible, but its default behavior changes from first-failure terminal ERROR to up to three total attempts. Existing callers that require immediate terminal failure must create/configure the jobs row with `max_attempts=1`.

This is an intentional P04 contract change reserved by P01.

### Behavioral change to stale recovery

Default stale recovery now applies 30-second backoff instead of immediate PENDING. Tests or callers that require immediate reclaim must set base and max delay to zero for that job.

### New jobs columns

Existing rows receive:

```text
max_attempts = 3
base = 30
factor = 2
max delay = 86400
```

No data transformation outside the table is required. Replay preserves explicit per-row policy values.

Old application code selecting `jobs.*` receives additional columns. PostgreSQL composite-return consumers that bind by position must be retargeted; current repository tests read named values or selected fields, and no host SDK exists yet.

### Source downgrade

Applying an older tree after P04 is unsupported. An older 0001 definition could replace the P04 functions while leaving new columns and indexes present. Disposable downgrade tests must use `--reset`.

### Wait deadline latency

Timeout is sweep-driven. A deadline does not wake a run at the exact wall-clock instant unless a claim or explicit resolver call occurs then. An event may win after the deadline if it acquires the event lock before a timeout sweep.

This is the cost of avoiding a background timer and second scheduler.

### Unlimited retries

`max_attempts=NULL` can retry indefinitely. The 86400-second cap bounds each delay, not total lifetime. Operators/producers must opt into NULL deliberately.

### Event persistence after timeout

Timeout does not mark the event emitted. A later event emission persists and can resolve later waits on the same key immediately. Callers must use event scopes/names with the intended lifecycle.

### Terminal log integration

P04 terminal failures append `error`, fixing historical projection for the transitions P04 owns. P01 `complete_claim` still does not append `final`; that pre-existing jobs-to-log gap remains outside P04.

### Permission boundary

Until P07, the install role can directly modify jobs policy or side tables. P04 functions use locks and constraints but do not claim ACL-level protection.

### Rollback

A failed 0004 apply rolls back columns, indexes, functions, and p04 marker in the tree transaction. The database itself follows the existing apply behavior and may remain after failure.

---

## Implementation order

1. Add `sql/0004_p04_sleep_retry.sql` with only the replay-safe jobs policy columns, named constraints, and replacement indexes. Apply a temporary 0000–0004 tree.
2. Add `retry_delay_seconds` and verify default, fixed, zero, capped, and invalid parameter cases.
3. Add `sleep_claim` and verify log-before-release, rollback, lost token, past sleep, and future sleep.
4. Add `resolve_due_waits` and the deadline index. Verify explicit timeout resolution before integrating it into claim.
5. Add timeout-vs-emit concurrency tests while `claim_job` is still unchanged, proving the resolver’s lock order independently.
6. Replace `fail_claim` with the retry/dead-letter body while retaining its exact identity.
7. Replace `release_stale` with per-row timeout logging and shared retry/dead-letter semantics.
8. Replace `claim_job` atomically with:
   - timeout sweep call;
   - revised stale sweep call;
   - PENDING/SLEEPING candidate predicate;
   - timer wake append.
9. Add the p04 version replacement at the end of 0004.
10. Update `sql/README.md`.
11. Retarget `tests/test_p00_sql_source.py`.
12. Retarget only the P04-affected assertions in `tests/test_p01_claim.py`.
13. Add the remaining P04 catalog, failure, stale, same-step, replay, and source-boundary tests.
14. Run the complete verification set below.
15. Follow `AGENTS.md`: obtain an Oracle implementation review with no unresolved P0/P1, record the review, then commit and push only the P04 ship set. P04 is not complete before that review gate and successful push.

The following changes must land atomically in the final P04 commit:

- policy columns + revised failure/stale functions;
- broadened ready index + broadened claim predicate;
- timeout resolver + claim piggyback;
- SQL + tests + README + version assertions.

A release containing only one side of any pair would leave behavior or indexes inconsistent.

---

# Verification

## New test module and named cases

Add `tests/test_p04_sleep_retry.py` with these tests:

| Test | Required proof |
|---|---|
| `test_p04_fresh_apply_catalog_and_version` | 0000–0004 file order, version p04, exact new/revised identities, no P06 dependency |
| `test_p04_retry_policy_columns_constraints_and_indexes` | exact columns/defaults/checks, PENDING+SLEEPING ready index, deadline index |
| `test_p04_retry_delay_defaults_caps_and_validation` | exponent attempt−1, defaults 30/2/86400, fixed/zero/cap behavior, invalid values |
| `test_p04_sleep_claim_logs_and_transitions` | live claim → run/sleep + SLEEPING + exact available_at + cleared ownership |
| `test_p04_sleep_rollback_preserves_running_claim` | explicit rollback removes sleep log and restores original token |
| `test_p04_sleep_lost_claim_and_parameter_errors` | malformed values raise; lost claim returns false with no log/state change |
| `test_p04_due_sleep_is_claimed_and_logs_wake` | future sleeper skipped; due sleeper claimed with new token and one timer wake |
| `test_p04_due_sleep_claim_rollback_has_no_wake` | claim rollback leaves SLEEPING and no committed timer wake |
| `test_p04_wait_timeout_wakes_and_folds_state` | due wait → timeout wake + PENDING + wait deletion + awaiting→in-progress |
| `test_p04_wait_deadline_null_past_and_infinities` | past/−infinity due; NULL/+infinity retained; WAITING available_at remains unrelated |
| `test_p04_duplicate_timeout_resolution_is_noop` | first resolver count 1, later count 0, exactly one wake |
| `test_p04_emit_timeout_race_has_one_wake` | both winner interleavings; no deadlock; exactly one event-or-timeout wake |
| `test_p04_claim_piggybacks_wait_timeout` | targeted claim resolves a due WAITING row then claims it in the same transaction |
| `test_p04_fail_requeues_same_row_with_default_backoff` | same job/run, attempt 1→2, SLEEPING, 30s delay, retry run/sleep |
| `test_p04_fail_preserves_incomplete_step_name` | LLM-only step remains the next step after retry/reclaim |
| `test_p04_fail_over_limit_dead_letters` | attempt=max → ERROR, exact dead-letter name/cause, error log |
| `test_p04_fail_unlimited_and_zero_backoff` | NULL max retries; zero delay produces immediately due PENDING |
| `test_p04_release_stale_retries_and_logs_timeout` | stale attempt increments, same curve used, one run/claim_timeout, old token fenced |
| `test_p04_release_stale_over_limit_dead_letters` | exhausted stale row → run/claim_timeout + error + jobs ERROR |
| `test_p04_shared_attempt_counter_across_fail_and_lease_expiry` | explicit fail and later stale recovery consume attempts 1→2→3 on one row |
| `test_p04_retry_and_lease_expiry_stay_on_one_jobs_row` | job_id/run_id unchanged across both recovery sources; no second scheduler row |
| `test_p04_replay_preserves_policy_sleep_wait_and_logs` | in-place apply preserves custom policy, sleeper/wait, side rows, and log |
| `test_p04_no_second_queue_or_direct_log_insert` | no direct agent_steps mutation, no new queue/public/absurd object, no notification dependency |

## Catalog assertions

`test_p04_fresh_apply_catalog_and_version` uses a copied tree containing exactly:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0004_p04_sleep_retry.sql
```

Assert:

- apply output lists exactly those files;
- `get_schema_version()` returns p04;
- `plugin_catalog` is absent;
- jobs, agent_steps, run_events, and run_waits exist;
- no public P04 table;
- no absurd schema;
- no pg_cordis extension.

Exact new identities:

```text
cordis.resolve_due_waits(text,integer)
cordis.retry_delay_seconds(integer,double precision,double precision,double precision)
cordis.sleep_claim(uuid,text,timestamp with time zone,integer)
```

Exact revised identities remain:

```text
cordis.claim_job(text,text,integer)
cordis.fail_claim(uuid,jsonb)
cordis.release_stale(text,integer)
```

Assert:

- delay evaluator is immutable;
- all writers are volatile;
- all are security invoker;
- every PL/pgSQL function pins search path to pg_catalog;
- no overloads exist;
- version remains zero-argument SQL/immutable/invoker.

## Exact sleep assertions

After a successful future sleep:

```text
status = SLEEPING
available_at = requested timestamp
attempt unchanged
claim_token/claimed_by/claim_expires_at = NULL
completed_at/result/error = NULL
```

Log:

```text
kind = run/sleep
step_name = NULL
payload.reason = sleep
payload.until = to_jsonb(requested timestamp)
```

Before due time, targeted claim returns zero. After setting/using a due timestamp, claim returns:

```text
same job_id
same run_id
same attempt
new claim token
status RUNNING
```

with exactly one `run/wake` whose reason is sleep.

## Exact timeout assertions

For a due wait:

- event row remains SQL-NULL/unemitted;
- one timeout wake exists with the exact await ID;
- jobs is PENDING and due;
- wait registration is absent;
- no event/emit was added;
- `run_state.status = in-progress`;
- a later claim succeeds.

For NULL/+infinity:

- resolver count excludes them;
- jobs remains WAITING;
- wait remains present;
- no wake row is added.

## Timeout concurrency shape

### Timeout-first

1. Create a due wait.
2. Session A begins and calls `resolve_due_waits`, leaving the transaction open.
3. Session B calls `emit_event` in a thread and blocks on the event row.
4. Session A commits.
5. Session B completes with first emission and wake count 0.
6. Assert one timeout wake, PENDING, no wait.

### Emit-first

1. Create another due wait.
2. Session A begins and executes `emit_event`, leaving it uncommitted.
3. Session B calls `resolve_due_waits` and blocks.
4. Session A commits.
5. Session B returns 0.
6. Assert one event wake, PENDING, no wait.

Both sessions set a finite statement timeout. A deadlock, timeout, duplicate wake, or missing wake fails the test.

## Exact retry assertions

### Default explicit failure

Starting attempt 1:

```text
fail_claim = true
status = SLEEPING
attempt = 2
available_at ≈ failure time + 30s
claim fields NULL
jobs.error NULL
```

Retry log:

```text
kind = run/sleep
payload.reason = retry
payload.failed_attempt = 1
payload.next_attempt = 2
payload.delay_seconds = 30
payload.error = original reason
```

The test compares timestamps with a bounded interval rather than exact client time.

### Terminal explicit failure

For `attempt=max_attempts`:

```text
status = ERROR
attempt unchanged
completed_at non-NULL
jobs.error.name = MAX_RECOVERY_ATTEMPTS_EXCEEDED
jobs.error.cause = original reason
```

Exactly one terminal `error` row has the same payload.

### Stale retry

For an expired attempt-1 row:

```text
release_stale = 1
attempt = 2
status = SLEEPING
delay = 30s
old token verbs return false
```

Exactly one `run/claim_timeout` has outcome retry.

### Stale terminal

For an expired row at its limit:

```text
release_stale = 1
status = ERROR
attempt unchanged
```

Log order is:

```text
run/claim_timeout
error
```

and both identify terminal exhaustion.

## Shared five-proof row

The acceptance proof is the combination of these named tests:

| Proof element | Test |
|---|---|
| Emit-before-wait | existing `test_p03_emit_before_wait_resolves_without_yield` |
| Duplicate event first-write-wins | existing `test_p03_duplicate_emit_first_write_wins` |
| Retry on the same queue row | `test_p04_retry_and_lease_expiry_stay_on_one_jobs_row` |
| Lease expiry using the same retry state | `test_p04_shared_attempt_counter_across_fail_and_lease_expiry` |
| One jobs queue and no second engine | `test_p04_no_second_queue_or_direct_log_insert` |

The P04 test must assert one `cordis.jobs` relation and one row for the run across all attempts. `run_waits`/`run_events` remain side tables, not claim sources.

## Existing assertion change/stay matrix

### `tests/test_p00_sql_source.py` — must change

1. `KERNEL_FUNCTIONS` gains:

   ```text
   cordis.resolve_due_waits
   cordis.retry_delay_seconds
   cordis.sleep_claim
   ```

   in the exact order listed in Component 9.

2. `test_fresh_apply_lists_current_tree_and_p06` expects:

   ```text
   0000_kernel.sql,
   0001_p01_claim.sql,
   0002_p02_log.sql,
   0003_p03_wait_event.sql,
   0004_p04_sleep_retry.sql,
   0006_p06_plugin_catalog.sql
   ```

3. `test_numbered_file_extension_without_loader_change` includes 0004 in the copied-tree file string before 0006 and the dynamic probe.

4. Full-tree version remains p06.

### `tests/test_p01_claim.py` — must change

1. Terminal fail fixture sets `max_attempts=1`; expected reason moves under:

   ```text
   error.name = MAX_RECOVERY_ATTEMPTS_EXCEEDED
   error.cause.reason = boom
   ```

2. Stale immediate-reclaim fixtures set:

   ```text
   retry_backoff_base_seconds = 0
   retry_backoff_max_seconds = 0
   ```

   so their original immediate-claim purpose remains valid.

3. `test_reserved_waiting_sleeping_not_claimed` is renamed/reframed to prove:
   - due WAITING remains unclaimed;
   - future SLEEPING remains unclaimed;
   - due SLEEPING is claimed.

4. `test_catalog_defaults_identity_and_index_predicates` expects ready-index status coverage for both PENDING and SLEEPING.

5. Existing stale limit tests may continue without checking the resulting state, but P04 tests own exact default backoff assertions.

### Must remain unchanged and green

- P03-only apply/version/catalog tests;
- P03 assertion that WAITING does not copy deadline into `available_at`;
- P03 event first-write and emit-before-wait behavior;
- P02 direct append monopoly;
- P02-only function/kind tests;
- P06 plugin metadata and `retry_class` tests;
- loader/preflight/rollback tests;
- full-tree p06 marker;
- no-extension/public-object rules.

## Source-boundary assertions

`test_p04_no_second_queue_or_direct_log_insert` inspects 0004 and the tree to assert:

- no `INSERT INTO cordis.agent_steps` in 0004;
- no UPDATE or DELETE targeting `cordis.agent_steps`;
- the only direct insert remains in `0002_p02_log.sql`;
- no second jobs/task/run queue table;
- no `CREATE SCHEMA absurd`;
- no public P04 object;
- no `LISTEN`, `NOTIFY`, or `pg_notify` correctness path;
- no `CREATE EXTENSION`;
- no GRANT/role/transaction-control statement;
- no reference to P06 `retry_class`, `plugin_catalog`, or `host_plugin_definitions`;
- no deadline assignment from `run_waits` to `jobs.available_at`;
- no WAITING branch in the claim candidate predicate.

Use the existing source-scan style and `load_apply_module` where preflight sanitization is required.

## Exact commands

Fast P04 suite:

```bash
uv run pytest tests/test_p04_sleep_retry.py -q
```

Required current-tree and protocol regression suite:

```bash
uv run pytest \
  tests/test_p00_sql_source.py \
  tests/test_p01_claim.py \
  tests/test_p02_agent_steps.py \
  tests/test_p03_wait_event.py \
  tests/test_p04_sleep_retry.py \
  tests/test_p06_plugin_catalog.py \
  -q
```

Required named five-proof and compatibility checks:

```bash
uv run pytest \
  tests/test_p03_wait_event.py::test_p03_emit_before_wait_resolves_without_yield \
  tests/test_p03_wait_event.py::test_p03_duplicate_emit_first_write_wins \
  tests/test_p04_sleep_retry.py::test_p04_retry_and_lease_expiry_stay_on_one_jobs_row \
  tests/test_p04_sleep_retry.py::test_p04_shared_attempt_counter_across_fail_and_lease_expiry \
  tests/test_p04_sleep_retry.py::test_p04_no_second_queue_or_direct_log_insert \
  -q
```

All commands run against the existing embedded PostgreSQL fixture. No alternate apply command, driver, or server harness is introduced.

---

## Open questions

None remaining for implementation.

The scaffold’s six questions and the additional required decisions are closed:

- sleep uses `sleep_claim`, exact log payload, and `emit_step_claimed`;
- due sleepers are claimed directly;
- deadlines use a bounded resolver plus claim piggyback;
- timeout and emit serialize on the P03 event row;
- past/`±infinity` semantics are explicit;
- timeout reuses `run/wake` with a discriminator;
- `fail_claim` is revised in place;
- retry policy is durable per jobs row;
- default max attempts and backoff are fixed;
- retry uses SLEEPING except at zero delay;
- attempts are shared;
- stale release logs, backs off, and dead-letters;
- cancellation is excluded;
- P06 `retry_class` is not consumed.

Residual work owned by later phases:

- general cancellation or force-fail;
- worker cadence/operational scheduling beyond claim piggyback;
- permissions and grants in P07/P08;
- enqueue APIs that set retry policy;
- jitter or richer paradigm policy;
- event retention;
- the pre-existing complete-claim-to-final-log gap.

---

## References

- `docs/plans/2026-08-23-pg-cordis-development.md` — P04 and shared five-proof row
- `docs/decisions/2026-08-23-pending.md` — D3, D4, D7; dead-letter name
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — locked kernel and one-queue boundaries
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` — sleep/fail/stale verbs, failure ordering, scheduler state machine
- `docs/plans/P01-jobs-claim-2026-08-23.md` — P04 extension permissions and attempt semantics
- `docs/plans/P03-wait-event-2026-08-24.md` — lock order, payload and concurrency template, deadline handoff
- `docs/reviews/2026-08-24-p03-plan-critique.md` — WAITING recovery gap, deadline serialization, deadlock reasoning
- `sql/0000_kernel.sql`
- `sql/0001_p01_claim.sql`
- `sql/0002_p02_log.sql`
- `sql/0003_p03_wait_event.sql`
- `sql/0006_p06_plugin_catalog.sql`
- `sql/README.md`
- `tests/conftest.py`
- `tests/test_p00_sql_source.py`
- `tests/test_p01_claim.py`
- `tests/test_p03_wait_event.py`
- `AGENTS.md`
- `absurd/sql/absurd.sql` — delay, due-sleeper claim, stale recovery, and wait-race morphology only; not ABI


> 💡 Continue this plan conversation with ask_oracle(chat_id: "p04-sleep-retry-deep-pla-3B7B91", new_chat: false)