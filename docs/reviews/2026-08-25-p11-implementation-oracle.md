# P11 implementation Oracle review

Date: 2026-08-25  
Oracle export (round 1): `prompt-exports/oracle-review-2026-08-25-232826-untitled-chat-8ad4a1-3122.md`  
Chat: `untitled-chat-8AD4A1`  
Plan: `docs/plans/P11-alternating-claim-2026-08-25.md`  
Plan critique: `docs/reviews/2026-08-25-p11-plan-critique.md`  
Diff snapshot: `_git_data/repos/zcordis-pgembed-b17cbc32/2026-08-25/2326`

## Round 1

**Verdict: ready.** P0 none, P1 none, P2 none. First-round pass. Recording this note does not reopen the review.

Oracle summary: the staged ship set is the planned tests-only proof. One P09-enqueued job is advanced in-db → host → in-db on the same `job_id`; the host appends the locked P08-scoped `run/yield` event with `step_name=NULL`; stale leases are taken over in both directions with targeted claims. The test checks token freshness and fencing, attempt `1 → 2 → 3`, five-event log order, live `claimed_by` flips, and the final one-row `PENDING` invariant. No SQL, marker, host-client, shared-fixture, dependency, plugin, or runtime API change.

### P0 / blockers

None.

### P1 / should-fix

None.

### P2 / nits

None.

## Tests run before review

```text
uv run pytest tests/test_p11_*.py -q
# 1 passed

uv run pytest \
  tests/test_p00_sql_source.py \
  tests/test_p01_claim.py \
  tests/test_p02_agent_steps.py \
  tests/test_p03_wait_event.py \
  tests/test_p05_one_step_driver.py \
  tests/test_p06_plugin_catalog.py \
  tests/test_p07_grant_registry.py \
  tests/test_p08_four_seam_enforcement.py \
  tests/test_p19_paradigm_policies.py \
  tests/test_p09_in_db_worker.py \
  tests/test_p10_host_sql_seam.py \
  tests/test_p11_alternating_claim.py -q
# 212 passed

PGCORDIS_PGDATA="$PWD/.pgdata" uv run pytest -q
# 212 passed
```
