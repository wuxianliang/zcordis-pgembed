# P08 implementation Oracle review

Date: 2026-08-25  
Oracle export: `prompt-exports/oracle-review-2026-08-25-192455-untitled-chat-808fa4-1a9e.md`  
Chat: `untitled-chat-808FA4`  
Plan: `docs/plans/P08-four-seam-enforcement-2026-08-24.md`  
Plan critique: `docs/reviews/2026-08-24-p08-plan-critique.md`

## Round 1

**Verdict:** not ready (no P0; two P1; two P2).

### P0

None.

### P1

1. Whole-tree `p20` pins missing from `test_p01` / `test_p02` / `test_p06` / `test_p19`. **Already present in the ship-set diff** (MAP files 06–10: `p01` two pins, `p02` full-tree pin with `P02_ONLY` still `p02`, `p06` one pin, `p19` three pins at `:112`, `:451`, `:669`). Closed without code change; pointed out in round 2.
2. `isolation_seams` replay `ON CONFLICT (seam) DO UPDATE SET gate_fn` can hit `isolation_seams_gate_fn_key` if two rows have swapped or colliding `gate_fn`. **Fix:** replace the upsert with a delete-then-insert CTE that snapshots `installed_at`, and add `test_p08_replay_repairs_swapped_gate_fns`.

### P2

1. Thinner proofs than W88 (COMMENT entrypoint denylist, lost-claim append, fold-handler deletion, fuller replay snapshot, `search_path` pin). Folded the cheap ones: lost claim, missing handler, `search_path`, fold-handler timestamps, `llm_checkpoint` not denylisted. COMMENT-on-kernel-entrypoint remains a host-identity denylist plus OID branch in SQL (kernel `COMMENT` on `emit_step` is not a valid P06 envelope).
2. README isolated-resume sentence. Folded.

## Round 2

Export: `prompt-exports/oracle-review-2026-08-25-193525-untitled-chat-808fa4-e8ce.md`  
**Verdict: ready.** P0 0, P1 0, P2 2 (docs still mention ON CONFLICT upsert; COMMENT-entrypoint and fuller replay row snapshots). P2 nits do not block.

P1.1 closed as already in MAP files 07–11. P1.2 closed by `$p08latch$` delete-and-reinsert plus `test_p08_replay_repairs_swapped_gate_fns`.
