# Oracle Review



## Summary

The updated P03 ship set implements scoped persistent events, active waits, atomic fan-out wake-up, emit-before-wait replay shape, first-write-wins event storage, and log-derived `awaiting` state while preserving the single jobs queue and P02 log-write monopoly. The round-1 payload validation and deterministic lock-wait test fixes are correct, and `FOR UPDATE SKIP LOCKED` removes the immediate event→jobs wait inside `await_event`. However, PostgreSQL retains the event row lock until transaction end—not statement/function return—so the claim-held deadlock remains reachable when `await_event` is called inside an explicit transaction. **Round 2 does not pass: no P0, one open P1.**

## P1 — Should fix

- **`sql/0003_p03_wait_event.sql:125-184`; `docs/plans/P03-wait-event-2026-08-24.md` Component 4 “Global lock sequence” and Component 7; `tests/test_p03_wait_event.py::test_p03_await_skips_locked_claim_without_deadlock` — The busy path returns without releasing its event lock.**

  `SKIP LOCKED` correctly prevents `await_event` from waiting for the jobs row, but the plan’s statement that it “releases the event lock at statement end” is incorrect for PostgreSQL row locks: the `FOR SHARE` lock remains held until the surrounding transaction ends. When this transaction created and then deleted the sentinel, a conflicting insert can likewise remain blocked on the uncommitted insert/delete until transaction end.

  The current regression hides this because the busy `await_event` runs through one-shot `psql` in autocommit mode. The following explicit-transaction sequence is still possible:

  1. T1 begins and calls `emit_step_claimed`, retaining the jobs-row lock.
  2. T2 begins and calls `await_event`; it locks/inserts the event row, skips T1’s jobs row, and returns `accepted=false`, but T2 remains open and still owns the event-key lock.
  3. T1 calls `emit_event` and blocks on T2’s event key.
  4. If T2 subsequently performs any blocking claim-fenced operation on that jobs row, PostgreSQL again has the event↔jobs cycle and aborts a transaction. Even without step 4, emission remains unexpectedly blocked until T2 commits or rolls back.

  **Suggestion:** ensure the busy/lost path rolls back the event acquisition before returning. One viable implementation is an inner PL/pgSQL block with an `EXCEPTION` clause, which establishes a subtransaction: acquire/insert the event row and attempt the nonblocking jobs lock inside it; on no row, raise and catch a private SQLSTATE so that subtransaction rollback removes the sentinel and releases locks before returning `accepted=false`. Alternatively, explicitly change the API contract so a busy result must abort the caller’s transaction, although that is less composable.

  Replace the regression with or add an explicit-transaction test: leave the transaction that received `accepted=false` open and prove that the claim-holding transaction can still complete `emit_event` before the first transaction commits. This will distinguish actual lock release from the current autocommit behavior.

## P2 — Consider

- **`tests/test_p03_wait_event.py::test_p03_event_and_wait_constraints` — JSON `null` is not tested through the public event protocol.**

  The current test manually inserts a `run_events` row containing JSON `null`, which proves the table constraint but not that `emit_event`, duplicate emit, canonical-log validation, and immediate `await_event` all preserve the SQL-NULL-versus-JSON-null distinction—especially after adding `src_payload IS NULL`.

  **Suggestion:** add an end-to-end case that emits `'null'::jsonb`, verifies a duplicate emit returns `emitted=false`, and verifies a later await immediately returns JSON `null` with the canonical source pointer.