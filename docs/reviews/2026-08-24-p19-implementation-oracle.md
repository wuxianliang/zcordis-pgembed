# P19 implementation Oracle review

Date: 2026-08-24
Plan: `docs/plans/P19-paradigm-policies-2026-08-24.md`
Critique: `docs/reviews/2026-08-24-p19-plan-critique.md`
Oracle chat: `untitled-chat-D2B4AE`

## Round 1

Export: `prompt-exports/oracle-review-2026-08-24-230729-untitled-chat-d2b4ae-adbb.md`
Snapshot: `2026-08-24/2301`
Verdict: **Not pass.** No P0. Two P1. Three P2.

### P0

None.

### P1

- Clip validator: `(v_clip_raw #>> '{}')::integer` overflow (`2147483648`) raised `22003` instead of `22023` / `invalid observation_clip_chars`.
- Review shipset mixed unrelated P04/P05 hunks in `tests/test_p01_claim.py` (retry/sleep claiming) and `sql/README.md` (P05 driver paragraph).

### P2

- `tests/test_p00_sql_source.py` file-list assertions weakened to substrings.
- README P05 paragraph contradicted the version ladder (`current` still `p06`).
- Built-ins in `sql/0019_p19_paradigm_policies.sql` not consistently `pg_catalog.`-qualified.

### Folded before round 2

- Validator compares clip as `numeric` against `1…1000000` before any `integer` cast; overflow/non-integer/out-of-range raise `22023` / `invalid observation_clip_chars`. Regression: `test_p19_clip_overflow_is_22023`.
- Reverted unrelated P04 hunks from `tests/test_p01_claim.py` (only full-tree `'p07'` → `'p19'` remains). README documents `0019`/`p19` as current; the committed P05 paragraph no longer calls `0005`/`0006` the current tree.
- Restored ordered `files=` lists. After P05 landed on `origin/main` (`5a5af5f`), the product file list is `0000,0001,0002,0003,0005,0006,0007,0019`. `KERNEL_FUNCTIONS` keeps P05/P07 names and adds the P19 verbs/stubs/wrapper. Builtins in `0019` are `pg_catalog.`-qualified.

Tests (round 2 shipset): `uv run pytest tests/test_p19_paradigm_policies.py tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py tests/test_p03_wait_event.py tests/test_p05_one_step_driver.py tests/test_p06_plugin_catalog.py tests/test_p07_grant_registry.py -q` → 146 passed.

## Round 2

Export: `prompt-exports/oracle-review-2026-08-24-233146-untitled-chat-d2b4ae-06e3.md`
Snapshot: `2026-08-24/2322`
Verdict: **Pass.** No P0. No P1.

### P2 (not blocking; left unfixed)

- Fresh-apply / lookup / signature tests do not pin every W190 column/named CHECK or every `pg_get_function_identity_arguments` / result type. SQL matches the plan. Adding those assertions after pass would require another implementation review.

## Final

Oracle review passed. Shipset is P19-only on top of `origin/main` (P05 + P07 product tree).
