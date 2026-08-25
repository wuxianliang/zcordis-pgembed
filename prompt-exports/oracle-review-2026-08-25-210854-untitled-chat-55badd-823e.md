# Oracle Review



The change adds the planned P09 scheduler layer: a catalog-validated enqueue API, one-claim/one-handler `worker_step`, claim-bound read-only in-database tool dispatch through P08, direct catalog registration of the existing legacy `step_once`, the `p21` marker, documentation, and broad acceptance/regression tests. The normal `kernel.step_once` path correctly yields, reclaims, and completes without adding a second queue or changing historical SQL. However, the implementation does not consistently preserve the exact catalog identity and function OID it validates, leaving correctness gaps for overloaded entrypoints and concurrent catalog refreshes. **Verdict: not yet a pass because of the P1 findings below.**

## P1 — Should fix

- **`sql/0021_p09_in_db_worker.sql` — `worker_step` and `invoke_in_db_tool` discard the exact validated entrypoint before invocation.**  
  Both paths validate a specific `regprocedure`/`pg_proc` OID, but then reduce it to only `(namespace, proname)` and execute `schema.name($1, ...)`. This is weaker than the deep plan’s requirement to execute the validated exact entrypoint. An allowed sibling overload with default parameters—for example, a validated `fn(text, uuid, integer)` alongside `fn(text, uuid, integer, text DEFAULT NULL)`—can make the dynamic call ambiguous even though the resolver accepted the registered handler. The same issue exists for a tool alongside `fn(jsonb, text DEFAULT NULL)`. A handler can therefore pass admission but make every worker invocation roll back with an overload-resolution error.  
  **Suggestion:** extend ABI validation to reject competing same-schema/same-name overloads callable with the P09 argument list, or introduce an invocation mechanism that can prove it resolves back to the validated OID. Add queue and tool tests containing default-compatible sibling overloads.

- **`sql/0021_p09_in_db_worker.sql` — `enqueue_job` reverse-resolves the identity from `entrypoint` instead of preserving the validated requested identity.**  
  After `_resolve_in_db_queue_handler(p_job_type)` validates the normalized identity, enqueue runs:
  ```sql
  SELECT c.identity INTO STRICT v_job_type
    FROM cordis.plugin_catalog AS c
   WHERE c.entrypoint = v_handler;
  ```
  This introduces an unnecessary second catalog lookup and changes the contract from “store the normalized requested handler identity” to “store whichever current catalog row points to this OID.” Because `enqueue_job` is volatile, a concurrent `refresh_plugins()` can relabel or remove the entry between those reads, causing an unexpected `NO_DATA_FOUND`/`TOO_MANY_ROWS` path or silently storing a different identity. The plan specifies that later drift should be revalidated by `worker_step`, not silently rebound during enqueue.  
  **Suggestion:** after the resolver succeeds, assign `v_job_type := pg_catalog.btrim(p_job_type)`, or change the resolver to return both normalized identity and entrypoint from one lookup. If the catalog changes afterward, the queued original identity can correctly fail closed during worker revalidation.

## P2 — Consider

- **`tests/test_p09_in_db_worker.py` — several explicit W90/W92 negative cases are not covered.**  
  The plan requires resolver rejection of set-returning and non-`VOLATILE` queue handlers, plus tool rejection of incompatible SQL ABIs and external classifications and propagation of entrypoint exceptions. The current suite covers wrong arguments, `SECURITY DEFINER`, unpinned paths, host/queue/transactional rows, and SQL NULL results, but not those remaining cases.  
  **Suggestion:** add fixtures for:
  - a set-returning queue handler;
  - a `STABLE` queue handler;
  - a tool with the wrong argument or return type;
  - an external in-db `session_select` entry;
  - a valid read-only tool that raises a known SQLSTATE.

- **`tests/test_p09_in_db_worker.py` — the replay test does not prove all behavior promised by its name and the deep plan.**  
  `test_p09_replay_preserves_jobs_logs_runtime_catalog_and_policies` preserves a job, logs, and a host definition, but it neither registers a runtime paradigm-policy override nor perturbs the canonical `step_once` COMMENT before replay. Consequently, it does not prove that runtime policy upserts survive or that replay restores the canonical COMMENT metadata.  
  **Suggestion:** register a custom/runtime policy and assert it is unchanged after replay; replace or clear the `step_once` COMMENT/catalog row before replay and verify that apply restores the exact canonical metadata.

- **`tests/test_p09_in_db_worker.py` — the “at most one ready job” assertion does not directly prove that only one job advanced.**  
  After a successful P05 step, the selected job yields back to `PENDING`, so asserting that both jobs are `PENDING` cannot distinguish correct one-job processing from accidental processing of both. The returned row identifies the high-priority job, but the test does not assert that the low-priority job has no log events.  
  **Suggestion:** assert that the high-priority run has exactly its first-step log rows while the low-priority run has zero `agent_steps`.

- **`docs/reviews/2026-08-25-p09-plan-critique.md` — the checked-in verdict still says the plan is not ready.**  
  The deep plan states that the critique’s P1 and P2 findings were folded and marks itself ready, while the critique’s final section still says “尚未 ready to implement.” That historical verdict is understandable, but the two newly added documents appear contradictory to readers or process automation.  
  **Suggestion:** append a dated resolution note to the critique stating that finding 1 and the recommended P2 edits were subsequently folded into the deep plan, without rewriting the original review history.