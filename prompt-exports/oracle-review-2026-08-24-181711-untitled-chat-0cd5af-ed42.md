# Oracle Review



## Summary

The P03 ship set adds persistent scoped-event and active-wait side tables, claim-fenced `await_event`, first-write-wins `emit_event` with atomic fan-out wake-up, canonical `@event/<uuid>` log streams, and an `awaiting` extension to `run_state`. It also advances truncated-tree schema reporting to `p03`, preserves full-tree `p06`, updates documentation and current-tree assertions, and adds broad catalog, atomicity, replay, invariant-failure, and concurrency coverage. The implementation closely follows the deep plan overall, but one reachable lock cycle contradicts the plan’s deadlock-freedom claim and should be resolved before passing the implementation gate.

## P1 — Should fix

- **`sql/0003_p03_wait_event.sql:125-140, 322-331`; `docs/plans/P03-wait-event-2026-08-24.md` Component 7 — A claim-held transaction can deadlock with a concurrent await on the same run.**

  `await_event` acquires or inserts the event row before blocking on the jobs-row `UPDATE`, while the plan explicitly permits a transaction to first call `emit_step_claimed`/`checkpoint`—thereby retaining a `RUNNING` jobs-row lock—and then call `emit_event`, which waits for the event row. With the same valid claim token used concurrently, the following cycle is possible:

  1. T1 calls `emit_step_claimed(token, run_id, ...)` and retains the jobs-row lock.
  2. T2 calls `await_event(token, run_id, event, ...)`, acquires the event lock, then blocks on T1’s jobs row.
  3. T1 calls `emit_event(event, ...)` and blocks on T2’s event row.
  4. PostgreSQL detects a deadlock and aborts one transaction.

  The plan’s “fan-out targets are `WAITING`, while claim-held rows are `RUNNING`” argument does not cover this case: T2 has not inserted `run_waits` or changed the job to `WAITING` yet; it is holding the event lock while waiting to do so.

  **Suggestion:** choose and enforce one of these contracts:

  - make the jobs fence in `await_event` nonblocking while the event lock is held, for example with a fenced `FOR UPDATE SKIP LOCKED`/`NOWAIT` acquisition followed by the lease update, returning a retryable/busy result rather than waiting; or
  - forbid calling `emit_event` from a transaction that already holds a claim-fenced jobs row and split that workflow into transactions; or
  - explicitly require and enforce one in-flight transaction per claim token.

  Update the deep-plan concurrency argument accordingly and add a regression test reproducing the three-step sequence above. The current ordinary wait-vs-emitter tests do not exercise the pre-held jobs-lock case.

## P2 — Consider

- **`sql/0003_p03_wait_event.sql:218-238` — Canonical source validation accepts an `event/emit` row with no payload field.**

  The immediate branch checks the source row’s kind, scope, and name, but does not reject `src_payload IS NULL`. If the canonical row is malformed or tampered so that its nested `payload` key is absent, `await_event` returns `accepted=true`, `should_suspend=false`, and SQL `NULL` as the payload. That violates the event schema’s distinction between an invalid SQL-null payload and a valid JSON `null`.

  **Suggestion:** include `src_payload IS NULL` in the invariant check. This still accepts JSONB `null`, because JSON `null` is a non-SQL-null JSONB value. Add a corruption-path test alongside the existing cache-tampering test.

- **`tests/test_p03_wait_event.py:699-800` — The concurrency test does not establish that the second session is blocked before committing the first.**

  Both interleavings rely on `time.sleep(0.4)`. Under a slow or heavily loaded runner, the worker thread could issue its SQL only after the first session commits, allowing the test to pass without exercising the intended lock ordering.

  **Suggestion:** wait with a finite timeout until `pg_stat_activity`/`pg_locks` shows the uniquely identifiable second query waiting on a lock, then commit the first session. This would make the test deterministic and would also provide a suitable foundation for the claim-held deadlock regression above.