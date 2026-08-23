# I — pg_cordis 架构探索收尾（工作假设快照）

Date: 2026-08-23  
Status: **探索结束。** 用户已签名的合同 + 系列收敛后采纳的工作假设。A–H 仍是证据，不再当待决架构分叉。  
决定源: `docs/decisions/2026-08-23-pending.md`  
愿景裁决: `docs/analysis/2026-08-23-h-vision-d1-d9-oracle-verdicts.md`

本文件**不**实现内核、**不**把一步驱动移出 scratch。那是下一阶段（实现）的第一刀。

---

## 1. 系列怎么读

| 文 | 问的是什么 | 收尾后的地位 |
|----|------------|--------------|
| A | DSH 插件如何迁到 pg_cordis（迁角色，不复用 TS） | SQL-first、动态代码推迟、UI 在核外：采纳 |
| B | session log 为唯一真相；投影怎么分层 | log SoT 已锁；workspace 第三态见 §3 |
| C | CodeAct 与 RLM 共存 | 核 = loop 基座；范式 = 政策包。CodeAct 主体 |
| D | 隔离 ≠ Zleap workspace | 切片 grant 已签名（D5） |
| E | Absurd 耐久执行 | 升格 `jobs`，不第二队列；五件套进核（D4） |
| F | yield-loop 协议草图 | 协议有效；TE1 放置已由 D4 闭合 |
| G | `rlm_step_once` 一步驱动 | scratch 9/9 证明三步=三次 claim；仍非产品 SQL |
| H | 宏观愿景 vs D1–D9 | 九条已签名 |

对照：Kimi「机制学 DBOS、形态学 absurd」；oracle Q1–Q4；scratch `scratch/yield_walkthrough/REPORT.md`。

---

## 2. 产品形状

**先做** RepoPrompt-CE 类编码 agent。workspace、Context Builder、selection（full/slice/codemap）、worktree、`apply_edits` 都是 **pg_cordis 插件**，改已有文件。

**后做** DuckDB 2.0 数据分析插件，造新表。InfiniSynapse 逆向和 pg-agent TEMP VIEW / DA SQL 是探索，不是运行时。

两者在同一核上协调：log、claim、grant、spawn、插件目录。

**范式：** CodeAct 为主体（一步 = 一次 LLM + 它的 tools）。RLM 取 prime-agent 形态：持久控制环境 + `rlm()` 只返回 admission handle，孩子异步。

**独特能力：** 提示词由检索出的片段组合。工作例「项目 A 做功能 1，项目 B 做功能 2 和 3」靠 **slice 绑定的 named_corpus grant**，不能靠 workspace 并集。

---

## 3. 分层

```text
                    用户 / 受信宿主签发 grant
                              │ 模型只能申请
                              ▼
┌─────────────────────────────────────────────────────────┐
│ pg_cordis 核（Postgres，本仓库 SQL 源，暂不 EXTENSION）   │
│  jobs + 一套 claim     agent_steps 唯一历史真相            │
│  checkpoint ⊂ log      sleep / scoped event / retry       │
│  run_waits / run_events（旁表，服务同一队列）              │
│  grant 登记 + 切片绑定   插件目录（locus / grant / 分类）   │
└────────────┬──────────────────────────────┬─────────────┘
             │ 同一 claim 协议               │
     ┌───────▼───────┐              ┌───────▼───────┐
     │ 库内 worker    │              │ 宿主 SDK worker │
     │ SQL 一步驱动   │              │ 文件 / worktree │
     └───────────────┘              └───────┬───────┘
                                            │
         范式插件（政策包）          工作台插件（substrate）
         CodeAct | RLM               编码: Git worktree（改旧文件）
         prompt fold 是投影          DA: DuckDB（造新表，后做）
```

三态（采纳 D 文 P0，修正 B「此外皆投影」的过宽表述）：

| 态 | 是什么 | 例子 |
|----|--------|------|
| **log** | 历史真相，append-only | `agent_steps` |
| **projection** | 派生，永不权威 | `run_state()`、按范式的 prompt fold、监督视图 |
| **workspace** | run 拥有的执行态，非历史、跨 run 不可读 | grant/selection 登记、`rlm_vars`、worktree 绑定、（后做）DuckDB 清单指针 |

分析中间表 **不是** PG workspace。它们活在 DuckDB 插件里；PG 只存可回放的定义/血统指针。

---

## 4. 用户已签名的合同

来自 pending「已锁定」+ D1–D9。不要在实现里重开。

| 项 | 合同 |
|----|------|
| SoT | `agent_steps` 唯一历史真相；Zleap 产品表不当核 |
| 插件 | SQL/PL/pgSQL-first；DSH **迁角色不复用 TS** |
| 队列 | 升格 `jobs`/`worker()`，禁止第二套 Absurd 队列 |
| Worker | 库内和宿主同一套 claim |
| Checkpoint | ⊂ log |
| Yield | 默认一步 = 一次 LLM + 它的 tools |
| LLM 幂等 | `Idempotency-Key = H(run_id, step_name)` + log 有该步则跳过 HTTP。**不管 tool** |
| 事件 | 能力在 `(event_scope_id, name)`；前缀只是存储 |
| D1 | 退役 `pg_temp` DA。DuckDB 插件后做。PG 只留协调态。禁止亲和会话 |
| D2 | A+C：只读可重跑；非 PG 事务先 `tool/call` 再副作用再 `tool/result`。文件编辑/未来 DuckDB 相对 claim 都是非事务 |
| D3 | `jobs` 调度；`run_waits`/`run_events` 旁表 |
| D4 | 五件套进核：claim、checkpoint、sleep、scoped event、任务级 retry。habitat/SDK 非核 |
| D5 | v0 枚举 `run` / `named_corpus:<id>` / `event:<scope>`；**按 slice 生效**；**模型只能申请**；用户或受信宿主签发。禁止 SQL 谓词和 `run_id` 顶替 |
| D6 | v0 只有步数/深度/扇出硬顶（depth 4、16 子、child `LEAST(parent,6)`、map ≤8），**admission 时检查** |
| D7 | SQL 源在本仓；pg-agent 测试床；先不 `CREATE EXTENSION`；插件不是各自扩展 |
| D8 | 最小 SQL 动词 + 插件目录。不做 DSH 迁移器 / 事件兼容层 / `node:vm` |
| D9 | 子 run **一律 enqueue**，返回 admission handle。一步内 tools 不是 spawn |

---

## 5. 系列收敛后采纳的工作假设

下面 **没有** 单独投票，但与签名不冲突，且 A–E 意见一致。实现按此走；要改必须显式修订 pending。

### 插件与核（A）

- **T1** 作者面：`COMMENT` JSON 为源，`refresh_*()` 编进登记表。
- **T2** 元数据一天齐，执行力渐进（结构先校验，依赖排序后做）。
- **T3** 库内效果靠事务可逆；库外效果（HTTP、文件）走 D2 call/result，不发明第二套补偿账本当核。
- **T4** 动态插件推迟；与 D8 一致。
- **T6** UI/浏览器半边在核外，只定义可观察投影。
- **T7** 一套元数据，`invocation = queue | session_select`（或 host-tool）；每对象互斥。
- 循环：**核是 loop 基座**（claim、fold 消费、LLM 传输、预算、spawn 管道、工具渲染）；**范式是政策包插件**（prompt、parser、动作路由、env 政策、观察截断）。CodeAct 与 RLM 登记为两份政策，不是两套循环引擎。

### 日志与投影（B）

- **TB1** 类型化信封 + JSONB payload；插件 kind 不靠 DDL。
- **TB2** 按事件提交，中断用 closer 修补；不按整 turn 回滚丢掉已生成内容。
- **TB3** 结构用约束，语义用 append 路径校验函数。
- **TB4/TB5** 两层投影：确定折同步一致切；模型折异步、声明 `asOfSeq`。
- Prompt 组装是 **投影**（每范式一份 fold），且必须按 **调用 slice 的 live grants** 过滤；禁止把 run 上全部 grant 并进每一次 fold。
- Compaction 是投影/插件，不是 loop 内核私货。
- 多写者 append：能力门禁 + 同 session 串行事务。

### 范式（C）

- v0 CodeAct 动作面 = **结构化工具**（CE 的 search/read/`apply_edits`），不是库内任意代码。T4 解禁前不做 in-DB 自由程序。
- RLM 的 REPL 是表（`rlm_vars` 等 workspace），不是钉会话的 `pg_temp`。
- Spawn 谱系写 log（`spawn/start` / `spawn/end`），禁止 `created_at DESC` 回填孩子。
- 子 run 继承的是 **named grants + question**，不是父 env 全量。

### 隔离（D，P1–P8 中已由 D5/D2/D8 覆盖的）

- Grant 登记是 **核**（与 `emit_step` 写垄断同级）：每个检索缝（recall、fold、env 读、工具分派）都必须强制 slice 绑定。半套强制不得对用户暴露。
- 能力靠 role + RLS + 钉住的 `search_path` + session 类型；关键字黑名单最多算卫生，不算安全。
- 模型写的 SQL / 宿主工具都在 grant 里跑。

### 耐久（E/F）

- F 的 claim 动词、状态机、失败时序仍有效。
- Wait：先写 `run/await`（或 sleep）进 log，**同一事务**登记旁表、把 jobs 标不可认领、放租约。
- 事件 first-write-wins；先 emit 后 wait 仍能看见。
- Retry **状态机**在核；**曲线**是范式/插件参数。

---

## 6. 分析遗留问题对照

A–E 文末的 open questions，收尾后只剩实现细节或明确延期。

| 来源 | 原问题 | 收尾 |
|------|--------|------|
| A T4 / D8 | 动态 `node:vm` / in-DB 不信任代码 | **延期**。隔离是前置，v0 不做 |
| A T5 | EXTENSION vs SQL 目录 | **D7**：先本仓 SQL |
| A 循环插件还是核 | | **核 + 范式政策包** |
| A 递归是否绕过事件 | | **否**；D9 + spawn log |
| A Σ^iso → schema/RLS/search_path | | **三层都用**，grant 来选 |
| B SessionPersistence API | | **D8** SQL 动词吸收；JSONL 不当核 |
| B torn-tail | | WAL + 事件级 closer |
| B prompt 是不是投影 | | **是**，且 grant 过滤 |
| B `rlm_vars` 第二 SoT | | **workspace 第三态**，D1 |
| B 多写者 | | 能力 + 串行事务 |
| B 遗忘/TTL | | **仍开**：遗忘默认只在投影；log 修剪另议 |
| C 黑名单不够 | | P2：role/RLS/search_path |
| C 子 agent 继承 | | slice grants，D5 |
| C 异步孩子在哪跑 | | D9 jobs，任意 worker |
| C 预算池还是块 | | **D6** v0 不做费用池 |
| D 语法/签发 | | **D5 已拍** |
| D grant 核还是插件 | | **核** |
| D RLS 性能 | | **仍开**（优化，不当真相） |
| D corpus 快照/撤销 | | **仍开**，不挡 v0；偏安=整根 named_corpus、run 期内不静默扩权 |
| E yield 边界 | | Q1 混合 D |
| E LLM 幂等 | | Q2 A+B |
| E 事件名 vs grant | | Q3 |
| E TE1 放置 | | **D4 闭合** |
| F 数字阈值 | | **D9** 一律异步 |
| G TEMP 跨 yield | | **D1** 退役该路径 |

---

## 7. 编码 agent v0（探索结论里的实现范围）

做：

- 五件套核 + 旁表 + 插件目录 + grant 登记
- 宿主最小 seam：claim / checkpoint / yield / sleep / await / 查目录
- workspace / selection / context-builder / path-fenced `apply_edits` 插件
- CodeAct 一步一 claim；RLM/context-builder 孩子一律 enqueue
- D5 工作例必须在 recall **和** fold 上都不串切片
- D2 给每个一类工具标 effect/retry class

必须先证明（H 文五条）：

1. 两个 worker 交替认领同一次编码 run
2. 宿主文件 mutation 能 call/result 恢复，无未分类双写
3. 项目 1 / 项目 2 三功能例零泄漏
4. 子 agent 返回 handle，事后交结果
5. 先 emit 再 wait、重复事件、retry、租约过期仍是一条队列

**一步驱动 SQL 留在 `scratch/yield_walkthrough/`。** 证明不是产品。规范源按 D7 另建，不要把 scratch 假设抬成 ABI。

---

## 8. DuckDB 插件（以后，不是核）

做：每 run/task 一个 DuckDB；`SELECT … AS` 造表；定义+血统可回放；父子 merge；产物归档；按 D2 分类工具。

不做：第二队列、第二 claim、钉 PG 后端、把 `plugin_temp_views.sql` 迁进核、DuckDB 单独 EXTENSION、同步 RLM 子树、与 PG claim 假装 2PC（没有跨库原子协议之前，DuckDB mutation 相对 claim 是非事务）。

---

## 9. 明确不做

- Zleap workspace 当隔离模型；Zleap 产品表当核
- DSH TypeScript 当运行时；动态 `node:vm`
- `CREATE SCHEMA absurd` / 第二队列 / `c_` 表当真相
- 钉同一 PG 后端用 TEMP 当 REPL
- 模型自己写 grant；SQL 谓词 grant；run 级 grant 并集检索
- token/费用共享池（v0）
- 现在就 `CREATE EXTENSION pg_cordis`
- 厚宿主 SDK / DSH 事件兼容层 / 插件迁移器
- 同步 `rlm_loop(child)`

---

## 10. 仍开（实现时定，不是架构分叉）

1. 本仓规范 SQL 目录和文件名（D7 布局已定，具体路径未定）
2. `jobs` / `run_waits` / `run_events` 精确 DDL、锁序、payload 是否在旁表缓存
3. 插件目录字段名；宿主 SDK 第一种语言
4. 每个宿主工具的 operation-id 与 indeterminate 用户可见态
5. `named_corpus` 是否带版本；撤销对进行中 prompt 的影响
6. RLS/pgvector 计划时强制 vs 物化优化
7. log 分区/GDPR 修剪是否合法
8. checkpoint 里 delta vs workspace 里全文的分割
9. 观察性：v0 是否只要 `run_state()` + 查 log，habitat 类 UI 以后再说

---

## 11. 探索到此结束

架构分叉已经关了。实现骨架（一条一个未来 deep plan）：`docs/plans/2026-08-23-pg-cordis-development.md`。

建议顺序（摘录；并行与验收以计划文为准）：

1. 按 D7 建本仓规范 SQL 源（与 scratch 分开）。
2. 五件套 + D3 旁表 + 原子 wait/wake。
3. 插件目录 + grant 登记；四个缝同时强制切片绑定。
4. 最小宿主 seam；双 worker 交替认领。
5. 编码 workspace / context / `apply_edits` 插件；跑 D5 工作例。
6. D2 工具恢复。
7. D9 spawn（admission handle + 事后结果）。
8. DuckDB 插件另开一轮。

修订规则：改 §4 必须在 pending 该条下追加「修订」。改 §5 在本文件追加修订并说明与签名的关系。不要改写 A–H 正文。
