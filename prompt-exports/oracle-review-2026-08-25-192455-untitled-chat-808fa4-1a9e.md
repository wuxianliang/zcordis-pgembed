# Oracle Review



## Summary

The change adds the planned `0020`/`p20` isolation layer: persistent four-seam readiness catalogs, claim-fenced scoped-log writes, slice-aware recall and fold, fail-closed env admission, exact-target tool authorization, P19 fold adapters, documentation, and the central two-slice leak/feature-closure tests. The core SQL generally matches the deep plan and no P0 issue was found, but the ship set is **not ready** because two P1 issues remain: required whole-tree version pins are absent from the diff, and replay cannot repair every gate mismatch promised by the plan. **Score: P0 0, P1 2, P2 2.**

## P1 — Should fix

- **`tests/test_p01_claim.py`, `tests/test_p02_agent_steps.py`, `tests/test_p06_plugin_catalog.py`, `tests/test_p19_paradigm_policies.py` — required `p20` pin updates are missing from the ship-set diff.**  
  `0020_p08_four_seam_enforcement.sql` unconditionally changes the full-tree marker to `p20`, but only `tests/test_p00_sql_source.py` is retargeted here. The deep plan’s W87/file-impact section and the plan critique identify remaining full-tree assertions that still expect `p19`, including three assertions in `test_p19_paradigm_policies.py`. The mandatory full-suite command will therefore fail even if the new P08 module passes.  
  **Suggestion:** update only full-product-tree expectations from `p19` to `p20` in those four modules. Preserve truncated-tree expectations such as `p02`, `p06`, and P19-only behavior, and leave the dynamically calculated P19 sentinel prefix alone.

- **`sql/0020_p08_four_seam_enforcement.sql: isolation_seams seed upsert` — replay cannot reliably repair swapped or conflicting gate registrations.**  
  The plan promises that replay restores missing rows and corrects mismatched canonical rows. However, `isolation_seams_gate_fn_key` makes `gate_fn` unique, while replay repairs rows one at a time with:

  ```sql
  ON CONFLICT (seam) DO UPDATE
      SET gate_fn = EXCLUDED.gate_fn
  ```

  If two seam rows have had their gate functions swapped, or another seam currently owns the expected function, the first update encounters the unique constraint before the conflicting row is repaired. The whole tree replay then rolls back instead of restoring the latch. The current replay test covers only an already-canonical catalog, so it does not expose this case.  
  **Suggestion:** reconcile conflicting noncanonical rows in two phases—preserve their `installed_at` values, remove all conflicting/mismatched registrations, then insert the canonical rows and restore the saved timestamps. Add a replay test that swaps two `gate_fn` values through a temporary third function, verifies the feature is closed, and confirms an in-place apply repairs the catalog without timestamp churn.

## P2 — Consider

- **`tests/test_p08_four_seam_enforcement.py` — several explicit W80/W81/W88 proofs are not exercised.**  
  The skeleton’s primary leak and missing-seam tests are present, but several detailed acceptance requirements are thinner than the plan specifies:
  - `test_p08_control_plane_functions_are_not_model_tools` exercises only the identity denylist through a host plugin. It never creates COMMENT-sourced in-database plugins whose `entrypoint` resolves to each denylisted function, so removal or breakage of the OID-based branch would pass unnoticed. It also does not prove that `llm_checkpoint` remains allowed.
  - No test passes a lost or expired claim to `emit_step_scoped` and proves that it returns false without appending.
  - The replay test checks grants and `isolation_seams`, but not `isolation_fold_handlers.installed_at`, scoped log rows, slices/corpora, plugin catalog rows, or runtime paradigm policies as required by the plan.
  - The fresh-catalog test checks volatility, language, and invoker status, but not the planned `search_path=pg_catalog` configuration.
  - There is no readiness test for deleting a certified fold-handler row, even though handler certification is part of the fold latch.
  
  **Suggestion:** add focused assertions for these paths, especially a parameterized COMMENT-entrypoint denylist test, a lost-claim append test, a missing-handler closure test, and complete before/after replay snapshots.

- **`sql/README.md: 0020 description` — the documented isolated-resume contract is incomplete.**  
  The deep plan explicitly requires the README to state that pre-P08 and otherwise unscoped history is omitted from isolated folds. The current text says isolated history uses `p08_scope`, but does not clearly warn operators that existing unscoped runs cannot be resumed with their prior history through `fold_slice_messages`.  
  **Suggestion:** add a direct sentence such as: “Pre-P08 or otherwise unscoped `agent_steps` rows are omitted from isolated folds; they are not assigned to a slice automatically.”