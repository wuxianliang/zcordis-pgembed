# P19 — CodeAct / RLM 范式政策包: Plan

Date: 2026-08-24  
Status: **ready to implement**
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P19  
Depends on: P06, implemented (`sql/0006_p06_plugin_catalog.sql`)  
Parallel with: P07, P05 (neither required)  
Contract: CodeAct 主体; RLM 取 prime-agent 形态; 核是 loop 基座，范式是政策包  
Primary deliverable: `sql/0019_p19_paradigm_policies.sql`  
Critique: `docs/reviews/2026-08-24-p19-plan-critique.md`
Oracle round 1: `prompt-exports/oracle-review-2026-08-24-214138-untitled-chat-136564-8da5.md` (not pass; P1 folded)
Oracle round 2: `prompt-exports/oracle-review-2026-08-24-215433-untitled-chat-136564-db6e.md`
Oracle round 3: `prompt-exports/oracle-review-2026-08-24-220807-untitled-chat-136564-cd14.md`
Oracle round 4: `prompt-exports/oracle-review-2026-08-24-221506-untitled-chat-136564-cb70.md`
Oracle round 5: `prompt-exports/oracle-review-2026-08-24-221702-untitled-chat-136564-335f.md` (**pass**; no remaining P0/P1)

**Landing state:** product tree is `0000` + `0001` + `0002` + `0003` + `0006`; marker `'p06'` (`sql/README.md:39-46`; `tests/test_p00_sql_source.py:54-65`). Gaps are allowed. P04/P05/P07 are not in the tree and are not dependencies. Filename is `sql/0019_p19_paradigm_policies.sql` so it cannot collide with `0004`/`0005`/`0007` if those land first. Combined-tree version assertions that currently pin `'p06'` become `'p19'`. P02-only temp trees stay `'p02'`; P03-only temp trees stay `'p03'`.

## Goal

Register CodeAct and RLM as two queryable policy rows on the shared loop substrate, without a second loop engine, without freezing `CASE identity` in the kernel, and without implementing the one-step driver.

P19 creates:

- durable table `cordis.paradigm_policies`;
- `cordis._validate_paradigm_policy(jsonb)`;
- `cordis.register_paradigm_policy(jsonb)` / `cordis.unregister_paradigm_policy(text)`;
- `cordis.paradigm_policy(text)` — the only lookup the future loop kernel may use;
- six stub functions for the three dispatch slots × two seeds, with locked SQL signatures;
- two seed rows, identities `codeact` and `rlm`;
- schema marker `cordis.get_schema_version() → 'p19'`.

**v0 proof:** a SQL client looks up a policy by identity and calls `fold_fn` / `parse_fn` / `observe_fn` from that row with one shared signature per slot (no `CASE identity`). A third identity can be registered with a different clip/prompt without editing kernel SQL. No host SDK, no LLM, no `rlm_vars`, no spawn execution, no real fold/parse bodies (stubs only).

P19 does **not** implement grant issuance (P07), four-seam enforcement (P08), the one-step driver (P05), in-database or host workers (P09/P10), async child execution (P17), wait/sleep/retry (P03/P04 already or next), or workspace `rlm_vars`.

## 中文摘要

P19 在 `sql/` 增加 `0019_p19_paradigm_policies.sql`：表 `cordis.paradigm_policies` 加两行种子（`codeact` / `rlm`）。CodeAct = 结构化工具一步；RLM = 跑级 env 变量。**显式**子 run 一律 `always_enqueue`（D9；两行相同；普通工具仍不是 spawn）。查找走 `cordis.paradigm_policy(identity)`，再按行里的函数名调用三槽 stub（共同签名），核不按 identity 做 if-else。政策不进 `plugin_catalog`。种子 apply 用 `ON CONFLICT DO NOTHING`，不覆盖运行时 upsert。不改 loader，不建 `rlm_vars`，不 ALTER `jobs`。全树标记变 `p19`。

## Execution index

P02 used `W19`–`W26`; P03 used `W27`–`W33`; P06 used `W60`–`W66`. P19 uses `W190`–`W195` so it cannot collide with P04/P05/P07 work-item numbers.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W190 | Policy table DDL | Fresh apply of the product tree plus `0019` creates `cordis.paradigm_policies` with the columns, named CHECKs, and PK below; `plugin_catalog` CHECKs unchanged | `sql/0019_p19_paradigm_policies.sql` | P06 | Medium |
| W191 | Validator | `_validate_paradigm_policy(jsonb)` accepts a valid envelope, rejects bad keys/enums/env/sync, SQLSTATE `22023`; `metadata` is the original envelope | `sql/0019_p19_paradigm_policies.sql` | W190 | Medium |
| W192 | Register / unregister / lookup | `register_paradigm_policy` upserts; `unregister_paradigm_policy` deletes; `paradigm_policy(text)` returns the row or raises | `sql/0019_p19_paradigm_policies.sql` | W191 | Medium |
| W193 | Stubs + wrapper + two seeds + version marker | Six slot stubs + `apply_observation_policy`; seeds via `INSERT … SELECT validate ON CONFLICT DO NOTHING`; `get_schema_version() → 'p19'` | `sql/0019_p19_paradigm_policies.sql` | W192 | Medium |
| W194 | Retarget current-tree tests | Product file list includes `0019`; `KERNEL_FUNCTIONS` gains the four verbs + six stubs + `apply_observation_policy`; full-tree `'p06'` → `'p19'`; P02-only stays `'p02'`; P03-only stays `'p03'`; **no** loader edit | `tests/test_p00_sql_source.py`, `tests/test_p01_claim.py`, `tests/test_p02_agent_steps.py`, `tests/test_p06_plugin_catalog.py`, `sql/README.md` | W190–W193 | Medium |
| W195 | P19 policy tests | Named tests in `tests/test_p19_paradigm_policies.py` all pass via `uv run pytest`; no `import` of `tools/` | `tests/test_p19_paradigm_policies.py` | W190–W194 | Medium |

## Background

Curated from the skeleton, snapshot, analysis C, and P06. Spot-checked against current code.

### Parent skeleton

`docs/plans/2026-08-23-pg-cordis-development.md:202-212`:

- **Depends on P06. Parallel with P07, P05.**
- **Contract:** CodeAct 主体; RLM 取 prime-agent 形态; 核是 loop 基座。
- **Decide here:** fields in the policy row (prompt, parser, observation clip, env policy).
- **Do:** two registrations. CodeAct = structured tools in one step. RLM = env variables + async children (child execution in P17).
- **Do not:** two loop engines; synchronous `rlm_loop(child)`.
- **Done when:** the one-step driver can select policy by `paradigm` without an if-else frozen in the kernel.
- Numbering after P08 is for writing order; **do not wait for P08** to register paradigms.

Do not reopen D1–D9 or snapshot §4 (`development.md:18`). No `CREATE EXTENSION` in P00–P19 (`development.md:21`). SQL namespace is schema `cordis` (`development.md:20`).

Downstream (consume these rows; do not implement here):

| Later item | What it reads |
|---|---|
| P05 (`development.md:152-160`) | `paradigm_policy(identity)` to pick prompt/parser/clip/env; implements fold/parse bodies named in the row |
| P09 / P10 | same lookup; loop kernel stays one function |
| P13 | fold is a projection; P19 only stores the fold function **name** |
| P17 | RLM `spawn_mode = always_enqueue`; P19 does not enqueue |
| P04 | retry **state machine** stays kernel; P19 does **not** store retry curves |

### Signed contracts and snapshot (do not reopen)

- Snapshot §2 (`docs/analysis/2026-08-23-i-architecture-snapshot.md:37`): CodeAct is the v0 body (one step = one LLM + its tools). RLM is prime-agent: durable control env + `rlm()` returns only an admission handle; children are async.
- Snapshot §5 (`snapshot.md:117`): kernel = loop substrate (claim, fold **consumption**, LLM transport, budget, spawn plumbing, tool rendering). Paradigm = policy pack (prompt, parser, action routing, env policy, observation clip). Two policies, not two engines.
- Snapshot §5 C (`snapshot.md:131-134`): v0 CodeAct action surface = structured tools (CE search/read/`apply_edits`), not in-DB free programs (T4). RLM REPL is tables (`rlm_vars` etc.), not session `pg_temp`. Child runs inherit **named grants + question**, not the parent env.
- D9 (`docs/decisions/2026-08-23-pending.md:32`, `:51`): every child run is enqueued; in-step tools are not spawn. Synchronous `rlm_loop(child)` is in snapshot §9 (`snapshot.md:226`).
- D1 (`pending.md:18`, `:90`): retire `pg_temp` DA. P19 must not seed a `data_analysis` paradigm and must not create TEMP-backed env.
- D6 (`snapshot.md:98`): v0 budget is kernel step/depth/fanout caps at admission. Not per-paradigm token pools. P19 does not store D6 numbers.
- D8 / P06: plugin catalog is identity/locus/invocation/grants/effect/retry. That vocabulary classifies **tools**. Loop policy is a different object.
- Yield mixed D (`pending.md:50`): default step = one LLM + its tools. That **is** the CodeAct row. RLM does not get a second driver.

### Working hypotheses (snapshot §5; change requires pending revision)

- TC1(c) from analysis C (`docs/analysis/2026-08-23-c-codeact-and-rlm-on-pg-cordis.md:82` and following): kernel substrate + paradigms as data-driven policy bundles. pg-agent v2 inlines the bundle as `CASE paradigm` inside one `rlm_loop`; P19 is the table that replaces that inline branch.
- TC3(c): env is workspace, not log SoT. P19 **declares** env policy; it does not create `rlm_vars`.
- TC5: CodeAct v0 is structured tool-call blocks, not `exec_sql_readonly` as the only tool and not free-form in-DB code.
- TC6: prompt assembly is a projection. P19 stores the fold function name; P05/P13 write the function.
- Analysis C shared-substrate table (`c.md:62-72`): one log, one claim, one transport; paradigm-specific pieces are prompt, parser, observation clip, env, spawn. Those become columns.

### P06 relationship (why not `plugin_catalog` rows)

P06 plan (`docs/plans/P06-plugin-catalog-2026-08-23.md:79`, `:206`) lists P19 as a future **reader** of `cordis.plugin_catalog`. Read that as: the loop will render **tools** from the catalog. It is not an instruction to store paradigm policies as catalog rows.

`sql/0006_p06_plugin_catalog.sql:36-42` closes `invocation` to `queue` / `session_select` / `host_tool` and requires an effect/retry/reconciliation matrix that does not describe a loop policy. Expanding that CHECK in `0019` via `CREATE OR REPLACE` of `_validate_plugin_definition` would retcon P06’s closed vocabulary and force fake `effect_class` values. P19 does not edit `0006`.

Identity / version **grammar** is reused from P06 so P05/P10 see one identifier style. That is the “against this vocabulary” remainder.

### P00 install contract

Append only: `sql/0019_p19_paradigm_policies.sql`. Do not edit `0000`–`0006`. Discovery already accepts gaps (`sql/README.md:17`). `next_sql_prefix` is `max+1` (`tests/conftest.py:60-66`); after `0019` lands, probe files become `0020_*.sql`.

Every numbered file (`sql/README.md:29-35`; `tools/apply_pg_cordis.py:21-35`):

- replay-safe inside one tree-wide `--single-transaction`
- schema-qualified `cordis.*`
- no `\\connect` / `GRANT` / `CREATE EXTENSION` / `CREATE TABLE public.*` / `CREATE SCHEMA absurd` / role DDL / transaction-control / psql meta-commands
- no pg-agent `public` objects

Preflight still strips dollar-quoted bodies (`apply_pg_cordis.py:206-208`). **P19 must not edit `tools/apply_pg_cordis.py`.** Writing rule: `0019` plpgsql uses outer `$p19$`; GRANT/REVOKE/BEGIN/END words live only inside dollar-quotes or SQL comments. No `{`-prefixed `COMMENT` on P19 functions (`refresh_plugins` would try to parse them as plugins).

`verify_bootstrap` does not pin the version string. Tests do.

### Tests that change when `0019` lands

`tests/test_p00_sql_source.py`:

- `KERNEL_FUNCTIONS` (`:23-42`) is an **exact** `proname` list, `ORDER BY 1`. Add the four P19 verbs plus six stubs plus `apply_observation_policy` (see W194).
- `test_fresh_apply_lists_current_tree_and_p06` (`:46-65`): file list currently `0000,0001,0002,0003,0006`; version `'p06'`. Rename to `…_and_p19`; append `0019_p19_paradigm_policies.sql`; version `'p19'`; assert `paradigm_policies` exists; keep jobs / agent_steps / wait tables / catalog tables / no extension.
- `test_numbered_file_extension_without_loader_change` (`:186-189`): hardcoded list before `{probe_name}` must include `0019_p19_paradigm_policies.sql`.
- composition `:503` `'p06'` → `'p19'`.

`tests/test_p01_claim.py`: `_ensure_p01` applies the product tree; `:130` and `:495` `'p06'` → `'p19'`.

`tests/test_p02_agent_steps.py`:

- full tree `:337` `'p06'` → `'p19'`;
- `_apply_p02_only` `:113` stays `'p02'`.

`tests/test_p03_wait_event.py`: P03-only trees stay `'p03'` (`:159`, `:1212`). Do not add `0019` to those temp trees.

`tests/test_p06_plugin_catalog.py`: product apply (`P06_DB`) currently pins `'p06'` (`:215` and in-place replay `:216`). Those become `'p19'`. Catalog behavior is otherwise unchanged.

Reuse `tests.conftest` helpers. Do not `import tools.apply_pg_cordis`.

### pg-agent precedent (other database — not copy target)

`pg-agent/v2/pg_agent_rlm.sql` runs **one** loop body and branches on `agent_runs.paradigm` for prompt + latch. Identities observed: `'codeact'|'rlm'|'hybrid'|'data_analysis'`. `rlm_clip` is 4000 chars with full result in env `last_obs`. `rlm_spawn` is synchronous in-transaction — **forbidden** here (D9). `codeact_spawn` discovers children by `created_at DESC` — also forbidden (snapshot spawn lineage is log events; P17).

P19 copies the **split** (shared loop, per-paradigm prompt/parser/clip/env), not the SQL loop and not `hybrid` / `data_analysis` seeds.

This product has no `agent_runs` table (P02 explicitly did not create one). P19 does not create it. The discriminator for a live job is **not** this file’s work (decision 6).

---

## Current-state analysis

### Existing responsibilities

| Component | Responsibility today | P19 consequence |
|---|---|---|
| `sql/0000_kernel.sql` | schema `cordis` + version stub | Unchanged |
| `sql/0001_p01_claim.sql` | `cordis.jobs` + claim verbs | Unchanged. No `paradigm` column. `job_type` is not the discriminator |
| `sql/0002_p02_log.sql` | `agent_steps` + emit monopoly; kinds already include `spawn/start` / `spawn/end` | Unchanged. P19 writes no log |
| `sql/0003_p03_wait_event.sql` | wait/event side tables | Unchanged |
| `sql/0006_p06_plugin_catalog.sql` | tool catalog + host register + `'p06'` | Unchanged. P19 does not INSERT catalog rows and does not extend `invocation` |
| `tools/apply_pg_cordis.py` | discover / preflight / apply | **No production change** |
| `tests/test_p00_sql_source.py` | exact files + `'p06'` + exact functions | File list + version + function set grow |
| pg-agent `rlm_loop` | inlined `CASE paradigm` | Precedent for the anti-goal |

### Current data/control flow

```text
tools/apply_pg_cordis.py
  → discover sql/NNNN_slug.sql  (today ends at 0006)
  → preflight
  → apply in --single-transaction
  → verify cordis + get_schema_version() identity |text
```

No product paradigm registry exists. P05/P09 cannot yet select a policy without hard-coding.

P19 product path:

```text
jsonb envelope { "cordis_paradigm": { … } }
  → cordis._validate_paradigm_policy   -- enums, env, spawn, slot signatures
  → cordis.register_paradigm_policy    -- UPSERT (runtime)
  → cordis.paradigm_policies

0019 apply
  → CREATE six slot stubs (fold STABLE, parse/observe IMMUTABLE)
  → CREATE apply_observation_policy
  → INSERT seeds … SELECT validate ON CONFLICT DO NOTHING
  → get_schema_version → 'p19'

driver (P05, not this P)
  → policy ← paradigm_policy(identity)
  → fold   ← policy.fold_fn(run_id)
  → parsed ← policy.parse_fn(llm_text)
  → obs    ← apply_observation_policy(policy.observe_fn(raw), clip, full_in_env)
```

### Reuse / do not duplicate

Reuse: numbered-file discovery; tree-wide transaction; `cordis` naming; P06 identity/version grammar; `run_apply` / `psql` / `pgdata`; SQLSTATE `22023`; dollar-quote tag around GRANT/END words; `CREATE TABLE IF NOT EXISTS` / `CREATE OR REPLACE`; version function last.

Do not copy: `plugin_catalog` columns; `refresh_plugins` COMMENT scan; `agent_runs`; pg-agent `rlm_loop` / `rlm_vars` / `rlm_children`; P06-style stub **plugin** functions (these loop-slot stubs are not catalog tools); `jobs.paradigm` column; a second queue; `hybrid` / `data_analysis` seeds.

### Hard constraints

- Schema `cordis`; product name `pg_cordis`.
- Exactly one new numbered SQL file: `sql/0019_p19_paradigm_policies.sql`.
- No GRANT / EXTENSION / public tables / tx-control / psql meta-commands.
- Append-only: do not edit `0000`–`0006`.
- Policy rows are declarative. No row causes dynamic SQL, LLM calls, spawn, or plugin loading.
- Slot names are text on the row. At validate/register time they **must** resolve to existing functions with the locked signatures (`fold`/`parse`: `(text)→jsonb`; `observe`: `(jsonb)→jsonb`).
- No `{`-prefixed COMMENT on P19 functions.
- No `CREATE EXTENSION`.

---

## Design

### Resolved decisions

| # | Decision | Evidence and rationale | Rejected alternative |
|---:|---|---|---|
| 1 | New table `cordis.paradigm_policies`, not `plugin_catalog` rows and not an `invocation='paradigm'` extension of P06. | P06 `invocation` and effect/retry CHECKs (`sql/0006_p06_plugin_catalog.sql:36-73`) describe tools. Loop policy has prompt/parser/clip/env/spawn, none of which are catalog columns. Editing `0006` violates append-only release. P06’s “P19 reads the catalog” line is about **tool** rendering. | Stuffing policies into `plugin_catalog` with fake `effect_class='read_only'`. Replacing P06 validator to add `paradigm`. A second COMMENT→refresh compiler. |
| 2 | Filename `sql/0019_p19_paradigm_policies.sql`; marker `'p19'` in that file. | Skeleton number is P19; gaps allowed (`sql/README.md:17`). `0004`/`0005`/`0007` remain free for P04/P05/P07. Highest numeric prefix wins the version string. | `0007_p19_*.sql` (steals P07’s likely prefix). Waiting for P08 because the skeleton number sits after P08. |
| 3 | Seed identities `codeact` and `rlm` only. Identity grammar = P06. Identity is **not** a closed enum. | Skeleton “two registrations”. pg-agent discriminator strings without `hybrid` (inlined if-else) or `data_analysis` (D1). Open PK is the proof that the kernel does not `CASE identity`. | Closed CHECK `identity IN ('codeact','rlm')`, which *is* a frozen if-else. Seeding `hybrid`. `paradigm.codeact` dotted names — extra noise for the P05 discriminator. |
| 4 | No exact A∨B tuple CHECK. Closed enums stay; cross-field CHECKs are only env self-consistency and “no sync spawn”. `action_surface`, `parser_kind`, and clip vary independently. | Oracle P1.2: the exact two-bundle disjunction froze both paradigms in DDL; a third row was only an alias. Skeleton asked P19 to decide **fields**, not to lock every field into two frozen tuples. A later *kind* (new enum value) still needs a numbered file. | Exact bundle A∨B. Closed `identity` enum. |
| 5 | Dispatch ABI is the three function **slots** plus `apply_observation_policy`. P19 locks signatures, ships stubs, and **resolves** them at validate/register. Fold stubs are `STABLE`; parse/observe stubs and `apply_observation_policy` are `IMMUTABLE`. P19 owns the six names; real bodies live in a numbered file **> 0019** (not in `0005`). | Oracle round 2: `CREATE OR REPLACE` in `0019` would wipe `0005`; `to_regprocedure(fold_fn)` without `(text)` cannot resolve; `IMMUTABLE` fold is wrong for a log projection; clip columns were unused. | Enum-only dispatch. Unresolved forward names as live policy. Real bodies in `0005`. `IF identity = 'rlm'`. |
| 6 | P19 does **not** ALTER `cordis.jobs` and does not create `agent_runs`. The run discriminator is P05 (or the enqueue path that P05 defines). | P19 is parallel with P05. `jobs.job_type` is already a handler label, not a paradigm. P02 refused `agent_runs`. Candidate for P05: `jobs.payload->>'paradigm'` or a new column; **not decided here**. | Adding `jobs.paradigm` in P19 (couples queue to policy before any driver exists). Recreating pg-agent `agent_runs`. |
| 7 | Env policy is declarative columns. **No `rlm_vars` table, no `env_*` API, no GUC `rlm.run_id`.** | Snapshot §3 lists `rlm_vars` as workspace; skeleton says children execute in P17. A table without readers is premature ABI. D1 forbids TEMP as REPL. | Creating `rlm_vars` “as a placeholder”. Folding env into log (TC3(a), rejected by snapshot). |
| 8 | `spawn_mode` is the policy for **explicit child admission** only. Closed set is `{always_enqueue}`. Both seeds use that value. In-step tools are not spawn and do not read this column. | Oracle P1.3: CodeAct `none` conflated “tools ≠ spawn” with “CodeAct cannot request a child” and would block P17/P18 Context Builder from a CodeAct parent. D9: every operation that *is* spawn enqueues; it does not forbid CodeAct from spawning. No `sync` value. | `spawn_mode='none'` on CodeAct. A `sync` value. Treating ordinary tool calls as spawn. |
| 9 | Observation clip: CodeAct `NULL` (no clip); RLM `4000` with `observation_full_in_env = true`. | pg-agent `rlm_clip` + `last_obs`; paper D.1 truncated REPL output. CodeAct observations stay on the log as tool results (P05/P16). | Clipping CodeAct. Storing full RLM observations only in the log (explodes context, C’s reason for workspace). |
| 10 | Runtime authoring is `register_paradigm_policy(jsonb)` with envelope key `cordis_paradigm`. Apply-time seeds are `INSERT … SELECT * FROM _validate_paradigm_policy(...) ON CONFLICT (identity) DO NOTHING`. No COMMENT scan, no `refresh_plugins` hook. | Oracle P1.4: seeding through `register` upsert would overwrite runtime/later-file prompt edits on every in-place apply. Validator still owns seed shape. Envelope name is distinct from `cordis_plugin`. | Seeds calling `register` (overwrite). Reusing `cordis_plugin`. COMMENT-on-stub-plugin. Raw INSERT that skips validate. |
| 11 | Retry curves and D6 caps are **not** columns. | D4: retry **state** is kernel; P04 owns the machine. D6: v0 caps are kernel-wide. Skeleton “拍什么” list is prompt/parser/clip/env, not backoff. | Baking `max_attempts` into P19 and forcing P04 to read it. |
| 12 | Unregister of seed identities is allowed. Replay of `0019` restores a **missing** seed and does **not** overwrite an existing seed row. Lasting seed-text changes belong in a numbered file `> 0019` or in a runtime `register` upsert. | Oracle P1.4: P05/P13 occupy lower prefixes, so they cannot patch seeds after `0019` in apply order. `ON CONFLICT DO NOTHING` plus this ownership rule is the replay contract. | Apply-time UPSERT of seeds. Protecting seeds in `unregister` with an identity allowlist. |
| 13 | `metadata jsonb NOT NULL` stores the complete original `p_definition` envelope (P06’s rule). No separate user-metadata object, no default `{}`. | Oracle P1.5: the draft said default `{}`, “unknown keys plus original object”, and “original envelope” at once. | A nested `metadata` key merged with unknown fields. Default empty object on seeds. |

No implementation question remains open. Mid-flow answers belong in this table, not in Open questions.

### Cross-field CHECKs (decision 4) and dispatch signatures (decision 5)

Table CHECK `paradigm_policies_env_check` is exactly:

```text
(
  env_enabled = false
  AND env_workspace = 'none'
  AND env_inherit = 'none'
  AND observation_full_in_env = false
)
OR
(
  env_enabled = true
  AND env_workspace = 'run_vars'
  AND env_inherit IN ('none', 'named_grants_and_question')
)
```

Table CHECK `paradigm_policies_spawn_mode_check`: `spawn_mode = 'always_enqueue'`.

`action_surface`, `parser_kind`, and `observation_clip_chars` are **not** tied to those predicates. Seeds still use the intended CodeAct/RLM combinations; a third identity may mix clip with structured tools, or set `env_inherit='none'` on an env-enabled row.

**Locked slot signatures** (P19 creates stubs with `CREATE OR REPLACE` in `0019`):

| Slot | SQL signature | Volatility | Stub return |
|---|---|---|---|
| `fold_fn` | `(p_run_id text) RETURNS jsonb` | `STABLE` | `{"p19_stub": true, "slot": "fold", "run_id": <p_run_id>}` |
| `parse_fn` | `(p_llm_text text) RETURNS jsonb` | `IMMUTABLE` | `{"p19_stub": true, "slot": "parse", "outcome": "malformed", "action": null, "payload": null, "final_text": null}` |
| `observe_fn` | `(p_raw jsonb) RETURNS jsonb` | `IMMUTABLE` | `{"p19_stub": true, "slot": "observe", "shown": <2000 `x` chars>, "stored": <p_raw>}` |

Kernel wrapper (not a per-paradigm name):

```text
cordis.apply_observation_policy(p_obs jsonb, p_clip_chars integer, p_full_in_env boolean)
  RETURNS jsonb
  LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER
```

Exact rule:

If `p_obs` is SQL NULL or `jsonb_typeof(p_obs)` is not `object`, raise `22023` / `invalid observation`.
1. `shown0 := COALESCE(p_obs->>'shown', '')`.
2. `shown := CASE WHEN p_clip_chars IS NULL THEN shown0 ELSE left(shown0, p_clip_chars) END`.
3. `stored := CASE WHEN p_full_in_env THEN COALESCE(p_obs->'stored', 'null'::jsonb) ELSE to_jsonb(shown) END`.
4. Return `p_obs || jsonb_build_object('shown', shown, 'stored', stored)` (preserves `p19_stub` and other keys).

P05 real `parse_fn` keeps this envelope (extra keys allowed):

```text
outcome: "continue" | "final" | "malformed"
action:  "tool_calls" | "env_eval" | null
payload: jsonb or null
final_text: text or null
```

P05 real `observe_fn` still returns `{shown, stored}` **unclipped**; the wrapper applies clip / full-in-env. P05 real `fold_fn` stays `(text) → jsonb` and **STABLE**.

**Body ownership:** `0019` always installs the stubs. A later numbered file **> 0019** may `CREATE OR REPLACE` the six names with real bodies. `0005` (or any prefix `< 0019`) must not own those names — numeric apply would let `0019` win. P05’s driver SQL may still be `0005` if it only *calls* the slots.

Driver sketch (W195 exercises this on stubs):

```text
policy ← paradigm_policy(identity)
fold   ← policy.fold_fn(run_id)
parsed ← policy.parse_fn(llm_text)
obs    ← apply_observation_policy(policy.observe_fn(raw), policy.observation_clip_chars, policy.observation_full_in_env)
```

No `CASE identity`.

### Envelope (`cordis_paradigm`)

```json
{
  "cordis_paradigm": {
    "identity": "codeact",
    "version": "0.1.0",
    "description": "…",
    "action_surface": "structured_tools",
    "parser_kind": "json_tool_calls",
    "spawn_mode": "always_enqueue",
    "env_enabled": false,
    "env_workspace": "none",
    "env_inherit": "none",
    "observation_clip_chars": null,
    "observation_full_in_env": false,
    "system_prompt": "…",
    "fold_fn": "cordis.fold_codeact_messages",
    "parse_fn": "cordis.parse_codeact_decision",
    "observe_fn": "cordis.observe_codeact"
  }
}
```

Required keys inside `cordis_paradigm`: `identity`, `version`, `action_surface`, `parser_kind`, `spawn_mode`, `env_enabled`, `env_workspace`, `env_inherit`, `observation_full_in_env`, `system_prompt`, `fold_fn`, `parse_fn`, `observe_fn`.

`description` default = `identity`. `observation_clip_chars` may be JSON `null` (CodeAct seed). `spawn_mode` must be the string `always_enqueue`.

`metadata` on the table row is the complete original `p_definition` (the argument to validate/register), including unknown keys. There is no default `{}` and no second merged object.

Reject the envelope if the top-level object contains `cordis_plugin`, `job_handler`, or `workbench_plugin`.

---

## Component 1 — `sql/0019_p19_paradigm_policies.sql`

**Kind:** numbered SQL source file  
**Path:** `sql/0019_p19_paradigm_policies.sql`  
**Applied:** after `0006_p06_plugin_catalog.sql` (and after any `0004`/`0005`/`0007` that may exist at implementation time)

Replay-safe. Order inside the file:

1. `cordis.paradigm_policies` + named constraints;
2. `cordis._validate_paradigm_policy`;
3. `cordis.register_paradigm_policy`;
4. `cordis.unregister_paradigm_policy`;
5. `cordis.paradigm_policy`;
6. six stub functions (`fold_codeact_messages`, `fold_rlm_messages`, `parse_codeact_decision`, `parse_rlm_decision`, `observe_codeact`, `observe_rlm`);
7. `cordis.apply_observation_policy`;
8. two seed `INSERT … SELECT … FROM cordis._validate_paradigm_policy($p19seed$…$p19seed$::jsonb) ON CONFLICT (identity) DO NOTHING;`;
9. `CREATE OR REPLACE FUNCTION cordis.get_schema_version()` returning `'p19'`.

All P19 functions are `SECURITY INVOKER` and pin `search_path` to `pg_catalog`. Writers and the validator are `VOLATILE`. `paradigm_policy` is `STABLE`. The version function remains `LANGUAGE sql IMMUTABLE SECURITY INVOKER`, same shape as `0006` (`sql/0006_p06_plugin_catalog.sql:770-777`). Schema-qualify builtins (`pg_catalog.btrim`, `pg_catalog.clock_timestamp`, `pg_catalog.octet_length`, `pg_catalog.jsonb_typeof`).

plpgsql bodies use `$p19$`. No nested dollar tags. No `{`-prefixed COMMENT.

Do not call `refresh_plugins()` at the end of `0019`.

---

## Component 2 — `cordis.paradigm_policies`

**Kind:** persistent registry. **Owner:** `register_paradigm_policy` / `unregister_paradigm_policy` / apply-time seeds. P05+ **read** via `paradigm_policy(text)`.

### Exact columns

| Column | Type | Null/default | Meaning |
|---|---|---|---|
| `identity` | `text` | `NOT NULL`, PK | Discriminator P05 will pass; seed values `codeact`, `rlm` |
| `version` | `text` | `NOT NULL` | Definition version; not part of the key |
| `description` | `text` | `NOT NULL` | Human text; default `identity` |
| `action_surface` | `text` | `NOT NULL` | `structured_tools` or `env_repl` |
| `parser_kind` | `text` | `NOT NULL` | `json_tool_calls` or `json_env_eval` |
| `spawn_mode` | `text` | `NOT NULL` | `always_enqueue` only (explicit child admission; D9) |
| `env_enabled` | `boolean` | `NOT NULL` | Whether the run may use workspace vars |
| `env_workspace` | `text` | `NOT NULL` | `none` or `run_vars` |
| `env_inherit` | `text` | `NOT NULL` | `none` or `named_grants_and_question` |
| `observation_clip_chars` | `integer` | nullable | `NULL` = no clip; else max chars the model is shown |
| `observation_full_in_env` | `boolean` | `NOT NULL` | Full observation stored in env (`last_obs` shape) |
| `system_prompt` | `text` | `NOT NULL` | Contractual system prompt for this policy |
| `fold_fn` | `text` | `NOT NULL` | Qualified name of the prompt-fold projection |
| `parse_fn` | `text` | `NOT NULL` | Qualified name of the decision parser |
| `observe_fn` | `text` | `NOT NULL` | Qualified name of the observation policy |
| `metadata` | `jsonb` | `NOT NULL` | Complete original `p_definition` envelope |
| `registered_at` | `timestamptz` | `NOT NULL DEFAULT pg_catalog.clock_timestamp()` | First insert |
| `updated_at` | `timestamptz` | `NOT NULL DEFAULT pg_catalog.clock_timestamp()` | Last upsert |

No other indexes. PK lookup is the access path.

### Named constraints

| Name | Exact contract |
|---|---|
| `paradigm_policies_pkey` | `PRIMARY KEY (identity)` |
| `paradigm_policies_identity_check` | `octet_length(identity) <= 128 AND identity ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'` (same as P06) |
| `paradigm_policies_version_check` | `octet_length(version) BETWEEN 1 AND 64 AND version ~ '^[A-Za-z0-9][A-Za-z0-9._+-]*$'` |
| `paradigm_policies_action_surface_check` | `action_surface IN ('structured_tools', 'env_repl')` |
| `paradigm_policies_parser_kind_check` | `parser_kind IN ('json_tool_calls', 'json_env_eval')` |
| `paradigm_policies_spawn_mode_check` | `spawn_mode = 'always_enqueue'` |
| `paradigm_policies_env_workspace_check` | `env_workspace IN ('none', 'run_vars')` |
| `paradigm_policies_env_inherit_check` | `env_inherit IN ('none', 'named_grants_and_question')` |
| `paradigm_policies_clip_check` | `observation_clip_chars IS NULL OR observation_clip_chars > 0` |
| `paradigm_policies_fn_name_check` | each of `fold_fn`, `parse_fn`, `observe_fn` matches `^cordis\.[a-z][a-z0-9_]*$` and `octet_length(…) <= 128` |
| `paradigm_policies_prompt_nonblank_check` | `pg_catalog.btrim(system_prompt) <> ''` |
| `paradigm_policies_metadata_object_check` | `jsonb_typeof(metadata) = 'object'` |
| `paradigm_policies_env_check` | the env self-consistency predicate in Design → Cross-field CHECKs |

**Table CHECK vs validator-only.** Table CHECKs are the rows above. Validator-only: `description` 1–500 chars, no control characters (`chr(0)`–`chr(31)` except none — same as P06: no controls at all); `system_prompt` 1–8000 **bytes**, no NUL / other C0 controls except newline (`chr(10)`) and tab (`chr(9)`); JSON types (booleans are JSON booleans, clip is JSON number or null); required keys; rejection of `cordis_plugin` / `job_handler` / `workbench_plugin`; `observation_clip_chars` integer in `1… 1000000` when not null.

`env_cross_run_reads` is **not a column**. The invariant “no cross-run env reads” is snapshot §5 and is documented here; the first env API plan must enforce it.

---

## Component 3 — Validator, register, unregister, lookup

### `cordis._validate_paradigm_policy(p_definition jsonb)`

`RETURNS TABLE` with every column of `paradigm_policies` except `registered_at` / `updated_at`.

Steps:

1. `p_definition` must be a JSON object. Else `RAISE … USING ERRCODE = '22023'`.
2. Reject if `p_definition ? 'cordis_plugin'` or `? 'job_handler'` or `? 'workbench_plugin'`.
3. `plugin := p_definition -> 'cordis_paradigm'` must be an object.
4. Read required keys; `btrim` text; default `description` to `identity` when omitted. Set `metadata := p_definition` (the complete original envelope). Do not default `metadata` to `{}`.
5. Enforce **every table CHECK** here (enums, spawn `always_enqueue`, env self-consistency, clip, fn-name grammar, nonblank prompt) **and** the validator-only length/control-character/JSON-type rules. Failures are `22023`, not table `23514`.
6. Resolve slot functions **before returning**. For each resolved OID, read `pg_proc` and require **all** of:
   - `to_regprocedure(fold_fn || '(text)')` / `parse_fn || '(text)'` / `observe_fn || '(jsonb)'` is non-null;
   - `prokind = 'f'` (ordinary function, not aggregate/window/procedure);
   - `proretset = false` (`RETURNS jsonb`, not `SETOF jsonb`);
   - `prorettype = 'jsonb'::regtype`;
   - `provolatile = 's'` for fold, `'i'` for parse and observe.
   Missing or mismatched: `22023` with fragment `invalid fold_fn` / `invalid parse_fn` / `invalid observe_fn`.
7. Return one normalized row. Do **not** insert.

All failures SQLSTATE `22023`. Message must contain a stable fragment tests can match (`invalid identity`). Required-key failures: `missing field: <name>`. Unknown keys stay inside `metadata` and are not errors.

Do not **execute** the slot functions during validate. Do resolve `to_regprocedure` with the argument lists above.

### `cordis.register_paradigm_policy(p_definition jsonb) RETURNS text`

1. `SELECT * FROM cordis._validate_paradigm_policy(p_definition)` into a record.
2. `INSERT … ON CONFLICT (identity) DO UPDATE` of every column except `identity` and `registered_at`. `updated_at = pg_catalog.clock_timestamp()`. `registered_at` is preserved on conflict (same rule as P06 host `registered_at`).
3. Return the identity text.

### `cordis.unregister_paradigm_policy(p_identity text) RETURNS boolean`

1. Trim; reject NULL/blank/illegal grammar with `22023` / `invalid identity` (same predicate as P06 `unregister_host_plugin`, `sql/0006_p06_plugin_catalog.sql:752-757`).
2. `DELETE FROM cordis.paradigm_policies WHERE identity = btrim(p_identity)`.
3. Return `true` if a row was deleted, `false` if none. Do **not** call `refresh_plugins`.

### `cordis.paradigm_policy(p_identity text)`

`STABLE`. `RETURNS TABLE` with **all table columns including timestamps**. The validator does not return timestamps.

1. Trim; reject NULL/blank/illegal grammar with `22023` / `invalid identity`.
2. `SELECT … FROM cordis.paradigm_policies WHERE identity = v_identity`.
3. If not found: `RAISE EXCEPTION 'unknown paradigm: %', v_identity USING ERRCODE = '22023'`.
4. Return the row.

This is the kernel ABI. P05/P09/P10 must call this function, not `CASE` on the identity string, and not `SELECT` from the table in new kernel SQL (tests may `SELECT` the table to count rows).

Exact signatures (identity arguments, for tests):

```text
cordis._validate_paradigm_policy(jsonb)
cordis.register_paradigm_policy(jsonb)
cordis.unregister_paradigm_policy(text)
cordis.paradigm_policy(text)
```

Volatility / security, asserted in W195:

| function | volatile | prosecdef |
|---|---|---|
| `_validate_paradigm_policy` | `v` | false |
| `register_paradigm_policy` | `v` | false |
| `unregister_paradigm_policy` | `v` | false |
| `paradigm_policy` | `s` | false |
| two fold stubs | `s` | false |
| four parse/observe stubs | `i` | false |
| `apply_observation_policy` (`plpgsql`) | `i` | false |
| `get_schema_version` (full tree) | `i` | false |

---

## Component 3b — Slot stubs and observation wrapper

Create the six functions named by the seeds, with the signatures and volatilities in Design → locked slot signatures. `LANGUAGE sql SECURITY INVOKER`, `search_path` pinned to `pg_catalog`, bodies in `$p19$`. Fold stubs: `STABLE`. Parse/observe stubs: `IMMUTABLE`. They are loop-slot stubs, **not** `cordis_plugin` tools: no `{`-prefixed COMMENT.

Observe stub `shown` is exactly `repeat('x', 2000)` so clip tests have measurable length.

Also create `cordis.apply_observation_policy(jsonb, integer, boolean) RETURNS jsonb` **`LANGUAGE plpgsql` `IMMUTABLE SECURITY INVOKER`** (not `sql`: it must `RAISE` `22023` / `invalid observation`). Pin `search_path` to `pg_catalog`. Body in `$p19$`. Validate `p_obs` first, then apply the four transformation steps. Volatility remains `i`; `W195` still asserts `i`.

`0019` uses `CREATE OR REPLACE` for these seven functions. Real replacements for the six slot names belong in a numbered file **> 0019**. Changing arity or result type is a later numbered file plus a plan change. P05 must keep fold `STABLE` and parse/observe/`apply_observation_policy` `IMMUTABLE`.

## Component 4 — Seed rows

Apply-time, after validator and stubs exist, **two** inserts that still go through the validator:

```sql
INSERT INTO cordis.paradigm_policies (
  identity, version, description, action_surface, parser_kind, spawn_mode,
  env_enabled, env_workspace, env_inherit, observation_clip_chars,
  observation_full_in_env, system_prompt, fold_fn, parse_fn, observe_fn,
  metadata, registered_at, updated_at
)
SELECT
  identity, version, description, action_surface, parser_kind, spawn_mode,
  env_enabled, env_workspace, env_inherit, observation_clip_chars,
  observation_full_in_env, system_prompt, fold_fn, parse_fn, observe_fn,
  metadata, pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
FROM cordis._validate_paradigm_policy($p19seed${…}$p19seed$::jsonb)
ON CONFLICT (identity) DO NOTHING;
```

JSON lives in `$p19seed$`. Prompts must not contain that tag. Nested `$p19$` inside the JSON is forbidden; the seed tag is different so plpgsql bodies stay `$p19$`.

Replay: missing seed rows are inserted; existing rows (including runtime `register` upserts) are left alone.

### Seed `codeact`

| Field | Value |
|---|---|
| `identity` | `codeact` |
| `version` | `0.1.0` |
| `description` | `CodeAct structured-tool policy for the shared loop kernel.` |
| `action_surface` | `structured_tools` |
| `parser_kind` | `json_tool_calls` |
| `spawn_mode` | `always_enqueue` |
| `env_enabled` | `false` |
| `env_workspace` | `none` |
| `env_inherit` | `none` |
| `observation_clip_chars` | JSON `null` |
| `observation_full_in_env` | `false` |
| `fold_fn` | `cordis.fold_codeact_messages` |
| `parse_fn` | `cordis.parse_codeact_decision` |
| `observe_fn` | `cordis.observe_codeact` |

`system_prompt` **exact text** (tests assert equality):

```text
You are a CodeAct agent. Each step is one model turn plus its structured tool calls. Call tools as JSON. Do not execute free-form code. Context is in the prompt, not in an environment. In-step tools are not child runs.
```

### Seed `rlm` (bundle B)

| Field | Value |
|---|---|
| `identity` | `rlm` |
| `version` | `0.1.0` |
| `description` | `RLM prime-agent policy: run-scoped env plus always-enqueue children.` |
| `action_surface` | `env_repl` |
| `parser_kind` | `json_env_eval` |
| `spawn_mode` | `always_enqueue` |
| `env_enabled` | `true` |
| `env_workspace` | `run_vars` |
| `env_inherit` | `named_grants_and_question` |
| `observation_clip_chars` | `4000` |
| `observation_full_in_env` | `true` |
| `fold_fn` | `cordis.fold_rlm_messages` |
| `parse_fn` | `cordis.parse_rlm_decision` |
| `observe_fn` | `cordis.observe_rlm` |

`system_prompt` **exact text**:

```text
You are an RLM prime agent. Context lives in run-scoped environment variables; address it there. Observations you see are truncated; full results remain in the environment. Child work uses rlm() and returns only an admission handle. Do not wait for a child in this step. Do not inline large context into the model prompt.
```

The named fold/parse/observe functions **are** the Component 3b stubs. W195 resolves `to_regprocedure(fold_fn || '(text)')` (and the parse/observe argument lists) and calls the looked-up names.

---

## Component 5 — Version marker and README

Near the end of `0019`, after seeds:

```sql
CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p19'::text;
$$;
```

`sql/README.md` product-tree paragraph currently (`:39-46`):

```text
tree including 0006_p06_plugin_catalog.sql → p06  (current product tree)
```

Change to: a tree whose highest numbered file is `0019_p19_paradigm_policies.sql` reports `p19` (current product tree after P19). Keep the `0003` → `p03` and `0006` → `p06` lines for prefix-truncated trees. Add one paragraph:

`0019` adds `cordis.paradigm_policies`, seeds `codeact` / `rlm`, six slot stubs, and `cordis.apply_observation_policy`. Lookup is `cordis.paradigm_policy(text)`. These rows are loop policy, not plugin-catalog tools. Real slot bodies, if any, belong in a later numbered file `> 0019`.

---

## Component 6 — Tests

### W194 retarget

`KERNEL_FUNCTIONS` exact list after P19 (`ORDER BY 1`, C collation):

```text
cordis._validate_paradigm_policy
cordis._validate_plugin_definition
cordis.apply_observation_policy
cordis.await_event
cordis.checkpoint
cordis.claim_job
cordis.complete_claim
cordis.emit_event
cordis.emit_step
cordis.emit_step_claimed
cordis.fail_claim
cordis.fold_codeact_messages
cordis.fold_rlm_messages
cordis.get_schema_version
cordis.llm_checkpoint
cordis.next_step_name
cordis.observe_codeact
cordis.observe_rlm
cordis.paradigm_policy
cordis.parse_codeact_decision
cordis.parse_rlm_decision
cordis.refresh_plugins
cordis.register_host_plugin
cordis.register_paradigm_policy
cordis.release_stale
cordis.renew_claim
cordis.run_state
cordis.unregister_host_plugin
cordis.unregister_paradigm_policy
cordis.yield_claim
```

Sort notes: `_validate_paradigm_policy` before `_validate_plugin_definition`; `apply_observation_policy` before `await_event`; `fold_*` after `fail_claim` (`s` vs `i` on fold vs parse is volatility, not name order); `observe_*` after `next_step_name`; `paradigm_policy` before `parse_*`.

Product file list:

```text
0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,0003_p03_wait_event.sql,0006_p06_plugin_catalog.sql,0019_p19_paradigm_policies.sql
```

If P04/P05/P07 files already exist when P19 is implemented, append `0019` to **that** current list rather than deleting them. Do not take a dependency on those files.

Full-tree version `'p19'` in: `test_p00` current-tree + composition; `test_p01` both pins; `test_p02` full tree; `test_p06` current-tree + in-place replay.

Must stay unchanged:

- P02-only `'p02'` and P03-only `'p03'` and their absence assertions;
- P02 write-monopoly test (P19 contains no `INSERT INTO cordis.agent_steps`);
- loader / preflight / `conftest.py` / `next_sql_prefix` implementation;
- P06 catalog semantics (host register, COMMENT refresh, mutex).

### W195 named tests — `tests/test_p19_paradigm_policies.py`

Reuse `run_apply`, `psql`, `next_sql_prefix`. Database name `cordis_p19`. Reset via `--reset`. No `import tools`.

Named functions (complete list):

1. `test_p19_fresh_apply_seeds_and_version` — file in tree; version `p19`; table exists; `SELECT count(*) FROM cordis.paradigm_policies` = `2`; identities `codeact,rlm`; `plugin_catalog` still empty until a host plugin is registered; no `rlm_vars` table; no `public.paradigm_policies`.
2. `test_p19_lookup_codeact_and_rlm` — `paradigm_policy('codeact')` / `('rlm')` return the exact seed fields including both `system_prompt` strings, clip NULL vs 4000, **both** `spawn_mode='always_enqueue'`, env columns, fn names, and `metadata->'cordis_paradigm'->>'identity'`.
3. `test_p19_unknown_and_invalid_identity` — `paradigm_policy('hybrid')` and `paradigm_policy('data_analysis')` raise `22023` / `unknown paradigm`; `paradigm_policy('')`, `NULL`, and `paradigm_policy('CodeAct')` raise `invalid identity`.
4. `test_p19_third_policy_independent_clip` — register `probe.alias` with `action_surface='structured_tools'`, `parser_kind='json_tool_calls'`, `spawn_mode='always_enqueue'`, env disabled, `observation_clip_chars=1000`, different `system_prompt`, **reuse** `cordis.fold_codeact_messages` / `parse_codeact_decision` / `observe_codeact`; lookup returns clip 1000; count = 3; unregister returns true; seeds remain.
5. `test_p19_register_rejects_illegal_env_sync_and_plugin_envelope` — (a) `env_enabled=true` and `env_workspace='none'` rejected with `22023` from `_validate_paradigm_policy` (not `23514`); (b) `spawn_mode='sync'` → `22023`; (c) unknown `action_surface` → `22023`; (d) envelope with `cordis_plugin` rejected; (e) `fold_fn='cordis.missing_fold'` → `22023` / `invalid fold_fn`; (f) a `RETURNS SETOF jsonb` fold, a `VOLATILE` fold, and a `RETURNS text` fold each → `22023` / `invalid fold_fn`; (g) a `STABLE` custom parser → `22023` / `invalid parse_fn`; (h) a `RETURNS SETOF jsonb` observer → `22023` / `invalid observe_fn` (create those helpers in the test DB via `psql`, not as product SQL); (i) seed rows unchanged.
6. `test_p19_unregister_and_replay_restores_missing_seed` — unregister `codeact` → lookup raises unknown; in-place `run_apply` without `--reset` inserts `codeact` again with the seed prompt; `mode=in-place`; version `p19`. Preserve `public.p19_sentinel` across replay.
7. `test_p19_replay_preserves_runtime_upsert` — `register_paradigm_policy` upserts `codeact` with a new `system_prompt`; in-place apply; prompt is still the new text (`ON CONFLICT DO NOTHING`). Then restore the seed prompt via another register so later tests are isolated, **or** run this test last on its own `--reset`.
8. `test_p19_upsert_preserves_registered_at` — register `probe.alias`; capture `registered_at`; register again with a new description; `registered_at` equal; `updated_at` greater or equal; unregister.
9. `test_p19_dispatch_calls_slot_stubs_by_name` — for both seeds: look up slot names from `paradigm_policy(identity)`; `to_regprocedure(fold_fn || '(text)')` is not null; execute `SELECT <fold_fn>('run-1')` (and parse/observe) using **only the looked-up names**. Each result `->>'p19_stub' = 'true'`.
10. `test_p19_observation_wrapper_clips_without_identity_branch` — `obs := observe_codeact('{}'::jsonb)` (shown length 2000). `apply_observation_policy(obs, 10, false)` shown length 10; `apply_observation_policy(obs, NULL, false)` shown length 2000; `apply_observation_policy(obs, 1000, true)` shown length 1000 and `stored` remains the stub stored value. `apply_observation_policy('{}'::jsonb, 10, false)` shown is empty text (missing key). SQL NULL `p_obs` and `'[]'::jsonb` raise `22023` / `invalid observation`. Uses the wrapper only — no identity branch and no `probe.alias` row.
11. `test_p19_higher_file_replaces_stub_and_survives_replay` — copy the sql tree; add `{next_sql_prefix}_sentinel.sql` (`0020_…` while 0019 is max) with:

    ```sql
    CREATE OR REPLACE FUNCTION cordis.fold_codeact_messages(p_run_id text)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SECURITY INVOKER
    SET search_path TO pg_catalog
    AS $sentinel$
      SELECT pg_catalog.jsonb_build_object('sentinel', true, 'run_id', p_run_id);
    $sentinel$;
    ```

    Do not replace `get_schema_version`. Fresh apply: `fold_codeact_messages('r')` is sentinel, version `p19`. In-place replay: still sentinel. This is the ownership proof that real bodies belong in files `> 0019`.
12. `test_p19_signatures_and_volatility` — four verbs + six stubs + `apply_observation_policy` exist once each; fold stubs `s` + `sql`; parse/observe stubs `i` + `sql`; wrapper `i` + **`plpgsql`**; arguments as locked; `get_schema_version` still `|text|sql|i|false`.
13. `test_p19_does_not_touch_plugin_catalog_invocation` — `plugin_catalog` CHECK still `invocation IN ('queue','session_select','host_tool')`. Host-plugin register still works (inline the P06 proof JSON; do not import `test_p06_plugin_catalog`).

No test relies on a permanently running postmaster between sequential CLI subprocesses.

### Commands

```bash
uv run pytest tests/test_p19_paradigm_policies.py -q
uv run pytest tests/test_p00_sql_source.py tests/test_p01_claim.py tests/test_p02_agent_steps.py tests/test_p03_wait_event.py tests/test_p06_plugin_catalog.py tests/test_p19_paradigm_policies.py -q
```

P19 changed the numbered SQL tree, so the earlier protocol tests in that second command are required (`Agents.md` 送审之前 §2).

---

## File-by-file impact

| File | Change |
|---|---|
| `sql/0019_p19_paradigm_policies.sql` | **Create.** DDL, validator, register/unregister/lookup, six stubs, `apply_observation_policy`, two `ON CONFLICT DO NOTHING` seeds, version `'p19'` |
| `sql/README.md` | Document `0019` / `'p19'` / policy table vs plugin catalog |
| `tests/test_p00_sql_source.py` | File list, `KERNEL_FUNCTIONS`, version, probe list, composition |
| `tests/test_p01_claim.py` | Full-tree version `'p19'` |
| `tests/test_p02_agent_steps.py` | Full-tree version `'p19'` only |
| `tests/test_p06_plugin_catalog.py` | Product-tree version `'p19'` |
| `tests/test_p19_paradigm_policies.py` | **Create.** Named tests above |
| `docs/plans/P19-paradigm-policies-2026-08-24.md` | This plan |

Do not edit: `tools/apply_pg_cordis.py`, `tests/conftest.py`, `sql/0000`–`sql/0006`, P03-only fixtures, P02-only fixtures, pg-agent, pgembed.

---

## What P05 must consume (handoff, not this P)

- Look up policy with `SELECT … FROM cordis.paradigm_policy(<identity>)`.
- Store the identity on the run at enqueue time (column vs `jobs.payload` is P05’s decision).
- Call slots by the names in the row; wrap observe with `apply_observation_policy(obs, clip, full_in_env)`. Do not `CASE identity`.
- Real slot bodies: numbered file **> 0019**, same signatures, fold remains `STABLE`. Do not put those names in `0005`.
- Explicit child admission (CodeAct Context Builder, RLM `rlm()`) uses `spawn_mode='always_enqueue'` and enqueues (P17 executes children). Ordinary in-step tools are not spawn.
- Do not create `rlm_vars` unless the P05 plan explicitly claims workspace DDL.
- Do not implement sync child loops.
- Seed-prompt updates: runtime `register_paradigm_policy` or a file `> 0019`.

---

## Risks and deferred work

- **Discriminator storage** is unset until P05. Until then nothing writes `codeact`/`rlm` onto a jobs row. P19 still completes: lookup + stub dispatch work.
- **`rlm_vars` unassigned.** Snapshot names the table; no numbered P owns the DDL yet. P19 must not sneak it in. First consumer plan must claim it.
- **A new enum value** (`action_surface`, `parser_kind`) needs a later numbered file. Independent clip/env_inherit/prompt already do not.
- **Retry curve not on the row.** If P04 wants per-paradigm backoff, it adds a column in `0004` or a later file, not by editing `0019`.
- **Prompt text is contractual v0.** Richer prompts: runtime `register_paradigm_policy` or a file numbered `> 0019`.
- **No cancel/grant/wait interaction.** Policies are data.

## Open questions

None for P19 implementation. Deferred items above are owned by later P numbers, not open forks inside this file.

## References

- `docs/plans/2026-08-23-pg-cordis-development.md:202-212` — P19 skeleton
- `docs/plans/2026-08-23-pg-cordis-development.md:38`, `:79` — parallel with P07/P05; after P06
- `docs/decisions/2026-08-23-pending.md` — D1, D6, D8, D9; yield mixed D; no `CREATE EXTENSION`
- `docs/analysis/2026-08-23-i-architecture-snapshot.md:37`, `:63`, `:73`, `:117`, `:131-134`, `:226`
- `docs/analysis/2026-08-23-c-codeact-and-rlm-on-pg-cordis.md` — TC1(c), TC3, TC5, TC6, substrate table
- `docs/analysis/2026-08-23-h-vision-d1-d9-oracle-verdicts.md` — CodeAct body, RLM prime-agent, D9 handle
- `docs/analysis/2026-08-23-g-rlm-one-step-driver.md` — semantic sketch only; not ABI
- `docs/plans/P06-plugin-catalog-2026-08-23.md:79`, `:100`, `:206` — catalog vs policy; P06 must not freeze paradigm if-else
- `sql/0006_p06_plugin_catalog.sql:5-93`, `:716-777` — closed invocation; host register; `'p06'`
- `sql/0001_p01_claim.sql:4-24` — jobs columns; no paradigm
- `sql/0002_p02_log.sql:14-27` — spawn kinds already reserved
- `sql/README.md:9-17`, `:39-46`
- `tests/test_p00_sql_source.py:23-65`, `:186-189`, `:503`
- `tests/conftest.py:60-66` — `next_sql_prefix = max+1`
- `pg-agent/v2/pg_agent_rlm.sql` — one loop, inlined paradigm branch (anti-goal)
