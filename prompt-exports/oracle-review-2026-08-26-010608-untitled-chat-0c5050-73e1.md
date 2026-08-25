# Oracle Review



## Summary

The revised P04 plan fully closes the previous replay-validation and PostgreSQL floating-point P1 findings: canonical defaults and CHECK expressions are pinned, incompatible deadline indexes are rejected rather than repaired, and strict infinity bounds correctly reject `NaN` and infinities. The exact prewritten-error stale payload and P05 supersession note also close both prior P2 suggestions. One P1 remains in current-tree integration: the plan changes stale recovery to always append `run/claim_timeout`, but its prescribed P11 retarget only sets zero backoff and does not update P11’s exact five-event assertions; the P09 exact source-tree assertion is likewise omitted from the concrete retargeting instructions.

## Prior Finding Closure

| Prior finding | Status | Assessment |
|---|---|---|
| **P1.1 — Timeout sweeper deadlock** | **Fully closed** | Deadline-first selection and event-key processing remain consistently specified, with the differing-snapshot regression retained. |
| **P1.2 — Canonical replay comparison** | **Fully closed** | The plan now pins exact default and CHECK expressions and gives `run_waits_deadline_idx` one unambiguous create-or-validate-and-raise policy. |
| **P1.3 — Obsolete p06 baseline** | **Fully closed** | P04-only remains `p04`; the product tree remains `p21` with `0004` inserted before `0005`. |
| **P1.4 — Prewritten errors becoming retryable** | **Fully closed** | `fail_claim` and stale recovery consistently treat the latest committed `error` event as a terminality fence without changing `0021`. |
| **P1.5 — P09/P10/P11 consumer integration** | **Not fully closed** | Retry defaults, P09 terminal failures, P10 sleep presence, and P11 zero backoff are covered, but P11’s new timeout history and P09’s exact file list are not retargeted. |
| **P2.1 — Floating-point overflow coverage** | **Fully closed** | The adversarial finite-result/intermediate-overflow case, saturation, non-finite values, and large attempts remain named requirements. |

The two P1 findings and both P2 suggestions from the latest re-review are otherwise fully closed.

## P1 — Should Fix

### Current-tree consumer retargeting does not account for all observable P04 changes

**Files:**

- `docs/plans/P04-sleep-retry-2026-08-24.md` — W40, Component 9, File-by-file impact, and Existing assertion change/stay matrix
- `docs/plans/P11-alternating-claim-2026-08-25.md` — stale-takeover and final log invariants
- `tests/test_p11_alternating_claim.py` — exact `_kind_names(...) == expected_log` assertions
- `tests/test_p09_in_db_worker.py` — `TREE_FILES`

P04 specifies that **every** processed stale claim appends one `run/claim_timeout`, including zero-delay retries. Setting P11’s base and cap to zero preserves immediate takeover, but it does not preserve P11’s existing five-row log contract. The current P11 test asserts after each takeover—and again at completion—that the log still contains only:

```text
llm/s-1
tool/s-1
run/yield/NULL
llm/s-2
tool/s-2
```

Under P04, the first stale takeover adds a retry `run/claim_timeout` for attempt `1 → 2`, and the reverse takeover adds another for `2 → 3`. Therefore the required P11 regression command will fail even if the implementation follows the current P04 instructions exactly. The P11 deep plan also explicitly says stale release adds no log event, which becomes superseded guidance.

Separately, `tests/test_p09_in_db_worker.py::TREE_FILES` pins the complete source list without `0004`. W40 generically mentions current-tree file lists, but the concrete P09 file-impact and verification sections only require asserting retry defaults. The P09 fresh-apply test will therefore fail unless this assertion is explicitly retargeted.

**Concrete suggestion:**

1. Extend the P11 instructions to require:
   - zero base/max backoff;
   - one exact retry `run/claim_timeout` after the host-to-in-db takeover with `failed_attempt=1`, `next_attempt=2`, and `delay_seconds=0`;
   - a second after the in-db-to-host takeover with `failed_attempt=2`, `next_attempt=3`, and `delay_seconds=0`;
   - no `run/sleep` or timer `run/wake`, because zero delay transitions through `PENDING`;
   - updated intermediate and final log-order assertions.
2. Add a dated P04 supersession note to the P11 plan, analogous to the P05 note, replacing its “stale release adds no history” assumption.
3. Explicitly require `tests/test_p09_in_db_worker.py::TREE_FILES` to include `0004_p04_sleep_retry.sql` between `0003` and `0005`.
4. Reflect both changes in W40, File-by-file impact, and the assertion matrix so the implementation instructions and required commands agree.

## Final Verdict

**NOT READY**

Open P1:

1. Complete the P09/P11 consumer retargeting for P04’s inserted source file and mandatory stale-timeout history.