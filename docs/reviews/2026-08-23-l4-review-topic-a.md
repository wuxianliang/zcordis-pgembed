# L4 Review — Topic A: DSH plugin migration to pg_cordis

Reviewer: design-agent (L4 substitute; oracle unavailable) · Turn 1 · Date: 2026-08-23
Report under review: `docs/analysis/2026-08-23-a-dsh-plugin-migration-to-pg-cordis.md`
Rubric: `prompt-exports/loop-orchestrate-pg-cordis-research-runs.md` (frozen; Topic A sections)

## Verdict: **PASS**

All five rubric criteria are satisfied. Spot-checks of load-bearing citations across `deepseek-harness`, `pg-agent`, and `pgembed` found no invented APIs and no false claims; two trivial citation-path drifts are noted below (neither is rubric-violating).

## Context / Scope

Reviewed the full report (172 lines) against the frozen rubric. Verified file citations read-only in the three referenced roots by direct search plus two explore-probe sweeps (deepseek-harness session plane; pg-agent v2 SQL; pgembed packaging). No changes made to the report.

## Findings — rubric criteria

### 1. File path — PASS

File exists at exactly `docs/analysis/2026-08-23-a-dsh-plugin-migration-to-pg-cordis.md`, matching the Turn 1 deliverable path in the rubric table.

### 2. Required headings verbatim — PASS

All seven Topic A headings present as exact `##` headings, in rubric order:

| Required heading | Report line |
|---|---|
| `## DSH plugin surface to migrate` | 32 |
| `## What pg_cordis would need to accept` | 68 |
| `## Database-unique value (why migrate, not reuse)` | 92 |
| `## Obstacles` | 105 |
| `## Already in Postgres / pgembed / pg-agent vs must build` | 118 |
| `## Key tradeoffs (opinion, not decision)` | 143 |
| `## Open questions for B/C/D` | 161 |

### 3. Concrete files/modules, no invented APIs — PASS

Spot-checked the load-bearing citations. Every checked API, constant, and quote is real:

| Claim in report | Check result |
|---|---|
| Six Cordis kernel files `vendor/cordis/src/{registry,context,service,fiber,events,reflect}.ts` | all six exist |
| `events.ts` five dispatch modes | verbatim: `DispatchMode = 'emit' \| 'parallel' \| 'serial' \| 'bail' \| 'waterfall'` (events.ts:32) |
| `fiber.ts` state machine incl. `UNLOADING`; `internal/update` waterfall | present (fiber.ts:153, 728–748) |
| `registry.ts` `@Inject` decorator, inject map, intercept config | present (registry.ts:37–47) |
| `packages/README.md` quote "contribute through `ctx.effect()`, `ctx.on()`, or `ctx.waterfall()`" | verbatim at README.md:5 |
| Bug-note quote "Cordis activates plugins by service availability, not configuration order" | verbatim in the note (see path drift below) |
| `tool-cordis` five tools `cordis_inspect/define/run/stop/undefine` | confirmed (extensions README + slot-catalog) |
| `cordis-host-runner`: `createSandbox()`/`evaluateHostCode()`/`precheckCode()` in `sandbox.ts`; `missingServices(ctx, fiber)` in `lifecycle.ts:55`; `guard.ts` `denyContext()`; `vmTimeoutMs` | all confirmed |
| `SessionPersistence` abstract API `locate/create/append/load/inspect/readFrom/list/listSnapshots` | confirmed in `packages/session/session-persistence/src/index.ts` |
| `JsonlSessionPersistence`: `static inject = ['sessions']`, zod Config, zstd, temp file + `link()` + dir fsync | all confirmed |
| `MAX_PACKED_ROW_MEMBERS = 1024` (sqlite codec); WAL default | confirmed (`codec.ts`; `journalMode: 'wal'`) |
| `DEFAULT_WRITE_BATCH_MAX_DELAY_MS = 200`; torn-tail repair in `PersistenceCoordinator` | confirmed (`coordinator.ts`) |
| pg-agent `refresh_workbench_tools()`: validates `name==proname`, `returns='jsonb'`, `session_scope`, `capability ∈ ('read_only','temp_view_mutation')`, RAISEs on `workbench_plugin`+`job_handler` co-occurrence; `render_workbench_tools()` | all confirmed in `v2/pg_agent_workbench_core.sql` |
| pg-agent `worker()`: `FOR UPDATE SKIP LOCKED` + `EXECUTE format('SELECT %s($1)', v_fn)` | confirmed in `v2/pg_agent_functional.sql` |
| pg-agent `rlm_loop`, `fold_rlm_messages`, `rlm_spawn`/`codeact_spawn` → `rlm_children`, `env_*` over `rlm_vars`, `rlm.run_id` GUC | confirmed in `v2/pg_agent_rlm.sql` |
| pgembed `pgbuild/Makefile:33` retrieval stack | confirmed: `EXTENSIONS ?= pgvector vectorchord age psql_bm25s timescaledb pg_cron pg_net pgsql_http plsh …` (~lines 33–37) |
| pgembed packaging: `generate_bundle_metadata.py` EXTENSIONS dict, `EXTENSION_PACKAGES`/`EXTENSION_SO_FILES`, `validate_bundled_binaries()`, `src/pgembed_pgvector/` pattern | all confirmed |

The report's structural claims about pg-agent's two invocation models (queue-dispatch vs session-SELECT with scanner-enforced mutual exclusion) are accurate, not extrapolated.

### 4. Tradeoffs as options + analysis + opinion, not a decision — PASS

Seven tradeoffs (T1–T7) are enumerated up front and each analyzed as explicit options (a)/(b)/(c) ending in an italicized *Opinion*. The section opens with "none of these is a decision, and the extension-vs-plugin split explicitly remains open." Opinions are genuinely contestable positions (e.g. T4 defers dynamic plugins with a named revisit condition), not disguised decisions.

### 5. No "build this" architecture shipped as chosen — PASS

The header marks the whole document "analysis with opinions, not architecture decisions"; the element-mapping table is labeled "analysis, not a frozen design"; the extension-vs-plugin split is kept open per the locked working assumptions. The "must build" rows in the have/must-build table name capabilities, not a chosen design.

## Factual issues (minor, non-blocking)

1. **Archived note path.** The report cites `.agents/notes/bug-fix/2026-07-30-tui-adapter-registration-race.md`; the file actually lives at `.agents/notes/archived/bug-fix/2026-07-30-tui-adapter-registration-race.md`. Quote itself is verbatim-accurate.
2. **`session-query` location.** `packages/session-query/` is a top-level group, not under `packages/session/`. The report lists it correctly in the group enumeration and never asserts a wrong path, but the persistence-plane paragraph ("plus `session-projection`, `session-query`") could be misread as both living under `session/`.

Neither affects any argument in the report; no correction required for the rubric.

## Notes Topic B must inherit

1. **The report's B questions are well-grounded — answer them, don't restate them.** Specifically: which of the eight `SessionPersistence` methods (`locate/create/append/load/inspect/readFrom/list/listSnapshots`) survive as pg_cordis contract seams vs dissolve into WAL/table primitives; whether torn-tail repair reduces to transaction discipline; what metadata distinguishes a projection plugin from a log plugin; whether producer-enforced log invariants (`Session.append` serializability throw) become constraints/triggers or convention.
2. **Remote/host-side service providers are a flagged contract gap.** Topic A's obstacle #1 concludes process-bound capability families (`lsp/`, `terminal/`, `subprocess/`, `sandbox/`, `e2b/`) stay host-side and must appear to pg_cordis as remote providers — the mapping table does not yet cover this. B's log/projection contract should say how host-side providers write to and read from the log.
3. **The UI seam was handed to B.** T6's opinion excludes browser halves from the plugin contract and defines the seam as "what state changes the client observes" — explicitly a Topic B projection question. B must define that observation surface (or argue it back out of scope).
4. **Invocation-model vocabulary constraint.** T7's opinion (one metadata schema with an `invocation` discriminator, `queue` | `session_select`, keeping pg-agent's per-object mutual exclusion) constrains what a "plugin that touches the log/projection layers" can look like in B; if B needs a third model (e.g. event-triggered projection refresh), that is the named revisit condition.
5. **Precedent files B will reuse.** pg-agent's `agent_steps` append-only table + `run_state()` fold (in `v2/pg_agent_functional.sql` — note: not in `pg_agent_rlm.sql`) is the cited schema precedent for log-as-SoT; DSH's `PersistenceCoordinator`/JSONL/SQLite machinery is the emulation baseline the database supersedes.

## Recommendation

Accept the Topic A report as-is; proceed to Turn 2 (Topic B). Optionally fix the two minor citation drifts in a later editorial pass — do not block on them.
