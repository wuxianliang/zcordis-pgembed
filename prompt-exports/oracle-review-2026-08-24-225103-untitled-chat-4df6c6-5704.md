# Oracle Review



# Verdict: **Not pass**

There are no P0 findings, but the implementation has open P1 contract issues. The change otherwise implements the intended three-table, slice-bound grant registry with current-state transitions, stable tuple identities, asserted issuer provenance, opaque event scopes, slice-first writer locking, and no run-union retrieval API. The GRANT/REVOKE preflight requirement is also satisfied: prohibited words appear only in comments or `$p07$` bodies after sanitization.

## P1 — Should fix

1. **`slice_has_grant` omits required named-corpus registration validation**  
   **File:** `sql/0007_p07_grant_registry.sql` — `cordis.slice_has_grant`

   The deep plan requires `slice_has_grant` to use the shared kind/target validation, including raising `22023` with `unknown named corpus` when a syntactically valid corpus ID is not registered. The current named-corpus branch only validates the ID regex and then returns `false` when the corpus is unknown.

   This creates a behavioral mismatch between `request_grant`/`issue_grant` and the planned P08 read surface.

   **Suggestion:** Add the same `EXISTS` check used by `request_grant` and `issue_grant`, and add a test such as:

   ```sql
   SELECT cordis.slice_has_grant(
       'run-a', <slice>, 'named_corpus', 'missing'
   );
   ```

   asserting `unknown named corpus` and SQLSTATE `22023`.

2. **`issue_grant` timestamps the decision before acquiring its linearization lock**  
   **File:** `sql/0007_p07_grant_registry.sql` — `cordis.issue_grant`

   `v_now := pg_catalog.clock_timestamp()` is evaluated before the slice `FOR UPDATE`. If another transaction holds the slice lock, `issue_grant` may wait for an arbitrary period and then store the pre-wait timestamp as `decided_at`. This conflicts with the plan’s definition of `decided_at` as the time of the current decision and with the slice lock being the writer linearization point.

   A fresh direct issue also evaluates the default `created_at` after the earlier `v_now`, allowing `decided_at < created_at`.

   **Suggestion:** Capture `clock_timestamp()` only after the slice and matching grant row have been locked, immediately before each mutation. For a fresh issued row, explicitly set both `created_at` and `decided_at` to the same post-lock timestamp. Recompute it after any retry rather than keeping one value for the whole function.

3. **Corpus-label API validation is not equivalent to the table constraint**  
   **File:** `sql/0007_p07_grant_registry.sql` — `named_corpora_label_check` and `cordis.register_named_corpus`

   The table rejects `[[:cntrl:]]`, while the function pre-validates only `\x01`–`\x1F` and `\x7F`. Those predicates can differ under database locales that classify additional characters, such as C1 control characters, as `cntrl`. Such input can pass the function check and then leak a table `check_violation` (`23514`) instead of the planned API error `invalid corpus label` / `22023`.

   **Suggestion:** Use the exact table predicate in the function:

   ```sql
   OR p_label ~ '[[:cntrl:]]'
   ```

   Keeping validation expressions identical will also prevent future drift. Add a control-character edge-case test that verifies SQLSTATE `22023`.

## P2 — Consider

1. **The concurrency test does not execute all required linearization cases**  
   **File:** `tests/test_p07_grant_registry.py` — `test_p07_concurrent_request_issue_deny_revoke`

   The test proves blocking for request-then-issue and revoke-then-issue. However, the deep plan explicitly requires every row of the Component 6 concurrency table:

   - issue then revoke → revoked;
   - deny then issue from pending → issued;
   - issue then deny from pending → deny raises `22023`;
   - the reverse ordering of the fresh request/issue race.

   The current “issue then deny” section starts from an already issued row, so transaction A only exercises the idempotent issued path rather than promoting a pending row. In addition, this assertion does not actually require the SQLSTATE:

   ```python
   assert "22023" in msg or "grant is not pending" in msg
   ```

   because the preceding assertion has already guaranteed the second operand.

   **Suggestion:** Use a fresh tuple for each state-machine case, explicitly create the required starting status, prove backend B is blocked while A holds the slice lock, and assert the exact final status/ID. Run the failing backend with verbose error reporting and require `22023` directly.

2. **The planned negative API matrix is incomplete**  
   **File:** `tests/test_p07_grant_registry.py` — `test_p07_api_errors_are_22023`

   The deep plan explicitly calls for a SQL `NULL` kind case, but the test currently does not call any grant API with `p_kind = NULL`. It also does not cover the missing named-corpus behavior in `slice_has_grant`, which allowed the P1 drift above to pass.

   **Suggestion:** Add at least the NULL-kind cases for writer/read APIs and the unknown-corpus `slice_has_grant` case. It would also be useful to cover re-requesting both denied and revoked rows, asserting that the same `grant_id` returns to pending and all decision/revocation fields are cleared.