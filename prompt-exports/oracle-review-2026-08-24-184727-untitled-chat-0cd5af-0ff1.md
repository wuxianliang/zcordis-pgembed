# Oracle Review



## Summary

The P03 ship set implements persistent scoped events, active waits, first-write-wins canonical event logging, atomic fan-out wake-up, emit-before-wait resolution, and log-derived `awaiting` state while preserving the single jobs queue and P02 log-write monopoly. The round-2 fix is correct: the inner `BEGIN … EXCEPTION` block creates a PL/pgSQL subtransaction, and raising `P0301` rolls back the sentinel acquisition and releases the event-row lock before returning `accepted=false`, even when the caller keeps its transaction open. The updated two-session regression exercises that exact contract by allowing the claim-holding transaction to emit before the busy transaction commits, and the JSON-null end-to-end test correctly distinguishes JSON `null` from SQL `NULL`. I found **no P0, P1, or P2 findings**. **Round 3 passes.**