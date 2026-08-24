# Oracle Review

# Verdict: **Not ready to implement**

The revised plan closes five of the six round-1 P1 findings and now has the correct D5 shape: concrete grants are slice-bound, there is no run-union retrieval API, `run_id` follows P02 without duplication, terminal states are current workspace state, event scopes preserve P03 opacity, and live-root semantics are an explicit v0 choice. The remaining blocker is the concurrency specification: its documented lock order, transition outcomes, and proposed test expectations still contradict one another. A smaller unresolved API choice remains around repeated-request provenance.

## Round-1 P1 re-score

| Round-1 finding | Status | Remaining required change |
|---|---|---|
| **1.1 Provenance vs authentication** | **Closed** | None. Decision 1 now accurately calls `p_issuer_kind` asserted provenance, identifies direct SQL as trusted-control-plane access, and makes P08/P10 exposure control the delivery gate without requesting forbidden role/GRANT DDL. |
| **1.2 `run_id` compatibility / no `grants.run_id`** | **Closed** | None. `slices.run_id` now preserves P02’s nonblank, untrimmed text contract; `grants.run_id` is removed; `p_run_id` is only an exact slice-ownership fence. |
| **1.3 Slice-lock linearization** | **Still open** | Reconcile the contradictory lock-order wording and transition expectations, then specify tests that actually force lock contention. Details are in the first P1 finding below. |
| **1.4 Explicit live-root choice** | **Closed** | None. The plan explicitly chooses whole live-root identity with no P07 content snapshot and no claim that grant-target immutability freezes corpus contents. |
| **1.5 Current-state unique tuple** | **Closed** | None. The full `(slice_id, kind, target)` unique constraint, stable `grant_id`, and in-place status transitions avoid a second lifecycle-history source. |
| **1.6 P03 event-scope opacity** | **Closed** | None. Event targets now reuse P03’s nonblank-text contract, preserve bytes, permit `/` and `:`, avoid an FK/wrapper, and have a round-trip test. |

## P1 — Should fix

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Component 3 “Validation groups and locking,” Component 6 concurrency paragraph, and `test_p07_concurrent_request_issue_deny_revoke`: the linearization contract remains internally contradictory.**  
  The `Grant-state` group is defined as loading the grant `FOR UPDATE`, and the function matrix says approve/deny/revoke perform “grant-state by id then slice `FOR UPDATE`.” That conflicts with the immediately following mandatory order of slice first, grant second. The later per-function descriptions use the correct order, but an implementer following the group table would introduce grant-first locking.

  The expected issue-versus-deny result is also impossible under the stated state machine. Starting from `pending`:

  - If deny linearizes first, it changes the row to `denied`; issue then accepts `denied` and changes it to `issued`. Both succeed, final status is `issued`.
  - If issue linearizes first, it changes the row to `issued`; deny must then fail with `22023` because deny accepts only `pending`.
  - Therefore, “if deny runs last, status is denied” and “after both commit” cannot both hold.

  The named concurrency test also says only that it uses two sessions; it does not require one session to hold the slice lock while the other is shown to block, so a sequential test could pass without proving serialization.

  **Required change:** define an unlocked **grant locator** step for grant-ID APIs, then require:

  1. read immutable `slice_id` without locking the grant;
  2. lock the slice `FOR UPDATE`;
  3. re-read the grant `FOR UPDATE`;
  4. validate the expected status and update.

  Replace the concurrency outcomes with state-machine-accurate expectations:

  - request versus issue from no row: one row, final `issued`;
  - issue versus revoke from initially `issued`: final state follows the second linearized operation;
  - issue versus deny from initially `pending`: either both succeed with final `issued` when deny linearizes first, or deny receives `22023` when issue linearizes first.

  Require each two-session test to hold transaction A’s slice lock, demonstrate that transaction B is blocked, then release A and assert B’s exact result. Describe outcomes by **linearization order**, not loosely by commit order.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — `cordis.grants.requested_by_kind` and Component 5 step 5: repeated-request provenance is still left as an implementation choice.**  
  The plan says a duplicate pending request may either update `requested_by_kind` or leave it unchanged, while the column is described as “current requester provenance” and the plan claims no implementation questions remain. A model request followed by a user or host request will therefore produce different observable workspace state depending on the implementation.

  **Required change:** choose one contract and test it. The least disruptive choice is to define `requested_by_kind` as the actor that opened the **current pending cycle**:

  - duplicate requests while already pending leave it unchanged;
  - re-request after denied/revoked replaces it with the new requester;
  - request against an issued row changes nothing;
  - a fresh direct issue treats the issuer as the implicit originator.

  Remove “optionally” and “either behavior is acceptable,” and update the column description and idempotency test accordingly. If latest-requester semantics are preferred instead, require every duplicate pending request to update it consistently.

## P2 — Consider

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Execution index W71 versus Component 4: duplicate corpus behavior is described inconsistently.**  
  W71 says duplicate “name/id raises,” but `register_named_corpus` is explicitly idempotent when an existing corpus ID has the same exact label; only a conflicting label raises. `create_slice`, by contrast, rejects a duplicate `(run_id, name)`.

  **Required change:** rewrite W71 to say that same-ID/same-label corpus registration returns the existing ID, same-ID/different-label raises `22023`, and duplicate slice names raise `22023`.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — Verification test list: the declared SQLSTATE contract is not fully exercised.**  
  Component 3 says every validation error other than asserted model issuance returns `22023`, but the named tests do not clearly cover SQL NULL inputs, invalid non-model issuer/requester kinds, same corpus ID with a conflicting label, or duplicate slice-name conversion. Without those cases, implementations can leak native `23502`, `23505`, or `23514` errors through SQL three-valued logic or uncaught constraints.

  **Required change:** add a parameterized API-validation test asserting `22023` and stable message fragments for null/malformed IDs, labels, names, issuer/requester kinds and targets, plus conflicting corpus registration and duplicate slice creation. Keep direct table constraint failures separate from the function API contract.

- **`docs/plans/P07-grant-registry-2026-08-24.md` — P06 citation in “Signed contracts” and References: the selected line range is stale.**  
  The cited `sql/0006_p06_plugin_catalog.sql:90-92` lands around the indexes in the supplied file; the kinds-only constraint is the named `plugin_catalog_required_grants_check` immediately before them.

  **Required change:** cite the constraint by name or update the line range to the actual `plugin_catalog_required_grants_check`. The substantive P06 interpretation—kinds only—is correct.