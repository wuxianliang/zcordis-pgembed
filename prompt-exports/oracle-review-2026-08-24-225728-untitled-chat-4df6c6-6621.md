# Oracle Review



# Verdict: **Not pass**

There are no P0 findings, but the attached SQL still contains the three previously identified P1 contract mismatches; the corresponding fixes are visible in the tests or described in the request, but not in `sql/0007_p07_grant_registry.sql`. In particular, the new unknown-corpus read test cannot pass against the displayed `slice_has_grant` implementation, so the reported 18-pass run does not correspond to the attached SQL revision. Apart from these points, the implementation follows the planned slice-bound current-state registry, state transitions, requested-by pending-cycle semantics, live-root model, opaque event scopes, slice-first writer locking, and absence of a run-union retrieval API; the prohibited-word preflight also remains satisfied.

## P1 — Should fix

1. **`slice_has_grant` still does not validate named-corpus registration**  
   **File:** `sql/0007_p07_grant_registry.sql` — `cordis.slice_has_grant`

   The displayed named-corpus branch checks only the target syntax and assigns `v_target`; it contains no `EXISTS` lookup in `cordis.named_corpora`. Consequently, a syntactically valid but unregistered corpus returns `false` instead of raising `unknown named corpus` with SQLSTATE `22023`.

   This directly contradicts the shared kind/target validation required by the plan. It also contradicts the current `test_p07_unknown_corpus_and_slice_mismatch`, which now expects that exception; that test should fail against this SQL.

   **Suggestion:** Add the same registration check used by `request_grant` and `issue_grant` before assigning `v_target`:

   ```sql
   IF NOT EXISTS (
       SELECT 1
       FROM cordis.named_corpora AS nc
       WHERE nc.corpus_id = p_target
   ) THEN
       RAISE EXCEPTION 'unknown named corpus'
           USING ERRCODE = '22023';
   END IF;
   ```

2. **`issue_grant` still captures the decision timestamp before locking**  
   **File:** `sql/0007_p07_grant_registry.sql` — `cordis.issue_grant`

   The attached implementation still executes:

   ```sql
   v_now := pg_catalog.clock_timestamp();
   ```

   before entering the retry loop and before taking the slice and grant `FOR UPDATE` locks. A blocked issuer therefore records a timestamp from before its linearization point. On a fresh insert, `created_at` is still supplied by the later table default rather than being explicitly set alongside `decided_at`, so `decided_at < created_at` remains possible.

   **Suggestion:** Remove the pre-loop assignment. After the slice and matching grant row have been locked, capture a fresh timestamp immediately before each mutation. For a fresh issued row, explicitly insert both timestamps:

   ```sql
   v_now := pg_catalog.clock_timestamp();

   INSERT INTO cordis.grants (
       slice_id,
       kind,
       target,
       status,
       requested_by_kind,
       decided_by_kind,
       created_at,
       decided_at
   ) VALUES (
       p_slice_id,
       v_kind,
       v_target,
       'issued',
       p_issuer_kind,
       p_issuer_kind,
       v_now,
       v_now
   );
   ```

   Recompute `v_now` after any retry rather than retaining a timestamp from an earlier attempt.

3. **The corpus-label API predicate still differs from its table constraint**  
   **File:** `sql/0007_p07_grant_registry.sql` — `cordis.register_named_corpus`

   The table uses:

   ```sql
   label !~ '[[:cntrl:]]'
   ```

   but the function still pre-validates with:

   ```sql
   p_label ~ E'[\\x01-\\x1F\\x7F]'
   ```

   These are not the same predicate. Locale-classified control characters outside those explicit ranges can pass the API check and then fail the table constraint with `23514`, leaking a storage-layer error instead of the planned `invalid corpus label` / `22023`.

   The added `\x01` test is rejected by both predicates, so it does not prove that the predicates have been aligned.

   **Suggestion:** Use the table predicate verbatim in the function:

   ```sql
   OR p_label ~ '[[:cntrl:]]'
   ```

   Add a C1/locale-classified control-character case, such as a label constructed with `pg_catalog.chr(133)`, and require SQLSTATE `22023`.

## P2 — Consider

1. **The issue-then-deny concurrency case still starts from `issued`, not `pending`**  
   **File:** `tests/test_p07_grant_registry.py` — `test_p07_concurrent_request_issue_deny_revoke`

   The first request/issue race leaves the tuple `issued`. The subsequent “issue then deny” section calls the idempotent `issue_grant` path on that already-issued row. It therefore does not prove the required transition where transaction A promotes a **pending** row to issued while transaction B’s deny waits and then fails with `22023`.

   The reverse ordering of the fresh request/issue race is also still absent.

   **Suggestion:** Give each concurrency-table row a fresh tuple and explicitly establish its required initial status. For issue-then-deny:

   1. Create a pending request.
   2. Have A call `issue_grant` and hold the transaction open.
   3. Verify B’s `deny_grant` is blocked.
   4. Commit A.
   5. Require B to fail with `22023`.
   6. Assert the same `grant_id`, final status `issued`, and exactly one tuple row.

   Add the fresh issue-then-request ordering as a separate case if the plan’s reverse-order proof is to be fully enforced.