# Oracle Review



# Verdict: **Pass**

The current `sql/0007_p07_grant_registry.sql` satisfies the P07 deep plan with no P0 or open P1 findings. It implements the three-table, slice-bound current-state registry; the required pending/issued/denied/revoked transitions and pending-cycle provenance; slice-first writer locking; live-root named corpora; opaque event scopes; model-request-only behavior; and slice-only retrieval without a run-union function. The three previously reported P1s are fixed in the current file: named-corpus existence is validated by `slice_has_grant`, `issue_grant` timestamps after both locks and aligns fresh `created_at`/`decided_at`, and label validation matches the table’s `[[:cntrl:]]` predicate. The skeleton test executes both slice grants and the pending cross-slice model request, while the concurrency test now starts issue-then-deny from a genuinely pending tuple and demonstrates B waiting while A holds the slice lock. Prohibited words remain confined to sanitized comments or `$p07$` bodies.

## P2 — Consider

1. **`slice_has_grant` performs kind/target validation before the planned run/slice ownership fence**  
   **File:** `sql/0007_p07_grant_registry.sql` — `cordis.slice_has_grant`

   Component 3 specifies run/slice validation first for read functions, followed by kind/target validation for `slice_has_grant`. The implementation currently validates the kind and checks `named_corpora` before checking whether the slice exists and belongs to `p_run_id`.

   This changes planned error precedence and lets a caller distinguish registered from unregistered corpus IDs even when supplying a missing or foreign slice.

   **Suggestion:** Validate `p_run_id`, locate the slice without locking, and verify exact run ownership before validating `p_kind`/`p_target` and performing the named-corpus `EXISTS` check.

2. **The fresh request/issue race is tested only request-first**  
   **File:** `tests/test_p07_grant_registry.py` — `test_p07_concurrent_request_issue_deny_revoke`

   The test now correctly covers all five principal transition rows, including pending issue-then-deny with verbose `22023`. It does not, however, execute the parenthetical reverse ordering from Component 6 where `issue_grant` linearizes first on a fresh tuple and a concurrent `request_grant` waits, then observes the already-issued row unchanged.

   **Suggestion:** Add a fresh slice where A issues and holds the transaction, B requests and is shown to block, then assert both calls return the same `grant_id`, the final status remains `issued`, and exactly one tuple row exists.