# P09 implementation Oracle review

Date: 2026-08-25  
Plan: `docs/plans/P09-in-db-worker-2026-08-25.md`  
Plan critique: `docs/reviews/2026-08-25-p09-plan-critique.md`

## Oracle exports

- Round 1 (new chat, not a pass): `prompt-exports/oracle-review-2026-08-25-210854-untitled-chat-55badd-823e.md`
- Round 2 (same chat `untitled-chat-55BADD`, pass): `prompt-exports/oracle-review-2026-08-25-211738-untitled-chat-55badd-ac53.md`

## Verdict

**Pass.** Round 2 has no P0 and no unfixed P1.

## Round 1 findings (closed)

| Severity | Finding | Resolution |
|---|---|---|
| P1 | `worker_step` / `invoke_in_db_tool` reduced the validated entrypoint to `(namespace, proname)`, so a default-arg sibling overload could make the dynamic call ambiguous | Reject any same-schema/same-name sibling `pg_proc` row before invoke; tests cover default-arg overloads for queue and tool |
| P1 | `enqueue_job` reverse-looked up identity from `entrypoint` after resolve | Store `btrim(p_job_type)` after a successful resolver call |
| P2 | Missing negative fixtures (set-returning, STABLE, external tool, raising tool) | Added |
| P2 | Replay test did not restore COMMENT or keep a runtime policy | Replay now clears the `step_once` COMMENT then asserts restore plus `p09.runtime` |
| P2 | At-most-one-job did not prove the unselected run was idle | Assert low-priority run has zero `agent_steps` |
| P2 | Plan critique still said not ready | Dated resolution note appended |

## Round 2 leftover P2 (not blocking)

- Source-boundary `worker_step` check uses `startswith("000")`, so it would not fail if `0019`/`0020` gained the name. Current historical files do not contain it.
- Malformed-WAITING `P09_WAIT_STATE_INVALID` rollback path is specified in the plan but not given its own fixture.
- Enqueue of a *known* unsupported handler (registered host / session-select) is covered at the resolver, not also through `enqueue_job`.

These were left unfixed so the passing review is not invalidated by a further test-only change.

## Tests run before round 2

```text
uv run pytest tests/test_p09_in_db_worker.py -q
# 21 passed

uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py \
  tests/test_p02_agent_steps.py tests/test_p03_wait_event.py \
  tests/test_p05_one_step_driver.py tests/test_p06_plugin_catalog.py \
  tests/test_p07_grant_registry.py tests/test_p08_four_seam_enforcement.py \
  tests/test_p19_paradigm_policies.py tests/test_p09_in_db_worker.py -q
# 193 passed (before P1 SQL/test follow-up)

uv run pytest -q
# 193 passed (same tree, before P1 follow-up)
```

After the P1 SQL/test follow-up: `tests/test_p09_in_db_worker.py` 21 passed.
