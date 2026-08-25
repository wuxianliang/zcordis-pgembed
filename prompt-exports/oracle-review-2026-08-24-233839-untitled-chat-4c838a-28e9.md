# Oracle Review

## Summary

Round 3 closes the round-2 numeric-overflow P1: the cap decision is made in the log domain, the `power()` path is used only below a safe exponent threshold, and the new extreme-policy regression exercises the previously failing case. The P19/P05 mix-in finding is also closed against authoritative snapshot `2331`: current-tree assertions and documentation consistently end at P07, while a truncated 0004 tree reports P04. The replay-schema P1 remains open because the new “fingerprints” are permissive substring checks rather than semantic or exact normalized comparisons. I also found a reachable two-sweeper deadlock in deadline-order processing. The sleep, retry, dead-letter, same-row, and emit-versus-timeout transitions otherwise match the plan. **No P0, but the review does not pass because P1 findings remain.**

## P1 — Should fix

- **`sql/0004_p04_sleep_retry.sql:127-285` — Replay verification still accepts incompatible defaults and same-named constraints.** The CHECK validators only search `pg_get_constraintdef` for fragments such as the column name, `NaN`, `>=`, and `Infinity`. For example, this incompatible constraint passes the current factor fingerprint while allowing values that make recovery fail inside `retry_delay_seconds`:

  ```sql
  CHECK (
      retry_backoff_factor <> 'NaN'::double precision
      AND retry_backoff_factor >= 0
      AND retry_backoff_factor <> 'Infinity'::double precision
  )
  ```

  Similar false positives include `max_attempts >= 0` and `retry_backoff_base_seconds <= retry_backoff_max_seconds OR true`. The new `CHECK (true)` test proves only that a constraint lacking every searched token is rejected. Defaults are also executed once and compared by value, so a nonconstant or stateful default can return the expected value during apply and different values for later inserts. This leaves the round-2 replay-schema P1 open despite the added metadata coverage.
  - **Suggestion:** compare each `pg_get_expr(conbin, conrelid)` and column default against an exact canonical normalized expression, rejecting compound or callable defaults rather than executing arbitrary catalog expressions. Add replay tests for a factor constraint using `>= 0`, a bounds constraint ending in `OR true`, and a nonconstant default that evaluates to `2` only during validation.

- **`sql/0004_p04_sleep_retry.sql:488-548` — Deadline-order processing can deadlock two concurrent global sweepers when a new past-due wait changes event-key order between their snapshots.** Event-row locks are retained until transaction end, but the loop acquires them in deadline order. One sweeper can therefore hold event A and later request B, while a second snapshot—after insertion of an older past-due B wait—holds B and later requests A. PostgreSQL will abort one transaction as a deadlock victim, causing a reachable `resolve_due_waits` or `claim_job` failure. The current race test covers resolver versus emitter, not resolver versus resolver.
  - **Suggestion:** preserve deadline-first **selection** by choosing the oldest `p_limit` rows in an inner query, then process that selected set in global `(event_scope_id, event_name, run_id)` order. This retains the plan’s starvation protection and event → jobs → wait order while making shared event-lock acquisition consistent. Add a two-resolver regression that pauses the first resolver after it acquires event A, inserts an older due wait for B, and verifies both calls complete without a deadlock.