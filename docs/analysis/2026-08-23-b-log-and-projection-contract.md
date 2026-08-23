# B — Log and projection contract on pg_cordis

Date: 2026-08-23 · Series: sequential research A→I · Status: **analysis evidence.** Decisions and working hypotheses: `2026-08-23-i-architecture-snapshot.md`. Log SoT frozen; B's "everything else is a projection" is amended by the workspace tier (snapshot §3).

Evidence base (read-only): `deepseek-harness` (persistence plane + projection framework + event model), `Zleap-Agent` (database-centric product + memory graph), `pg-agent` (in-database log precedent), `pgembed` (retrieval substrate), `zcordis-pgembed/docs/` papers. Inherits A's findings; does not reopen them.

The four governing requirements for B, restated:

1. **Replace DSH persistence with the database** — abandon the file form (JSONL artifacts, SQLite files as the store) while **keeping the information content** of the session log.
2. **Projection is the cognitive layer** — a raw log is unreadable; the database-centric role (Zleap's evidence, not Zleap's inventory) is projection for **humans and agents**.
3. **Log + projection is itself a pg_cordis contract** — new plugins may touch the log layer and the projection layer; plugins are not assumed to be stateless tools.
4. **The session log stays the unique SoT** — everything else (including anything inherited from Zleap) is a projection of the log or of retrieval, never a second source of truth.

---

**Key tradeoffs at a glance** (full analysis in the tradeoffs section):

- **TB1** — Log storage shape: single append-only events table vs typed per-kind tables vs typed envelope + JSONB payloads.
- **TB2** — Crash boundary: event-granularity commits + repair closers (DSH semantics) vs turn-granularity transactions.
- **TB3** — Invariant enforcement: producer convention vs DB triggers vs layered (structural constraints + append-path validator).
- **TB4** — Projection tiers: pure deterministic folds only vs anything goes vs two explicit tiers (deterministic + model-backed).
- **TB5** — Projection freshness: synchronous in-transaction refresh vs async eventual vs per-tier.
- **TB6** — Log-only state: keep UI/request state as log content vs log carries only model-surface events.

---

## Session log as SoT in Postgres (content preserved, files abandoned)

### What "information content" concretely is

The content that must survive migration lives in `packages/core/session/src/types.ts`: the **merge-extensible `SessionEventMap`** — "The merge-extensible, append-only source of truth for an agent interaction. Message history is derived from this log. Every event is lossless JSON and sequence numbers stay contiguous."

Core vocabulary (each an entry in `SessionEventMap`):

| Event kind | Payload | Role |
|---|---|---|
| `turn/start` / `turn/end` | `{turn}` / `{turn, reason}` | durability/replay boundary (see below) |
| `step/start` / `step/end` | `{turn, step}` | one model call + its tool executions |
| `user/message` | `UserMessage` | human prompt, synthetic `agent.inject()` context, or goal continuation — `source` distinguishes |
| `assistant/chunk` | `{turn, step, chunk}` | raw stream chunk — "token-level replay fidelity" |
| `assistant/message` | `{turn, step, message, usage?, interrupted?}` | assembled message + token accounting + interrupted-prefix marker |
| `tool/call` | `{turn, step, callId, name, arguments}` | raw unparsed `arguments` JSON string |
| `tool/result` | `{turn, step, message, error?, meta?}` | model-facing result + tool-private opaque `meta` |
| `todo/write` | `{todos}` | whole-list snapshot; "log-only UI state; never derived history" |
| `request/header` / `request/context` | `EpochHeader` / `RequestContext` | full next-request header; route metadata |
| `session/end-seed` | `{}` | seed/live boundary; "Session's constructor is the only legitimate writer" |

Envelope fields on `SessionEvent`: `type`, monotonic `seq`, `time`; conditionally `sourceEventSeqs` (which earlier events this one cites), `surfaceOp` (`'append'` or `{op:'replace', start, end}` — compaction replaces surface nodes), and `ignorable?: true` (forward-compat protocol: a reader meeting an unrecognized type **without** the marker MUST refuse reconstruction rather than silently drop it). Plus plugin extensions: `SessionEventMap` is interface-merged by at least `compaction/compaction/src/types.ts`, `core/agent/src/types.ts`, `core/tools/src/types.ts`, `feedback/command-feedback/src/index.ts`, `goal/goal/src/domain.ts`, `hooks/hook-protocol/src/types.ts`, `interaction/commands/src/types.ts`, `experimental/agent-team/src/types.ts`. **The vocabulary is already plugin-extensible in DSH — requirement 3's log-layer premise is not hypothetical.**

The turn is the durability boundary: "Every session event lives inside a turn" (`.agents/notes/archived/architecture/2026-06-15-turn-enclosure-invariant.md`), enforced producer-side by the `dsh-session` invariant package — "Strict sequence growth, turn/step enclosure, and same-step tool call/result pairing" (`.agents/notes/implemented/architecture/2026-07-19-package-invariant-runtime-contracts.md`).

### What dissolves, what migrates

| DSH file-form machinery | Postgres replacement | Verdict |
|---|---|---|
| zstd JSONL framing, torn-tail discard on load (`session-persistence-jsonl/src/format.ts` `scanLog`; `readPrefix` in `session-persistence-jsonl/src/index.ts`) | WAL atomicity — a committed row is whole | **dissolve** |
| crash-safe materialization: temp file + `link()` + directory fsync (`materializePosix`/`materializeWin32`, `session-persistence-jsonl/src/index.ts`) | not applicable | **dissolve** |
| `EventRow`/`SessionRow` physical schema, `SCHEMA_VERSION = 17`, app id `0x44534850`, `synchronous FULL`, journal-mode negotiation (`session-persistence-sqlite/src/schema.ts`) | plain tables + migration discipline; durability is server config | **migrate ~1:1 (opinion)** — DSH's own columns already sketch the table: `seq, type, time, data, source_event_seqs, surface_op, ignorable` and `id, version, created_at, cwd, parent_session, seed_length, origin, incarnation, revision, delegation_depth, agent_preset` |
| `PersistenceCoordinator` write-behind batching (`DEFAULT_WRITE_BATCH_MAX_DELAY_MS`, ~200 ms per A's survey; `session-persistence/src/coordinator.ts`) | WAL + group commit | **dissolve** |
| torn-tail repair + synthetic closers on load (`interruptedTurnClosers`, `packages/core/session/src/repair.ts`) | transaction discipline — but see TB2; closers may remain as data | **partially migrate** |
| per-request durability checkpoint (`session-checkpoint-policy` package) | commit/`synchronous_commit` policy knob | **migrate as policy** |
| opaque revision tokens (`SessionPersistenceSnapshot.revision`) | seq high-water + per-store change token (LSN or counter) | **migrate** |

### Fate of the `SessionPersistence` API (A's open question, answered as opinion)

From `packages/session/session-persistence/src/index.ts`:

- **dissolve**: `locate`, `supportsRawArtifacts`, `readRaw` — there is no artifact; verbatim export becomes `COPY` of the log table (opinion). 
- **become table ops**: `create` → `INSERT` session row; `append` → `INSERT` events, durability = commit return; `list`/`listSnapshots` → metadata `SELECT` + change tokens.
- **become trivially strong**: `readFrom(id, fromSeq)` — the watermark-read primitive DSH documents for "a persisted projection cache folding only the tail past its checkpoint" — is a native `WHERE seq >= $1` seek in PG (DSH notes SQLite seeks by seq but JSONL must parse the whole artifact; PG always seeks).
- **remain kernel/host notions**: `load`/`inspect`'s cold-recovery and unpublished-reservation semantics, and `prepare` (resume reservation) — host-side state machine concerns, not table concerns.
- **remain contract seams**: what may enter the log (append validation), watermark reads, change tokens. The rest of the API was an emulation of durability; PG owns that now.

### pg-agent precedent and its gaps

`agent_steps` (`v2/pg_agent_functional.sql`): `(run_id, seq bigserial, kind, payload jsonb, created_at)`, PK `(run_id, seq)`, kinds `llm | tool | final | error`, written only through `emit_step()`; `run_state()` is a STABLE fold deriving status/steps/answer/error with no stored status column. This is the shape — but the content is thin next to DSH: no turn/step enclosure, no stream chunks, no `surfaceOp`/provenance, no `ignorable` forward-compat, four kinds vs DSH's dozen-plus. And `rlm_vars` (`v2/pg_agent_rlm.sql`, with `rlm_children`) is workspace state in a **separate writable table, not log-derived** — a live second SoT inside the PG precedent itself. Evidence for what happens without a contract, not a model to copy (picked up again under C).

### Invariants (A's open question, answered as opinion)

DSH enforces at the producer (`Session.append` throws on non-JSON-serializable data; invariant package registers enclosure checks with `ctx.invariants`), deliberately: "The rule is intentionally producer-enforced and dev-checked rather than reader-tolerated: a future backend (SQLite/WAL) inherits the same clean boundary for free" (turn-enclosure note). In PG the split should be layered — structural invariants as constraints, semantic ones as an append-path validator — argued as TB3 below.

## Projection as cognitive layer (human + agent)

The log is for forensics and replay; **nobody reads it raw**. Every consumer — human or agent — reads a projection. DSH already says so structurally: "Message history is derived from this log" (`deriveMessages()` in `packages/core/session/src/index.ts`, switching purely on event type via `deriveEventMessage`, `packages/core/session/src/surface.ts`).

**Human-facing projections.** DSH: `sessionStats` (`packages/session/session-stats/src/projection.ts`) — a pure fold of step boundaries, stream chunks, tool call/result pairs, and assembled messages into `turns/steps/llmMs/toolMs/ttftMs/decodeTokens` whole-log figures, with careful rules (count `step/end`, not `assistant/message`, because "it is the step lifecycle authority"). Zleap: the web surface — `packages/web/app/api/memory/route.ts`, `packages/web/app/api/chat/conversation/route.ts`, `packages/web/app/api/chat/trace/route.ts`, `packages/web/app/api/chat/approval/route.ts` — plus the inspector text feed (`listMemoryInspectorText()`, `packages/agent/src/engine/index.ts`).

**Agent-facing projections — the cognitive function.** The loop itself consumes projections:

- **Prompt reconstruction**: `fold_rlm_messages` (`v2/pg_agent_rlm.sql`) rebuilds the `messages` array from `agent_steps` every iteration before `http_call_llm` — the log is unreadable to the model; the fold is its reading.
- **Compaction**: DSH's compaction brackets with `surfaceOp {op:'replace'}` citing shadowed seqs (compaction's own event kinds, `packages/compaction/compaction/src/types.ts`); Zleap's `session_entries` compaction rows carry fold metadata (foldStart/foldEnd, tokensBefore/After — `packages/agent/src/compaction/service.ts`, written via `packages/agent/src/persistence/runBridge.ts`).
- **Memory retrieval**: Zleap's `CoreStore.recall()` — four paths (vector `embedding <=> $v` cosine, lexical `tsvector` + `plainto_tsquery`, entity name match, entity-shared graph hops) fused by **Reciprocal Rank Fusion** (`mergeRrfRankings`, `DEFAULT_RRF_K = 60`, `packages/store/src/core/rrf.ts`), in `fast` (no LLM) or `precise` (LLM reranker) modes; hits are injected into the model context as a synthetic `listMemory` tool-result message **before** replayed history (`listMemoryRuntimeMessages`, `packages/agent/src/engine/index.ts`). Projection is not reporting — it is how the agent thinks.

**DSH's projection framework is the formal precedent.** `packages/session/session-projection/src/index.ts`: plugins register `ProjectionDefinition` units — `key`, `stateSchema`, `init()`, pure synchronous `apply(state, event)` (async forbidden: it "would tear the carriers' consistency cut"), optional client `wire.view`, and `stateVersion` for cache invalidation. The registry eagerly drives every committed event through every unit, keeps per-session watermark cells, emits a change feed `(session, key, value, seq)`, serves `ProjectionSnapshot` with a shared `asOfSeq` consistent cut, and persists checkpoint rows `(sessionId, key, ver, seq, val)` — "A row is never authoritative, only a fold shortcut" (`session-projection-cache` persists them) — and the RFC's keystone for requirement 4 says it outright: *state is always computed, never logged*. Cold reads use a read ladder: zero-I/O `viewCheckpoint`, then `restore()` seeded from usable rows plus the tail from `readFrom(restoreFloor(...))`, with version-mismatch or shrunk-log detection forcing a full refold. Design authority: `.agents/notes/proposed/architecture/2026-07-27-session-projection-and-command-log.md`.

**Query and trace are projections too.** `packages/session-query/session-query/src/` ships `SessionQueryEngine` (`ctx.sessionQuery`): `listSessions/readSession/readSurface/readEvent/listEvents`, `filterSessions/filterEvents`, `traceSession` (ancestor/descendant lineage), `traceEvent` (replacement chains over `surfaceOp`), abstract `searchSessions/searchEvents`; `SessionCorpus` resolves live-preferred sources strictly through the `SessionPersistence` API — never raw files. Its only concrete backend, `session-query-sqlite`, maintains a second-file FTS5 index (`persisted_docs`, `search_state.global_generation`, reconcile-on-search — `packages/session-query/session-query-sqlite/src/schema.ts`) — in Postgres this could collapse into `tsvector` + GIN on the log itself (opinion): the query layer and the search index would stop being separate artifacts.

**Retrieval-grade projections are already bundled.** pgembed ships the substrate (`pgbuild/Makefile`): pgvector 0.8.2 + vectorchord 1.1.1 (semantic), psql_bm25s (BM25 lexical), age (entity graph), timescaledb 2.27.1 (temporal rollups). Zleap proves the pattern in production shape on its own store (ivfflat + tsvector + entity hops + RRF, `packages/store/src/schema.ts` / `packages/store/src/core/schema.ts`).

*Opinion*: projection should be treated as a **first-class interface with two audiences**, not an output format. Humans supervise through it; agents act through it (prompt assembly, memory, compaction are all projections). That is precisely why it must be contract, not convention — next section.

## Log + projection as pg_cordis plugin contract

Requirement 3 says new plugins may touch both layers. DSH already demonstrates both touch-points; the contract needs somewhere to accept them as first-class (what that somewhere concretely is stays with A's T1/T2):

**Log layer — vocabulary + writer scope + validation.**
- *Vocabulary registration*: plugins extend `SessionEventMap` by interface merging (eight-plus packages cited above). The pg_cordis analog: registry metadata declaring a plugin's event kinds, mirroring A's T1/T2 metadata vocabulary.
- *Forward compatibility*: the `ignorable` marker protocol (unknown + unmarked → refuse; unknown + marked → skip) is a log-layer contract clause that costs one column.
- *Writer scope*: DSH already scopes per type — `session/end-seed` has exactly one legitimate writer; the turn-enclosure note's rule ("a plugin that records an event outside a turn fails loudly in dev instead of silently losing data") is enforced by **registered invariant checks** (`dsh-session/invariant` + `ctx.invariants`). The pg_cordis analog: an append-path validation seam every writer passes through (TB3).
- *Whole-value rule*: "a state-carrying log event MUST carry the complete post-change state, never a bare delta" (`session-projection/src/index.ts` header) — a log-layer style constraint that keeps every fold trivially cheap.

**Projection layer — registration, state, staleness, tiers.**
- *Registration as effect*: DSH's `register()` rides the caller's fiber; unloading a domain plugin removes its key and "clients read it as capability absence". The natural PG analog would be registry rows + transactional DDL — unload as deregistration + cache drop, which A's T3 argued PG gives natively.
- *Versioned checkpoints*: `stateVersion` refusal (re-registering a key at a different version throws) + `(key, ver, seq, val)` rows would generalize naturally to a projection-cache table with the same discard-on-mismatch rule.
- *Two tiers — the load-bearing addition beyond DSH*. DSH constrains units to pure synchronous folds. But Zleap's memory graph is **not** a pure fold: `ingestFragment()` (`packages/store/src/core/extract.ts`) calls an LLM extractor over message fragments, batches embeddings, dedups by `content_hash`, runs `recall()` for candidates, then an LLM **reconciler** decides `skip / keep_both / replace_old / keep_old` and sets supersedes chains. That cannot live inside DSH's projection framework at all — yet it is the single most "cognitive" projection in any of these repos. *Opinion*: pg_cordis needs both tiers explicit — **deterministic folds** (SQL functions/views; synchronous; consistent cuts, DSH-style) and **model-backed projections** (async, checkpointed, versioned; refreshed by workers; staleness declared). A contract that only accepts pure folds re-excludes Zleap's best ideas and quietly violates requirement 1 of A (rich plugins must land somewhere).
- *Plugins are not stateless*: projection plugins own state (watermark cells, checkpoint rows, indexes, materialized views); log plugins own vocabulary and invariants. Both are stateful citizens — consistent with A's finding that the richness is in the wiring contract, not the tool count.

*Opinion*: the log-layer contract is small (vocabulary, writer scope, validation, watermark reads, change tokens). The projection-layer contract is where pg_cordis earns its keep, and it is the plugin category A left open ("is `session-projection` a pg_cordis plugin category?") — answered here: **yes, with two tiers**.

## What of Zleap to drop vs keep as projection ideas

Zleap's store (`packages/store/src/schema.ts`, ~30 tables; migrations in `packages/store/src/migrate.ts` over a `pg` Pool, bootstrapped under `pg_advisory_lock` (`packages/store/src/store.ts` schema lock)) is the working evidence that the database-centric agent role is projection and retrieval — but founded on a **product schema with the loop in Node** (`packages/agent/src/engine/index.ts`, `packages/agent/src/workspaces/turnLoop.ts`, `packages/agent/src/persistence/runBridge.ts` bridging runtime `AgentEvent`s into durable rows). pg_cordis re-founds the same ideas on the log SoT. (Deployment note for A/D: the desktop ships its own Postgres tarball resolved by the Tauri launcher — `packages/desktop/src-tauri/src/lib.rs`, `ZLEAP_POSTGRES_BUNDLE` — a bundle, not the pgembed attested-wheel path.)

**Drop** (from pg_cordis's core, per requirement 4 — opinion, not a decision about Zleap, which keeps them as its product):

- The product inventory as data model: `avatars`/`avatar_versions`, `spaces`/`space_versions`, `capability_definitions`/`space_capability_bindings`/`capability_snapshots`, `skill_definitions`, `model_configs`, `mcp_servers`/`mcp_tool_definitions`, `scheduled_tasks`/`scheduled_task_runs`, `threads`, `gateway_integrations`. Product concerns — canonizing them would contradict pg_cordis (per B guidance, do not insist on Zleap's inventory).
- The second-SoT pattern: `runs`/`works`/`work_steps`/`tool_calls` written directly by `runBridge.ts` from runtime events (an independent durable model of the same history the conversation log records), `agent_memory` (a separate people-memory store), `runtime_cache_entries`. Under requirement 4 these can only be folds of the log or retrieval projections — **never independently writable truth**.
- The Node loop owning persistence timing (`beginReply`/`endReply` write points — `RunPersistenceBridge`, `packages/agent/src/persistence/runBridge.ts`). Under pg_cordis (requirement 4) the loop appends to the log; everything else derives.

**Keep as projection ideas** (cognitive value already proven):

- **Four-path recall + RRF fusion** (`packages/store/src/core/rrf.ts`, `CoreStore.recall` in `packages/store/src/core/types.ts`; path SQL in `packages/store/src/store.ts`) — the retrieval-projection pattern for agents, mapping onto pgembed's pgvector/psql_bm25s/age substrate almost column-for-column.
- **The `source/event/entity` graph with provenance** (`packages/store/src/core/schema.ts`): `content_hash` idempotency, `supersedes` chains, reconciler decisions, importance/confidence, `event_entity` edges with role/weight — a memory projection that resolves its own conflicts instead of blindly appending.
- **Compaction entries with fold metadata** (foldStart/foldEnd, tokensBefore/After) — human-auditable compaction as log-referencing projection.
- **Memory dream** (`runMemoryDreamNow`, `packages/agent/src/engine/index.ts`; scheduling in `packages/agent/src/memoryDream.ts`) — scheduled background projection maintenance (extraction of impressions/experiences), plus refresh triggers (`EVENT_REFRESH_TRIGGER_MESSAGES = 30`, `EVENT_REFRESH_TRIGGER_TOKENS = 10_000`, `engine/index.ts`).
- **`listMemory` synthetic tool-result injection** — feeding a projection to the model as a tool result placed before replayed history: the cleanest existing pattern of projection→agent consumption.
- **Human surfaces**: trace/approval/memory endpoints and the inspector — the human half of the cognitive layer.

## Key tradeoffs (opinion, not decision)

Analyzed in turn; each ends with an opinion. None is a decision; the extension-vs-plugin split from A remains open.

**TB1 — Log storage shape.** Options: (a) single append-only events table, JSONB payloads (pg-agent shape); (b) typed per-kind tables; (c) typed envelope + JSONB payloads, extension kinds free-form. Analysis: (b) gives the richest constraints but freezes the vocabulary — direct contradiction with the merge-extensibility evidence; every plugin event kind would be a DDL event. (a) is proven and flexible; payload queries lean on JSONB operators. (c) keeps indexable/invariant-bearing columns typed and lets plugin kinds exist without DDL. *Opinion: (c) — which in practice is (a) plus the envelope columns DSH's own `EventRow` already proved sufficient (`seq, type, time, data, source_event_seqs, surface_op, ignorable`); per-kind views then become the cheapest deterministic projections.*

**TB2 — Crash boundary.** Options: (a) event-granularity commits + repair closers (preserve DSH semantics: an interrupted final turn keeps its real events and gains a synthetic `turn/end {interrupted}`); (b) turn-granularity transactions (a crash rolls the whole turn back; torn tails become impossible; closers unnecessary). Analysis: (b) is the PG-unique simplification and tempting — but it silently discards real content (DSH even finalizes interrupted stream prefixes as `assistant/message {interrupted: true}`, content worth keeping), changes replay semantics vs DSH, and couples append latency to turn length. (a) preserves information content — the explicit B requirement — and reduces repair to a data-level step. DSH's own note predicted WAL "inherits the same clean boundary for free": the *rule* survives; only the physical repair dissolves. *Opinion: (a); revisit (b) only if append throughput ever forces batching — and note the write-behind layer that would have created that pressure has already dissolved into WAL.*

**TB3 — Invariant enforcement.** Options: (a) producer convention (DSH today: dev-checked invariants via `ctx.invariants`); (b) full DB triggers/constraints; (c) layered — structural as constraints (PK/identity contiguity, NOT NULL, JSONB validity are free), semantic (turn enclosure, call/result pairing, writer scope) as an append-path validator function, triggers deferred. Analysis: (b) fails loudly but taxes every append and makes vocabulary evolution a trigger-rewrite exercise; (a) is silent in production and trusts every writer. (c) generalizes the validation discipline pg-agent already uses at scan time (`refresh_workbench_tools()` in `v2/pg_agent_workbench_core.sql` enforces contract rules) into the write path. *Opinion: (c), with the validator as a contract seam plugins extend — the pg_cordis analog of DSH's registered invariant checks.*

**TB4 — Projection tiers.** Options: (a) pure deterministic folds only; (b) no tiers, anything registerable; (c) two explicit tiers. Analysis: (a) inherits DSH's consistency-cut guarantee but cannot host memory extraction (the LLM extractor + reconciler pipeline is inherently impure and slow) — Zleap's core value becomes unrepresentable; (b) loses the ability to promise anything about consistency or staleness. (c) prices each tier honestly: deterministic units get synchronous consistent cuts; model-backed units get async refresh, checkpointed watermarks, declared staleness. *Opinion: (c). The checkpoint machinery (`(key, ver, seq, val)` rows, version-mismatch discard, refold-on-shrunk-log) is DSH-proven and generalizes unchanged to the model-backed tier.*

**TB5 — Freshness model.** Options: (a) synchronous trigger-driven refresh inside the writing transaction; (b) all-async workers; (c) per-tier — deterministic synchronous, model-backed async. Analysis: synchronous model-backed refresh is impossible (LLM latency in the append path); all-async wastes the free consistent cut deterministic folds can have, and forces every consumer to reason about staleness even for trivial views. *Opinion: (c), with a mandatory `asOfSeq` disclosure on every projection read (DSH's `ProjectionSnapshot` pattern) so consumers choose staleness knowingly.*

**TB6 — Log-only state.** Options: (a) keep UI/request state as log content (`todo/write`, `request/header`, `session/end-seed`, compaction brackets — "log-only" events DSH deliberately logs); (b) the log carries only model-surface events, everything else in side tables. Analysis: (b) re-creates second SoTs — side tables writable outside log discipline, exactly the drift requirement 4 forbids — and loses replay fidelity of UI state; (a) makes the log heavier but replay-complete. pg-agent's `rlm_vars` is the cautionary opposite already living in the PG precedent. *Opinion: (a) — "information content preserved" includes UI and request state; side state is a projection, and projections are never authoritative.*

## Open questions for C/D

For **C** (CodeAct + RLM on pg_cordis):

- Is prompt assembly itself a projection plugin the loop consumes (`fold_rlm_messages` / `deriveMessages()` generalized), or loop-kernel? Does CodeAct need a different fold over the same log than RLM, or different event kinds?
- Compaction: plugin category or loop-internal? DSH's compaction uses `surfaceOp {op:'replace'}` citing shadowed seqs — are surface operations part of the pg_cordis log contract, or a projection-layer concern?
- `rlm_vars`/env state: fold it into a log-derived projection, or is per-run workspace state legitimately separate? pg-agent currently holds it as a second SoT — resolve where the loops live.
- Do paradigm runs share one event vocabulary (paradigm-scoped kinds) or per-paradigm logs? Affects the registry metadata design (A's T7).
- When the loop is host-side (Zleap's Node engine) rather than in-database (`rlm_loop`, `v2/pg_agent_rlm.sql`), the log-append seam becomes a client-facing writable API and pg_cordis turns multi-writer: what concurrency/ownership policy (advisory locks? serialized append transactions?) governs concurrent appenders, and is it paradigm-independent?

For **D** (isolation):

- Projection visibility: are projection tables tenant/session-scoped (RLS)? Zleap's `source` table is an isolation envelope (`agent_id/user_id/tenant_id/space_id/thread_id`; `packages/store/src/core/schema.ts`) — does that generalize to retrieval-range isolation ("project 1's code for function 1; project 2's for functions 2–3")?
- Memory-graph leakage: model-backed projections ingest from logs — **whose** logs may a projection read? Is projection registration itself capability-gated?
- Where do model-backed projections execute (worker sessions, `plsh`, host-side) such that retrieval-range isolation still holds? Ties to A's T4 deferral of dynamic code.
- Retention of the SoT itself: partitioning/TTL for cold sessions is storage policy, but deleting log partitions deletes truth. Does the isolation model need a retention-policy layer — and is *forgetting* allowed only in projections, never in the log?

Cross-cutting: migrating existing DSH JSONL/SQLite archives into the PG log (`readRaw` gives verbatim export today — is `COPY` the archive path?); projection-cache invalidation across pg_cordis upgrades (the SQL analog of `stateVersion`); a performance budget for synchronous folds living in the append path.
