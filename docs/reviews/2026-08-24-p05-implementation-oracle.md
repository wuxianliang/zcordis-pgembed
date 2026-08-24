# P05 implementation Oracle review

Date: 2026-08-24  
Plan: `docs/plans/P05-one-step-driver-2026-08-24.md`  
Oracle chat: `untitled-chat-182FC2` (`mode: review`)

Exports:

- Round 1: `prompt-exports/oracle-review-2026-08-24-225201-untitled-chat-182fc2-640c.md`
- Round 2: `prompt-exports/oracle-review-2026-08-24-230613-untitled-chat-182fc2-0603.md`
- Round 3 (pass): `prompt-exports/oracle-review-2026-08-24-231510-untitled-chat-182fc2-6ec5.md`

## Verdict

**Pass.** Round 3 has no P0 and no open P1.

## P0 / P1 / P2

### Round 1

- P0: none
- P1: `tests/test_p00_sql_source.py` not staged (file list / `KERNEL_FUNCTIONS`)
- P2: README omitted; no `23505` test; incomplete malformed coverage; `claimed_by` not asserted

### Round 2

- Previous P1 closed
- P1: checkpoint scalar fields compared via `->>` without requiring JSON strings
- P2: `23505` timing barrier; remaining malformed cases; full P01 suite not isolated from P04 WIP; README “no worker / no retry”

### Round 3 (closed)

- P0: none
- P1: none
- P2 (open, non-blocking): remaining malformed-input parameterization; run complete P01 module after P04 WIP is isolated

## Tests recorded

Isolated tree `0000+0001+0002+0003+0005+0006+0007` (uncommitted P04/P19 SQL moved aside):

```bash
uv run pytest tests/test_p05_one_step_driver.py -q
# 21+ protocol tests in that module, including unique-violation and non-string checkpoint model

uv run pytest \
  tests/test_p00_sql_source.py \
  tests/test_p01_claim.py \
  tests/test_p02_agent_steps.py \
  tests/test_p03_wait_event.py \
  tests/test_p05_one_step_driver.py \
  tests/test_p06_plugin_catalog.py \
  -q
# 110 passed; 4 local P01 failures from uncommitted P04 expectations (max_attempts / SLEEPING), not this change set
```
