# A — DSH plugin migration to pg_cordis

Date: 2026-08-23 · Series: sequential research A→I · Status: **analysis evidence.** Decisions and working hypotheses: `2026-08-23-i-architecture-snapshot.md`. SQL/PL/pgSQL-first is frozen; extension-vs-plugin split closed by D7 (SQL source in this repo, no CREATE EXTENSION yet).

Evidence base (read-only): `deepseek-harness` (plugin population + vendored Cordis kernel), `pg-agent` (v2 SQL plugin precedent), `pgembed` (attested PG 18 bundle + extension packaging path), `zcordis-pgembed/docs/` papers (Cordis theory, RLM, Zleap/SAG articles).

The two governing requirements, restated:

1. **Migratable, not identical** — every DSH plugin role must have somewhere to land in a pg_cordis plugin contract. If a plugin kind cannot migrate, the contract is wrong.
2. **Migration is not direct reuse** — pg_cordis exists because the database changes the terms: some things DSH builds by hand, Postgres has natively; some things DSH does easily, Postgres cannot host at all. Both directions shape the contract.

---

**Key tradeoffs at a glance** (listed first per guidance; full analysis in the tradeoffs section):

- **T1** — Plugin authoring surface: `COMMENT`-embedded JSON (pg-agent style) vs registry-table-first vs C-extension-only.
- **T2** — Contract fidelity: port the full DSH semantic vocabulary (`inject`/`provide`/events/fiber lifecycle) vs a minimal "function + tool descriptor" contract.
- **T3** — Temporal composability mechanism: lean on transactions vs build an explicit compensation/undo ledger.
- **T4** — Dynamic runtime-defined plugins (DSH's `node:vm` path): support in v0 vs defer behind static registration.
- **T5** — Where the pg_cordis kernel lives: versioned SQL schema vs C extension from day one vs pgembed-bundled artifact.
- **T6** — Browser/UI plugin halves: inside the pg_cordis contract vs outside it behind a seam.
- **T7** — One unified plugin registry vs two invocation models (queue-dispatch and session-SELECT) under one metadata schema.

---

## DSH plugin surface to migrate

DSH's plugin system has two layers: a **kernel contract** every plugin programs against, and a **plugin population** of several dozen capability groups. The migration surface is both.

### The kernel contract (vendor/cordis/src/)

The vendored Cordis kernel is small and well-factored. The pieces a plugin actually touches:

| Kernel module | What a plugin sees | File |
|---|---|---|
| Plugin entry shapes | `Plugin.Function` `(ctx, config)`, `Plugin.Constructor`, `Plugin.Object { apply(ctx, config) }`; shared metadata `Plugin.Base`: `name`, `Config`, `inject`, `provide`, `intercept` | `vendor/cordis/src/registry.ts` |
| Dependency declaration | `@Inject(name, config?)` decorator, normalized by `Inject.resolve()` into a `name → config` map | `vendor/cordis/src/registry.ts` |
| Context | proxied service container: `ctx.get/set/provide/inject`, `ctx.extend()`, `ctx.isolate(name, label?)`, `ctx.intercept(name, config)` | `vendor/cordis/src/context.ts` |
| Service base | `Service` abstract class; lifecycle symbols `init/check/config/invoke/extend/tracker/resolveConfig`; callable services via `createCallable()` | `vendor/cordis/src/service.ts` |
| Fiber lifecycle | states `PENDING/LOADING/ACTIVE/FAILED/DISPOSED/UNLOADING`; `fiber.effect()` registers cleanup inverses; `fiber.update(config)` goes through an `internal/update` waterfall veto | `vendor/cordis/src/fiber.ts` |
| Events | five dispatch modes (`emit`, `parallel`, `serial`, `bail`, `waterfall`); `ctx.on`/`ctx.once` | `vendor/cordis/src/events.ts` |
| Reflect | service resolution keyed by isolation label; `notify()` re-evaluates dependent fibers when a provider appears/disappears | `vendor/cordis/src/reflect.ts` |

The repo's own catalog states the contribution contract in one line: *"Cordis `Service` subclasses and function plugins contribute through `ctx.effect()`, `ctx.on()`, or `ctx.waterfall()`"* (`packages/README.md`). A DSH bug note also records the activation semantics that any port must preserve conceptually: *"Cordis activates plugins by service availability, not configuration order"* (`.agents/notes/bug-fix/2026-07-30-tui-adapter-registration-race.md`).

### The plugin population

Grouped under `packages/<group>/<pkg>/`, npm scope `@deepseek-ai/dsh-*`, catalogued in `packages/README.md` (~30 groups: `core`, `llm`, `shell`, `fs`, `web`, `terminal`, `subprocess`, `code-runtime`, `sandbox`, `lsp`, `skill`, `compaction`, `context`, `subagent`, `jobs`, `workflow`, `goal`, `schedule`, `session`, `session-query`, `storage`, `attachment`, `spill`, `todo`, `plan`, `feedback`, `identity`, `e2b`, `experimental`, `extensions`, `client`, …). Classified by migration difficulty:

1. **Model-facing tool registrations** — declare tools over services. Examples: `packages/extensions/tool-cordis/` (five tools: `cordis_inspect/define/run/stop/undefine`), `tool-bash`, `tool-skill`. Best case for SQL migration; pg-agent's workbench plugins are exactly this shape.
2. **Service providers (capability families)** — the bulk of the catalog: seam interface + local provider + tool. Examples: `shell/` (`ctx.shell` executor seam + `bash-local`/`bash-sandbox`/`shell-env`), `skill/` (`ctx.skills` registry + `skill-filesystem`), `lsp/`, `fs/`. These carry the `inject`/`provide` wiring richness.
3. **Persistence plane** — `session/session-persistence/` defines abstract `SessionPersistence` (`locate/create/append/load/inspect/readFrom/list/listSnapshots`); concrete backends `session-persistence-jsonl` (zstd-compressed append-only log, crash-safe materialization via temp file + `link()` + directory fsync) and `session-persistence-sqlite` (WAL, chunk-row codec, `MAX_PACKED_ROW_MEMBERS = 1024`); plus `session-projection`, `session-query`. Mostly **superseded** by the database rather than migrated (Topic B).
4. **Loop/orchestration** — `core/agent-loop/` (the concrete default loop behind the `agent` seam), `workflow/` (worker-thread engine), `subagent/`, `jobs/` (background-job runtime + `job_*` tools).
5. **Dynamic runtime plugins** — `extensions/cordis-host-runner/`: `createSandbox()`/`evaluateHostCode()`/`precheckCode()` run plugin code in a `node:vm` context with capability traps (`require`, `fetch`, timers redirected) and a guarded read-only `ctx` facade (`guard.ts` denies raw `Context` and undeclared services). Registry is process-memory only. Hardest to migrate.
6. **Browser/UI halves** — `client/ui-*` plugins (React slots: `ui-conversation`, `ui-tool`, `ui-plan`, `ui-settings-plugins`, …) and `cordis-client-runner`. Not database material; the contract only needs a seam for them.

A representative plugin shape, `JsonlSessionPersistence` (`packages/session/session-persistence-jsonl/src/index.ts`): `static inject = ['sessions']`, zod `static Config`, constructor `(ctx, config)`, abstract-method overrides. **That triple — declared dependencies, validated config schema, contextual lifecycle — is what "DSH plugins are very rich" concretely means.** The richness is in the wiring contract, not the tool count.

## What pg_cordis would need to accept

Requirement 1 says the eventual pg_cordis plugin structure must be able to receive each DSH plugin *role*. Under the SQL-first hypothesis, "accepting a plugin" means accepting a **declarative definition** plus **SQL objects**, compiled into a catalog the runtime consults. Element-by-element mapping (analysis, not a frozen design):

| DSH contract element | PG-native candidate | Existing precedent |
|---|---|---|
| Plugin identity + metadata (`Plugin.Base`) | JSON metadata attached to SQL objects; scanned into registry tables | pg-agent v2 `COMMENT ON FUNCTION … '{"workbench_plugin": …, "llm_tool": …}'` (`v2/pg_agent_workbench_core.sql`, validated by `refresh_workbench_tools()`) |
| `inject` (coeffects: what a plugin needs) | metadata field + dependency rows; unsatisfied deps detectable at scan time | pg-agent `job_handler` scan checks handler existence; DSH `missingServices(ctx, fiber)` in `cordis-host-runner/src/lifecycle.ts` is the semantic model |
| `provide` (effects: what a plugin contributes) | provider registration rows in a service-namespace table | `workbench_tools` / `handlers` tables; conceptually `ctx.provide` |
| Reactive activation (service availability) | re-scan/refresh on registration change; triggers on provider table re-evaluating dependents | `refresh_handlers()` / `refresh_workbench_tools()` TRUNCATE+INSERT rebuild is the degenerate form; `ReflectService.notify()` is the target semantics |
| Events, 5 dispatch modes | triggers (synchronous, in-transaction, ordered) cover `serial`/`waterfall`; `LISTEN/NOTIFY` covers fire-and-forget; `parallel`/`bail` need kernel functions | no direct precedent in pg-agent; DSH `events.ts` is the reference |
| Fiber lifecycle + `effect()` inverses | load = install/refresh; unload = drop/refresh; inverses = savepoints/rollback or an undo ledger (T3) | pg-agent has no unload concept; `agent_steps` + `run_state()` show state-as-derived-data |
| Config with schema validation | JSONB column/comment + validator function | `refresh_workbench_tools()` already enforces `llm_tool.name == proname`, `returns = 'jsonb'`, `session_scope`, `capability ∈ ('read_only','temp_view_mutation')` |
| Callable services | functions/procedures; dynamic dispatch via `regproc` | pg-agent `worker()` dispatches `EXECUTE format('SELECT %s($1)', v_fn)` (`v2/pg_agent_functional.sql`) |
| Tool listing for prompts | STABLE render function over the registry | `render_workbench_tools()` (`v2/pg_agent_workbench_core.sql`) |
| Dynamic runtime code | **no native equivalent** — see obstacles; candidates: static SQL only, `plsh` (bundled in pgembed), trusted languages, C extension | `cordis-host-runner/src/sandbox.ts` is the capability bar |
| Browser/UI halves | out of the database; a seam contract between host-half and client-half | DSH already splits `cordis-host-runner` vs `cordis-client-runner` |

Two structural conclusions the table supports (opinions):

- **Compatibility lives in the metadata vocabulary, not the runtime.** A DSH plugin migrates if its `inject`/`provide`/`capability`/`config` declaration can be expressed in the pg_cordis registry and its body re-expressed as SQL. The TS runtime (`Context` proxies, fibers) is an implementation of the semantics, not the semantics themselves.
- **The DSH population implies at least two invocation models.** pg-agent v2 already discovered this independently: queue-dispatch plugins (`job_handler` → `handlers` table → `worker()` polling `jobs` with `FOR UPDATE SKIP LOCKED`) and session-SELECT plugins (`workbench_plugin` → LLM-invocable `wb_*` functions), with a scanner-enforced **mutual exclusion** rule (`refresh_workbench_tools()` raises if a comment carries both keys — `v2/pg_agent_workbench_core.sql`). DSH's breadth (tools vs services vs loops vs jobs) will not collapse into one model.

## Database-unique value (why migrate, not reuse)

Requirement 2's premise: the database gives conditions DSH cannot give, and the contract should be shaped to harvest them. Where the value actually is:

1. **Temporal composability becomes transactions.** The Cordis paper's hardest machinery — per-fiber effect accumulators holding explicit inverses so that unloading a component *completely reverts* its side effects (paper §3.3.1 plug/unplug semantics) — is a hand-built reimplementation of what Postgres provides natively: atomic commit/rollback, savepoints, and **transactional DDL**. A plugin whose effects are rows gets unload-for-free. This is the single largest structural win, and it is why the SQL-first hypothesis is plausible at all.
2. **Spatial composability becomes catalog data.** The paper's coeffect context `Σ := (k: K) ⇀ V_k` (a finite partial function from dependency keys to values) is literally a table keyed on `k`. Reactive notification (paper Def. 26: activating/deactivating/neutral classification of context changes against a declared spec `d ⊆ K`) maps to triggers on the provider registry. Isolation realms (`Σ^iso`, same logical key resolved per context) map to schemas/roles/RLS; interception (`Σ^inter`) to RLS policies. The theory was waiting for a relational substrate.
3. **The session log gains query power.** DSH's persistence plane is elaborate precisely because it emulates durability outside a database: `PersistenceCoordinator` write-behind batching (`DEFAULT_WRITE_BATCH_MAX_DELAY_MS = 200`), torn-tail repair, zstd JSONL framing, SQLite WAL chunk codecs (`session-persistence-sqlite/src/codec.ts`). In Postgres, WAL *is* the write-behind layer, and `session-query`/`session-projection` plugins become views/functions over an append-only table. The Zleap articles argue exactly this ("a file system is like raw logs; databases make agent runtime partitionable, auditable, rollbackable, and reusable" — `zleapai-x-articles.md`).
4. **One substrate for state, logic, and retrieval.** SAG's multi-hop retrieval is already "relational expansion inside a database" (SQL joins over `chunk → event → entities`); pgembed bundles the retrieval stack (`pgvector`, `vectorchord`, `psql_bm25s`, `age`, `timescaledb` — `pgbuild/Makefile:33`). DSH retrieval/记忆 plugins collapse into indexed queries instead of separate subsystems.
5. **Attested deployment.** pgembed's content-addressed bundle stamp + `build-metadata.json` (schema v1) + `validate_bundled_binaries()` give pg_cordis a pinned, hash-verified distribution path. DSH has nothing equivalent for its runtime.
6. **Real concurrency and scheduling primitives.** `FOR UPDATE SKIP LOCKED` job consumption (pg-agent `worker()`), advisory locks, `pg_cron`/`pg_net` bundled — the `jobs/`/`schedule/` DSH groups map onto engine primitives rather than Node bookkeeping.

**Caveat that keeps this honest:** the value is conditional on the richness surviving. If the SQL contract can only host tool-shaped plugins, migration degrades to porting `tool-*` packages, and points 1–2 (the composability theory) go unharvested — at which point pg_cordis is just "tools in a database" and requirement 2's premise weakens. Requirement 1 is therefore a *design constraint on the contract*, not an afterthought.

## Obstacles

Ranked by severity:

1. **Language and paradigm gap.** TypeScript async + zod + closures → PL/pgSQL is not mechanical. The capability families (`lsp/`, `terminal/` PTYs, `subprocess/`, `code-runtime/` worker threads, `e2b/`, `sandbox/` bwrap/Landlock/Seatbelt) are process-bound by nature; they cannot live inside the server. The realistic split is: orchestration/state/retrieval plugins migrate; process-bound capability families stay host-side and appear to pg_cordis as *remote service providers* — which the contract must then also accept (a gap in the table above, flagged for B/D).
2. **No `node:vm`.** Dynamic plugin definitions (the `tool-cordis` self-modification story) have no safe PG equivalent. Candidates: static SQL scanned from catalog (proven, but no runtime definition); `plsh` (bundled in pgembed — but that is a shell in the database); `DO` blocks (unsafe for this); trusted languages (unproven here); C extension (heavyweight, compile-time). DSH's sandbox also provides a *guarded context facade* (`guard.ts`: read-only proxy, `denyContext()`, only declared injects visible) — PG has no analogous capability wall for in-database code.
3. **Event model mismatch.** DSH events have five dispatch modes with lifecycle-owned listeners; triggers are synchronous and transactional (stronger consistency, weaker expressiveness), `LISTEN/NOTIFY` is fire-and-forget with no delivery guarantee. `bail`/`waterfall` need kernel functions built from scratch.
4. **Long-running loops pin sessions.** pg-agent's `rlm_loop` runs synchronously in the caller's session (`v2/pg_agent_rlm.sql`); DSH fibers are concurrent runtimes. Background execution in PG means worker polling (the `worker()` pattern) or extensions (`pg_cron`). The contract must not assume plugins are short SELECTs — but it also cannot assume they can sleep.
5. **Global catalog vs per-session runtime.** SQL objects are database-global; DSH fibers are per-runtime. pg-agent papers over this with the `rlm.run_id` GUC + session TEMP VIEWs (`session_scope='current_session'` in the workbench contract). Multi-tenant plugin *visibility* is unsolved and directly feeds Topic D.
6. **Security surface.** `worker()` dispatches via `EXECUTE format(...)` — the injection-surface pattern is already present; a richer contract multiplies it. DSH's vm traps (redirected `require`/`fetch`, timeouts via `vmTimeoutMs`) are stronger than anything offered to PL/pgSQL.
7. **Ecosystem and tooling.** DSH plugins are npm packages with per-file 100%-coverage gates (`.agents/notes/` culture) and group READMEs owning package/ctx-key maps (`packages/README.md`). SQL has no package manager, no test-harness convention, and versioning only via extension script files. Migration tooling (DSH manifest → SQL skeleton) does not exist.
8. **Performance is unmeasured.** PL/pgSQL interpretation vs V8, per-call parsing vs warm closures. Opinion: acceptable for orchestration-tier plugins (the LLM call dominates anyway — `http_call_llm` is already the bottleneck in `rlm_loop`), risky for hot data-path plugins. Needs a budget, not a guess.

## Already in Postgres / pgembed / pg-agent vs must build

| Capability | Status | Where |
|---|---|---|
| Temporal composability (effect inverses) | **have** | PG core: transactions, savepoints, transactional DDL |
| Reactive notification (coeffect reactivity) | **partial** | PG triggers; no cross-provider dependency re-evaluation yet |
| Isolation realms / interception | **have (as primitives)** | PG schemas, roles, RLS — unwired into any plugin contract |
| Event bus | **partial** | triggers + `LISTEN/NOTIFY`; no ordered/durable/5-mode bus |
| Durable append-only session log | **have** | WAL; pg-agent `agent_steps` (append-only `llm/tool/final/error`) + `run_state()` fold is the schema precedent |
| Job queue + dispatch | **have** | pg-agent v2: `jobs`/`handlers`/`worker()` (`FOR UPDATE SKIP LOCKED`); scheduling via bundled `pg_cron` |
| Plugin registry, authoring, validation, tool rendering | **have (two flavors)** | pg-agent v2: `job_handler` and `workbench_plugin` COMMENT contracts, `refresh_*()` scanners/validators, `render_workbench_tools()` |
| Agent loop in-database | **have** | pg-agent v2 `rlm_loop`, `fold_rlm_messages`, `rlm_spawn`/`codeact_spawn`, `env_*` variable API over `rlm_vars` |
| LLM transport | **have** | `http` extension (`http_call_llm`); pgembed bundles `pg_net`/`pgsql_http` |
| Retrieval stack | **have** | pgembed: `pgvector`, `vectorchord`, `psql_bm25s`, `age`, `timescaledb` |
| Attested PG distribution | **have** | pgembed wheel: content-addressed stamp, `build-metadata.json` (schema v1), `validate_bundled_binaries()`, `get_server()`/`PostgresServer` host API |
| Packaging path for pg_cordis itself | **have (a path, not done)** | four edit sites: `pgbuild/Makefile` (source pin + build rule + `EXTENSIONS`), `tools/generate_bundle_metadata.py` (`EXTENSIONS` dict), `src/pgembed/__init__.py` (`EXTENSION_PACKAGES`/`EXTENSION_SO_FILES`/create-name map), optional standalone `src/pgembed_pg_cordis/` package (pattern: `src/pgembed_pgvector/`) |
| **Unified plugin contract** (one metadata vocabulary spanning both invocation models, with `inject`/`provide`/`capability`/`session_scope`/config schema) | **must build** | the core deliverable; pg-agent's two COMMENT flavors are the starting vocabulary |
| Dependency (coeffect) registry + reactivation scan | **must build** | generalizes `refresh_*()` into dependency-aware activation ordering |
| Event propagation kernel (5-mode semantics or a chosen subset) | **must build** | no precedent in any of the repos |
| Undo/compensation for effects that escape the transaction (HTTP calls, files — the paper's "outside" locations) | **must build** | transactions only cover "inside" locations |
| Remote/host-side service providers as plugin citizens | **must build** | for the process-bound capability families (`lsp/`, `terminal/`, `subprocess/`, …) |
| Per-session / per-tenant plugin visibility | **must build** | current workaround: `rlm.run_id` GUC + TEMP objects; feeds Topic D |
| DSH→SQL migration tooling + SQL plugin packaging/versioning/test conventions | **must build** | nothing exists |
| Dynamic in-database plugin code | **must build or must defer** (T4) | explicitly unresolved |

## Key tradeoffs (opinion, not decision)

Analyzed in turn. Each ends with my opinion — none of these is a decision, and the extension-vs-plugin split explicitly remains open.

**T1 — Authoring surface.** Options: (a) `COMMENT`-embedded JSON, pg-agent style; (b) registry tables as the primary authoring surface; (c) everything is a C extension. Analysis: (a) has the strongest precedent (two proven scanners), keeps metadata next to the object, but comments are invisible to FKs and easy to orphan; (b) is queryable and constraint-friendly but splits definition from body; (c) maximizes power, minimizes authorability — contradicts the SQL-first hypothesis. *Opinion: author in (a), compile into (b* via the `refresh_*()` pattern — *the pg-agent shape is already this hybrid — and reserve (c) for what SQL demonstrably cannot do. The compiled-table step is what makes dependency reasoning (T2) possible at all.*

**T2 — Contract fidelity.** Options: (a) port the full DSH vocabulary (`inject`/`provide`/`intercept`, events, fiber state machine) as first-class enforced objects; (b) minimal function+tool descriptor only. Analysis: (b) forfeits the richness — requirement 1 fails for service-family plugins; (a) in full is a big kernel to build before anything migrates, and the fiber state machine (`PENDING…UNLOADING`) has no natural SQL resident. *Opinion: keep the* metadata vocabulary *complete from day one (all DSH fields representable), but let enforcement be progressive — validate structure like `refresh_workbench_tools()` does today, enforce dependency ordering later, and map fiber states onto coarse loaded/valid flags rather than the full machine. Richness preserved as data costs little; richness enforced as runtime costs a kernel.*

**T3 — Temporal composability mechanism.** Options: (a) rely on transactions as the inverse accumulator; (b) build an explicit compensation ledger alongside. Analysis: (a) is the database-unique advantage and covers all "inside" effects (rows, DDL, temp objects); but DSH plugins also cause "outside" effects — HTTP calls (LLM providers), spawned processes — which a transaction cannot revert, and the paper is explicit that outside locations are neither tracked nor recovered. (b) re-imports the machinery we just argued PG obviates. *Opinion: transactions first, unconditionally; add a narrow compensation ledger only for declared outside-effects (e.g. an `http` provider row recording an inverse action), and treat every ledger entry as evidence the contract leaked a side effect past the database.*

**T4 — Dynamic plugins now vs later.** Options: (a) ship a dynamic path in v0 (`plsh` or trusted languages); (b) static registration only, dynamic deferred. Analysis: (a) answers DSH's runtime self-modification story immediately but is the single riskiest surface (shell-in-DB, no capability wall comparable to `guard.ts`); (b) is provably sufficient for the tool surface (pg-agent evidence) but leaves `tool-cordis`-class plugins unlandable — a real requirement-1 gap, temporarily. *Opinion: defer, and say so loudly in the contract (reserve a `dynamic` capability key). Revisit after Topic D — retrieval-scoped isolation is a precondition for ever running untrusted code in-database. The interim landing spot for self-modification is host-side, same as the browser half.*

**T5 — Kernel packaging.** Options: (a) versioned SQL schema files installed like pg-agent's `v2/*.sql`; (b) C extension from day one; (c) pgembed-bundled artifact. Analysis: the contract is still moving (T1–T4 unresolved); C rebuilds are slow and pgembed bundling is a release discipline (four edit sites, attestation pins) premature for experiments. pg-agent's plain-SQL iteration loop is exactly what contract-finding needs. *Opinion: (a) now, promote hot paths to (b) when profiling justifies, adopt (c) at stability. This is also the honest reading of "SQL-first": it is an iteration-speed claim as much as an authoring claim.*

**T6 — UI/browser halves.** Options: (a) fold client plugins into the pg_cordis contract; (b) exclude them, define only a host↔client seam. Analysis: browser React plugins cannot be SQL; pretending otherwise corrupts the contract. DSH already separates halves (`cordis-host-runner` vs `cordis-client-runner`, `host/` vs `client/` groups) — the seam exists to be copied. *Opinion: (b). The pg_cordis contract covers host-half concerns; the seam (what state changes the client observes) is a Topic B projection question, not a plugin question.*

**T7 — One registry or two invocation models.** Options: (a) force one dispatch model; (b) two models, two metadata keys (pg-agent today); (c) two models, one metadata schema. Analysis: (a) loses queue semantics or session semantics — pg-agent's mutual-exclusion rule exists because they genuinely conflict; (b) fragments the vocabulary requirement 1 wants unified; (c) costs one schema, keeps both lifecycles. *Opinion: (c) — one metadata vocabulary with an `invocation` discriminator (`queue` | `session_select`), keeping pg-agent's mutual-exclusion per-object rule. Cheapest unification available; revisit only if a third model appears (e.g. event-triggered plugins).*

## Open questions for B/C/D

For **B** (persistence, projection, plugin contract over the log):

- Which parts of DSH's `SessionPersistence` abstract API (`locate/create/append/load/inspect/readFrom/list/listSnapshots` — `packages/session/session-persistence/src/index.ts`) become pg_cordis contract *seams* (i.e. plugin-touchable), and which dissolve into WAL/table primitives?
- Does `PersistenceCoordinator`'s torn-tail repair survive at all once WAL owns durability, or does it reduce to transaction discipline (DSH's own turn-enclosure invariant note already anticipated "a future backend (SQLite/WAL) inherits the same clean boundary")?
- Is `session-projection` a pg_cordis plugin category (plugins may touch the projection layer — per B guidance), and what metadata marks a projection plugin vs a log plugin?
- Do DSH's producer-enforced log invariants (e.g. `Session.append` throwing on non-serializable data) become constraints/triggers, or convention?

For **C** (CodeAct + RLM on pg_cordis):

- Is the paradigm loop a *plugin* (DSH's `core/agent-loop` is a plugin behind the `agent` seam) or kernel? pg-agent currently hardcodes `rlm_loop` in SQL — is that the contract or an accident of v2?
- How do loops consume the plugin contract — is prompt-side tool injection (`render_workbench_tools()` called from `make_da_prompt`) the pattern, and does it generalize to CodeAct?
- Does recursion (`rlm_spawn`/`codeact_spawn` child runs in `rlm_children`) interact with the event model or bypass it?

For **D** (isolation):

- Plugin visibility per session/tenant: global catalog vs session scope — today's workaround is the `rlm.run_id` GUC + TEMP VIEWs; is that a footnote or the design?
- Do Cordis isolation realms (`Σ^iso`) map to schemas, RLS, or `search_path` — and does the mapping change once retrieval is scoped ("project 1's code for function 1; project 2's code for functions 2–3") rather than workspace-shaped?
- Where could dynamic plugin code (T4, deferred) eventually run such that retrieval-range isolation still holds?

Cross-cutting: feasibility of a DSH-manifest→SQL migration translator; versioning/upgrade conventions for SQL-distributed plugins; a performance budget separating orchestration-tier from data-path plugins; test-harness conventions for SQL plugins.
