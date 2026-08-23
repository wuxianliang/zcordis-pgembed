# E — Absurd durable execution vs pg_cordis

Date: 2026-08-23 · Series: sequential research A→I · Status: **analysis evidence.** TE1 placement closed by D4 (five primitives in kernel). Working hypotheses: `2026-08-23-i-architecture-snapshot.md`.

Inherits A–D. New evidence: [earendil-works/absurd](https://github.com/earendil-works/absurd) (`sql/absurd.sql`, docs/concepts, docs/comparison, Armin Ronacher's 2025-11-03 announcement). Working assumptions **locked this turn** (do not reopen unless they conflict with A–D):

1. **Upgrade existing `jobs`/`worker()`, do not run a second queue** alongside Absurd-style tables.
2. **Both worker loci**: in-database loop *and* host SDK worker, against one claim/checkpoint primitive.
3. **Checkpoints are log events / folds**, not a second source of truth (B's session log stays unique SoT).

---

**Key tradeoffs at a glance** (full analysis below):

- **TE1** — Placement: kernel primitive vs plugin vs split surface (still open).
- **TE2** — Jobs upgrade shape: extend pg-agent `jobs` in place vs replace with `absurd.*` function names vs a new pg_cordis catalog that absorbs both.
- **TE3** — Checkpoint encoding: first-class log event kinds vs projection-only vs workspace-adjacent rows.
- **TE4** — Sleep/await-event: kernel wait registrations vs `pg_cron` + jobs vs plugin.
- **TE5** — Dual worker: one claim protocol, two executors vs two protocols.
- **TE6** — Vendor `absurd.sql` vs re-implement the five primitives on the upgraded jobs path.

---

## What Absurd is

Absurd is **Postgres-native durable execution**, not a database extension and not a Temporal-class cluster. The engine is one SQL file (`sql/absurd.sql`) that installs the `absurd` schema plus per-queue tables. SDKs (TypeScript ~2k lines, Python, experimental Go) are thin: they pull work, run ordinary functions, write checkpoints. Armin Ronacher's announcement states the motive explicitly: agents resurrect the old durable-execution problem, and he wanted that **with just Postgres**, no extra service.

Building blocks (docs/concepts + schema header):

| Name | Role |
|---|---|
| **Task** | Named unit of work (`task_name` + JSON params) on a queue |
| **Step** | Named checkpoint; successful result is persisted and never re-executed |
| **Run** | One attempt; retries create a new run that **replays checkpoints** |
| **Queue** | Namespace: `t_` tasks, `r_` runs, `c_` checkpoints, `e_` events, `w_` waits (`i_` idempotency on partitioned queues) |
| **Worker** | Pulls with a **time-limited claim**; claim extends on checkpoint write; expired claims fail the run (`$ClaimTimeout`) |
| **Sleep** | Suspend + `available_at` in the future (`schedule_run`) |
| **Await event** | Suspend until named event; **first emit wins** (immutable cached payload); optional timeout |
| **Retry** | Task-level, not step-level: `fixed` / `exponential` / `none` |
| **Cancel** | `maxDuration` / `maxDelay`; running code notices at next checkpoint/heartbeat |

Core SQL surface (not exhaustive): `create_queue`, `spawn_task`, `claim_task` (`FOR UPDATE SKIP LOCKED`), `complete_run`, `fail_run`, `schedule_run`, `set_task_checkpoint_state`, `get_task_checkpoint_states`, `await_event`, `emit_event`, `cancel_task`, `retry_task`. Test clock via GUC `absurd.fake_now`. Optional `pg_cron` for partition/cleanup.

What it is **not**:

- Not deterministic-replay of workflow source (Temporal). Code *around* steps may re-run; only step bodies are skipped via stored JSON.
- Not a push/HTTP control plane (Inngest). Pull only.
- Not a C extension. Drop-in SQL, like pg-agent's `v2/*.sql`.
- Not SQL-first *execution*: step closures run in the host language. SQL owns queue, lease, checkpoint, sleep, event.

Ronacher's agent recipe is one looping step (`iteration`, `iteration#2`, …) that returns *deltas* (new messages), not the whole transcript — crash at step 5, replay 1–4 from checkpoints. That is durable ReAct, not pg-agent's current "one PL/pgSQL `rlm_loop` holds the session until `final_answer`."

## Mapping onto A–D

**A (plugin contract / pgembed).** pg-agent already has the *queue* half: `jobs` + `worker()` + `FOR UPDATE SKIP LOCKED` (`v2/pg_agent_functional.sql:33–47,465–476`). It does **not** have checkpoints, leases-with-heartbeat, sleep, or await-event. A's obstacle 4: long-running loops pin sessions. Absurd's whole point is to *unpin* them. Packaging: Absurd is SQL files, which matches A's T5 opinion (iterate as SQL schema, promote hot paths later) — but copying `absurd.sql` as-is would install a **second** job engine, which this turn forbids.

**B (log + projection).** Absurd's `c_` table is a second append-only history of *execution* (step name → JSON). B forbids a second SoT. This turn locks: checkpoints **are log events or folds of the log**, not `c_` as independent truth. A fast lookup table (like DSH projection-cache rows) may exist as a fold shortcut — "a row is never authoritative" (B). Sleep/await-event wakeups belong in the log as well (`spawn/start` already proposed in C/D), or they become undeclared workspace.

**C (CodeAct + RLM).** TC2 already asked for mixed sync/async spawn; async children via `jobs`/`worker()` had no checkpoints, so a crashed child restarts from scratch. Absurd-style steps are exactly the missing piece for async RLM trees and for the paper's "blocking sequential sub-calls" pain. Dual worker locus (this turn) also answers C's "host `ReactLoopAgent` vs in-database `rlm_loop`" — both become *claimers* of the same durable run, which is D's P5 multi-writer in another costume.

**D (isolation).** A host worker claiming a run must hold that run's **grants** (P1/P8). Claim-timeout overlap (Absurd documents brief dual execution when a lease expires) is an isolation event: two workers must not both retrieve under the same grant without idempotency. Sleep/await-event are natural carriers for "wait for the user / wait for a tool host" without holding a PG session (and without holding grants on a live backend).

## Upgrade path for jobs (not a second queue)

pg-agent `jobs` today:

```
job_id, job_type, payload, status PENDING|RUNNING|DONE|ERROR,
priority, run_id, result, error_msg, worker_id, created_at, completed_at
```

`worker()` claims one PENDING row, `EXECUTE`s the `job_handler` regproc, writes DONE/ERROR. No attempt counter, no lease expiry, no checkpoint, no sleep, no events. Agent loops (`h_agent_run`, `h_rlm_run`, `h_hybrid_run`) are themselves handlers — so the "durable unit" is the *entire* `rlm_loop`, not a step.

Upgrade means **one** catalog that grows toward Absurd's primitives while keeping the COMMENT/`job_handler` registration (A's T7: one metadata vocabulary, `invocation` discriminator). Opinion of the mechanical mapping (not a decision to copy names):

| pg-agent `jobs` | Absurd | After upgrade (opinion) |
|---|---|---|
| `jobs` row | `t_` + current `r_` | one job = one task; attempts = runs |
| `job_type` → `handlers` | `task_name` → SDK registry | keep COMMENT/`job_handler` (and session-select tools stay on the other invocation model) |
| `worker()` SKIP LOCKED | `claim_task` + lease | add `claim_expires_at`, heartbeat/extend on checkpoint |
| `result` / `error_msg` | `complete_run` / `fail_run` | keep; add attempt/backoff |
| (missing) | `c_` checkpoints | **do not add as SoT** — emit log events; optional fold table |
| (missing) | `schedule_run` sleep | `available_at` on the run/job row |
| (missing) | `e_`/`w_` events | named waits; first-emit-wins |
| `run_id` text FK to agent | task headers / correlation | D's grant id + session log id as headers (Absurd already has `headers`) |

*Opinion:* do not `CREATE SCHEMA absurd` next to `jobs`. Lift `jobs`/`worker()` in place (or replace the table once, same logical queue). Vendor-importing `absurd.sql` as a sibling engine violates the no-second-queue lock even if we never start two workers.

## Dual worker locus

Locked: **both** in-database loops and host SDK workers.

Shared protocol (opinion): whatever claims a run must speak the same verbs — `claim`, `checkpoint` (→ log append), `sleep`, `await_event`, `complete`, `fail`, `heartbeat`. The in-database `rlm_loop` becomes a *claimer that happens to be SQL*, not a session-pinning while-loop that owns the world. A host `ReactLoopAgent` becomes a *claimer that happens to be TypeScript*, writing the same log events DSH already calls `step/start`/`step/end`.

Implications:

- **Lease overlap** is real (Absurd is honest about it). Steps that call LLM or HTTP must be idempotent (Absurd: derive keys from `taskID`). pg-agent's `http_call_llm` is not. Dual locus makes this a contract clause, not an SDK nicety.
- **TEMP VIEW `session_scope`** (A/C) does not survive a host worker or a later claim on another backend. D already said run-scoped execution must not equal PG session identity. Dual locus *forces* that.
- **SQL-first plugin hypothesis** (A) still holds for *plugin bodies* (tools, folds). It does not require the *loop* to pin a backend. Dual locus is how C's host vs in-DB loops coexist without two logs.

## Checkpoints as log events

Locked: not a second SoT.

DSH already has the vocabulary: `step/start`, `step/end`, `tool/call`, `tool/result`, `assistant/message` with `sourceEventSeqs`. Absurd's `ctx.step('process-payment', fn)` is "run `fn` unless a committed checkpoint named `process-payment` exists." That is a **fold plus a skip rule**, not a parallel truth:

- **Write path:** completing a step appends a log event (kind TBD: `step/checkpoint` or reuse `step/end` + payload). The payload is the step's return JSON — Ronacher's "store deltas, not the full transcript" for agent loops.
- **Read path:** a deterministic projection `checkpoints_as_of(run, seq)` (B tier 1) yields `name → payload` for names whose events are still on the surface (compaction/`surfaceOp` applies). Resume = look up the fold, skip named steps.
- **Optional cache:** a `(run_id, step_name, seq, payload)` table as projection-cache, invalidated like DSH `stateVersion` / watermark — never writable except by the fold.

Sleep and await-event: either log kinds (`run/sleep`, `run/await`, `run/wake` with event payload) that the claimer interprets, or they leak into undeclared workspace. *Opinion:* log them. Events themselves (`emit_event`) are not conversation history; they are **control-plane facts**. B's TB6 said UI/request state stays in the log so replay is complete. Wake payloads belong there too. First-emit-wins is a uniqueness constraint on `(queue, event_name)` that can sit next to the log as an index — the *payload* still appears as a log event when first emitted.

Conflict with C/D's **workspace** tier: env/`rlm_vars` stays workspace (cannot replay by re-executing model SQL). Checkpoints *can* replay (they are pure stored JSON). That is why they belong on the log, not in workspace.

## Kernel-shaped vs plugin-shaped (research — not a decision)

Placement stays open. The split below is an **opinionated map** of what *would have to be true* for each answer, given the three locks above.

**Looks kernel-shaped** (without these, C's async spawn and D's wait-without-pinning have no substrate):

- Claim + lease + SKIP LOCKED (already proto-kernel in `worker()`)
- Task-level retry / backoff / cancel
- Step skip-if-present, implemented via the log fold
- Sleep (`available_at`)
- Await/emit named events (first-write-wins)
- One claim protocol both SQL loops and host workers speak

**Looks plugin-shaped** (product, not the contract):

- habitat web UI
- `absurdctl` / per-queue partitioned storage / `pg_cron` cleanup recipes
- Language SDKs as *one* host worker implementation (the protocol is kernel-shaped; npm `absurd-sdk` is not)
- User-defined workflow graphs that are neither CodeAct nor RLM (order-fulfillment example) — those register as tasks/plugins on the upgraded jobs path
- Ronacher's looping `iteration#N` agent is a **paradigm policy** (C: paradigm = plugin over loop kernel), not a new kernel

**Looks like a bad import:**

- Installing `absurd` schema beside `jobs`
- Treating host-only step closures as the only legal executor (contradicts dual locus + SQL-first tools)
- Treating `c_` as authoritative (contradicts B + this turn)

*Opinion (not a decision):* the five primitives (claim, checkpoint-via-log, sleep, event, retry) want to live with the loop kernel C already described — the same place `worker()` lives today — because every paradigm plugin will need them. Habitat, extra queues-as-product, and language SDKs want to be pg_cordis plugins or host tools. Whether those primitives are "the pg_cordis extension" vs "SQL catalog the extension loads" is A's still-open T5, not this document's to freeze.

## Key tradeoffs (opinion, not decision)

**TE1 — Placement.** Options: (a) all five primitives in the kernel; (b) entire durable engine as an optional plugin; (c) split: primitives with the loop/jobs kernel, product/UI/SDK as plugins. Analysis: (b) makes async RLM and "wait for user" optional — then the default path stays session-pinning `rlm_loop`, and A's obstacle 4 never closes. (a) dumps habitat and partitioned-queue policy into the kernel, contradicting "plugins are how richness lands" (A). (c) matches how Absurd itself is already split (SQL engine vs SDK vs habitat) *and* the no-second-queue lock. *Opinion: (c), with the kernel/plugin cut drawn at "can a CodeAct/RLM run resume after the backend dies," not at "do we like Temporal." Placement remains officially open.*

**TE2 — How to upgrade jobs.** Options: (a) ALTER `jobs` in place (lease, attempts, `available_at`, wait columns); (b) replace with `absurd.*` names/tables, migrate rows; (c) new pg_cordis catalog, deprecate both names. Analysis: (b) is a second queue during migration and imports checkpoint-as-table SoT. (a) preserves COMMENT handlers and `h_rlm_run`. (c) is cleaner long-term but largest rewrite. *Opinion: (a) now, (c) only if the in-place columns become a mess — do not do (b).*

**TE3 — Checkpoint encoding.** Options: (a) new log kinds; (b) projection-only (derive skip-set from existing `tool/result`/`step/end`); (c) workspace-adjacent cache. Analysis: (c) is a second SoT. (b) under-specifies sleep/await and Ronacher's named steps (`iteration#3`). (a) is explicit and compaction-aware (`surfaceOp`). *Opinion: (a) for named steps + sleep/wake; (b) as a compatibility fold over old `agent_steps` during migration.*

**TE4 — Sleep / await-event implementation.** Options: (a) wait registrations on the job/run row (Absurd `w_`/`e_`); (b) `pg_cron` + re-enqueue; (c) plugin. Analysis: (b) exists in pgembed but is coarse (minute granularity, another daemon). (c) makes "wait for email confirmation" optional infrastructure. (a) is the substrate host and SQL workers both need. Event first-write-wins needs a uniqueness constraint — that can live as a small table **indexed from log events**, not as a SoT. *Opinion: (a) as primitive; `pg_cron` only for Absurd-like partition cleanup (plugin/ops).*

**TE5 — Dual-worker protocol.** Options: (a) one claim protocol, two executors; (b) SQL loop uses in-session execution, host uses Absurd-like claims (two protocols). Analysis: (b) re-creates two queues in spirit. (a) is the lock. Cost: in-database `rlm_loop` must learn to **yield** (checkpoint + release claim) instead of looping until final. That is the actual design work. *Opinion: (a), and treat yield-able `rlm_loop` as the CodeAct/RLM change, not a new product.*

**TE6 — Vendor vs reimplement.** Options: (a) copy `absurd.sql` and wrap; (b) reimplement the five primitives on `jobs`; (c) depend on absurd as an extension-like SQL module (`CREATE EXTENSION` from their file, if they ever ship one). Analysis: (a) fights the no-second-queue lock and checkpoint-SoT. (c) is a distribution choice (A T5 / pgembed packaging) once the contract exists. (b) is more work but keeps COMMENT plugins, log-as-SoT, and grants. Absurd remains the **reference implementation to steal semantics from** (lease, first-emit-wins, claim timeout, step naming). *Opinion: (b) for the contract; (c) later iff packaging wants a pinned SQL module — still one logical queue.*

## Residual open questions

- **Yield semantics for `rlm_loop`.** After this turn, the loop must claim → fold → LLM → maybe tool → checkpoint → **release** (or extend lease). Where is the yield boundary — per LLM call, per tool, per user-await? Interacts with C's turn/step enclosure.
- **Idempotency of `http_call_llm`.** Absurd requires step-level idempotency because overlapping claims happen. pg-agent does not. Dual workers make this mandatory. How: request hash in the log, or provider idempotency keys derived from `(run_id, step_name)`?
- **Event namespace vs D grants.** Is `shipment.packed:order-42` globally unique per queue, or grant-scoped so two tenants cannot collide or snoop? First-emit-wins is a security boundary if names are guessable.
- **Who may emit.** Host worker, SQL tool, user-facing API — all three show up in Absurd's docs. Under D, emit is a capability. Which grant?
- **Checkpoint payload size.** Ronacher stores message *deltas*. pg-agent stores clipped observations (`rlm_clip` 4000) with full text in env. If checkpoints are log events, B's compaction/`surfaceOp` must apply; env remains workspace. Exact split of "delta in log" vs "full blob in workspace" is unstated.
- **Claim timeout vs D budget.** Absurd `$ClaimTimeout` fails the run; D treats budget overrun as isolation. Same event, two names?
- **Habitat / absurdctl.** If TE1(c), they are plugins or out-of-tree tools. Needed for v0 observability, or is `run_state()` + log query enough?
- **Placement freeze.** TE1 remains open on purpose. A later turn should freeze it only after the yield-able loop sketch exists — otherwise "kernel" means nothing operational.

Cross-cutting with A–D: still-open extension vs SQL-catalog (A T5); log event vocabulary growth (B TB1(c), C TC4); grant-carrying workers (D P5/P8). Absurd does not change those questions; it names the execution engine they have been missing.
