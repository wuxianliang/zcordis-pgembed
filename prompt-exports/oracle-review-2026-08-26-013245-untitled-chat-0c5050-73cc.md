# Oracle Review

## Summary

The Round 3 fixes are present in the current files. P04 now has one unambiguous readiness status; P11 accurately declares and consumes its P04 full-tree dependency; the canonical replay expressions and deadline-index policy are implementable; strict infinity bounds reject PostgreSQL `NaN` and infinities; retry/attempt semantics, prewritten-error fencing, stale recovery payloads, and lock ordering are consistent; and the P05, P09, P10, and P11 handoffs match the current p21 consumers. All prior P1.1–P1.5 and P2.1 findings are fully closed, and no new P0 or P1 remains.

## P2 — Nits

1. **`docs/plans/P04-sleep-retry-2026-08-24.md` — “Sweep invariant failure poisons every claim” overstates the blast radius.**  
   `claim_job` passes its optional `p_run_id` to both maintenance functions. A due corrupted wait can poison global polling and a targeted claim for that same run, but an unrelated targeted claim filters it out. The paragraph also says this is possible “until P07 tightens grants,” although the preceding section correctly says P07 has landed and does not restrict the install role.  
   **Suggestion:** Describe the impact as global polling plus the affected run’s targeted claims, and assign the remaining direct-SQL risk to future ACL/security work rather than P07.

2. **`docs/plans/P11-alternating-claim-2026-08-25.md` — W114’s explicit cross-protocol command omits P04.**  
   The implementation order requires relevant P04 stale-recovery tests before P11, but the listed cross-protocol command jumps from P03 to P05. P04’s own verification command covers both modules, so this does not leave the P04 implementation gate untested, but the P11 command no longer mirrors its declared dependency.  
   **Suggestion:** Add `tests/test_p04_sleep_retry.py` to W114, or list the exact P04 stale-retry tests immediately before the focused P11 command.

3. **`docs/plans/P11-alternating-claim-2026-08-25.md` — a few historical P01-era phrases remain.**  
   Outstanding concern 7 still attributes immediate stale eligibility to P01’s `release_stale`, and the deferred list broadly defers “successful sleep/retry” even though P11 now verifies P04’s zero-delay stale retry. The implementation-order numbering also contains two step 12 entries.  
   **Suggestion:** Point the stale eligibility statement to P04’s zero-delay branch, narrow the deferral to explicit sleep/default backoff/dead-letter behavior, and renumber the list.

## Final Verdict

READY TO IMPLEMENT