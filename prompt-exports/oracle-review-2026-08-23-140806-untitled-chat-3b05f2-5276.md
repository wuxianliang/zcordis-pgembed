# Oracle Review

# Synthesis result

The four verdicts are **CONFIRMED**. They are mutually consistent: Q1 fixes the behavioral yield boundary, Q2 fixes the combined provider-idempotency and log-replay rule, Q3 fixes the authorization and naming semantics for events, and Q4 freezes only the shared jobs/claim/checkpoint substrate while deferring physical placement. The main work still missing is a precise yield-loop protocol connecting claim ownership, `WAITING` transitions, scoped event wakeups, retries, and stale-worker behavior. Nothing in Q1–Q4 requires freezing TE1 as “all durable-execution primitives belong in the kernel.”

## Q1–Q4 verdict table

| Question | Verdict | Synthesis status | Consistency assessment |
|---|---|---|---|
| **Q1 — Yield boundary** | **D — mixed**: normally yield after a completed LLM + tools step; force async/yield when spawn depth or cost crosses policy limits | **CONFIRMED** | Compatible with dual workers and the one-queue constraint. It avoids half-step yields while preventing `rlm_spawn` from hiding unbounded work. |
| **Q2 — `http_call_llm` idempotency** | **A+B**: provider `Idempotency-Key = H(run_id, step_name)` plus log skip-if-present with request-fingerprint validation | **CONFIRMED** | Correctly handles both provider-side duplicate requests and local replay. The stated residuals remain: provider support, tool idempotency, and explicit claim ownership. |
| **Q3 — Event names vs grants** | **C + constrained B**: emit/await require a grant over `(event_scope_id, event_name)`; prefixes may aid storage but are not authorization | **CONFIRMED** | Gives Q1’s await-user path a scoped security model without making events globally enumerable or requiring `LISTEN`. First-emit-wins remains scoped and log-backed. |
| **Q4 — TE1 freeze** | **C — targeted freeze**: freeze one jobs queue, one claim protocol, and log-backed checkpoints; defer sleep/event/retry placement | **CONFIRMED** | Correct scope. It freezes the minimum shared contract without prematurely deciding kernel versus plugin placement or A’s packaging question. |

> **Editorial clarification, not an amendment:** Q1 is correctly a **D/mixed** verdict. The parenthetical “(B)” should be read as describing the normal completed-step behavior, not as selecting option B (“per-tool”). If it is intended as an option label, it should be corrected.

## Tensions and couplings

### 1. Q1’s await behavior versus Q4’s deferred placement

This is **not a contradiction**.

- Q1 establishes the behavioral rule: a run must be able to yield rather than pin a session.
- Q3 establishes the event semantics: await and emit are grant-authorized and scoped.
- Q4 leaves open whether sleep, wait registrations, and wakeups live on the upgraded jobs catalog, a plugin surface, or another implementation.

The semantics can therefore be frozen before the storage or ownership placement is frozen. Q4’s “placement open” must not be interpreted as “await behavior optional”; it means only that the implementation locus remains undecided.

### 2. Q2’s claim-ownership requirement versus Q4’s one claim protocol

These are aligned, but the relationship is not yet explicit enough.

Q2 correctly identifies that idempotency alone does not establish which worker owns an `agent_runs` execution. Q4 freezes one claim protocol, so both the in-database loop and the host worker must use the same ownership and lease semantics. The next artifact must define how the queue job and the logical agent run correspond, without allowing independent ownership state in both places to diverge.

### 3. Q3 await-user behavior requires a claim lifecycle

Q3’s scoped await model is compatible with Q1 and Q4 only if the lifecycle is explicit:

1. The worker records the await intent and its scoped event identity.
2. The worker relinquishes its claim before entering `WAITING`.
3. An authorized, first-wins emit makes the run eligible to resume.
4. A worker reacquires the run through the same claim protocol before continuing.

The exact table or plugin location remains open. The ordering, release, and reacquisition semantics cannot remain implicit, or an expired worker could continue executing after another worker has resumed the run.

### 4. Q2 covers LLM idempotency, not tool idempotency

This is a deliberate residual rather than a verdict conflict. Q1 treats the LLM-plus-tools unit as the normal yield boundary, while Q2’s combined rule only protects the LLM request. A lease expiry or retry can therefore still repeat a non-idempotent tool call inside that unit.

The yield-loop artifact should preserve this distinction rather than implying that the entire step is duplicate-safe by virtue of the provider key. Tool behavior needs its own contract—such as idempotency requirements, capability restrictions, or an explicitly documented non-retryable class.

## Findings

### P1 — Claim ownership is not connected to the frozen claim protocol

**Reference:** `prompt-exports/oracle-e-four-verdicts.md` — Q2 residual and Q4 verdict; `docs/analysis/2026-08-23-e-absurd-durable-execution.md` — “Dual worker locus”.

**What is wrong:** Q2 requires claim ownership for `agent_runs`, while Q4 freezes a single claim protocol over the jobs queue, but the verdicts do not state which object is authoritative for owner, lease expiry, and run eligibility. If `jobs` and `agent_runs` independently carry `RUNNING`/owner state, the two worker loci can make conflicting decisions while still nominally using “one protocol.”

**Suggestion:** Make the next yield-loop sketch define one authoritative claim/lease contract keyed by the logical run identity, including:

- how a jobs row maps to an `agent_runs` row;
- where the owner and lease are observed;
- how host and in-database workers acquire and release it;
- how stale claims are fenced after timeout.

This should clarify the relationship without introducing a second queue or a second source of truth.

### P1 — The `WAITING` transition and wakeup ordering are underspecified

**Reference:** `prompt-exports/oracle-e-four-verdicts.md` — Q1/Q3/Q4; `docs/analysis/2026-08-23-e-absurd-durable-execution.md` — “Sleep / await-event implementation”.

**What is wrong:** Q1 and Q3 require a non-pinning await path, but Q4 defers the placement of sleep and event machinery. Without a protocol-level ordering, a worker can release its claim before the await registration is durable, or a wakeup can race with an old worker that still believes it owns the run.

**Suggestion:** Specify the abstract transition contract in the yield-loop artifact, independent of physical placement: await registration and its log event must become durable before claim release; resumption must require a new claim; emit must enforce the scoped first-wins rule; and stale workers must be unable to append or continue after losing ownership. Leave the choice of rows, tables, or plugin implementation open.

### P1 — The completed LLM-plus-tools boundary overstates the current idempotency coverage

**Reference:** `prompt-exports/oracle-e-four-verdicts.md` — Q1/Q2; `docs/analysis/2026-08-23-e-absurd-durable-execution.md` — “Dual worker locus” and residual question “Idempotency of `http_call_llm`”.

**What is wrong:** The Q2 verdict correctly solves the LLM duplicate-request problem only conditionally on provider support and log fingerprints. It does not make tool execution safe under claim overlap, retry, or crash-after-side-effect. Because Q1 treats LLM plus tools as the normal completion unit, the combined synthesis must not imply that the whole unit has exactly-once behavior.

**Suggestion:** Explicitly separate LLM idempotency from tool idempotency in the protocol sketch. Define which tool classes may be retried after lease overlap and what the worker must do for tools that cannot safely be repeated. Keep this as a residual contract question; do not weaken or amend Q2’s A+B verdict.

## Next research artifact

**Yes: produce the yield-loop sketch next.** It should be a protocol sketch, not a TE1 placement decision. At minimum it should show:

1. **Normal iteration:** claim → fold log/projections → perform LLM call → execute tools → append checkpoint/log events → complete or release the claim.
2. **Spawn policy:** when shallow work remains synchronous and when depth, fan-out, or budget forces an asynchronously scheduled child.
3. **Await-user path:** scoped grant check → durable await registration/log event → release claim → `WAITING` → authorized first emit → wake eligibility → reclaim.
4. **Retry and overlap:** log skip with request fingerprint, provider idempotency key, claim expiry, stale-worker handling, and tool idempotency boundaries.
5. **Both worker loci:** the in-database loop and host SDK worker performing the same claim/checkpoint/yield operations against the same jobs queue.
6. **Failure ordering:** especially crashes after the provider accepts a request, after a tool side effect, and before or after the checkpoint append.

The sketch should leave the physical placement of sleep, event, and retry primitives open, as Q4 requires.

## Residual open questions

- Exact claim-owner and lease representation, including the `jobs` ↔ `agent_runs` mapping and fencing after timeout.
- Whether sleep, event, and retry implementation belongs to the kernel, a plugin, or a split surface; TE1 remains open.
- Provider behavior when an idempotency key is unsupported, expired, or reused with a different request fingerprint.
- Idempotency and retry policy for tools, particularly side-effecting tools.
- Budget accounting and propagation: shared parent pool versus bounded child allocation, plus the exact depth/cost threshold from Q1.
- Creation and authorization of `event_scope_id` values and opaque await-user channels, including lifecycle and retention.
- How host workers acquire and carry D’s grants when they reclaim a run.
- A T5 packaging decision: SQL catalog versus extension/module packaging, provided it does not create a second logical queue.

**Overall disposition: CONFIRMED.** No verdict needs amendment; the next turn should operationalize the coupled lifecycle before freezing TE1 placement.