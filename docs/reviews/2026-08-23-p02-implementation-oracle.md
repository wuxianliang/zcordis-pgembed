# P02 implementation Oracle review

Date: 2026-08-23  
Plan: `docs/plans/P02-agent-steps-log-2026-08-23.md`  
Oracle chat: `untitled-chat-954FFC`  
Latest export: `prompt-exports/oracle-review-2026-08-23-191548-untitled-chat-954ffc-5714.md`  
Prior rounds: `prompt-exports/oracle-review-2026-08-23-190203-untitled-chat-954ffc-2cab.md`, `prompt-exports/oracle-review-2026-08-23-190955-untitled-chat-954ffc-829a.md`

## Verdict

**PASS** on round 3. No P0, no open P1, no remaining P2.

Tests: `uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py -q` → 57 passed.

## Round 1 (not pass)

### P0

None.

### P1

1. `emit_step_claimed` / `checkpoint` returned `false` for malformed events when the token was null/unknown, instead of raising before lost-claim. **Fixed:** validate kind, `llm`/`tool` `step_name`, `s-N` format, and JSON string types before the null-token path. Tests: `test_p02_malformed_event_raises_before_lost_claim`.
2. `next_step_name` used `1 + count(completed llm rows)`, so `llm(s-5)+tool` became `s-2` and sparse `s-1`/`s-3` collided. **Fixed:** greatest numeric suffix + 1. Tests: `test_p02_sparse_next_step_name`.

### P2 (also addressed)

- Checkpoint now iterates `jsonb_array_elements … WITH ORDINALITY ORDER BY ordinality`.
- Catalog test asserts named CHECK defs, `nextval(seq)`, `clock_timestamp(created_at)`.
- Plan P01 composition diagram marked as deferred jobs-only gap.

## Round 2 (not pass)

### P1

- Suffix `::integer` overflowed on `s-2147483648`. **Fixed:** `numeric` suffix. Test asserts `s-2147483648` → `s-2147483649`.

### P2 (addressed)

- Plan algorithm step 4 now says greatest existing LLM suffix plus one.
- Catalog test maps `conname` → definition and checks exact kind set plus run-id/presence predicates.

## Round 3

PASS — no P0, P1, or remaining P2.
