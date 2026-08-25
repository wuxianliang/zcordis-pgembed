# Oracle Review

## Summary

The revised P04 plan closes the Round 2 replay, floating-point finiteness, prewritten-error payload, P05 handoff, and P09/P11 retargeting findings at the plan level. The deadline-first selection/event-key processing lock order remains internally consistent, retry and shared-attempt semantics are coherent, and the verification commands cover the required current-tree consumers. However, two P1 plan inconsistencies remain: P04 still declares itself `needs revision` despite documenting that the findings are folded, and P11 simultaneously says it does not rely on P04 while requiring P04’s stale-recovery timeout history. The actual P09/P11 test files still show the pre-P04 baseline, but the revised P04 instructions explicitly identify those implementation edits; that is not itself an implementation-review finding.

## P1 — Should Fix

### 1. P04’s readiness status is stale and contradicts the rest of the plan

**File:** `docs/plans/P04-sleep-retry-2026-08-24.md`

The header still says:

```text
Status: needs revision — 2026-08-25 plan re-review has two open P1 findings
```

But the same document says those findings have been folded, its `File-by-file impact` section says the status is `ready to implement`, its `Open questions` section says none remain, and the current Round 3 changes explicitly close the remaining P09/P11 retargeting issue. The prior review record also says the status was restored to ready.

This is implementation-gate-relevant metadata, not merely editorial: an implementer following the header could correctly conclude that implementation is still prohibited, while another section says it is ready.

**Suggestion:** Change the header to a single current status, for example:

```text
Status: **ready to implement** — Round 3 P09/P11 consumer-retarget review folded
```

Retain the separate statement that this plan does not itself substitute for the later implementation Oracle gate.

### 2. P11 has a contradictory P04 dependency and non-goal

**File:** `docs/plans/P11-alternating-claim-2026-08-25.md`, header `Depends on`, `Explicit non-goals`, `Current-state analysis`, and W112

The plan’s latest stale-takeover contract requires P04 behavior:

- `release_stale` must append `run/claim_timeout`;
- zero base/max backoff must make the retry immediately claimable;
- takeover 1 must produce the attempt `1 → 2` timeout row;
- takeover 2 must produce the attempt `2 → 3` timeout row.

The plan’s W112 even lists `P04` as a dependency. However, the header still says P11 depends only on P09 and P10, and the explicit non-goals say P11 does not “rely on P04” or “retry” behavior. That is incompatible with the required seven-event final history. Without P04, the current P01 `release_stale` only requeues and increments the attempt; it does not append either timeout event.

**Suggestion:**

1. Change the header dependency to include P04, for example:

   ```text
   Depends on: P04, P09, and P10 (implemented)
   ```

2. Replace the contradictory non-goal with wording such as:

   ```text
   P11 does not test sleep_claim, default backoff, or dead-letter behavior.
   It does consume the full-tree P04 release_stale contract using a zero-delay
   fixture and verifies the resulting run/claim_timeout history.
   ```

3. State in the implementation order that P04 must be implemented and its relevant P04 suite must pass before the P11 test is run.

## Final Verdict

**NOT READY**

Open P1 items:

1. Update the stale contradictory P04 readiness status.
2. Make P11’s P04 dependency and non-goal consistent with its mandatory timeout-history assertions.