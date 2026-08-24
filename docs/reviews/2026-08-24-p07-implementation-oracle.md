# P07 implementation Oracle review

Date: 2026-08-24  
Plan: `docs/plans/P07-grant-registry-2026-08-24.md`  
Oracle export (round 1): `prompt-exports/oracle-review-2026-08-24-225103-untitled-chat-4df6c6-5704.md`  
Chat: `untitled-chat-4DF6C6`

## Round 1

**Verdict:** not pass (no P0; three P1; two P2)

### P0

None.

### P1

1. `slice_has_grant` omitted the registered-corpus EXISTS check (`unknown named corpus` / `22023`).
2. `issue_grant` captured `clock_timestamp()` before the slice `FOR UPDATE`, so `decided_at` could predate the linearized decision (and `created_at`).
3. Function label validation used `\\x01-\\x1F\\x7F` while the table CHECK uses `[[:cntrl:]]`, allowing a `23514` leak.

### P2

1. Concurrency test did not cover every Component 6 linearization row; deny SQLSTATE check was weak.
2. Negative API matrix omitted NULL kind and unknown-corpus `slice_has_grant`.

### Folded

- `slice_has_grant` now EXISTS-checks `named_corpora`.
- `issue_grant` timestamps after slice+grant locks; fresh insert sets `created_at` and `decided_at` to that same instant.
- Label pre-check uses `[[:cntrl:]]` to match the table CHECK.
- Concurrency test covers request/issue, issue/deny (verbose `22023`), revoke/issue, deny/issue from pending, issue/revoke.
- API errors cover NULL kind, unknown-corpus has-grant, control-character label.

Tests: `uv run pytest tests/test_p07_grant_registry.py -q` → 18 passed after the fold.

## Round 3

Export: `prompt-exports/oracle-review-2026-08-24-230221-untitled-chat-4df6c6-3650.md`  
**Verdict: Pass.** No P0. No open P1. Two P2 nits (read-API error precedence; reverse request/issue race) left unfixed because they do not block the gate.

**Final: Oracle review passed.**
