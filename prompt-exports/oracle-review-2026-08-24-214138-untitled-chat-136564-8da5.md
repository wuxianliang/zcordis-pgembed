# Oracle Review



## Summary and Verdict

**Verdict: Not pass.** The draft correctly keeps P19 declarative: `cordis.paradigm_policies` is a defensible separation from P06’s executable tool catalog, and does not violate D8; forcing policies into `plugin_catalog` would require fake locus/effect/retry semantics. It is also appropriate for P19 to omit `rlm_vars`, `jobs.paradigm`, the one-step driver, and the fold/parser implementations. The proposed identities and RLM’s `always_enqueue` behavior align with D9. However, the plan still has several P1 design/specification gaps: it does not establish a callable policy-dispatch ABI, its exact bundle constraint largely hard-codes the two current behavior shapes, CodeAct’s `spawn_mode='none'` conflates ordinary tools with explicit child spawning, and replay ownership of seeded policies conflicts with the claimed P05/P13 update path. No P0 blockers were identified.

## P1 — Should Fix

1. **The plan does not define a callable dispatch ABI, so it does not yet guarantee that P05 can avoid paradigm-specific branching.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:221`, `:312-316`, `:390`, `:415`, `:626-629`  
   The policy stores `fold_fn`, `parse_fn`, and `observe_fn` as untyped text, deliberately permits them not to exist, and leaves their signatures to P05. The handoff then allows P05 either to branch on `action_surface`/`parser_kind` or dynamically execute the names. That leaves two unresolved contracts:
   - whether the function names are authoritative or merely descriptive alongside the strategy enums;
   - what common arguments and return shape allow CodeAct and RLM functions to be invoked through one generic loop path.

   Without a common callable contract, CodeAct and RLM parsers can naturally acquire incompatible return types and force P05 to recover with identity- or parser-specific branches. The lookup test at `:583` proves row selection, but not that a driver can consume the selected row generically.

   **Suggestion:** Decide one dispatch mechanism in P19:
   - define stable shared signatures and JSONB/composite input/output contracts for all three function slots, while still leaving their bodies to P05; or
   - remove the function slots and define the closed strategy-enum interpretation that P05 must implement.

   Also clarify the P05/P19 sequencing: P19 is declared parallel with P05 at `:6-7`, but `:628` assigns required policy function bodies to P05. Add an explicit integration acceptance test to whichever plan lands second, rather than treating a bare `paradigm_policy()` lookup as the complete skeleton done-when.

2. **The exact two-bundle CHECK moves the two-paradigm branch into the schema and makes most “policy fields” non-configurable.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:220`, `:234-262`, `:640`  
   This does avoid `CASE identity`, so it is compatible with the narrow literal reading of “no identity if-else.” However, the exact disjunction fixes parser, spawn, environment, inheritance, clipping, and full-observation behavior into only two legal tuples. A third registration can change prompts and function names, but cannot, for example:
   - use structured tools with clipping;
   - use a run workspace without RLM’s exact inheritance policy;
   - use an RLM-like surface with a different observation policy.

   Thus the plan’s third-policy proof demonstrates aliases of the two existing bundles, not genuinely data-driven policy composition. Any variation in fields that the skeleton explicitly asks P19 to decide requires another DDL migration.

   **Suggestion:** Replace the exact A-or-B disjunction with narrower cross-field invariants—for example, consistency between `env_enabled`, `env_workspace`, and `env_inherit`, and a prohibition on synchronous spawn—while allowing independent policy dimensions where the kernel already has generic behavior. If exactly two behavior kinds are intentionally frozen for v0, represent that honestly as a closed `policy_kind`/`action_surface` contract and avoid claiming that the individual columns provide broader composability.

3. **`spawn_mode='none'` for CodeAct conflates “ordinary tools are not spawn” with “CodeAct cannot explicitly spawn a child.”**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:224`, `:238-260`, `:453`, `:478`  
   D9 says every operation that *is* a spawn must enqueue, while ordinary tools within a CodeAct step are not spawn. It does not say CodeAct can never request an explicit child run. The draft justifies CodeAct’s `none` value by saying its in-step tools are not child runs, but those are separate questions. This may block the primary CodeAct coding agent from requesting the asynchronous Context Builder child required by P17/P18.

   RLM’s `always_enqueue` value is aligned with D9; the issue is the meaning assigned to CodeAct’s `none`.

   **Suggestion:** Make explicit child admission orthogonal to ordinary structured-tool execution. For example:
   - define `spawn_mode` as the behavior of an explicit spawn action and use `always_enqueue` for every paradigm that supports one; or
   - rename the current field to something RLM-specific such as `implicit_child_call_mode`, while documenting that the kernel’s explicit spawn capability is separately available to CodeAct.

   Add a downstream acceptance statement showing how a CodeAct parent requests an enqueued Context Builder without turning ordinary tool calls into spawn.

4. **Seed replay semantics conflict with the proposed P05/P13 policy-update path and numeric file ordering.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:440-442`, `:587`, `:637-642`  
   P19 deliberately re-upserts the exact seeds on every in-place apply, and W195 tests that replay restores them. The risk section nevertheless says P05/P13 may upsert richer `system_prompt` values. Those plans normally occupy lower-numbered files (`0005`/`0013`), so on a fresh or repeated full apply:
   - their SQL executes before `0019`, when the P19 registry may not yet exist;
   - even if an update happened at runtime, replaying `0019` overwrites it with the seed again.

   The current plan therefore leaves policy source ownership ambiguous: the table is called durable authoring state, but P19’s numbered SQL remains the effective authority for the two seed identities.

   **Suggestion:** State that changes to seeded CodeAct/RLM policy data must be introduced by a numbered file greater than `0019`, or adopt seed semantics that preserve later/runtime customization. Do not assign persistent seed updates to lower-numbered P05/P13 files unless the apply ordering and replay behavior are redesigned and tested.

5. **The `metadata` representation is internally contradictory and blocks a deterministic W191 implementation.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:288-292`, `:343`, `:377-386`  
   The envelope section says "`metadata` default `{}`" while also saying unknown keys are retained in metadata “together with the original object.” The table definition describes `metadata` as the original envelope, including unknown keys. These imply different implementations:
   - `metadata = p_definition`;
   - `metadata = cordis_paradigm.metadata`;
   - or a synthesized object merging the optional metadata field and unknown keys.

   They also produce different replay and equality behavior.

   **Suggestion:** Specify one exact rule, preferably mirroring P06: `metadata` stores the complete original `p_definition`; if an optional user metadata object is wanted, give it a separate normalized column or clearly state that it remains nested inside the preserved envelope. Add the expected metadata value to the seed and third-policy tests.

## P2 — Consider

1. **The uppercase-identity test contradicts the lookup validation contract.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:353-355`, `:404-413`, `:584`  
   `CodeAct` violates the lowercase identity grammar, so `paradigm_policy('CodeAct')` must raise `invalid identity`, not `unknown paradigm` as W195 currently expects.

   **Suggestion:** Change the expected result to `22023 / invalid identity`, or allow mixed-case identity syntax consistently across the table, validator, and lookup.

2. **The source-text regex test is brittle and does not prove the architectural property it claims.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:590`  
   The proposed regex can false-positive across comments or unrelated SQL, while missing forms such as dynamic comparisons, `IF policy.identity = ...`, or helper-function identity branching. It will also impose a fragile repository-wide restriction on later numbered files.

   **Suggestion:** Prefer a behavioral test using a third policy identity and the same generic dispatch path. If a static guard is retained, scope it to the actual loop-driver function definition and sanitize comments/string literals before scanning.

3. **One current-tree README line citation is stale.**  
   **Reference:** `docs/plans/P19-paradigm-policies-2026-08-24.md:12`, `:513-519`; current `sql/README.md:39-46`  
   The current `0006 → p06` entry is at approximately line 46 after the P03 line was added, not within the cited `:39-44` range. The substantive current-tree claims—files `0000`, `0001`, `0002`, `0003`, `0006`; exact current `KERNEL_FUNCTIONS`; and current full-tree marker `p06`—otherwise match the supplied tree.

   **Suggestion:** Refresh the README line range before changing the plan status to `ready to implement`.