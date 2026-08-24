# Oracle Review



The staged P05 implementation adds the planned paradigm-neutral `cordis.step_once` driver and replaceable mock `cordis.invoke_llm` hook, derives stable provider keys from `(run_id, step_name)`, validates and reuses LLM checkpoints, preserves `llm`-before-action ordering, fences all log writes through `emit_step_claimed`, and demonstrates the three-claim/three-step flow. The SQL implementation is closely aligned with the deep plan, including fail-closed wait handling, unmatched-await classification, lease fencing, max-step behavior, and propagation of invariant violations. The main blocker is that the staged change does not include the plan-required full-tree assertion updates, so the repository’s existing exact SQL-tree tests will reject the newly discovered file and functions.

## P1 — Should fix

- **`tests/test_p00_sql_source.py` (missing from the staged change): full canonical-tree assertions are not retargeted.**  
  Adding `sql/0005_p05_one_step_driver.sql` changes both the discovered file list and the exact `KERNEL_FUNCTIONS` set, but the staged diff does not update the test that pins those values. Consequently, the required full-tree suite will fail even though the isolated P05 suite passes. This also leaves W59 and the repository gate in `Agents.md` incomplete; only `tests/test_p05_one_step_driver.py` was reported as run.
  
  **Suggestion:** stage P05-only updates to `tests/test_p00_sql_source.py` that:
  - add `0005_p05_one_step_driver.sql` between `0003` and `0006`;
  - add `cordis.invoke_llm` and `cordis.step_once` to the exact function list;
  - preserve the staged-base full-tree version as `p06`;
  - avoid staging concurrent P07/P19 changes.
  
  Then run the plan-required P00/P01/P02/P03/P05/P06 regression suite, not only the isolated P05 module.

## P2 — Consider

- **`sql/README.md` (missing from the staged change): the documented numbered-tree contract omits P05.**  
  W55 and the plan’s primary-deliverables section require documentation that a tree ending at `0005` reports `p05`, while a tree continuing through `0006` reports `p06`, along with the mock-only and caller-owned-transition boundaries. None of this is staged.
  
  **Suggestion:** add the P05 marker and a short description of `step_once`, `invoke_llm`, and the explicit absence of worker/enqueue/wait/retry/HTTP behavior. Stage only the P05-specific README hunk so concurrent Px documentation is not mixed into this change.

- **`tests/test_p05_one_step_driver.py`: the required `23505` propagation contract has no automated regression test.**  
  The implementation currently appears correct: the `EXCEPTION WHEN OTHERS` block surrounds only `cordis.invoke_llm`, while the claimed `llm` append occurs afterward, so an `agent_steps_llm_step_idx` collision should propagate unchanged. However, neither the 21 tests nor the source-boundary test proves this user-highlighted contract; a later refactor could broaden the exception block and silently convert caller concurrency misuse into `P05_LLM_INVOCATION_FAILED`.
  
  **Suggestion:** add a two-session test that makes both calls enter the checkpoint-miss path with the same claim token and verifies that the losing insert raises SQLSTATE `23505`, appends no P05 error event, and leaves one durable LLM checkpoint.

- **`tests/test_p05_one_step_driver.py`: several validation and recovery branches promised by the deep plan are only partially covered.**  
  `test_p05_invalid_config_hook_and_decision_fail_durably` covers a non-object payload, an unknown action, a missing observation, and a non-object hook result, but not the other reachable validation classes implemented in `step_once`: malformed `model`, `llm_params`, or `tools`; zero/fractional/overflow `max_steps`; invalid final answers or tool arguments; and corrupted checkpoint protocol/raw/key/model fields. Direct hook tests also omit a missing run and an invalid step-name format. The three-claim test passes three worker IDs but does not assert `claimed_by` after each claim, despite the plan calling for that proof.
  
  **Suggestion:** parameterize the malformed configuration/decision/checkpoint cases and record/assert `claimed_by` immediately after each claim. These are test-coverage gaps rather than observed SQL defects.