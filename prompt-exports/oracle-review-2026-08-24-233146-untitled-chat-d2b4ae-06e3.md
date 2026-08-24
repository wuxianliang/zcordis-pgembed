# Oracle Review



## Summary and verdict

The staged P19 shipset adds the separate `cordis.paradigm_policies` registry, data-driven lookup and dispatch slots, strict slot-signature validation, `always_enqueue` seeds for CodeAct and RLM, replay-safe `ON CONFLICT DO NOTHING` seeding, and the PL/pgSQL observation-policy error path without introducing an identity branch or modifying `plugin_catalog`. The round-one clip overflow, shipset scope, file-list, README, and qualification findings are closed. **Verdict: Pass.** No P0 or P1 findings remain.

## P2 — Consider

- **`tests/test_p19_paradigm_policies.py:108-150`, `tests/test_p19_paradigm_policies.py:153-205`, `tests/test_p19_paradigm_policies.py:663-746` — portions of the exact P19 ABI are implemented but not directly pinned by tests.**  
  The fresh-apply test proves that `paradigm_policies` exists, but does not assert W190’s exact columns and named constraints. The lookup test omits several exact RLM seed fields, including its version, description, parse/observe names, and metadata identity. The signature test verifies volatility, language, security mode, and one function per name, but does not directly compare every identity argument and result type as required by W195. The SQL itself matches the deep plan, so this is not a release blocker; however, later ABI drift could escape the intended catalog tests. Add `pg_attribute`/`pg_constraint` assertions similar to the P01 and P06 catalog tests, and compare `pg_get_function_identity_arguments` plus `pg_get_function_result` for the P19 functions.