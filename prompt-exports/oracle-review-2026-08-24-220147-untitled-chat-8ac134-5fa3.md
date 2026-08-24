# Oracle Review



# Verdict: **Ready to implement**

The current plan closes all six round-1 P1 findings and both remaining round-2 P1s. Provenance is no longer presented as authentication; `run_id` matches P02 without duplication; grant writers consistently linearize through unlocked locator → slice `FOR UPDATE` → grant `FOR UPDATE`; the issue/deny outcomes now match the state machine; live-root semantics are explicit; grants are current-state tuples; P03 event scopes remain opaque; and `requested_by_kind` has a deterministic pending-cycle contract. The combined two-slice/pending-request test now proves the skeleton requirement, and the selected P02, P03, P06, loader, and `KERNEL_FUNCTIONS` references agree with the supplied files. No P0 or P1 findings remain.

## P2 — Consider

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Verification, `test_p07_api_errors_are_22023`: the NULL-target wording is broader than the API contract.**  
  Component 3 explicitly says that a SQL NULL target is normalized to `''` for `kind='run'`, while the test currently says “SQL NULL … targets … Each raises `22023`.” Taken literally, that would require the accepted `run` case to fail.

  **Required change:** qualify the negative cases as NULL targets for `named_corpus` and `event`, and add or retain a positive assertion that `kind='run', p_target=NULL` is normalized to the empty target.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Component 1 versus Component 8 version-function snippet: the stated `search_path` rule is not reflected in the exact snippet.**  
  Component 1 says all functions pin `search_path` to `pg_catalog`, but the shown `get_schema_version()` definition omits `SET search_path TO pg_catalog`. This function only returns a literal, so the omission is not a practical safety problem, but the implementation instructions are inconsistent.

  **Required change:** either add `SET search_path TO pg_catalog` to the version-function snippet or explicitly exempt this literal-only SQL function from the general rule.