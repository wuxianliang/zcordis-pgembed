# Oracle Review



## Summary and Verdict

**Verdict: Not pass.** The round-three P1 is closed: registration now verifies that every slot resolves to an ordinary, scalar JSONB function with the slot’s required volatility, preventing successfully registered policies from exposing incompatible callable ABIs (`docs/plans/P19-paradigm-policies-2026-08-24.md:431-448`). The observation and higher-file test refinements are also directionally correct. However, the wrapper fold introduced a new implementation-blocking contradiction: `apply_observation_policy` must raise a specific SQLSTATE and message while remaining a `LANGUAGE sql` function, which has no `RAISE` facility. No P0 blockers were identified.

## P1 — Should Fix

1. **The observation wrapper cannot implement its specified error path as a `LANGUAGE sql` function.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:273-285`, `:497-505`

   The exact rule requires:

   > SQL NULL or non-object input must raise `22023 / invalid observation`.

   Component 3b simultaneously requires `cordis.apply_observation_policy` to be `LANGUAGE sql`. SQL-language functions cannot execute PL/pgSQL `RAISE ... USING ERRCODE`, and the plan defines no error helper. Deliberately provoking an unrelated built-in error would not reliably provide both the required SQLSTATE and stable message fragment. Consequently, W193 cannot implement the locked contract cleanly, and W195’s NULL-input assertion cannot pass as specified.

   **Suggestion:** Make `apply_observation_policy` `LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path TO pg_catalog` and explicitly validate `p_obs` before applying the four transformation steps:

   ```sql
   IF p_obs IS NULL
      OR pg_catalog.jsonb_typeof(p_obs) <> 'object' THEN
       RAISE EXCEPTION 'invalid observation'
           USING ERRCODE = '22023';
   END IF;
   ```

   Its external signature and volatility can remain unchanged. Alternatively, specify a dedicated raising helper and add it to the exact function inventory, but that adds unnecessary surface area.

## P2 — Consider

1. **The wrapper test does not cover the newly specified non-object rejection path.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:281-285`, `:685`

   W195 tests `{}` and SQL NULL. `{}` is still a JSON object; it covers the missing-`shown` normalization, not the non-object branch.

   **Suggestion:** Also assert that an array or scalar, such as `[]::jsonb`, raises `22023 / invalid observation`.

2. **Negative ABI tests cover only `fold_fn`, despite the validator contract applying independently to all three slots.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:431-448`, `:680`, `:701`

   The specification correctly requires `prokind`, `proretset`, return type, and volatility checks for fold, parse, and observe. W195’s custom invalid-function cases exercise only `fold_fn`; the signature test verifies the shipped stubs but would not catch an implementation that omitted equivalent registration checks for custom parsers or observers.

   **Suggestion:** Add at least one asymmetric case—for example, a `STABLE` custom parser expecting `invalid parse_fn`, and a set-returning observer expecting `invalid observe_fn`. This is a coverage improvement rather than a blocker because the validator algorithm itself is now explicit.