# Oracle Review



## Summary

The ship set implements the planned P08 isolation layer across recall, fold, env read, and tool dispatch, backed by claim-fenced scoped logging and a fail-closed four-seam latch. Both previous P1 findings are closed: all identified full-tree assertions now expect `p20` while truncated trees retain their historical markers, and the `$p08latch$` reconciliation block repairs swapped `gate_fn` registrations without unique-key conflicts while preserving canonical timestamps. The reported P08 and regression suites are green. **Score: P0 0, P1 0, P2 2. The implementation is ready: there are no P0 findings and no open P1 findings.**

## P2 — Consider

- **`sql/README.md: 0020 replay description`; `docs/plans/P08-four-seam-enforcement-2026-08-24.md: Component 1` — replay documentation still describes the superseded upsert algorithm.**  
  Both documents say latch rows are reconciled using `ON CONFLICT DO UPDATE`, but the P1.2 repair now snapshots canonical `installed_at` values, deletes the catalogs, and reinserts canonical rows. The implementation is correct for the unique-`gate_fn` collision case, but the documented operational contract is no longer accurate.  
  **Suggestion:** describe the `$p08latch$` delete-and-reinsert reconciliation explicitly, including that only canonical rows survive and timestamps are preserved by canonical seam/function key.

- **`tests/test_p08_four_seam_enforcement.py` — a few exact W88 proofs remain thinner than the deep plan.**  
  In particular:
  - `test_p08_control_plane_functions_are_not_model_tools` reaches the identity denylist through a host plugin, but never registers a noncolliding COMMENT-sourced identity whose `entrypoint` is a denylisted function. Consequently, the separate OID-based `v_plugin.entrypoint` branch could regress unnoticed.
  - `test_p08_replay_preserves_existing_workspace_and_log` compares grant metadata, latch timestamps, fold-handler timestamps, and the scoped-log count, but not the complete corpus/slice/plugin rows, scoped log payloads and timestamps, or a runtime-modified paradigm policy required by the plan’s replay proof.
  
  **Suggestion:** add a parameterized COMMENT-entrypoint test using noncolliding plugin identities so authorization must reach the OID comparison, and extend replay snapshots to compare the actual relevant rows rather than only counts. These are coverage gaps, not blockers for the current implementation.