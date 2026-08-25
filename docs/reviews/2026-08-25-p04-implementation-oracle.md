# P04 implementation Oracle review

Date: 2026-08-25
Plan: `docs/plans/P04-sleep-retry-2026-08-24.md`
Chat: `untitled-chat-CA1A61`

This is the current implementation gate. The older `docs/reviews/2026-08-24-p04-implementation-oracle.md` records a superseded WIP review and is not continued.

## Round 1

Oracle export: `prompt-exports/oracle-review-2026-08-26-033822-untitled-chat-ca1a61-be8d.md`
Diff snapshot: `_git_data/repos/zcordis-pgembed-b17cbc32/2026-08-26/0333`

Date note: the review occurred on **2026-08-25**. RepoPrompt generated the export/snapshot directory names with `2026-08-26`; those paths are recorded verbatim.

**Not passed.** No P0. One P1 / should-fix.

### P0 / blockers

None.

### P1 / should-fix

1. `cordis.resolve_due_waits` locked the candidate event row, then the jobs row, and only afterward discovered that the current wait had moved to another event key. The stale path retained the jobs lock until transaction end, allowing `jobs(R) → event(B)` to deadlock with another resolver’s `event(B) → jobs(R)`.

### P2 / nits

None.

### Fix after Round 1

- After locking the candidate’s old event row, the resolver now performs an unlocked current-wait identity check. An absent/replaced wait skips before acquiring the jobs lock.
- A still-matching candidate continues through the required event → jobs → locked-wait sequence and final revalidation.
- `test_p04_two_sweepers_older_deadline_insert_does_not_deadlock` now uses deterministic coordination: an old-event row lock blocks sweeper A after candidate materialization; a trusted fixture moves the same run’s wait to a new event key; sweeper B resolves the replacement; A then skips the stale candidate without a jobs lock.
- The deep plan was updated with this stale-candidate fast path and test shape.

Post-fix verification:

- deterministic stale-replacement concurrency regression: passed;
- affected P00/P01/P04/P08/P09/P10/P11 suite: **139 passed**;
- `git diff --check`: clean before Round 1 and will be rerun before final submission.

Round 2 continues in the same Oracle chat with refreshed diff snapshot `_git_data/repos/zcordis-pgembed-b17cbc32/2026-08-26/0346`.

## Round 2

Oracle export: `prompt-exports/oracle-review-2026-08-26-035911-untitled-chat-ca1a61-e356.md`
Diff snapshot: `_git_data/repos/zcordis-pgembed-b17cbc32/2026-08-26/0346`

Date note: the review occurred on **2026-08-25**; RepoPrompt-generated paths are recorded verbatim.

**Passed.** No P0. No P1. One P2 / non-blocking test-coverage nit.

### Closed P1

The stale-candidate fast path closes Round 1: an absent/replaced wait is skipped after the old event lock and before the jobs lock; matching candidates retain event → jobs → locked-wait plus final revalidation.

### P2 / nit

The deterministic replacement test still allowed the pre-fix implementation to pass because sweeper B could resolve and commit while A remained blocked on the old event; it did not prove that A had avoided the replaced run’s jobs lock.

### P2 fix after passing Round 2

- Added a second due pause candidate and held its event row in a separate transaction.
- After sweeper B resolves the replacement, sweeper A is released from the old event, skips the stale candidate, and blocks on the pause event while keeping its transaction open.
- A separate `FOR UPDATE NOWAIT` on the replaced run’s jobs row must succeed at that point. The pre-fix implementation would retain the jobs lock and fail this assertion.
- The test retains finite statement timeouts and exact one-wake-per-run assertions.
- The deep plan’s named-test description now records this lock proof.

The strengthened regression passes. Because tests and plan changed after a passing review, Round 3 is mandatory in the same Oracle chat before the gate remains passed.

## Round 3

Oracle export: `prompt-exports/oracle-review-2026-08-26-042617-untitled-chat-ca1a61-fd86.md`
Diff snapshot: `_git_data/repos/zcordis-pgembed-b17cbc32/2026-08-26/0415`

Date note: the review occurred on **2026-08-25**; RepoPrompt-generated paths are recorded verbatim.

**PASS.** No P0, P1, or P2 findings remain. Round 2’s concurrency-test nit is closed.

The final deterministic regression proves that the fixed resolver does not retain `jobs(R)` after skipping a replaced stale candidate: sweeper A is paused on a separate event candidate, and a third transaction successfully obtains `FOR UPDATE NOWAIT` on `jobs(R)` while A’s transaction remains open. The pre-fix jobs-locking resolver would fail that assertion. The plan text records the same proof.

Post-fix checks:

- strengthened stale-replacement regression: passed;
- full P04 module: 31 passed;
- `git diff --check`: clean.

This is the implementation Oracle approval required by `AGENTS.md`. Final completion still requires the immediate P04-only commit and push; no unrelated worktree files may be staged.
