# L4 Review — Topic C: CodeAct and RLM on pg_cordis

Reviewer: design-agent (L4 substitute; oracle unavailable) · Turn 3 · Date: 2026-08-23
Report under review: `docs/analysis/2026-08-23-c-codeact-and-rlm-on-pg-cordis.md`
Rubric: `prompt-exports/loop-orchestrate-pg-cordis-research-runs.md` (frozen; Topic C sections)
Inherited context: `docs/analysis/2026-08-23-b-log-and-projection-contract.md` (unique log SoT; `rlm_vars` flagged as live second SoT; B's open C-questions)

## Verdict: **PASS**

All five rubric criteria are satisfied. Every load-bearing citation spot-checked in `pg-agent` (v1 + v2 SQL), `deepseek-harness` (`packages/core/agent-loop/`), and the RLM paper (`docs/RECURSIVE LANGUAGE MODELS.md`) is real — including exact line numbers, Chinese in-file quotes, recursion caps, and the paper's benchmark figures. The three flags carried over from the failed oracle attempt were adjudicated individually; none is a rubric violation, though all three produce inheritance notes for Topic D (below).

## Context / Scope

Reviewed the full report (103 lines) against the frozen rubric. Citations verified read-only by direct search and file reads in `pg-agent` and `deepseek-harness`; the RLM paper checked in `zcordis-pgembed/docs/`. Topic B report read in full for the SoT context. No changes made to the C report.

## Findings — rubric criteria

### 1. File path — PASS

File exists at exactly `docs/analysis/2026-08-23-c-codeact-and-rlm-on-pg-cordis.md`, matching the Turn 3 deliverable path in the rubric table.

### 2. Required headings verbatim — PASS

All five Topic C headings present as exact `##` headings, in rubric order:

| Required heading | Report line |
|---|---|
| `## CodeAct paradigm on pg_cordis` | 22 |
| `## RLM paradigm on pg_cordis` | 36 |
| `## Shared substrate vs paradigm-specific` | 58 |
| `## Key tradeoffs (opinion, not decision)` | 78 |
| `## Open questions for D` | 94 |

### 3. Concrete files/modules, no invented APIs — PASS

Spot-checked the load-bearing citations. Every checked function, constant, quote, and number is real:

| Claim in report | Check result |
|---|---|
| v1 `make_system_prompt`/`fold_messages`/`agent_run` "at lines 134/192/402" | exact: `v1/pg_agent_functional.sql` 134, 192, 402 |
| "唯一工具是 execute_sql" in the system prompt | verbatim, `v2/pg_agent_functional.sql:138` |
| mantra "决策是纯函数，动作是薄外壳，编排是数据，注册是注释" | verbatim, `v2/pg_agent_functional.sql:12` |
| `exec_sql_readonly`: single statement ("禁止多语句"), blacklist incl. `drop`/`insert`/`set`, wrap `SELECT COALESCE(jsonb_agg(t),'[]') FROM (… LIMIT n) t` | all confirmed, `v2/pg_agent_functional.sql:252–282` (`set` at 262) |
| query latch: `v_got_q`, "必须先成功执行至少一条 SELECT 才能 final_answer", `da_wrap_obs` applied in `rlm_loop` | confirmed, `v2/pg_agent_rlm.sql:413/457/464/483/486`; `da_wrap_obs` defined in `v2/pg_agent_data_analysis.sql:121` |
| `parse_rlm_output` maps `action_input`→`code` when `action ∈ ('execute_sql','eval','ipython','sql')` | verbatim CASE, `v2/pg_agent_rlm.sql:163–166` |
| `agent_run_hybrid` `action = 'rlm'` delegating via `rlm_spawn`; presets env `question`/`context` | confirmed, `v2/pg_agent_rlm.sql:784–786, 749–753` |
| `rlm_spawn` caps: `depth >= max_depth` OR `depth >= 4`; ≤ 16 children; child `max_steps = LEAST(parent,6)` | exact, `v2/pg_agent_rlm.sql:522–545` |
| `rlm_map` ≤ 8 chunks ("rlm_map 最多 8 块") | confirmed, `v2/pg_agent_rlm.sql:586` |
| v2 `codeact_spawn` calls `agent_run` directly, discovers child by `ORDER BY created_at DESC LIMIT 1`, retro-links `parent_run_id` | confirmed, `v2/pg_agent_rlm.sql:621–678`; "race-prone heuristic" is a fair characterization |
| `rlm_clip` default 4000, full result to env `last_obs`; `rlm.run_id` GUC with `rlm_bind` save/restore; `make_rlm_user` 1500-char threshold | confirmed, `v2/pg_agent_rlm.sql:351–357, 201–213, 365–374, 108` |
| Header quotes: "RLM × CodeAct", "rlm_loop 按 agent_runs.paradigm 分支", "两种范式的 run 在同一张表", rule 5 "可用 WITH 在一条语句里组合多个调用" | verbatim, `v2/pg_agent_rlm.sql:2, 5, 856, 76` |
| v1 standalone: `rlm_runs/rlm_steps/rlm_vars/rlm_children`, `'spawn'` kind, mantra "上下文是变量，工具是 SQL，子 agent 是函数" | confirmed, `v1/pg_agent_rlm.sql:17, 33–68, 50` |
| v1 integrated header: `paradigm`/`parent`/`depth`, "run_state() 对两种范式都成立", `job_type='rlm_run'`, `codeact_spawn` via `pg_agent_poml.sql`'s `agent_loop` | verbatim, `v1/pg_agent_rlm_integrated.sql:7–12` |
| "v2's `fold_rlm_messages` still understands `'spawn'` but nothing emits it" | verified: `'spawn'` appears only in the fold (`v2/pg_agent_rlm.sql:184,187`); no v2 emitter found |
| `render_workbench_tools()` STABLE, `read_only` ordered before `temp_view_mutation`, stable text on empty registry; `da_system_prompt = make_da_prompt(…) || render_workbench_tools()`; workbench bypasses `jobs`/`worker()`/`job_handler` (header) | confirmed, `v2/pg_agent_workbench_core.sql:11, 15–16, 214–244`; `v2/pg_agent_data_analysis.sql:147` |
| Job-handler registrations `h_agent_run`/`h_rlm_run`/`h_hybrid_run` via `COMMENT '{"job_handler":…}'` | confirmed (`v2/pg_agent_functional.sql:368–381`; `v2/pg_agent_rlm.sql:805–836`) |
| DSH module doc "Every request is derived from the session log" | verbatim, `packages/core/agent-loop/src/agent.ts:1–3` |
| `ReactLoopAgent`, `executeToolCalls`, `session.deriveMessages()`, `agent/pre-step`, `agent/request` waterfall, `chunkSeqs`, `sourceEventSeqs`, `next-turn`/`next-step`, `idle\|maintenance\|running` | all confirmed in `agent.ts` |
| `DEFAULT_MAX_PARALLEL_TOOL_CALLS = 10` in `src/constants.ts`; settings-owned cap read in `src/index.ts`; "Concrete agent-loop plugin: creates scoped ReactLoopAgents…"; `AgentLoop extends Service implements AgentFactory`; `static inject = ['agents','sessions','llm','tools','systemPrompt']`; `ctx.agents.setFactory(this)` | all verbatim (`constants.ts:6`; `index.ts:2, 134, 296–297, 350`) |
| RLM paper: CodeAct §2.2 quote, Figure 2 quote, `llm_query` "around 500K chars", truncated-outputs rule, `FINAL()`/`FINALVAR()`, "RLMs without asynchronous LM calls are slow", three §3.1 trajectory patterns, "essentially unbounded tokens" | all verbatim in `docs/RECURSIVE LANGUAGE MODELS.md` |
| Paper numbers: BrowseComp+ (GPT-5) RLM 91.33 at avg $0.99 vs CodeAct+BM25 51.00; "10M+ token regime" | exact table cells confirmed: `91.33 ($0.99 ± $1.22)`, `51.00 ($0.71 ± $1.20)` |

No invented APIs found. The report's structural syntheses (one loop body branched by paradigm; DSH's seam consumption; the quadratic refold) match the code as read.

### 4. Tradeoffs as options + analysis + opinion, not a decision — PASS

TC1–TC6 each list 2–3 lettered options, analyze them against evidence, and close with an italicized *Opinion*. The section opener states "None is a decision"; the document status line says "analysis with opinions, not architecture decisions". Opinions consistently defer enforcement questions to D (TC2 threshold, TC3 boundary, TC5's T4 revisit).

### 5. No shipped "build-this" architecture — PASS

The strongest architectural statement — loop kernel + paradigm-as-policy-bundle in the shared-substrate section — is labeled *Opinion*, grounded in the convergence of two existing designs, and framed as answering A's open question rather than fixing pg_cordis. Locked hypotheses (A's SQL-first, B's log SoT) are inherited, not re-decided.

## Adjudication of the three carried-over flags

**F1 — TC3 workspace tier vs B's unique-log-SoT: no rubric violation; real contract tension to inherit.** B explicitly handed C this question ("`rlm_vars`/env state: … legitimately separate?"), so C answering "yes, as a declared workspace tier" is in-scope, opinion-labeled, and argued with a sound technical reason why the B-orthodox option (a) fails: env values come from executing model-written SQL against live data, so a log fold cannot replay them, and the log already records the *code* that mutated the env. The locked assumption says the log is the unique SoT *for conversation/runtime history*; TC3(c) defines workspace as explicitly not-history, run-scoped, and contract-bound. However, B's own requirement 4 wording ("everything else is a projection … never a second source of truth") and B's TB6 opinion are stated more broadly than the locked assumption — TC3(c) is therefore an *amendment* to B's contract language, not a reading of it. That is legitimate analysis, but D (or the synthesis turn) must reconcile the wording: either B's requirement 4 gains a third named category (log / projection / workspace) with TC3's clauses, or workspace must be re-derived. C says this honestly; it does not pretend B already allowed it.

**F2 — env/REPL listed as shared though CodeAct may not use it: minor presentational inconsistency, factually accurate.** The row's cell is verified true — RLM owns `rlm_vars`/`env_*`; hybrid presets `question`/`context` (`agent_run_hybrid`, `v2/pg_agent_rlm.sql:749–753`). But pure CodeAct (`agent_run`) never touches env, so the cell sits under a column headed "both paradigms use it today" only via the hybrid paradigm. The governing requirement forces env/REPL to appear in the split table somewhere, and the cell's qualifier does the disambiguation work. Not a rubric failure; a stricter phrasing would place env/REPL as "shared *mechanism*, RLM-owned *usage*".

**F3 — TC5 "proven safe subset" vs the VOLATILE caveat: internal wording tension, not a factual error.** The same report states twice (CodeAct gaps; first D question) that the blacklist cannot stop side-effecting `VOLATILE` functions reachable from a plain `SELECT` — so "safe" in TC5(a) overstates what the report itself has already disproven. Read in context, "proven safe subset" functions as comparative shorthand ("battle-tested, smaller blast radius than free-form code"), and the opinion explicitly reserves (b) behind the T4/D isolation revisit. No claim of actual safety is made that the report doesn't immediately undercut with the D handoff. Verdict: note, not failure.

## Factual issues

None rubric-relevant. Two trivia: the workbench-core "file header, lines 7–16" citation is a block reference whose bypass statement sits at lines 15–16 (inside the cited block — fine); the retro-linking pattern also appears in `h_rlm_run`/`h_hybrid_run` (`ORDER BY created_at DESC` at `v2/pg_agent_rlm.sql:815,831`), which slightly strengthens the report's "not a contract" complaint rather than weakening it.

## Notes Topic D must inherit

1. **Workspace-tier reconciliation (from F1).** If D builds on TC3(c), it must restate B's requirement 4 as three categories (log = history SoT; projections = derived, never authoritative; workspace = run-owned execution state, non-authoritative, non-history) and carry TC3's contract clauses: run-owned, run-lifecycle-scoped, no cross-run reads. The no-cross-run-reads clause is exactly D's retrieval-range boundary — C already positioned it that way.
2. **Capability scoping replaces the blacklist (from F3).** D must not treat `exec_sql_readonly` as a safety mechanism; the report's own finding is that the real boundary is role/RLS/`search_path`/session-type discipline. TC5(a) should be read as "proven, smaller-blast-radius subset pending D's scoping", never as "safe".
3. **Spawn lineage as log events.** Both spawn paths bypass the event model today (`rlm_children` rows + `created_at DESC` retro-linking, confirmed in three places). D's isolation design should assume TC2's note: explicit run-id contract + `spawn/start`/`spawn/end` log events, whatever the sync/async choice.
4. **Env inheritance across spawns.** Spawns preset only `question` (hybrid also `context`) into a fresh child namespace — verified. D's worked example ("project 1's code for function 1; project 2's for functions 2–3") should use the scoped-slice inheritance question as its mechanism-level anchor, as C suggests.
5. **Multi-writer append ownership** (host-side `ReactLoopAgent` + in-database `rlm_loop` on one log) and **budget-per-subtree** are restated by C as D questions; both are isolation-owned, and C deliberately did not answer them.
