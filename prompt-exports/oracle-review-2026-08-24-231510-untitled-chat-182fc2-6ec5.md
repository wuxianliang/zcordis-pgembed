# Oracle Review

The staged Round 3 P05 implementation is aligned with the deep plan. It provides the required `cordis.step_once(text, uuid, integer DEFAULT 90)` and `cordis.invoke_llm(text, text, jsonb, text)` APIs, derives stable provider keys, skips matching checkpoints, preserves `llm`-before-action ordering, fences all P05 appends through `emit_step_claimed`, fails closed for wait and malformed await history, propagates concurrent `23505` violations, and remains within the P05 scope boundaries. The previous checkpoint JSON-type P1 is fixed: `protocol`, `fingerprint`, `provider_key`, and `model` are now required to be JSON strings before comparison. The P00 retarget is also correct for the current P07 tree, and the reported P01 failures are attributable to uncommitted P04 WIP rather than this staged P05 set. **No P0 or P1 findings remain; P05 passes the requested gate.**

## P2 — Consider

- **`tests/test_p05_one_step_driver.py` — malformed-input coverage remains incomplete.**  
  The implementation has reachable validation branches for malformed `llm_params`, malformed `tools`, fractional/negative/string/overflow `max_steps`, and corrupted checkpoint fields other than the newly covered boolean `model`. The current combined invalid-input test covers a non-object payload, blank model, `max_steps = 0`, an invalid decision, missing observation, and a non-object hook result; it does not exercise all of those remaining branches.
  
  **Suggestion:** parameterize the configuration and checkpoint cases and assert the exact durable error code, `step_name` envelope, absence of hook/tool execution, and—where applicable—the absence of a second `llm` row. This is a coverage improvement, not an observed P05 correctness defect.

- **`tests/test_p05_one_step_driver.py` — the reported regression run is isolated rather than the literal full plan command.**  
  The 110 passing tests cover the relevant P00/P02/P03/P05/P06 paths plus P01 tests compatible with the current tree. The remaining P01 failures are explicitly attributed to uncommitted P04 WIP (`max_attempts` and `SLEEPING` expectations), so they should not be charged to P05.
  
  **Suggestion:** once the concurrent P04 test changes are removed or isolated, run the exact P05 plan regression command including the complete P01 module and record that result separately. This is a verification follow-up, not a release blocker for the staged P05-only change.