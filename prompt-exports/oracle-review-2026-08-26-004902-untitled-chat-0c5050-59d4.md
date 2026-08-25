# Oracle Review



## Summary

The updated P04 plan specifies a coherent sleep, wait-timeout, retry, stale-lease recovery, and dead-letter state machine inserted as `0004_p04_sleep_retry.sql` into the existing p21 tree. It correctly preserves one `cordis.jobs` queue, separates deadline-first candidate selection from event-key lock ordering, introduces the approved prewritten-`error` terminality fence, and accounts for current P09, P10, and P11 consumers while retaining the full-tree `p21` marker. Most prior findings are fully closed, but the plan is not yet ready: its replay-validation contract remains internally contradictory and under-specified, and its prescribed floating-point finiteness check is incorrect for PostgreSQL `NaN`.

## Prior Finding Closure

| Prior finding | Status | Assessment |
|---|---|---|
| **P1.1 — Timeout sweeper deadlock** | **Fully closed** | Decision 9, Component 4, W36, concurrency analysis, and `test_p04_two_sweepers_older_deadline_insert_does_not_deadlock` consistently select by deadline and process the materialized set by event key. |
| **P1.2 — Canonical replay comparison** | **Partially closed; P1 remains** | The plan now requires catalog comparison and adversarial replay tests, but it does not pin the canonical expressions and contradicts itself over whether an incompatible deadline index is rejected or repaired. |
| **P1.3 — Obsolete p06 baseline** | **Fully closed** | The header, version ladder, file-order assertions, function inventory guidance, README impact, and verification commands consistently use the current p21 tree with `0004` inserted before `0005`. |
| **P1.4 — P09/P05 prewritten errors becoming retryable** | **Fully closed** | Decision 21 and Components 5, 6, and 8 consistently make a committed `error` event a terminality fence for both `fail_claim` and stale recovery, without changing `0021`. |
| **P1.5 — Missing P09/P10/P11 consumer integration** | **Fully closed** | W40, file-by-file impact, the assertion matrix, and regression commands cover P09 defaults, P10 sleep presence/absence, host row decoding, and P11 zero-backoff takeover fixtures. |
| **P2.1 — Floating-point overflow regression coverage** | **Fully closed** | Component 2 and the named delay test include the `1e-320`/`1e155` case, true saturation, non-finite inputs, and a large unlimited-attempt case. |

## P1 — Should Fix

### 1. Replay validation still has no single implementable contract

**File:** `docs/plans/P04-sleep-retry-2026-08-24.md`, Component 1, W34, and replay verification cases

The plan now says that defaults and checks are compared using canonical `pg_get_expr` output, but describes the expected values as whatever `test_p04_retry_policy_columns_constraints_and_indexes` observes on a clean apply. That is circular: the migration itself must know what expressions are valid before the test can certify it. The prior review explicitly required the plan to pin the expected canonical forms, but the updated plan still gives alternatives such as “`30` / `2` / `86400` or the server’s canonical double-precision form.”

The deadline-index policy is also contradictory:

- Component 1 permits `run_waits_deadline_idx` to be either dropped/recreated **or** validated.
- The same component and W41 require an incompatible same-named index to make apply **fail**.
- Dropping and recreating that index would repair the drift and make apply succeed.

An implementer cannot satisfy both contracts, and the adversarial replay test has no unambiguous expected result.

**Concrete suggestion:**

1. Pin the exact clean-apply `pg_get_expr` strings for all four defaults and all five named checks, using the repository’s supported embedded PostgreSQL version.
2. State that those literal forms are used by both the SQL catalog guard and test assertions; remove “whatever the test observes” wording.
3. Choose one deadline-index policy. To preserve the current “incompatible objects fail apply” requirement:
   - create the index if absent;
   - if present, validate its relation, access method, key columns/order, and predicate;
   - raise on any mismatch;
   - do not drop/recreate it.
4. Alternatively, if repair is intentional, explicitly change the adversarial test to expect successful canonical replacement rather than failure.

### 2. The prescribed `NaN` check is false under PostgreSQL comparison semantics

**File:** `docs/plans/P04-sleep-retry-2026-08-24.md`, Component 1 “Named constraints” and Component 2 “Validation”

The plan repeatedly states that `col = col` rejects `NaN`. PostgreSQL deliberately treats floating-point `NaN` as equal to itself and greater than ordinary finite values, so this predicate does **not** reject it. This is especially material for `retry_backoff_factor`, because its lower bound `factor >= 1` also accepts `NaN`.

An implementation following the stated predicate can therefore persist a non-finite retry policy, contradicting the plan’s validation contract and potentially producing invalid delay calculations. The named tests require rejection, but the schema prescription and future canonical-expression checks currently point implementers in the wrong direction.

**Concrete suggestion:**

- Replace the `col = col` guidance with explicit PostgreSQL-safe finite bounds, for example requiring each float to be greater than `'-Infinity'::double precision` and less than `'Infinity'::double precision`, in addition to its domain bounds.
- Apply the same rule in `retry_delay_seconds` parameter validation.
- Then pin those corrected predicates as the canonical `pg_get_expr` forms required by the replay guard and catalog tests.

## P2 — Consider

### 1. The stale prewritten-error timeout payload has no exact variant

**File:** `docs/plans/P04-sleep-retry-2026-08-24.md`, Components 6 and 8

Component 6 says that stale recovery with an existing `error` event appends a `run/claim_timeout` with `outcome="terminal"`, reuses the latest error as `jobs.error`, and does not create another error or back off. Component 8, however, says the terminal `run/claim_timeout` variant includes a dead-letter object. That is accurate for exhausted recovery, but no new dead letter exists in the prewritten-error branch.

The state transition is clear, but the historical log shape is ambiguous even though the plan otherwise treats P04 writer payloads as closed conventions.

**Concrete suggestion:** Define two terminal timeout subvariants—budget exhaustion and prewritten-error fence—and pin the fields expected for the latter. Extend `test_p04_release_stale_with_prewritten_error_is_terminal` to assert that exact payload and confirm it does not falsely identify the transition as `MAX_RECOVERY_ATTEMPTS_EXCEEDED`.

### 2. The existing P05 plan retains superseded integration guidance

**Files:** `docs/plans/P04-sleep-retry-2026-08-24.md`, Component 9; `docs/plans/P05-one-step-driver-2026-08-24.md`, “P04 retry integration”

The updated P04 plan correctly says P05/P09 failures remain terminal through the prewritten-error fence and do not require `max_attempts=1`. The existing P05 plan still instructs full-tree callers to configure `max_attempts=1` when mapping P05 failures through `fail_claim`.

This does not break the proposed runtime behavior, but it leaves conflicting implementation guidance in the repository.

**Concrete suggestion:** Add a dated supersession note to the P05 integration section stating that the approved P04 error-event fence preserves terminal P05 failures under the default policy, so `max_attempts=1` is no longer required for those prewritten-error paths.

## Final Verdict

**NOT READY**

Open P1 items:

1. Pin a single, non-contradictory canonical replay-validation contract, including the deadline-index mismatch behavior.
2. Correct the PostgreSQL floating-point finiteness predicates before making them part of the canonical checks.

All other prior P1 findings and prior P2.1 are fully closed.