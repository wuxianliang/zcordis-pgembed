# Oracle Review



## Summary and Verdict

**Verdict: Not pass.** The revision closes round-one P1s 2–5: the exact two-bundle constraint is gone, `spawn_mode` now consistently represents D9 explicit-child admission, replay no longer overwrites runtime seed updates, and `metadata` has one unambiguous meaning. The separate `cordis.paradigm_policies` table remains the correct split from P06, and omitting `rlm_vars` and run-level paradigm storage remains appropriate P19 scope. The dispatch direction is much stronger, but P1.1 is not closed end-to-end: numeric SQL ordering lets `0019` overwrite P05’s real functions with stubs, arbitrary registrations are not checked against the locked signatures, and the proposed fold volatility is incompatible with a log-reading projection. There are no P0 blockers.

### Round-One Closure Status

| Round-one finding | Status |
|---|---|
| P1.1 — callable dispatch ABI | **Partially closed; remaining P1s below** |
| P1.2 — exact A∨B bundle CHECK | **Closed** |
| P1.3 — CodeAct `spawn_mode='none'` | **Closed** |
| P1.4 — seed replay overwrites updates | **Closed** |
| P1.5 — contradictory `metadata` meaning | **Closed** |

## P1 — Should Fix

1. **`0019` will overwrite P05’s real slot implementations with the P19 stubs.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:321-336`, `:463-467`, `:678-689`

   The plan explicitly allows `0005` to exist before `0019`, then has `0019` unconditionally `CREATE OR REPLACE` the six final function names with stub bodies. Numeric application order is always `0005` followed by `0019`, regardless of which Git change lands first. Therefore a full apply or replay after P05 exists will replace P05’s real folds/parsers/observers with `p19_stub` implementations.

   This makes the proposed “whichever lands second” handoff incorrect: Git landing order does not override numbered SQL order.

   **Suggestion:** Choose an ordering-safe ownership model. For example:

   - have `0019` create a stub only when the exact signature does not already exist, so a real implementation from `0005` wins; or
   - place the real replacements in a numbered integration file greater than `0019`; or
   - let P19 own permanent wrappers while P05 supplies differently named implementation functions behind them.

   Add an integration test with real/sentinel slot bodies in a lower-numbered file and verify that applying/replaying `0019` does not replace them.

2. **The registration API still accepts uncallable policies, and the planned signature check uses an invalid `regprocedure` spelling.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:375-395`, `:401-416`, `:543`, `:644`

   The table checks only the lexical form `cordis.<name>`, and the validator explicitly does not resolve the function. A runtime registration can therefore become immediately selectable while naming:

   - a nonexistent function;
   - a function with the wrong argument type;
   - or a function with a non-JSONB result.

   The locked signatures then exist only in prose and for the six built-ins, rather than being enforced for policy rows generally.

   In addition, `to_regprocedure(fold_fn)` cannot resolve a stored value such as `cordis.fold_codeact_messages`; `regprocedure` resolution requires the argument list, such as `cordis.fold_codeact_messages(text)`. The W195 assertion will therefore return null or fail rather than proving the ABI.

   **Suggestion:** Resolve the exact signatures during registration or lookup and raise `22023` for missing/mismatched slots:

   - `fold_fn || '(text)'`
   - `parse_fn || '(text)'`
   - `observe_fn || '(jsonb)'`

   Also verify `prorettype = 'jsonb'::regtype`. If forward registration must remain possible, introduce an explicit inactive/unresolved state rather than allowing an uncallable row to be selected as a live policy.

3. **`IMMUTABLE` is the wrong locked volatility for the fold slots.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:257-274`, `:450-467`, `:645`

   `fold_fn(p_run_id)` is defined as the prompt-fold projection and will read the changing `cordis.agent_steps` history. Marking it `IMMUTABLE` tells PostgreSQL that its result never changes for a given `run_id`, permitting constant folding or stale reuse that is invalid once new log rows are appended. The plan also says P05 may replace only the bodies, while W195 locks all six functions to `provolatile='i'`, making it unclear whether P05 may correct this attribute.

   **Suggestion:** Define the two fold functions as `STABLE` from P19 onward. `parse_fn` and `observe_fn` can remain `IMMUTABLE` if their real implementations depend only on their arguments. Update the volatility table and W195 assertions accordingly, and clarify that P05 must retain those volatility contracts.

4. **The validator algorithm does not specify enforcement of the table-level enums and cross-field rules required to produce SQLSTATE `22023`.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:43-48`, `:375-414`, `:640`

   W191 requires `_validate_paradigm_policy` itself to reject bad enums, illegal env combinations, and synchronous spawn with `22023`. However, validator step 5 says only to enforce the “validator-only” rules. If implemented literally:

   - a direct validator call can return an invalid normalized row; and
   - `register_paradigm_policy` reaches a table CHECK and fails with `23514`, not the promised `22023`.

   **Suggestion:** State explicitly that the validator duplicates every enum, function-name, clip, env, and spawn invariant before returning, with table CHECKs serving only as defense in depth. Add direct `_validate_paradigm_policy(...)` assertions for illegal `spawn_mode`, illegal env combinations, and unknown enum values, all expecting `22023`.

5. **The independent observation fields are stored but are not connected to the locked observation ABI.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:253-285`, `:363-368`, `:639`, `:680-685`

   The plan claims `observation_clip_chars` is independently configurable, but `observe_fn` receives only `p_raw`; the dispatch sketch neither passes the clip/full-env settings to it nor says that the shared driver applies those settings generically. The third-policy test merely verifies that `clip=1000` was stored while reusing `observe_codeact`; it does not prove that the resulting observation is actually clipped to 1000.

   This leaves P05 with an unresolved ownership choice: hard-code clipping inside each observer, ignore the row, or add generic driver logic not currently specified.

   **Suggestion:** Lock one generic rule without branching on identity. Either:

   - pass normalized observation policy into the observer through a common signature; or
   - state that the shared driver applies `observation_clip_chars` and `observation_full_in_env` generically around `observe_fn`, and define the order.

   The downstream integration test should reuse one observer under two clip values and verify different shown-output lengths. This remains data-driven and does not require `CASE identity`.

## P2 — Consider

1. **Several stale statements still contradict the new stub design.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:188-207`, `:321-342`, `:463-467`, `:568-570`

   The plan variously says:

   - the apply path calls `register(codeact), register(rlm)`, although seeds now use validated `INSERT … ON CONFLICT DO NOTHING`;
   - not to copy stub fold/parser bodies;
   - the slot functions “need not exist in P19”;
   - and that the README should describe them as forward names that P05 creates.

   Those statements conflict with W193 and Component 3b, which require P19 to create six executable stubs.

   **Suggestion:** Remove the stale no-stub/forward-only language and update the data-flow sketch to show the actual validated seed inserts. Resolve the ordering issue above first, then describe the selected stub ownership model consistently.

2. **One README citation remains stale despite the round-one note saying it was corrected.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:562`; current `sql/README.md:39-46`

   The landing-state citation was updated to `:39-46`, but Component 5 still cites `:39-44`, which omits the current `0006 → p06` line.

   **Suggestion:** Change the remaining citation to `sql/README.md:39-46`.