# Oracle Review



The updated P09 implementation now satisfies the deep plan’s core contracts: handler-aware enqueue preserves the normalized requested identity, queue and tool dispatch fail closed on overloaded entrypoint names, `worker_step` claims and advances at most one job through the complete outcome state machine, and in-database tool execution remains claim-fenced and P08-authorized. The expanded tests cover the previously missing overload, volatility, effect-class, exception, replay, and one-job assertions. **Verdict: pass — no P0 or unfixed P1 findings remain.**

## P2 — Consider

- **`tests/test_p09_in_db_worker.py` — the source-boundary assertion does not cover all historical SQL files.**  
  In `test_p09_source_boundaries`, this condition:
  ```py
  assert "worker_step" not in text or path.name.startswith("000") is False
  ```
  allows `worker_step` to appear in historical files such as `0019_p19_paradigm_policies.sql` or `0020_p08_four_seam_enforcement.sql`, because those names do not start with `"000"`. That weakens the deep plan’s append-only proof even though the current diff does not modify those files.  
  **Suggestion:** for every numbered SQL file except `0021_p09_in_db_worker.sql`, directly assert that `worker_step` is absent. Consider applying the same exclusivity check to the other P09 function definitions and the `step_once` COMMENT registration.

- **`tests/test_p09_in_db_worker.py` — the explicitly planned malformed-WAITING rollback path remains untested.**  
  The suite proves a valid P03 wait and a handler that returns `wait` while still `RUNNING`, but W94 also requires malformed WAITING state to raise `P09_WAIT_STATE_INVALID` and roll back the entire worker call. That branch contains materially different behavior from the durable-failure path.  
  **Suggestion:** add a fixture that calls `await_event`, corrupts/removes its `run_waits` registration in the same transaction, and returns `wait`. Assert SQLSTATE `55000`, then verify that the claim, wait row, and handler log changes were all rolled back and the job returned to its pre-call `PENDING` state.

- **`tests/test_p09_in_db_worker.py` — enqueue rejection is not tested through the enqueue API for known unsupported handlers.**  
  `test_p09_enqueue_validates_handler_paradigm_and_payload` calls `host.p09.none` without registering it, so it only exercises the unknown-handler path. Resolver tests separately cover known host, session-select, and incompatible handlers, but W91 specifically requires those enqueue failures to insert nothing.  
  **Suggestion:** register a known host row, a session-select entry, and an ABI-incompatible queue entry, call `enqueue_job` for each, assert the planned error category, and verify the jobs count remains unchanged.