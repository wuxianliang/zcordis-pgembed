# pg_cordis 开发计划（骨架）

Date: 2026-08-23  
Status: **骨架，不是 deep plan。** 每条以后单独写详细 deep plan。  
合同: `docs/decisions/2026-08-23-pending.md`  
架构: `docs/analysis/2026-08-23-i-architecture-snapshot.md`  
协议: `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md`  
一步驱动草图: `docs/analysis/2026-08-23-g-rlm-one-step-driver.md`（语义参考；**禁止**把 `scratch/yield_walkthrough/` 抬成 ABI）

以后每条的 deep plan 建议路径：`docs/plans/Pxx-<slug>.md`，文首引用本文件的 **Pxx**。

---

## 怎么用这份文件

- **顺序**：编号是推荐撰写/开工顺序。有硬依赖的，先写完依赖项的 deep plan 再写下一项。
- **并行**：条目标了「可与 … 并行」。无依赖交叉的 deep plan 可以同时写、同时做。
- **一条 = 一次 deep plan**。不要把并行的两条合成一篇。
- **不重开** D1–D9 和快照 §4。条内只拍实现细节（DDL、文件名、语言）。
- **现在不** `CREATE EXTENSION`，**不**编进 pgembed 认证表。那是核稳定后的发行步，不在 P00–P19 里。
- **P20** 是数据分析另轮，不挡编码 agent v0。

当前进度：**P00 已实现**（`docs/plans/P00-sql-source-2026-08-23.md`；schema 为 `cordis`，因 PostgreSQL 禁止 `pg_` 前缀）。下一项可写/做 **P01**。

---

## 总图

```text
P00 规范 SQL 源
 ├─ 核（可与目录/grant 表结构并行）
 │    P01 claim ──┐
 │    P02 log  ───┼─► P03 wait/event ─► P04 sleep/retry
 │                └─► P05 一步驱动（可先 stub wait）
 ├─ 目录与隔离（P00 后即可与 P01 并行）
 │    P06 插件目录 ─► P07 grant 登记 ─► P08 四缝强制
 │    P19 范式政策包（可与 P07 并行，P06 之后）
 ├─ 双 worker
 │    P09 库内 worker ──┐  （P05+P06 之后；二者并行）
 │    P10 宿主 seam  ───┴─► P11 交替认领证明
 ├─ 编码插件（P10 之后）
 │    P12 worktree ┐
 │    P13 selection┤ 并行
 │                 ├─► P14 apply_edits ─┬─► P16 D2 恢复
 │                 └─►                 └─► P15 D5 工作例（还要 P08）
 ├─ 子 run
 │    P17 异步 spawn（P03+P04+P09）─► P18 context-builder 子 run
 └─ 另轮
      P20 DuckDB 插件（最早 P11 之后；产品上建议 P15 之后）
      ── 更后：CREATE EXTENSION / 编进 pgembed（无编号，见文末）
```

五条必须证明（写入相关条的验收，不要另开一条）：

| 证明 | 最早落在 |
|------|----------|
| 两个 worker 交替认领同一次编码 run | **P11** |
| 宿主文件 mutation 能 call/result 恢复 | **P16** |
| 项目 1 / 项目 2 三功能零泄漏（recall **和** fold） | **P15** |
| 子 agent 返回 handle，事后交结果 | **P17**（P18 用它） |
| 先 emit 再 wait、重复事件、retry、租约过期仍一条队列 | **P03 + P04** |

---

## 一览

| ID | 标题 | 硬依赖 | 可并行 |
|----|------|--------|--------|
| P00 | 本仓规范 SQL 源与安装路径 | — | —（一切之始） |
| P01 | `jobs` 升格与 claim 协议 | P00 | P02、P06 |
| P02 | `agent_steps` 日志与 checkpoint⊂log | P00 | P01、P06 |
| P03 | `run_waits` / `run_events` 与原子 wait/wake | P01、P02 | P06、P07、P19 |
| P04 | sleep 与任务级 retry 状态机 | P01、P03 | P06、P07、P19 |
| P05 | 一步驱动 + LLM 幂等 A+B | P01、P02 | P03（先 stub wait）、P06、P19 |
| P06 | 插件目录 | P00 | P01、P02 |
| P07 | Grant 登记（C + 模型只能申请 + slice） | P06 | P03、P04、P05、P19 |
| P08 | 四缝强制隔离 | P02、P05、P07 | P09、P10 |
| P19 | CodeAct / RLM 范式政策包 | P06 | P07、P05 |
| P09 | 库内 worker | P05、P06 | P10 |
| P10 | 宿主最小 SQL seam | P05、P06 | P09 |
| P11 | 双 worker 交替认领证明 | P09、P10 | — |
| P12 | Workspace / worktree 插件 | P10 | P13 |
| P13 | Selection 与 prompt 组装 | P10、P07 | P12 |
| P14 | `apply_edits` 与路径围栏 | P12 | P13 若已完成 |
| P15 | D5 工作例 | P08、P13 | P16、P14（读路径可先于写） |
| P16 | D2 工具 call/result 恢复 | P06、P14 | P15 |
| P17 | D9 异步 spawn | P03、P04、P09 | P16 |
| P18 | Context Builder 作为子 run | P13、P17 | — |
| P20 | DuckDB 数据分析插件（另轮） | P11（核+目录能登记插件） | 不与 P12–P18 抢第一版 |

---

## P00 — 本仓规范 SQL 源与安装路径

- **依赖：** 无  
- **可并行：** 无（先做）  
- **合同：** D7  
- **拍什么（deep plan 里定）：** 目录名、文件切分、如何 APPLY 到 pgembed、与 scratch 的隔离规则  
- **做：** 在 `zcordis-pgembed` 建规范 `.sql` 树（不是 `scratch/`）。一条安装命令能在 pgembed 上 APPLY。pg-agent 只当测试床，不把合同写进 pg-agent 仓。  
- **不做：** `CREATE EXTENSION`；编进 pgembed `bundle-metadata.json`；搬迁 scratch 当产品文件。  
- **完成：** 空核也能干净安装/再装；后续 Px 只往这棵树加文件。

---

## P01 — `jobs` 升格与 claim 协议

- **依赖：** P00  
- **可并行：** P02、P06  
- **合同：** 一条队列；双 locus 同一 claim；F 草图 §3/§11  
- **拍什么：** `claim_token`、`available_at`、状态名、租约时长、SKIP LOCKED 细节  
- **做：** 升格现有 `jobs`/`worker()` 语义：claim / renew / yield / complete / fail。权威 claim 在 jobs 行，keyed by `run_id`。  
- **不做：** 第二队列；`CREATE SCHEMA absurd`；wait 旁表（P03）；一步循环体（P05）。  
- **完成：** 两个连接能互斥认领；yield 后另一连接能再认领。

---

## P02 — `agent_steps` 日志与 checkpoint⊂log

- **依赖：** P00  
- **可并行：** P01、P06  
- **合同：** log 唯一历史真相；checkpoint 是 log 事件/折叠  
- **拍什么：** 信封列、kind 词表、`emit_step` 写垄断、seq  
- **做：** append-only 日志；`run_state()`；命名步 `s-N`；skip-if-present。  
- **不做：** 独立 `c_` 真相表；投影当 SoT。  
- **完成：** 三步历史可折叠；崩溃后能从 log 判断下一步名字。

---

## P03 — `run_waits` / `run_events` 与原子 wait/wake

- **依赖：** P01、P02  
- **可并行：** P06、P07、P19  
- **合同：** D3；事件能力 `(event_scope_id, name)`  
- **拍什么：** DDL、锁序、first-write-wins、payload 是否旁表缓存  
- **做：** 同一事务：写 `run/await`（或 sleep 意图）→ 登记旁表 → jobs 不可认领 → 放租约。先 emit 后 wait 仍可见。重复事件/重复 wait 有定义。  
- **不做：** `LISTEN/NOTIFY` 当正确性；第二队列。  
- **完成：** 先 emit 再 wait、重复 emit、租约过期，仍一条 jobs 队列。

---

## P04 — sleep 与任务级 retry 状态机

- **依赖：** P01、P03  
- **可并行：** P06、P07、P19  
- **合同：** D4（五件套进核）；retry **状态机**在核，**曲线**可参数化  
- **拍什么：** 默认 backoff、最大次数、死信名  
- **做：** `SLEEPING` + `available_at`；attempt / 下次可认领 / 终态失败。  
- **不做：** 把插件各自的重试曲线写进核；habitat UI。  
- **完成：** 失败步按状态机再入队；超限终态；与 P03 一起覆盖「retry + 租约过期」证明。

---

## P05 — 一步驱动 + LLM 幂等 A+B

- **依赖：** P01、P02  
- **可并行：** P03（wait 可 stub）、P06、P19  
- **合同：** Yield 混合 D；LLM `Idempotency-Key = H(run_id, step_name)` + log 有该步则跳过 HTTP  
- **拍什么：** 函数名（`rlm_step_once` 是否改名）、与 G 草图的差异清单  
- **做：** 把 G/scratch **语义**迁进 P00 树：一 claim = 一 LLM + 其 tools（当时已有的工具面），然后 yield。禁止搬 scratch 文件当 ABI。  
- **不做：** 同步子树；TEMP VIEW；真 LLM 之前可用 mock。  
- **完成：** 规范源上复现「三步 = 三次 claim」（可仍 mock LLM）。

---

## P06 — 插件目录

- **依赖：** P00  
- **可并行：** P01、P02  
- **合同：** D8；T1 COMMENT→refresh 进表  
- **拍什么：** 字段名：identity、version、locus（in-db / host）、required grants、effect class、retry/reconciliation  
- **做：** 一套元数据，`invocation` 可区分 queue / host-tool。登记、查询、互斥规则。  
- **不做：** 动态 `node:vm`；DSH 迁移器；每种插件一个 EXTENSION。  
- **完成：** 能插入一条宿主工具描述并被 SQL 查出。

---

## P07 — Grant 登记

- **依赖：** P06  
- **可并行：** P03、P04、P05、P19  
- **合同：** D5：`run` / `named_corpus:<id>` / `event:<scope>`；按 **slice**；**模型只能申请**；用户或受信宿主签发  
- **拍什么：** 表结构；申请 vs 签发 API；run 期内是否冻结 corpus（偏安：整根、不静默扩权）  
- **做：** grant 写进库的只有用户/受信宿主。模型申请不被自动批准。绑定到 slice，不是 run 并集。  
- **不做：** SQL 谓词 grant；`run_id` 顶替隔离；结构化描述符 A。  
- **完成：** 能签发两个 named_corpus 到不同 slice；模型申请保持 pending。

---

## P08 — 四缝强制隔离

- **依赖：** P02、P05、P07  
- **可并行：** P09、P10  
- **合同：** D5；快照「半套强制不得对用户暴露」  
- **拍什么：** 每个缝的失败模式；测试夹具（泄漏用例）  
- **做：** recall、fold、env 读、工具分派 **同时**按调用 slice 的 live grants 过滤。  
- **不做：** 只在 recall 上过滤却把另一项目写进 fold。  
- **完成：** 泄漏测试红/绿；未齐四缝则功能关闭。

---

## P19 — CodeAct / RLM 范式政策包

- **依赖：** P06  
- **可并行：** P07、P05  
- **合同：** CodeAct 主体；RLM 取 prime-agent 形态；核是 loop 基座  
- **拍什么：** 政策包行里有哪些字段（prompt、parser、观察截断、env 政策）  
- **做：** 两份登记。CodeAct = 结构化工具一步。RLM = 环境里的变量 + 异步孩子（孩子执行在 P17）。  
- **不做：** 两套循环引擎；同步 `rlm_loop(child)`。  
- **完成：** 一步驱动能按 `paradigm` 选政策，而不 if-else 冻死在核里。

编号在 P08 之后是为了 deep plan 撰写可插在目录之后、四缝之前或同时；**不是**等 P08 做完才登记范式。

---

## P09 — 库内 worker

- **依赖：** P05、P06  
- **可并行：** P10  
- **合同：** 双 locus 同一 claim  
- **做：** 规范源里的 `worker_step`：claim → 一步 → yield/wait/complete。只跑标了 in-db locus 的工具。  
- **不做：** 文件编辑；钉会话 TEMP。  
- **完成：** 单 worker 能把 mock 编码/只读步进到 yield 再认领。

---

## P10 — 宿主最小 SQL seam

- **依赖：** P05、P06  
- **可并行：** P09  
- **合同：** D8  
- **拍什么：** 第一种 SDK 语言（实现时定）  
- **做：** 薄封装：claim / checkpoint / yield / sleep / await / 查目录。同一 provider 幂等键规则。  
- **不做：** 厚 SDK；DSH 事件兼容层；UI。  
- **完成：** 宿主进程能认领并写回一步 log（工具面可先只读）。

---

## P11 — 双 worker 交替认领证明

- **依赖：** P09、P10  
- **可并行：** 无  
- **证明 1**  
- **做：** 同一次 run：库内一步、宿主一步、再库内一步（或相反）。租约过期由另一方接走。  
- **不做：** 功能插件。  
- **完成：** 自动化测试 证明 1 绿。

---

## P12 — Workspace / worktree 插件

- **依赖：** P10  
- **可并行：** P13  
- **合同：** 编码 substrate = Git worktree（改旧文件）；D1（PG 不放分析表）  
- **做：** per-run worktree 绑定、路径沙箱、清单进 PG workspace 态。  
- **不做：** merge-back 完整状态机可第二篇 deep plan，但本条至少有隔离 checkout。  
- **完成：** 宿主工具只碰绑定 worktree 内路径。

---

## P13 — Selection 与 prompt 组装

- **依赖：** P10、P07  
- **可并行：** P12  
- **合同：** full / slice / codemap；prompt 是投影且 grant 过滤（P08 齐之前不得对用户开检索）  
- **做：** StoredSelection 同类登记；snapshot 组装。slice 带 grant。  
- **不做：** Context Builder 子 agent（P18）。  
- **完成：** 能按两个 named_corpus 装两段不同 selection。

---

## P14 — `apply_edits` 与路径围栏

- **依赖：** P12  
- **可并行：** P13 已完成时  
- **合同：** 非 PG 事务性宿主 mutation  
- **做：** 路径围栏、operation-id 相关、审批挂钩可最小。真正的 call/result 恢复在 P16。  
- **不做：** 假装与 claim 同事务提交。  
- **完成：** 围栏外写入失败；围栏内一次编辑成功并可从 log 看到意图（P16 再补齐结果配对）。

---

## P15 — D5 工作例

- **依赖：** P08、P13（写路径还要 P14）  
- **可并行：** P16  
- **证明 3**  
- **做：** 「项目 A 做功能 1，项目 B 做功能 2 和 3」：recall **和** fold 都不串切片。  
- **不做：** 用 run 级 grant 并集顶替。  
- **完成：** 泄漏测试：功能 1 的 prompt 不含项目 B 检索/历史片段，反之亦然。

---

## P16 — D2 工具 call/result 恢复

- **依赖：** P06、P14  
- **可并行：** P15  
- **证明 2**  
- **合同：** A+C；文件编辑/未来 DuckDB 相对 claim 非事务  
- **做：** 只读可重跑；非事务先 `tool/call` 再副作用再 `tool/result`。call 无 result：可重跑则重跑，否则 indeterminate，禁止盲重放。  
- **不做：** 给 LLM HTTP 另搞一套（已是 A+B）。  
- **完成：** 在 call 之后、result 之前杀宿主，恢复行为符合分类。

---

## P17 — D9 异步 spawn

- **依赖：** P03、P04、P09  
- **可并行：** P16  
- **证明 4**  
- **合同：** 每个 spawn 新 jobs；admission handle；D6 硬顶在 admission 检查  
- **做：** 父请求 → 核 admission → 返回 handle → 父不等答案。结果：消息/文件/事后 wake。谱系写 `spawn/start`/`spawn/end`。禁止 `created_at DESC` 回填。  
- **不做：** 同步 `rlm_loop(child)`；一步内普通 tools 当 spawn。  
- **完成：** 子 run 独立被认领；父通过 wait 被唤醒；超深度/扇出在 admission 拒绝。

---

## P18 — Context Builder 作为子 run

- **依赖：** P13、P17  
- **可并行：** 无  
- **做：** Context Builder 是 enqueue 的子 run（可 RLM 政策），继承 named grants，不继承父 env 全量。  
- **不做：** 在父 claim 里同步跑完整个 builder。  
- **完成：** 父拿到 handle；子交回 selection/计划产物；父 fold 仍受自己 slice grant 约束。

---

## P20 — DuckDB 数据分析插件（另轮）

- **依赖：** 最早 P11（核+目录可用）；**产品建议** P15 之后  
- **可并行：** 不与 P12–P18 抢 v0  
- **合同：** D1；造新表；相对 PG claim 非事务（走 D2）  
- **做：** 每 run/task DuckDB；`SELECT … AS`；定义+血统在 PG workspace；可回放。  
- **不做：** `pg_temp`；第二队列；钉 PG 后端；单独 `CREATE EXTENSION`；与 claim 假装 2PC。  
- **完成：** 另写一轮计划；本骨架只占位。

---

## 不在本骨架内（核稳定之后）

下面 **不要** 提前插进 P00–P19：

1. `CREATE EXTENSION pg_cordis`（只包核，不包 workspace/DuckDB）  
2. 编进 pgembed（`pgbuild` + `bundle-metadata.json`）  
3. 热点路径改 C  
4. habitat / 厚 SDK / DSH 迁移器  
5. token 费用池  
6. 动态 in-DB 代码（T4）

发行包装是核 ABI 不再周周改之后的单独计划，仍只有 **一个** 数据库扩展。

---

## 建议的 deep plan 撰写批次

可一轮只写一篇；若要并行写稿，按批：

| 批次 | 写这些 | 为什么 |
|------|--------|--------|
| 1 | P00 | 没有树，后面无处落 SQL |
| 2 | P01 ∥ P02 ∥ P06 | 无互相依赖 |
| 3 | P03、P05、P07、P19 | P03 要 01+02；其余可并行 |
| 4 | P04、P08、P09 ∥ P10 | 四缝与双 worker 可交错 |
| 5 | P11 | 证明 1，关核里程碑 |
| 6 | P12 ∥ P13，然后 P14 | 编码 substrate |
| 7 | P15 ∥ P16 | 隔离工作例 + 文件恢复 |
| 8 | P17，然后 P18 | 子 run 与 context-builder |
| 9 | P20 | 另轮 DA |

从 P00 开始写详细 deep plan。
