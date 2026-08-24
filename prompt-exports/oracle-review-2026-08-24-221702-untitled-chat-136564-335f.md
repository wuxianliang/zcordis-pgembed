# Oracle Review

## Summary and Verdict

**Verdict: Pass.** The round-four P1 is closed. `cordis.apply_observation_policy(jsonb, integer, boolean)` is now explicitly a `LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER` function, so it can implement the required `RAISE EXCEPTION 'invalid observation' USING ERRCODE = '22023'` path while retaining the locked signature and volatility (`docs/plans/P19-paradigm-policies-2026-08-24.md:273-285`, `:497-505`). W195 now covers SQL NULL and non-object input, asymmetric parser/observer ABI failures, and the wrapper’s `plpgsql` language contract (`docs/plans/P19-paradigm-policies-2026-08-24.md:674-701`). The fold introduces no new P0 or P1 issue, and no remaining P2 finding is identified within the requested scope.