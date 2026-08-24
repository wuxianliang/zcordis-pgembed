# Oracle Review



## Verdict

**Not pass.** Round-two findings 1, 4, and 5 are closed: higher-numbered files safely own real slot bodies, validator-level CHECK duplication guarantees `22023`, and observation clipping is now generic rather than identity-driven. The built-in volatility correction is also sound. However, signature enforcement remains incomplete for arbitrary registered policies: checking only `to_regprocedure(...)` and `prorettype=jsonb` still admits set-returning or non-ordinary routines, and the validator does not enforce the locked slot volatilities. No P0 blockers were found.

### Round-Two Closure Status

| Round-two finding | Status |
|---|---|
| 1. `0019` overwrites lower-numbered real bodies | **Closed** |
| 2. Registration accepts uncallable/wrong-signature slots | **Partially closed; remaining P1 below** |
| 3. Fold incorrectly `IMMUTABLE` | **Closed for built-ins; arbitrary registrations remain unenforced** |
| 4. Validator relies on table CHECK SQLSTATE | **Closed** |
| 5. Clip policy disconnected from observer dispatch | **Closed**, with one P2 edge case |

## P1 — Should Fix

1. **The validator still does not enforce the complete callable slot ABI for arbitrary policy rows.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:265-271`, `:431-446`, `:480-503`

   Validator step 6 checks the argument-list lookup and `pg_proc.prorettype`, but that is insufficient to establish the locked contract:

   - `RETURNS SETOF jsonb` has `prorettype = jsonb`, so it passes despite producing zero or multiple rows where the driver expects one JSONB value.
   - A non-ordinary routine represented in `pg_proc`, such as a window function, can resolve through `regprocedure` and have a JSONB return type while not being callable as the plain `SELECT slot(argument)` shown in the dispatch contract.
   - An `IMMUTABLE` custom fold or `STABLE`/`VOLATILE` parse or observer passes registration even though the plan declares fold `STABLE` and parse/observe `IMMUTABLE`. The six seeded stubs are correct, but the open registration API does not preserve that ABI for a third policy.

   Consequently, a successfully registered live row can still fail or behave with incompatible cardinality/volatility in the generic driver.

   **Suggestion:** After resolving each OID, inspect `pg_proc` and require:

   - `prokind = 'f'`;
   - `proretset = false`;
   - `prorettype = 'jsonb'::regtype`;
   - the declared slot volatility (`'s'` for fold, `'i'` for parse/observe).

   Extend W195 with direct validator/register tests for a `RETURNS SETOF jsonb` function, a wrong-volatility function, and a wrong-return-type function. All should raise `22023` with the appropriate `invalid *_fn` fragment.

## P2 — Consider

1. **The observation-wrapper pseudocode does not implement its stated missing-key behavior.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:273-286`

   The rule says a missing `shown` key becomes empty text, but `p_obs->>'shown'` actually returns SQL `NULL`. That propagates through `left(...)` and `to_jsonb(...)`, producing JSON nulls rather than the promised empty string. SQL-null or non-object `p_obs` is likewise undefined.

   **Suggestion:** Specify `shown0 := COALESCE(p_obs->>'shown', '')` explicitly and decide whether SQL-null/non-object observer output is rejected or normalized. Add one wrapper test with `{}`.

2. **The clipping test depends on a `probe.alias` row that another named test removes.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:674`, `:680`

   `test_p19_third_policy_independent_clip` unregisters `probe.alias`, while `test_p19_observation_wrapper_clips_without_identity_branch` later assumes it exists. With per-test resets it never exists in the latter test; with shared state it was already deleted.

   **Suggestion:** Have the observation-wrapper test register and unregister its own `probe.alias`, or test the generic wrapper directly with independently supplied clip values. Do not rely on pytest ordering or another test’s database state.

3. **The proposed `0020` sentinel function does not follow the SQL tree’s pinned-`search_path` rule.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:681`; `sql/README.md:24-35`

   The test replacement uses unqualified `jsonb_build_object` and omits `SET search_path TO pg_catalog`. Although it is a temporary test tree, it is meant to demonstrate the shape of a legitimate later numbered implementation file.

   **Suggestion:** Declare it with `SECURITY INVOKER SET search_path TO pg_catalog` and call `pg_catalog.jsonb_build_object(...)`, so the ownership proof also conforms to the numbered-SQL contract.