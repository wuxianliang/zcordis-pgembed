# Oracle Review



## Summary

The change implements P04’s scheduler state machine on the existing `cordis.jobs` queue: durable retry policy, claim-fenced sleep, direct due-`SLEEPING` claims, bounded wait-deadline resolution, retry-aware explicit and stale failure handling, terminality fencing for prewritten errors, and atomic wake/timeout logging. It also preserves the full-tree `p21` marker, updates current consumers and documentation, and adds broad catalog, replay, concurrency, and protocol coverage. The implementation is generally aligned with the approved plan, but the timeout resolver still has a reachable cross-event deadlock involving a stale candidate whose run has moved to a different event key.

**Verdict: NOT PASSED.** No P0 findings, but the P1 below must be closed before the AGENTS.md completion gate passes.

## P1 — Should fix

- **`sql/0004_p04_sleep_retry.sql` — `cordis.resolve_due_waits` retains a jobs-row lock after detecting a stale event-key candidate, allowing a cross-event deadlock.**

  The resolver currently locks in this sequence:

  1. candidate’s old `run_events` row;
  2. the candidate’s jobs row;
  3. the current `run_waits` row;
  4. only then discovers that the current wait’s `await_id` or event key differs and executes `CONTINUE`.

  PostgreSQL retains the jobs-row lock until transaction end. A reachable sequence is:

  1. Sweeper A materializes candidates for run R on event A and another run on event B.
  2. Before A locks event A, run R is legitimately woken, reclaimed, and registered on event B.
  3. A locks event A and jobs row R, observes that R now waits on B, and skips the stale candidate—but retains the lock on jobs row R.
  4. Sweeper B, whose snapshot contains R on event B, locks event B and waits for jobs row R.
  5. Sweeper A advances to its own event-B candidate and waits for event B.

  This forms `A: jobs(R) → event(B)` versus `B: event(B) → jobs(R)`, so PostgreSQL aborts one resolver with a deadlock. Event-key ordering alone does not prevent this because the stale candidate causes a jobs row to become associated with a different event after candidate materialization.

  **Concrete suggestion:** after acquiring the candidate event-row lock, perform an **unlocked identity check** of the current `run_waits` row before locking the jobs row. If the wait is absent or its `await_id`/event key differs, skip immediately without acquiring the jobs lock. If it still matches, holding the event lock prevents legitimate emit/timeout paths from replacing that wait while the resolver proceeds with the required event → jobs → locked-wait sequence and final revalidation.

  Also strengthen `tests/test_p04_sleep_retry.py::test_p04_two_sweepers_older_deadline_insert_does_not_deadlock`. Its current `time.sleep(0.05)` does not establish that the first sweeper materialized its candidate set before the insertion, and it does not exercise wait replacement across event keys. Add deterministic lock/barrier coordination and a case where a stale candidate’s run is woken and re-registered on a later event key before the resolver locks its jobs row.