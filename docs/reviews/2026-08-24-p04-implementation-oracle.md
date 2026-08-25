# P04 implementation Oracle review

Date: 2026-08-24  
Plan: `docs/plans/P04-sleep-retry-2026-08-24.md`  
Chat: `untitled-chat-4C838A`

## Round 1

Oracle export: `prompt-exports/oracle-review-2026-08-24-225816-untitled-chat-4c838a-c52e.md`

**Not passed.** No P0. Two P1 / should-fix.

### P0 / blockers

None.

### P1 / should-fix

1. Finite-factor validation admits `NaN`. Saturation check `ln(max/base)` can overflow for tiny positive bases.
2. Replay guards (`ADD COLUMN IF NOT EXISTS`, name-only constraint existence, deadline index `IF NOT EXISTS`) can accept incompatible pre-existing objects.

### P2 / nits

- Column-constraint tests missing NaN/non-finite cases.
- No regression for deadline-first `p_limit=1` selection.
- One-queue source test should allowlist `cordis` base tables.

## Round 2

Oracle export: `prompt-exports/oracle-review-2026-08-24-232453-untitled-chat-4c838a-2d3f.md`

**Not passed.** No P0. Three P1.

1. Logarithmic threshold still left `power()` as an intermediate overflow for accepted policies (example `retry_delay_seconds(3, 1e-320, 1e155, 86400)`).
2. Replay-schema validator still skipped column defaults and four of five CHECK definitions.
3. P19 assertions mixed into the live working tree (not the isolated P04 ship set). Origin/main is P07; P04 current-tree marker stays `p07`.

## Round 3

Oracle export: `prompt-exports/oracle-review-2026-08-24-233839-untitled-chat-4c838a-28e9.md`  
Diff snapshot: `_git_data/repos/zcordis-pgembed-b17cbc32/2026-08-24/2331`

**Not passed.** No P0. Two P1 remain. Isolated worktree tests: 135 passed, 1 skipped.

Closed from round 2:

- `power()` intermediate overflow (log-domain cap + `power` only when `exponent * ln(factor) < 700`).
- P19 mix-in against snapshot 2331 (full-tree marker `p07`).

Still open:

1. Replay CHECK/default verification is still fingerprint/substring based, so a same-named `CHECK (factor >= 0 AND factor <> NaN AND factor <> Infinity)` or a nonconstant default that happens to evaluate to 2 during apply can pass. Oracle wants exact canonical `pg_get_expr(conbin)` / default expressions, not executed-once values.
2. **New:** two concurrent `resolve_due_waits` sweepers can deadlock if a newly inserted older-deadline wait inverts event-lock order between their snapshots. Suggested fix: still *select* the oldest `p_limit` rows by deadline, then *process* that set in `(event_scope_id, event_name, run_id)` order.

AGENTS.md empty-loop cap: three consecutive reviews with open P1. Stopped here; do not start round 4 unless the user authorizes it.
