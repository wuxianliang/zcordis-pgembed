# Oracle Plan



# Summary

The product vision resolves eight of the nine pending decisions sufficiently for implementation planning: retire the PostgreSQL `pg_temp` data-analysis path in favor of a later DuckDB substrate, build the coding-agent product first around CodeAct and host-executed file tools, keep RLM children uniformly asynchronous, and retain one PostgreSQL durability kernel for logs, claims, grants, waits, retries, and plugin registration. D5 remains the only substantive user decision: slice-bound retrieval grants are mandatory in v0, but the exact grant grammar and issuing authority are not determined by the vision. None of these verdicts is a signed entry in `docs/decisions/2026-08-23-pending.md`.

# Current-state analysis

## Existing responsibilities and data flow

The selected documents describe three currently separate prototypes or design sources:

1. **pg_cordis durability kernel**
   - `jobs`/`worker()` provide the single queue and claim protocol.
   - `agent_steps` is the append-only history source of truth.
   - Checkpoints are log events or folds of that log.
   - `scratch/yield_walkthrough` proves three steps can be executed as three independent claims with a mock LLM.
   - The proof does not exercise host file tools, grants, waits, real LLM failure, or `pg_temp`.

2. **Coding workbench from RepoPrompt-CE**
   - Workspace/worktree state owns existing-file identity.
   - Context selection supports full files, slices, and codemaps.
   - Context Builder curates fragments and packages a prompt snapshot.
   - Mutating tools such as `apply_edits` act on the host filesystem and already have concepts such as operation IDs, path fencing, approvals, and retry classes.
   - This is the first product to convert into pg_cordis plugins.

3. **Data-analysis workbench**
   - The existing pg-agent workbench uses TEMP VIEWs tied to one PostgreSQL backend.
   - Yield releases the claim and permits another connection to continue the run, so `pg_temp` cannot survive the handoff.
   - The product vision explicitly replaces this path with a future DuckDB 2.0 plugin. PostgreSQL remains the coordination and durability plane; DuckDB becomes the materialization substrate.

4. **Complementary RLM execution**
   - prime-agent establishes the required semantic shape: `await rlm(...)` admits a child and returns a handle rather than the child answer.
   - Children are separate sessions/runs.
   - Results arrive later through `agent_message` or files.
   - Therefore synchronous recursive `rlm_loop(child)` is not part of the target first version.

## Target end-to-end flow

For the coding-agent-first product, the intended control path is:

1. A host worker claims a run using the same claim protocol as an in-database worker.
2. The current task or subtask identifies a **slice**, not merely a run.
3. The workspace/context plugin resolves only the grants attached to that slice.
4. Prompt assembly combines:
   - system and tool descriptions,
   - a grant-filtered fold of visible log history,
   - fragments retrieved under the slice’s live grants,
   - the selected full/slice/codemap representations.
5. One CodeAct claim performs one LLM invocation and its ordinary tool calls.
6. Read tools may be replayed. Host filesystem mutations use explicit `tool/call` and `tool/result` records and their own operation/reconciliation policy.
7. The step is checkpointed in `agent_steps`, and the claim is completed, yielded, slept, or placed into an event wait.
8. An RLM/context-builder child is always enqueued as a separate job. The caller receives an admission handle; it does not synchronously receive the child answer.

For the differentiating isolation example, function 1 carries grant `P1`, while functions 2 and 3 carry `P2`. Prompt assembly must not use the run-wide union `{P1,P2}`. The log-fold seam must also enforce the calling slice’s visibility; otherwise content retrieved earlier under `P1` could leak into a later `P2` prompt through history.

## Reusable mechanisms

The design should extend rather than duplicate:

- The existing `jobs`/`worker()` claim protocol rather than introducing an Absurd-style second queue.
- `agent_steps` for checkpoint, tool, spawn, wait, and wake history.
- RepoPrompt-CE’s selection representations and apply-edits operation/retry concepts.
- The isolation proposal’s P1 rule: grants are bound to slices and enforced at every retrieval seam.
- prime-agent’s asynchronous admission-handle contract.
- The DuckDB prototype’s durable-definition/lineage and rebuildable-workbench approach when the DA plugin is implemented.

## Hard constraints retained without reopening

- `agent_steps` remains the append-only history source of truth.
- Plugins are pg_cordis plugins, not separate `CREATE EXTENSION` packages.
- There is one upgraded `jobs` queue and one claim protocol.
- In-database and host workers use that same protocol.
- Checkpoints remain part of the log.
- The default yield unit remains one LLM call plus its ordinary tools.
- Existing LLM idempotency is not generalized into an unconditional exactly-once guarantee for tools.
- Event authorization remains capability-based on `(event_scope_id, event_name)`.
- Isolation is retrieval-grant isolation, not Zleap workspace partitioning.
- DSH is migration input, not runtime inventory.
- The scratch proof remains evidence only; it is not a production implementation.

# Design

## Verdict terminology

- **`lock_option`**: the vision and evidence select an option strongly enough to use as the implementation baseline, subject to user confirmation.
- **`lock_direction`**: mandatory invariants are known, but a remaining architectural choice still requires the user.
- **`defer`**: an explicit staged exclusion; it must not be implemented through an unacknowledged version of another option.
- **`still_user`**: the evidence does not materially narrow the choice.

## D1–D9 summary

| ID | lock_level | recommended option | confidence | vs Kimi lean | one-line why |
|---|---|---|---:|---|---|
| D1 | `defer` | **D**, re-read as “retire/defer PG-TEMP DA; DuckDB plugin later” | 0.97 | Conflicts with primary **A**, but adopts its **D** contingency for a product-level reason | The first product is a file-worktree coding agent, while future DA materializations belong in DuckDB, not a run-level PostgreSQL workspace. |
| D2 | `lock_option` | **A+C** | 0.95 | Aligns | Host filesystem and future DuckDB effects cannot commit atomically with the PG claim, so tools require capability classes plus call/result records. |
| D3 | `lock_option` | **B** | 0.92 | Aligns | Durable event and wait state belongs in `run_events`/`run_waits`, while `jobs` remains the single eligibility and scheduling queue. |
| D4 | `lock_option` | **A** | 0.91 | Aligns | Coding approvals, async children, recovery, and scheduled work all require sleep, scoped events, and retry in the installed kernel. |
| D5 | `lock_direction` | **C for v0, with A as the upgrade path** | 0.87 | Aligns with the C lean and makes it mandatory rather than optional | Slice-bound named-corpus grants are the product differentiator, but the vision does not settle the issuer or final descriptor grammar. |
| D6 | `lock_option` | **C** | 0.91 | Aligns | v0 has evidence for step/depth/fan-out limits, while token and cost pools are neither required nor supported by the referenced systems. |
| D7 | `lock_option` | **D** | 0.98 | Aligns | Kernel SQL belongs in this repository and pg-agent is a testbed; individual coding and DuckDB plugins must not become separate extensions. |
| D8 | `lock_option` | **A**, plus the minimum plugin catalog needed for host dispatch | 0.94 | Aligns | Coding-agent-first requires the host execution locus now, but not DSH event compatibility, a migrator, or dynamic TypeScript loading. |
| D9 | `lock_option` | **D** | 0.97 | Narrows the pending **D/B** lean to **D** | prime-agent’s RLM contract and the durable child-run evidence both require every child spawn to enqueue and return an admission handle. |

---

## D1 — TEMP VIEW versus yield

- **Lock level:** `defer`
- **Recommended option:** **D**

**Required new reading of D:** D means “retire and defer the PostgreSQL `pg_temp` DA path, not data analysis as a product”; coding-agent v0 uses PostgreSQL for durable coordination and a host worktree for files, while a later DuckDB plugin owns DA materializations.

### What the vision supplies

- The first product is explicitly the RepoPrompt-CE-style coding agent.
- The existing InfiniSQL/PG TEMP VIEW path is explicitly a prototype, not the product runtime.
- The future DA substrate is explicitly DuckDB.
- Both substrates share the pg_cordis kernel, grants, log, spawn protocol, and registry.
- Session affinity options B and C remain incompatible with interchangeable workers and one-claim-at-a-time execution.

### What remains missing

- DuckDB workbench lifecycle: in-process versus service-managed connections, database-file retention, and teardown.
- The exact durable manifest used to rebuild views/tables and lineage.
- Artifact archival and parent/child merge-back semantics for DuckDB workbenches.
- The physical schema for PostgreSQL coordination state such as workbench registry and lineage references.

These are DuckDB plugin design tasks, not reasons to preserve `pg_temp`.

### Confidence and falsifier

- **Confidence:** 0.97
- **Falsifier:** A deployment requirement proves that the DA product must execute exclusively inside PostgreSQL transactions and that DuckDB cannot provide isolated, replayable per-run workbenches. That would require reconsidering an A-like durable PG substrate.

### Conflict with pending research lean

This conflicts with pending.md’s primary recommendation of **A** as the DA materialization solution. It agrees with **D** as the selected phase boundary, but for a stronger reason than “not enough time.” The DBOS principle that durable state must be recoverable is retained for PG coordination and DuckDB manifests; it does not require the physical analytical tables to live in PostgreSQL.

This is not a hidden form of A: PG tables may hold selections, grants, log events, environment variables, registry entries, and lineage metadata, but not the product’s analytical intermediate tables or views.

---

## D2 — Tool replay and overlapping leases

- **Lock level:** `lock_option`
- **Recommended option:** **A+C**

### What the vision supplies

The coding product identifies the concrete tool classes that the earlier TEMP-oriented discussion lacked:

- **Replay-safe reads:** tree, search, file reads, context inspection, and database reads without side effects.
- **PG-transactional operations:** operations whose effect and corresponding result can be committed in the same PostgreSQL transaction.
- **Non-PG-transactional operations:** `apply_edits`, worktree operations, external HTTP, paid services, message/file publication, and future DuckDB mutations from the perspective of the PG claim transaction.

The protocol should therefore be:

1. Classify every registered tool by retry/effect semantics.
2. For nontransactional tools, append a durable `tool/call` before invoking the side effect.
3. Execute with a stable operation ID when the tool supports reconciliation or idempotency.
4. Append `tool/result` after success or a classified failure.
5. If recovery sees a call without a result:
   - replay a read or idempotent/reconcilable operation;
   - otherwise mark the step indeterminate/non-retryable rather than blindly repeating the mutation.

DuckDB transactions do not make a DuckDB operation transactional with the PostgreSQL claim. Until there is an explicit cross-store recovery protocol, DuckDB mutations belong to the non-PG-transactional class.

### What remains missing

- The plugin-catalog field names for retry class, effect class, operation-ID support, and reconciliation handler.
- Stable operation-ID derivation for each host tool.
- The user-visible recovery state for a call whose external effect may have succeeded but whose result was not logged.
- Whether a particular DuckDB operation is replayed from a manifest, deduplicated by name/version, or rejected as indeterminate.

### Confidence and falsifier

- **Confidence:** 0.95
- **Falsifier:** All production mutations become atomically commit-able with the PostgreSQL claim, eliminating the external-effect crash window. In that case C would be unnecessary for those tools.

### Conflict with pending research lean

None. It directly confirms the pending **A+C** recommendation. It does not reopen the locked LLM idempotency pin: LLM A+B remains its own rule, and tools receive only the guarantees declared by their classifications.

---

## D3 — Physical placement of sleep and await

- **Lock level:** `lock_option`
- **Recommended option:** **B**

### What the vision supplies

Coding-agent v0 needs durable waits for:

- file-edit or merge approval,
- context-builder/RLM child completion,
- external user input,
- retry backoff and scheduled resumption.

The state transition should remain within the single jobs engine:

1. The worker writes `run/await` or sleep intent to `agent_steps`.
2. In the same PostgreSQL transaction, it registers `run_waits`, changes the job to a non-claimable waiting state, and releases the lease.
3. An event is durably inserted into `run_events`.
4. Event consumption and job reactivation occur transactionally.
5. An event emitted before the wait must still be discoverable.
6. Duplicate event emission follows a defined first-write-wins rule; duplicate wait registration is deduplicated by the run and logical event key.

`run_events` and `run_waits` are side tables supporting the one queue, not a second queue or source of history truth.

### What remains missing

- Exact primary keys, uniqueness rules, indexes, and retention policy.
- Lock ordering between event, wait, run, and job rows.
- Whether payload is stored only in the log or additionally cached in `run_events`.
- Exact job status names and which wake transitions are externally observable.

### Confidence and falsifier

- **Confidence:** 0.92
- **Falsifier:** A measured implementation demonstrates that side-table coordination cannot preserve atomic wait/wake transitions or creates unacceptable contention, while placing the minimal wake fields on `jobs` solves the problem without conflating responsibilities.

### Conflict with pending research lean

None. It confirms **B** and preserves the locked single-queue constraint.

---

## D4 — Kernel contents

- **Lock level:** `lock_option`
- **Recommended option:** **A**

### What the vision supplies

Both product families require the same five kernel primitives:

1. claim,
2. log checkpoint,
3. sleep,
4. capability-scoped event,
5. task-level retry.

CodeAct does not remove the need for waits: approvals, children, external messages, and retries all cross claim boundaries. RLM’s asynchronous child model makes events/waits more central, not less central.

The retry **state machine** belongs in the kernel: attempts, eligibility time, terminal failure, and lease-safe rescheduling. Retry curves and plugin-specific retry decisions may remain configuration or policy.

### What remains missing

- Public SQL function names and result shapes.
- Default retry/backoff policy and maximum attempts.
- Administrative inspection and cancellation interfaces.
- Cleanup/partitioning policy, which remains outside the core semantics.

### Confidence and falsifier

- **Confidence:** 0.91
- **Falsifier:** The intended minimum deployment can provide a usable durable coding agent without waits, events, or retries, and including them imposes an unacceptable privilege or deployment dependency. That would reopen B or C.

### Conflict with pending research lean

None. It confirms **A**. This does not silently change the existing TE1 pin: TE1 remains narrow-frozen until the user confirms this verdict, after which sleep/event/retry can be promoted through the normal decision record.

---

## D5 — Grant grammar and issuer

- **Lock level:** `lock_direction`
- **Recommended option:** **C for v0**, preserving **A** as the planned upgrade

### What the vision supplies

The following are product requirements, not optional paper:

- Isolation is based on retrieval ranges.
- Grants bind to a task slice, prompt segment, child request, or tool invocation.
- Retrieval must use only the union of the **calling slice’s** grants, never the run’s full grant set.
- The fold/history seam, recall seam, environment reads, and tool dispatch must all enforce that same boundary.
- Coding v0 must express at least:
  - `named_corpus:<id>` for a project/reference corpus,
  - `event:<opaque-scope-id>` for scoped event capabilities,
  - run-owned output/workspace access where required.
- A `run_id`-only fallback is not an acceptable v0 isolation implementation.
- SQL predicate text supplied by users or models is not an acceptable grant grammar.

For the worked example, the minimum state is conceptually:

- Slice `function-1` → grant `named_corpus:project-1`
- Slice `function-2` → grant `named_corpus:project-2`
- Slice `function-3` → grant `named_corpus:project-2`

Prompt assembly and context building must preserve those associations through selection and packaging.

### What remains missing and requires the user

1. **Issuer authority**
   - Whether a user directly signs grants.
   - Whether a trusted host/orchestrator may sign from a user instruction.
   - Whether a planner may propose grants that require approval.
   - Whether the model is categorically limited to requests.

2. **Exact v0 grammar**
   - Whether `named_corpus` always means an entire registered project root or can name a versioned subset.
   - Whether corpus snapshots are immutable for a run.
   - How revocation affects an in-progress prompt or child.
   - Whether compound descriptors are needed in v0.

3. **Upgrade boundary**
   - When C becomes insufficient and structured A descriptors are introduced.
   - How existing C grants are represented as a subset of A without migration ambiguity.

**Oracle recommendation for the unresolved issuer:** permit the user and a trusted host/orchestrator to issue grants; permit the model only to request them. This is a recommendation, not something the vision has already signed.

### Confidence and falsifier

- **Confidence:** 0.87 for C as the v0 grammar; effectively 1.0 that slice-bound grants cannot be deferred.
- **Falsifier:** The first coding-agent workflows require row-, branch-, path-, or version-level filters that cannot be represented securely as registered named corpora. That would move the first version directly to structured option A.

### Conflict with pending research lean

No conflict with the C lean. The vision strengthens the status: **D is ruled out**, while C versus an immediate constrained form of A and the issuer model still require the user. D5 is the only D1–D9 item that should not be treated as option-locked.

---

## D6 — Child-run budget propagation

- **Lock level:** `lock_option`
- **Recommended option:** **C**

### What the vision supplies

Coding-agent v0 and prime-agent supply no shared token- or currency-pool primitive. The existing enforceable controls are sufficient for the first version:

- maximum depth: 4,
- maximum direct children per parent: 16,
- child `max_steps` bounded by `min(parent limit, 6)`,
- map fan-out bounded by 8.

With D9-D, these checks occur when a child job is admitted, not inside a synchronous recursive call. RepoPrompt-style selection token limits remain a context-builder plugin concern and must not be mistaken for a kernel-wide LLM cost pool.

### What remains missing

- Whether later accounting uses a shared parent pool or bounded child allocations.
- Token and currency metering authority across model providers.
- Cancellation policy when a future aggregate budget is exceeded.
- Whether DA workloads require a separate resource budget such as bytes scanned or materialized size.

### Confidence and falsifier

- **Confidence:** 0.91
- **Falsifier:** The first production release has a mandatory per-run token or monetary SLA that cannot be enforced with step/depth/fan-out limits.

### Conflict with pending research lean

None. It confirms **C** for v0 without deciding the later A-versus-B budget model.

---

## D7 — Delivery shape

- **Lock level:** `lock_option`
- **Recommended option:** **D**

### What the vision supplies

- The canonical kernel SQL belongs in `zcordis-pgembed`.
- pg-agent remains a consumer/testbed and must not become the source of the contract.
- Packaging is deferred until the SQL contract is stable.
- Workspace, context-builder, apply-edits, and later DuckDB workbench functionality are registered pg_cordis plugins.
- Those plugins must not be delivered as separate PostgreSQL extensions.
- Only the kernel may later receive an extension wrapper; that future packaging decision does not alter the plugin model.

### What remains missing

- The final versioned SQL directory and filename convention.
- Installation metadata and migration conventions.
- The point at which the kernel receives a `CREATE EXTENSION pg_cordis` wrapper, if ever.
- Plugin catalog schema and plugin-version compatibility rules.

The selected repository tree does not expose an established production SQL layout, so the implementation should validate the full repository/build convention before choosing the path rather than treating `scratch/install_driver.sql` as canonical.

### Confidence and falsifier

- **Confidence:** 0.98
- **Falsifier:** A target managed-PostgreSQL environment requires extension packaging before any SQL can be installed or tested, making B unavoidable for the kernel. This would still not justify one extension per plugin.

### Conflict with pending research lean

None. It confirms **D**.

---

## D8 — Host SDK and plugin seam

- **Lock level:** `lock_option`
- **Recommended option:** **A**, with the minimum plugin catalog required by the product

**New reading of A:** the minimal SQL seam includes catalog lookup and dispatch metadata for registered pg_cordis plugins; it does not include dynamic TypeScript loading, DSH event compatibility, a manifest-to-SQL migrator, or UI APIs.

### What the vision supplies

The coding product forces the host execution locus into v0 because filesystem operations cannot be performed by an ordinary SQL-only worker. The host must be able to:

- claim and renew/release work under the common protocol,
- append log events and step results,
- checkpoint, yield, sleep, and await,
- retrieve the active slice and grants,
- look up tool/plugin metadata,
- execute host-locus tools,
- report classified tool outcomes.

The plugin catalog must semantically identify at least:

- plugin/tool identity and version,
- execution locus,
- required grants/capabilities,
- read/transactional/nontransactional effect class,
- retry or reconciliation support.

The physical schema and SDK language remain implementation details.

### What remains missing

- Exact SQL signatures and SDK data structures.
- Authentication and session-role assumptions for host workers.
- Catalog schema and version negotiation.
- The first supported host SDK language.
- Heartbeat and cancellation surface details.
- Whether catalog metadata is entirely declarative or may reference registered SQL handlers.

### Confidence and falsifier

- **Confidence:** 0.94
- **Falsifier:** A host worker cannot execute coding tools safely or reconstruct context with the minimal claim/checkpoint/yield/catalog seam and demonstrably requires the richer DSH event model. That would justify B.

### Conflict with pending research lean

None. It confirms **A** while adding only the catalog necessary to satisfy the explicit plugin product model.

---

## D9 — Asynchronous spawn threshold

- **Lock level:** `lock_option`
- **Recommended option:** **D**

### What the vision supplies

All child-agent creation is asynchronous in v0:

1. The parent requests a child.
2. pg_cordis admits a distinct child run/job.
3. The call returns an admission handle containing child identity and admission status.
4. The parent does not receive or fold the child answer in the spawning transaction.
5. Results arrive through `agent_message`, files, or a later durable wake/message path.
6. The D6 depth, child-count, and step caps are checked at admission.
7. Ordinary CodeAct tool calls inside one claim are not “spawn” and remain part of the mixed-D yield unit.

This removes synchronous recursive subtrees and backend affinity.

### What remains missing

- Exact admission-handle shape.
- Idempotent child-run identity and duplicate-enqueue behavior.
- Spawn lineage event names and the transaction boundary between logging and enqueueing.
- Parent cancellation propagation.
- The exact event/message contract by which a waiting parent resumes.
- Orphan-child retention and supervision policy.

These details are required to implement D safely but do not change the choice between B and D.

### Confidence and falsifier

- **Confidence:** 0.97
- **Falsifier:** A required first-version workflow must synchronously receive a child answer within the parent transaction, and evidence shows that replacing it with a queued child breaks correctness rather than merely adding latency.

### Conflict with pending research lean

This resolves pending.md’s **D or B** range in favor of **D**. It agrees with the durable-execution direction and rejects B only as an unnecessary v0 optimization.

# User-sign status

## Substantive choice still required

- **D5** — the user must choose or confirm:
  - C named-corpus grammar versus an immediate constrained A grammar,
  - who may issue grants,
  - whether models may only request grants,
  - the corpus snapshot/revocation rules.

The implementation must not substitute run-wide visibility while waiting for this choice.

## Research-locked, pending confirmation

The following can be treated as planning baselines, but still require confirmation before their `决定` cells are populated:

- **D1:** D under the DuckDB substrate reading
- **D2:** A+C
- **D3:** B
- **D4:** A
- **D6:** C
- **D7:** D
- **D8:** A plus minimal plugin catalog
- **D9:** D

Governance remains explicit: **none of D1–D9 is signed by this adjudication**. If `pending.md` is authoritative, the user must ratify even the research-locked items before they are recorded as final decisions; only D5 requires additional design selection rather than confirmation.

# Sequencing

## Coding-agent-first v0

| Area | Included in v0 |
|---|---|
| Durability kernel | One `jobs` queue, shared claim protocol, append-only `agent_steps`, checkpoint, sleep, scoped event, task retry |
| Isolation | Slice-bound named-corpus grants enforced at recall, fold, environment, and tool-dispatch seams |
| Plugin system | pg_cordis catalog and registration; no independent extension package per plugin |
| Workspace | Per-run Git worktree lifecycle and target-file identity |
| Context | Full/slice/codemap representations, selection registry, prompt packaging, Context Builder |
| Primary agent | CodeAct: one LLM plus its ordinary tools per claim |
| File tools | Search/tree/read plus path-fenced `apply_edits` and worktree operations |
| Tool recovery | A+C classification with durable call/result for nontransactional operations |
| Complementary RLM | Every child enqueued; admission handle returned immediately; result via messages/files |
| Budget | Step/depth/child/fan-out hard caps only |
| Host support | Minimal claim/checkpoint/yield/wait/catalog SDK seam |
| DA behavior | No pg-agent `pg_temp` workbench migration and no sticky-session scheduler |

The coding v0 must prove at least:

1. Two workers can alternate claims for one coding run.
2. A host filesystem mutation can survive call/result recovery without an unclassified duplicate.
3. The project-1/project-2 isolation example produces no cross-slice retrieval or fold leakage.
4. An RLM child returns a handle, runs independently, and publishes a later result.
5. Event-before-wait, duplicate event, retry, and lease-expiry cases preserve one-queue semantics.

## DuckDB DA plugin later

The later DA phase adds:

- a per-run or per-task DuckDB workbench substrate;
- generative `SELECT … AS <view/table>` operations;
- durable definitions, lineage, and workbench registry entries in the pg_cordis coordination plane;
- rebuild/replay into a fresh DuckDB environment;
- parent-to-child inheritance and merge-back rules for named analytical objects;
- artifact archive and recall;
- DuckDB-specific tool classifications and reconciliation.

It does **not** add:

- a second jobs queue,
- a second claim protocol,
- PostgreSQL backend affinity,
- a migration of `plugin_temp_views.sql` into the kernel,
- a separate `CREATE EXTENSION` package for the DuckDB plugin,
- a synchronous RLM subtree.

Until a cross-store atomicity protocol exists, DuckDB mutations remain nontransactional relative to PostgreSQL and follow D2’s call/result and reconciliation contract.

# File-by-file impact

No repository file is changed by this response.

After user confirmation, the decision-recording work should be:

- **`docs/decisions/2026-08-23-pending.md`**
  - Populate D1–D4 and D6–D9 only after explicit user confirmation.
  - Record D1 as D with the DuckDB substrate reading so it cannot later be mistaken for “DA is abandoned” or “use A silently.”
  - Leave D5 unsigned until the issuer and grammar are confirmed.
  - Preserve the locked-pins section unchanged.

- **`docs/analysis/2026-08-23-h-vision-context-for-oracle.md`**
  - Keep as the evidence/context brief.
  - At most add a link to the eventual verdict record; do not rewrite H1–H8 as though they were original decisions.

- **`docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md`**
  - Keep its proposal status.
  - A later decision record may promote P1’s slice-binding invariant without implying that all P0–P8 clauses were approved.
  - Do not weaken the worked example into run-wide grant unioning.

- **Future canonical kernel SQL source**
  - Establish under D7-D only after validating the repository’s intended production SQL layout.
  - Do not promote `scratch/yield_walkthrough/install_driver.sql` in place without separating proof-only assumptions from the kernel contract.

# Risks and migration

- **D1 prototype discontinuity:** existing pg-agent TEMP VIEW behavior is not migrated into pg_cordis. If retained for experiments, it must be labeled a separate prototype and must not constrain the kernel.
- **D5 partial enforcement:** adding grant records before every recall, fold, environment, and tool seam enforces them would create a false security boundary. The grant-backed feature must not be exposed until all seams are covered.
- **D9 API break:** existing synchronous spawn callers must migrate from “return child answer” to “return admission handle and observe later output.”
- **External-effect ambiguity:** a crash after `apply_edits` or a DuckDB mutation but before `tool/result` may leave an indeterminate call. Each tool needs a reconciliation or non-retryable policy.
- **Cost exposure:** D6-C does not enforce token or monetary budgets. Metrics should still be recorded so later budget policy has evidence.
- **Packaging ambiguity:** “pg_cordis plugin” must not be interpreted as “one PostgreSQL extension per plugin”; only the shared kernel may later receive extension packaging.

# Implementation order

1. **Obtain user confirmation**
   - Ratify D1–D4 and D6–D9.
   - Resolve D5’s issuer and exact v0 grammar.
   - Do not fill `pending.md` before this step.

2. **Record the decisions**
   - Add the D1 DuckDB reading explicitly.
   - Record D5’s slice-binding invariants separately from its chosen grammar.
   - Preserve all locked pins.

3. **Establish the canonical SQL source under D7-D**
   - Separate kernel SQL from scratch evidence.
   - Keep pg-agent as an integration testbed rather than the contract owner.

4. **Implement the five-primitives kernel**
   - Upgrade the single jobs/claim path.
   - Add D3-B wait/event side tables.
   - Make log append, wait registration, job transition, and lease release atomic where required.
   - Add kernel retry state without embedding plugin-specific retry policy.

5. **Add the plugin catalog and grant registry**
   - Define execution locus, required grants, and effect/retry classifications.
   - Land slice-bound enforcement across recall, fold, environment, and tool seams atomically; partial enforcement must remain disabled.

6. **Add the minimal host SDK seam**
   - Prove a host worker and in-database worker can alternate claims under the same protocol.
   - Exercise plugin lookup and capability presentation without DSH runtime loading.

7. **Implement coding workspace and context plugins**
   - Worktree lifecycle, selection, full/slice/codemap representations, prompt packaging, and Context Builder.
   - Validate the two-project/three-function isolation scenario before general release.

8. **Implement D2 tool recovery**
   - Register every first-party tool’s effect class.
   - Add call/result handling and operation reconciliation for `apply_edits` and other host mutations.
   - Test lease loss at each external-effect crash boundary.

9. **Replace synchronous spawn with D9-D**
   - Enqueue every RLM/context-builder child.
   - Return admission handles.
   - Apply D6 limits at admission.
   - Add message/file result observation and parent wake behavior.

10. **Add the DuckDB plugin as a later phase**
    - Design the replayable manifest and lineage contract first.
    - Implement DuckDB materialization and recovery without introducing PostgreSQL session affinity or a second queue.