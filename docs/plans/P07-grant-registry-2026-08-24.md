# P07 — Grant registry (C + model-only request + slice binding)

Date: 2026-08-24  
Status: **ready to implement**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P07  
Depends on: P06, implemented (`sql/0006_p06_plugin_catalog.sql`)  
Parallel with: P03 (in tree), P04, P05, P19  
Contract: D5 — `run` / `named_corpus:<id>` / `event:<scope>`; slice-bound; model only requests; user or trusted host issues  
Primary deliverable: `sql/0007_p07_grant_registry.sql`  
Critique: `docs/reviews/2026-08-24-p07-plan-critique.md`  
Oracle export (round 1): `prompt-exports/oracle-review-2026-08-24-214119-untitled-chat-8ac134-2c49.md`  
Oracle export (round 3, passed): `prompt-exports/oracle-review-2026-08-24-220147-untitled-chat-8ac134-87ec.md`

**Landing state:** product tree is `0000` + `0001` + `0002` + `0003` + `0006`; marker `'p06'`. P07 appends `0007` and replaces the version body with `'p07'`. Combined-tree pins that currently say `'p06'` become `'p07'`. Truncated trees stay as they are (`0000+0002` → `'p02'`; `0000`–`0003` → `'p03'`).

---

## Goal

Add the kernel grant registry: named corpus roots, per-run slices, request vs issue verbs, and a live-grant query that is **per slice**.

P07 creates:

- `cordis.named_corpora` — registered corpus **roots** (no version subset, no file list);
- `cordis.slices` — named workspace slices inside a run;
- `cordis.grants` — current-state one row per `(slice_id, kind, target)`, status `pending | issued | denied | revoked`;
- SQL verbs so `request_grant` never writes `issued`, and issue/approve/deny/revoke/`create_slice`/`register_named_corpus` reject an asserted `issuer_kind='model'` (provenance label, not authentication);
- `cordis.slice_live_grants` / `cordis.slice_has_grant` as the only retrieval-oriented read API (no run-union helper);
- schema marker `cordis.get_schema_version() → 'p07'`.

**v0 proof:** issue two `named_corpus` grants onto two slices of one run; each slice’s live set contains only its own corpus; a model `request_grant` for the other corpus remains `pending` and does not appear in `slice_live_grants`.

P07 does **not** implement four-seam enforcement (P08), RLS/roles, plugin dispatch, wait/emit authorization, selection (P13), spawn inheritance (P17), corpus content snapshots, or structured descriptor A.

---

## 中文摘要

P07 在 `sql/` 增加 `0007_p07_grant_registry.sql`：三张核表 `named_corpora` / `slices` / `grants`。Grant 是 **当前 workspace 态**（每 slice+kind+target 一行），不写 `agent_steps`，不改 P02 kind 词表，denied/revoked 不是第二套历史。D5 枚举按 **slice** 绑定；`run` 目标为空串；`named_corpus` 是 live root 身份（不冻结文件内容）；`event` 的 target 与 P03 `event_scope_id` 同契约（非空、原样存）。`request_grant` 从不写 issued。issue 族拒绝 **声称** `issuer_kind='model'`，这是来源标签不是认证；P07 不是模型可调的产品面。活查询只有 slice API。不静默扩权 = grant **集合**不自动变大。写路径锁 slice `FOR UPDATE`。不改 loader / `0000`–`0006`。plpgsql 用 `$p07$`。 

---

## Execution index

P06 used `W60`–`W66`; P03 used `W27`–`W33`. P07 uses `W70`–`W77`.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W70 | Grant-registry DDL | Fresh apply of the product tree plus `0007` creates `named_corpora`, `slices`, `grants` with the columns, CHECKs, FKs, and indexes below; prior tables remain; no `public` tables | `sql/0007_p07_grant_registry.sql` | P06 | Medium |
| W71 | Corpus root + slice verbs | `register_named_corpus` same-id/same-label is idempotent; same-id/different-label raises `22023`; `create_slice` duplicate `(run_id, name)` raises `22023`; asserted `issuer_kind='model'` raises `42501` | same | W70 | Small |
| W72 | Model request | `request_grant` never writes `issued`; a fresh request is `pending` and absent from `slice_live_grants`; reuse the same `grant_id` if the tuple already exists | same | W70–W71 | Medium |
| W73 | Host/user issue + approve/deny | issue family rejects asserted `issuer_kind='model'`; two corpora on two slices stay distinct live sets; denied/revoked reuse the same row | same | W72 | Medium |
| W74 | Revoke + per-slice live query + linearization | `revoke_grant` takes the row out of the live set; query APIs see only `issued`; slice `FOR UPDATE` serializes writers; no run-union retrieval function | same | W73 | Medium |
| W75 | Version marker + README | `get_schema_version() → 'p07'`; README documents the three tables and D5 literals | `sql/0007_p07_grant_registry.sql`, `sql/README.md` | W70–W74 | Small |
| W76 | Retarget current-tree tests | Product-tree file list includes `0007`; `KERNEL_FUNCTIONS` gains the nine P07 names (exact `ORDER BY 1` list); combined-tree `'p06'` → `'p07'`; truncated trees unchanged | `tests/test_p00_sql_source.py`, `tests/test_p01_claim.py`, `tests/test_p02_agent_steps.py`, `tests/test_p06_plugin_catalog.py` | W75 | Medium |
| W77 | P07 registry tests | Named tests in `tests/test_p07_grant_registry.py` all pass via `uv run pytest`; no `import` of `tools/` | `tests/test_p07_grant_registry.py` | W70–W76 | Medium |

---

## Background

Curated from the skeleton, D5, snapshot, P06 hand-off, and P03 event opacity. Spot-checked against current code.

### Parent skeleton

`docs/plans/2026-08-23-pg-cordis-development.md:178-186`:

- **Depends on P06. Parallel with P03, P04, P05, P19.**
- **Contract:** D5 C + model-only request; slice-bound; user or trusted host issues.
- **Decide here:** table shape; request vs issue API; whether a corpus is frozen during a run (偏安: whole root, no silent expansion).
- **Do:** only user/trusted host writes live grants; model requests are not auto-approved; bind to slice, not the run union.
- **Do not:** SQL-predicate grants; `run_id` as the isolation range; structured descriptor A.
- **Done when:** two `named_corpus` grants on two slices; a model request stays pending.

Do not reopen D1–D9 or snapshot §4 (`development.md:18`). No `CREATE EXTENSION` in P00–P19. SQL namespace is schema `cordis`.

Downstream (consume this registry; do not implement here):

| Later item | What it reads |
|---|---|
| P08 | live grants **of the calling slice** at recall, fold, env read, and tool dispatch |
| P10 | host SDK may call issue/revoke; must not expose issue as a model tool |
| P13 | attaches StoredSelection to the same `slice_id`; slice already carries grants |
| P15 | D5 worked example: project 1 / project 2 on different slices |
| P17 | copies/issues named grants onto a child run via `issue_grant`; no inherit verb here |

### Signed contracts

- D5 (`docs/decisions/2026-08-23-pending.md:264-267`): **C** + 签发政策. Enum `run` / `named_corpus:<id>` / `event:<scope>`. Slice-bound, not the run union. Model only requests. User or trusted host/orchestrator writes the live row. Ban **B** (SQL predicate) and **D** (`run_id` as range). Upgrade path remains A; this round does not implement A.
- D5 still-open (同文 `:303`): `named_corpus` whole root vs version subset; corpus freeze; revoke vs in-flight prompt / child run. Skeleton 偏安 for this plan: **whole root, no silent expansion**.
- Snapshot §4 D5 (`docs/analysis/2026-08-23-i-architecture-snapshot.md:97`).
- Snapshot §5 isolation (`:138`): grant registry is **kernel**, same class as `emit_step` write monopoly. Four-seam enforcement is P08. Half-enforcement must not ship to users — P07 is the registry only, so it must not claim recall/fold are filtered.
- Snapshot §9 (`:222`): ban model-written grants, SQL-predicate grants, run-union retrieval.
- Snapshot §10.5 (`:236`): corpus versioning and revoke-vs-in-flight prompt are implementation details, not architecture forks. This plan closes them for v0 as below.
- Q3 / F (`docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:14`, `:186`): emit/await are grant **capabilities** on `(event_scope_id, event_name)`. D5 C is coarser: holding `event:<scope>` authorizes every name under that scope, both emit and await. Per-name / emit-vs-await split is A, not P07.
- P03 (`docs/plans/P03-wait-event-2026-08-24.md` decision 9 / Goal): event scope is opaque; P03 does **not** check grants. P07 records authorization. P08 will gate the verbs. P07 must not wrap `await_event` / `emit_event` and must not FK `grants` to `run_events`.
- P06 (`docs/plans/P06-plugin-catalog-2026-08-23.md` decision 5; `sql/0006_p06_plugin_catalog.sql` constraint `plugin_catalog_required_grants_check`): catalog `required_grants` are **kinds only** (`run` / `named_corpus` / `event`). P07 issues the colon-suffixed D5 literals and binds slices. Do not edit `0006` or bake a corpus UUID into a plugin row.

### P00 install contract

Append only: `sql/0007_p07_grant_registry.sql`. Do not edit `0000`–`0006` or `tools/apply_pg_cordis.py`.

Every numbered file (`sql/README.md:29-35`):

- replay-safe inside one tree-wide `--single-transaction`
- schema-qualified `cordis.*`, `search_path` independent
- no `\connect` / `GRANT` / `CREATE EXTENSION` / `public` tables / `CREATE SCHEMA absurd` / role DDL / transaction-control / psql meta-commands

Preflight word-boundary GRANT / REVOKE patterns scan the sanitized file (`tools/apply_pg_cordis.py:26-27`, `:217`). `sanitize_sql_for_preflight` blanks comments and dollar-quoted bodies (`:112`, `:206-208`). **Writing rule:** any natural-language use of the word GRANT/REVOKE/BEGIN/END in `0007` lives inside `$p07$` bodies or SQL comments. Identifiers such as `grants` / `grant_id` / `request_grant` are safe (`GRANT` + trailing identifier characters). Exception messages that contain the English word “grant” **must** sit inside `$p07$`.

`get_schema_version()` is replaced by the last numbered file. `0007` applies after `0006`, so the product tree reports `'p07'`.

### Loader: do not retouch

Same as P06: W09 already strips dollar quotes. P07 must not edit the apply tool.

### Tests that change when `0007` lands

| File | What changes |
|---|---|
| `tests/test_p00_sql_source.py` | Rename `test_fresh_apply_lists_current_tree_and_p06` → `…_and_p07`; file list adds `0007_p07_grant_registry.sql`; version `'p07'`; count the three new tables; `KERNEL_FUNCTIONS` exact list below; probe file-list at `:188` inserts `0007…` before `{probe_name}`; composition pin `:503` `'p07'` |
| `tests/test_p01_claim.py` | `:130` and `:495` `'p06'` → `'p07'` |
| `tests/test_p02_agent_steps.py` | full-tree `P02_DB` `:337` `'p06'` → `'p07'`; `P02_ONLY_DB` stays `'p02'` |
| `tests/test_p03_wait_event.py` | **no change** (P03-only tree stays `'p03'`) |
| `tests/test_p06_plugin_catalog.py` | in-place replay pin `:215` `'p06'` → `'p07'` |

Reuse `tests.conftest` (`run_apply`, `psql`, `next_sql_prefix`). Do not `import tools`. Do not duplicate helpers.

### Isolation proposal D is evidence, not ABI

`docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md` is the worked example and P1–P8 opinion. Signed D5 already chose enum C over SQL predicates and over `run_id`. Do not import `(grant_id, predicate, resources, capabilities)` as DDL. Do not add read/append/execute columns (that is A).

---

## Current-state analysis

| Component | Responsibility today | P07 consequence |
|---|---|---|
| `sql/0000_kernel.sql` | schema `cordis` + version function | Unchanged; `0007` replaces only the version **body** |
| `sql/0001_p01_claim.sql` | `cordis.jobs` keyed by unique `run_id` | Unchanged. Grants are workspace, not scheduler. **No FK** from slices/grants to `jobs` (a child run may receive grants before enqueue, P17) |
| `sql/0002_p02_log.sql` | append-only `agent_steps`; closed kind CHECK | Unchanged. Grant mutations do **not** emit log rows and do **not** ALTER the kind CHECK |
| `sql/0003_p03_wait_event.sql` | opaque `(event_scope_id, event_name)` | Unchanged. `event:<scope>` is authorization, not an event sentinel |
| `sql/0006_p06_plugin_catalog.sql` | `required_grants` kinds | Unchanged. P07 does not call `refresh_plugins` |
| Apply loader | discovery + GRANT/END preflight | Unchanged |

Workspace vs log (`snapshot.md:68-73`): grant/slice rows are **workspace** (run-owned execution state). They are not history and not a fold. P08 will read live workspace grants when assembling a projection.

---

## Design

### Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | `p_issuer_kind` is **asserted provenance**, not authentication. `request_grant` never writes `issued`. Issue/approve/deny/revoke/`create_slice`/`register_named_corpus` reject `p_issuer_kind='model'` (`42501`) so an honest control-plane caller cannot mislabel a model. Direct table writes and `issue_grant(..., 'host')` are **trusted control-plane**. P07 is not a model-exposed product surface; P08/P10 must not dispatch issue-family functions as model tools and must not turn four seams on while those verbs are reachable as tools. The named test proves only the asserted-kind rejection. | D5 “模型只能申请” plus the SQL-tree GRANT/ROLE ban (`sql/README.md:35`, `apply_pg_cordis.py:26-28`). v0 shares one DB user. Oracle round 1 P1.1. | Pretending `p_issuer_kind` authenticates the caller. Baking GRANT/ROLE into `0007`. Blocking P07 SQL until P08 exists (the registry must land first; exposure is the later gate). |
| 2 | Three tables: `named_corpora`, `slices`, `grants`. One `grants` row is bound to exactly one slice. | Skeleton: bind to slice, not the run union. P13 attaches selection to the same slice identity. Corpus roots are project-level, shared across runs. | A run-level grant table plus a join table that P08 could accidentally union. Baking grants into `jobs.payload`. |
| 3 | D5 stored as `(kind, target)` not a free-text predicate. `kind ∈ {run, named_corpus, event}`. `run` ⇒ `target = ''` (exact empty string). `named_corpus` ⇒ registered `corpus_id`. `event` ⇒ opaque scope copied from P03. Query API also returns `d5_literal` but does not parse it. | D5 C. P06 kinds-only. Ban extra JSON filters by not having those parameters. | SQL predicate (B). Descriptor A. Storing only a D5 literal and parsing at every call. |
| 4 | `named_corpus:<id>` is a **live-root identity**. Whole registered root: no version suffix, no subset path, no file list, no revision/fingerprint column in P07. Membership of that root may change later; P07 does **not** freeze corpus bytes. P13/P08 must pin a snapshot themselves if they need one. Test: no snapshot/revision table or column exists. | Skeleton 「整根」. Snapshot §10.5 freeze-vs-in-flight is closed here as **live root**, which is an explicit departure from “run 期内冻结快照”, not a silent default. Oracle round 1 P1.4. | Pretending `(kind,target)` immutability freezes file contents. A fake unused `content_revision` column. `named_corpus:<id>@v1`. |
| 5 | **No silent expansion of the grant set.** Issued `(kind, target)` never mutates. `request_grant` never writes `issued`. Adding a **different** range is an explicit `issue_grant` of another tuple. Explicit mid-run issue is allowed. “不静默扩权” in P07 means this grant-set rule, not content freeze (decision 4). | Skeleton 偏安 applied to rights, which is what P07 can enforce. | Auto-approve. Mutating target. A run-start freeze of the live set that would block an explicit second issue. Calling live-root “frozen”. |
| 6 | `grants` is **current workspace state only**: exactly one row per `(slice_id, kind, target)` for all statuses. Re-request / re-issue / approve / deny / revoke reuse that `grant_id`. `decided_*` / `revoked_*` describe the **current** status, not an audit log. Do not emit grant kinds into `agent_steps`. | Snapshot: log is history, grants are workspace. Retaining terminal rows “for audit” would be a second SoT (Oracle P1.5). | New `grant_id` after deny/revoke. `grant/*` log kinds. Claiming denied rows are historical truth. |
| 7 | Holding `event:<scope>` authorizes emit **and** await of every name under that scope. Holding `run` authorizes this run’s own workspace/log for that slice. Holding `named_corpus:<id>` authorizes retrieval from that live root. No capability column. | D5 C vs F’s finer `event.await on (scope, name)`. Finer split is A. | `capabilities text[]`. Per-event-name grants. |
| 8 | No `grants.run_id` column. No FK to `jobs`. `slices.run_id` uses the same contract as `agent_steps.run_id`: non-blank (`btrim <> ''`), stored **as given**, no P07 length limit, no trim-before-store. Functions take `p_run_id` only as an ownership fence: `p_run_id IS NOT DISTINCT FROM slices.run_id` (exact bytes). FK `grants.slice_id → slices.slice_id` `ON DELETE RESTRICT`. No FK to `run_events` or `named_corpora`. | P02 `sql/0002_p02_log.sql:13-14,55-58`. Oracle P1.2. P17 may issue before enqueue. | Trim/256-byte P07-only run_id. Duplicate `grants.run_id` without a composite FK. Jobs FK. |
| 9 | Table UNIQUE `(slice_id, kind, target)` covering every status. Same corpus on two slices is allowed. | Current-state registry. Worked example needs two slices. | Partial unique on pending/issued only (Oracle P1.5/P1.3). UNIQUE `(run_id, kind, target)`. |
| 10 | Retrieval-oriented API is **only** `slice_live_grants(run_id, slice_id)` and `slice_has_grant(...)`. Inventory is `SELECT` from `cordis.grants`. | Snapshot §9. | `cordis.run_live_grants` / `run_grants`. |
| 11 | `0007` replaces the version body with `'p07'`. Product tree reports `'p07'`. | Numeric apply order. | Expecting `'p06'` after `0007`. |
| 12 | P07 does not wrap P03 verbs, does not refresh the plugin catalog, does not add log kinds, does not create RLS policies, and does not create a default slice. | Four-seam work is P08. | Implicit slice-per-run. Grant check inside `await_event`. |
| 13 | Writer lock order is **slice row `FOR UPDATE` → matching grant row `FOR UPDATE`** (if it exists). Isolation: default READ COMMITTED. Slice lock is the linearization point for all grant mutations on that slice. Live-query functions do **not** take `FOR UPDATE`. Do not depend on serializable `40001`. | Oracle P1.3. `FOR SHARE` plus a partial unique index does not serialize deny/revoke against request/issue. | Grant-first locking. Catch-all `23505` without holding the slice. |
| 14 | Event `target` copies P03 `event_scope_id`: `CHECK (pg_catalog.btrim(target) <> '')`, store the value byte-for-byte, no charset/length grammar. `d5_literal` is `'event:' || target` and may contain extra colons; callers must not parse it. A P03-accepted scope must round-trip through P07. | `sql/0003_p03_wait_event.sql:15` `run_events_scope_nonblank_check`. Oracle P1.6. | `[A-Za-z0-9._-]{1,128}` or banning `:`. Trimming before store. FK to `run_events`. |

No implementation question remains open for P07. Deferred: role/RLS principal (P08+), four-seam filtering (P08), selection (P13), child inherit (P17), **corpus content snapshot** (explicitly not P07; live root), descriptor A, emit-vs-await split, freeze-live-set-at-first-fold (P08).

---

## Component 1 — `sql/0007_p07_grant_registry.sql`

### File contract

**Kind:** numbered SQL source file  
**Path:** `sql/0007_p07_grant_registry.sql`  
**Applied:** after `0006_p06_plugin_catalog.sql` (numeric order)

The file must be replay-safe and contain, in order:

1. `cordis.named_corpora`;
2. `cordis.slices`;
3. `cordis.grants` + indexes;
4. `cordis.register_named_corpus`;
5. `cordis.create_slice`;
6. `cordis.request_grant`;
7. `cordis.issue_grant`;
8. `cordis.approve_grant`;
9. `cordis.deny_grant`;
10. `cordis.revoke_grant`;
11. `cordis.slice_live_grants`;
12. `cordis.slice_has_grant`;
13. replacement `cordis.get_schema_version` returning `p07`.

All plpgsql functions are `SECURITY INVOKER` and pin `search_path` to `pg_catalog`. Writers are `VOLATILE`; the two read functions are `STABLE`. The version function remains `LANGUAGE sql IMMUTABLE SECURITY INVOKER` and, matching `0001`–`0006`, does **not** set `search_path` (literal-only body). Schema-qualify builtins in plpgsql (`pg_catalog.clock_timestamp()`, `pg_catalog.gen_random_uuid()`, `pg_catalog.btrim()`, `pg_catalog.octet_length()`).

Outer dollar-quote tag for every plpgsql body: `$p07$`. No nested dollar tags. No `COMMENT` beginning with `{`.

Do not `SELECT cordis.refresh_plugins()`. Do not reference `plugin_catalog` except in comments inside `$p07$` / `--` lines.

---

## Component 2 — DDL

### `cordis.named_corpora`

**Kind:** persistent kernel workspace table  
**Lifecycle:** inserted by `register_named_corpus`; never updated in P07; not deleted in P07  
**Historical authority:** none

| Column | Type | Null/default | Meaning |
|---|---|---|---|
| `corpus_id` | `text` | `NOT NULL` | Whole-root identity; D5 `named_corpus:<id>` uses this id |
| `label` | `text` | `NOT NULL` | Display label; not part of the D5 literal |
| `created_by_kind` | `text` | `NOT NULL` | `user` or `host` |
| `created_at` | `timestamptz` | `NOT NULL DEFAULT pg_catalog.clock_timestamp()` | First insert |

Named constraints:

| Name | Exact contract |
|---|---|
| `named_corpora_pkey` | `PRIMARY KEY (corpus_id)` |
| `named_corpora_id_check` | `CHECK (corpus_id ~ '^[a-z][a-z0-9_-]{0,127}$')` |
| `named_corpora_label_check` | `CHECK (pg_catalog.btrim(label) <> '' AND pg_catalog.octet_length(label) <= 256 AND label !~ '[[:cntrl:]]')` |
| `named_corpora_created_by_kind_check` | `CHECK (created_by_kind IN ('user', 'host'))` |

No version column. No path column. No file list.

### `cordis.slices`

**Kind:** persistent kernel workspace table  
**Lifecycle:** inserted by `create_slice`; never updated/deleted in P07  
**Historical authority:** none. P13 may later add a selection side table keyed by `slice_id`.

| Column | Type | Null/default | Meaning |
|---|---|---|---|
| `slice_id` | `uuid` | `NOT NULL DEFAULT pg_catalog.gen_random_uuid()` | Stable id for P13 and grant FK |
| `run_id` | `text` | `NOT NULL` | Logical run; not a jobs FK |
| `name` | `text` | `NOT NULL` | Human name, unique per run |
| `created_by_kind` | `text` | `NOT NULL` | `user` or `host` |
| `created_at` | `timestamptz` | `NOT NULL DEFAULT pg_catalog.clock_timestamp()` | First insert |

Named constraints:

| Name | Exact contract |
|---|---|
| `slices_pkey` | `PRIMARY KEY (slice_id)` |
| `slices_run_name_key` | `UNIQUE (run_id, name)` |
| `slices_run_id_check` | `CHECK (pg_catalog.btrim(run_id) <> '')` — store `run_id` as given; do not trim or length-cap |
| `slices_name_check` | `CHECK (name ~ '^[a-z][a-z0-9_-]{0,63}$')` |
| `slices_created_by_kind_check` | `CHECK (created_by_kind IN ('user', 'host'))` |

Index: PK and unique constraint are enough. No extra index required.

### `cordis.grants`

**Kind:** persistent kernel workspace table  
**Lifecycle:** current-state upsert per `(slice_id, kind, target)`; `kind`/`target`/`slice_id`/`grant_id` never change after insert  
**Historical authority:** none. The row is the live workspace fact for that tuple. Timestamps describe current status only.

| Column | Type | Null/default | Meaning |
|---|---|---|---|
| `grant_id` | `uuid` | `NOT NULL DEFAULT pg_catalog.gen_random_uuid()` | Stable id for this tuple |
| `slice_id` | `uuid` | `NOT NULL` | Binding target; run is `slices.run_id` |
| `kind` | `text` | `NOT NULL` | `run` / `named_corpus` / `event` |
| `target` | `text` | `NOT NULL` | `''` for `run`; corpus id; event scope as given |
| `status` | `text` | `NOT NULL` | `pending` / `issued` / `denied` / `revoked` |
| `requested_by_kind` | `text` | `NOT NULL` | Actor that opened the **current pending cycle** (or the issuer on a fresh direct issue). Duplicate pending requests do not change it. |
| `decided_by_kind` | `text` | nullable | Current decider if not pending |
| `revoked_by_kind` | `text` | nullable | Current revoker if revoked |
| `created_at` | `timestamptz` | `NOT NULL DEFAULT pg_catalog.clock_timestamp()` | First insert of this tuple |
| `decided_at` | `timestamptz` | nullable | Time of the current non-pending decision |
| `revoked_at` | `timestamptz` | nullable | Time of the current revoke |

Named constraints:

| Name | Exact contract |
|---|---|
| `grants_pkey` | `PRIMARY KEY (grant_id)` |
| `grants_slice_kind_target_key` | `UNIQUE (slice_id, kind, target)` |
| `grants_slice_fkey` | `FOREIGN KEY (slice_id) REFERENCES cordis.slices(slice_id) ON DELETE RESTRICT` |
| `grants_kind_check` | `CHECK (kind IN ('run', 'named_corpus', 'event'))` |
| `grants_status_check` | `CHECK (status IN ('pending', 'issued', 'denied', 'revoked'))` |
| `grants_requested_by_kind_check` | `CHECK (requested_by_kind IN ('model', 'user', 'host'))` |
| `grants_decided_by_kind_check` | `CHECK (decided_by_kind IS NULL OR decided_by_kind IN ('user', 'host'))` |
| `grants_revoked_by_kind_check` | `CHECK (revoked_by_kind IS NULL OR revoked_by_kind IN ('user', 'host'))` |
| `grants_target_by_kind_check` | see predicate below |
| `grants_status_times_check` | see predicate below |

`grants_target_by_kind_check` must be logically equivalent to:

```text
(kind = 'run' AND target = '')
OR (kind = 'named_corpus' AND target ~ '^[a-z][a-z0-9_-]{0,127}$')
OR (kind = 'event' AND pg_catalog.btrim(target) <> '')
```

Event target is stored as given. Do not add a charset or length CHECK. Colon, slash, and mixed case are legal because P03 accepts them.

`grants_status_times_check` must be logically equivalent to:

```text
(status = 'pending'
   AND decided_by_kind IS NULL AND decided_at IS NULL
   AND revoked_by_kind IS NULL AND revoked_at IS NULL)
OR (status = 'issued'
   AND decided_by_kind IS NOT NULL AND decided_at IS NOT NULL
   AND revoked_by_kind IS NULL AND revoked_at IS NULL)
OR (status = 'denied'
   AND decided_by_kind IS NOT NULL AND decided_at IS NOT NULL
   AND revoked_by_kind IS NULL AND revoked_at IS NULL)
OR (status = 'revoked'
   AND decided_by_kind IS NOT NULL AND decided_at IS NOT NULL
   AND revoked_by_kind IS NOT NULL AND revoked_at IS NOT NULL)
```

Lookup index (no `run_id` column):

```text
CREATE INDEX grants_slice_status_idx
    ON cordis.grants (slice_id, status, kind, target);
```

No partial unique index. `grants_slice_kind_target_key` is the conflict target:

```text
ON CONFLICT ON CONSTRAINT grants_slice_kind_target_key
```

`ON DELETE RESTRICT` on the slice FK: deleting a slice that still has grant rows must fail loudly. P07 has no slice-delete verb.

Do not add UNIQUE `(run_id, kind, target)` — two slices of one run may hold the same corpus.

---

## Component 3 — Validation groups and locking

Do not run one undifferentiated checklist on every function. Named groups:

| Group | Checks |
|---|---|
| **Issuer** | `p_issuer_kind = 'model'` → `'issuer must not be model'` / `42501`. Any other value not in `('user','host')` → `'invalid issuer_kind'` / `22023`. This is asserted provenance. |
| **Requester** | `p_requester_kind IN ('model','user','host')` else `'invalid requester_kind'` / `22023`. |
| **Run/slice** | `p_run_id` is not SQL NULL and `btrim(p_run_id) <> ''` — do **not** trim before compare or store, do **not** length-cap. `SELECT ... FROM cordis.slices WHERE slice_id = p_slice_id FOR UPDATE` (writers) or no lock (live-query). Missing → `'slice not found'` / `22023`. `slices.run_id IS DISTINCT FROM p_run_id` → `'slice does not belong to run'` / `22023`. |
| **Kind/target** | `p_kind IN ('run','named_corpus','event')` else `'unknown grant kind'` / `22023`. Reject `p_kind` containing `:`. `p_target` NULL becomes `''` **only for `kind='run'`**; event/corpus targets are stored as given (NULL corpus/event target → `'invalid grant target'`). Pairing must match `grants_target_by_kind_check`. `named_corpus` requires `EXISTS` in `named_corpora` (`'unknown named corpus'`). No jsonb predicate parameter. |
| **Grant locator** | For grant-id APIs only: `SELECT slice_id, status FROM cordis.grants WHERE grant_id = p_grant_id` with **no** row lock. Missing → `'grant not found'` / `22023`. This is not a lock step. |
| **Grant-state** | After the slice is already locked: `SELECT ... FROM cordis.grants ... FOR UPDATE` by `(slice_id, kind, target)` or by `grant_id`. Missing / wrong status → `'grant not found'` / `'grant is not pending'` / `'grant is not issued'`. Never take this lock before the slice lock. |

Which group each function uses, in this order:

| Function | Groups then mutations |
|---|---|
| `register_named_corpus` | Issuer; corpus id/label CHECKs; insert |
| `create_slice` | Issuer; run/name CHECKs (run stored as given); insert |
| `request_grant` | Requester; kind/target; run/slice **FOR UPDATE**; grant-state on the tuple; upsert |
| `issue_grant` | Issuer; kind/target; run/slice **FOR UPDATE**; grant-state on the tuple; upsert |
| `approve_grant` / `deny_grant` / `revoke_grant` | Issuer; **grant locator** (unlocked); slice `FOR UPDATE`; grant-state `FOR UPDATE`; status-guarded update |
| `slice_live_grants` / `slice_has_grant` | Run/slice **without** `FOR UPDATE`; kind/target only for `slice_has_grant` |

**Lock order for every writer that touches grants:**

1. If the public arguments include `p_grant_id`, **grant locator** (unlocked) to learn `slice_id`.
2. Lock that `cordis.slices` row `FOR UPDATE`.
3. Re-read the grant `FOR UPDATE`.
4. Validate expected status and mutate.

Never lock grant before slice. Isolation is READ COMMITTED. Do not require the caller to handle `40001`.

Error SQLSTATE: `42501` only for `'issuer must not be model'`; everything else `22023`. Messages live inside `$p07$`. Do not consult `plugin_catalog`.

---

## Component 4 — Corpus and slice verbs

### `cordis.register_named_corpus`

```text
cordis.register_named_corpus(
    p_corpus_id    text,
    p_label        text,
    p_issuer_kind  text
) RETURNS text
```

Catalog identity: `cordis.register_named_corpus(text,text,text)`.

Steps:

1. Issuer group.
2. `p_corpus_id` must match `named_corpora_id_check` as given (`'invalid corpus id'`). Do not trim the id; the regex already forbids leading space.
3. `p_label` must satisfy `named_corpora_label_check` (`'invalid corpus label'`). Store label as given.
4. `INSERT`. On PK conflict: if the existing label equals `p_label` (exact), return `corpus_id`. Else `'corpus already registered'` / `22023`.
5. Return `corpus_id`.

Do not update `label` in place.

### `cordis.create_slice`

```text
cordis.create_slice(
    p_run_id       text,
    p_name         text,
    p_issuer_kind  text
) RETURNS uuid
```

Catalog identity: `cordis.create_slice(text,text,text)`.

Steps:

1. Issuer group.
2. `p_run_id` not null and `btrim(p_run_id) <> ''` (`'invalid run_id'`). Store **as given**.
3. `p_name` matches `slices_name_check` (`'invalid slice name'`).
4. `INSERT ... RETURNING slice_id`. Unique `(run_id, name)` → `'duplicate slice name'` / `22023`.
5. Return `slice_id`.

No default slice. No jobs row required.

---

## Component 5 — `cordis.request_grant`

```text
cordis.request_grant(
    p_run_id          text,
    p_slice_id        uuid,
    p_kind            text,
    p_target          text,
    p_requester_kind  text
) RETURNS uuid
```

Catalog identity: `cordis.request_grant(text,uuid,text,text,text)`.

This is the only model-facing writer. It must not write `status = 'issued'`.

Steps (one transaction):

1. Requester group, kind/target group.
2. Lock slice `FOR UPDATE`; run/slice ownership fence (exact `run_id`).
3. `SELECT ... FOR UPDATE` the unique `(slice_id, kind, target)` row if any.
4. No row → `INSERT` pending (`requested_by_kind = p_requester_kind`, decided/revoked NULL). On unexpected `23505`, re-enter from step 3 once.
5. `pending` → return `grant_id` and leave the row **unchanged**, including `requested_by_kind` (duplicate request does not start a new pending cycle).
6. `issued` → return `grant_id` with **no** column changes (observation, not approval).
7. `denied` or `revoked` → `UPDATE` to `pending`, set `requested_by_kind` to this requester (new pending cycle), clear decided/revoked columns. Same `grant_id`.
8. Return `grant_id`.

After step 4 or 7, `slice_has_grant` is false.

---

## Component 6 — Issue / approve / deny / revoke

Apply **to_issued(issuer)**: `status='issued'`, `decided_by_kind=issuer`, `decided_at=clock_timestamp()`, `revoked_by_kind=NULL`, `revoked_at=NULL`. Leave `requested_by_kind` as already stored on an existing row; on a fresh insert set it to `issuer`.

Apply **to_denied(issuer)**: `status='denied'`, set decided columns, clear revoked columns.

Apply **to_revoked(issuer)**: `status='revoked'`, set `revoked_by_kind`/`revoked_at`, leave `decided_*` as they were from the issue that is being revoked.

### `cordis.issue_grant`

```text
cordis.issue_grant(
    p_run_id       text,
    p_slice_id     uuid,
    p_kind         text,
    p_target       text,
    p_issuer_kind  text
) RETURNS uuid
```

Catalog identity: `cordis.issue_grant(text,uuid,text,text,text)`.

Trusted control-plane. Asserted `model` rejected by issuer group.

Steps:

1. Issuer, kind/target, lock slice `FOR UPDATE`, ownership fence.
2. `SELECT ... FOR UPDATE` the unique tuple.
3. No row → `INSERT` issued via **to_issued**.
4. `issued` → return `grant_id` (idempotent, not expansion).
5. `pending` / `denied` / `revoked` → **to_issued**, same `grant_id`.
6. Return `grant_id`.

### `cordis.approve_grant`

```text
cordis.approve_grant(p_grant_id uuid, p_issuer_kind text) RETURNS uuid
```

Catalog identity: `cordis.approve_grant(uuid,text)`.

1. Issuer group.
2. Grant locator (unlocked) for `slice_id`; lock that slice `FOR UPDATE`; grant-state `FOR UPDATE`.
3. Missing → `'grant not found'`. `status <> 'pending'` → `'grant is not pending'`.
4. **to_issued**. Return `grant_id`.

### `cordis.deny_grant`

```text
cordis.deny_grant(p_grant_id uuid, p_issuer_kind text) RETURNS uuid
```

Catalog identity: `cordis.deny_grant(uuid,text)`.

Same lock order. Only `pending` → **to_denied**. Live set unchanged.

### `cordis.revoke_grant`

```text
cordis.revoke_grant(p_grant_id uuid, p_issuer_kind text) RETURNS uuid
```

Catalog identity: `cordis.revoke_grant(uuid,text)`.

Same lock order. Only `issued` → **to_revoked**. Subsequent `slice_live_grants` omits it. Re-issue of the same tuple uses **the same** `grant_id` (issue step 5).

Do not UPDATE `kind` or `target` on any path.

Concurrent writers on one slice serialize on the slice row. Outcomes are by **linearization order** (who first acquired the slice `FOR UPDATE`), not by who committed last after waiting.

Required two-session proofs (`test_p07_concurrent_request_issue_deny_revoke`). Each case: transaction A acquires the slice lock and **holds it**; transaction B’s matching writer is shown to **block**; A then commits or rolls back; B unblocks and its exact result is asserted.

| Setup | Linearization | After both complete |
|---|---|---|
| No row; A `request_grant`, B `issue_grant` (or the reverse) | Either order | Exactly one row. If issue linearized first: `issued` and request returns that id with no status change. If request linearized first: `pending` then issue promotes to `issued`. Final status is **`issued`** whenever both verbs succeed. |
| `issued`; A `issue_grant`, B `revoke_grant` | Issue then revoke | `revoked`, not live. Same `grant_id`. |
| `issued`; A `revoke_grant`, B `issue_grant` | Revoke then issue | `issued` (re-issue of the same `grant_id`), live. |
| `pending`; A `deny_grant`, B `issue_grant` | Deny then issue | Deny succeeds (`denied`); issue then **to_issued**. Final **`issued`**. Both succeed. |
| `pending`; A `issue_grant`, B `deny_grant` | Issue then deny | Issue succeeds (`issued`); deny then raises `22023` `'grant is not pending'`. Final **`issued`**. |

Never two rows. No client-visible `23505`. Do **not** claim “deny last ⇒ denied” when issue is also in flight: deny that linearizes after issue must fail.

---

## Component 7 — Live query (the P08 read surface)

### `cordis.slice_live_grants`

```text
cordis.slice_live_grants(
    p_run_id    text,
    p_slice_id  uuid
) RETURNS TABLE (
    grant_id    uuid,
    kind        text,
    target      text,
    d5_literal  text
)
```

Catalog identity: `cordis.slice_live_grants(text,uuid)`.

`STABLE`. Run/slice group **without** `FOR UPDATE` (missing slice → raise, not empty). Compare `p_run_id` to `slices.run_id` with exact bytes. Return only `status = 'issued'` rows for that slice. Join grants via `slice_id`; do not read a `grants.run_id` column (there is none).

`d5_literal`:

```text
run            → 'run'
named_corpus   → 'named_corpus:' || target
event          → 'event:' || target
```

`event` literals may contain extra colons if the P03 scope did. Do not parse `d5_literal` in kernel code.

Order: `kind, target, grant_id` for deterministic tests.

An unknown slice **raises**; a known slice with no issued grants returns zero rows.

### `cordis.slice_has_grant`

```text
cordis.slice_has_grant(
    p_run_id    text,
    p_slice_id  uuid,
    p_kind      text,
    p_target    text
) RETURNS boolean
```

Catalog identity: `cordis.slice_has_grant(text,uuid,text,text)`.

`STABLE`. Shared kind/target validation. `true` iff an `issued` row exists for that exact tuple. Pending/denied/revoked → `false`. Missing slice → raise.

Do **not** add `cordis.run_live_grants` or any function whose documented purpose is “union of this run’s grants for retrieval.”

---

## Component 8 — Version, README, KERNEL_FUNCTIONS

End of `0007`:

```sql
CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p07'::text;
$$;
```

`sql/README.md` — extend the version ladder:

```text
tree including 0006_p06_plugin_catalog.sql → p06
tree including 0007_p07_grant_registry.sql → p07  (current product tree)
```

Add a short paragraph: `0007` adds `named_corpora`, `slices`, `grants`; live rights are slice-bound D5 enums; model-facing writer is `request_grant`; issue-family writers reject asserted `issuer_kind='model'` (provenance, not auth); `required_grants` on the plugin catalog remain kinds; `named_corpus` is a live-root identity.

### Exact `KERNEL_FUNCTIONS` after P07

`tests/test_p00_sql_source.py` compares `nspname || '.' || proname ORDER BY 1` to this tuple **exactly**, using the same query the file already has (no collation change, no claim that `ORDER BY 1` is C). `_validate_plugin_definition` remains first under that existing query:

```python
KERNEL_FUNCTIONS = (
    "cordis._validate_plugin_definition",
    "cordis.approve_grant",
    "cordis.await_event",
    "cordis.checkpoint",
    "cordis.claim_job",
    "cordis.complete_claim",
    "cordis.create_slice",
    "cordis.deny_grant",
    "cordis.emit_event",
    "cordis.emit_step",
    "cordis.emit_step_claimed",
    "cordis.fail_claim",
    "cordis.get_schema_version",
    "cordis.issue_grant",
    "cordis.llm_checkpoint",
    "cordis.next_step_name",
    "cordis.refresh_plugins",
    "cordis.register_host_plugin",
    "cordis.register_named_corpus",
    "cordis.release_stale",
    "cordis.renew_claim",
    "cordis.request_grant",
    "cordis.revoke_grant",
    "cordis.run_state",
    "cordis.slice_has_grant",
    "cordis.slice_live_grants",
    "cordis.unregister_host_plugin",
    "cordis.yield_claim",
)
```

Do not add a helper `cordis._d5_literal` (it would appear in this list). Inline literal formatting in `slice_live_grants`.

No overloads.

---

## Implementation order

1. Write complete `sql/0007_p07_grant_registry.sql` (DDL → verbs → version `'p07'`). Do not merge a partial file. Do not edit `0000`–`0006` or `apply_pg_cordis.py`.
2. Update `sql/README.md` current-tree marker to `p07`.
3. Retarget product-tree tests listed in W76.
4. Add `tests/test_p07_grant_registry.py` using `tests.conftest` helpers.
5. `uv run pytest tests/test_p07_grant_registry.py tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py tests/test_p06_plugin_catalog.py -q` then the full suite including `tests/test_p03_wait_event.py`.
6. Do not start P08 until the two-slice proof and the pending-request proof are green.

---

## Verification

All commands from `zcordis-pgembed`. Disposable DBs. pytest via `[dependency-groups] dev`. CLI via `sys.executable` + `tools/apply_pg_cordis.py` subprocess — never `import tools`. No test relies on a permanently running postmaster between sequential CLI subprocesses.

### Exact test module and names

Add `tests/test_p07_grant_registry.py`:

| Test | Required proof |
|---|---|
| `test_p07_fresh_apply_catalog_and_version` | Product-tree file list includes `0007`; version `p07`; three new tables exist once; `jobs` / `agent_steps` / `run_events` / `plugin_catalog` still exist; `grants` has no `run_id` column; no `public` P07 table; no `pg_cordis` extension; exact function identities and `VOLATILE`/`STABLE`/`INVOKER` |
| `test_p07_constraints_and_tuple_unique` | Named CHECKs, FK RESTRICT, table UNIQUE `(slice_id, kind, target)`, no `grants.run_id`, `run` target empty, event target only `btrim <> ''` |
| `test_p07_two_named_corpus_on_two_slices` | **Full skeleton proof in one test:** register `project-1`/`project-2`; two slices on one `run_id`; issue each corpus to a different slice; `slice_live_grants` A only `named_corpus:project-1`, B only `named_corpus:project-2`; then `request_grant` of `project-2` onto slice A with requester `model` stays `pending` and `slice_has_grant` A/`project-2` is false. Must execute the Protocol assertions sequence below, not a subset. |
| `test_p07_model_request_stays_pending` | Isolated `request_grant(..., 'model')` on an empty tuple is pending and not live (still required; the combined proof lives in the test above) |
| `test_p07_issue_rejects_asserted_model_kind` | issue family + `create_slice` + `register_named_corpus` with `issuer_kind='model'` raise `42501` and fragment `issuer must not be model`; no row written. This does **not** prove caller identity. |
| `test_p07_approve_and_deny_pending` | Model request then host `approve_grant` → issued and live; a second request on another tuple then `deny_grant` → `denied`, still not live |
| `test_p07_request_is_idempotent_and_does_not_approve` | Second `request_grant` on a pending tuple returns the same id and leaves `requested_by_kind` unchanged even if the second requester differs; `issue_grant` of an already-issued tuple returns the same id with no second row; request against issued does not change columns |
| `test_p07_rejects_sql_predicate_and_version_suffix` | `kind='named_corpus:project-1'`, `target='project-1:v1'`, `target='project-1 WHERE true'`, `kind='run OR true'` all raise `22023` before insert |
| `test_p07_unknown_corpus_and_slice_mismatch` | Issue `named_corpus` before register raises; slice of run A used with run B raises `slice does not belong to run` |
| `test_p07_event_and_run_kinds` | Issue `run` (empty target) and `event` + opaque scope onto a slice; live literals are `run` and `event:` concatenated with the stored target; no `run_events` row is created by issue itself |
| `test_p07_event_scope_round_trips_p03_opacity` | `emit_event('Acme/scope:v1', 'n', '{}'::jsonb)` succeeds (P03 non-blank scope); `issue_grant` of kind `event` with the **same bytes** stores that target; `d5_literal` is `event:Acme/scope:v1`; emit still does not consult grants |
| `test_p07_revoke_drops_live_not_log` | Issue then revoke → not live; `agent_steps` count for that `run_id` unchanged if the test never emitted; re-issue reuses the **same** `grant_id` and is live again |
| `test_p07_corpus_is_live_root_identity` | After register+issue, catalog has no revision/fingerprint/snapshot table or column on `named_corpora`/`grants`; comment in the test records live-root (content may change later) |
| `test_p07_concurrent_request_issue_deny_revoke` | Uses `psql_session`. For each table row in Component 6: A holds the slice lock, B blocks, A commits, B’s exact result matches the linearization table (including deny-after-issue → `22023`). One row per tuple; no client-visible `23505`. |
| `test_p07_api_errors_are_22023` | Parameterized negatives raise `22023`: SQL NULL ids/labels/names/kinds; NULL `p_target` for `named_corpus` and `event`; invalid non-model issuer/requester; conflicting corpus label; duplicate slice name. Separate positive case: `kind='run'` with `p_target=NULL` stores `target=''` and does not raise. Direct table CHECK failures are out of scope. |
| `test_p07_no_run_union_retrieval_function` | `to_regprocedure` / `pg_proc` has no `cordis` function whose name is `run_live_grants` or `run_grants`; inventory is table `SELECT` only |
| `test_p07_replay_preserves_grants` | In-place apply keeps corpus/slice/grant rows, statuses, and timestamps |
| `test_p07_sql_tree_grant_word_only_in_quotes_or_comments` | `0007` scanned with `sanitize_sql_for_preflight` still has no GRANT token (covered by existing `test_sql_tree_has_no_forbidden_tokens`; this test additionally asserts the file uses `$p07$` for plpgsql) |

### Catalog assertions

Product-tree file list:

```text
0000_kernel.sql,
0001_p01_claim.sql,
0002_p02_log.sql,
0003_p03_wait_event.sql,
0006_p06_plugin_catalog.sql,
0007_p07_grant_registry.sql
```

Exact new identities:

```text
cordis.register_named_corpus(text,text,text)
cordis.create_slice(text,text,text)
cordis.request_grant(text,uuid,text,text,text)
cordis.issue_grant(text,uuid,text,text,text)
cordis.approve_grant(uuid,text)
cordis.deny_grant(uuid,text)
cordis.revoke_grant(uuid,text)
cordis.slice_live_grants(text,uuid)
cordis.slice_has_grant(text,uuid,text,text)
```

Writers `VOLATILE`; `slice_live_grants` and `slice_has_grant` `STABLE`; all `SECURITY INVOKER`; version zero-arg `text`, SQL, immutable, invoker; no overloads.

### Protocol assertions for the two-slice proof

After:

```sql
SELECT cordis.register_named_corpus('project-1', 'Project 1', 'host');
SELECT cordis.register_named_corpus('project-2', 'Project 2', 'host');
-- s1 := create_slice('run-d5', 'fn-1', 'host')
-- s2 := create_slice('run-d5', 'fn-2-3', 'host')
SELECT cordis.issue_grant('run-d5', s1, 'named_corpus', 'project-1', 'host');
SELECT cordis.issue_grant('run-d5', s2, 'named_corpus', 'project-2', 'host');
SELECT cordis.request_grant('run-d5', s1, 'named_corpus', 'project-2', 'model');
```

Assert:

- `slice_live_grants('run-d5', s1)` → one row, `d5_literal = 'named_corpus:project-1'`;
- `slice_live_grants('run-d5', s2)` → one row, `d5_literal = 'named_corpus:project-2'`;
- `slice_has_grant('run-d5', s1, 'named_corpus', 'project-2')` is false;
- the model request row has `status = 'pending'` and `requested_by_kind = 'model'`;
- a join `grants` ⋈ `slices` for `run_id = 'run-d5'` may show both issued rows **and** the pending row — that inventory is not a retrieval API (`grants` has no `run_id` column).

### Commands

```bash
export CORDIS_ROOT=/path/to/zcordis-pgembed
cd "$CORDIS_ROOT"

uv run pytest tests/test_p07_grant_registry.py -q
uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py tests/test_p06_plugin_catalog.py tests/test_p03_wait_event.py -q
PGCORDIS_PGDATA="$CORDIS_ROOT/.pgdata" uv run pytest -q
```

---

## Risks

- **Same-user SQL.** Decision 1 is asserted provenance. A client that can run arbitrary SQL can call `issue_grant(...,'host')`. P07 must not be described as enforcement-complete. P08/P10 are the exposure wall.
- **P03 remains unauthorized.** Emit/await still work without `event:<scope>` until P08.
- **Live root.** Granting `named_corpus:<id>` does not freeze files. P13/P08 must pin a snapshot if they need one.
- **Jobs independence.** Grants can exist for a `run_id` with no jobs row.
- **Approve/deny/revoke lock order.** Must take the slice before the grant row even though the public signature only has `grant_id`.

---

## Open questions

None remaining for P07 implementation. Deferred (not this file):

- four-seam filtering and “half-enforcement must not ship” (P08);
- Postgres roles / RLS principals (P08+, requires a later exception to the GRANT ban or a superuser setup path outside `sql/`);
- exposing or hiding issue-family verbs from the model (P08/P10 delivery gate);
- StoredSelection on slices (P13);
- child grant copy (P17);
- corpus **content** snapshots / version subsets (explicit live-root in P07);
- structured descriptor A;
- emit vs await vs per-name event capabilities;
- freeze-live-set-at-first-fold.

---

## References

- `docs/plans/2026-08-23-pg-cordis-development.md:178-186` — P07 skeleton; `:190-198` P08; `:265-268` P13
- `docs/decisions/2026-08-23-pending.md:18`, `:53`, `:264-303` — D5
- `docs/analysis/2026-08-23-i-architecture-snapshot.md:39`, `:54`, `:97`, `:125`, `:138`, `:222`, `:236`, `:252`
- `docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md` — worked example (evidence)
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:14`, `:186` — event capability grain
- `docs/plans/P06-plugin-catalog-2026-08-23.md` — kinds-only `required_grants`; W60–W66; deferred issuance
- `docs/plans/P03-wait-event-2026-08-24.md` — opaque event scope; no grant check
- `sql/README.md`, `sql/0002_p02_log.sql:3-27`, `sql/0006_p06_plugin_catalog.sql` constraint `plugin_catalog_required_grants_check`
- `tools/apply_pg_cordis.py:21-34`, `:112`, `:206-218`
- `tests/test_p00_sql_source.py:23-65`, `:188`, `:503`
- `tests/conftest.py` — `run_apply`, `psql`, `next_sql_prefix`, `psql_session`
