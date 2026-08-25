# P08 — Four-seam enforcement

Date: 2026-08-24
Status: **ready to implement**
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P08
Depends on: P02, P05, P07 (implemented); P19 is in the product tree and constrains fold ABI / file order
Parallel with: P09, P10
Contract: D5; recall, fold, env read, and tool dispatch all enforce the calling slice’s live grants; half-enforcement must not ship
Primary deliverable: `sql/0020_p08_four_seam_enforcement.sql`
Critique: `docs/reviews/2026-08-24-p08-plan-critique.md` (P0/P1 folded below)
Plan export: `prompt-exports/oracle-plan-2026-08-25-013020-p08-four-seam-plan-3-a90b.md`

The context_builder export contains three concatenated drafts. This document is the orchestrator integration: version 1 is the preservation baseline (scoped log, latch catalog, P19 fold adapter, no `step_once`/`P03` wrap). Version 2’s `step_once` rewrite and version 3’s “no writer / env returns NULL” simplifications are recorded as rejected alternatives where they conflict with the leak fixture or P19 tests.

**Mid-flow lock (2026-08-24, user):** keep `step_once` unwrapped; replace the two P19 fold bodies in `0020`; authorized env read raises `55000 P08_ENV_WORKSPACE_UNAVAILABLE`. These match decisions 2, 3, and 6.

---

## Goal

Install one atomic isolation layer so the four named seams cannot be advertised independently:

1. **Recall** returns only a named-corpus root currently issued to the calling slice.
2. **Fold** returns only log events emitted with that slice’s immutable scope envelope whose declared corpora are still live on the slice.
3. **Env read** validates slice, paradigm env policy, and the slice’s `run` grant, then raises an explicit workspace-unavailable error because no env store exists.
4. **Tool dispatch** returns a catalog descriptor only when every concrete invocation binding is currently issued to the calling slice; it never executes the tool.

A kernel readiness latch makes every public seam raise the same closed-feature error if any one of the four registrations is missing or invalid. The numbered SQL file, latch seeds, fold-body replacements, and all seam functions land in one tree-wide transaction.

### Explicit non-goals

P08 does **not**:

- add RLS, roles, role assumption, privilege DDL, or `GRANT`/`REVOKE`;
- wrap or replace `cordis.await_event`, `cordis.emit_event`, or `cordis.step_once`;
- add a run-union grant reader;
- add corpus files, embeddings, selection rows, snapshots, revisions, or recall ranking;
- add `rlm_vars`, `env_*` storage APIs, TEMP state, or `rlm.run_id`;
- execute a plugin or external tool;
- implement a worker, host SDK, Context Builder, child inheritance, or the P15 product example;
- edit historical numbered files as the release mechanism;
- depend on untracked `sql/0004_p04_sleep_retry.sql`;
- treat isolation proposal D’s `(grant_id, predicate, resources, capabilities)` tuple as ABI;
- claim that same-user arbitrary SQL is authenticated.

---

## 中文摘要

P08 用 `sql/0020_p08_four_seam_enforcement.sql` 同时落四个门：recall、fold、env read、tool dispatch。公开门都显式接 `run_id + slice_id`，只读 P07 的 `slice_live_grants` / `slice_has_grant`，禁止 run 级并集。不用 `0008`：P08 要替换 P19 的两个 fold stub，`0008` 会被后续 `0019` 覆盖回 stub。完整树 schema 标记变成 **`p20`**（SQL 前缀，不表示骨架里的 DuckDB P20）。plpgsql 仍用 `$p08$`，跟 P07/P19 一样按计划号贴标签。

四门由 `cordis.isolation_seams` 的四条规范登记加两个认证 fold handler 共同控制；任意一条缺失，公开门全部报 `42501 P08_ISOLATION_FEATURE_CLOSED`。

P19 fold 槽签名锁成 `(text) → jsonb`，因此公开入口是 `fold_slice_messages(run_id, slice_id, paradigm)`。它先验 slice/`run` grant，再用事务内 `set_config('cordis.p08_calling_slice_id', …, is_local=true)` 适配锁定 ABI；`0020` 替换两个内置 fold body。无适配上下文的直接调用仍返回 P19 stub，现有 P19 测试不破。P05 `step_once` 和 P03 emit/await **不包装**：它们不是隔离入口；P09/P10 只能接四门 API。

Fold 需要可信的 slice 归属：`emit_step_scoped` 经 `emit_step_claimed` 写 `payload.p08_scope`（不直接 INSERT，守 P02 写垄断）。隔离 fold 忽略无 scope / 锚误 / 别的 slice / 已撤销 corpus 的行。Grant 每次 statement 现读，不做 first-fold freeze，不造 content snapshot。Recall 只返 corpus 身份+label。Env 在获准后仍报 `55000 P08_ENV_WORKSPACE_UNAVAILABLE`。Tool 只授权+descriptor，不执行。

---

## Execution index

P07 used W70–W77. P19 used W190–W195. P08 uses W80–W88.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W80 | Four-seam latch and fold-handler certification | Fresh apply creates `isolation_seams` and `isolation_fold_handlers`; four canonical seam rows plus two certified fold handlers make the feature enabled; deleting any one closes every public seam with `42501 P08_ISOLATION_FEATURE_CLOSED` | `sql/0020_p08_four_seam_enforcement.sql` | P07, P19 | Medium |
| W81 | Claim-fenced scoped-log append | `emit_step_scoped` writes canonical `p08_scope` only after validating slice, `run` grant, and every declared corpus; lost claims append nothing; no direct `INSERT` into `agent_steps` | same | W80, P02, P07 | Medium |
| W82 | Recall seam | `recall_named_corpus` returns authorized live-root metadata; unauthorized/unknown valid targets return zero rows; no run-union reader | same | W80, P07 | Small |
| W83 | Slice-aware fold and P19 ABI adapter | Public `fold_slice_messages` takes explicit `slice_id`; locked P19 fold names keep signature/volatility; with adapter they return scoped live-grant-filtered history; without adapter they still return the P19 stub | same | W80–W81, P02, P07, P19 | Large |
| W84 | Fail-closed env-read seam | CodeAct / env-disabled and missing-`run` raise `42501`; authorized RLM reaches `55000 P08_ENV_WORKSPACE_UNAVAILABLE`; no env table or GUC-backed store | same | W80, P07, P19 | Small |
| W85 | Tool-dispatch authorization | Exact concrete bindings satisfy every P06 `required_grants` kind; missing/revoked bindings and control-plane entrypoints (issue-family **and** log writers) fail closed; authorized calls return a descriptor and execute nothing | same | W80, P06, P07 | Medium |
| W86 | Version marker and SQL documentation | Full product tree ends in `0020` and reports `p20`; README documents latch, APIs, live semantics, `$p08$` tag, and the direct-event / `step_once` boundary | `sql/0020_p08_four_seam_enforcement.sql`, `sql/README.md` | W80–W85 | Small |
| W87 | Retarget current-tree tests | File-list/version/`KERNEL_FUNCTIONS` pins include `0020` / `p20`; truncated P03/P05/P07 trees keep existing markers; P19 full-tree version pins become `p20`; P05/P07/P19 **behavior** tests still pass | existing test modules | W86 | Medium |
| W88 | P08 enforcement tests | Named module proves red/green leak fixture, per-seam failures, four-way feature closure, replay, source discipline, and no regressions | `tests/test_p08_four_seam_enforcement.py` | W80–W87 | Large |

W80–W85 must land atomically in the one numbered SQL file. A branch that only implements some of those items is not an implementable P08 state.

---

## Background

### Parent skeleton

`docs/plans/2026-08-23-pg-cordis-development.md:190-198`:

- Depends on P02, P05, P07. Parallel with P09, P10.
- Contract: D5; snapshot “半套强制不得对用户暴露”.
- Decide here: failure mode of each seam; leak-test fixtures.
- Do: recall, fold, env read, and tool dispatch **simultaneously** filter by the calling slice’s live grants.
- Do not: filter only on recall and write the other project into the fold.
- Done when: leak tests red/green; if the four seams are not all in place, the feature is closed.

Do not reopen D1–D9 or snapshot §4 (`development.md:18`). No `CREATE EXTENSION`. Schema is `cordis`. Isolation proposal D (`docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md`) is evidence, not ABI. P15, not P08, owns the product two-project example (`snapshot.md:193`).

### Signed and inherited contracts

- D5 (`docs/decisions/2026-08-23-pending.md:264-267`, snapshot `:97`): enum `run` / `named_corpus:<id>` / `event:<scope>`; **slice-bound**; model only requests; ban SQL predicates and `run_id` as the isolation range. Descriptor A is not this round.
- Snapshot §5 B (`:125`): prompt assembly is a **projection** filtered by the **calling slice’s live grants**; do not union the run’s grants into every fold.
- Snapshot §5 D (`:138-140`): grant registry is kernel. Every retrieval seam must force slice binding. Half-enforcement must not ship. The same paragraph names role + RLS + pinned `search_path`; that stack **cannot land in `sql/`**: `sql/README.md:35` and `tools/apply_pg_cordis.py:26-28` reject `GRANT`/`REVOKE`/role DDL. P07 deferred RLS to **P08+** with a later exception or a superuser path **outside** `sql/` (`docs/plans/P07-grant-registry-2026-08-24.md:778-779`).
- Snapshot §3 (`:68-73`): grants/slices are **workspace**, not log, not a fold.
- Snapshot §9 (`:222`): no model-written grants, no SQL-predicate grants, no run-union retrieval.
- P07 retrieval surface is only `slice_live_grants(text,uuid)` and `slice_has_grant(text,uuid,text,text)` (`sql/0007_p07_grant_registry.sql:664-716`, `:718+`; `tests/test_p07_grant_registry.py` `test_p07_no_run_union_retrieval_function`).
- `named_corpus` is a **live-root identity** (P07 decision 4; `test_p07_corpus_is_live_root_identity`). P07 does not freeze file bytes.
- Holding `event:<scope>` authorizes emit **and** await of every name under that scope (P07 decision 7). Per-name split is descriptor A.
- Holding `run` authorizes this run’s own workspace/log **for that slice** (P07 decision 7).
- P07 issuer labels are provenance, not authentication. **P08/P10 must not dispatch issue-family functions as model tools and must not turn four seams on while those verbs are reachable as tools** (P07 decision 1; `docs/reviews/2026-08-24-p07-plan-critique.md:59`).
- Settled boundary: P08 does **not** wrap P03 emit/await (`docs/reviews/2026-08-24-p07-plan-critique.md:6`).
- P19 locks fold slots to `(p_run_id text) RETURNS jsonb`, `STABLE`; real replacements of those six names belong in a file **`> 0019`** (`docs/plans/P19-paradigm-policies-2026-08-24.md:270-303`; `tests/test_p19_paradigm_policies.py` `test_p19_higher_file_replaces_stub_and_survives_replay`).
- P19 declares env policy and creates **no** `rlm_vars`, `env_*` API, or GUC `rlm.run_id` (P19 decision 7).
- P06 `required_grants` are **kinds only** (`sql/0006_p06_plugin_catalog.sql:95-98`). Index `(locus, invocation, identity)` is named for P08/P09/P10.

### Install constraints

Current product tree (`tests/test_p00_sql_source.py:68-89`):

```text
0000, 0001, 0002, 0003, 0005, 0006, 0007, 0019 → p19
```

`0004` is untracked P04 work; P08 must not depend on it. `0008` sorts **before** `0019`, so P19 would overwrite any replacement of its fold bodies. P08 therefore uses `0020_p08_four_seam_enforcement.sql`. The schema marker becomes `p20` because the highest numeric prefix wins (`sql/README.md:39-49`).

Apply path (`tools/apply_pg_cordis.py:14-40`, `:105-135`, `:205-235`, `:315-358`):

- filename `NNNN_slug.sql`;
- preflight rejects `GRANT`/`REVOKE`/role DDL/transaction control/public tables/`CREATE EXTENSION`;
- comments and dollar-quoted bodies are blanked before the token scan;
- whole tree, one transaction, advisory lock;
- bootstrap verifies only the zero-argument text `get_schema_version()`.

PL/pgSQL bodies use `$p08$` (plan-number tag, matching `$p07$` / `$p19$`). Natural-language GRANT/END words stay inside comments or dollar-quoted bodies.

---

## Current-state analysis

| Component | Current responsibility | P08 consequence |
|---|---|---|
| `cordis.agent_steps` / `emit_step*` (`sql/0002_p02_log.sql:1-91`) | Append-only history; no slice column; unrestricted JSON payload; **one** product `INSERT` (the P02 monopoly) | Isolated writers attach a checked `p08_scope` envelope via `emit_step_scoped` → `emit_step_claimed`. Isolated fold omits unscoped/malformed/wrong-slice/revoked-corpus rows. |
| `cordis.step_once` (`sql/0005_p05_one_step_driver.sql:69+`, history fold `:340-362`) | Mock driver; folds **all** `agent_steps` for `p_run_id`; dispatches only `mock.observe`; does not read `plugin_catalog` | Remains a P05 proof path, **not** the isolated entry point. P09/P10 must call P08 gates. A named test proves the legacy path is still unfiltered. |
| P19 fold slots (`sql/0019_p19_paradigm_policies.sql:530-551`) | `(text) → jsonb STABLE` stubs returning `p19_stub` | Public P08 fold receives explicit `slice_id`, then adapts it through a transaction-local setting. Direct slot calls without that setting still return the stub so P19 tests stay green. |
| P07 `named_corpora` / `slices` / `grants` | Live-root catalog and current slice-bound grant state | Reused only through `slice_live_grants` / `slice_has_grant`. No duplicate parser, no run-union API, no default slice (P07 decision 12). |
| `cordis.plugin_catalog` | Metadata including grant **kinds**, locus, invocation, effect/retry class, entrypoint | P08 AND-checks concrete invocation bindings against live grants and returns a descriptor; execution stays in P09/P10. |
| `cordis.await_event` / `emit_event` (`sql/0003`) | Atomic wait/wake; no authorization | Unchanged. If later exposed as model tools, P10 must route them through a catalog row that declares `event` and through `authorize_tool_dispatch`. |
| P19 env columns | Declare whether a paradigm uses `run_vars` | P08 enforces policy + `run` grant then raises workspace-unavailable. Does not create `rlm_vars`. |
| P13 selection / corpus reader | Not implemented | Recall returns identity/label only. |

### Data flow

```text
trusted worker supplies (run_id, slice_id)
    → seam validates syntax (22023)
    → _require_isolation_feature()          -- latch
    → slice_live_grants / slice_has_grant   -- P07, no FOR UPDATE
    → seam-specific behavior:

recall:  live named_corpus identity → named_corpora label
         unauthorized/unknown valid target → zero rows

fold:    live run grant + certified P19 fold handler
         → set_config calling-slice (is_local)
         → scoped agent_steps + live named_corpus filter
         → ordered prompt projection

env:     paradigm_policy + live run grant
         → 55000 workspace unavailable

tool:    plugin_catalog + exact concrete bindings
         → AND of current slice grants
         → descriptor, no execution
```

Read seams use one statement snapshot. A revoke committed after that snapshot does not retroactively rewrite the current result; it affects the next call. `emit_step_scoped` authorizes and appends in the same function invocation and caller transaction; lost claims return `false` and write nothing.

### Downstream consumers

| Later plan | P08 handoff |
|---|---|
| P09 in-database worker | Must use `fold_slice_messages` and `authorize_tool_dispatch`; must not advertise `step_once` as isolated |
| P10 host seam | Must pass explicit `slice_id`, use the four public gates, and hide P07 issue-family SQL from model tools |
| P13 selection | Must join real corpus retrieval to `recall_named_corpus` in the same operation; StoredSelection stays on the same `slice_id` |
| P15 D5 example | Reuses the leak fixture and adds real selection/prompt content |
| P16 external effects | Consumes the authorized descriptor’s effect/retry/reconciliation fields |
| P17 spawn | Copies grants through trusted issuance onto an explicit child slice; no inherit verb here |

---

## Design

### Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | **Public seams take explicit `p_run_id` + `p_slice_id`.** The locked P19 fold slot sees the slice only through a transaction-local adapter `cordis.p08_calling_slice_id` set and restored by `fold_slice_messages` (`set_config(..., is_local=true)`). The setting is not caller truth, not persisted, and not session affinity. `_fold_scoped_history` revalidates run/slice ownership and live `run` grant; spoofing the setting to a foreign slice still fails. | P07 allows two slices per run and has no default slice (`test_p07_two_named_corpus_on_two_slices`; P07 decision 12). P19 locks fold to `(text)` (`sql/0019:530-551`; `to_regprocedure(fold_fn \|\| '(text)')`). | Changing P19 arity breaks ABI/tests. A persistent active-slice row races. Making callers set a GUC themselves would make spoofable session state the API. Encoding slice in `run_id` violates D5. |
| 2 | File **`sql/0020_p08_four_seam_enforcement.sql`**, marker **`p20`**, dollar tag **`$p08$`**. | P08 replaces the two P19 fold bodies; `0008` would be overwritten by `0019` (`test_p19_higher_file_replaces_stub_and_survives_replay`). Marker follows the highest prefix (`sql/README.md:39-49`). Tag follows plan number like `$p07$`/`$p19$`. | `0008`/`p08` is safe only if P08 never owns those fold names, which would leave policy `fold_fn` disconnected from isolation. Returning `p08` from file `0020` makes the version ladder lie. Using `$p20$` would be the only file whose tag is the prefix rather than the P number. |
| 3 | **New slice-aware gates.** Do **not** replace `step_once`, `await_event`, or `emit_event`. Replace only the two P19 fold bodies as the internal ABI bridge. | P05 is a mock that neither reads the catalog nor performs external work (`sql/0005:340-362`, `:538+`). P07 critique `:6` forbids wrapping P03. Replacing `step_once` would copy the whole P05 state machine and change fingerprints. | Version 2 wrap of `step_once`: couples P08 to a mock, breaks P05-prefix tests, and still would not implement real recall/env. Version 3 “do not replace P19 slots”: leaves `paradigm_policy.fold_fn` returning stubs forever and disconnects policy dispatch from the isolated fold. |
| 4 | Direct P03 event verbs stay outside the four seams. `event:<scope>` is enforced only when an event operation is dispatched through a catalog tool and `authorize_tool_dispatch`. | Skeleton names recall/fold/env/tool. Critique `:6` records “不包装 P03 emit/await.” Event targets stay opaque (`test_p07_event_scope_round_trips_p03_opacity`). | Wrapping P03 adds a fifth seam, risks its lock order, and contradicts the settled boundary. Leaving event bindings unchecked in tool dispatch would drop P07 decision 7. |
| 5 | Grants are evaluated **live at each seam statement**. No first-fold freeze, no grant snapshot table. | Snapshot `:125` says live grants. P07 decision 5 allows explicit mid-run `issue_grant`. PostgreSQL statement snapshots give an in-flight boundary. | Freeze-at-first-fold needs another state machine and muddies revoke-vs-in-flight (snapshot §10.5 still open). Caching all run grants recreates the banned union. |
| 6 | Failure modes: recall miss/unauthorized → **empty set**; fold missing `run` grant → `42501 P08_FOLD_RUN_GRANT_REQUIRED`; env disabled / missing `run` → `42501`; authorized env without store → `55000 P08_ENV_WORKSPACE_UNAVAILABLE`; unauthorized tool → `42501 P08_TOOL_GRANT_REQUIRED`; invalid args / missing slice → P07 `22023`; closed latch → `42501 P08_ISOLATION_FEATURE_CLOSED`. | Retrieval misses must not be a corpus-existence oracle. Env/tool are admissions; empty would look like success. P07 already uses `22023` for malformed IDs (`test_p07_api_errors_are_22023`). Version 3’s authorized-env `NULL` hides “store missing” as “key missing.” |
| 7 | Live **corpus-root membership** only. No content snapshot, revision, fingerprint, file list, or selection table. | P07 live-root (`test_p07_corpus_is_live_root_identity`). P13 owns selection/content pin. | Pinning bytes here invents P13 storage. Treating immutable `(kind,target)` as frozen files is the mistake P07 already closed. |
| 8 | Recall is a metadata gate. Env read is an unavailable-but-authorized stub. | No corpus reader and no `rlm_vars` exist. This gives fail-closed seams without pulling P13/P17. | Fixture content tables become accidental ABI. Returning caller-provided env values is not a read. Creating `rlm_vars` steals an undecided workspace contract. |
| 9 | Four-way closure is a **persistent canonical manifest** plus a common guard. Every public seam and `emit_step_scoped` calls `_require_isolation_feature()`. Ready only when all four exact seam rows **and** both certified fold handlers are present. Tests close the feature by deleting one canonical row (or a later probe file that deletes it). | Skeleton requires a concrete half-enforcement barrier. One file + one transaction makes install atomic; runtime manifest checks prove continued completeness. | Documentation-only promise cannot be tested. Four independent booleans allow partial enablement. Version 3 catalog-only `four_seam_ready()` does not certify the P19 fold handlers the fold gate dispatches. |
| 10 | Scoped history is written through `emit_step_scoped`; legacy/unscoped events are omitted. Canonical payload field is `p08_scope = {slice_id, named_corpora}`. Fold rechecks listed corpora against current `slice_live_grants`. | `agent_steps` has no slice column (`sql/0002`). Controlled append plus read-time live filter is the minimum enforceable provenance without ALTER of historical DDL. Version 3’s “do not write `agent_steps`” cannot produce a fold leak fixture. | Inferring slice from `run_id` violates D5. Trusting arbitrary unscoped payload leaks. A side table keyed by `seq` splits provenance from the log SoT. |
| 11 | Tool authorization requires an exact JSON **object** whose key set equals the catalog `required_grants` set. `run` → JSON `true` (P07 target `''`); `named_corpus` / `event` → one exact string each. All kinds are ANDed. Before grant checks, reject in-db entrypoints that are P07 issuer verbs **or** that persist caller-chosen payload into `agent_steps` (`emit_step`, `emit_step_claimed`, `emit_step_scoped`, `checkpoint`). The descriptor includes P06 lifecycle columns `inject`/`provide`/`intercept` plus `name`/`description` so P09/P16 do not bypass the gate to read the catalog. Exclude only raw compiler fields (`metadata`, `source_kind`). | P06 stores kinds; P07 stores concrete targets. Plan-critique P1: the same DB chokepoint that denies issue-family must deny log-writer entrypoints, or a catalog row pointing at `emit_step` forges `p08_scope`. Descriptor is P09/P16 ABI (critique Q1). | “Any live grant of this kind” lets a project-1 slice dispatch project-2. Baking IDs into catalog rows contradicts P06. A free SQL predicate reopens D5 option B. Omitting `inject`/`provide`/`intercept` forces later bypass. |
| 12 | P08 is a targeted additive layer, not a loop refactor. Same-role direct SQL remains trusted control-plane. Forgery of `p08_scope` via raw `emit_step` is the same class as raw `INSERT` into `grants`. Decision 11 blocks that path as a **model tool**; P09/P10 must still not expose `emit_step` / issue-family as host tools. | P07 already documented the same-user limitation. Source-tree preflight bans RLS in `sql/`. | Pretending `SECURITY INVOKER` authenticates a model. Adding role/RLS DDL here. Rebuilding worker/selection/env in P08. |
| 13 | `p_paradigm` on fold and env is **trusted-worker input**, not a run-owned binding. P08 does not record paradigm on `jobs` or `slices`. A later env/`run_vars` plan must not treat this argument as authenticated policy. | There is no run↔paradigm column today. Fold/env only need a policy row to resolve `fold_fn` / env flags. Critique Q2: after `run_vars` exists, lying `rlm` on a CodeAct run would bypass `env_enabled=false` unless a later plan binds paradigm at admission. | Inferring paradigm from `jobs.payload` (P05 mock-only). Adding a P08 paradigm column on `jobs` (belongs with the env workspace plan). |

No P08 implementation fork remains open after this table. Mid-flow (2026-08-24) confirmed decisions 2, 3, and 6: unwrap `step_once`, replace P19 fold bodies in `0020`, authorized env raises `55000`.

---

## Component 1 — Numbered SQL file and readiness catalogs

### File contract

**Kind:** numbered SQL source
**Path:** `sql/0020_p08_four_seam_enforcement.sql`
**Applied:** after `0019_p19_paradigm_policies.sql`
**Version marker:** `cordis.get_schema_version() → 'p20'`

File order:

1. `cordis.isolation_seams`
2. `cordis.isolation_fold_handlers`
3. `cordis.isolation_feature_status`
4. `cordis._require_isolation_feature`
5. `cordis.emit_step_scoped`
6. `cordis.recall_named_corpus`
7. `cordis._fold_scoped_history`
8. replacements for `cordis.fold_codeact_messages(text)` and `cordis.fold_rlm_messages(text)`
9. `cordis.fold_slice_messages`
10. `cordis.read_run_env`
11. `cordis.authorize_tool_dispatch`
12. canonical fold-handler seed rows
13. canonical four-seam seed rows
14. replacement `cordis.get_schema_version()` returning `p20`

The four public seams must not succeed before their canonical seed rows exist. The tree-wide transaction hides the intermediate state.

All P08 functions are `SECURITY INVOKER` and pin `search_path TO pg_catalog`, except the literal-only version function (historical no-`search_path` shape, same as `0001`–`0019`). PL/pgSQL bodies use `$p08$`. Builtins are schema-qualified.

### `cordis.isolation_seams`

Kernel installation latch. No public mutation API.

| Column | Type | Constraints |
|---|---|---|
| `seam` | `text` | `NOT NULL` |
| `gate_fn` | `regprocedure` | `NOT NULL` |
| `contract_version` | `text` | `NOT NULL` |
| `installed_at` | `timestamptz` | `NOT NULL DEFAULT clock_timestamp()` |

Named constraints:

- `isolation_seams_pkey` — primary key on `seam`;
- `isolation_seams_gate_fn_key` — unique `gate_fn`;
- `isolation_seams_name_check` — `seam IN ('recall','fold','env_read','tool_dispatch')`;
- `isolation_seams_contract_check` — `contract_version = 'p08.v1'`.

Canonical rows:

| seam | gate |
|---|---|
| `recall` | `cordis.recall_named_corpus(text,uuid,text)` |
| `fold` | `cordis.fold_slice_messages(text,uuid,text)` |
| `env_read` | `cordis.read_run_env(text,uuid,text,text)` |
| `tool_dispatch` | `cordis.authorize_tool_dispatch(text,uuid,text,jsonb)` |

Replay (not P19’s `ON CONFLICT DO NOTHING`, and not a row-wise `ON CONFLICT DO UPDATE` on `seam`): a `$p08latch$` block snapshots each canonical `installed_at`, `DELETE`s all latch rows, then `INSERT`s the four seams and two fold handlers. Only canonical rows survive. Timestamps are restored by seam / `fold_fn` key so unique `gate_fn` collisions from swapped rows cannot abort the tree-wide transaction (`test_p08_replay_repairs_swapped_gate_fns`, `test_p08_replay_preserves_existing_workspace_and_log`).

### `cordis.isolation_fold_handlers`

Certification catalog for locked P19 fold slots.

| Column | Type | Constraints |
|---|---|---|
| `fold_fn` | `regprocedure` | `NOT NULL`, primary key `isolation_fold_handlers_pkey` |
| `contract_version` | `text` | `NOT NULL`, `isolation_fold_handlers_contract_check` (`= 'p08.v1'`) |
| `installed_at` | `timestamptz` | `NOT NULL DEFAULT clock_timestamp()` |

Canonical handlers: `cordis.fold_codeact_messages(text)`, `cordis.fold_rlm_messages(text)`. Replay is the same `$p08latch$` delete-and-reinsert as `isolation_seams` and does **not** churn surviving `installed_at` values.

A third P19 policy is isolated only if its `fold_fn` resolves to one of these. `probe.alias` in P19 tests reuses the CodeAct handler and remains valid. A later custom fold is denied until a later numbered file certifies it.

### Readiness APIs

```text
cordis.isolation_feature_status()
  RETURNS TABLE(enabled boolean, missing_seams text[])

cordis._require_isolation_feature()
  RETURNS void
```

Both `STABLE` PL/pgSQL invoker.

A seam is missing if its row is absent, `contract_version <> 'p08.v1'`, `gate_fn` is not the exact expected `regprocedure`, that procedure no longer resolves, or (for `fold`) either canonical handler row is missing/mismatched.

`missing_seams` is sorted `env_read, fold, recall, tool_dispatch`. `enabled` is true only when that array is empty.

`_require_isolation_feature` raises SQLSTATE `42501`, stable fragment `P08_ISOLATION_FEATURE_CLOSED`, details containing the sorted missing names.

Every public seam and `emit_step_scoped` calls this guard after basic argument-shape validation and before any protected read or write.

---

## Component 2 — Shared validation and errors

| Group | Behavior |
|---|---|
| Basic run | NULL or `btrim(run_id)=''` → `22023` `invalid run_id`. Store/compare bytes exactly; do not trim or length-cap (P07 decision 8). |
| Slice ownership | Call `slice_live_grants(run_id, slice_id)` even when no grant is expected, so P07 owns missing-slice and run-mismatch `22023`. Do not query `cordis.grants` directly. |
| Feature readiness | `_require_isolation_feature` → `42501 P08_ISOLATION_FEATURE_CLOSED`. |
| Live grant | `slice_has_grant` for one target or `slice_live_grants` for a set. Do not cache across seam calls. No `FOR UPDATE`. |
| Corpus identity | Exact P07 grammar `^[a-z][a-z0-9_-]{0,127}$`; malformed → `22023`. Well-formed but unregistered **or** unauthorized recall target → zero rows. |
| Paradigm | `cordis.paradigm_policy(identity)`; preserve its `22023`. |
| Plugin identity | P06 identity grammar, then `plugin_catalog`. Invalid/absent → `22023`. |
| JSON shape | NULL or wrong JSON type → `22023`. JSON `null` is not an object. |

Syntactically invalid input takes precedence over the latch. Valid input against a disabled latch always receives the common closed-feature error.

| Operation | Condition | Result |
|---|---|---|
| Any protected op | Invalid run/slice/identity/JSON | `22023` |
| Any protected op | Any seam absent/invalid | `42501 P08_ISOLATION_FEATURE_CLOSED` |
| Recall | Valid target not issued (including valid unknown id) | Zero rows |
| Fold | Missing live `run` grant | `42501 P08_FOLD_RUN_GRANT_REQUIRED` |
| Fold | Policy `fold_fn` not certified | `42501 P08_FOLD_POLICY_NOT_CERTIFIED` |
| Fold | Certified slot returns NULL or non-object | `55000 P08_FOLD_INVALID_RESULT` |
| Fold | Scoped event names a corpus no longer issued | Omit that event; do not fail the fold |
| Env | `env_enabled=false` or `env_workspace='none'` | `42501 P08_ENV_DISABLED` |
| Env | `env_workspace` not `run_vars` | `55000 P08_ENV_POLICY_UNSUPPORTED` |
| Env | Lacks `run` grant | `42501 P08_ENV_RUN_GRANT_REQUIRED` |
| Env | Policy and grant pass | `55000 P08_ENV_WORKSPACE_UNAVAILABLE` |
| Tool | Missing/extra/malformed binding | `22023` |
| Tool | Required binding not live | `42501 P08_TOOL_GRANT_REQUIRED` (missing kind only, not other slices’ inventory) |
| Tool | Catalog identity or in-db `entrypoint` is a control-plane writer (issue-family or log writer) | `42501 P08_CONTROL_PLANE_TOOL_DENIED` |
| Scoped append | Missing live `run` grant | `42501 P08_SCOPED_APPEND_RUN_GRANT_REQUIRED` |
| Scoped append | A listed corpus is not live `named_corpus` on the slice | `42501 P08_SCOPED_APPEND_CORPUS_GRANT_REQUIRED` |
| Scoped append | Lost/expired/absent claim | Return `false`; append nothing |

---

## Component 3 — Scoped log and fold seam

### `cordis.emit_step_scoped`

```text
cordis.emit_step_scoped(
    p_claim_token     uuid,
    p_run_id          text,
    p_slice_id        uuid,
    p_kind            text,
    p_payload         jsonb,
    p_step_name       text DEFAULT NULL,
    p_corpus_ids      text[] DEFAULT ARRAY[]::text[],
    p_extend_seconds  integer DEFAULT 90
) RETURNS boolean
```

`VOLATILE`. Composes with P07 live queries and `emit_step_claimed`. Contains **no** direct `INSERT INTO cordis.agent_steps` (P02 monopoly, `tests/test_p02_agent_steps.py` `test_p02_source_tree_append_monopoly`).

Algorithm:

1. Validate run, payload object, positive extension, corpus array (NULL array invalid; NULL elements, malformed IDs, duplicates invalid). Normalize IDs into deterministic ascending order.
2. Reject a caller payload that already contains top-level `p08_scope` (`22023`); this function owns that field.
3. Require the latch.
4. Validate exact run/slice via P07.
5. Require live `run` grant (`42501 P08_SCOPED_APPEND_RUN_GRANT_REQUIRED`).
6. Require a live `named_corpus` grant for every normalized corpus ID (`42501 P08_SCOPED_APPEND_CORPUS_GRANT_REQUIRED`).
7. Attach:

```text
p08_scope = {
  "slice_id": <canonical uuid text>,
  "named_corpora": <normalized corpus-id array>
}
```

8. Delegate kind, step-name, lease, and claim checks to `emit_step_claimed`.
9. Return that boolean unchanged.

Existing `emit_step` / `emit_step_claimed` stay unchanged and may still write unscoped kernel/legacy events. Those events are absent from isolated folds. Raw `emit_step` **can** forge a `p08_scope` object; that is the same-user control-plane hole (decision 12). P09/P10 must not expose `emit_step` to the model.

### Scope-envelope fold rule

An `agent_steps` row is eligible iff all of:

1. `payload` is a JSON object;
2. `payload.p08_scope` is a JSON object;
3. `p08_scope.slice_id` is a JSON string exactly equal to the calling slice’s canonical UUID text;
4. `p08_scope.named_corpora` is an array of unique valid corpus-ID strings;
5. every listed corpus is present in the calling slice’s current `slice_live_grants` as `kind='named_corpus'`.

Malformed, unscoped, wrong-slice, or no-longer-authorized rows are omitted. They do not fail the fold and do not reveal their payload.

Projected history element:

```text
{
  "ordinal": <dense 1-based index among included rows>,
  "seq": <agent_steps.seq>,
  "kind": <kind>,
  "step_name": <string or null>,
  "scope": <canonical p08_scope>,
  "payload": <original payload with p08_scope removed>
}
```

Order: `seq ASC`. Empty fold: `history=[]`, `named_corpora=[]`, `as_of_seq=0`. `as_of_seq` is the greatest included `seq`.

### `cordis._fold_scoped_history(p_run_id text, p_paradigm text) RETURNS jsonb`

`STABLE`. Reads `current_setting('cordis.p08_calling_slice_id', true)`:

- missing/blank → this helper does not accept the call (the SQL replacements return the P19 stub instead of invoking it);
- malformed UUID or run/slice mismatch → `42501 P08_INVALID_CALLING_SLICE_CONTEXT`;
- revalidates latch, exact slice ownership, live `run` grant;
- authorized corpora only through `slice_live_grants`.

Returns protocol `cordis.p08.fold.v1`, handler paradigm, run, slice, live corpus IDs, history, `as_of_seq`.

### Replaced P19 fold bodies

Recreate exact identities `cordis.fold_codeact_messages(text)` and `cordis.fold_rlm_messages(text)`:

- `LANGUAGE sql`, `STABLE`, `SECURITY INVOKER`, `SET search_path TO pg_catalog`;
- when `cordis.p08_calling_slice_id` is missing/blank, return the **exact** P19 stub `{p19_stub:true, slot:fold, run_id}` so `test_p19_dispatch_calls_slot_stubs_by_name` stays green;
- when the setting exists, call `_fold_scoped_history` with the respective handler identity.

Parse and observe slots are **not** replaced.

### `cordis.fold_slice_messages`

```text
cordis.fold_slice_messages(
    p_run_id    text,
    p_slice_id  uuid,
    p_paradigm  text
) RETURNS jsonb
```

`VOLATILE` solely because it establishes/restores transaction-local call context. `p_paradigm` is trusted-worker input (decision 13), not a stored run binding.

Algorithm:

1. Validate run and paradigm identity.
2. Require latch.
3. Validate slice ownership and live `run` grant.
4. `paradigm_policy(p_paradigm)`.
5. Resolve `fold_fn(text)`; require a matching `isolation_fold_handlers` row.
6. Save prior `cordis.p08_calling_slice_id`.
7. `set_config(..., is_local=true)` to the canonical slice UUID.
8. Invoke the validated qualified fold name dynamically with `p_run_id` (no `CASE paradigm`).
9. Restore the prior setting on success and in `EXCEPTION`; a previously absent value restores to blank.
10. Require a non-null JSON object.
11. Return a normalized object whose wrapper-owned security fields override same-named slot fields: `protocol, run_id, slice_id, paradigm, system_prompt, action_surface, parser_kind, live named_corpora, as_of_seq, history`.

Nested calls on one backend restore the prior setting. Concurrent backends have independent transaction-local settings.

---

## Component 4 — Recall seam

```text
cordis.recall_named_corpus(
    p_run_id     text,
    p_slice_id   uuid,
    p_corpus_id  text
) RETURNS TABLE (
    grant_id   uuid,
    corpus_id  text,
    label      text
)
```

`STABLE`. Metadata gate, not content retrieval.

1. Validate run and corpus grammar.
2. Require latch.
3. `slice_live_grants` for exact run/slice and live rows.
4. Keep the row whose `kind='named_corpus'` and `target` equals `p_corpus_id`.
5. Join to `named_corpora` for `label`.
6. Zero or one row.

A valid unregistered id and a registered-but-unauthorized id both return zero rows.

P13 must call this in the same retrieval operation that reads real bytes. It must not treat an earlier success as a reusable token. P08 creates no content table, ranking, embedding, selection object, or snapshot pointer.

---

## Component 5 — Env-read seam

```text
cordis.read_run_env(
    p_run_id     text,
    p_slice_id   uuid,
    p_paradigm   text,
    p_key        text
) RETURNS jsonb
```

`STABLE`. No successful-return path in P08.

Key: NULL/blank invalid; max 256 bytes; control characters invalid; otherwise preserve bytes.

1. Validate run, paradigm identity, key.
2. Require latch.
3. Validate run/slice.
4. `paradigm_policy`.
5. `env_enabled=false` or `env_workspace='none'` → `42501 P08_ENV_DISABLED`.
6. `env_workspace` not `run_vars` → `55000 P08_ENV_POLICY_UNSUPPORTED`.
7. Missing `run` grant → `42501 P08_ENV_RUN_GRANT_REQUIRED`.
8. Raise `55000 P08_ENV_WORKSPACE_UNAVAILABLE`.

Does not read `jobs.payload` as env. Does not use a GUC as env storage. `p_paradigm` is trusted-worker input (decision 13), not a stored run binding. A later plan may replace this function with the same signature and return `{found,key,value}` after defining the workspace. CodeAct cannot read env merely because a `run` grant exists; its P19 seed disables the surface.

---

## Component 6 — Tool-dispatch seam

```text
cordis.authorize_tool_dispatch(
    p_run_id     text,
    p_slice_id   uuid,
    p_identity   text,
    p_bindings   jsonb
) RETURNS jsonb
```

`STABLE`. Authorize and return a descriptor; never call the entrypoint.

`p_bindings` is a JSON **object** whose key set must equal the catalog row’s `required_grants` set.

| Catalog kind | Concrete value |
|---|---|
| `run` | JSON boolean `true`; checked as P07 target `''` |
| `named_corpus` | JSON string, one P07 corpus id |
| `event` | JSON string, one nonblank opaque scope, byte-for-byte |

Examples: no grants → `{}`; run only → `{"run": true}`; named corpus → `{"named_corpus": "project-1"}`; run+event → `{"run": true, "event": "Acme/scope:v1"}`.

Missing keys, extra keys, JSON nulls, `run: false`, malformed corpus ids, blank event scopes → `22023`.

Algorithm:

1. Validate run, plugin identity, bindings-object shape.
2. Require latch.
3. `slice_live_grants` for run/slice ownership.
4. Exactly one `plugin_catalog` row by normalized identity; missing → `22023 unknown plugin`.
5. **Before** grant checks, reject control-plane targets. Rule: an in-db `entrypoint` (or an identity equal to that function name) must not resolve to a function that persists caller-chosen payload into `agent_steps`, nor to a P07 issuer verb. Exact denylist:
   - `register_named_corpus(text,text,text)`
   - `create_slice(text,text,text)`
   - `issue_grant(text,uuid,text,text,text)`
   - `approve_grant(uuid,text)`
   - `deny_grant(uuid,text)`
   - `revoke_grant(uuid,text)`
   - `emit_step(text,text,jsonb,text)` (`sql/0002_p02_log.sql:40`)
   - `emit_step_claimed(uuid,text,text,jsonb,text,integer)` (`:72`)
   - `emit_step_scoped(uuid,text,uuid,text,jsonb,text,text[],integer)` (this file)
   - `checkpoint(uuid,jsonb,integer)` (`sql/0002_p02_log.sql:147` — walks caller JSON and `PERFORM emit_step`)
   Do **not** denylist `llm_checkpoint(text,text)`: it is `STABLE` and only reads (`sql/0002_p02_log.sql:335`).
6. Require exact binding key set.
7. For each required kind, `slice_has_grant` with the concrete target.
8. Any false → `42501 P08_TOOL_GRANT_REQUIRED` (missing kind only).
9. Return descriptor: identity, `name`, `description`, version, locus, invocation, required kinds, normalized bindings, effect/retry/reconciliation, entrypoint text or JSON null, session_scope, capability, config, **and** P06 lifecycle columns `inject`/`provide`/`intercept` (`sql/0006_p06_plugin_catalog.sql:16-18`). Exclude only raw compiler fields `metadata` and `source_kind`.

A plugin requiring no grants is authorized only with `{}`. All required kinds are AND.

Event binding authorizes the opaque scope for both emit and await (P07 decision 7). It does not parse names or inspect `run_events`.

The in-db entrypoint/identity check does not authenticate a host tool with `entrypoint IS NULL`; P10 remains responsible for host impersonation. Same-user limitation as P07.

Returned descriptor is valid for the current dispatch decision only. P09/P10 must not cache it across claims.

---

## Component 7 — Version, README, catalog surface

Last function in `0020` recreates zero-argument `get_schema_version` with unchanged SQL/immutable/invoker shape and literal `p20`.

README ladder:

```text
tree including 0019_p19_paradigm_policies.sql → p19
tree including 0020_p08_four_seam_enforcement.sql → p20  (current product tree)
```

README must state: plan number P08 ≠ marker `p20` because `0020` must run after P19; `p20` is not DuckDB P20; `$p08$` tag; four public gates; latch tables and `ON CONFLICT DO UPDATE` replay; live statement-snapshot grants; `p08_scope`; P03/`step_once` remain unwrapped; live-root membership not content freeze; pre-P08 unscoped history is omitted from isolated fold; `p_paradigm` on fold/env is trusted-worker input, not a stored run binding.

### Exact function identities added by P08

```text
cordis._fold_scoped_history(text,text)
cordis._require_isolation_feature()
cordis.authorize_tool_dispatch(text,uuid,text,jsonb)
cordis.emit_step_scoped(uuid,text,uuid,text,jsonb,text,text[],integer)
cordis.fold_slice_messages(text,uuid,text)
cordis.isolation_feature_status()
cordis.read_run_env(text,uuid,text,text)
cordis.recall_named_corpus(text,uuid,text)
```

The two existing fold identities remain single, non-overloaded functions.

| Function | Volatility | Language |
|---|---|---|
| `_fold_scoped_history` | STABLE | plpgsql |
| `_require_isolation_feature` | STABLE | plpgsql |
| `authorize_tool_dispatch` | STABLE | plpgsql |
| `emit_step_scoped` | VOLATILE | plpgsql |
| `fold_codeact_messages` replacement | STABLE | sql |
| `fold_rlm_messages` replacement | STABLE | sql |
| `fold_slice_messages` | VOLATILE | plpgsql |
| `isolation_feature_status` | STABLE | plpgsql |
| `read_run_env` | STABLE | plpgsql |
| `recall_named_corpus` | STABLE | plpgsql |
| `get_schema_version` | IMMUTABLE | sql |

All `SECURITY INVOKER`.

### Exact `KERNEL_FUNCTIONS` after P08

`tests/test_p00_sql_source.py` continues to compare `nspname || '.' || proname ORDER BY 1` to this tuple **exactly**:

```text
cordis._fold_scoped_history
cordis._require_isolation_feature
cordis._validate_paradigm_policy
cordis._validate_plugin_definition
cordis.apply_observation_policy
cordis.approve_grant
cordis.authorize_tool_dispatch
cordis.await_event
cordis.checkpoint
cordis.claim_job
cordis.complete_claim
cordis.create_slice
cordis.deny_grant
cordis.emit_event
cordis.emit_step
cordis.emit_step_claimed
cordis.emit_step_scoped
cordis.fail_claim
cordis.fold_codeact_messages
cordis.fold_rlm_messages
cordis.fold_slice_messages
cordis.get_schema_version
cordis.invoke_llm
cordis.isolation_feature_status
cordis.issue_grant
cordis.llm_checkpoint
cordis.next_step_name
cordis.observe_codeact
cordis.observe_rlm
cordis.paradigm_policy
cordis.parse_codeact_decision
cordis.parse_rlm_decision
cordis.read_run_env
cordis.recall_named_corpus
cordis.refresh_plugins
cordis.register_host_plugin
cordis.register_named_corpus
cordis.register_paradigm_policy
cordis.release_stale
cordis.renew_claim
cordis.request_grant
cordis.revoke_grant
cordis.run_state
cordis.slice_has_grant
cordis.slice_live_grants
cordis.step_once
cordis.unregister_host_plugin
cordis.unregister_paradigm_policy
cordis.yield_claim
```

No overloads. No `run_live_grants`. `test_p00` also gains a count pin for `isolation_seams` and `isolation_fold_handlers` (two new `cordis` tables).

---

## File-by-file impact

| File | Change | Why | Ordering |
|---|---|---|---|
| `docs/plans/P08-four-seam-enforcement-2026-08-24.md` | This deep plan | AGENTS plan-before-code | First |
| `sql/0020_p08_four_seam_enforcement.sql` | **Create.** Latch tables, readiness APIs, scoped append, four seams, two P19 fold-body replacements, seeds, `p20` marker | Atomic four-seam surface after P19 | One complete file |
| `sql/README.md` | Add `0020`/`p20`, gates, latch, live semantics, `$p08$`, non-integration with P03/P05 | Install contract | After signatures settle |
| `tests/test_p08_four_seam_enforcement.py` | **Create.** Protocol, failure, latch-deletion, replay, source-discipline | Acceptance proof | Shared harness only |
| `tests/test_p00_sql_source.py` | Rename current-tree test to `p20`; file list adds `0020`; version `p20`; `KERNEL_FUNCTIONS` exact tuple; table count for the two latch tables; probe list inserts `0020` before `{probe_name}` | P00 owns the catalog pin | Atomic with SQL |
| `tests/test_p01_claim.py` | Full-tree `'p19'` → `'p20'` only | Last file wins | After SQL |
| `tests/test_p02_agent_steps.py` | Full-tree `'p19'` → `'p20'`; P02-only tree stays `'p02'`; monopoly scan still finds exactly one `INSERT INTO cordis.agent_steps` | Scoped append delegates to `emit_step_claimed` | After SQL |
| `tests/test_p05_one_step_driver.py` | **No change** (P05-only tree stays `'p05'`; no full-tree pin exists). Regression only | `step_once` is not replaced | Regression only |
| `tests/test_p06_plugin_catalog.py` | Full-tree `'p19'` → `'p20'` | Last file wins | After SQL |
| `tests/test_p19_paradigm_policies.py` | Three full-tree version assertions `'p19'` → `'p20'` (`tests/test_p19_paradigm_policies.py:112`, `:451`, `:669`). Do **not** hard-code the sentinel prefix; `next_sql_prefix` becomes `0021` automatically. Stub-by-name and signature tests still pass (no adapter ⇒ stub) | P08 sorts after P19 but blank-context fold still stubs | Atomic with P08 tests |
| `tests/test_p07_grant_registry.py` | **No change** (P07-only tree stays `'p07'`; all 18 tests unchanged) | P08 consumes the stable P07 API | Regression only |
| `tests/test_p03_wait_event.py` | **No change** (P03-only tree stays `'p03'`) | Event verbs unwrapped | Regression only |
| `tools/apply_pg_cordis.py`, `tests/conftest.py`, `sql/0000`–`0019` | **No change** | Append-only; existing harness | — |
| `sql/0004_p04_sleep_retry.sql`, `.p19-backup/` | **No change and no dependency** | Out of P08 ship set | Must not enter the P08 commit |

---

## Implementation order

1. Plan critique is `docs/reviews/2026-08-24-p08-plan-critique.md`. P0/P1/P2 from that note are folded into this file (two-slice `run` grant, log-writer denylist, latch replay, named append fragments, file-by-file pins).
2. Create `sql/0020_p08_four_seam_enforcement.sql` atomically (W80–W85). Do not land a partial seam set.
3. Disposable-DB smoke: fresh apply and in-place replay; `isolation_feature_status().enabled` is true; blank-context `fold_codeact_messages('r')` is still the P19 stub; adapter path returns protocol `cordis.p08.fold.v1`.
4. Update `sql/README.md`.
5. Retarget whole-tree tests (W87).
6. Add `tests/test_p08_four_seam_enforcement.py` (W88).
7. Run the commands in Verification. Fix only P08 implementation or version-pin fallout; do not weaken P03/P05/P07/P19 behavior.
8. Full suite on a clean tree that does not apply untracked P04 as part of P08.
9. Implementation Oracle gate in `AGENTS.md`; then commit and push only the P08 ship set.

Steps 2, 5, and 6 must land together in the final commit because the source-tree catalog test fails between them.

---

## Verification

### Exact test module and names

Create `tests/test_p08_four_seam_enforcement.py` using only `run_apply`, `psql`, `psql_session`, `next_sql_prefix` from `tests.conftest`. Do not `import tools`.

| Test | Required proof |
|---|---|
| `test_p08_fresh_apply_catalog_version_and_ready` | File list ends `0019,0020`; version `p20`; two latch tables; exact new identities; volatilities/languages/invoker/`search_path` as Component 7; `enabled=true`; no overloads; no `pg_cordis` extension |
| `test_p08_two_named_corpora_four_seam_leak_fixture` | The protocol below, in **one** named test |
| `test_p08_legacy_step_once_still_unfiltered` | Same two-slice scoped history plus an unscoped `emit_step` marker; `step_once` request history still contains both slices’ sentinels; `fold_slice_messages` for `s1` does not. Proves the mock driver is not the isolated path |
| `test_p08_fold_ignores_unscoped_malformed_and_cross_slice_rows` | Unscoped, malformed `p08_scope`, wrong `slice_id`, and revoked-corpus rows omitted without abort; own live rows remain `seq` ordered |
| `test_p08_live_issue_and_revoke_affect_next_call_without_freeze` | Explicit issue makes a scoped row visible on the next fold/recall; revoke removes it on the next call; log rows remain; no snapshot table |
| `test_p08_recall_failure_contract` | Unauthorized/unknown valid corpus → zero rows; malformed corpus and missing/mismatched slice → `22023` |
| `test_p08_fold_failure_contract` | Slice with live `run` and no scoped rows → empty history JSON; missing `run` grant → `42501 P08_FOLD_RUN_GRANT_REQUIRED`; missing/mismatched slice → `22023`; uncertified custom `fold_fn` → `42501 P08_FOLD_POLICY_NOT_CERTIFIED` |
| `test_p08_env_read_failure_contract` | Blank key → `22023`; CodeAct on a slice that has `run` → `42501 P08_ENV_DISABLED`; RLM on a **third** slice that has no `run` grant → `42501 P08_ENV_RUN_GRANT_REQUIRED`; RLM with `run` → `55000 P08_ENV_WORKSPACE_UNAVAILABLE` |
| `test_p08_tool_dispatch_failure_contract` | Invalid/unknown identity / invalid JSON → `22023`; missing exact grant / missing required kind / extra kind → `42501`; `{}` authorizes a no-grant plugin |
| `test_p08_tool_dispatch_checks_exact_target_not_only_kind` | Slice holding `project-1` cannot authorize `project-2` merely because both are `named_corpus` |
| `test_p08_control_plane_functions_are_not_model_tools` | P07 issue/create/approve identities and P02 log writers (`emit_step`, `emit_step_claimed`, `checkpoint`) are absent from `plugin_catalog`; `authorize_tool_dispatch` on those names is `22023 unknown plugin`; a COMMENT-sourced colliding `entrypoint` for each denylisted signature raises `42501 P08_CONTROL_PLANE_TOOL_DENIED`. `llm_checkpoint` is **not** denylisted |
| `test_p08_p19_blank_context_still_stubs` | `SELECT cordis.fold_codeact_messages('run-1')` still has `p19_stub=true` on the product tree |
| `test_p08_feature_closed_when_any_seam_is_missing` | Parameterized over the four `isolation_seams.seam` values: copy tree, later probe `DELETE`s that canonical row (does not replace `get_schema_version`), apply, `enabled=false`, remaining public seams raise `42501 P08_ISOLATION_FEATURE_CLOSED` |
| `test_p08_does_not_replace_legacy_driver_or_event_verbs` | `step_once` and P03 event identities/signatures unchanged; `0020` source has no `CREATE OR REPLACE` of those names |
| `test_p08_has_no_snapshot_env_table_or_run_union_helper` | No corpus revision table, no `rlm_vars`, no `run_live_grants`/`run_grants` |
| `test_p08_source_tree_append_monopoly_holds` | Product SQL still contains exactly one `INSERT INTO cordis.agent_steps`, inside `emit_step` |
| `test_p08_replay_preserves_existing_workspace_and_log` | In-place replay leaves corpora, slices, grant statuses/timestamps, catalog rows, scoped log rows, runtime policy upserts, **and** latch-table `installed_at`; `enabled` remains true; version `p20` |
| `test_p08_sql_tree_forbidden_words_and_dollar_tag` | `0020` uses `$p08$`; sanitized source has no forbidden token; no public/extension/role/transaction-control statement |
| `test_p08_event_scope_binding_is_opaque` | Tool binding `{"event":"Acme/scope:v1"}` round-trips through `slice_has_grant` / authorize; no parsing of extra colons |

### Mandatory two-slice protocol

`test_p08_two_named_corpora_four_seam_leak_fixture` must run this sequence in one test, reusing P07 verbs (not a run-union helper):

1. `register_named_corpus('project-1', …)` and `register_named_corpus('project-2', …)`.
2. `s1 = create_slice('run-d5', 'fn-1', 'host')`; `s2 = create_slice('run-d5', 'fn-2-3', 'host')`.
3. Issue `named_corpus/project-1` to `s1`; `named_corpus/project-2` to `s2`; `run/''` to **both** `s1` and `s2`. The leak fixture proves corpus isolation, not the presence/absence of `run`. Missing-`run` fold/env failures live in `test_p08_fold_failure_contract` and `test_p08_env_read_failure_contract` on a **third** slice that is never issued `run`.
4. Open a live claim on `run-d5`. Via `emit_step_scoped`:
   - `s1` writes a `tool` row with sentinel `project-1-secret` and `p_corpus_ids={'project-1'}`;
   - `s2` writes `project-2-secret` / `project-2`.
5. Register host plugin `host.p08.lookup` with `invocation='host_tool'`, `required_grants=['named_corpus']`, `read_only` / `replayable` / `none`.

Assertions for `s1`:

- `recall_named_corpus(run,s1,'project-1')` returns project-1; `'project-2'` returns zero rows.
- `fold_slice_messages(run,s1,'codeact')` contains `project-1-secret` and never `project-2-secret`; `live named_corpora` is only `project-1`.
- `read_run_env(run,s1,'rlm','question')` raises `55000 P08_ENV_WORKSPACE_UNAVAILABLE`.
- `read_run_env(run,s1,'codeact','question')` raises `42501 P08_ENV_DISABLED`.
- `authorize_tool_dispatch(run,s1,'host.p08.lookup','{"named_corpus":"project-1"}')` returns a descriptor; the same call with `project-2` raises `42501 P08_TOOL_GRANT_REQUIRED`.

Mirror recall/fold/tool **and** RLM env (`55000 P08_ENV_WORKSPACE_UNAVAILABLE`) for `s2`.

Also assert that `SELECT` joining `grants` to `slices` at run scope can see both corpora, while none of the four P08 seams returns their union. `test_p08_legacy_step_once_still_unfiltered` reuses this same two-slice scoped history (both slices have `run`).

### Feature-closed proof

`test_p08_feature_closed_when_any_seam_is_missing` is parameterized over `recall`, `fold`, `env_read`, `tool_dispatch`. Each case copies the sql tree, appends `{next_sql_prefix}_drop_seam.sql` that `DELETE`s that canonical `isolation_seams` row and does **not** replace `get_schema_version`. After apply: marker still `p20`; `enabled=false`; `missing_seams` contains exactly that name; `recall_named_corpus` / `fold_slice_messages` / `read_run_env` / `authorize_tool_dispatch` / `emit_step_scoped` all raise `42501 P08_ISOLATION_FEATURE_CLOSED` (valid syntax, so the latch wins).

### Red/green discipline

Against a tree ending at `0019` (copy without `0020`):

- every new gate is PostgreSQL `42883` undefined-function;
- `step_once` still folds all-run history (legacy leak);
- no latch tables.

After `0020` lands, the leak fixture is green and the drop-one-seam probe stays red/closed. No temporary half-enforced production path is added.

### No-regression

All existing `test_p07_*` names remain green, including `test_p07_two_named_corpus_on_two_slices`, `test_p07_issue_rejects_asserted_model_kind`, `test_p07_event_and_run_kinds`, `test_p07_event_scope_round_trips_p03_opacity`, `test_p07_revoke_drops_live_not_log`, `test_p07_corpus_is_live_root_identity`, `test_p07_api_errors_are_22023`, `test_p07_no_run_union_retrieval_function`, `test_p07_replay_preserves_grants`, `test_p07_sql_tree_grant_word_only_in_quotes_or_comments`.

P19 must keep `test_p19_dispatch_calls_slot_stubs_by_name`, `test_p19_higher_file_replaces_stub_and_survives_replay` (sentinel prefix `0021`, full-tree version `p20`), `test_p19_signatures_and_volatility`.

P03 event tests unchanged. P05 mock protocol tests unchanged.

### Commands

```bash
uv run pytest tests/test_p08_four_seam_enforcement.py -q

uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py \
  tests/test_p02_agent_steps.py tests/test_p03_wait_event.py \
  tests/test_p05_one_step_driver.py tests/test_p06_plugin_catalog.py \
  tests/test_p07_grant_registry.py tests/test_p19_paradigm_policies.py \
  tests/test_p08_four_seam_enforcement.py -q

PGCORDIS_PGDATA="$CORDIS_ROOT/.pgdata" uv run pytest -q
```

P08 changed the numbered SQL tree, so the earlier protocol tests in the second command are required (`AGENTS.md` 送审之前 §2).

---

## Risks

- **Same-user SQL.** A client that can run arbitrary SQL can `issue_grant`, `emit_step` a forged `p08_scope`, or `DELETE` latch rows. P08 protects the official worker/model seam, not a hostile superuser. Mitigation: P09/P10 hide issue-family and `emit_step` from the model; RLS remains P08+ outside `sql/`.
- **Legacy `step_once` still unfiltered.** Advertising it as isolated would ship half-enforcement. Mitigation: named test `test_p08_legacy_step_once_still_unfiltered`; P09/P10 must use the four gates.
- **P03 remains unauthorized.** Direct emit/await still work without `event:<scope>` until a catalog tool is routed through P08. Mitigation: P10 must not expose those verbs as model tools.
- **Live root.** Granting `named_corpus:<id>` does not freeze files. P13 must pin content if it needs a snapshot.
- **Unscoped resume.** Isolated fold omits pre-P08 history. Old mock runs cannot be “resumed isolated” without rewriting log rows (forbidden). Mitigation: document; do not auto-guess slice.
- **Dynamic fold dispatch.** `fold_slice_messages` invokes a validated `regprocedure`. Mitigation: certification catalog; uncertified names raise `42501`; restore `set_config` in `EXCEPTION`.
- **Marker `p20` vs plan P08 vs skeleton P20.** Mitigation: README sentence that `p20` is the SQL prefix, not DuckDB P20.
- **In-place rollback.** Removing `0020` from the source tree and replaying in place does not `DROP` functions already installed. Rollback is `--reset` or a later reversal file.

---

## Open questions

None remaining for P08 implementation. Mid-flow 2026-08-24 and plan-critique P0/P1/P2/Q1/Q2 are folded. Explicitly deferred:

- role/RLS/search_path principals (P08+ outside `sql/`);
- wrapping P03 event verbs (settled no; a later plan would have to reopen P07 critique `:6`);
- replacing `step_once` (settled no; mid-flow 2026-08-24);
- corpus content snapshot / selection (P13);
- worker integration and model-facing exposure (P09/P10);
- product two-project example (P15);
- D2 call/result recovery (P16);
- child grant inherit (P17);
- real `rlm_vars` workspace (later dedicated plan);
- **run-level paradigm binding** so a later env store cannot be bypassed by lying `p_paradigm` (decision 13; env/`run_vars` plan);
- emit-vs-await per-name capabilities (descriptor A).

---

## References

- `docs/plans/2026-08-23-pg-cordis-development.md:190-198` — P08 skeleton
- `docs/decisions/2026-08-23-pending.md:264-267` — D5
- `docs/analysis/2026-08-23-i-architecture-snapshot.md:68-73`, `:97`, `:125`, `:138-140`, `:193`, `:222`, `:236`
- `docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md` — evidence, not ABI
- `docs/plans/P07-grant-registry-2026-08-24.md` — decisions 1/4/5/7/10/12, Component 7 live query
- `docs/reviews/2026-08-24-p07-plan-critique.md:6`, `:59`
- `docs/reviews/2026-08-24-p08-plan-critique.md` — P0 two-slice `run` grant; P1 log-writer denylist; P2 latch/replay/pins
- `docs/plans/P19-paradigm-policies-2026-08-24.md` decisions 5 and 7, body ownership `:301-303`
- `docs/plans/P03-wait-event-2026-08-24.md:32`, `:345`, `:858`
- `docs/plans/P05-one-step-driver-2026-08-24.md` — unfiltered request fold
- `docs/plans/P06-plugin-catalog-2026-08-23.md:70-76` — P08 reads identity + grants at dispatch
- `sql/0002_p02_log.sql` — append monopoly
- `sql/0005_p05_one_step_driver.sql:340-362` — current history fold
- `sql/0006_p06_plugin_catalog.sql:95-98` — kinds-only `required_grants`
- `sql/0007_p07_grant_registry.sql:664-716` — `slice_live_grants`
- `sql/0019_p19_paradigm_policies.sql:530-551` — fold stubs
- `sql/README.md` — append-only tree, GRANT ban, version ladder
- `tools/apply_pg_cordis.py:14-40`, `:105-135`, `:205-235`, `:315-358`
- `tests/test_p00_sql_source.py:23-89` — `KERNEL_FUNCTIONS` and current tree pin
- `tests/test_p07_grant_registry.py:287`, `:391`, `:615`, `:645`, `:678`, `:728`, `:967`, `:1034`, `:1050`, `:1086`
- `tests/test_p19_paradigm_policies.py` — stub-by-name and `> 0019` ownership
- `AGENTS.md` — plan-before-code, append-only source, shared harness, implementation Oracle gate
