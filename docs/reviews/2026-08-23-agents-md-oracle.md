# Oracle review: AGENTS.md

Date: 2026-08-23  
Oracle round 1: `prompt-exports/oracle-review-2026-08-23-191130-untitled-chat-cc791a-a88d.md`  
Spec: process file `AGENTS.md` (not a numbered P)  
Round 1 verdict: **FAIL** — no P0; four open P1.

## Round 1 P1 and what changed

1. Gate could not be applied retroactively to landed P00 (open P1 in `docs/reviews/2026-08-23-p00-implementation-oracle.md`). **Fix:** prospective transition rule; P00 not claimed as passed under this file; P01+ use the full gate.
2. Rule 6 banned importing `tools/`, contradicting `tests/conftest.py` `load_apply_module()`. **Fix:** subprocess helpers for apply/integration; existing `load_apply_module()` allowed for loader unit tests; still no second harness and no packaging `tools/`.
3. Contract-conflicting P1 had no closure path; 3-round cap covered only P0. **Fix:** owner decision must return to the same Oracle chat until the finding is withdrawn; user reply is not a pass; cap is unresolved P0 **or** P1.
4. Selection required a not-yet-written review note; recording a pass would invalidate that pass. **Fix:** select implementation diff plus existing plan/contract/skeleton; first round has no review note; faithful recording of the exported verdict does not force another round; implementation edits after pass still re-review.

P2 also applied: broader shared-surface test trigger; self-reading the diff is allowed, self-review cannot replace Oracle.

## Round 2

Oracle: `prompt-exports/oracle-review-2026-08-23-191922-untitled-chat-cc791a-28d4.md`
Verdict: **FAIL** — no P0; three open P1.

1. P01 (and in fact P02) already on `origin/main`; cannot use a “P01 uses the full gate” sentence. **Fix:** grandfather P00–P02 at `709fea1`; full gate starts at the next P implementation not yet committed as that P.
2. `git push origin HEAD` can ship unrelated local commits ahead of upstream. **Fix:** before first review and again before push, `@{u}..HEAD` must contain only this P; otherwise stop.
3. Snapshot §4 conflicts had no closure path. **Fix:** Rule 2 and the review-loop exception name 合同 **or** 快照 §4.

## Round 3

Oracle: `prompt-exports/oracle-review-2026-08-23-192425-untitled-chat-cc791a-a7db.md`
Verdict: **PASS** — no P0 and no open P1.
