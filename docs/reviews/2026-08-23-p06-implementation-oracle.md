# Oracle review: P06 implementation

Date: 2026-08-23  
Oracle chat: `untitled-chat-5F12AF`  
Exports:
- round 1: `prompt-exports/oracle-review-2026-08-23-205331-untitled-chat-5f12af-db84.md`
- round 2: `prompt-exports/oracle-review-2026-08-23-210009-untitled-chat-5f12af-20a4.md`
- round 3 (pass): `prompt-exports/oracle-review-2026-08-23-210611-untitled-chat-5f12af-6a5b.md`  
Plan: `docs/plans/P06-plugin-catalog-2026-08-23.md`  
Tests: `uv run pytest tests/test_p06_plugin_catalog.py tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py -q` → 70 passed.

Verdict: **PASS — no open P0 or P1.**

## Round 1 P1 (fixed)

- `refresh_plugins()` dropped candidate identity/signature when `_validate_plugin_definition` raised. Wrapped both validator calls and re-raise `22023` with COMMENT signature or host identity.

## Round 2 P1 (fixed)

- `capability: null` (JSON null, not SQL NULL) was accepted. Reject `jsonb_typeof(...) = 'null'`; covered in `test_invalid_host_registration_preserves_previous_definition`.

## Round 3

No P0. No open P1. Remaining P2 nits (README classification enum line, empty-string regression cases, `pg_get_constraintdef` depth) do not block the gate.
