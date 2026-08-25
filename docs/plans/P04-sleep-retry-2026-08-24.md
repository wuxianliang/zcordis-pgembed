# P04 — sleep and task-level retry state machine

Date: 2026-08-24
Status: **ready to implement** — Round 3 P09/P11 consumer-retarget findings folded; implementation still requires the separate AGENTS.md Oracle gate
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P04
Depends on: P01 and P03, implemented
Current product tree: **p21** (`0000`–`0003`, `0005`–`0007`, `0019`–`0021`). P05–P11 and P19 are already on `origin/main`. P09 `enqueue_job` / `worker_step`, P10 `pg_cordis_host`, and P11 alternating-claim proof are existing consumers.
Parallel with: originally P06/P07/P19; those have landed. P04 still inserts `sql/0004_p04_sleep_retry.sql` (numeric gap is reserved).
Primary deliverables: `sql/0004_p04_sleep_retry.sql`, README + current-tree tests (`test_p00`, `test_p01`, `test_p09`, `test_p10`, `test_p11`), new `tests/test_p04_sleep_retry.py`

This plan is the later rewrite from the planning export (`prompt-exports/oracle-plan-2026-08-24-213630-p04-sleep-retry-deep-2f10.md`), plus mid-flow decisions, the fold-in from `docs/reviews/2026-08-24-p04-plan-critique.md`, and the 2026-08-25 p21 re-critique (`docs/reviews/2026-08-25-p04-plan-critique.md`; Oracle `untitled-chat-953DBF`). An earlier numbered draft in the same export used a JSONB `retry_policy`, token-only `sleep_claim(uuid,timestamptz)`, and always-`SLEEPING` retries; those forks stay rejected.

### Mid-flow checkpoint (2026-08-24)

User confirmed:

1. Default `max_attempts = 3` (first-fail terminal is a fixture with `max_attempts=1`, not the kernel default).
2. `sleep_claim(uuid, text, timestamptz, integer)` matching `await_event` / `emit_step_claimed`.
3. `release_stale` shares `jobs.attempt` and the same backoff/dead-letter budget as `fail_claim`.
4. Dead-letter JSON uses `reason = "MAX_RECOVERY_ATTEMPTS_EXCEEDED"` with the original payload nested under `cause` (not a separate `name` field).

Plan critique (`docs/reviews/2026-08-24-p04-plan-critique.md`) findings 1–6 are folded in: deadline-first timeout **candidate selection**, no `{`-leading `COMMENT ON` in 0004, sweep-invariant poison documented (behavior unchanged), retry reclaim uses `wake_reason="sleep"`, closed payloads are writer conventions, `make_interval` + no `p_now`.

### Mid-flow checkpoint (2026-08-25)

User confirmed the 2026-08-25 critique board (all yes):

1. Timeout sweepers **select** the oldest `p_limit` due waits by `deadline, event_scope_id, event_name, run_id`, then **lock/process** that fixed set in `(event_scope_id, event_name, run_id)` order. Deadline-first lock order is rejected; it deadlocks when snapshots differ.
2. If the run already has a committed `error` log event, `fail_claim` is terminal and does not retry. Direct `fail_claim` with no prewritten `error` still uses the retry/dead-letter machine. No later file `> 0021` is required for P09/P05 compatibility.
3. P11 immediate stale-takeover fixtures set zero base/max backoff. Default 30s stale delay remains product behavior and stays in P04’s own tests.

P1.2 (canonical replay catalog comparison), P1.3 (p21 baseline), and the rest of P1.5 (P09/P10 test and docs impact) are folded below. This plan rewrite does not authorize implementation Oracle round 4.

---

## Summary

P04 completes the kernel scheduler state machine on the existing `cordis.jobs` row. It adds a claim-fenced `cordis.sleep_claim(...)`, makes due `SLEEPING` rows directly claimable without a ticker, resolves P03 wait deadlines through a bounded `cordis.resolve_due_waits(...)` sweep using the existing **event row → jobs row → wait row** lock order, and revises the existing `fail_claim`, `release_stale`, and `claim_job` definitions from a new `0004` file. Retry policy is durable per jobs row: three total attempts by default, deterministic exponential backoff with defaults `30s × 2^(attempt−1)` capped at 86400 seconds, and `NULL max_attempts` meaning unlimited. Retry and lease recovery share the existing `jobs.attempt` counter, mutate the same jobs row and `run_id`, and become terminal `ERROR` with the required `MAX_RECOVERY_ATTEMPTS_EXCEEDED` dead-letter reason when no next attempt is allowed.

Retry applies only to a live claim whose run **does not** already have a committed `error` log event. A prewritten `error` (P09 `worker_step` protocol/P05 fail paths) is already terminal historical truth: `fail_claim` then terminalizes the jobs row without backoff and without a second `error` append. Direct `fail_claim` with no such event still retries or dead-letters as specified below.

All history is appended through P02’s existing `emit_step` or `emit_step_claimed`; P04 adds no direct writer, queue, background worker, plugin retry coupling, cancellation path, or apply mechanism. `0004` does not replace P09 `enqueue_job` / `worker_step` (those live in later `0021`). New columns have defaults, so existing `INSERT` lists keep working.

---

## Goal

Implement the P04 contract from `docs/plans/2026-08-23-pg-cordis-development.md:142-150`:

- Add claim-fenced kernel sleep using the already-reserved `SLEEPING` status and `jobs.available_at`.
- Append `run/sleep` before clearing the claim.
- Make due `SLEEPING` rows eligible through the existing `claim_job`, without a separate ticker or queue.
- Resolve due P03 wait deadlines and guarantee that timeout and event emission cannot both wake one `await_id`.
- Revise task failure from always-terminal behavior to retry-or-terminal behavior, except when an `error` log event is already committed for that run (then jobs go `ERROR` immediately).
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
5. explicit failure with no prewritten `error` event retries the same jobs row with deterministic backoff;
6. exhausted explicit failure becomes terminal with `MAX_RECOVERY_ATTEMPTS_EXCEEDED`;
7. a live `fail_claim` after a committed `error` event terminalizes the jobs row and does not retry;
8. stale claims use the same attempt/backoff/dead-letter policy and append `run/claim_timeout`;
9. two timeout sweepers with differing deadline snapshots do not deadlock;
10. the shared P03+P04 proof covers emit-before-wait, duplicate events, retry, and lease expiry while retaining one jobs queue.

---

P03 used `W27`–`W33`. P04 continues with `W34`–`W41`. P06’s `W60`–`W66` range is not reused.

## Execution index

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W34 | Add durable retry policy and curve evaluator | Existing and new jobs rows have validated policy defaults; replay compares canonical `pg_get_expr` text; the deterministic curve returns bounded delays; ready index covers PENDING and SLEEPING | `sql/0004_p04_sleep_retry.sql` | P01 | Medium |
| W35 | Add claim-fenced sleep | A live claim appends `run/sleep`, enters `SLEEPING`, stores `available_at`, and clears ownership atomically | `sql/0004_p04_sleep_retry.sql` | W34, P02 | Medium |
| W36 | Add wait-deadline resolution | Select due waits deadline-first; lock/process that set in event-key order; append timeout `run/wake`; WAITING→PENDING; delete once | `sql/0004_p04_sleep_retry.sql` | P03 | Large |
| W37 | Revise explicit failure | `fail_claim(uuid,jsonb)` retries or dead-letters unless a committed `error` event already exists, in which case jobs go terminal | `sql/0004_p04_sleep_retry.sql` | W34, P02 | Large |
| W38 | Revise stale recovery and claiming | Stale claims log and retry/dead-letter; claim piggybacks timeout/stale sweeps and claims due sleepers with one timer wake | `sql/0004_p04_sleep_retry.sql` | W34–W37 | Large |
| W39 | Advance and document the P04 marker | A tree ending at 0004 reports p04; the product tree still reports p21; README describes P04 state without regressing later files | `sql/0004_p04_sleep_retry.sql`, `sql/README.md` | W34–W38 | Small |
| W40 | Retarget current-tree and consumer assertions | File/function lists stay p21 plus 0004; P09 `TREE_FILES` includes 0004; P01/P09/P10/P11 fixtures match retry defaults, error-fence, sleep presence, zero-delay takeover, and the two mandatory stale-timeout log rows | `tests/test_p00_sql_source.py`, `tests/test_p01_claim.py`, `tests/test_p09_in_db_worker.py`, `tests/test_p10_host_sql_seam.py`, `tests/test_p11_alternating_claim.py`, `docs/plans/P11-alternating-claim-2026-08-25.md`, `docs/host-sql-seam.md` | W34–W39 | Medium |
| W41 | Add P04 protocol and concurrency tests | Catalog, sleep, timeout race, two-sweeper deadlock, error-fence, retry, dead-letter, stale logging, shared attempts, replay, and one-queue proofs pass | `tests/test_p04_sleep_retry.py` | W34–W40 | Large |

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

Current product order on `origin/main` (before this P) is:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0005_p05_one_step_driver.sql
0006_p06_plugin_catalog.sql
0007_p07_grant_registry.sql
0019_p19_paradigm_policies.sql
0020_p08_four_seam_enforcement.sql
0021_p09_in_db_worker.sql
```

P04 inserts:

```text
0004_p04_sleep_retry.sql
```

between `0003` and `0005`. Numeric order makes the version sequence:

```text
0000 → p00
0001 → p01
0002 → p02
0003 → p03
0004 → p04          (truncated P04-only tree)
0005 → p05
0006 → p06
0007 → p07
0019 → p19
0020 → p20
0021 → p21          (current product tree; unchanged marker)
```

A P04-only test tree is `0000`–`0004` and reports `p04`. The full product still reports **p21** because `0021` applies later and replaces `get_schema_version()`. Later files do not replace `claim_job`, `fail_claim`, or `release_stale`, so P04’s bodies survive.

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
| P09 `enqueue_job` / `worker_step` | Producer and in-db fail/complete/yield mapping | Unchanged SQL in `0021`. New jobs columns fill from defaults. `worker_step` fail already appends `error` then calls `fail_claim`; the error-fence in Component 5 keeps those jobs terminal |
| P10 `pg_cordis_host` | Host `psql` client; probes `sleep_claim` | Sleep becomes available on the full tree; `fail_claim` may mean retry unless an `error` event already exists |
| P11 alternating-claim proof | Immediate stale takeover on one jobs row | Takeover fixtures set zero backoff; default 30s stale is not this proof’s subject |

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

## Design

## Resolved decisions

| # | Decision | Rationale | Rejected alternatives |
|---:|---|---|---|
| 1 | Retry policy is durable on each `cordis.jobs` row as scalar columns: nullable `max_attempts` plus base/factor/cap fields. | Stale recovery has no caller-supplied policy, so explicit failure and lease recovery can share one policy only if it is stored with the scheduler row. Scalar columns provide constraint-checked values without a JSON policy parser. | Passing policy only to `fail_claim`, because `release_stale` could not reproduce it; a JSONB policy, because it adds validation/parser complexity; deriving it from P06 `retry_class`, which violates the tool/task boundary. |
| 2 | Default `max_attempts` is 3 total attempts, including the initial attempt. SQL NULL means unlimited. | Three attempts gives two recoveries, matches common task semantics, and makes the counter’s meaning explicit. NULL is the deliberate opt-in for unlimited recovery. | Default unlimited, which can leave permanently failing work cycling forever; “max retries” excluding the initial attempt, which would conflict with the existing attempt value starting at 1. |
| 3 | Backoff is deterministic exponential: `min(cap, base × factor^(attempt−1))`, with defaults base 30 seconds, factor 2, cap 86400 seconds, and no jitter. | It matches the selected prior-art shape, is easy to test/replay, and keeps the curve parameterized without putting plugin-specific branches in the kernel. | Hard-coded delays; randomized jitter, which makes deterministic protocol tests and projections harder; arbitrary curve kinds or executable policy. |
| 4 | `fail_claim(uuid,jsonb)` is revised in place with the same catalog identity. It reads policy from the locked jobs row. | Existing SQL callers remain source-compatible, stale recovery can use the same durable policy, and P01 explicitly reserved this P04 revision. | A new retry verb plus unchanged terminal `fail_claim`, which creates parallel failure paths; adding policy arguments and dropping the old function, which is unnecessarily breaking and still does not solve stale recovery. |
| 5 | Retry and explicit sleep use `SLEEPING` when their wake time is in the future; zero-delay retry uses due `PENDING`. | `SLEEPING` becomes an observable timer state instead of disguising backoff as future PENDING. Zero delay need not make a transient sleeping state. | Always future PENDING, which leaves the reserved SLEEPING state mostly unused; always SLEEPING, including zero delay, which adds a meaningless state transition. |
| 6 | `claim_job` directly claims due PENDING or SLEEPING rows. No SLEEPING→PENDING ticker is added. | Eligibility can be decided in the same `FOR UPDATE SKIP LOCKED` candidate statement, as allowed by P01 and F. It avoids another worker, table scan, or transition race. | A timer/background ticker; a separate wake queue; claiming WAITING directly, which violates P03’s event-lock requirement. |
| 7 | Claiming a due SLEEPING row appends `run/wake` with `wake_reason="sleep"` in the same transaction as the new claim. Retry-backoff sleepers use this same wake reason; there is no `wake_reason="retry"`. | The sleep interval has a durable close event and cannot produce a wake without a successful claim. Distinguish retry vs requested sleep by the earlier `run/sleep` `reason` field. | Waking sleepers in a preliminary ticker; omitting wake history; a fourth wake_reason; changing P03 event wake payloads retroactively. |
| 8 | `sleep_claim(uuid,text,timestamptz,integer)` uses one `emit_step_claimed` call, then changes the locked row to SLEEPING and clears ownership. | It reuses P02’s claim-aware append and guarantees `run/sleep` is durable before claim release. The explicit run ID matches `emit_step_claimed` and `await_event` patterns. | Direct log insertion; changing status before logging; a token-only API that first performs an unfenced run-ID lookup; emitting after the claim is cleared. |
| 9 | Wait deadlines are resolved by `resolve_due_waits(p_run_id DEFAULT NULL, p_limit DEFAULT 100)`, and `claim_job` calls that same function before stale reap and candidate selection. **Selection** of the oldest `p_limit` due rows uses `deadline ASC, event_scope_id, event_name, run_id`. **Lock/process** of that already-materialized set uses `(event_scope_id, event_name, run_id)` only. The function captures its own `clock_timestamp()` and has no caller-supplied `p_now`. | One timeout mechanism for maintenance and worker polling. Deadline-first **selection** matches `run_waits_deadline_idx` and prevents dictionary-order starvation under `p_limit`. Event-key **lock** order is a global sequence independent of which due subset each sweeper snapshotted, so a newly inserted older-deadline wait cannot invert overlapping event locks. Capturing now inside the function prevents resolving future waits early. | Timeout logic duplicated inside claim; an independent daemon; copying deadline into jobs; locking in deadline order (deadlocks when snapshots differ; 2026-08-24 critique finding 1 plus implementation Oracle R3); adding `p_now` for testability. |
| 10 | Timeout and emit use lock acquisition as the winner rule. A due deadline is eligible for timeout, but an event transaction that obtains the event-row lock first may still win. | PostgreSQL has no background clock edge; the event-row lock gives one atomic winner without rewriting P03 `emit_event`. This is precise and testable. | Timestamp-priority emit rewriting, which would broaden P04 into a replacement of P03 emission; allowing both outcomes to append wake; relying on notifications. |
| 11 | Due means `deadline IS NOT NULL AND deadline <= captured clock_timestamp()`. Past and `-infinity` are immediately due; `+infinity` and NULL are never due. | P03 deliberately stored all these values unchanged, so P04 must consume them rather than retroactively rejecting persisted rows. | Migrating deadlines onto jobs; rejecting old past/infinite values during apply; treating +infinity as due. |
| 12 | Timeout reuses kind `run/wake`, includes the same `await_id`, and is distinguished by `wake_reason="timeout"` plus deadline and wake time. | `run_state` already closes an await by matching `await_id`; a separate kind would require P02 CHECK and projection changes. | A new `run/timeout` kind; an `error` row, which would make timeout terminal; an event source pointer with no canonical emitted event. |
| 13 | `jobs.attempt` is the single shared execution-attempt number for explicit failure and stale-lease recovery. It increments only when a next attempt is created. | D4 names one attempt state, P01 already increments it for stale recovery, and splitting counters would need another schema and ambiguous limits. | Separate failure and lease counters; incrementing on ordinary yield, sleep, wait, or claim. |
| 14 | Exhaustion occurs when the current attempt is already `>= max_attempts`, or the integer counter cannot be incremented. The terminal row retains the last executed attempt number. | No nonexistent attempt should be recorded. Policy reduction below a current attempt must terminalize safely. | Incrementing to `max_attempts+1` before terminal failure; permitting integer overflow; resetting attempts after successful sleep or wait. |
| 15 | The terminal reason is an `error` payload and `jobs.error` object whose `reason` is exactly `MAX_RECOVERY_ATTEMPTS_EXCEEDED`; the original cause is nested under `cause`. | Mid-flow: reuse P01’s `reason` key and the D4 dead-letter string. `error->>'reason'` is the dead-letter code; tests read `cause` for the original payload. | Storing only the raw last error; a separate `name` field; a dead-letter queue; putting MAX_RECOVERY only on the log row. |
| 16 | Every stale lease appends `run/claim_timeout`. Recoverable stale leases use the same curve and attempt limit as `fail_claim`; exhausted stale leases additionally append terminal `error`. | Lease loss is one recovery source, not a special unlimited retry path. The timeout event remains durable even when the outcome is terminal. | Keeping immediate unconditional requeue; logging only terminal timeouts; using a separate stale-attempt budget. |
| 17 | P04 adds no new agent-step kind and no direct `agent_steps` writer. | Existing `run/sleep`, `run/wake`, `run/claim_timeout`, and `error` can represent every transition while preserving P02’s insert monopoly. | Adding `run/retry`; direct inserts for performance; treating `jobs.error` as historical truth. |
| 18 | P04 defines no private `P04xx` SQLSTATE. | Lost claims return false, stale candidate races skip, and invariant failures fit `object_not_in_prerequisite_state`. P03’s private code was needed to roll back a subtransaction and release an event lock; P04 has no equivalent branch. | Adding a private code without a distinct recovery contract. |
| 19 | Cancellation remains out of scope. | Timeout resolves finite waits, but D4 and the P04 parent contract do not include general cancellation. Null/+infinity waits and deliberate long sleeps remain durable until their event/time or later cancellation work. No P04 invariant requires a seventh status. | Adding CANCELLED, force-fail, or a general wake API; treating timeout as cancellation. |
| 20 | The full change is delivered in `0004_p04_sleep_retry.sql`; historical SQL remains unchanged. | Later numbered overrides are the repository’s migration mechanism. `0021` still wins the full-tree version marker (`p21`). `0004` must not replace `enqueue_job` or `worker_step`. | Editing 0001/0002/0003 or 0021; changing the loader or adding a manifest; adding a file `> 0021` in this P. |
| 21 | A committed `error` log event is a terminality fence for `fail_claim`. | P09/P05 already append `error` before calling `fail_claim`. Retrying would split `jobs.status=SLEEPING` from `run_state=error`. Mid-flow 2026-08-25: fence inside generic `fail_claim` rather than revise `0021`. Direct failures with no `error` event still retry. | Treating prewritten errors as retryable; a later `> 0021` P09 contract file; `max_attempts=1` on every `enqueue_job` (would disable scheduler retry for all in-db jobs). |

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

| Name | Predicate the CHECK must implement |
|---|---|
| `jobs_max_attempts_check` | `max_attempts IS NULL OR max_attempts >= 1` |
| `jobs_retry_backoff_base_check` | `retry_backoff_base_seconds > '-Infinity'::double precision AND retry_backoff_base_seconds < 'Infinity'::double precision AND retry_backoff_base_seconds >= 0 AND retry_backoff_base_seconds <= 86400` |
| `jobs_retry_backoff_factor_check` | `retry_backoff_factor > '-Infinity'::double precision AND retry_backoff_factor < 'Infinity'::double precision AND retry_backoff_factor >= 1` |
| `jobs_retry_backoff_max_check` | `retry_backoff_max_seconds > '-Infinity'::double precision AND retry_backoff_max_seconds < 'Infinity'::double precision AND retry_backoff_max_seconds >= 0 AND retry_backoff_max_seconds <= 86400`
| `jobs_retry_backoff_bounds_check` | base is `<=` max |

The strict `±Infinity` bounds reject PostgreSQL float `NaN`, `Infinity`, and `-Infinity`: PostgreSQL treats `NaN = NaN` and `NaN >= 1` as true, so self-equality and ordinary lower bounds are not finiteness checks.

Columns use `ADD COLUMN IF NOT EXISTS` only as a name-existence guard, then **canonical catalog comparison**. Defaults must be constant literals, not expressions that happen to evaluate to 2/30/86400 during apply. The SQL guard and W41 assertions use these exact clean-apply outputs from the repository’s supported embedded PostgreSQL version:

```text
DEFAULT max_attempts                    = 3
DEFAULT retry_backoff_base_seconds     = 30
DEFAULT retry_backoff_factor           = 2
DEFAULT retry_backoff_max_seconds      = 86400
CHECK jobs_max_attempts_check           = ((max_attempts IS NULL) OR (max_attempts >= 1))
CHECK jobs_retry_backoff_base_check     = ((retry_backoff_base_seconds > '-Infinity'::double precision) AND (retry_backoff_base_seconds < 'Infinity'::double precision) AND (retry_backoff_base_seconds >= (0)::double precision) AND (retry_backoff_base_seconds <= (86400)::double precision))
CHECK jobs_retry_backoff_bounds_check   = (retry_backoff_base_seconds <= retry_backoff_max_seconds)
CHECK jobs_retry_backoff_factor_check   = ((retry_backoff_factor > '-Infinity'::double precision) AND (retry_backoff_factor < 'Infinity'::double precision) AND (retry_backoff_factor >= (1)::double precision))
CHECK jobs_retry_backoff_max_check      = ((retry_backoff_max_seconds > '-Infinity'::double precision) AND (retry_backoff_max_seconds < 'Infinity'::double precision) AND (retry_backoff_max_seconds >= (0)::double precision) AND (retry_backoff_max_seconds <= (86400)::double precision))
```

After DDL, 0004 compares and raises (tree-wide rollback) unless column type, nullability, generated/identity state, defaults, and all five named CHECK rows match those canonical values. CHECK comparison includes `contype='c'` and `conrelid=cordis.jobs::regclass`.

`jobs_ready_idx` is intentionally dropped and recreated because its predicate changes from PENDING-only to PENDING+SLEEPING. `run_waits_deadline_idx` follows a different replay contract: create it if absent; if the name exists, validate its relation (`cordis.run_waits`), btree access method, key columns and ascending order (`deadline, event_scope_id, event_name, run_id`), and exact predicate `(deadline IS NOT NULL)` through `pg_index`/`pg_get_expr`; raise on any mismatch and never repair an incompatible same-named index.

A same-named weaker CHECK, a volatile/nonconstant default, or an incompatible same-named deadline index must fail apply. W41 includes those three adversarial replay cases.

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

Policy values are read under the jobs row lock at failure time. Direct policy changes committed before that lock take effect; later changes block behind the transition. P04 adds no policy-update function and no per-enqueue policy arguments.

`cordis.enqueue_job` (`sql/0021_p09_in_db_worker.sql`) inserts `(run_id, job_type, payload, priority)` only. After 0004, those rows receive the column defaults (`max_attempts=3`, base 30, factor 2, cap 86400). Configurable producer policy remains later work. Protocol/P05 failures stay terminal through the `error`-event fence (Decision 21), not by forcing `max_attempts=1` on every enqueue.

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
- null, `NaN`, `Infinity`, or `-Infinity` base, factor, or max; finiteness is checked with strict `> '-Infinity'::double precision` and `< 'Infinity'::double precision` bounds;
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
- `power()` is evaluated only when `exponent * ln(factor)` is safely below the overflow threshold (implementation Oracle: log-domain cap, example attempt 3 / base `1e-320` / factor `1e155` must not overflow an intermediate and must return a finite value in range);
- return is always finite and in `[0, 86400]`.

An O(1) logarithmic threshold comparison is preferred over an attempt-count loop. It prevents pathological runtime if an unlimited job reaches a large attempt number. Named tests in W41 must include that overflow-resistant case, a true cap saturation, a very large attempt under `max_attempts NULL`, and NaN/`±Infinity` at both the evaluator and the column CHECKs.

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

`p_run_id=NULL` scans globally. A non-null run ID limits the sweep to that scheduler row. There is no `p_now` argument; the function captures `pg_catalog.clock_timestamp()` internally so callers cannot resolve future waits early.

### Deadline index

Add:

```text
run_waits_deadline_idx
  ON cordis.run_waits
     (deadline ASC, event_scope_id, event_name, run_id)
  WHERE deadline IS NOT NULL
```

This supports the global due **selection** scan (`deadline` first). Targeted scans may continue to use `run_waits_pkey`.

### Candidate selection

1. Capture one finite `t0 = pg_catalog.clock_timestamp()`.
2. Read at most `p_limit` candidate registrations satisfying:
   - optional run filter;
   - `deadline IS NOT NULL`;
   - `deadline <= t0`.
3. **Select** (materialize) that set ordered by:
   - `deadline ASC`;
   - `event_scope_id`;
   - `event_name`;
   - `run_id`.

   This is fairness under `p_limit`, not the lock order. Event-key-only **selection** would starve later dictionary keys under a persistent backlog larger than `p_limit`.
4. **Then sort that already-materialized set** for processing by:
   - `event_scope_id`;
   - `event_name`;
   - `run_id`.

   Deadline immutability does **not** make deadline-first locking safe. Two sweepers can snapshot different due subsets (`LIMIT`, or a newly inserted older-deadline wait between snapshots) and lock overlapping event rows in opposite order. Event-key order on the **fixed selected set** is a global sequence: any two sweepers that share an event key acquire that key in the same relative order as every other event key.
5. Do not lock `run_waits` during candidate discovery, because locking it before the event/jobs rows would violate P03’s global order.

Candidate rows are hints. Every field is revalidated after the correct locks are acquired.

### Per-candidate lock and resolution algorithm

For each candidate **in the event-key process order**:

1. Lock the exact `run_events` row `FOR UPDATE`.
   - Missing row is an invariant error because `run_waits_event_fkey` requires it.
2. While holding that event lock, perform an **unlocked identity check** of the current `run_waits` row for the candidate run. If it is absent, or its `await_id` / event key differs from the candidate, skip immediately without acquiring the jobs lock. This stale-candidate fast path is required: a run may have been woken and registered on another event key after candidate selection, and retaining a jobs lock for the stale old key can deadlock against a resolver processing the new key.
3. If the identity still matches, lock the candidate jobs row `FOR UPDATE`.
4. Lock the current `run_waits` row for that run `FOR UPDATE`.
5. If the wait row is absent, skip; another emit/timeout already won.
6. If its `await_id` or event key differs from the candidate, skip; this is a second defense for a replacement that raced the unlocked identity check after the event lock. The candidate became stale and a later logical wait now occupies the run.
7. Revalidate deadline:
   - null or `> t0` → skip;
   - past, `-infinity`, or equal to `t0` → due.
8. Require:
   - event payload still SQL NULL;
   - jobs status exactly `WAITING`;
   - all jobs claim fields null.
9. If the exact wait still exists but those invariants fail, raise `object_not_in_prerequisite_state`.
10. Append timeout `run/wake` through `cordis.emit_step`.
11. Update jobs:
    - `WAITING → PENDING`;
    - `available_at = t0`;
    - claim fields remain null;
    - `completed_at`, `result`, and `error` = NULL.
12. Guard the update by run ID and `status='WAITING'`; require one row.
13. Delete `run_waits` by both run ID and await ID; require one row.
14. Increment the returned count.

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

### Prewritten `error` event (terminality fence)

After the jobs row is locked and before retry eligibility:

```sql
SELECT EXISTS (
    SELECT 1
      FROM cordis.agent_steps
     WHERE run_id = <locked run_id>
       AND kind = 'error'
);
```

If true:

1. Do **not** evaluate backoff or increment `attempt`.
2. Do **not** append `run/sleep` and do **not** append a second `error` row.
3. Take the latest `error` payload (`ORDER BY seq DESC LIMIT 1`) as authoritative `jobs.error`.
4. Update the locked row: `status='ERROR'`, `error` = that payload, `result=NULL`, `completed_at=t0`, claim fields NULL, current `attempt` unchanged.
5. Require one row; return true.

This is Decision 21. It keeps P09 `worker_step` / P05 fail paths terminal without editing `0021`. `run_state` already reports `error`; jobs must match. `MAX_RECOVERY_ATTEMPTS_EXCEEDED` remains the envelope only for recovery-budget exhaustion when no `error` event existed yet.

A retryable kernel failure is a `fail_claim` whose run has **no** `error` row. P04 itself appends `run/sleep` (retry) or `error` (dead-letter) in that case.

### Retry eligibility

Reached only when the fence above is false. A next attempt is allowed only if:

```text
current attempt < integer maximum
AND
(max_attempts IS NULL OR current attempt < max_attempts)
```

If allowed:

```text
next_attempt = current attempt + 1
delay = retry_delay_seconds(current attempt, row policy)
retry_at = t0 + pg_catalog.make_interval(secs => delay)
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
  "reason": "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
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
  "reason": "CLAIM_TIMEOUT",
  "message": "worker did not finish before claim expiry",
  "claim_token": "<expired UUID>",
  "claimed_by": "<worker ID>",
  "claim_expires_at": "<timestamptz JSON string>"
}
```

The old token is logged only in the same transaction that clears it. It is expired before selection and has no authority after commit.

If the expired run already has a committed `error` event, apply Decision 21: append a prewritten-error-fence `run/claim_timeout` variant, do not append a second `error`, do not backoff, and terminalize jobs with the latest log error as `jobs.error`. A crash between P09’s `error` append and `fail_claim` must not become a retry via lease recovery.

The prewritten-error-fence timeout payload is distinct from budget exhaustion and must not claim `MAX_RECOVERY_ATTEMPTS_EXCEEDED`:

```json
{
  "reason": "claim_timeout",
  "claim_token": "<expired UUID>",
  "claimed_by": "<worker ID>",
  "claim_expires_at": "<timestamptz JSON string>",
  "outcome": "terminal",
  "terminal_reason": "PREWRITTEN_ERROR_EVENT",
  "error_seq": 7
}
```

`error_seq` is the sequence of the latest committed `error` event whose payload becomes `jobs.error`. The exact test asserts `outcome`, `terminal_reason`, the expired-claim fields, and that no `dead_letter` or `MAX_RECOVERY_ATTEMPTS_EXCEEDED` field is present.

### Recoverable stale claim

Reached only when that fence is false. Evaluate retry eligibility and delay exactly as `fail_claim`.

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
  "reason": "MAX_RECOVERY_ATTEMPTS_EXCEEDED",
  "message": "task exceeded max recovery attempts",
  "failure_source": "claim_timeout",
  "attempt": 3,
  "max_attempts": 3,
  "cause": {
    "reason": "CLAIM_TIMEOUT",
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

Two closed payload variants produced by P04 kernel writers. "Closed" is a writer convention, not a table constraint: `emit_step` / `emit_step_claimed` still accept any JSON object for these kinds (`sql/0002_p02_log.sql:102-109`). W41 must not assert that the log table contains only these shapes.

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
| P04 due sleep | `wake_reason="sleep"`, `scheduled_for`, `woken_at`; no `await_id`. Also used when claiming a retry-backoff sleeper; do not invent `wake_reason="retry"`. |

P04 does not replace P03 `emit_event` merely to add `wake_reason="event"`.

### `run/claim_timeout`

Every stale claim produces one row. `outcome` is the discriminator:

```text
retry | terminal
```

A terminal row has one of two closed writer variants: budget exhaustion carries `dead_letter` and is followed by a matching `error` row; the prewritten-error fence carries `terminal_reason="PREWRITTEN_ERROR_EVENT"` and `error_seq`, has no `dead_letter`, and is not followed by another `error` row.

The retry variant includes next attempt/time/delay. Budget-exhaustion terminal includes `dead_letter`; prewritten-error-fence terminal instead includes `terminal_reason` and `error_seq` and has no `dead_letter`.

### `error`

P04 emits `error` only for terminal explicit failure or terminal stale recovery **when no `error` row already exists**. Retry must never append `error`, preserving `run_state` correctness. If an `error` row already exists, `fail_claim` does not append another; it only terminalizes the jobs row (Decision 21).

### Projection effects

`cordis.run_state` remains unchanged:

- explicit sleep and retry backoff remain `in-progress`;
- a timeout wake matches the latest await ID, changing `awaiting` to `in-progress`;
- timer wake has no await ID and does not falsely close an await;
- terminal exhaustion appends `error`, yielding `error`;
- a prewritten P09/P05 `error` already yields `error`; the fence makes jobs `ERROR` so scheduler and projection agree;
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

### Test and production call sites

- `tests/test_p00_sql_source.py`
  - inserts the three new function names into the **current p21** `KERNEL_FUNCTIONS` tuple (C collation), do not replace that tuple with the old 22-name p06 list;
  - inserts `0004_p04_sleep_retry.sql` into the current-tree file list **between `0003` and `0005`**;
  - full-tree version remains `p21`.
- `tests/test_p01_claim.py`
  - retains the existing two-argument `fail_claim` calls;
  - changes fixture policy where terminal or zero-delay behavior is required;
  - updates SLEEPING eligibility and ready-index assertions.
- `tests/test_p09_in_db_worker.py`
  - insert `0004_p04_sleep_retry.sql` into the exact `TREE_FILES` string between `0003_p03_wait_event.sql` and `0005_p05_one_step_driver.sql`;
  - enqueue still omits retry columns; assert the four defaults on a fresh enqueue;
  - existing terminal-fail tests stay green via the `error`-event fence (no `max_attempts=1` required on enqueue).
- `tests/test_p10_host_sql_seam.py`
  - keep `test_p10_sleep_is_typed_but_unavailable_without_p04` on a copied tree that **excludes** `0004`;
  - add a full-tree case where the existing client discovers and successfully calls `sleep_claim`;
  - host `SETOF cordis.jobs` decoding must still work with four new columns (named fields / `to_jsonb`, not positional).
- `tests/test_p11_alternating_claim.py`
  - immediate stale-takeover fixture sets `retry_backoff_base_seconds = 0` and `retry_backoff_max_seconds = 0` after enqueue (Proof 1 is ownership, not default delay);
  - after host→in-db takeover, append/assert one `run/claim_timeout` with `failed_attempt=1`, `next_attempt=2`, `outcome="retry"`, and `delay_seconds=0`;
  - after in-db→host takeover, append/assert a second `run/claim_timeout` with `failed_attempt=2`, `next_attempt=3`, `outcome="retry"`, and `delay_seconds=0`;
  - both timeout rows have `step_name=NULL`; zero delay uses PENDING, so neither takeover adds `run/sleep` or timer `run/wake`; update intermediate and final exact log-order assertions accordingly.
- `tests/test_p04_sleep_retry.py`
  - exercises all new behavior, including the fence, two-sweeper lock order, and adversarial replay.
- P03-only and P05-only tests remain unchanged because their truncated trees exclude 0004.
- `docs/host-sql-seam.md` — a true `fail_claim` return can mean retry/requeue unless an `error` event already existed; sleep is present on the product tree.

Production consumers already in tree: `cordis.enqueue_job`, `cordis.worker_step`, `pg_cordis_host.CordisHostClient`. No pg-agent or scratch call site.

### Exact full-tree function-name list

`tests/test_p00_sql_source.py::KERNEL_FUNCTIONS` stays the current p21 tuple and **gains** these three names in C-collation order:

```text
… renew_claim
… request_grant
cordis.resolve_due_waits
cordis.retry_delay_seconds
… revoke_grant
… run_state
cordis.sleep_claim
… slice_has_grant
```

Do not drop P05–P11/P19 names. No overload is added for any new P04 function.

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

Both may discover overlapping unlocked candidates. They serialize on the event row. The loser sees the wait absent or changed and returns no resolution for it.

They must **not** acquire event locks in deadline order. After each sweeper materializes its own oldest-`p_limit` set, it processes that set in `(event_scope_id, event_name, run_id)` order. Differing snapshots (insert an older-deadline wait between the two `SELECT`s) then still lock shared event keys in one global order. W41 `test_p04_two_sweepers_older_deadline_insert_does_not_deadlock` proves this with finite `statement_timeout`.

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
- malformed policy values are rejected, including NaN/`±Infinity`;
- delay defaults and cap are exact, including the log-domain overflow case;
- replay preserves rows and policies;
- replay compares canonical `pg_get_expr` defaults and CHECKs and fails the three adversarial cases;
- WAITING remains absent from the ready index;
- a P09-enqueued row without explicit policy columns receives the four defaults.

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

- exact signature (no `p_now`);
- **selection** order `deadline ASC, event_scope_id, event_name, run_id`;
- **process/lock** order `(event_scope_id, event_name, run_id)` on that materialized set;
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
- no `jobs.available_at` deadline copy is introduced;
- the oldest due waits are **selected** in deadline order;
- overlapping sweepers with an inserted older-deadline wait do not deadlock and still resolve fairly.

### W37 — Retry-aware `fail_claim`

**File:** `sql/0004_p04_sleep_retry.sql`

Replace the P01 body using `CREATE OR REPLACE` with the same identity.

**Done when:**

- default failure with no prewritten `error` retries attempts 1 and 2;
- attempt 3 becomes terminal;
- a committed `error` event makes `fail_claim` terminal with no retry and no second `error` append;
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

At the end of 0004, replace `get_schema_version()` with the unchanged zero-argument identity returning `p04`. That marker is visible only on a tree that **ends** at 0004. The product tree still reports `p21` from 0021.

README documents:

- the P04-only marker `p04`;
- the current product tree still ending at `0021` / `p21`, with `0004` inserted after `0003`;
- policy defaults and NULL max semantics;
- the `error`-event terminality fence;
- direct due-SLEEPING claims;
- timeout resolver: deadline-first selection, event-key lock order, one-winner;
- same-row retry and dead-letter;
- no relationship between P04 curve fields and P06 `retry_class`.

### W40 — Retarget existing tests

**Files:**

- `tests/test_p00_sql_source.py`
- `tests/test_p01_claim.py`
- `tests/test_p09_in_db_worker.py`
- `tests/test_p10_host_sql_seam.py`
- `tests/test_p11_alternating_claim.py`
- `docs/host-sql-seam.md`

Apply the changes enumerated under **Verification → Existing assertion change/stay matrix**.

### W41 — P04 tests

**File:** `tests/test_p04_sleep_retry.py`

Use:

- a P04-ending tree containing 0000–0004 (excludes 0005+);
- the full product tree (`p21` including 0004) for current-version, P09/P10/P11, and cross-phase checks;
- `psql_session` plus a Python thread for blocking race tests;
- finite `statement_timeout` for deadlock regressions, including the two-sweeper older-deadline insert.

No new fixture or client.

---

## File-by-file impact

### `docs/plans/P04-sleep-retry-2026-08-24.md` — rewritten by this planning task

- Status is `ready to implement` after 2026-08-24 critique findings 1–6, the 2026-08-25 p21 re-critique P1.1–P1.5, and the user’s three yes votes.
- Exact APIs, policy schema, select-vs-lock order, error-event fence, tests, and migration behavior are specified.
- No runtime implementation is included in this task. This rewrite does not pass or reopen the failed implementation Oracle chat.

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
- no `COMMENT ON` whose trimmed text starts with `{` (P06 `refresh_plugins` would parse it as a plugin definition and a bad comment blocks the whole refresh).

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

Add the P04 version and behavior summary. Preserve the statement that the current full tree ends at `0021` and reports `p21`. Insert `0004` in the version ladder between `p03` and `p05`.

### `tests/test_p00_sql_source.py` — modified during implementation

- Insert `0004_p04_sleep_retry.sql` into both exact current-tree file-list assertions, between `0003_p03_wait_event.sql` and `0005_p05_one_step_driver.sql`.
- Add the three P04 function names to the existing p21 `KERNEL_FUNCTIONS` tuple (C collation).
- Keep current-tree version **p21**.
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

### `tests/test_p09_in_db_worker.py` — modified during implementation

- Insert `0004_p04_sleep_retry.sql` into `TREE_FILES` between `0003_p03_wait_event.sql` and `0005_p05_one_step_driver.sql`.
- Assert a fresh `enqueue_job` row has the four P04 defaults.
- Existing `status == ERROR` fail tests remain; they pass because those paths prewrite `error`.
- Do not edit `sql/0021_p09_in_db_worker.sql`.

### `tests/test_p10_host_sql_seam.py` — modified during implementation

- Keep the unavailable-sleep test on a tree that copies SQL **without** `0004`.
- Add a product-tree test that `CordisHostClient.sleep_claim` succeeds when 0004 is present.
- Confirm claim snapshots still decode after four new jobs columns.

### `tests/test_p11_alternating_claim.py` — modified during implementation

After enqueue, `UPDATE` the proof job to `retry_backoff_base_seconds = 0` and `retry_backoff_max_seconds = 0` so stale takeover stays immediate. Do not change the default product curve.

Retarget the exact log sequence for P04 stale history:

- after the first takeover, append one `run/claim_timeout` / `step_name=NULL` after the original five coding/yield rows, with `failed_attempt=1`, `next_attempt=2`, `outcome="retry"`, and numeric `delay_seconds=0`;
- after the second takeover, append a second such row with `failed_attempt=2` and `next_attempt=3`;
- assert neither takeover adds `run/sleep` or `run/wake`, because zero delay transitions through due PENDING and is claimed directly;
- retain the no-`final`/no-`error`, one jobs row, attempt 3, token-fencing, and ownership-flip assertions.

### `docs/plans/P11-alternating-claim-2026-08-25.md` — modified during implementation

Add a dated P04 supersession note: P04 replaces P01 stale recovery in the full tree, requires one retry `run/claim_timeout` per takeover, and therefore supersedes P11’s original “stale release adds no log” assumption. The P11 proof remains tests-only and keeps zero backoff plus marker p21.

### `docs/host-sql-seam.md` — modified during implementation

- Sleep is present on the product tree; the unavailable path is the truncated-tree test only.
- Successful `fail_claim` may be retry or terminal; callers inspect `get_job` / `run_state`. Prewritten `error` remains terminal.

### `tests/test_p04_sleep_retry.py` — added during implementation

Contains all P04 catalog, algorithm, state, atomicity, concurrency, replay, error-fence, and one-queue tests.

### Files explicitly unchanged

- `sql/0000_kernel.sql`
- `sql/0001_p01_claim.sql`
- `sql/0002_p02_log.sql`
- `sql/0003_p03_wait_event.sql`
- `sql/0005_p05_one_step_driver.sql`
- `sql/0006_p06_plugin_catalog.sql`
- `sql/0007_p07_grant_registry.sql`
- `sql/0019_p19_paradigm_policies.sql`
- `sql/0020_p08_four_seam_enforcement.sql`
- `sql/0021_p09_in_db_worker.sql`
- `pg_cordis_host/` client implementation (tests/docs only unless a positional `jobs.*` decode actually breaks — prefer tests first)
- `tools/apply_pg_cordis.py`
- `tests/conftest.py`
- `tests/test_p03_wait_event.py`
- `tests/test_p05_one_step_driver.py` (P05-only tree continues to exclude 0004)
- pg-agent SQL
- `scratch/yield_walkthrough/*`
- `absurd/sql/absurd.sql`

---

## Risks and migration

### Behavioral change to `fail_claim`

The function identity remains compatible, but its default behavior for a run **without** a committed `error` event changes from first-failure terminal ERROR to up to three total attempts. Existing callers that require immediate terminal failure without writing `error` first must create/configure the jobs row with `max_attempts=1`.

Callers that already append `error` and then call `fail_claim` (P09 `worker_step`, P05 mapped fail) stay terminal via Decision 21. Direct host `fail_claim` with no prior `error` event now means “retry scheduled unless budget is exhausted”; inspect `get_job` / `run_state` instead of assuming `ERROR`.

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

Old application code selecting `jobs.*` receives additional columns. PostgreSQL composite-return consumers that bind by position must be retargeted. Current repository tests and `pg_cordis_host` read named JSON fields; W40 includes a host decode regression after the four new columns.

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

P07 has landed; grants still do not stop the install role from writing jobs policy. P04 functions use locks and constraints but do not claim ACL-level protection. Sweep-invariant poison is narrower than when this plan was first written, but out-of-band SQL can still break `resolve_due_waits`.

### Sweep invariant failure poisons global polling and the affected targeted run

After P04, every `claim_job` calls `resolve_due_waits` then `release_stale` with the same optional `p_run_id`. If either sweep hits an impossible cross-table state, it raises `object_not_in_prerequisite_state` and rolls back the whole call — including the claim. A corrupted due wait/jobs row therefore blocks global polling and targeted claims for that affected run until the row is repaired or its `run_waits` registration is deleted; unrelated targeted claims filter it out. P01 claim depended only on jobs-row constraints, so this coupling is new. P07 has landed but does not restrict the install role; remaining out-of-band SQL risk belongs to future ACL/security work. Do not change the raise-and-rollback behavior (same all-or-nothing preference as P03), and name it so operators do not treat it as a transient claim miss.

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
11. Retarget `tests/test_p00_sql_source.py` for p21 + 0004.
12. Retarget P04-affected assertions in `tests/test_p01_claim.py`, `tests/test_p09_in_db_worker.py`, `tests/test_p10_host_sql_seam.py`, `tests/test_p11_alternating_claim.py`, and `docs/host-sql-seam.md`.
13. Add the remaining P04 catalog, failure, fence, stale, two-sweeper, same-step, replay, and source-boundary tests.
14. Run the complete verification set below.
15. Follow `AGENTS.md`: obtain an Oracle implementation review with no unresolved P0/P1, record the review, then commit and push only the P04 ship set. Do **not** continue `untitled-chat-4C838A` (three open-P1 rounds, cap hit). After this plan fold, implementation review is a **new** chat on the new ship set. P04 is not complete before that review gate and successful push.

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
| `test_p04_retry_policy_columns_constraints_and_indexes` | exact columns/defaults/checks via canonical `pg_get_expr`; PENDING+SLEEPING ready index; deadline index |
| `test_p04_retry_delay_defaults_caps_and_validation` | exponent attempt−1, defaults 30/2/86400, fixed/zero/cap, NaN/`±Infinity` raise, log-domain overflow case (`1e-320`/`1e155`), large unlimited attempt |
| `test_p04_sleep_claim_logs_and_transitions` | live claim → run/sleep + SLEEPING + exact available_at + cleared ownership |
| `test_p04_sleep_rollback_preserves_running_claim` | explicit rollback removes sleep log and restores original token |
| `test_p04_sleep_lost_claim_and_parameter_errors` | malformed values raise; lost claim returns false with no log/state change |
| `test_p04_due_sleep_is_claimed_and_logs_wake` | future sleeper skipped; due sleeper claimed with new token and one timer wake |
| `test_p04_due_sleep_claim_rollback_has_no_wake` | claim rollback leaves SLEEPING and no committed timer wake |
| `test_p04_wait_timeout_wakes_and_folds_state` | due wait → timeout wake + PENDING + wait deletion + awaiting→in-progress |
| `test_p04_wait_deadline_null_past_and_infinities` | past/−infinity due; NULL/+infinity retained; WAITING available_at remains unrelated |
| `test_p04_duplicate_timeout_resolution_is_noop` | first resolver count 1, later count 0, exactly one wake |
| `test_p04_emit_timeout_race_has_one_wake` | both winner interleavings; no deadlock; exactly one event-or-timeout wake |
| `test_p04_two_sweepers_older_deadline_insert_does_not_deadlock` | old-event and pause-event locks make ordering deterministic; sweeper A materializes the old-key candidate, the wait moves to a new key, sweeper B resolves it, then A skips the stale candidate and blocks on the pause candidate; `FOR UPDATE NOWAIT` proves A did not retain the replaced run’s jobs lock; finite timeouts and exactly one wake per run |
| `test_p04_claim_piggybacks_wait_timeout` | targeted claim resolves a due WAITING row then claims it in the same transaction |
| `test_p04_fail_requeues_same_row_with_default_backoff` | same job/run, attempt 1→2, SLEEPING, 30s delay, retry run/sleep; later due claim appends `wake_reason="sleep"` |
| `test_p04_fail_with_prewritten_error_is_terminal` | emit `error` then `fail_claim` → jobs ERROR, same payload, no `run/sleep`, no second `error`, attempt unchanged |
| `test_p04_fail_preserves_incomplete_step_name` | LLM-only step remains the next step after retry/reclaim |
| `test_p04_fail_over_limit_dead_letters` | attempt=max → ERROR, exact dead-letter name/cause, error log |
| `test_p04_fail_unlimited_and_zero_backoff` | NULL max retries; zero delay produces immediately due PENDING |
| `test_p04_release_stale_retries_and_logs_timeout` | stale attempt increments, same curve used, one run/claim_timeout, old token fenced |
| `test_p04_release_stale_over_limit_dead_letters` | exhausted stale row → run/claim_timeout + error + jobs ERROR |
| `test_p04_release_stale_with_prewritten_error_is_terminal` | expired RUNNING plus existing `error` event → exact prewritten-error-fence timeout payload + jobs ERROR, no backoff, no second `error` |
| `test_p04_shared_attempt_counter_across_fail_and_lease_expiry` | explicit fail and later stale recovery consume attempts 1→2→3 on one row |
| `test_p04_retry_and_lease_expiry_stay_on_one_jobs_row` | job_id/run_id unchanged across both recovery sources; no second scheduler row |
| `test_p04_replay_preserves_policy_sleep_wait_and_logs` | in-place apply preserves custom policy, sleeper/wait, side rows, and log |
| `test_p04_replay_rejects_weaker_factor_check` | same-named weaker CHECK fails apply |
| `test_p04_replay_rejects_nonconstant_default` | default that currently evaluates to 2 but is not a constant fails apply |
| `test_p04_replay_rejects_incompatible_deadline_index` | same-named deadline index with wrong keys/predicate fails apply |
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

with exactly one `run/wake` whose `wake_reason` is `sleep` (the same value is required when reclaiming a retry-backoff sleeper).

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
payload.delay_seconds = 30   # numeric compare; to_jsonb(30::float8) renders 30
payload.error = original reason
```

The test compares timestamps with a bounded interval rather than exact client time.

### Terminal explicit failure

For `attempt=max_attempts`:

```text
status = ERROR
attempt unchanged
completed_at non-NULL
jobs.error.reason = MAX_RECOVERY_ATTEMPTS_EXCEEDED
jobs.error.cause = original reason
```

Exactly one terminal `error` row has the same payload.

### Prewritten `error` fence

After a live claim appends `kind=error` (or a fixture inserts one) and then `fail_claim`:

```text
fail_claim = true
status = ERROR
attempt unchanged
jobs.error = latest error payload
no run/sleep row
error count unchanged
```

Default `max_attempts=3` must not produce SLEEPING in this case.

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

1. `KERNEL_FUNCTIONS` gains the three names in Component 9, inserted into the **existing p21 tuple** (not a 22-name replacement).

2. `test_fresh_apply_lists_current_tree_and_p21` expects `0004_p04_sleep_retry.sql` between `0003_p03_wait_event.sql` and `0005_p05_one_step_driver.sql`. Later files `0006`/`0007`/`0019`/`0020`/`0021` stay.

3. `test_numbered_file_extension_without_loader_change` includes 0004 in the copied-tree file string in numeric order.

4. Full-tree version remains **p21**.

### `tests/test_p01_claim.py` — must change

1. Terminal fail fixture sets `max_attempts=1`; expected reason moves under:

   ```text
   error.reason = MAX_RECOVERY_ATTEMPTS_EXCEEDED
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

Direct P01 `fail_claim` fixtures have no `error` event, so they still need `max_attempts=1` (or they would retry). That is different from P09, which prewrites `error`.

### `tests/test_p09_in_db_worker.py` — must change

1. Insert `0004_p04_sleep_retry.sql` into the exact `TREE_FILES` source list between `0003_p03_wait_event.sql` and `0005_p05_one_step_driver.sql`.
2. Add or extend a catalog/enqueue assertion that a fresh `enqueue_job` row has `max_attempts=3` and default backoff columns.
3. Keep `test_p09_worker_maps_p05_failure_to_terminal_job` and other `status == ERROR` / `error->>'code'` assertions; they remain valid under Decision 21.
4. Do not set `max_attempts=1` on every enqueue just to keep those tests green.

### `tests/test_p10_host_sql_seam.py` — must change

1. `test_p10_sleep_is_typed_but_unavailable_without_p04` applies a copied SQL tree **without** 0004 (or skips 0004 in the copy).
2. New product-tree test: client `sleep_claim` returns true and the job is `SLEEPING`.
3. Existing host claim snapshots still parse after four new jobs columns.

### `tests/test_p11_alternating_claim.py` — must change

1. After enqueue of the proof run, set zero base/max backoff so stale takeover remains immediate. Default curve is not this module’s subject.
2. Update the exact intermediate/final log lists: first takeover adds `run/claim_timeout(NULL)` after the existing five rows; second takeover adds another.
3. Assert exact timeout payloads `failed_attempt=1,next_attempt=2,delay_seconds=0` then `failed_attempt=2,next_attempt=3,delay_seconds=0`, both `outcome="retry"`.
4. Assert no `run/sleep`, timer `run/wake`, `final`, or `error` is introduced.
5. Update the P11 deep plan with the dated P04 supersession note described in File-by-file impact.

### Must remain unchanged and green

- P03-only apply/version/catalog tests;
- P03 assertion that WAITING does not copy deadline into `available_at`;
- P03 event first-write and emit-before-wait behavior;
- P02 direct append monopoly;
- P02-only function/kind tests;
- P05-only truncated-tree tests (still exclude 0004);
- P06 plugin metadata and `retry_class` tests;
- P07/P08/P19 modules except where they only pin full-tree `p21`;
- loader/preflight/rollback tests;
- full-tree **p21** marker;
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
- no WAITING branch in the claim candidate predicate;
- no `COMMENT ON` in 0004 whose text, after `btrim`, starts with `{` (`sql/0006_p06_plugin_catalog.sql:493-506`: `refresh_plugins` treats every such comment on a `cordis` function as a plugin definition).

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
  tests/test_p05_one_step_driver.py \
  tests/test_p06_plugin_catalog.py \
  tests/test_p07_grant_registry.py \
  tests/test_p08_four_seam_enforcement.py \
  tests/test_p09_in_db_worker.py \
  tests/test_p10_host_sql_seam.py \
  tests/test_p11_alternating_claim.py \
  tests/test_p19_paradigm_policies.py \
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

The 2026-08-25 board is closed (user chose yes on all three):

- timeout **selection** is deadline-first; **lock/process** is event-key order;
- a committed `error` event is a `fail_claim` / stale-recovery terminality fence (no later `> 0021` file);
- P11 immediate takeover uses a zero-backoff fixture; default 30s stale stays in P04 tests.

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
- P06 `retry_class` is not consumed;
- P09/P05 prewritten `error` stays terminal without editing `0021`;
- product-tree marker remains p21.

Residual work owned by later phases:

- general cancellation or force-fail;
- worker cadence/operational scheduling beyond claim piggyback;
- enqueue APIs that set retry policy (P09 `enqueue_job` currently accepts column defaults only);
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
- `docs/reviews/2026-08-24-p04-plan-critique.md` — deadline-first **selection**, `{` COMMENT ban, claim-path poison
- `docs/reviews/2026-08-25-p04-plan-critique.md` — p21 re-critique; select vs lock; error fence; consumer tests
- `docs/reviews/2026-08-24-p04-implementation-oracle.md` — unpassed implementation P1s folded as plan defects; do not continue that chat
- `sql/0000_kernel.sql`
- `sql/0001_p01_claim.sql`
- `sql/0002_p02_log.sql`
- `sql/0003_p03_wait_event.sql`
- `sql/0005_p05_one_step_driver.sql`
- `sql/0006_p06_plugin_catalog.sql`
- `sql/0021_p09_in_db_worker.sql`
- `sql/README.md`
- `pg_cordis_host/client.py`
- `docs/host-sql-seam.md`
- `tests/conftest.py`
- `tests/test_p00_sql_source.py`
- `tests/test_p01_claim.py`
- `tests/test_p03_wait_event.py`
- `tests/test_p09_in_db_worker.py`
- `tests/test_p10_host_sql_seam.py`
- `tests/test_p11_alternating_claim.py`
- `AGENTS.md`
- `absurd/sql/absurd.sql` — delay, due-sleeper claim, stale recovery, and wait-race morphology only; not ABI
