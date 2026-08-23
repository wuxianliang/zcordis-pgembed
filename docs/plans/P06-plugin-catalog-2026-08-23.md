# P06 — 插件目录: Plan

Date: 2026-08-23  
Status: **ready to implement**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P06  
Depends on: P00 (`docs/plans/P00-sql-source-2026-08-23.md`, implemented)  
Originally parallel with: P01, P02 — **both now implemented** (`sql/0001_p01_claim.sql`, `sql/0002_p02_log.sql`)  
Contract: D8; T1 COMMENT→refresh compiled registry  
Primary deliverable: `sql/0006_p06_plugin_catalog.sql`  
Baseline export: `prompt-exports/oracle-plan-2026-08-23-174556-p06-plugin-catalog-d-42f5.md`  
Review context: `docs/reviews/2026-08-23-p00-plan-critique.md`  
Critique: `docs/reviews/2026-08-23-p06-plan-critique.md`

**Landing state (after P01/P02):** product tree is `0000_kernel.sql` + `0001_p01_claim.sql` + `0002_p02_log.sql`; marker `'p02'` (`sql/README.md:39-44`). `tests/conftest.py` exists (`run_apply`, `psql`, `next_sql_prefix`, `load_apply_module`). P01 W09 landed: `tools/apply_pg_cordis.py` `sanitize_sql_for_preflight` / `strip_sql_dollar_quotes` (`:206-208`, `:217`). `cordis.jobs` and `cordis.agent_steps` exist. P06 still does **not** take a runtime dependency on those tables (queue plugins still must not require a `jobs` argument). Filename remains `sql/0006_p06_plugin_catalog.sql` (gap after `0002` is allowed). Combined-tree version assertions that currently pin `'p02'` become `'p06'`. P02-only temp trees (`0000+0002`) stay `'p02'`.

**Mid-flow (2026-08-23):** host authoring = `host_plugin_definitions` + `register_host_plugin` (no stub functions). `session_select` remains a v0 CHECK value. `required_grants` are **kinds only** (`run` / `named_corpus` / `event`) — P07 issues concrete `named_corpus:<id>` / `event:<scope>`. Keep the effect/retry/reconciliation cross-field CHECK matrix.

## Goal

Add a schema-qualified, queryable plugin catalog to `zcordis-pgembed` without a second queue, a DSH compatibility runtime, or an extension-per-plugin model.

P06 creates:

- compiled consumer table `cordis.plugin_catalog`;
- durable host-source table `cordis.host_plugin_definitions`;
- one metadata vocabulary for in-database and host-side plugins;
- `cordis.refresh_plugins()` — scan `cordis` function COMMENTs and host definitions, validate every candidate, atomically rebuild the compiled catalog;
- `cordis.register_host_plugin(jsonb)` / `cordis.unregister_host_plugin(text)` for host tools with no SQL body;
- schema marker `cordis.get_schema_version() → 'p06'`.

Catalog fields: identity, version, locus, invocation, required-grant declarations, effect class, retry class, reconciliation, DSH `inject`/`provide`/`intercept`/`capability`/`session_scope`/`config`, source provenance, optional SQL entrypoint.

**v0 proof:** register one host-tool definition through SQL → refresh into `cordis.plugin_catalog` → SELECT the compiled row. No host SDK, no real `apply_edits`, no jobs worker, no `node:vm`.

P06 does **not** implement grant issuance (P07), four-seam enforcement (P08), worker loop (P09), host SDK verbs (P10), paradigm policy packs (P19), wait/events (P03), claim (P01), or log (P02).

## 中文摘要

P06 在 `sql/` 增加 `0006_p06_plugin_catalog.sql`：统一编译表 `cordis.plugin_catalog` + 宿主源表 `cordis.host_plugin_definitions`。库内插件以 `cordis` 函数的 `COMMENT` JSON 为源；宿主工具没有 SQL 函数体，用同一套 `cordis_plugin` JSON 写入源表，再由同一个 `cordis.refresh_plugins()` 编进目录。目录按 `identity` 唯一。`required_grants` 只存种类（`run` / `named_corpus` / `event`），具体 corpus/event id 由 P07 签发。刷新先完整校验再重建；非法 COMMENT、重复 identity、互斥 invocation 失败时保留旧目录。P06 不发 grant、不执行工具、不把 catalog 绑到 `cordis.jobs` 签名。当前树已是 `0000+0001+0002`（标记 `p02`）；P01 W09 与 `tests/conftest.py` 已落地，**不要再改 loader**。`0006` 函数体仍须把 GRANT/END 等敏感词放在 `$$` 内。

## Execution index

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W60 | Compiled catalog + host-source DDL | Fresh apply of `0000+0001+0002+0006` creates both catalog tables with the columns, CHECKs, and indexes below; `jobs`/`agent_steps` remain; no `public` tables | `sql/0006_p06_plugin_catalog.sql` | P00 | Medium |
| W61 | Unified metadata validator | `_validate_plugin_definition(jsonb,text)` accepts valid in-db or host JSON, normalizes defaults, rejects invalid enums/grants/shapes | `sql/0006_p06_plugin_catalog.sql` | W60 | Medium |
| W62 | Atomic unified refresh | `refresh_plugins()` scans only `cordis` `pg_proc` plus host rows, mutex, validate-then-`DELETE`, prior rows survive failure | `sql/0006_p06_plugin_catalog.sql` | W60–W61 | Large |
| W63 | Host-tool register/unregister | `register_host_plugin` / `unregister_host_plugin` update source + refresh in one transaction; host row has `entrypoint IS NULL` | `sql/0006_p06_plugin_catalog.sql` | W61–W62 | Medium |
| W64 | Version marker + apply-time refresh | `get_schema_version() → 'p06'`; file ends with `SELECT cordis.refresh_plugins();`; reset and in-place replay succeed | `sql/0006_p06_plugin_catalog.sql` | W62–W63 | Small |
| W65 | Retarget current-tree tests for catalog + `'p06'` | Product-tree file list includes `0006`; `KERNEL_FUNCTIONS` gains the four P06 names; combined-tree version `'p02'`→`'p06'` in P00/P01/P02 full-tree tests; P02-only temp trees stay `'p02'`; **no** loader edit | `tests/test_p00_sql_source.py`, `tests/test_p01_claim.py`, `tests/test_p02_agent_steps.py`, `sql/README.md` | W60–W64 | Medium |
| W66 | P06 catalog tests | Named tests in `tests/test_p06_plugin_catalog.py` all pass via `uv run pytest`; no `import` of `tools/` | `tests/test_p06_plugin_catalog.py` | W60–W65 | Medium |

## Background

Curated from Phase 2 explores and the P00/P01 plans. Spot-checked against current code.

### Parent skeleton

`docs/plans/2026-08-23-pg-cordis-development.md:166-174`:

- **Depends on P00. Parallel with P01, P02.**
- **Contract:** D8; T1 COMMENT→refresh 进表.
- **Decide here:** identity, version, locus (`in-db` / `host`), required grants, effect class, retry/reconciliation.
- **Do:** one metadata set; `invocation` distinguishes queue / host-tool; register, query, mutex.
- **Do not:** `node:vm`; DSH migrator; one EXTENSION per plugin.
- **Done when:** insert one host-tool description and query it via SQL.

Do not reopen D1–D9 or snapshot §4 (`development.md:18`). No `CREATE EXTENSION` in P00–P19 (`development.md:21`). SQL namespace is schema `cordis` (`development.md:20`).

Downstream (consume catalog; do not implement here):

| Later item | What it reads |
|---|---|
| P07 (`development.md:178-186`) | `required_grants` declarations; live grant rows are P07 |
| P08 (`development.md:190-198`) | identity + grants at tool dispatch |
| P09 (`development.md:216-224`) | `locus = in-db` only |
| P10 (`development.md:227-235`) | 查目录; first SDK language is P10 |
| P16 (`development.md:87`) | `effect_class` / retry / reconciliation for D2 |
| P19 (`development.md:202-212`) | paradigm policy rows against this vocabulary |

### Signed contracts

- D8 (`docs/decisions/2026-08-23-pending.md:412-415`): **A** + 最小插件目录. Host uses the same SQL verbs (claim / checkpoint / yield / sleep / await) **and looks up** identity, locus, required grants, effect/retry class. No DSH event layer, no manifest→SQL migrator, no postponed host path, no `node:vm`.
- D8 signed (`docs/analysis/2026-08-23-h-vision-d1-d9-oracle-verdicts.md:32`, `:49`): coding agent **is** the host locus.
- D7 (`docs/analysis/2026-08-23-i-architecture-snapshot.md:99`): SQL in this repo; plugins are not each an EXTENSION.
- D5 (`snapshot.md:97`): live grant enum `run` / `named_corpus:<id>` / `event:<scope>`; slice-bound; model only requests. Catalog **declares kinds** (`run` / `named_corpus` / `event`); P07 **issues** the concrete IDs and binds slices. A plugin row must not bake a corpus UUID or event scope.
- Snapshot §10.3 (`snapshot.md:234`): catalog **field names** were left open at architecture close — this plan names them. Host SDK first language is P10.
- Snapshot §10.5 (`snapshot.md:236`): `named_corpus` versioning is **not** plugin-catalog versioning.

### Working hypotheses (snapshot §5; change requires pending revision)

`docs/analysis/2026-08-23-i-architecture-snapshot.md:104-117`:

- **T1** COMMENT JSON is source; `refresh_*()` compiles into tables.
- **T2** metadata vocabulary complete day one; enforcement progressive.
- **T3** in-DB effects revert via transactions; outside effects use D2 call/result — no second compensation ledger. Catalog classifies; it does not implement D2.
- **T4** dynamic plugins deferred (same as D8).
- **T6** UI halves outside kernel.
- **T7** one vocabulary; `invocation = queue \| session_select` (或 host-tool); **per-object mutex**.
- Loop kernel vs paradigm policy packs: P19 registers two policies; P06 must not freeze paradigm `if-else` in the kernel.

A-doc opinions §5 adopted (`docs/analysis/2026-08-23-a-dsh-plugin-migration-to-pg-cordis.md:137-149`):

- T1 hybrid: author in COMMENT, compile into tables.
- T2: DSH fields representable (`inject`/`provide`/`capability`/`session_scope`/config); enforce later.
- T7: do not force one dispatch model; do not keep two disconnected JSON keys. One schema + `invocation`. pg-agent mutex exists because queue vs session-select conflict (`a.md:80`, `:148`).
- Host/process-bound families cannot live in the server (`a.md:99`); contract must accept **remote/host-side providers as plugin citizens** (`a.md:128`). That is why done-when is a **host-tool row**, not a `wb_*` function.

**T1 vs host-tool:** COMMENT-on-`pg_proc` needs a SQL function. Host tools have no SQL body. P06 uses a second **source adapter** (`host_plugin_definitions`) with the **same** JSON vocabulary — not a second metadata contract, not a stub function P09 could dispatch, not a DSH migrator.

### P00 install contract

P00 kernel is still `sql/0000_kernel.sql:5-14` (schema `cordis` + `get_schema_version()`). Current **product** marker is `'p02'` from `0002` (`sql/README.md:39-44`; `sql/0002_p02_log.sql` end). Product name is pg_cordis; schema cannot be `pg_cordis` (`sql/README.md:47-48`).

Append only: later Px add numbered files; never edit `0000_kernel.sql`, `0001_p01_claim.sql`, or `0002_p02_log.sql`. Discovery: direct children matching `NNNN_slug.sql`; unique numeric prefix; **gaps allowed** (`sql/README.md:9-17`; `tools/apply_pg_cordis.py:17`, `:44-80`). Nested `.sql` rejected (`:48-54`).

`0001` and `0002` are landed. P06 uses `sql/0006_p06_plugin_catalog.sql` so prefixes do not collide.

Every numbered file (`sql/README.md:29-35`; `apply_pg_cordis.py:21-35`):

- replay-safe inside one tree-wide `--single-transaction` (`apply_pg_cordis.py:319-325`)
- schema-qualified `cordis.*`, independent of `search_path`
- no `\connect` / `GRANT` / `CREATE EXTENSION` / `CREATE TABLE public.*` / `CREATE SCHEMA absurd` / role DDL / transaction-control / psql meta-commands
- no pg-agent `public` objects; same PGDATA, **separate databases**

Preflight runs **before** any DB mutation (`:210-224`) via `sanitize_sql_for_preflight`. Advisory lock `pg_advisory_xact_lock(hashtext('pg_cordis.apply'))` (`:320`) — no timeout. `verify_bootstrap` (`:328-359`) only checks schema `cordis` and `get_schema_version()` identity `|text`; it does **not** pin the returned string.

Preflight **already permits** `CREATE TABLE cordis.*` (`FORBIDDEN_STMTS` only bans `CREATE TABLE public.*` at `:30`). `test_sql_tree_has_no_forbidden_tokens` (`tests/test_p00_sql_source.py:379-394`) already requires later tables to be `cordis.*` and scans with `sanitize_sql_for_preflight`.

### Loader: W09 already landed — do not retouch

`FORBIDDEN_STMTS` still treats statement-level `END;` as transaction control (`apply_pg_cordis.py:31-34`) and `\bGRANT\b` / `\bREVOKE\b` anywhere (`:26-27`). P01 already strips dollar-quoted bodies (`sanitize_sql_for_preflight` / `strip_sql_dollar_quotes`, `:206-208`, used at `:217`). **P06 must not edit `tools/apply_pg_cordis.py`.** Keep the writing rule: `0006` plpgsql uses outer `$$`, no nested dollar tags, no adjacent `$$` in the body; GRANT/REVOKE/BEGIN/END words live only inside dollar-quotes or SQL comments. Existing test `test_plpgsql_end_inside_dollar_quotes_applies` covers the `END;` hole.

### Tests that change when `0006` lands

`tests/test_p00_sql_source.py` (already P02-shaped):

- `:40-115` `test_fresh_apply_lists_current_tree_and_p02`: file list `0000,0001,0002`; version `'p02'`; `jobs` and `agent_steps` present; `KERNEL_FUNCTIONS` (`:23-37`) is an **exact** `proname` list. Rename to `…_and_p06`; file list adds `0006_p06_plugin_catalog.sql`; version `'p06'`; keep `jobs`/`agent_steps`; add P06 function names to `KERNEL_FUNCTIONS` (exact list, `ORDER BY 1`).
- `:379-394` forbidden-token scan already allows `cordis.*` tables — keep; `0006` must pass it.
- `:143+` probe tests already use `next_sql_prefix` (`tests/conftest.py:60-66`) — keep; do not hard-code `0001`/`0006`.
- `:484` composition pins `'p02'` → `'p06'`.

`tests/test_p01_claim.py`: `_ensure_p01` applies the **product** tree; `:130` and `:495` pin `'p02'` → `'p06'`.

`tests/test_p02_agent_steps.py`:

- `_ensure_full` / `P02_DB` applies the product tree; `:337` pins `'p02'` → `'p06'`.
- `_apply_p02_only` / `test_p02_fresh_apply_catalog_and_version` (`:109-113`) is `0000+0002` **without** `0006` — keep `'p02'`.

Reuse `tests.conftest` helpers. Do not duplicate them in `test_p06_plugin_catalog.py`. Do not `import tools.apply_pg_cordis` (the P00 test’s `load_apply_module()` file-location load is the existing exception for scanning `FORBIDDEN_STMTS`).

### pg-agent precedent (other database, `public` — not copy target)

**Queue / `job_handler`** — `pg-agent/v2/pg_agent_functional.sql`:

- `handlers (job_type text PK, fn regproc NOT NULL)` `:303-306`.
- `refresh_handlers()` TRUNCATE-first + INSERT from `public` `pg_proc` where comment `~ '^\s*\{'` and jsonb `? 'job_handler'` `:309-327`.
- JSON key only `job_handler`. No version, locus, grants. A trimmed comment that does **not** start with `{` is skipped. A `{`-prefixed **invalid** JSON is **not** silently skipped: the `::jsonb` cast raises **after** `TRUNCATE` (`:315-323`). That is the defect P06 must not copy (validate-then-rebuild).
- Worker `EXECUTE format(...)` is **P09**, not P06.

**Session-SELECT / `workbench_plugin`** — `pg-agent/v2/pg_agent_workbench_core.sql`:

- `workbench_tools (tool_name PK, plugin_name, fn regprocedure, metadata jsonb, refreshed_at)` `:22-28`.
- Scan all `public` JSON comments, filter in PL/pgSQL `:103-124`.
- **Mutex:** both `workbench_plugin` and `job_handler` → `RAISE EXCEPTION` `:15-16`, `:126-128`.
- Validate **all** candidates, then `TRUNCATE`+`INSERT` `:204-209`; any exception rolls back, old table kept `:9-10`.
- Enforced `llm_tool`: `name` == `proname`; description ≤500; args match `proargnames`/`proargtypes`; `returns` == `jsonb`; `session_scope` == `current_session`; `capability` ∈ (`read_only`, `temp_view_mutation`) `:143-189`.
- Stale `fn` omitted at **render** by joining `pg_proc` `:222-227`. P06 has no render function; stale compiled rows last until the next successful refresh.

Scan namespace today is `public`. P06 scans **`cordis` only**.

`session_scope='current_session'` is a pg-agent DA/TEMP VIEW invariant. Snapshot D1 retires `pg_temp` DA (`snapshot.md:90`). P06 **represents** `session_scope` and defaults it to `run`; it does **not** freeze `current_session` as the only legal value.

### DSH vocabulary (roles, not TS reuse)

`deepseek-harness/vendor/cordis/src/registry.ts:100-111` `Plugin.Base`: `name?`, `Config?`, `inject?`, `provide?`, `intercept?`.

Store as JSONB (T2 representable, unenforced). `intercept` and fiber states have no pg-agent precedent. Dynamic `node:vm` is T4/D8 deferred.

### Isolation «locus» is not plugin locus

`docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md:77,87` uses «locus» for enforcement/budget. Plugin `locus` values are only `in-db` | `host`.

### Plan-shape and critique pitfalls

Match P00: Goal, 中文摘要, Execution index, Background, Current-state, Design, Verification with commands, Open questions, References.

Do not repeat (`docs/reviews/2026-08-23-p00-plan-critique.md`): drop the GRANT ban; drop append-only policy; weaken absence assertions; pytest extra vs `[dependency-groups] dev`; `import tools`; unpinned lock literal; silent lock timeout; ban `\` without a grep.

---

## Current-state analysis

### Existing responsibilities and ownership

| Component | Responsibility today | P06 consequence |
|---|---|---|
| `sql/0000_kernel.sql` | Schema `cordis` + `get_schema_version()` | Unchanged; P06 appends `0006` and replaces only the version-function **body** (`'p06'` wins over `'p02'`) |
| `sql/0001_p01_claim.sql` | `cordis.jobs` + claim verbs | Unchanged. Catalog does not require a `jobs` argument on queue plugins |
| `sql/0002_p02_log.sql` | `cordis.agent_steps` + emit/checkpoint | Unchanged. P02 functions have no `{`-prefixed COMMENT; refresh must ignore them |
| `tools/apply_pg_cordis.py` | Discover, preflight (dollar-quote strip landed), one transaction, bootstrap identity | **No production change.** Discovery already accepts `0006` |
| `tests/test_p00_sql_source.py` | Current-tree `0000+0001+0002`, `'p02'`, exact `KERNEL_FUNCTIONS` | File list + version + function set grow for P06 |
| `tests/conftest.py` | Shared `run_apply` / `psql` / `next_sql_prefix` / `load_apply_module` | Reuse; do not fork helpers |
| pg-agent `handlers` / `workbench_tools` | Separate `public` registries in `da_agent` | Precedent only; not a dependency |
| DSH `registry.ts` | TS plugin metadata | Vocabulary only |
| Future P07–P10, P16, P19 | Grants, seams, workers, SDK, D2, paradigms | Read `cordis.plugin_catalog`; none implemented here |

### Current data/control flow

```text
tools/apply_pg_cordis.py
  → discover sql/NNNN_slug.sql
  → preflight all files (before Postgres/DB create)
  → get_server(pgdata)
  → create or reset target DB
  → pg_advisory_xact_lock(hashtext('pg_cordis.apply'))
  → apply 0000 (and later files) in --single-transaction
  → verify cordis + get_schema_version() identity |text
```

No product plugin registry exists. pg-agent (other DB):

```text
COMMENT job_handler     → refresh_handlers()          → public.handlers
COMMENT workbench_plugin → refresh_workbench_tools()  → public.workbench_tools
```

P06 product path:

```text
cordis function COMMENT JSON
  → cordis.refresh_plugins()
  → cordis.plugin_catalog (entrypoint regprocedure, source_kind=comment)

host JSON
  → cordis.register_host_plugin(jsonb)
  → cordis.host_plugin_definitions
  → cordis.refresh_plugins()
  → cordis.plugin_catalog (entrypoint NULL, source_kind=host_registration)
```

Downstream consumers query **only** `cordis.plugin_catalog`. The host source table is authoring state, not a second consumer registry.

### Reuse / do not duplicate

Reuse: numbered-file discovery; tree-wide transaction; `cordis` naming; `obj_description(p.oid, 'pg_proc')` scan; `regprocedure`; validate-all-before-rebuild; P00 `run_apply`/`psql`/`pgdata`/temp-tree; apply-time `SELECT refresh_*()`. pg-agent `setup_db.py` count-gate is **not** copied into SQL; W66 tests assert `refresh_plugins()` return values.

Do not copy: `public.handlers`, `public.workbench_tools`, either `refresh_*` name, `current_session` as the only scope, any `cordis.jobs` signature, a host SDK, TypeScript `RegistryService`, stub SQL bodies for host tools.

### Hard constraints

- Schema `cordis`; product name `pg_cordis`.
- Exactly one new numbered SQL file: `sql/0006_p06_plugin_catalog.sql`.
- No GRANT / EXTENSION / public tables / tx-control / psql meta-commands.
- Append-only: do not edit `0000_kernel.sql`.
- Must not assume `cordis.jobs`, `agent_steps`, `run_waits`, `run_events`.
- Catalog rows are declarative metadata. No row causes dynamic SQL, host execution, or plugin loading.
- `source_kind='comment'` ⇒ in-db SQL function; `source_kind='host_registration'` ⇒ no SQL entrypoint.
- Plugin `locus` ≠ isolation-doc locus.

---

## Design

### Resolved questions

| # | Question | P06 decision | Rationale |
|---|---|---|---|
| 1 | SQL filename | `sql/0006_p06_plugin_catalog.sql` | Gaps allowed (`sql/README.md:17`); P01 owns `0001` |
| 2 | Host-tool vs T1 | `cordis.host_plugin_definitions` + `register_host_plugin(jsonb)`; **no stub functions** | A fake SQL body would look executable to P09. Same `cordis_plugin` JSON + same compiler = second **source adapter**, not a second contract. Direct INSERT into the compiled table would be wiped on the next refresh |
| 3 | Identity / version / locus / invocation / mutex | PK = `identity`. `version` is required descriptive text, not part of the key. `locus`: `in-db`\|`host`. `invocation`: `queue`\|`session_select`\|`host_tool`. Legal pairs: in-db+queue, in-db+session_select, host+host_tool. One `cordis_plugin` per object; reject leftover `job_handler` / `workbench_plugin` keys | Single identity avoids v0 version-selection. Keeping `session_select` representable preserves pg-agent’s second family (T7). Scalar `invocation` **is** the mutex |
| 4 | T2 extra keys | JSONB columns `inject`, `provide`, `intercept`, `capability`, `config`; text `session_scope` default `run`; full original JSON in `metadata` | Representable day one; no fiber/dependency enforcement |
| 5 | Required grants | `required_grants text[]`; each element exactly `run`, `named_corpus`, or `event`; no duplicates; reject colon-suffixed D5 literals | Mid-flow: kinds only. Catalog says which grant families a plugin needs; P07 fills `named_corpus:<id>` / `event:<scope>` and binds slices. Baking a project id into the plugin row would couple plugins to one corpus |
| 6 | Effect / retry / reconciliation | `effect_class`: `read_only`\|`transactional`\|`external`. `retry_class`: `replayable`\|`idempotent`\|`non_retryable`. `reconciliation`: `none`\|`operation_key`\|`manual`. Cross-field rules in Component 1 | Classifies D2 without embedding retry **curves** (P04) or a compensation ledger (T3) |
| 7 | Refresh | One `cordis.refresh_plugins()`; scan `cordis` only; `pg_advisory_xact_lock(hashtext('pg_cordis.plugin_refresh'))`; validate-then-`DELETE FROM cordis.plugin_catalog` + bulk insert | One atomic view. Distinct from apply lock. No timeout (same as P00). `DELETE` not `TRUNCATE`: MVCC-safe for concurrent readers, ROW EXCLUSIVE not ACCESS EXCLUSIVE, no extra TRUNCATE privilege. Catalog is tens of rows; same test expectations |
| 8 | Version marker | `CREATE OR REPLACE get_schema_version()` body `'p06'` near end of `0006`, **before** final refresh | Numeric sort: `0006` wins over current `'p02'` from `0002` |
| 9 | Replay + tests | `CREATE TABLE IF NOT EXISTS` / `CREATE OR REPLACE`; final `SELECT cordis.refresh_plugins();`; product-tree file list is `0000,0001,0002,0006`; `'p06'` on that tree | `0000+0002` P02-only fixtures stay `'p02'` |
| 10 | Loader | **Do not edit** `apply_pg_cordis.py`. W09 already strips `$tag$` before `END;`/`GRANT` | Writing rule only: GRANT/END words inside `$$` in `0006` |

Rejected alternatives:

- Stub `cordis` SQL function + COMMENT for host tools — looks in-db-executable.
- Table-first as the **only** authoring surface — violates T1 for SQL-owned plugins.
- Two compiled tables (handlers + tools) — T7 rejected.
- PK `(identity, version)` — no v0 consumer has a selection rule (snapshot §10.5 is about corpus version, not this).
- Copy `session_scope='current_session'` as the only legal value — D1.
- Re-implement W09 in P06 — loader already strips dollar-quotes; a second preflight design would fork P01.
- Rebuild with `TRUNCATE` — pg-agent precedent, but MVCC-unsafe for concurrent snapshots, ACCESS EXCLUSIVE for the whole apply transaction, and needs TRUNCATE privilege. `DELETE` meets the same tests.

### Component 1: Compiled catalog and host source storage

#### `cordis.plugin_catalog`

**Kind:** persistent compiled registry. **Owner:** rebuilt only by `cordis.refresh_plugins()`. P10+ **read** this table. No P06 caller writes compiled rows directly.

| Column | Type | Nullability/default | Meaning |
|---|---|---|---|
| `identity` | `text` | `NOT NULL`, PK | Stable logical id |
| `version` | `text` | `NOT NULL` | Definition/API version; one compiled row per identity in v0 |
| `name` | `text` | `NOT NULL` | Display name; default `identity`; validator: 1–128 bytes, no control characters |
| `description` | `text` | `NOT NULL` | ≤500 chars, no control characters; default `name` |
| `locus` | `text` | `NOT NULL` | `in-db` or `host` |
| `invocation` | `text` | `NOT NULL` | `queue`, `session_select`, or `host_tool` |
| `required_grants` | `text[]` | `NOT NULL`, default `'{}'` | Declared grant **kinds**: `run`, `named_corpus`, `event` |
| `effect_class` | `text` | `NOT NULL` | `read_only`, `transactional`, `external` |
| `retry_class` | `text` | `NOT NULL` | `replayable`, `idempotent`, `non_retryable` |
| `reconciliation` | `text` | `NOT NULL` | `none`, `operation_key`, `manual` |
| `inject` | `jsonb` | `NOT NULL`, default `'[]'` | DSH deps, array or object |
| `provide` | `jsonb` | `NOT NULL`, default `'[]'` | DSH provide, string or array (stored as jsonb) |
| `intercept` | `jsonb` | `NOT NULL`, default `'{}'` | DSH `Dict<boolean>` |
| `capability` | `jsonb` | `NOT NULL`, default `'[]'` | Retained, not enforced |
| `session_scope` | `text` | `NOT NULL`, default `run` | Free label, not a closed enum. Validator: 1–64 bytes, no control characters. Not restricted to `current_session` |
| `config` | `jsonb` | `NOT NULL`, default `'{}'` | Declarative payload; not executed |
| `metadata` | `jsonb` | `NOT NULL` | Complete original JSON, including unknown keys |
| `source_kind` | `text` | `NOT NULL` | `comment` or `host_registration` |
| `entrypoint` | `regprocedure` | nullable | SQL signature for COMMENT rows; NULL for host |
| `refreshed_at` | `timestamptz` | `NOT NULL`, default `clock_timestamp()` | Compiled-row time |

Checks:

1. `identity` matches `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` and is ≤128 bytes. `host.worktree.apply_edits` is valid.
2. `version` is 1–64 bytes, starts alphanumeric, only `[A-Za-z0-9._+-]`, no controls.
3. `locus` ∈ (`in-db`, `host`); `invocation` ∈ (`queue`, `session_select`, `host_tool`).
4. Matrix: `in-db` + (`queue`\|`session_select`); `host` + `host_tool` only.
5. Classification:
   - `read_only` ⇒ `retry_class='replayable'` ∧ `reconciliation='none'`;
   - `transactional` ⇒ `reconciliation='none'`; retry any of the three;
   - `external` ⇒ `reconciliation ∈ ('operation_key','manual')`;
   - `external` + `operation_key` ⇒ `retry_class='idempotent'`;
   - `external` + `manual` ⇒ `retry_class='non_retryable'`.
   A tool that does both PG and external mutation is `external` in v0 (conservative D2; no `mixed` class).
6. `source_kind='comment'` ⇒ `locus='in-db'` ∧ `entrypoint IS NOT NULL`.
7. `source_kind='host_registration'` ⇒ `locus='host'` ∧ `invocation='host_tool'` ∧ `entrypoint IS NULL`.
8. `required_grants <@ ARRAY['run','named_corpus','event']::text[]`. Validator additionally rejects duplicates and any colon-suffixed D5 literal.

**Table CHECK vs validator-only.** Table CHECKs (W60) are: identity grammar+length; version grammar+length; locus/invocation enums + matrix; effect/retry/reconciliation enums + cross-field matrix; `source_kind`/`entrypoint`/`locus` consistency; `required_grants` subset. Validator-only (W61, the sole writer besides refresh which calls it): `name` 1–128 bytes no controls; `description` ≤500 chars no controls; `session_scope` 1–64 bytes no controls; duplicate grants; colon-suffixed grant literals; JSON shapes of `inject`/`provide`/`intercept`/`capability`/`config`; required JSON keys. Refresh-only: malformed `{`-prefixed JSON; legacy mutex; `prokind<>'f'`; duplicate identity; entrypoint/`session_select` jsonb return.

Indexes:

- PK on `identity`;
- btree `(locus, invocation, identity)` for P08/P09/P10;
- GIN on `required_grants` for P07.

`entrypoint` is `regprocedure` (not `regproc`) so overloads keep parameter types. OID-backed, no FK. Dropped functions leave a stale compiled row until the next **successful** refresh. P06 does not add `render_*` or a drop trigger.

#### `cordis.host_plugin_definitions`

**Kind:** host-authoring source. **Mutated by** `register_host_plugin` / `unregister_host_plugin`. **Read by** `refresh_plugins()` — never truncated by refresh.

| Column | Type | Nullability/default | Meaning |
|---|---|---|---|
| `identity` | `text` | `NOT NULL`, PK | Replacement/removal key |
| `metadata` | `jsonb` | `NOT NULL` | Full `{"cordis_plugin":{…}}` document |
| `registered_at` | `timestamptz` | `NOT NULL`, default `clock_timestamp()` | First insert |
| `updated_at` | `timestamptz` | `NOT NULL`, default `clock_timestamp()` | Last successful upsert |

Checks: `metadata` is a JSON object; `identity` uses the same grammar. Do **not** duplicate normalized columns here — JSON is the host source; `plugin_catalog` is the query surface.

#### Storage lifecycle

Successful apply of empty P00+P06: both tables exist, **zero** catalog rows (the SQL file ships no sample plugin). Failed refresh rolls back that statement / tree transaction. Successful refresh **may** drop compiled rows whose COMMENT or host source disappeared; it does not delete host source rows.

### Component 2: Unified metadata contract and validation

Envelope (both COMMENT and host):

```json
{
  "cordis_plugin": {
    "identity": "host.worktree.apply_edits",
    "version": "0.1.0",
    "name": "apply_edits",
    "description": "Apply an approved edit operation inside the bound worktree.",
    "locus": "host",
    "invocation": "host_tool",
    "required_grants": ["run"],
    "effect_class": "external",
    "retry_class": "idempotent",
    "reconciliation": "operation_key",
    "inject": ["worktree"],
    "provide": ["workspace.edit"],
    "intercept": {},
    "capability": ["worktree_write"],
    "session_scope": "run",
    "config": {}
  }
}
```

Required inside `cordis_plugin`: `identity`, `version`, `locus`, `invocation`, `effect_class`, `retry_class`, `reconciliation`.

Optional defaults: `name`→`identity`; `description`→`name`; `required_grants`→`[]`; `inject`→`[]`; `provide`→`[]`; `intercept`→`{}`; `capability`→`[]`; `session_scope`→`run`; `config`→`{}`.

Unknown keys inside `cordis_plugin` and extra root keys are preserved in `metadata` and ignored by P06 columns (T2 progressive enforcement). Core fields cannot be misspelled silently.

Internal function:

```text
cordis._validate_plugin_definition(p_definition jsonb, p_source_kind text)
RETURNS TABLE (
  identity text, version text, name text, description text,
  locus text, invocation text, required_grants text[],
  effect_class text, retry_class text, reconciliation text,
  inject jsonb, provide jsonb, intercept jsonb, capability jsonb,
  session_scope text, config jsonb, metadata jsonb
)
```

`VOLATILE`, `SECURITY INVOKER`. Invalid input → SQLSTATE `22023`. Success → exactly one normalized row.

Check order:

1. `p_source_kind` ∈ (`comment`, `host_registration`).
2. `p_definition` is a JSON object.
3. `p_definition->'cordis_plugin'` is a JSON object.
4. Required scalars exist, are strings, non-empty.
5. Identity grammar + byte limit.
6. `name` is 1–128 bytes, no control characters. `description` is 1–500 chars, no control characters. `session_scope` is 1–64 bytes, no control characters (free text, not a closed enum). Version grammar as above.
7. Locus/invocation closed set + matrix.
8. Source kind vs locus: `comment` ⇒ `in-db`; `host_registration` ⇒ `host` + `host_tool`.
9. `required_grants` is a JSON array of strings. Each element is exactly `run`, `named_corpus`, or `event`. Reject `named_corpus:<id>`, `event:<scope>`, empty strings, and unknown kinds.
10. No duplicate grants. Table CHECK: `required_grants <@ ARRAY['run','named_corpus','event']::text[]`.
11. `inject` is array (string elements) or object (values kept as JSON config).
12. `provide` is a string or an array of strings.
13. `intercept` is an object of booleans.
14. `capability` is any non-null JSON; default `[]` when omitted.
15. `config` is a JSON object; stored, never executed.
16. Effect/retry/reconciliation closed values + cross-field rules.
17. `metadata` is the original `p_definition`.

The validator must not inspect `cordis.jobs`, `agent_steps`, or any P01/P02 object.

#### Function-entrypoint extra checks (refresh only)

Scan **all** `cordis` `pg_proc` rows (do not `WHERE prokind='f'`). P01/P02 functions live in `cordis` today and have **no** `{`-prefixed COMMENT, so a fresh apply-time refresh inserts **zero** catalog rows. COMMENT-sourced extra checks are **candidate-level errors** (SQLSTATE `22023`), not silent filters:

- namespace is `cordis`;
- if the comment contains `cordis_plugin` and `prokind <> 'f'` → error (a `PROCEDURE` must not vanish);
- compiled `entrypoint` is `p.oid::regprocedure`.

`invocation='session_select'` additionally requires return type `jsonb` (future SELECT path). Do **not** enforce parameter names, a `jobs` argument, or handler naming in P06.

`invocation='queue'` must **not** require `cordis.jobs` (P01 is parallel).

Host definitions: no entrypoint; compile with `entrypoint IS NULL`.

### Component 3: Atomic unified refresh

```text
cordis.refresh_plugins() RETURNS integer
```

`VOLATILE`, `SECURITY INVOKER`. Return value = inserted compiled row count.

Before scanning:

```text
pg_advisory_xact_lock(hashtext('pg_cordis.plugin_refresh'))
```

Distinct from `hashtext('pg_cordis.apply')`. Database-local, **no timeout** (P00 critique §4.5). A crashed session releases it when its transaction ends.

#### COMMENT scan

```text
pg_proc JOIN pg_namespace WHERE nspname = 'cordis'
obj_description(p.oid, 'pg_proc')
```

- NULL / non-`{` (after trim) → ignore.
- Trimmed text starting with `{` is a JSON candidate. **Malformed JSON is an error** with SQLSTATE `22023` (do not copy `refresh_handlers`' post-TRUNCATE cast failure). Fail-closed: one `{`-prefixed illegal comment on **any** `cordis` function fails every refresh, including `register_host_plugin` and tree apply. No skip/force hatch; recovery is fix or drop that COMMENT. After P06 lands, prose COMMENTs on `cordis` functions must not start with `{`.
- Valid JSON without `cordis_plugin` → ignore **unless** it violates legacy mutex.
- Valid JSON with `cordis_plugin` → `_validate_plugin_definition(..., 'comment')`.
- `cordis_plugin` plus `job_handler` or `workbench_plugin` → error.
- Both legacy keys even without `cordis_plugin` → error (two invocation interpretations of one object).
- P06 does **not** compile `job_handler` / `workbench_plugin` by themselves.

Deterministic order: `p.oid`, then `pg_get_function_identity_arguments(p.oid)`.

#### Host-source scan

`cordis.host_plugin_definitions` ordered by `identity` ASC. For each row: source PK must equal identity inside `metadata`; validate as `host_registration`; `source_kind='host_registration'`; `entrypoint=NULL`.

Duplicate identity (host vs COMMENT, or two overloads) is an error. P06 does not pick last-wins.

#### Validate-before-rebuild

1. Empty candidate list + seen-identity set.
2. Scan/validate all COMMENT candidates.
3. Scan/validate all host candidates.
4. Reject already-seen identity.
5. After **every** candidate passes: `DELETE FROM cordis.plugin_catalog;` then bulk insert with one shared `refreshed_at`; return the inserted count.

Do **not** delete compiled rows before validation completes. A post-delete insert/CHECK failure aborts the function statement and rolls back the delete+inserts, preserving the previously committed catalog (MVCC-visible to concurrent REPEATABLE READ readers). Do not `DELETE`/`TRUNCATE` `host_plugin_definitions`. Do not `TRUNCATE plugin_catalog`.

Every candidate-level refresh failure (`malformed JSON`, mutex, duplicate identity, `prokind`, validator `22023`) uses `RAISE ... USING ERRCODE = '22023'` with the function signature or `identity` in the message. Tests match those fragments, not raw `::jsonb` cast text.

Complexity O(F+H+R) with small catalogs; no incremental refresh, no dependency ordering (T2 progressive).

#### Source vs compiled

- Dropping a function does not immediately delete the compiled row; next successful refresh does.
- Failed refresh leaves prior compiled rows and `refreshed_at`.
- Successful host register updates source + compiled together; failure leaves both previous states.
- Successful refresh with zero candidates leaves `plugin_catalog` empty.

### Component 4: Host-tool registration

Why not a stub function: P09 could treat a function-backed row as in-db-executable. Why not INSERT into `plugin_catalog`: the next refresh would wipe it and the compiled table would become a second source of truth.

```text
cordis.register_host_plugin(p_definition jsonb) RETURNS text
```

1. Validate as `host_registration` **before** mutating source.
2. Upsert `host_plugin_definitions` by `identity` (`INSERT ... ON CONFLICT (identity) DO UPDATE`); replace `metadata` only (not side-by-side versions).
3. `updated_at = clock_timestamp()`. **Do not overwrite `registered_at` on UPDATE** (`registered_at` stays the first-insert time).
4. `refresh_plugins()`.
5. Return `identity`. Any refresh failure rolls back the upsert.

```text
cordis.unregister_host_plugin(p_identity text) RETURNS boolean
```

1. Validate identity grammar.
2. Delete matching host source row only.
3. If a row was deleted, `refresh_plugins()`.
4. Return `true` iff a source row was deleted.

If a COMMENT-sourced row shares that identity, unregistering the host source leaves the COMMENT row after refresh — duplicate identity is only rejected while **both sources coexist**.

Both functions: `VOLATILE`, `SECURITY INVOKER`, schema-qualified. No grants, no host code, no claim, no log, no dispatch.

#### v0 proof definition (tests; metadata only)

Use the JSON envelope in Component 2. Expected compiled row:

- `identity = 'host.worktree.apply_edits'`
- `version = '0.1.0'`
- `locus = 'host'`
- `invocation = 'host_tool'`
- `required_grants = ARRAY['run']`
- `effect_class = 'external'`
- `retry_class = 'idempotent'`
- `reconciliation = 'operation_key'`
- `source_kind = 'host_registration'`
- `entrypoint IS NULL`
- `metadata` equals the submitted document
- `inject` / `provide` / `capability` / `session_scope` / `config` preserved

### Component 5: Version marker and apply integration

Near the end of `sql/0006_p06_plugin_catalog.sql`, **before** the final refresh:

```text
CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p06'::text;
$$;
```

Signature must stay `() → text` so `verify_bootstrap` (`:211-242`) still passes.

**Last statement in the file:**

```text
SELECT cordis.refresh_plugins();
```

This compiles host rows already present on replay, compiles COMMENT definitions from **earlier-numbered** files in the same tree transaction, and rolls back P06 DDL+version replacement if refresh fails during apply.

Later Px files that add COMMENT-sourced functions must call `cordis.refresh_plugins()` after those definitions if they need the rows in the same apply.

Loader discovery/manifest/`verify_bootstrap` stay as-is (**no** P06 dollar-quote patch). Apply lock literal remains `hashtext('pg_cordis.apply')` (`apply_pg_cordis.py:320`). Refresh lock is `hashtext('pg_cordis.plugin_refresh')`.

**Lock order:** apply path always takes `pg_cordis.apply` first, then `pg_cordis.plugin_refresh` inside the final `SELECT refresh_plugins()`. `register_host_plugin` / `unregister_host_plugin` take only the refresh lock. Never acquire refresh then apply. A long apply therefore blocks all host registrations until it commits or rolls back (no lock timeout; cancellable via client cancel / `statement_timeout`).

### Component 6: Tests and current-tree assertions

#### P00 retarget

Rename `test_fresh_apply_lists_current_tree_and_p02` → `test_fresh_apply_lists_current_tree_and_p06`:

- expected file list `0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,0006_p06_plugin_catalog.sql`;
- `get_schema_version() = 'p06'`;
- `cordis.jobs` and `cordis.agent_steps` still present; `run_waits`/`run_events` still absent;
- `to_regclass('cordis.plugin_catalog')` and `host_plugin_definitions` exist;
- extend `KERNEL_FUNCTIONS` (`tests/test_p00_sql_source.py:23-37`) with `cordis._validate_plugin_definition`, `cordis.refresh_plugins`, `cordis.register_host_plugin`, `cordis.unregister_host_plugin`; keep the exact `ORDER BY 1` equality;
- no `public.jobs` / `public.agent_steps` / `workbench_tools` / `pg_cordis` extension;
- keep “no non-system user tables in `public`”.

Product-tree version pins `'p02'`→`'p06'`:

- `tests/test_p00_sql_source.py` composition (`:484`);
- `tests/test_p01_claim.py:130`, `:495`;
- `tests/test_p02_agent_steps.py` `_ensure_full` / `P02_DB` (`:337`).

Keep `'p02'` on P02-only temp trees (`test_p02_fresh_apply_catalog_and_version`, `_apply_p02_only`).

#### Dynamic prefixes

Already implemented as `next_sql_prefix` in `tests/conftest.py:60-66`. Probe/invalid-tree/rollback tests must keep using it (next prefix after `0006` will be `0007`). Do not hard-code `0001` or `0006`.

#### Forbidden-token test

Keep `tests/test_p00_sql_source.py:379-394` as-is: `sanitize_sql_for_preflight` + `FORBIDDEN_STMTS` + later `CREATE TABLE` must be `cordis.*`. `0006` must pass this scan. Do not weaken the GRANT ban.

#### Shared helpers

Import `run_apply`, `psql`, `next_sql_prefix`, `SQL`, `APPLY` from `tests.conftest`. CLI is `[sys.executable, str(APPLY), ...]`. Do not copy helpers into `test_p06_plugin_catalog.py`.

### Work items

#### W60 — Catalog and source-table DDL

- **Goal:** Persistent compiled + host-source tables, checks, indexes.
- **Done when:** Both tables install after P00, replay without duplicate-object errors, exact columns/CHECKs/indexes, no `public` objects.
- **Key files:** `sql/0006_p06_plugin_catalog.sql`
- **Dependencies:** P00. Must install on the current `0000+0001+0002` tree without altering `jobs` / `agent_steps`.
- **Size:** Medium

#### W61 — Metadata validator

- **Goal:** Shared internal validator and v0 JSON vocabulary.
- **Done when:** `_validate_plugin_definition` returns one normalized row for the host proof definition and a valid in-db COMMENT definition; rejects bad root shape, identities, locus/invocation pairs, grant strings, duplicate grants, JSON shapes, effect/retry inconsistencies.
- **Key files:** `sql/0006_p06_plugin_catalog.sql`
- **Dependencies:** W60
- **Size:** Medium

#### W62 — Unified atomic refresh

- **Goal:** Compile COMMENT + host-source into one catalog.
- **Done when:** scans only `cordis` `pg_proc` + host table; `{`-prefixed malformed JSON and `prokind<>'f'` with `cordis_plugin` error with SQLSTATE `22023`; mutex; duplicate identity errors; validate-then-`DELETE`+insert; failed refresh leaves old rows.
- **Key files:** `sql/0006_p06_plugin_catalog.sql`
- **Dependencies:** W60–W61
- **Size:** Large

#### W63 — Host registration API

- **Goal:** Non-stub host-tool source path (D8).
- **Done when:** register upserts + refresh in one transaction; `ON CONFLICT` updates `metadata`/`updated_at` only and preserves `registered_at`; unregister deletes source + refresh; failed register (including blocked by an unrelated bad COMMENT) leaves both tables unchanged.
- **Key files:** `sql/0006_p06_plugin_catalog.sql`
- **Dependencies:** W61–W62
- **Size:** Medium

#### W64 — Version and apply-time refresh

- **Goal:** P06 marker and compiler on apply/replay.
- **Done when:** file replaces version body with `'p06'`, ends with `SELECT cordis.refresh_plugins();`, succeeds on `--reset` and in-place replay.
- **Key files:** `sql/0006_p06_plugin_catalog.sql`
- **Dependencies:** W62–W63
- **Size:** Small

W60–W64 land as **one** complete `0006` file; a partial file cannot satisfy apply-time refresh.

#### W65 — Retarget current-tree tests

- **Goal:** P00/P01/P02 product-tree tests survive catalog tables and `'p06'`.
- **Done when:**
  - `tools/apply_pg_cordis.py` is **unchanged**.
  - `0006` function bodies use outer `$$`, no nested dollar tags, no adjacent `$$`; GRANT/END words only inside dollar-quotes or SQL comments so existing W09 strip keeps working.
  - `test_fresh_apply_lists_current_tree_and_p06` lists `0000,0001,0002,0006`, version `'p06'`, `jobs`+`agent_steps`+both catalog tables, exact `KERNEL_FUNCTIONS` including the four P06 names.
  - Product-tree `'p02'` pins in P00 composition, P01, and P02 `_ensure_full` become `'p06'`.
  - P02-only temp trees still expect `'p02'`.
- **Key files:** `tests/test_p00_sql_source.py`, `tests/test_p01_claim.py`, `tests/test_p02_agent_steps.py`, `sql/README.md`
- **Dependencies:** W60–W64
- **Size:** Medium

#### W66 — P06 catalog tests

- **Goal:** Host registration, COMMENT compile, replay, mutex, malformed JSON, row preservation.
- **Done when:** `tests/test_p06_plugin_catalog.py` contains the named tests in Verification and all pass via `uv run pytest`; no test imports `tools/`.
- **Key files:** `tests/test_p06_plugin_catalog.py`
- **Dependencies:** W60–W65
- **Size:** Medium

### File-by-file impact

| File | Change | Why | Ordering |
|---|---|---|---|
| `sql/0006_p06_plugin_catalog.sql` | Add both tables, indexes, `_validate_plugin_definition`, `refresh_plugins`, `register_host_plugin`, `unregister_host_plugin`, replace `get_schema_version()` with `'p06'`, end with `SELECT cordis.refresh_plugins()` | Entire P06 surface | After `0000`/`0001`/`0002` (gap `0003–0005` unused) |
| `sql/0000_kernel.sql` / `0001_p01_claim.sql` / `0002_p02_log.sql` | **No change** | Append-only | Byte-for-byte unchanged |
| `sql/README.md` | Document `0006`, tables, JSON envelope, enums, host registration, kinds-only grants, current-tree marker `p06`, writing rules (GRANT/END words inside `$$`; `cordis` function COMMENTs must not start with `{`) | Source contract without a loader manifest | Land with the SQL file |
| `tools/apply_pg_cordis.py` | **No change** | W09 already strips dollar-quotes | Verify `0006` passes current preflight |
| `tests/test_p00_sql_source.py` | Rename fresh-apply test; file list + `'p06'` + extend `KERNEL_FUNCTIONS`; composition `'p06'` | Current tree is `0000+0001+0002` | |
| `tests/test_p01_claim.py` | Product-tree version `'p02'`→`'p06'` (`:130`, `:495`) | `_ensure_p01` applies the full product tree | |
| `tests/test_p02_agent_steps.py` | `_ensure_full` version `'p02'`→`'p06'`; keep `'p02'` on `_apply_p02_only` | Distinguishes product tree vs 0000+0002 fixture | |
| `tests/conftest.py` | **No change** unless a new helper is strictly shared | Already the helper owner | |
| `tests/test_p06_plugin_catalog.py` | New | Behavioral coverage | Import helpers from `tests.conftest` |
| `pyproject.toml` / `uv.lock` | No change | `[dependency-groups] dev = ["pytest"]`, `package = false` already | Do not add a plugin runtime |
| `pg-agent/v2/*` | No change | Separate testbed DB | Composition only |
| `scratch/yield_walkthrough/*` | No change | Proof-only, not ABI | No dependency |

### Risks and migration

- **New persistent state:** `host_plugin_definitions` (source) and `plugin_catalog` (derived). Current P02 databases have neither; `IF NOT EXISTS` + empty refresh creates them beside `jobs` and `agent_steps`. Replaying an **older** source tree is not a downgrade (tables and `'p06'` remain). Use `--reset` on a disposable DB to test older trees.
- **One row per identity:** a new `version` replaces. Side-by-side versions need a later numbered design, not an in-place PK change.
- **Stale compiled rows** until refresh. No trigger, no background job. Apply refreshes; later plugin files must refresh after their COMMENTs.
- **Duplicates / bad JSON / mutex / bad grants fail closed** — no last-wins. One `{`-prefixed illegal COMMENT on any `cordis` function fails **every** later `refresh_plugins()`, `register_host_plugin`, and tree apply until that COMMENT is fixed or dropped. There is no skip/force hatch.
- **Security:** declarations only. No GRANT statements, no RLS, no host permissions. `SECURITY INVOKER`.
- **Locks:** apply lock serializes tree apply; refresh lock serializes standalone refresh; neither times out. Order is always apply then refresh. A long apply blocks host registration for the duration of the tree transaction.
- **`--reset`** remains destructive and not concurrency-safe (P00).
- No threads, workers, dynamic code, or resource handles.

### Implementation order

1. Write complete `sql/0006_p06_plugin_catalog.sql` (DDL → validator → refresh → register/unregister → version `'p06'` → `SELECT refresh_plugins();`). Do not merge a partial file. Do not edit `0000`/`0001`/`0002` or `apply_pg_cordis.py`.
2. Update `sql/README.md` current-tree marker (`p02` → `p06` once `0006` is in the tree).
3. Retarget P00/P01/P02 **product-tree** tests (`KERNEL_FUNCTIONS`, file list, `'p06'`). Leave P02-only fixtures at `'p02'`.
4. Add `tests/test_p06_plugin_catalog.py` using `tests.conftest` helpers.
5. `uv run pytest tests/test_p06_plugin_catalog.py tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py -q` then full suite.
6. pg-agent composition on shared PGDATA, separate DBs.
7. Do not start P07 until compiled row shape and host-registration SELECT are stable; P07 reads `required_grants`, it does not invent a second declaration vocabulary.

---

## Verification

All commands from the `zcordis-pgembed` repo. Disposable DBs; tests own cleanup where they create them. pytest via `[dependency-groups] dev`. CLI via `sys.executable` + `tools/apply_pg_cordis.py` subprocess — never `import tools`.

### 1. Fresh P06 apply — `test_fresh_apply_lists_current_tree_and_p06`

```bash
export CORDIS_ROOT=/path/to/zcordis-pgembed
cd "$CORDIS_ROOT"

uv run python tools/apply_pg_cordis.py \
  --pgdata "$CORDIS_ROOT/.pgdata" \
  --database cordis_p06_verify \
  --reset
```

Expected: exit `0`; `mode=reset`; `bootstrap verification ok`; `files=0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,0006_p06_plugin_catalog.sql`.

Then:

```sql
SELECT cordis.get_schema_version();                 -- p06
SELECT to_regclass('cordis.plugin_catalog');        -- cordis.plugin_catalog
SELECT to_regclass('cordis.host_plugin_definitions');
```

Drive the SQL through the existing `psql` helper / bundled `POSTGRES_BIN_PATH` (same pattern as P00 tests), not `PostgresServer.psql()` without a database argument.

### 2. Register and query one host-tool — `test_register_host_plugin_and_select`

Call `cordis.register_host_plugin` with the proof JSON. SELECT:

```text
host.worktree.apply_edits|0.1.0|host|host_tool|{run}|external|idempotent|operation_key|host_registration|t
```

(`entrypoint IS NULL` → `t`). Also assert `inject`, `provide`, `capability`, `session_scope`, `config`, and `metadata` equal the submitted document. Assert `cordis.refresh_plugins()` returns `1` when called on a catalog that contains only this host row (or assert `register_host_plugin` left exactly one compiled row and a subsequent `SELECT cordis.refresh_plugins()` returns `1`). The SQL file itself does not assert the refresh count; W66 is the count-gate.

```bash
uv run pytest tests/test_p06_plugin_catalog.py -q -k register_host_plugin_and_select
```

### 3. COMMENT-sourced in-db — `test_comment_refresh_compiles_cordis_function`

Temp tree: copy `sql/`, add next unused prefix that:

1. creates a normal `cordis` function;
2. `COMMENT ON FUNCTION` with valid `cordis_plugin`, `locus='in-db'`, `invocation` `queue` **or** `session_select`;
3. `SELECT cordis.refresh_plugins();`.

`session_select` ⇒ `RETURNS jsonb`. `queue` ⇒ do **not** reference `cordis.jobs`.

Expected: compiled row `source_kind='comment'`, `entrypoint IS NOT NULL`, `entrypoint::text` has the full signature, DSH fields + `metadata` queryable, no `public` object. After the extra function is compiled, `SELECT cordis.refresh_plugins()` returns the compiled row count (host proof row if still present plus the new COMMENT row).

```bash
uv run pytest tests/test_p06_plugin_catalog.py -q -k comment_refresh
```

### 4. In-place replay after host registration — `test_in_place_replay_keeps_host_plugin`

Register the proof row, then apply **without** `--reset`.

Expected: exit `0`; `mode=in-place`; `bootstrap verification ok`; version still `p06`; host source row remains; compiled host row present after apply-time refresh; no duplicate-identity error; unrelated `public` sentinel (P00 pattern) survives.

```bash
uv run pytest tests/test_p06_plugin_catalog.py -q -k replay
```

### 5. Mutex COMMENT preserves previous catalog — `test_refresh_rejects_mutex_comment_and_preserves_previous_rows`

1. Clean P06 DB; register `host.worktree.apply_edits`.
2. Copy product `sql/` to a temp dir; add a higher-numbered file that creates `cordis.p06_bad_mutex()`, COMMENT containing `cordis_plugin` **plus** both `job_handler` and `workbench_plugin`, then `SELECT cordis.refresh_plugins();`.
3. Apply that tree **without** `--reset` onto the populated DB (`--sql-root`).

Expected: CLI exit **`1`** (SQL failure, not preflight `2`); refresh error SQLSTATE `22023` (mutex fragment in the message); original host compiled row unchanged (same normalized values); invalid identity absent from `plugin_catalog`; temp function rolled back with the tree transaction.

```bash
uv run pytest tests/test_p06_plugin_catalog.py -q -k mutex
```

### 6. Malformed COMMENT preserves previous catalog — `test_refresh_rejects_malformed_comment_and_preserves_previous_rows`

Same setup; COMMENT trimmed text starts with `{` but is invalid JSON (unterminated object).

Expected: exit `1`; refresh error SQLSTATE `22023` with a JSON-parse fragment (not a raw `::jsonb` cast-only message, not silent skip); prior host row still present with the **same** `refreshed_at`; no partial rebuild.

```bash
uv run pytest tests/test_p06_plugin_catalog.py -q -k malformed
```

### 7. Invalid host registration does not mutate source — `test_invalid_host_registration_preserves_previous_definition`

After a valid register, `register_host_plugin` with each of:

- illegal `locus`/`invocation` pair (e.g. `host` + `queue`);
- a colon-suffixed D5 literal such as `named_corpus:some-id` (kinds only; P07 owns IDs);
- `effect_class='external'`, `retry_class='replayable'`, `reconciliation='none'`.

Each call fails. Source JSON and compiled row remain the original valid definition.

```bash
uv run pytest tests/test_p06_plugin_catalog.py -q -k invalid_host_registration
```

### 8. Unrelated bad COMMENT blocks register — `test_unrelated_bad_comment_blocks_register_and_preserves_rows`

After a valid host register, `CREATE FUNCTION cordis.p06_unrelated()` with a `{`-prefixed malformed COMMENT (or `cordis_plugin` on a `PROCEDURE`). Then `register_host_plugin` of a second valid identity fails with SQLSTATE `22023`. Host source and compiled rows for `host.worktree.apply_edits` are unchanged. Demonstrates fail-closed pollution radius (no skip hatch).

Also `test_refresh_rejects_non_function_cordis_plugin`: a `CREATE PROCEDURE` in `cordis` whose COMMENT contains `cordis_plugin` makes refresh raise `22023`; it is not silently omitted.

### 9. Unregister and duplicate identity — `test_unregister_host_plugin` / `test_duplicate_identity_comment_vs_host`

- Unregister proof identity → compiled row gone, function returns `true`; second unregister returns `false` and does not error.
- Register host identity `p06.dup`, then add a COMMENT function with the same identity → refresh/apply fails; host source row remains.

### 10. P00 forbidden statements still exit 2 — existing `test_p00` invalid-tree + retargeted `forbidden_tokens`

```bash
uv run pytest tests/test_p00_sql_source.py -q -k invalid_tree
uv run pytest tests/test_p00_sql_source.py -q -k forbidden_tokens
```

Expected: GRANT, CREATE EXTENSION, psql meta-command, database DDL, invalid filename, duplicate prefix, nested `.sql`, missing `0000`, empty tree → exit **2** and target DB **absent** from `pg_database`. `CREATE TABLE cordis.*` in `0006` allowed; table DDL in `0000` forbidden; `CREATE TABLE public.*` / unqualified `CREATE TABLE` forbidden.

Existing `test_plpgsql_end_inside_dollar_quotes_applies` (`tests/test_p00_sql_source.py:196`) must still pass; top-level `END;` still exit 2. Do not add a second preflight implementation.

### 11. SQL tree rollback — `test_sql_failure_rolls_back_tree`

Dynamic unused prefix (not `0001`). Exit `1`; target DB may exist; objects from the failing tree (including catalog if this was a `--reset` of that DB) are absent because the tree transaction rolled back.

### 12. pg-agent composition — `test_pg_agent_separate_database_composition`

Same PGDATA, different DBs (`da_agent` vs `cordis_p06_comp` or current test name). Retarget version pin `'p02'` → `'p06'`.

```bash
PG_AGENT_ROOT=/path/to/pg-agent \
  uv run pytest tests/test_p00_sql_source.py -q -k pg_agent_separate_database_composition
```

Expected: `da_agent` still has `public.jobs` / handlers / workbench; cordis DB has schema `cordis`, version `p06`, `cordis.jobs` + `cordis.agent_steps` + catalog tables in `cordis` not `public`, no `public.jobs`; no pg-agent SQL under this repo’s `sql/`.

### 13. Full suite

```bash
PGCORDIS_PGDATA="$CORDIS_ROOT/.pgdata" uv run pytest -q
```

P00 + P01 + P02 + P06 all pass; no test imports `tools/` as a package; CLI via `sys.executable`. No test relies on a permanently running postmaster between sequential CLI subprocesses (each `run_apply` may start/stop the server).

Named P06 test functions (complete list for W66):

- `test_register_host_plugin_and_select`
- `test_comment_refresh_compiles_cordis_function`
- `test_in_place_replay_keeps_host_plugin`
- `test_refresh_rejects_mutex_comment_and_preserves_previous_rows`
- `test_refresh_rejects_malformed_comment_and_preserves_previous_rows`
- `test_invalid_host_registration_preserves_previous_definition`
- `test_unrelated_bad_comment_blocks_register_and_preserves_rows`
- `test_refresh_rejects_non_function_cordis_plugin`
- `test_unregister_host_plugin`
- `test_duplicate_identity_comment_vs_host`

---

## Open questions

Material P06 design is decided above. These remain **deferred**, not P06 work:

- side-by-side version rows / negotiation;
- live grant issuance, slice binding, corpus freeze (P07);
- four-seam enforcement (P08);
- claim / handler dispatch (P01/P09);
- host SDK language and verbs (P10);
- CodeAct/RLM policy registration (P19);
- wait/sleep (P03/P04);
- dependency ordering / reactive activation;
- config-schema execution;
- `node:vm` / dynamic in-DB code;
- `CREATE EXTENSION` / pgembed bundle.

Mid-flow answers are folded into Resolved questions. No remaining P06 design questions.

## References

- `docs/plans/2026-08-23-pg-cordis-development.md:166-174` — P06 skeleton and downstream consumers
- `docs/plans/P00-sql-source-2026-08-23.md` — numbered-file / apply contract; deferred catalog
- `docs/plans/P01-jobs-claim-2026-08-23.md` — `0001` prefix; W09 dollar-quote preflight; W13 conftest; version convention; test retarget
- `docs/decisions/2026-08-23-pending.md:264+` — D5; `:364+` D7; `:412-415` D8
- `docs/analysis/2026-08-23-i-architecture-snapshot.md:97-117` — §4/§5; `:234` field names open
- `docs/analysis/2026-08-23-a-dsh-plugin-migration-to-pg-cordis.md:63-75`, `:124-149` — mapping, T1/T2/T7, host-side citizens
- `docs/analysis/2026-08-23-h-vision-d1-d9-oracle-verdicts.md:32,49` — host locus now
- `docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md:77,87` — isolation «locus» ≠ plugin locus
- `docs/analysis/2026-08-23-e-absurd-durable-execution.md:74-79` — morphology only; no `absurd` schema
- `docs/reviews/2026-08-23-p00-plan-critique.md` — GRANT ban, subprocess tests, lock literal, absence assertions
- `docs/reviews/2026-08-23-p06-plan-critique.md` — DELETE vs TRUNCATE, loader GRANT words, fail-closed radius, SQLSTATE
- `sql/0000_kernel.sql`, `sql/README.md:3-35`
- `tools/apply_pg_cordis.py:17-35` discovery + forbidden; `:93-106` preflight; `:202-242` lock/apply/verify
- `tests/test_p00_sql_source.py:57-111`, `:143-184`, `:291-301`, `:311-333`
- `pg-agent/v2/pg_agent_functional.sql:303-327`
- `pg-agent/v2/pg_agent_workbench_core.sql:9-16,22-28,103-128,204-209`
- `deepseek-harness/vendor/cordis/src/registry.ts:100-111`
- Baseline export: `prompt-exports/oracle-plan-2026-08-23-174556-p06-plugin-catalog-d-42f5.md`
