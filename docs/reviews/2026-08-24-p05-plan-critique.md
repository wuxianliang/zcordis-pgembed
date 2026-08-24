# P05 计划评审 — 对照 planning 导出基线与已落地代码

Date: 2026-08-24
Scope: `docs/plans/P05-one-step-driver-2026-08-24.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-24-220109-p05-one-step-driver-0d24.md`。导出含两份叠放草稿：第一稿（中文标题 `# P05 — 一步驱动 + LLM 幂等 A+B` 起，导出 121 行起，在 Component 5 的 `llm` payload 处**中途截断**，残留 "Reconnecting... 1/5"）与完整重写稿（`# P05 — One-Step Driver + LLM Idempotency A+B` 起，966 行起）。**重写稿是保留基线**；第一稿仅在其含重写稿丢掉且仍受支持的细节时才计入。导出顶部的 composed prompt 与选中文件清单是上下文，不是计划内容。

对承重引用做了代码定点核对：`sql/0001_p01_claim.sql`、`sql/0002_p02_log.sql`、`sql/0003_p03_wait_event.sql`、`sql/0006_p06_plugin_catalog.sql`、`sql/README.md`、`tests/test_p00_sql_source.py`、`tests/conftest.py`，以及计划 file:line 表指向的全部文档（骨架、pending、快照、F、G、P01/P03/P04/P06 计划）。

不重开：D1–D9、快照 §4，以及四条 mid-flow 用户决定（`cordis.step_once`；fail-closed wait stub；fixture-only `mock.observe`；hook 前不 `renew_claim`）。

## 结论摘要

**维度 1（基线内容缺失/弱化）对重写稿无发现。** 现行计划与重写稿做了逐行 diff：全部差异恰为四项声明的增补——中文标题、deliverables 把 "SQL-tree documentation updates" 具体化为 `sql/README.md` updates（是加严不是弱化）、mid-flow 确认行与确认表、"Load-bearing file:line sources (spot-checked)" 表，及 Open questions 收尾句同步提及 mid-flow forks。无任何实现承重内容被删、弱化或泛化。

**承重技术断言抽查全部成立**（详见文末「已核实断言」）：P01 动词签名与栅栏、`emit_step_claimed` 六参/`GREATEST` 只延不缩/null token 返回 false、`error`/`final` 允许携带 `s-N` envelope step_name（presence CHECK 只约束 `llm`/`tool`，`sql/0002_p02_log.sql:31-33`）、llm 唯一部分索引、`next_step_name` 续传语义、`llm_checkpoint` SETOF、P03 版 `run_state` 优先级 final > error > awaiting（`sql/0003_p03_wait_event.sql:515-521`）、`run/await`/`run/wake` payload 均带 `await_id`（0003:194-206、:284-295，log-only await 守卫可实现且对 P03 自身流程零误报）、`payload jsonb NOT NULL`（0001:8）、版本标记模式、`KERNEL_FUNCTIONS` 字母序插入位、四个点名回归测试名全部存在、`W50`–`W59` 区间确实空闲（P02 W19–W26、P03 W27–W33、P04 W34–W41、P06 W60–W66）。

发现共 7 条：**无 P0**；1 条 P1（计划自增的 file:line 表存在已核实的行号错误，与其 "spot-checked" 自述矛盾）；5 条 P2（一处过时表述、三处第一稿有而重写稿丢掉的可用细节、一处两文皆未写明的边界）；1 条 P2 级问题（错误码归属，只影响错误分类与一个测试）。修完 P1（P2 顺手折进）后计划可维持 `ready to implement`，无需改设计或实现顺序。

---

## 发现

### 1.（P1）"Load-bearing file:line sources (spot-checked)" 表有多处已核实的行号错误

该表是计划自己新增的核对锚点，自述 "spot-checked"，但以下引用对不上现文件（逐条用 `rg -n`/`sed -n` 核实）：

| 计划引用 | 实际位置 | 修正 |
|---|---|---|
| 快照 §4 `:83-84`（Yield 混合 D；LLM A+B 不管 tool） | Yield 行 = `docs/analysis/2026-08-23-i-architecture-snapshot.md:90`，LLM 幂等行 = `:91` | 改为 `:90-91` |
| 快照 `:95`（D9 enqueue children） | D9 行 = `:101` | 改为 `:101` |
| 快照 `:82`、`:91`（D1 / D7） | D1 行 = `:93`，D7 行 = `:99`（`:91` 实为 LLM 幂等行） | 改为 `:93`、`:99` |
| pending `:45-47`（Yield 混合 D；D9） | Yield+D9 行 = `docs/decisions/2026-08-23-pending.md:49`，LLM A+B 行 = `:50` | 改为 `:49-50` |
| "P04 scaffold `:91`"（W34+ 编号） | W 编号句 = `docs/plans/P04-sleep-retry-2026-08-24.md:61`（"P04 continues with W34–W41"） | 改为 `:61`，并去掉 "scaffold" 措辞（见发现 2） |
| `sql/0002_p02_log.sql:241-310`（含 `llm_checkpoint`） | `next_step_name` = 0002:279-333，`llm_checkpoint` = 0002:335-364；`:241-310` 只盖到 checkpoint 尾部加 next_step_name 前半 | 改为 `:279-364`（或分列两段） |
| P06 plan `:274`（"P06 catalog does not execute tools"） | `:274` 是 effect/retry/reconciliation 分类行，只间接支持；直接陈述在 P06 计划 `:39`（"P06 不发 grant、不执行工具"） | 改为（或加注）`:39` |

表内其余引用全部核实无误：骨架 `:35`/`:75`/`:154-162`、pending `:58`（D7）与 `:70-72`（D1 讨论）、F `:111-154`、G `:1-3`/`:507-514`、`sql/0001_p01_claim.sql:23-40`/`:128-237`、P01 计划 `:601`/`:728`/`:914`、P03 计划 `:48`/`:1540-1542`、P04 计划 `:1-3`、`sql/0006_p06_plugin_catalog.sql:465+`、`sql/README.md:9-51`、`tests/test_p00_sql_source.py:23-43`/`:57-65`、`tests/conftest.py:28-128`。

行号错误不改变任何设计结论（所指事实本身全部正确），但该表的存在意义就是给实现审查当校验锚点，留着已证伪的锚点会误导实现闸门。纯文本修正，成本一分钟。

### 2.（P2）"P04 is scaffold-only" 已过时

计划 Background（"What P03, P04, and P06 mean for P05"）与 file:line 表均称 P04 为 scaffold。实际 `docs/plans/P04-sleep-retry-2026-08-24.md` 现为 Status **ready to implement** 的完整深计划（W34–W41），且已有对应 plan-critique。基线重写稿同样带这句（导出时即已过时或随后过时）。**操作性事实不变**：`sql/0004_*` 不存在、编号空档保留、树内无 timeout/retry 机制，P05 的 fail-closed wait、终态错误、不做 retry 的全部推理照旧成立。

修正：改为 "P04 has a deep plan (ready to implement, `W34`–`W41`) but no `sql/0004_*`; the gap remains reserved and no timeout/retry machinery exists in the tree."

### 3.（P2）第一稿的 await 守卫 rationale 被重写稿丢掉 — 建议一句话写回

第一稿在 Terminal-history precheck 处有："The unmatched-await guard is log-only and does not require P03 side tables. In a normal P03 wait, jobs would be `WAITING` and therefore could not pass the live-claim precheck; this guard catches malformed/manual state." 现行计划只剩条件本身（"unmatched while jobs is nevertheless RUNNING"），没有为什么该状态只可能是畸形状态的论证。

已对照 0003 验证该论证成立：`await_event` 的挂起路径原子转 `WAITING` 并清空 token（0003:227-242），立即命中路径同时追加 `run/await` 与配对 `run/wake` 且保持 `RUNNING`（0003:271-295）；`emit_event` 唤醒时先追加 `run/wake` 再转 `PENDING`（0003:428-448）。因此 P03 自身流程不可能产生「RUNNING 活 claim + 未配对 await」——守卫零误报，只拦手工/损坏状态。这一句是实现者判断守卫严格性（是否会误杀合法历史）的关键依据，值得写回。

### 4.（P2）并发误用下的异常传播契约被重写稿丢掉 — 建议钉死

第一稿明确："The only exceptions that propagate directly are malformed scalar function parameters and unhandled database invariant violations such as a duplicate LLM insert caused by concurrent use of one token." 现行计划只在 Duplicate-operations 表里说 "P05 does not promise graceful multiwriter arbitration"，未写明**具体行为**：两个执行体共用一个 token 并发进入 checkpoint-miss 分支时，后者的 `llm` append 会命中 `agent_steps_llm_step_idx` 唯一索引（0002:36-38），23505 **原样抛出**，不转换为 P05 错误事件、不返回 `fail`/`lost_claim`。

不钉死这一条，实现者可能顺手把 unique_violation 兜进 `P05_LLM_INVOCATION_FAILED` 之类的终态错误——那会把调用方违约静默变成 run 级终态失败，与「误用是调用方错误」的决定 19 矛盾。一句话写进 Errors and edge cases 的 "Duplicate execution with one token" 小节即可。

### 5.（P2）守卫触发的 `P05_WAIT_UNSUPPORTED` 的 envelope step_name 未写明（两文皆缺）

Terminal error payload 节说 envelope step_name 为 "the active `s-N` when known; SQL NULL for job configuration failures discovered before step selection"。但 unmatched-await 守卫也在 step selection **之前**触发（Terminal-history precheck 先于 Configuration validation），此时没有 active step；文本只点名了 config 失败一类。同一错误码在 wait 决策分支触发时则有 active `s-N`。写明：守卫路径的 `P05_WAIT_UNSUPPORTED` 用 SQL NULL envelope step_name，决策分支用当前 `s-N`——否则 `test_p05_wait_action_fails_without_waiting` 与守卫测试的断言可能相互打架。

### 6.（P2）`emit_step_claimed` 的六参调用形未在计划中出现（第一稿有）

第一稿写出了完整调用形 `emit_step_claimed(claim_token, run_id, 'llm', payload, step_name, extend_seconds)`；重写稿与现行计划只在 P02 Background 里描述行为，从未给出参数顺序。已核实实际签名为 `(p_claim_token uuid, p_run_id text, p_kind text, p_payload jsonb, p_step_name text DEFAULT NULL, p_extend_seconds integer DEFAULT 90) RETURNS boolean`（0002:72-79）。计划对自己新增的两个函数都钉到 catalog identity 级别，对唯一的写路径却不给调用形，不对称；补一处即可。

### 7.（P2 · 问题）损坏 await 历史与 wait 决策共用 `P05_WAIT_UNSUPPORTED`，是否应区分？

守卫路径（RUNNING + 未配对 await = 历史损坏/手工干预）与 wait 决策路径（mock 决策要求等待 = P05 不支持的功能）是两种完全不同的病因，计划让它们共用一个错误码。日志消费者与测试无法从 `code` 区分二者（只能靠 message/step_name 推断）。备选：守卫路径改用已有的 `P05_INVALID_HISTORY`（语义即「畸形乱序历史」，零新码）。答案只影响错误分类与一个测试断言，不影响执行顺序；两个方向都可接受，但计划应显式二选一，避免实现与测试各自发挥。

### 无需行动的记录

- 第一稿把 hook 返回非对象映射为 `P05_INVALID_LLM_DECISION`，重写稿/现行计划映射为 `P05_LLM_INVOCATION_FAILED`（Component 4 checkpoint-miss 第 3 点 "the same failure code"）。现行计划自洽，无需改；但 W58 的 "malformed response" 测试必须对准 `P05_LLM_INVOCATION_FAILED`，不要照第一稿写。
- 指纹的 history 元素内嵌绝对 `seq`（跨 run 共享的 bigserial）。核实过：指纹只在同一 run 的 resume 边界内比较，且 hit 边界 `seq < checkpoint.seq` 精确重建 miss 时点的折叠集（同一 claim 内 `llm` 是该步首个 append），回滚造成的 seq 空洞不影响已提交行的重读。跨语言重建已由 Tradeoff 8 声明为 P10 问题，无需改。

---

## 已核实断言（抽查记录）

- P01：`claim_job(text,text,integer DEFAULT 90) RETURNS SETOF cordis.jobs`、`yield_claim(uuid)`、`complete_claim(uuid, jsonb DEFAULT NULL)`、`fail_claim(uuid, jsonb NOT NULL)`，全部以 token + `RUNNING` + 未过期为栅（0001:117-282）；`release_stale` 转 PENDING 且 `attempt+1`（0001:89-113）；默认 90 秒租约；`payload jsonb NOT NULL DEFAULT '{}'`（0001:8）——计划 "SQL NULL jobs.payload is prevented by P01" 成立。
- P02：kind CHECK 白名单含 `llm/tool/final/error/run/*/spawn/*/event/emit`（0002:14-27）；step_name presence 只约束 `llm`/`tool`，format CHECK 允许任何 kind 携带合法 `s-N`（0002:28-33）——P05 给 `final`/`error` 带 envelope step_name 合法；llm 唯一部分索引（0002:36-38）；`emit_step` 是唯一直插（0002:64-66）；`emit_step_claimed` 的 `GREATEST` 只延不缩、null token 返回 false（0002:118-144）；`next_step_name` 未完成续传/`s-(max+1)` 前进（0002:279-333）；`llm_checkpoint` 返回整行或空（0002:335-364）。
- P03：`run_state` 覆盖版优先级 final > error > awaiting > in-progress，await/wake 按 `await_id` + `seq >` 配对（0003:496-521）——计划的终态优先级与守卫可实现性成立；`await_event` 挂起原子转 WAITING、立即命中保持 RUNNING 并成对追加 await+wake（0003:227-295）。
- 版本/目录：0006 尾部版本函数 + `SELECT cordis.refresh_plugins();` 模式（0006:771-779）；`KERNEL_FUNCTIONS` 19 项（test_p00:23-43），`cordis.invoke_llm` 插于 `get_schema_version` 与 `llm_checkpoint` 之间、`cordis.step_once` 插于 `run_state` 与 `unregister_host_plugin` 之间，与计划投影一致；文件清单断言（test_p00:54-60）与计划改法吻合。
- 测试名：`test_fresh_apply_lists_current_tree_and_p06`（test_p00:46）、`test_reserved_waiting_sleeping_not_claimed`（test_p01:413）、`test_p02_crash_shaped_next_step_name`（test_p02:437）、`test_p02_source_tree_append_monopoly`（test_p02:896）、`test_p03_no_second_queue_notify_or_direct_log_insert`（test_p03:1215）全部存在；`--sql-root` 截断树模式已在 test_p02 使用（:80）。
- W 编号：P03 计划 `:48` 同时载明 P03 W27–W33 与 P06 W60–W66；P04 计划 `:61` 载明 W34–W41；`W50`–`W59` 无冲突。

---

## P0 / P1 / P2 清单

- **P0：无。**
- **P1：**
  1. file:line 表行号修正（发现 1，按表逐条替换）。
- **P2：**
  2. "P04 is scaffold-only" 改为「深计划已就绪、实现未落地」（发现 2）。
  3. 写回 await 守卫零误报 rationale 一句（发现 3）。
  4. 钉死并发单 token 误用下 unique_violation 原样抛出、不转 P05 错误事件（发现 4）。
  5. 写明守卫路径 `P05_WAIT_UNSUPPORTED` 的 envelope step_name 为 SQL NULL（发现 5）。
  6. 补 `emit_step_claimed` 六参调用形一处（发现 6）。
  7. 显式二选一：守卫路径错误码沿用 `P05_WAIT_UNSUPPORTED` 或改 `P05_INVALID_HISTORY`（发现 7）。

## 裁决

**可以进入 ready to implement**：无 P0；唯一 P1 是计划自增核对表的行号修正，属纯文本更正，不触及设计、接口、错误语义或实现顺序；P2 全部为一两句话的钉子。把 P1 修掉（P2 建议顺手折进）后，现行 Status `ready to implement` 即可站住。基线保留维度（用户任务的核心关切）已用逐行 diff 证明干净。
