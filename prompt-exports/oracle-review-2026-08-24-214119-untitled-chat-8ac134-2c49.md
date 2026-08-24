# Oracle Review



# Verdict: **Not ready**

## Summary

The plan has the correct high-level D5 shape: grants are attached to slices, the retrieval API has no run-union helper, P06’s `required_grants` remain kinds-only, and P07 neither refreshes the plugin catalog nor wraps P03 emit/await. The request/issue verb split is an honest staged approach under the repository’s `GRANT`/role ban, but it is not itself an authorization boundary and must be presented and gated accordingly. Before implementation, the plan also needs to resolve run-identity incompatibilities, linearize concurrent grant transitions, make the corpus-freeze decision enforceable, preserve P03’s opaque event-scope contract, and avoid creating a second historical audit source outside `agent_steps`. The selected citations to `0002_p02_log.sql`, `0006_p06_plugin_catalog.sql`, the loader restrictions, and the current product-tree test generally agree with the supplied files.

## P1 — Should fix

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Decision 1, Goal, Risks, and `test_p07_issue_rejects_model_issuer`: the verb split is being asked to prove more authority than it provides.**  
  `p_issuer_kind` is caller-supplied, and the same database role can call `issue_grant(..., 'host')` or write the table directly. The plan acknowledges this in Risks, so this is not necessarily a D5 violation as a staged, non-exposed registry API; however, statements such as “only user/host can make a grant live” and the named test can be read as proving the locked model-only-request rule. They prove only that an honest caller passing `"model"` is rejected. If this surface becomes reachable before P08/P10 partitions model tools from trusted control-plane calls, D5 is violated.
  
  **Required change:** explicitly classify `p_issuer_kind` as asserted provenance, not authentication; state that all issue/approve/deny/revoke functions and direct table access are trusted-control-plane-only; and make “P07 must not be exposed until P08/P10 prevents model dispatch/direct SQL access” a hard delivery gate rather than only a risk note. Rename or qualify the test so it does not claim to prove caller identity. This does not require reopening the SQL-tree `GRANT`/role ban.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Component 2 (`slices`/`grants`) and Component 3 steps 1–2: the proposed `run_id` contract is incompatible with the existing kernel and is duplicated without database enforcement.**  
  The plan says `run_id` is the same logical key as `agent_steps.run_id`, but then trims it and limits it to 256 bytes. Existing `cordis.agent_steps` only checks `btrim(run_id) <> ''` and stores the original value; `emit_step` likewise does not normalize or impose a length limit. A run accepted by P02 can therefore be rejected by P07, and a value such as `" run-1 "` can be silently mapped to a different identity. In addition, `grants.run_id` can disagree with `slices.run_id` because the FK covers only `slice_id` and equality is enforced only by planned functions.
  
  **Required change:** preserve the existing exact run identifier semantics unless a kernel-wide migration explicitly changes them—validate nonblank but do not trim before storage/comparison or add a P07-only length limit. Prefer removing `grants.run_id` entirely and deriving it through the slice FK; the functions can retain `p_run_id` as an ownership fence. If the duplicate column is retained, add a database-enforced composite relationship such as a unique `(slice_id, run_id)` key on `slices` plus a composite FK from `grants`.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Component 3 locking, Components 5–6, and Risks: concurrent transition semantics are not linearizable as written.**  
  The partial unique index handles concurrent inserts, but it does not serialize reads against `deny_grant` or `revoke_grant`. For example, `request_grant` can observe a pending row while another transaction changes it to denied, then return an ID that is no longer pending. Similarly, `issue_grant` can observe an issued row while `revoke_grant` is committing and return an ID that ends up revoked. Updating a pending row without locking it can also overwrite or reverse a concurrent deny. The generic instruction to catch `unique_violation` and re-read is incomplete under these transitions and under transaction isolation stronger than Read Committed.
  
  **Required change:** specify a complete locking/linearization algorithm. Active-row reads used by request/issue should lock the row, state-changing updates should include the expected prior status and handle zero-row results, and insert conflicts should re-enter a bounded lock/re-read loop. Prefer an explicit partial-index `ON CONFLICT` target where possible rather than catching every unique violation. State the supported isolation-level behavior, including whether `40001` is propagated for caller retry. Add two-session tests covering at least request-versus-issue, issue-versus-revoke, and issue-versus-deny—not only sequential idempotency tests.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Decisions 4–5 and Risk “No content freeze”: “no silent expansion” is not actually resolved.**  
  The plan calls the corpus a whole immutable target and says new rights require explicit issuance, but it also says retrieval will use live project contents with no content snapshot. Adding rows/files to an already granted corpus silently expands what that grant can retrieve, even though `(kind, target)` did not change. Target immutability is therefore not equivalent to corpus-range immutability. This leaves one of the skeleton’s explicit P07 decisions unresolved while describing it as closed.
  
  **Required change:** choose and specify one enforceable semantic:
  1. bind each issued grant/slice to an immutable corpus revision or root fingerprint while keeping the external D5 literal `named_corpus:<id>`; or
  2. define the registered corpus root itself as immutable and state how P13 resolves it; or
  3. explicitly choose live-root semantics and stop calling it “no silent expansion,” documenting that this departs from the preferred conservative default.
  
  Whichever choice is made needs a schema/API hook and an acceptance test; merely deferring all content meaning to P13 does not complete the P07 freeze decision.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Decision 6 and `cordis.grants` lifecycle: retaining terminal attempts “for audit” creates historical truth outside the log.**  
  The architecture classifies grants as workspace state and `agent_steps` as the unique historical source of truth. The proposed table retains denied and revoked attempts indefinitely, allows later attempts for the same tuple to receive new IDs, and explicitly calls the old rows an audit record. Those old rows are no longer current workspace state; collectively they form a second lifecycle history with actors and timestamps.
  
  **Required change:** either make `grants` a current-state registry—one row per `(slice_id, kind, target)`, reusing/replacing terminal state and explicitly offering no historical audit contract—or record lifecycle history in `agent_steps` and derive/maintain current grant state accordingly. If terminal rows are retained only temporarily for reconciliation, state their non-authoritative status and cleanup lifecycle rather than describing them as audit truth.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Decision 3/7 and `grants_target_by_kind_check`: P07 invents an event-scope grammar despite treating the P03 scope as opaque.**  
  Restricting event targets to `[A-Za-z0-9._-]{1,128}` and trimming them creates a second definition of what an `event_scope_id` is. P03 may legitimately accept or generate a value that P07 cannot grant, or P07 may accept a value that cannot be passed back to P03 without conversion. “Opaque” means P07 should not infer a separate semantic grammar merely to serialize `event:<scope>`. The absence of an FK to `run_events` is correct because a grant may predate emission; the type/domain mismatch is the problem.
  
  **Required change:** copy or reuse P03’s exact `event_scope_id` type and validation contract, preserving its value byte-for-byte, and format `d5_literal` from that canonical value. Add a test using an event scope accepted/generated by P03 and verify that the corresponding P07 grant round-trips. Continue to avoid an FK and do not wrap `emit_event` or `await_event`.

## P2 — Consider

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Component 3 “Every writer uses the same rules”: the validation specification does not match the function signatures.**  
  `approve_grant`, `deny_grant`, and `revoke_grant` have no run, slice, kind, or target parameters; corpus and slice creation also cannot run the listed shared validation sequence. This wording leaves room for implementations to perform checks in inconsistent orders and makes SQLSTATE expectations ambiguous.
  
  **Required change:** divide validation into clearly named groups—issuer validation, run/slice ownership validation, kind/target validation, and grant-state validation—and list which group and check order each function uses. No additional SQL helper function is required.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Verification test mapping: the named tests do not unambiguously own the complete skeleton proof.**  
  The later “Protocol assertions” section contains the correct combined scenario—two issued corpus grants on different slices plus a cross-corpus model request that remains pending—but the named test table splits those properties between two tests without saying that either must execute the combined sequence. The corpus-freeze decision and concurrent unique-index behavior are also untested.
  
  **Required change:** make `test_p07_two_named_corpus_on_two_slices` include the cross-slice model request and all listed protocol assertions, or add a specifically named end-to-end D5 proof test. Add tests for the selected freeze semantic and the concurrent transition cases described above.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Component 8 `KERNEL_FUNCTIONS`: the tuple order is correct for C collation, but `ORDER BY 1` alone does not guarantee C ordering.**  
  The proposed tuple is lexically ordered correctly under C, including `_validate_plugin_definition` first. However, PostgreSQL sorts text using the database/expression collation unless the query explicitly selects C; punctuation such as `_` can sort differently under other locales.
  
  **Required change:** either make the test expression/order explicitly use `COLLATE "C"` or remove the unsupported claim that plain `ORDER BY 1` guarantees C ordering.