# Oracle Review



The new `AGENTS.md` correctly captures the repository’s main constraints: SQL belongs under `cordis`, numbered SQL is append-only, `CREATE EXTENSION` and copied pg-agent SQL are prohibited, pgembed/pg-agent remain sibling-repository boundaries, and every P implementation requires an Oracle review before a P-only commit and push. The six work rules are compact and mostly load-bearing rather than duplicating the referenced documents. **Verdict: FAIL** — no P0 findings, but the gate has open P1 contradictions around already-landed work, the actual test harness, review closure, and review-note sequencing.

## P1 — Should fix

### 1. The gate cannot be applied to already-landed P00 as written

**Files:** `AGENTS.md:31-41`, `AGENTS.md:69-92`; `docs/reviews/2026-08-23-p00-implementation-oracle.md:6-12`

The policy applies to every P from P00 through P20 and requires Oracle to pass before that P is committed and pushed. However, P00 is already committed, while its landed review explicitly contains an open P1. Under `AGENTS.md:63`, that review is not a pass, and the required review-then-commit ordering can no longer be followed retroactively.

This leaves agents unable to determine whether the current branch is compliant, whether P00 must be reopened, or whether the gate only governs future implementations.

**Suggestion:** Add a short transition rule. Either:

- define a one-time retrospective audit for already-landed Ps, using their committed change range/current implementation and recording that the commit-order requirement predates this policy; or
- explicitly identify the last grandfathered P and make the gate prospective.

Do not describe P00 as passed under the current review note unless a later Oracle round explicitly closes its P1.

### 2. The test rule contradicts the existing `load_apply_module()` fixture

**Files:** `AGENTS.md:27`; `tests/conftest.py:74-80`

Rule 6 says agents must use subprocess apply and must not import `tools/`, but the shared harness deliberately provides `load_apply_module()` for loading `tools/apply_pg_cordis.py` through `importlib`. P01’s dollar-quote-aware preflight work is a concrete case where focused white-box tests may need that helper.

An agent following `AGENTS.md` literally may avoid the existing helper, duplicate parser logic, or build another harness—the opposite of the rule’s stated purpose.

**Suggestion:** Narrow the prohibition, for example:

> Integration/application tests use the existing `run_apply`, `psql`, and `psql_session` helpers. Focused loader unit tests may use the existing `load_apply_module()` helper. Do not turn `tools/` into a package or create a second server/apply harness.

This preserves subprocess apply as the product-path test without contradicting `conftest.py`.

### 3. Contract-conflicting P1 findings have no valid closure path, and the retry cap excludes P1 loops

**File:** `AGENTS.md:23-24`, `AGENTS.md:63-67`

Rule 2 correctly says the signed contract wins over an Oracle suggestion, but step 6 says to modify all P0/P1 findings and repeat until pass. If Oracle raises a P1 that contradicts D1–D9, the agent must neither implement it nor declare a pass while it remains open. Asking the user does not itself satisfy the definition of an Oracle pass.

Separately, the three-round cap applies only when P0 findings remain. A repeated P1 also blocks passage, so the current procedure permits an unlimited P1 review loop despite calling this an “空转上限.”

**Suggestion:** State that after the owner resolves a contract conflict, the agent must return that decision and the governing contract to the same Oracle chat until the finding is explicitly withdrawn or closed. A user response alone is not an Oracle pass. Extend the three-round/no-progress cap to unresolved blocking findings—P0 **or P1**—and require escalation rather than endless review.

### 4. The selection and review-note sequence is internally inconsistent

**File:** `AGENTS.md:34`, `AGENTS.md:59-64`, `AGENTS.md:71`

Step 2 says selection should contain only files actually changed by the P, while also naming the P plan and a review note that is “about to be written.” Normally the plan and signed contract are unchanged but are still essential review criteria, while the review note does not exist until after the Oracle response.

There is also a bookkeeping loop: line 34 requires every post-pass modification to be reviewed again, but line 62 requires writing or updating the review note after the response. Read literally, recording a passing response invalidates that response and requires another round, whose result then changes the note again.

**Suggestion:**

- Select the implementation diff **plus** the existing deep plan and only the relevant governing contract/skeleton/source documents, whether or not those documents changed.
- Do not require a nonexistent review note in the first-round selection; include its current version in later rounds.
- Explicitly exempt faithful recording of the exported Oracle verdict from invalidating a pass.
- Continue to require re-review for any post-pass change to SQL, code, tests, plans, or other implementation behavior.

## P2 — Consider

### 1. The generic regression-test trigger is narrower than the shared surfaces

**File:** `AGENTS.md:45-52`

The rule requires the P-specific test and adds the P00 suite only when the apply path or `sql/0000_*.sql` changes. Changes to `tests/conftest.py`, `pyproject.toml`/`uv.lock`, or another numbered SQL file can also affect the common apply path or current-tree installation. In particular, editing `0000` is already prohibited for later Ps, so that trigger covers little future work.

**Suggestion:** Keep the rule short, but add shared-harness/current-tree changes to the trigger, such as:

> If the P changes the apply tool, shared fixtures/environment, or the numbered SQL tree, also run `tests/test_p00_sql_source.py` and every affected earlier protocol suite named by the deep plan.

### 2. “禁止用自己读 diff” is broader than the intended anti-substitution rule

**File:** `AGENTS.md:53-57`

The wording literally prohibits the agent from reading its own diff, even though the preceding step requires verifying that the ship set contains only the current P. Agents also need to inspect changes while addressing Oracle findings. The intended constraint appears to be that self-review cannot replace the mandatory Oracle review.

**Suggestion:** Replace it with wording such as:

> 可以并且应该自查 diff，但禁止以自审、`/review` skill 或 design-agent 报告替代本闸门要求的 Oracle review。