# Oracle Review



## Summary

P02 now delivers the planned append-only `cordis.agent_steps` log, claim-aware single and batch append paths, named-step and LLM-checkpoint projections, `run_state()`, replay-safe versioning, and standalone/full-tree integration coverage. The two prior P1 findings are substantively fixed: malformed events are validated before lost-claim returns, and sparse completed histories advance from the greatest existing `s-N` suffix; checkpoint ordering and the requested catalog assertions were also improved. However, the sparse-name implementation introduces one reachable numeric-overflow edge for step names that satisfy the plan’s unbounded `s-N` constraint. **Verdict: not yet a pass because one P1 remains; no P0 findings.**

## P1 — Should fix

- **`sql/0002_p02_log.sql` — `cordis.next_step_name` rejects valid large `s-N` names through an `integer` cast.**  
  The table accepts any name matching `^s-[1-9][0-9]*$`, but the completed-history branch evaluates `substring(step_name from 3)::integer` and stores the result in an `integer`. A valid sparse history can therefore fail with `integer out of range` after only two events:

  ```sql
  SELECT cordis.emit_step('large-step', 'llm', '{}'::jsonb, 's-2147483648');
  SELECT cordis.emit_step('large-step', 'tool', '{}'::jsonb, 's-2147483648');
  SELECT cordis.next_step_name('large-step'); -- integer out of range
  ```

  `s-2147483647` also fails when adding one. This is reachable schema-valid state through the public writer, not a row-count-scale concern. Cast the suffix to `numeric` and store the maximum in a `numeric` variable before adding one, or implement arbitrary-length decimal increment while retaining the exact unbounded regex contract. Add boundary tests above the 32-bit range.

## P2 — Consider

- **`docs/plans/P02-agent-steps-log-2026-08-23.md` — the normative step-name formula still contradicts the implemented sparse-history rule.**  
  Component 5 still defines the completed branch as `1 + COUNT(completed llm rows)`, while the same section says `llm(s-5) + tool(s-5)` must yield `s-6`. The implementation now correctly follows the latter rule by using the greatest numeric suffix. Replace the count-based “nominal rule” and algorithm step 4 with “greatest existing LLM `s-N` suffix plus one,” leaving the trailing-incomplete override intact.

- **`tests/test_p02_agent_steps.py:test_p02_fresh_apply_catalog_and_version` — the CHECK-definition assertions remain substring-based rather than exact.**  
  The test now queries `pg_get_constraintdef`, but it combines all definitions and checks only that the twelve expected kind strings and the step-name regex appear. It does not verify the run-ID or step-name-presence predicates directly, and an accidental thirteenth allowed kind would still pass. Build a `conname → definition` mapping, assert the required predicates against their corresponding named constraints, and compare the kind constraint’s extracted values exactly with `KINDS`.