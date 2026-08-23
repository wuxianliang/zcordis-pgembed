# Oracle Review



The revision correctly addresses the Round 1 findings concerning the shared test harness, Oracle conflict escalation, the three-round cap, review selection, review-note sequencing, regression triggers, and self-review wording. The six “开工规则” remain compact and source-linked. However, the transition still conflicts with the repository’s actual landed state, and two reachable paths can still make the gate impossible to apply or push changes outside the reviewed P. **Verdict: FAIL — no P0, but open P1 findings remain.**

## P1 — Should fix

### 1. P01 is already committed and pushed, so it cannot use the claimed prospective gate

**File:** `AGENTS.md:39`, `AGENTS.md:61-67`

The transition says the gate applies to implementations not yet committed as that P, but then says P01 and later use the full gate. In snapshot `2026-08-23/1912-2`, however, both `HEAD` and `origin/main` are already at `a721aac` (`Add P01 jobs table and dual-locus claim protocol.`), while `AGENTS.md` is still untracked. Therefore P01 predates this policy just as P00 does.

There is no P01 implementation diff left for the required working-tree review, and the required review-before-commit ordering cannot be performed retroactively. The two sentences at line 39 consequently give contradictory answers for P01.

**Suggestion:** Make the cutoff match repository history. Either:

- grandfather the already-landed P00 and P01 commits, explicitly saying neither is considered passed under this gate and that the strict gate begins with P02; or
- define a one-time retrospective P01 audit over the committed P01 change range, explicitly acknowledging that only the audit—not the original review-before-commit ordering—can be satisfied.

Do not state simply that P01 uses the normal full gate while its implementation is already on `origin/main`.

### 2. “Push this P only” checks the worktree but not commits already ahead of the remote

**File:** `AGENTS.md:55`, `AGENTS.md:61`, `AGENTS.md:74`, `AGENTS.md:88-89`

The ship-set checks and Oracle diff cover working-tree changes only. `git push -u origin HEAD`, however, pushes every local commit reachable from `HEAD` that the remote lacks. If the branch already contains an unrelated or unreviewed local commit, the final push can ship it even though the current worktree and staged P commit are clean.

That violates the stated requirement to push the reviewed P only.

**Suggestion:** Add one short precondition rather than a larger Git guide: before first review, and again before push, verify the branch’s commits ahead of its upstream contain only the current P. Stop if unrelated or unreviewed commits are present. The final check should cover both the working tree and the upstream-to-`HEAD` commit range.

### 3. A P1 conflicting with frozen snapshot §4 still has no explicit closure path

**File:** `AGENTS.md:23`, `AGENTS.md:65-66`, `AGENTS.md:102`

Line 102 correctly forbids reopening snapshot §4, but Rule 2’s escalation and Oracle-closure procedure names D1–D9 and several specific prohibitions without including snapshot §4. In the review loop, the exception is likewise phrased only as a contract conflict.

If Oracle raises a P1 that contradicts a frozen snapshot §4 decision but not one of Rule 2’s listed examples, line 66 says to implement the P1 while line 102 prohibits doing so. The agent has no explicit path to close that finding.

**Suggestion:** Add “快照 §4” to Rule 2 and refer to “合同或快照 §4 冲突” in the review-loop exception. The same owner-decision → same-Oracle-chat → explicit withdrawal/closure procedure can then apply without adding another section.