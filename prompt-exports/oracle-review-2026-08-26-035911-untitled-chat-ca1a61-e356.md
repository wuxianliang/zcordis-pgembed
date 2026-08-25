# Oracle Review

Reconnecting... 1/5

## Summary

The Round 1 P1 is closed in the implementation: after locking the candidate event row, `cordis.resolve_due_waits` now performs a non-locking identity read of the current `run_waits` registration and skips an absent or cross-event stale candidate before acquiring the jobs-row lock; candidates that still match continue through the required event → jobs → locked-wait sequence with final identity and deadline revalidation. The remaining sleep, retry, stale-recovery, error-fence, due-sleeper claim, replay, consumer-retarget, and one-queue changes remain aligned with the approved plan. I found no remaining P0 or P1.

## P2 — Consider

- **`tests/test_p04_sleep_retry.py::test_p04_two_sweepers_older_deadline_insert_does_not_deadlock` — the test does not actually distinguish the fixed implementation from the old jobs-locking behavior.**

  Sweeper B resolves and commits the replacement while sweeper A is still blocked on the old event row. Even with the previous buggy ordering, B could complete because A has not yet reached the jobs lock; after the blocker releases, A could acquire the now-free jobs row, discover that the wait is gone, return `0`, and still satisfy every current assertion. The SQL fix itself is correct, but this test would not catch its removal.

  **Suggestion:** add a second candidate whose event row keeps A’s transaction open after it processes the stale candidate, then contend on the replaced run’s jobs row with `NOWAIT` or a finite timeout. The jobs lock should remain obtainable while A is paused. Alternatively, deterministically recreate the original cycle—A progressing from stale run R toward event B while sweeper B holds event B and requests jobs R—and assert both sweepers complete without a deadlock.

## Verdict

**PASS.** The Round 1 P1 is closed, with no open P0 or P1. The remaining finding is a non-blocking regression-test coverage gap.