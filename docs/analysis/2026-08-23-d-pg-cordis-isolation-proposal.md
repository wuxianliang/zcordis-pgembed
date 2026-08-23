# D — pg_cordis isolation: retrieval-scoped context (design proposal)

Date: 2026-08-23 · Series: sequential research A→I · Status: **analysis evidence.** Slice-bound grants signed as D5; P0 workspace tier adopted in `2026-08-23-i-architecture-snapshot.md`. Remaining D-text clauses are working hypotheses there, not a re-vote of P0–P8 wholesale.

Inherits: A (plugin contract; T4 dynamic-code deferral), B (unique-log-SoT; projection tiers; requirement-4 wording), C (TC3(c) workspace tier; TC5 blacklist caveat; spawn/budget handoffs), and the C-L4 review's five "Notes Topic D must inherit". Locked working assumptions are not reopened.

## Isolation ≠ Zleap workspace

Zleap's isolation is a **product envelope**, not an isolation model. The envelope is real and well made: `CoreScope = {agentId, userId?, tenantId?, spaceId?, threadId?}` (`packages/store/src/core/types.ts:12–18`), materialized as columns on the `source` table with a partial index over `(group_id, agent_id, kind, COALESCE(user_id,''), COALESCE(space_id,''), COALESCE(thread_id,''))` (`packages/store/src/core/schema.ts:23–27,36`). Recall is filtered by that scope chain; a consumer lives inside exactly one cell.

That is a **partition** model: scope = where you sit. It cannot express a consumer that needs *two differently-scoped reference sets at once* — which is exactly the worked example below. It also conflates two different things: ownership (whose data this is) and visibility (what this run may retrieve right now).

The broader reading, per the user guidance: **in a prompt sent to an LLM, different parts are retrieved within ranges.** A prompt is not a window onto one workspace; it is a composition — system prompt, folded history (C's TC6: prompt assembly is a projection), retrieved context, rendered tools — each part pulled from somewhere with a boundary. **Isolation is the set of ranges a consumer may retrieve from, not the cell it sits in.** Zleap itself half-acknowledges this: `listMemoryRuntimeMessages` takes `scope: 'main' | 'workspace'` (`packages/agent/src/engine/index.ts:447–452`) — two retrieval ranges inside one engine, already beyond a single envelope.

What pg_cordis keeps from Zleap: the envelope as *one possible range predicate* — a tenant/project filter is a perfectly good grant. What it drops: the workspace as *the* isolation model, plus the product inventory B already dropped. The original intent was never workspace-shaped: pg-agent retrieves context with a range; Zleap narrowed that into a product cell. pg_cordis re-widens it.

## Retrieval-scoped context as isolation

pg-agent's original intent, stated plainly: **context is retrieved by the agent, and retrieval has a range — that is isolation.** The precedents are all already in the SQL:

- **Retrieve, don't inline.** `make_rlm_user` inlines the question only when ≤ 1500 chars; beyond that the prompt merely says variables `question` (and `context`) are preset and directs the model to `env_keys()` / `env_peek` / `env_search` (`v2/pg_agent_rlm.sql:108`). Context is pulled on demand — the prompt names the range, not the content.
- **Run-scoped visibility.** The `rlm.run_id` GUC, set by `rlm_bind` (`v2/pg_agent_rlm.sql:194–213`) and saved/restored around delegation (`:365–374`), is a visibility boundary implemented as session state.
- **Session-scoped tools.** Workbench tools declare `"session_scope": "current_session"` and resolve through TEMP VIEWs only inside `pg_my_temp_schema()` (`v2/pg_agent_workbench_core.sql:2,12–13,184–185` — the scanner rejects anything else).
- **Range-filtered recall.** Zleap's multi-path recall with RRF fusion (`DEFAULT_RRF_K = 60`, `packages/store/src/core/rrf.ts:16,20`; `CoreStore.recall`, `fast | precise`, `packages/store/src/core/types.ts:193–194`) is retrieval whose isolation *is* the scope predicate in the WHERE clause.
- **Projection → prompt.** `listMemory` injects a memory projection as a synthetic tool exchange placed before replayed history (`packages/agent/src/engine/index.ts:198,444`) — the cleanest existing case of a granted range flowing into a prompt.

So isolation has two planes, and pg-agent today implements neither as a *boundary*:

- **Data plane** — what may be retrieved. Today implicit: whatever tables the session role happens to see.
- **Control plane** — what may execute. Today the `exec_sql_readonly` keyword blacklist (`v2/pg_agent_functional.sql:252–266`: `drop…merge`, plus `set/reset/load/…`). This is **not a security mechanism**: it cannot stop side-effecting `VOLATILE` functions reachable from a plain `SELECT` (C states this twice; it is an inherited finding, not a fresh claim). Single-statement enforcement bounds the *shape* of a turn, not its *reach*. The real boundary is role assumption, RLS, pinned `search_path`, and session-type discipline — Postgres primitives pg_cordis has no reason to reinvent.

The theory connection is exact: Cordis **coefect isolation** introduces *isolation realms* — a realm table `ρ : K → R` assigning a realm identifier to each isolated key, so the same dependency resolves to different values per context, with applications "in multitenant systems, testing environments, and component sandboxes" (`docs/A Programming Paradigm for Spatiotemporal Composability.md:620,630`); `set` remains an effect function in `Σ^iso*` and inherits revertibility (`:644`). A realm is a named range. A's open question — realms → schemas, RLS, or `search_path` — gets its answer-shape here — *opinion:* **all three, layered**, with grants (not workspaces) doing the selecting.

## Worked example (two reference projects, three functions)

Task: *"use project 1's code to develop function 1; use project 2's code to develop functions 2 and 3."*

**Under workspace isolation this fails structurally.** A workspace holds one project's scope; a run lives in one workspace. The options are three runs across two workspaces with no shared contract for the deliverable, or one merged workspace containing both projects — which destroys the very boundary the task asserts (project 1's code must *not* reach functions 2–3's reference set). The task exceeds Zleap workspace isolation; it is the canonical case for range grants.

**Under retrieval-range isolation it is one run holding two named grants, bound per slice** — function 1's slice carries `grant P1`, functions 2–3's slice carries `grant P2`; a run-level union of grants would pool both projects into every prompt and defeat the boundary (binding is to slices, P1 below):

- `grant P1` — a predicate over project 1's corpus (source rows, embeddings, graph edges; on pgembed's bundled retrieval stack — pgvector, age, psql_bm25s, `pgbuild/Makefile` in the pgembed repo, A-L4-verified — the rows tagged project-1).
- `grant P2` — the same shape over project 2's corpus.
- **Function 1**: sub-task prompt = fold(parent log) + `recall(grant P1)`. The model sees project 1's code *only through* the grant; its output lands in the run's workspace tier, in neither corpus.
- **Functions 2 and 3**: same run, prompts assembled from `recall(grant P2)`. Project 1's code is unreachable — not because a workspace excludes it, but because no live grant names it.

The mechanism anchors exist as degenerate cases. Spawn today presets only `question` (hybrid adds `context`) into a fresh child namespace (`v2/pg_agent_rlm.sql:749–753`) — a one-slice inheritance. The proposal generalizes it to **named scope slices**: a spawn — or an RLM chunk sub-call; `rlm_map` batches ≤ 8 chunks (`v2/pg_agent_rlm.sql:586`), the natural carrier — carries `question` plus a list of grant names. CodeAct's equivalent is workbench tools tagged with a grant, RLS on the backing views making the tool's *own* queries range-bound. Three functions, two grants, one run: expressible, auditable, and unsayable in workspace vocabulary.

## pg_cordis isolation proposal

> **This is a proposal, not a decision** — the rubric's single sanctioned design sketch for this series. Every clause is contestable; none is frozen.

**P0 — Amend the state contract to three categories: log / projection / workspace.** B's requirement 4 wording said "everything else is a projection … never a second source of truth." C's TC3(c) showed why that cannot hold for env state: env values are produced by executing model-written SQL against live data, so a fold would have to re-execute non-deterministic code. **This proposal amends B's wording explicitly** (C-L4 adjudicated TC3(c) as an amendment, not a reading of B): *log* = history SoT; *projections* = derived, never authoritative; *workspace* = run-owned execution state — non-history, non-authoritative, and bound by TC3's clauses: **run-owned, run-lifecycle-scoped, no cross-run reads**. `rlm_vars` (`v1/pg_agent_rlm.sql:57`) is the precedent shape, contract-bound rather than ambient.

**P1 — Scope grants as the isolation primitive.** A grant is a named declarative range: `(grant_id, predicate, resources, capabilities)` — resources select corpora (source rows, embeddings, graph edges, logs, tools); capabilities declare what may be done inside the range (read / append / execute). Grants issue to runs and to *slices* within runs. **A retrieval call resolves against the union of the calling slice's live grants** — not the run's whole grant set, which is exactly what keeps the worked example's two grants from pooling — enforced at every retrieval seam: recall, fold, tool dispatch, env reads.

**P2 — Enforcement by capability scoping, not keyword filtering.** Per-run role assumption + RLS policies keyed to grant predicates + pinned `search_path` + session-type separation (analysis sessions vs worker sessions vs projection workers). The blacklist survives at most as input hygiene. Nothing in pg_cordis may describe `exec_sql_readonly`-style filtering as a safety mechanism.

**P3 — Realms layered on Postgres primitives.** Σ^iso realms (`Spatiotemporal Composability.md:620–644`) map as: **schemas** = realm namespaces; **RLS** = the realm wall; **`search_path`** = default visibility. The mapping *changes character* from workspace-shaped (one realm per consumer) to grant-shaped (many grants per consumer, each selecting within or across realms). This answers A's Σ^iso question and is precisely why workspace vocabulary was too narrow.

**P4 — Spawn lineage as log events + an explicit run-id contract.** Today both spawn paths bypass the event model (`rlm_children` rows plus `ORDER BY created_at DESC` retro-linking — a race-prone heuristic, per C). Proposal: the parent emits `spawn/start` (child run-id, prompt, grants) and `spawn/end`; children are discovered by contract, not timestamp. v1's `'spawn'` step kind (`v1/pg_agent_rlm.sql:50`) is the vocabulary precedent; v2's fold still understands it (`v2/pg_agent_rlm.sql:184,187`) while nothing emits it. **Env inheritance is scoped slices**: the child receives `question` plus named grants — never the whole parent env.

**P5 — Multi-writer append is capability-gated.** When a host-side loop (DSH's `ReactLoopAgent` through a PG-backed persistence seam) and an in-database `rlm_loop` append to one session log, ownership is: each writer holds an *append capability* scoped to that session log; appends are serialized transactions (seq-PK contention as the serialization point); advisory locks are an implementation detail, not the contract. Paradigm-independent — C deferred it here.

**P6 — Budget as an isolation dimension.** The RLM paper's cost table is the argument: averages hide outliers — GPT-5 RLM on BrowseComp+ scores `91.33 ($0.99 ± $1.22)`, and the ± is the point (`docs/RECURSIVE LANGUAGE MODELS.md:81`); runs reach the "10M+ token regime" (`:83`). Proposal: the budget lives on the **run row** (steps/depth/children/tokens/cost), the **kernel enforces**, the **paradigm policy parameterizes**. pg-agent's caps are the precedent — depth ≥ `max_depth` or ≥ 4, ≤ 16 children, child `max_steps = LEAST(parent, 6)` (`v2/pg_agent_rlm.sql:522–545`). A subtree that exceeds its budget is an isolation event, not merely a cost event. How budgets propagate to children — decrementing a shared parent pool vs issuing each child a bounded slice of the remainder — is deliberately left open (below).

**P7 — Projection visibility is grant-declared.** A projection registers *with its read range*: which grants' data it may fold. A supervision projection may hold a cross-paradigm grant; a tenant memory projection holds one tenant's. Registration is capability-gated (B's question, answered as opinion). Deterministic folds read within the writing transaction; model-backed projections run in worker sessions holding their *own* grants, never the caller's — which also answers B's "where do model-backed projections execute."

**P8 — Execution placement follows grants.** Deferred dynamic plugin code (A's T4) and model-backed projections execute only under grants carrying the `execute` capability, in worker sessions — the in-database analog of DSH's host-side wall (`denyContext`, `packages/extensions/cordis-host-runner/src/guard.ts:669`; `createSandbox`/`precheckCode`, `.../cordis-host-runner/src/sandbox.ts:129,212`). Retrieval-range isolation is the precondition A named for T4; this is where it lands.

**Retention** (B's question, deliberately narrowed here): forgetting happens in projections — a projection may drop what it derived; the log's retention is a separate storage policy that must never silently rewrite truth. Whether the log itself may ever be legally pruned stays open (below).

## Key tradeoffs (opinion, not decision)

Analyzed in turn; each ends with an opinion. None is a decision; A's extension-vs-plugin split and B/C's contracts are assumed, not reopened.

**TD1 — Enforcement locus.** Options: (a) RLS-only; (b) a distinct role per run (grant = role membership); (c) layered — shared roles + RLS keyed to grant predicates + pinned `search_path` + session types. Analysis: (a) makes every policy a row expression — flexible, but the grant grammar becomes "whatever RLS can say," and every recall path (pgvector/bm25s) must carry the predicate or silently leak; (b) is coarse — role churn per run, no intra-run slices, so the worked example dies — and cannot scope non-table resources; (c) prices each mechanism for what it does best: roles separate *trust classes*, RLS separates *ranges*, `search_path` pins defaults, session types separate *lifecycles*. *Opinion: (c). The worked example is the test — it needs intra-run slices, which neither (a) nor (b) provides cleanly.*

**TD2 — Grant shape.** Options: (a) declarative predicate rows evaluated at the seam; (b) materialized scope tables (grant → concrete row sets); (c) session GUCs (today's `rlm.run_id` pattern generalized). Analysis: (a) stays fresh as corpora change and composes as a union of predicates, but every retrieval path must evaluate it; (b) is cheap to enforce yet must be maintained, goes stale, and smells of a second SoT; (c) is proven (`rlm_bind`) but session state is invisible across sessions and dies with the connection — right as a *cache* of (a), wrong as the truth. *Opinion: (a) as truth, (c) as its per-session materialization — the honest reading of what pg-agent's GUC already is: a footnote that grew up.*

**TD3 — The workspace tier.** Options: (a) amend B's requirement 4 to three categories (P0); (b) re-derive env as a log fold (B-orthodox); (c) keep `rlm_vars` as an undeclared second SoT. Analysis: (b) cannot actually replay — it would re-execute non-deterministic model-written SQL — and explodes the log with full `last_obs` results; (c) is precisely the drift requirement 4 exists to prevent; (a) names the thing correctly and constrains it, and is the explicit amendment C-L4 demanded rather than a silent exception. *Opinion: (a), stated in the text as an amendment — not smuggled in.*

**TD4 — Spawn lineage.** Options: (a) log events (`spawn/start`/`spawn/end`) plus an explicit run-id contract; (b) registry rows only (`rlm_children` today). Analysis: (b) keeps lineage out of the fold — prompts cannot see children, supervision folds cannot use them, discovery stays race-prone; (a) costs two event kinds and restores v1's vocabulary. *Opinion: (a), unconditionally — it is also what makes P4's slice inheritance auditable.*

**TD5 — Multi-writer append ownership.** Options: (a) advisory locks; (b) serialized append transactions; (c) capability-gated append with (b) underneath. Analysis: (a) is implementation-visible and liveness-fragile (a crashed holder); (b) alone says *when*, never *who*; (c) answers who may append at all — host loop, in-database loop, projection worker — then serializes. *Opinion: (c). The capability is the contract; the transaction is the mechanism.*

**TD6 — Budget locus.** Options: (a) kernel-fixed; (b) paradigm policy; (c) run row + kernel enforcement + policy parameterization. Analysis: (a) cannot price paradigms differently; (b) lets a paradigm opt out — but budget is an isolation property, not a preference; (c) puts the number where the run is created, enforcement where the loop runs, defaults where the paradigm registers. *Opinion: (c) — pg-agent's caps are already (c) with the policy inlined in one function; this merely moves it into the registry.*

**TD7 — Where model-backed projections (and later dynamic code) execute.** Options: (a) worker sessions holding their own grants; (b) host-side processes reading through a client seam. Analysis: (a) keeps enforcement in-database — RLS applies, budgets apply, the log sees the work; (b) re-imports DSH's process wall, which is proven (`guard.ts`), but every grant check becomes an API call and the log's view of projection work degrades to "it happened outside." *Opinion: (a) for anything reading granted ranges; (b) only with declared outside-effects per A's T3 ledger. This is also A's T4 answer-in-waiting: dynamic code lands in (a)'s seat, behind an `execute`-capable grant.*

## Residual open questions

- **Grant grammar.** SQL predicate vs structured descriptor (resource-type + filter + capability)? Who authors grants — the user, a planner run, or the model proposing grants that a capability holder approves? The worked example needs only point grants; grant fusion into RRF recall's WHERE clause is untested.
- **Performance.** RLS predicates over pgvector/psql_bm25s/age recall paths — enforceable at plan time, or do grants need partial-index/materialized support (TD2(b) as an optimization, never as truth)?
- **Kernel or plugin?** Is the grant registry kernel (like `emit_step()`'s writer monopoly, per C) or a registered subsystem? Interacts with A's still-open extension-vs-plugin split.
- **Host-side grant acquisition.** How does a DSH `ReactLoopAgent` driving a pg_cordis log acquire and present grants through the persistence seam — the client-facing shape of P5's append capability?
- **Forgetting.** Is log pruning ever legal (retention/GDPR), or is forgetting strictly a projection power? B's question; this proposal only bounds it.
- **Migration and testing.** Importing pg-agent's `rlm.run_id` + TEMP-VIEW workaround into grants; a test harness proving range enforcement (recall-through-grant leakage tests) — the series' cross-cutting harness question, instantiated for isolation.
- **Budget propagation.** Does a child's consumption decrement the parent's pool, or does each child receive a bounded slice of the remaining budget (mirroring `LEAST(parent, 6)`)? Affects spawn-heavy RLM trees most.
- **Turn-5 candidates.** If a synthesis turn revisits anything here, P0's three-category wording is the clause most likely to need re-drafting against B's text — deliberately flagged rather than hidden.
