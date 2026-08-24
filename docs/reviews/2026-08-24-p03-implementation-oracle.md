# P03 implementation Oracle review

Date: 2026-08-24  
Plan: `docs/plans/P03-wait-event-2026-08-24.md`  
Oracle export: `prompt-exports/oracle-review-2026-08-24-181711-untitled-chat-0cd5af-ed42.md`  
Chat: `untitled-chat-0CD5AF` (continued)

## Verdict

**Passed on round 3.** No P0, no open P1, no P2.

## Round 1

Oracle export: `prompt-exports/oracle-review-2026-08-24-181711-untitled-chat-0cd5af-ed42.md`

### P0

None.

### P1

1. Claim-held transaction (`emit_step_claimed` then `emit_event`) can deadlock with concurrent `await_event` on the same token: await holds the event row then waits for the jobs row; the claim-held writer already holds jobs and then waits for the event row.

**Fix applied then:** `FOR UPDATE SKIP LOCKED` plus GREATEST on that `job_id`.

### P2

1. Immediate resolve accepted a canonical `event/emit` row whose nested `payload` field was SQL NULL. **Fixed:** `src_payload IS NULL` is invariant failure. `test_p03_missing_event_payload_field_raises`.
2. Concurrency test used `time.sleep(0.4)`. **Fixed:** `_wait_for_blocked_backend`.

## Round 2

Oracle export: `prompt-exports/oracle-review-2026-08-24-184054-untitled-chat-0cd5af-06ac.md`

### P0

None.

### P1 (still open)

1. `SKIP LOCKED` does not drop the event `FOR SHARE` lock: PostgreSQL row locks last until transaction end. A busy `await_event` in an explicit transaction still blocked a later `emit_event` in the claim-held txn. The autocommit regression hid this.

**Fix applied:** wrap event insert + SHARE + SKIP LOCKED in an inner PL/pgSQL block. Busy/lost raises SQLSTATE `P0301`; the subtransaction rolls back (sentinel + event lock gone) before returning `accepted=false`. Plan lock sequence / Component 7 updated. Regression now uses two open `psql_session`s: busy await returns false, holder still completes `emit_event` before the busy txn commits. Also `test_p03_json_null_emit_is_first_write` (P2).

Tests after the fix: `uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py tests/test_p03_wait_event.py -q` → 78 passed.

## Round 3

Oracle export: `prompt-exports/oracle-review-2026-08-24-184727-untitled-chat-0cd5af-0ff1.md`

### P0 / P1 / P2

None. Pass.

The inner `BEGIN … EXCEPTION` subtransaction rolls back sentinel insert and event `FOR SHARE` on SQLSTATE `P0301` before returning `accepted=false`. The two-session regression proves the claim-holding transaction can `emit_event` while the busy transaction is still open. JSON-null emit/duplicate/immediate-await is covered.
