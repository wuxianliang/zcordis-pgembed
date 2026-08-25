# Oracle Review



## Summary

The strengthened `test_p04_two_sweepers_older_deadline_insert_does_not_deadlock` now closes the Round 2 P2. Its two event-row blockers keep sweeper A’s transaction open after the stale candidate is processed: A materializes the old-key and pause candidates, blocks on the old event, the wait is moved and resolved on the new key by sweeper B, then A skips the stale candidate and blocks on the separate pause event. At that point, `FOR UPDATE NOWAIT` on `jobs(R)` succeeds, directly proving A did not acquire or retain the stale run’s jobs-row lock; the pre-fix resolver would retain that lock and fail the assertion. Finite statement timeouts, thread completion checks, exact resolver counts, and one wake per run cover the relevant failure paths. The matching plan text accurately describes this proof, the SQL remains on the previously passing stale-candidate fast path, and the implementation review note correctly records that Round 3 was required after the post-pass test and plan changes.

## Verdict

**PASS.** The Round 1 P1 remains closed, the Round 2 P2 is now closed, and I found no remaining P0, P1, or P2 findings in the current selected implementation, test, plan, or review record.