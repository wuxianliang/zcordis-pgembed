# Oracle Plan

# Summary

**VERDICT: C** — freeze only the direction that `jobs`/`worker()` will become the single durable-work substrate and that in-database loops and host SDK workers will use one claim protocol. Do **not** freeze the placement of sleep, event, and retry as kernel primitives yet. This preserves the already-locked no-second-queue, dual-worker, and log-backed-checkpoint constraints while avoiding an unjustified commitment to the full TE1 kernel/plugin boundary before the yieldable-loop design demonstrates the required lease, release, resume, and wake behavior.

## Current-state analysis

The relevant execution path is currently:

```text
enqueue job
  → jobs row
  → worker() claims with FOR UPDATE SKIP LOCKED
  → registered job_handler executes
  → h_agent_run / h_rlm_run / h_hybrid_run runs the entire loop
  → LLM/tool calls
  → agent_steps / session-log append
  → worker marks the job DONE or ERROR
```

The existing `jobs`/`worker()` path is therefore the reusable queue and handler-registration mechanism. It already supplies:

- one logical work catalog;
- `FOR UPDATE SKIP LOCKED` claiming;
- `job_handler` registration through the existing COMMENT contract;
- compatibility with the existing CodeAct, RLM, and hybrid handlers.

It does **not** yet supply the durable-execution behaviors that TE1 discusses:

- lease expiry and heartbeat;
- yieldable checkpoints;
- future scheduling/sleep;
- named event waits and wakeups;
- retry/backoff state.

The current loop handlers hold the database session while the complete RLM or CodeAct loop executes. That is the obstacle TE1 is intended to close. A host worker cannot safely be added as a second implementation with independent queue semantics because it would create two claim paths and two interpretations of run ownership.

The log remains the authoritative history. Checkpoint state must therefore travel through the existing append path:

```text
step completion
  → append checkpoint-capable log event
  → deterministic fold / projection
  → resume logic reads the folded checkpoint state
```

A separate Absurd-style checkpoint table must not become authoritative. `rlm_vars` remains workspace state rather than history and is not part of the TE1 freeze decision.

The unresolved architectural boundary is narrower than the already-set execution constraints:

- the single queue and shared claim protocol are cross-cutting requirements for both worker loci;
- sleep, event, and retry have additional lifecycle, security, and scheduling semantics that have not yet been validated against the yieldable loop;
- A’s T5 question—SQL catalog versus extension/C implementation—is a packaging and implementation decision, not something this adjudication should settle.

## Design

### Verdict

**C — Freeze only “upgrade jobs + one claim protocol”; leave sleep/event/retry placement open.**

This is a **targeted contract freeze**, not a broader durable-execution refactor.

### What may freeze now

The following constraints can be treated as settled for subsequent design work:

1. **One logical queue**
   - Extend the existing `jobs`/`worker()` path.
   - Do not install Absurd’s `absurd.*` tables or run a sibling queue beside `jobs`.
   - Preserve the existing `job_handler` registration vocabulary while adding durable-run metadata as needed.

2. **One claim protocol**
   - Both execution loci must act as clients of the same claim contract:
     - in-database loop handlers;
     - host SDK workers.
   - The protocol must have one meaning for ownership, claim validity, checkpoint interaction, and yielding. Its concrete lease durations, overlap behavior, and idempotency policy are not adjudicated here.
   - The in-database loop is not allowed to retain a private “session-pinned” execution protocol that differs from the host worker’s protocol.

   Illustratively, the shared protocol surface is conceptually:

   ```text
   claim(run/job)       → ownership token or no work
   checkpoint(token, event) → log append and claim progress
   release/yield(token) → resumable non-running state
   complete(token)      → terminal success
   fail(token, reason)  → terminal failure
   ```

   The exact signatures and state columns remain implementation work.

3. **Checkpoints remain log-backed**
   - A completed named step is represented by a log event or a fold of log events.
   - A checkpoint lookup table may be added only as a derived cache.
   - Resume behavior must consult the log-derived checkpoint projection, not an independent checkpoint source of truth.

4. **Both worker loci remain first-class**
   - The host worker is not an optional alternative queue.
   - The in-database worker is not permitted to bypass the common claim semantics.
   - This freeze is compatible with the assumption that a yield policy will allow loops to release claims; it does not select the specific yield boundary.

### What must stay open

The following decisions remain deliberately unresolved:

1. **Placement of sleep**
   - Whether future scheduling is implemented in the kernel/jobs catalog, a plugin, or a split surface remains open.
   - The eventual design must support releasing the claim and resuming without holding a database session, but this verdict does not choose the storage or ownership mechanism.

2. **Placement of await-event and emit-event**
   - Named waits, wakeups, first-emit-wins behavior, event indexing, and grant/capability enforcement remain open.
   - This includes the event namespace and authorization details; no Q3 verdict is being made here.
   - The eventual event design must work for both SQL and host workers without introducing a second queue.

3. **Placement of retry**
   - Retry/backoff/cancellation policy remains open.
   - The decision must eventually specify whether retries are represented solely in upgraded job/run state, through log events plus projections, or through a plugin-owned policy over kernel state.
   - This verdict does not select retry timing, attempt identity, or failure-overlap behavior.

4. **Full kernel/plugin boundary**
   - Do not yet declare all five primitives—claim, checkpoint, sleep, event, and retry—to be kernel-owned.
   - Do not declare durable execution an optional plugin either.
   - The next architectural gate is a concrete yieldable-loop sketch showing how a loop:
     1. claims work;
     2. folds prior log/checkpoint state;
     3. performs one resumable unit;
     4. appends its checkpoint;
     5. releases or renews ownership;
     6. resumes correctly on a later worker.
   - The user-supplied assumption guarantees that such a policy exists in principle; it does not make the unresolved placement questions disappear.

5. **A T5 packaging choice**
   - Keep open whether the eventual implementation ships as:
     - SQL catalog/functions loaded by pgembed;
     - a formal Postgres extension;
     - a later C-backed implementation for hot paths.
   - The contract should be designed so this packaging decision is replaceable.
   - Packaging must not be used to justify importing `absurd.sql` as a second queue. A later SQL module or C extension is acceptable only if it implements the one logical `jobs`/run protocol.

### Why C is the correct adjudication

C freezes exactly the parts required by the locked constraints and nothing more:

- **No second queue** requires the existing jobs path to be the durable substrate.
- **Dual worker loci** require one claim protocol; otherwise SQL and host execution would diverge in ownership and recovery semantics.
- **Checkpoints as log events/folds** already determines the checkpoint source-of-truth rule.
- **Sleep, events, and retry** depend on the still-unproven state transitions around yielding, waiting, wakeup, retry, and resumption. Freezing their ownership now would turn current opinions into architecture without validating those transitions.
- A full A-style freeze would also prematurely conflate the logical kernel boundary with A T5’s unresolved packaging mechanism.

C is stronger than merely waiting because it preserves forward progress on the queue and claim contract. It is narrower than A because it does not pretend that every durable-execution feature has already earned kernel status.

### Rejected options

#### A — Freeze all five primitives in the kernel

Rejected because it commits sleep, event, and retry placement before the yield-loop lifecycle is specified. It would also risk treating a logical kernel decision as a decision about SQL catalog versus extension/C packaging. The evidence supports a shared claim substrate, but not yet the complete ownership of all five primitives.

#### B — Wait for the yield-loop sketch before freezing anything

Rejected as the overall verdict because it delays constraints that are already independently established:

- there must be one logical queue;
- both worker loci must use one claim protocol;
- checkpoints must be log-backed.

The yield sketch remains a prerequisite for freezing the **full** TE1 boundary, but it is not a reason to leave the already-locked queue and claim direction unrecorded.

#### D — Make durable execution an optional plugin and retain synchronous `rlm_loop` by default

Rejected outright. It leaves the current session-pinning obstacle unresolved, prevents async RLM spawn from having a common resumable substrate, and conflicts with the locked requirement that in-database and host workers share one claim protocol. It would preserve two execution models in substance even if only one queue table existed.

## File-by-file impact

No production code or schema changes follow directly from this adjudication.

If the research record is updated, only the Q4 material should change:

- **`prompt-exports/oracle-e-four-verdicts.md`**
  - Change Q4 from `pending` to `C`.
  - Record high confidence and the rationale above.
  - Do not fill in Q1, Q2, Q3, or S.
  - Keep the existing locked assumptions unchanged.
  - Dependency: none; this is an additive research verdict.

The Topic E analysis document should not be rewritten as though all five primitives are now kernel decisions. Its existing statement that full TE1 should wait for a yield sketch remains valid; this verdict adds the narrower C-level freeze.

## Implementation order

1. **Record the narrow Q4 verdict**
   - Freeze the one-queue and one-claim-protocol direction.
   - Explicitly leave sleep, event, retry, full kernel/plugin placement, and A T5 packaging open.

2. **Define the protocol-neutral jobs/run contract**
   - Specify how the existing `jobs` row represents claimable work and how both SQL and host workers identify the same run.
   - Preserve existing handler registration and avoid introducing Absurd sibling tables.

3. **Draft the yieldable-loop lifecycle**
   - Show claim, log fold, resumable unit, checkpoint append, release/renew, and later resume.
   - Do not use this step to adjudicate Q1, Q2, or Q3.

4. **Revisit full TE1 placement after the lifecycle is validated**
   - Decide whether sleep, event, and retry belong in the kernel, a plugin, or a split surface.
   - Keep the semantic contract independent of whether the implementation is SQL-catalog-based, a Postgres extension, or later C-backed code.