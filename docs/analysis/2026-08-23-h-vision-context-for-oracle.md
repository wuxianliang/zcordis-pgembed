# H — 宏观愿景 vs D1–D9：oracle 裁决输入

Date: 2026-08-23
Status: **context brief (spent).** D1–D9 signed; wrap-up: `docs/analysis/2026-08-23-i-architecture-snapshot.md`. Adjudication: `docs/analysis/2026-08-23-h-vision-d1-d9-oracle-verdicts.md` and `prompt-exports/oracle-plan-2026-08-23-150327-untitled-chat-145b87-8ee1.md`.

## User product vision (verbatim intent, 2026-08-23)

1. **First product** of `pg_cordis`: a coding agent like `~/Projects/temps/repoprompt-ce`. Workspace, Context Builder, prompt packaging, selection, worktree — all become **pg_cordis plugins**, not extra `CREATE EXTENSION` packages.
2. **Second product family**: data-analysis. `~/ghidra-projects` InfiniSynapse reverse (InfiniSQL temp-view pipeline) is a **prototype**, not the runtime. A **DuckDB 2.0 workbench still to be written** is the real DA plugin. Earlier pg-agent DA SQL / TEMP VIEW work is **temporary exploration** — analysis actually happens **on DuckDB**, not in `pg_temp`.
3. **Two plugin polarities on one kernel**: RepoPrompt-CE-style plugins **edit existing files** (repr-switch: full / slice / codemap; `apply_edits`). DuckDB-2.0-style plugins **create new tables** (generative: `SELECT … AS view`). Both coordinate through pg_cordis (session log, grants, spawn, workbench registry).
4. **Two agent paradigms**: **CodeAct is primary**; **RLM is complementary**, shape taken from `~/Projects/prime-agent` (IPython kernel + `await rlm(...)` returns admission handle, never the child answer; results via `agent_message` / files).
5. **Unique isolation feature (no found reference)**: user says “reference project A for function 1, project B for functions 2 and 3.” The agent must **isolate retrieval ranges**, then **compose the actual prompt from retrieved fragments** (most reasonable slices), not from a whole workspace dump.

## What this does to the pending frame

`docs/decisions/2026-08-23-pending.md` D1–D9 were written assuming pg-agent v2 **Postgres TEMP VIEW workbench** is the DA path. The vision **re-homes DA onto DuckDB**. That is not a reopening of locked pins; it is new product sequencing that may **change how far D1/D5/D8 can lock**.

## Locked pins (do not reopen)

| Pin | Value |
|-----|--------|
| SoT | append-only session / `agent_steps` log |
| Plugins | SQL/PL/pgSQL-first; DSH migratable not reused |
| Queue | upgrade `jobs`/`worker()`, no second Absurd queue |
| Worker | in-DB loop and host SDK, one claim protocol |
| Checkpoint | ⊂ log |
| Yield | mixed D: default one LLM + its tools; deep/expensive spawn async |
| LLM idempotency | A+B; **not** tools |
| Events | grant capabilities on `(event_scope_id, name)` |
| TE1 | narrow-frozen: jobs+claim+log checkpoints; sleep/event/retry not frozen |
| Isolation direction | retrieval grants, **not** Zleap workspace |
| Scratch | 3 claims = 3 steps proven on mock LLM |

## Prototype evidence (collected this turn)

### RepoPrompt-CE — coding workbench to plugin-ize

Paths: `/Users/wxl/Projects/temps/repoprompt-ce`.

- **Workspace authority** is canonical domain state (`docs/spec/headless-mcp-domain-runtime-m2-context-authority.md`): workspace documents, compose-tab context, revisions, run-scoped bindings. App UI is a projection.
- **Context Composer** (`docs/architecture/context-composer.md`): selection (full / slice / codemap), Prompt packaging presets, **Context Builder** as a heavy sub-agent that curates files then produces plan/review/question. Prompt is assembled from a **snapshot of curated fragments**, not from the whole tree.
- **Headless MCP** (`docs/architecture/headless-mcp-runtime.md`): ~27 canonical tools; `manage_selection`, `workspace_context`, `context_builder`, `apply_edits`, `file_actions`, `agent_run`, `ask_oracle`. File edits go through a shared apply-edits engine (operation-id, path fencing, approval, retry class).
- **Provider plugins** (`docs/architecture/provider-plugins.md`): static SwiftPM composition, **not** dynamic `node:vm`. Seam stops short of dynamic loading — matches A-T4 deferral.
- **Worktree as coding substrate**: per-agent-session Git worktree; inherit default true; merge-back is a three-way merge state machine (see ghidra unified-workbench §2.1).
- Polarization vs DA: CE mutates **existing file identity** (repr-switch). It does not materialize new named tables.

### InfiniSynapse reverse + DuckDB workbench — DA prototype

Paths: `/Users/wxl/ghidra-projects` (reverse + Ghidra project), `/Users/wxl/Projects/infinisynapse` (recovered + Python-port sketches).

- InfiniSQL workbench = per-task session `{set_sqls, register_tables, temporary_views, databases}`; transform = `SELECT … AS <view>`; tools = `execute_infinity_sql(brief, view_name, query)` plus register/list/show/save (`docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md`).
- Standalone implementation intent (`docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md`): **Python agent → tool handler → in-process DuckDB**; SQLite holds replayable metadata; **no JVM/Spark**. Persist definitions + lineage, replay into a fresh DuckDB (Candidate B).
- Unified design (`docs/designs/unified-agent-workbench-2026-07-01.md` and `docs/designs/unified-temp-workbench.md`): CE worktree and InfiniSQL session are the **same workbench kernel** with different **substrates**. Shared invariants: per-task isolation, disposable-but-rebuildable from durable manifest, parent→child inheritance, merge-back, path sandbox, artifact archive+recall. Divergence is **only substrate**: files+commit vs named views.
- **User correction:** that kernel should live in **pg_cordis**, not a third standalone project. DuckDB 2.0 (to be written; local official tree is DuckDB v1.5.5 / main) is the DA substrate plugin. pg-agent `plugin_temp_views` / `pg_temp` is **not** the product DA path.

### prime-agent — RLM complementary shape

Paths: `/Users/wxl/Projects/prime-agent` (`packages/coding-agent/docs/rlm.md`, `rlm-runtime.md`).

- Default model tool is **one**: `ipython`. Files, shell, skills, spawn all go through a persistent kernel. This is RLM, not CodeAct (paper discriminator: RLM offloads the prompt into the environment).
- `await rlm("…")` returns **admission handle only**; never waits for the child answer. Children run as separate `AgentSession`s. Results via `agent_message` or files.
- Host (TypeScript) owns providers, persistence, usage, child lifecycle; Python is a shim. Depth policy, registry survive compaction.
- Prompt templates (`prompt-templates.md`) are **static markdown snippets**, not retrieval-composed grants. **Does not implement** “project A for f1, project B for f2/f3” isolation.
- Implication for D9: prime-agent spawn is **already enqueue-and-don't-wait**. Synchronous in-transaction `rlm_loop(child)` is the thing both DBOS and prime-agent refuse.

### pg_cordis isolation proposal (already written)

`docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md` worked example **is exactly** the unique feature. P1: grants bind to **slices**, not the run-union. Prompt assembly = fold(parent log) + `recall(grant)`. Isolation = retrieval ranges, not a workspace cell.

CE already composes prompts from **manually/automatically curated slices**. The unique step is: those slices are **retrieved under grants**, not only from `StoredSelection`.

## D1–D9 as currently optioned (pending.md)

| ID | Topic | Current research lean (Kimi/DBOS/absurd, not user-signed) |
|----|--------|-----------------------------------------------------------|
| D1 | TEMP VIEW vs yield | A run-level PG workspace, or D defer DA |
| D2 | Tool retry | A+C transactional vs non-transactional + call/result |
| D3 | sleep/await placement | B `jobs` + `run_waits`/`run_events` sidecars |
| D4 | Kernel contents | A five primitives in kernel |
| D5 | Grant syntax / issuer | still user; lean C enum ranges |
| D6 | Child budget | C step/depth/fan-out only |
| D7 | Delivery | D SQL source in this repo; pg-agent testbed |
| D8 | Host SDK seam | A min SQL seam |
| D9 | Async spawn threshold | B or D (always enqueue) |

## Hypotheses for the oracle (contestable)

**H1 — Sequencing locks D1 as “D for PG-TEMP DA” plus a substrate split, not A-as-written.** Coding-agent-first means v0 does not migrate `pg_temp` workbench. Run-level **coordination** state (selection registry, grants, rlm_vars, lineage) still lives in PG tables (P0 workspace tier). DA materializations live in the DuckDB plugin. Do not pick B/C (session affinity).

**H2 — Vision locks D5 direction, not full grammar.** Isolation-as-retrieval-grants is no longer optional paper (cannot pick D5-D). First coding-agent version can be **named corpora** (C): one grant per project root, bound per slice. Structured descriptors (A) are the upgrade path. SQL-predicate grants (B) out.

**H3 — D2 for coding-agent-first is file-edit classified, not TEMP classified.** `apply_edits` / worktree mutations are non-transactional (host FS) → need call/result + idempotency or non_retryable. Read tools (search/tree/read) are retryable. DuckDB `CREATE VIEW` is transactional **inside DuckDB**, not inside the PG claim transaction — treat as non-transactional step unless a future 2PC exists.

**H4 — D3/D4 unchanged by vision** (durable wait is kernel regardless of CE vs DuckDB). Coding agent still needs sleep/await for approvals and child agents.

**H5 — D6 stays C.** Coding agent v0 has no token-pool primitive in CE or prime-agent. CE has **selection token budget**; that is a **plugin concern** (context-builder plugin), not kernel shared-pool.

**H6 — D7 stays D; first plugins are CE-shaped not DSH-shaped.** Kernel SQL in this repo. Workspace / context-builder / apply_edits land as plugins. DuckDB DA plugin later. No `CREATE EXTENSION` this week.

**H7 — D8 is A plus a plugin catalog, not DSH event-shape (B) or migrator (C).** Host SDK speaks claim/checkpoint/yield. CE-like tools execute in the host locus under the same protocol. Do not postpone host path (D8-D) because coding-agent-first **is** the host locus.

**H8 — D9 leans D (always enqueue children) because CodeAct-primary + prime-agent RLM.** CodeAct steps are the default mixed-D yield (LLM+tools in one claim). RLM/child agents always jobs. Optional B (keep depth-1 sync) is an optimization, not required for v0 coding agent.

## Oracle task

For **each** of D1–D9, return:

1. **Lock level**: `lock_option` (vision+evidence pick one letter) | `lock_direction` (narrows options, letter still needs user) | `defer` (explicit debt, not a hidden A) | `still_user` (vision does not constrain).
2. **Recommended option** (or combination, e.g. A+C) using pending.md letters. If the vision requires a **new reading** of an option, say so in one sentence — do not invent a fifth letter unless the four cannot express it.
3. **What the vision supplies** vs **what is still missing**.
4. **Confidence** 0–1 and one falsifier.
5. Whether this recommendation **conflicts** with Kimi/DBOS/absurd leans in pending.md.

Then:

- A 9-row summary table.
- **Sequencing**: what a coding-agent-first v0 actually implements vs what waits for the DuckDB plugin.
- **Do not** fill pending.md `决定` cells as if the user signed. This is adjudication for the user to confirm.
- Do not reopen locked pins.
- Do not treat DSH richness or Zleap workspace as product inventory.
- D5 is the product differentiator; do not bury it as “later paper.”
