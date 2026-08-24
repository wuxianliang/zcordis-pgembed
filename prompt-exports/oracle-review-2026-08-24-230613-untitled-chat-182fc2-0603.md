# Oracle Review



The round-2 staged set correctly integrates `0005_p05_one_step_driver.sql` into the canonical tree while preserving full-tree version `p06`, documents the P05 mock-only and caller-owned boundaries, verifies all three claimants, and adds the requested two-session proof that a duplicate LLM checkpoint raises an uncaught `23505` without creating a P05 error event. **The previous P1 concerning canonical-tree assertions is closed.** No P0 issue was found; however, rechecking the explicit checkpoint-shape contract uncovered a separate P1 in the SQL validation.

## P1 — Should fix

- **`sql/0005_p05_one_step_driver.sql` — checkpoint validation does not enforce the required JSON string types.**  
  The plan requires `protocol`, `fingerprint`, `provider_key`, and `model` to be JSON strings. The implementation validates them only through `->>` comparisons:

  ```sql
  (v_ckpt.payload ->> 'model') IS DISTINCT FROM v_model
  ```

  Because `->>` converts non-string JSON values to text, a malformed checkpoint can pass. For example, a job configured with model string `"true"` accepts a checkpoint whose `model` is JSON boolean `true`, after which its stored decision may execute instead of producing `P05_LLM_CHECKPOINT_MISMATCH`. Arrays or objects can similarly match model strings containing their serialized representation. This violates the plan’s fail-closed corrupted-checkpoint contract.

  **Suggestion:** require `jsonb_typeof(...)= 'string'` for all four scalar checkpoint fields before comparing their values. Add a regression case that seeds an otherwise matching checkpoint with `model: true` while the configured model is `"true"` and verifies mismatch, no hook call, and no tool execution.

## P2 — Consider

- **`tests/test_p05_one_step_driver.py` — the concurrent `23505` test uses a timing-dependent barrier.**  
  `time.sleep(0.4)` does not guarantee that the rival session reached the blocked checkpoint-miss append before the first transaction commits. On a slow or heavily loaded runner, the rival may start afterward, observe the completed `s-1`, and proceed to `s-2` instead of raising the intended duplicate violation.

  **Suggestion:** capture the rival backend PID and wait until `pg_stat_activity` shows it blocked on a lock, or use another deterministic two-session synchronization barrier, before committing the first transaction.

- **`tests/test_p05_one_step_driver.py` — the remaining malformed-input branches from the previous P2 are still only partially covered.**  
  The combined invalid-input test covers a non-object job payload, unknown action, missing observation, and non-object hook result. It still omits malformed `model`, `llm_params`, `tools`, and `max_steps`; invalid final answers and tool arguments; direct-hook missing-run/invalid-step cases; and malformed checkpoint scalar types. The checkpoint-type omission directly allowed the P1 above to remain unnoticed.

  **Suggestion:** parameterize these configuration, decision, hook, and checkpoint cases and assert the exact error code, envelope `step_name`, hook behavior, and absence of tool/final rows.

- **`docs/plans/P05-one-step-driver-2026-08-24.md` — W59’s full protocol regression gate has not been reported as run.**  
  The 50-test command covers P00’s exact-tree assertions and the P05 module, but the plan explicitly requires the existing P01, P02, P03, and P06 suites as well. This is a verification gap rather than evidence of a regression.

  **Suggestion:** run the plan’s six-module command over the isolated `0000+0001+0002+0003+0005+0006` tree:

  ```bash
  uv run pytest \
    tests/test_p00_sql_source.py \
    tests/test_p01_claim.py \
    tests/test_p02_agent_steps.py \
    tests/test_p03_wait_event.py \
    tests/test_p05_one_step_driver.py \
    tests/test_p06_plugin_catalog.py \
    -q
  ```

  This does not require P04, P07, or P19 SQL.

- **`sql/README.md` — two W55 exclusions remain implicit rather than documented.**  
  The P05 paragraph explicitly excludes status changes, enqueue, plugin dispatch, wait, and HTTP, but the deep plan also calls for explicit “no worker” and “no retry” documentation.

  **Suggestion:** add a short sentence stating that P05 provides neither a worker loop nor retry behavior; those remain caller/later-plan responsibilities.