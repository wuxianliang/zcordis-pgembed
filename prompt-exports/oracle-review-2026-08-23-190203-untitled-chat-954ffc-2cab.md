# Oracle Review



## Summary

P02 adds the planned `cordis.agent_steps` append-only log, named-step and LLM-checkpoint projections, claim-aware single/batch append APIs, `run_state()`, the `p02` version marker, documentation, and broad integration coverage for standalone P02 and combined P01/P02 trees. The implementation satisfies most of the parent done-when, including three-step folding, crash-shaped continuation, absence of an independent checkpoint table, and preservation of the log as the projection source. **Verdict: not yet a pass**, because two open P1 correctness issues remain around validation precedence and sparse step-name generation.

## P1 — Should fix

- **`sql/0002_p02_log.sql` — `cordis.emit_step_claimed` and `cordis.checkpoint`: malformed events can be silently reported as lost claims.**  
  The deep plan requires parameter and event-shape errors to raise before any null/unknown/expired-token path returns `false`. The implementation validates duration, run ID, payload presence, and basic checkpoint-envelope keys, but it does not validate the allowed `kind`, required `step_name` for `llm`/`tool`, step-name format, or JSON field types until `emit_step` is called after a successful fence. Consequently:
  - `emit_step_claimed(NULL, 'r', 'nope', '{}'::jsonb, NULL)` returns `false` instead of raising for the unknown kind.
  - A checkpoint containing `{"kind":"llm"}` without `step_name` returns `false` when its token is unknown, rather than raising for a malformed event.
  - Non-string JSON values for `run_id`, `kind`, or `step_name` are coerced through `->>` instead of being rejected as malformed envelope fields.

  This conflates caller bugs with ownership loss, which can cause workers to abandon or retry work for the wrong reason. Validate all event invariants before the null-token check or jobs update: require string `run_id`/`kind`, require a string-or-null `step_name`, enforce the exact kind set and `s-N` format, and require a step name for `llm`/`tool`. Add tests combining malformed arguments with null, random, expired, and cleared tokens, asserting an exception with no log or lease mutation.

- **`sql/0002_p02_log.sql` — `cordis.next_step_name`: completed sparse histories produce incorrect or colliding names.**  
  Once the latest LLM is complete, the function returns `s-(1 + count(completed LLM rows))`. This contradicts the deep plan’s explicit sparse-history behavior: `llm(s-5)` followed by `tool(s-5)` should produce `s-6`, but the implementation returns `s-2`. More seriously, completed `s-1` and `s-3` rows produce `s-3`, which already exists and will fail the unique LLM checkpoint index when the caller tries to append the purported next step. Sparse histories are accepted by the table and public `emit_step` API, so this is reachable valid database state rather than impossible corruption.

  Keep the trailing-incomplete override, but after a completed latest LLM derive the next number from the greatest existing numeric `s-N` suffix—or otherwise implement the plan’s specified `s-5 → s-6` behavior—instead of counting rows. Add tests for completed sparse and out-of-order names and assert that the returned name cannot collide with an existing LLM checkpoint.

## P2 — Consider

- **`sql/0002_p02_log.sql` — `cordis.checkpoint`: array-order preservation is implicit rather than contractual.**  
  The plan requires events to be appended in JSON array order, but both loops use `ARRAY(SELECT jsonb_array_elements(p_events))` without ordinality or an explicit ordering clause. PostgreSQL’s current function scan normally emits array elements in order, but an unordered subquery does not clearly encode the durable-log ordering guarantee. Iterate with `jsonb_array_elements(...) WITH ORDINALITY ORDER BY ordinal`, and add a test asserting that distinguishable batch events receive ascending `seq` values in the submitted order.

- **`tests/test_p02_agent_steps.py:test_p02_fresh_apply_catalog_and_version` — the exact catalog contract is only partially locked.**  
  The deep plan calls for assertions that `seq` has a `nextval(...)` default, `created_at` uses the wall-clock default, the four named checks contain the specified predicates, and the kind check contains exactly twelve values. The test currently checks column shape and constraint names, then behavior for the twelve expected kinds and one unknown kind; it would not catch an extra allowed kind, a weakened predicate, or replacement of `clock_timestamp()` with another default. Query `pg_get_expr` and `pg_get_constraintdef` to assert these definitions directly.

- **`docs/plans/P02-agent-steps-log-2026-08-23.md` — the P01 composition diagram states behavior that is explicitly deferred elsewhere.**  
  Component 7 shows `complete`/`fail`/stale transitions flowing through `emit_step`, while the P01 interaction and risk sections correctly say those verbs remain jobs-only and the log wiring is deferred to a later numbered file. Mark the diagram as a future integration flow or show the current gap explicitly so the implementation plan does not describe two incompatible current states.