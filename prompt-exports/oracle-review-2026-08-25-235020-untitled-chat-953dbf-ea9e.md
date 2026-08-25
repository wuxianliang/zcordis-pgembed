# Oracle Review



## Summary

The P04 plan specifies a coherent same-row sleep/retry state machine: claim-fenced sleep, direct claiming of due sleepers, deadline-driven wait resolution, deterministic retry backoff, shared explicit-failure/stale-lease attempt accounting, and terminal dead-lettering without introducing another queue. However, it is still written against the old p06 product baseline and retains two unresolved Oracle findings. More importantly, it does not reconcile its new retry semantics with the already-shipped P09/P05 failure path, which writes a terminal `error` event before calling `fail_claim`. As written, implementation would produce contradictory scheduler and log states and break current P09, P10, and P11 expectations. The plan is therefore **not currently ready to implement**, although it can return to that status after the P1 folds below without reopening D1–D9, snapshot §4, or any of the four mid-flow decisions.

## P1 — Should Fix

### 1. Timeout candidates are selected and locked in an order that can deadlock

**References:** `docs/plans/P04-sleep-retry-2026-08-24.md` — Resolved Decision 9, Component 4 “Candidate selection,” “Two timeout sweepers,” W36, and timeout concurrency verification; `docs/reviews/2026-08-24-p04-implementation-oracle.md` Round 3.

The plan still says that processing candidates in deadline order is deadlock-safe because deadlines are immutable. Immutability does not guarantee that concurrent sweepers selected the same candidate set. With `LIMIT`, a newly inserted older-deadline wait can change one sweeper’s set:

- Sweeper A selects event keys `B, A` by deadline and locks `B`.
- A newly inserted older wait for `A` causes sweeper B to select `A, B` and lock `A`.
- Each then waits for the other event row.

PostgreSQL will detect and abort one transaction, but this is still a reachable claim-path failure and invalidates the plan’s lock-order proof.

**Concrete suggestion:**

Use two separate orders:

1. Materialize the oldest `p_limit` due candidates using:

   ```text
   deadline, event_scope_id, event_name, run_id
   ```

2. Process that fixed candidate set using the global lock order:

   ```text
   event_scope_id, event_name, run_id
   ```

This preserves deadline fairness and index use while ensuring all sweepers acquire overlapping event locks in the same order. Update:

- Resolved Decision 9;
- Component 4 candidate selection and deadline-index rationale;
- “Two timeout sweepers” concurrency analysis;
- W36;
- the verification description.

Add a two-sweeper regression that creates differing snapshots by inserting an older-deadline wait between candidate snapshots. It should use finite `statement_timeout` and prove no deadlock.

---

### 2. Replay validation promises incompatibility detection but does not specify exact catalog comparisons

**References:** `docs/plans/P04-sleep-retry-2026-08-24.md` — Component 1 “Schema additions” and “Named constraints,” W34, catalog assertions, and replay verification; `docs/reviews/2026-08-24-p04-implementation-oracle.md` Round 3.

The plan requires incompatible pre-existing columns and constraints to fail apply, but only specifies `ADD COLUMN IF NOT EXISTS` and named catalog guards. That leaves room for the exact implementation mistake found by Oracle:

- a same-named but weaker CHECK can be accepted;
- a nonconstant default can be evaluated once and happen to return the expected value during apply;
- a same-named incompatible index can survive an `IF NOT EXISTS` guard.

This is especially important for replay into an existing p21 database, where P04 is being inserted into an already-populated migration tree.

**Concrete suggestion:**

Require exact post-DDL catalog validation:

- Compare column type, nullability, and identity/generated properties through `pg_attribute`.
- Compare defaults using canonical `pg_get_expr(pg_attrdef.adbin, pg_attrdef.adrelid)`.
- Compare every CHECK using canonical `pg_get_expr(pg_constraint.conbin, pg_constraint.conrelid)`, along with relation and constraint type.
- Define the expected canonical expression for all four defaults and all five CHECKs.
- On any mismatch, raise and roll back the tree-wide apply.
- Continue dropping/recreating `jobs_ready_idx`, and either validate the complete `run_waits_deadline_idx` definition—keys, ordering, and predicate—or explicitly drop/recreate it.

Add adversarial replay tests for:

1. a same-named weaker factor CHECK;
2. a nonconstant default that currently evaluates to `2`;
3. an incompatible same-named deadline index.

---

### 3. The full-tree baseline, version marker, function list, and test instructions are all stale at p06

**References:** `docs/plans/P04-sleep-retry-2026-08-24.md` — header, “SQL tree and tests,” Component 9 exact function list, W39, W40, File-by-file impact, Existing assertion matrix, and Exact commands; current sources `sql/README.md` and `tests/test_p00_sql_source.py:23-102`.

The current product tree is p21, not p06. Implementing W39/W40 literally would regress the README and current-tree tests by replacing the p21 file list/function inventory with the old p06 versions.

The correct post-P04 full-tree order is:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0004_p04_sleep_retry.sql
0005_p05_one_step_driver.sql
0006_p06_plugin_catalog.sql
0007_p07_grant_registry.sql
0019_p19_paradigm_policies.sql
0020_p08_four_seam_enforcement.sql
0021_p09_in_db_worker.sql
```

A truncated tree ending at `0004` reports `p04`, but the full tree still reports `p21` because `0021` applies later and replaces `get_schema_version()`. The later SQL files do not replace `claim_job`, `fail_claim`, or `release_stale`, so P04’s definitions still survive.

**Concrete suggestion:**

Update all baseline-dependent sections to state:

- P04-only tree: `0000`–`0004`, marker `p04`;
- current full tree after insertion: the list above, marker `p21`;
- `tests/test_p00_sql_source.py::KERNEL_FUNCTIONS` gains the three P04 names in the current p21 tuple rather than being replaced by the plan’s obsolete 22-name p06 tuple;
- `sql/README.md` gains a `0004` description while retaining the existing p21 current-product description;
- the full-tree test remains named/expected as p21.

The plan should no longer say the current full tree ends at `0006`, that the current marker remains p06, or that no later production layers exist.

---

### 4. P09’s prewritten `error` event makes the proposed retry transition internally contradictory

**References:** `docs/plans/P04-sleep-retry-2026-08-24.md` — Component 5, Component 8 “error” and projection effects, Component 9 call sites, and Files explicitly unchanged; `sql/0021_p09_in_db_worker.sql:466-560`; `tests/test_p09_in_db_worker.py:752-802`; `docs/plans/P05-one-step-driver-2026-08-24.md` “P04 retry integration.”

This is in scope for P04 because P04 changes the behavior of the exact `fail_claim(uuid,jsonb)` function used by P09.

Every current P09 failure path reaches `fail_claim` only after an `error` event already exists:

- for a handler/P05 `fail`, P09 reads the latest existing `error` event and passes it to `fail_claim`;
- for a P09 protocol failure, P09 first appends an `error` through `emit_step_claimed`, then calls `fail_claim`.

Under the current plan, attempt 1 is retryable by default, so `fail_claim` would move the job to `SLEEPING` and clear `jobs.error`. But `run_state` gives any committed `error` event terminal precedence. The same run would therefore be:

```text
jobs.status = SLEEPING
run_state.status = error
```

P09 would also return `outcome='fail'` while its current tests and contract expect a terminal job. This is a reachable product regression, not merely a test update.

Because `0021` is applied after `0004`, P04 cannot solve this by placing an `enqueue_job` or `worker_step` replacement inside `0004`.

**Concrete suggestion:**

The simplest compatibility rule is to make an existing log `error` a terminality fence inside the generic P04 `fail_claim`:

1. Lock and validate the claim as planned.
2. Check whether the run already has a terminal `error` event.
3. If it does, do **not** enter retry:
   - transition the job to `ERROR`;
   - use the latest log error payload as the authoritative `jobs.error`;
   - clear the claim and set `completed_at`;
   - do not append a duplicate `error`;
   - preserve the current attempt.
4. Only failures without a precommitted `error` event use the retry/backoff/dead-letter state machine.

This preserves current P09/P05 terminal failures while allowing direct P04 failures to retry. It does not reopen the dead-letter decision: `MAX_RECOVERY_ATTEMPTS_EXCEEDED` remains the envelope for actual recovery-budget exhaustion, while a prewritten `error` is already terminal historical truth.

Update:

- Summary and Goal to distinguish retryable failure causes from already-terminal log history;
- Component 5 fencing and retry eligibility;
- Component 8 projection behavior;
- Component 9 current call sites;
- Risks and migration;
- W37/W41.

Add a P04 test proving that a prelogged `error` cannot produce `SLEEPING`, plus run the existing P09 terminal-failure tests unchanged or explicitly retargeted to the chosen payload contract.

If P09 failures are instead intended to become retryable, the plan must add a new file numbered after `0021` that revises the P09/P05 error-writing contract. Editing `0021` historically or claiming that `0004` overrides it would not be valid.

---

### 5. Current P09/P10/P11 integration is absent from the file impact and verification plan

**References:** `docs/plans/P04-sleep-retry-2026-08-24.md` — Component 1 lifecycle, Component 9 call sites, W40/W41, File-by-file impact, and Exact commands; `sql/0021_p09_in_db_worker.sql:95-157`; `docs/plans/P10-host-sql-seam-2026-08-25.md`; current P11 stale-takeover proof.

The plan says no production Python or host SDK exists, and only retargets P00/P01 tests. That is no longer true:

- `cordis.enqueue_job` is the current producer. Its explicit INSERT omits retry columns, so new P09 jobs receive P04 defaults. It exposes no policy arguments.
- `pg_cordis_host` exists and probes the exact `sleep_claim` signature.
- P10 currently tests that sleep is unavailable. That assertion must not remain the full-tree expectation after `0004` lands.
- P10’s direct host `fail_claim` call can now mean “retry scheduled,” not necessarily “job terminal.”
- P11’s stale takeover expects immediate attempt-2 reclaim, whereas default P04 stale recovery produces a 30-second `SLEEPING` interval.
- Adding columns to the `cordis.jobs` composite may affect typed host claim decoding if it depends on positional `jobs.*` output.

**Concrete suggestion:**

Expand Component 9, File-by-file impact, W40/W41, and Verification to cover:

- **P09**
  - State explicitly that `enqueue_job` accepts P04 defaults and has no per-enqueue retry-policy parameters.
  - Decide that configurable producer policy remains deferred unless P04 intentionally adds a later integration API.
  - Test that a P09-enqueued row receives the exact defaults.
  - Prove P09’s prelogged failures remain terminal under the compatibility rule from finding 4.
- **P10**
  - Keep the unavailable-feature test against a copied SQL tree that deliberately excludes `0004`.
  - Add a current full-tree test in which the existing client discovers and successfully calls `sleep_claim`.
  - Update host seam documentation so a successful direct `fail_claim` can mean retry/requeue rather than necessarily `ERROR`.
  - Exercise host claim decoding after the jobs composite gains four fields.
- **P11**
  - Make the immediate-takeover fixture explicitly set zero base/max backoff, since its purpose is alternating claim ownership rather than testing the default retry delay.
  - Leave the default 30-second stale behavior to P04’s own tests.

The required regression command should include at least P00–P11 current tests, and preferably simply run the complete current suite after the focused P04 suite. The existing P05-only tests should remain on their truncated tree and continue excluding `0004`.

## P2 — Consider

### 1. Preserve the previously closed floating-point overflow issue with explicit named tests

**Reference:** `docs/plans/P04-sleep-retry-2026-08-24.md` — Component 2 and `test_p04_retry_delay_defaults_caps_and_validation`; `docs/reviews/2026-08-24-p04-implementation-oracle.md` Rounds 1–3.

The plan states that saturation must be detected before floating-point power overflow, but its named verification does not preserve the adversarial case that already failed implementation review. A future implementation could satisfy ordinary cap tests while still overflowing an intermediate `factor^exponent`.

Add explicit cases for:

- subnormal base plus huge finite factor, such as attempt 3 with base `1e-320` and factor `1e155`, where the intermediate power overflows but the mathematically final result is finite;
- a result that genuinely saturates at the cap;
- very large attempts under unlimited retry;
- `NaN`, `Infinity`, and `-Infinity` in both the evaluator and column constraints.

## Readiness Verdict

The plan is **not ready to implement in its current form**. Before restoring `Status: ready to implement`, change these exact sections:

1. **Header / Summary / Background**
   - Pin the implementation baseline to current p21.
   - Name P09, P10, and P11 as existing consumers.
2. **Resolved Decision 9**
   - Separate deadline-based candidate selection from event-key lock processing.
3. **Component 1 / W34**
   - Specify canonical default and CHECK validation.
   - Describe current `enqueue_job` default behavior.
4. **Component 4 / W36 / Concurrency**
   - Replace the false deadline-order deadlock proof.
   - Add the two-sweeper regression.
5. **Component 5**
   - Define behavior when a terminal `error` event already exists.
6. **Component 8**
   - Reconcile projection semantics with P09/P05’s prewritten errors.
7. **Component 9**
   - Replace the obsolete p06 function list and “no host SDK” statement.
   - Document current P09/P10 call sites.
8. **W39/W40/W41 and File-by-file impact**
   - Keep the full marker at p21.
   - Add P09, P10, and P11 test impacts.
9. **Risks and migration**
   - Document direct-host failure retries and existing-error terminality.
10. **Verification**
    - Use the current p21 file/function expectations and run the current full regression suite.

After those folds, the plan can return to **ready to implement** without reopening any locked architectural or mid-flow decision. The prior implementation Oracle review nevertheless remains unpassed; revising this plan does not itself authorize or constitute Round 4 under the `AGENTS.md` three-round cap.