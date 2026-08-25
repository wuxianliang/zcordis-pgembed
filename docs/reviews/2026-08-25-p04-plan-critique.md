# P04 计划评审 — 对照现行 p21 树与未过闸的实现 Oracle P1

Date: 2026-08-25
Scope: `docs/plans/P04-sleep-retry-2026-08-24.md`
Oracle: `untitled-chat-953DBF`，`mode: review`
Export: `prompt-exports/oracle-review-2026-08-25-235020-untitled-chat-953dbf-ea9e.md`

**Folded 2026-08-25:** 用户三问全选是。P1.1–P1.5 与 P2.1 已写入计划；Status 恢复 **ready to implement**。本笔记仍是当时的评审记录，不构成实现过闸。

对照基线：现行计划（已折入 `docs/reviews/2026-08-24-p04-plan-critique.md` 发现 1–6）对当前 **p21** 产品树，以及 `docs/reviews/2026-08-24-p04-implementation-oracle.md` 三轮未关的 P1。

定点核对：`sql/0001_p01_claim.sql`、`sql/0003_p03_wait_event.sql`、`sql/0021_p09_in_db_worker.sql`、`sql/README.md`、`tests/test_p00_sql_source.py`、`tests/test_p01_claim.py`、`tests/test_p09_in_db_worker.py`、P05/P09/P10 计划中的 P04 交接句。

不重开：D1–D9、快照 §4、四条 mid-flow 决定（默认 `max_attempts=3`；`sleep_claim(uuid,text,timestamptz,integer)`；`release_stale` 与 `fail_claim` 共享 attempt/退避/死信；死信 `reason` + `cause`）。本评审**不**构成 AGENTS.md 实现闸门第 4 轮，也不授权续审那条失败的实现聊天。

## 结论摘要

**当时裁决：计划尚未 ready。** 无 P0。五个 P1，一个 P2。随后用户拍板并已折进计划（见文首 Folded）。

sleep / due-sleeper claim / 同行重试 / 共享 attempt / 死信 / 一条 `jobs` 队列，作为核状态机仍然自洽，也没有碰到合同。挡住开工的是：计划仍按 **p06** 树写；deadline 顺序锁的死锁证明已被实现 Oracle 证伪；replay 没有钉 canonical catalog 比较；更关键的是，已经落地的 P09/P05 失败路径会先写 `error` 再调 `fail_claim`，按现行默认重试会得到 `jobs=SLEEPING` 且 `run_state=error`。

2026-08-24 的 plan-critique 发现 1–6 已在计划正文里。今天的问题是树已经走到 P09/P10/P11，以及实现评审留下的两处计划缺陷。

折进计划（尤其 P1.4 的兼容规则拍板）后，可以把 Status 重新标成 ready。改计划本身不等于实现过闸。

## P1 — 应修

### 1. `resolve_due_waits` 按 deadline 加锁，并发 sweeper 会死锁

计划 Decision 9、Component 4「Candidate selection」、「Two timeout sweepers」、W36 仍写：候选按 `deadline ASC, event_scope_id, event_name, run_id` 处理，deadline 不可变所以并发 sweeper 锁序一致。

这是 2026-08-24 critique 发现 1 折进去的。实现 Oracle 第 3 轮 P1 已经打穿：deadline 不可变只保证**同一快照**内的序。`LIMIT p_limit` 或两次扫描之间插入一条更老 deadline 的 wait，会让两个 sweeper 选到不同集合：

- A 按 deadline 选到事件键 `B, A`，先锁 `B`
- 新插入更早的 `A` 后，B 选到 `A, B`，先锁 `A`
- 互相等待对方的事件行

PostgreSQL 会检测死锁并中止一方，但这是可到达的 claim 路径失败，计划的锁序证明不成立。

**修正（不改饥饿语义）：** 两套顺序分开。

1. **选出** 最老的 `p_limit` 条：`deadline, event_scope_id, event_name, run_id`（继续用 `run_waits_deadline_idx`）。
2. **处理/加锁** 这个固定集合：`event_scope_id, event_name, run_id`（与 P03 emit 的事件键序一致）。

同步改 Decision 9、Component 4、并发分析、W36、Verification。加一个两 sweeper 回归：在两次候选快照之间插入更老 deadline，有限 `statement_timeout`，证明无死锁。

### 2. Replay 承诺「不兼容则失败」，但没钉 canonical 表达式比较

Component 1 / W34 要求手工预创建的不兼容列/约束让 apply 失败，实际只写了 `ADD COLUMN IF NOT EXISTS` 和按名的 catalog guard。这正是实现 Oracle 第 3 轮仍开着的 P1：同名更弱 CHECK、求值碰巧为 2 的非常量 default、同名不兼容 deadline 索引都能混过去。

P04 是往已有 p21 树上**插入** `0004`，in-place replay 会碰到已有对象，这比当年 p06 树更硬。

**修正：** apply 后用 canonical catalog 比较，不匹配则整树回滚：

- 列：`pg_attribute` 类型 / 空值 / generated
- default：`pg_get_expr(pg_attrdef.adbin, adrelid)`
- CHECK：`pg_get_expr(pg_constraint.conbin, conrelid)` 加上关系与约束类型
- 计划正文写出四个 default、五个 CHECK 的期望表达式
- `jobs_ready_idx` 继续 drop/recreate；`run_waits_deadline_idx` 要么校验完整定义，要么也 drop/recreate

对抗 replay 测试至少三条：同名更弱 factor CHECK；非常量 default 当前求值为 2；同名不兼容 deadline 索引。

### 3. 全文仍按 p06 树写，照做会回退 README 和 `test_p00`

计划 header、「SQL tree and tests」、Component 9 的 22 项函数表、W39/W40、File-by-file、Verification change/stay 矩阵、Exact commands 都还说：全树止于 `0006`、标记 `p06`、没有宿主 SDK。

现行事实：

- `sql/README.md` / `tests/test_p00_sql_source.py:80-102`：全树标记 **p21**，文件含 `0005`/`0007`/`0019`/`0020`/`0021`
- `KERNEL_FUNCTIONS` 已是约 50 项的 p21 元组，不是计划里那 22 项
- `pg_cordis_host` 已落地；P10 计划写明 P04 可选、sleep 用 `to_regprocedure` 探测

`0004` 的 `CREATE OR REPLACE` 对 `claim_job` / `fail_claim` / `release_stale` 会活到全树末尾（后续编号文件没有再替换它们）。`get_schema_version()` 仍由 `0021` 写成 `p21`。

**修正：**

- P04-only 截断树：`0000`–`0004`，标记 `p04`
- 插入后的产品树：`0000,0001,0002,0003,0004,0005,0006,0007,0019,0020,0021`，标记仍为 **p21**
- `KERNEL_FUNCTIONS` 只在现有 p21 元组里按 C 排序插入三个新名，不要整表换成 p06 清单
- README 增加 `0004` 段，保留 p21 为当前产品树
- 删掉「全树止于 0006 / 没有宿主 SDK」

### 4. P09 已先写 `error`，默认重试会让调度行和 log 投影分裂

这是本轮最重的产品冲突，在 P04 范围内：P04 改的就是 P09 正在调用的 `fail_claim(uuid,jsonb)`。

`sql/0021_p09_in_db_worker.sql:466-560`：

- handler/P05 的 `fail`：读最新 `kind=error` 再 `fail_claim`
- 协议失败：先 `emit_step_claimed(..., 'error', ...)` 再 `fail_claim`

计划 Component 5/8：attempt 1 默认可重试，写 `run/sleep`，**禁止**再写 `error`，`jobs.error` 置空。P03 `run_state` 只要 log 里有 `error` 就是终态。于是同一 run：

```text
jobs.status = SLEEPING
run_state.status = error
```

`tests/test_p09_in_db_worker.py:752-769`（`test_p09_worker_maps_p05_failure_to_terminal_job`）断言 `status == ERROR`。P05 计划已写过：全树若含 `0004`，协议失败必须 `max_attempts=1`，且 P04 不能在留下无限定 `error` 的情况下简单重入队（`docs/plans/P05-one-step-driver-2026-08-24.md` P04 retry integration）。

`enqueue_job`（0021:147）只插 `(run_id, job_type, payload, priority)`，新列走默认 `max_attempts=3`。`0004` **不能**替换 `enqueue_job`/`worker_step`：它们定义在之后的 `0021` 里。

**两条合法折法（需拍板，都不重开 D4）：**

1. **推荐（Oracle）：** `fail_claim` 在锁行之后看该 run 是否已有终态 `error` 事件。有则不再入重试：jobs → `ERROR`，`jobs.error` 用最新 log payload，不重复 append `error`，保留当前 attempt。没有预写 `error` 的直接 `fail_claim` 才走退避/死信。P09/P05 现有终态路径保持；P04 自己的无 log 失败仍可重试。
2. 若 P09 失败改为可重试：必须另开 **编号 > 0021** 的文件改 P09/P05 的 error 契约。改历史 `0021` 或声称 `0004` 能覆盖它，都不合法。

无论选哪条，都要改 Summary/Goal、Component 5/8/9、Risks、W37/W41，并加测试：预写 `error` 不得变成 `SLEEPING`（若选 1），或显式重写 P09 契约（若选 2）。

### 5. P09 / P10 / P11 不在 File-by-file 和验证清单里

Component 9 仍写「还没有生产 Python / host SDK」；W40 只改 `test_p00` / `test_p01`。对照现行代码：

| 消费者 | 现行行为 | P04 默认后果 |
|---|---|---|
| `enqueue_job` | 不设 retry 列 | 全部库内 job 拿到 `max_attempts=3`、30s 退避 |
| P09 `worker_step` fail | 先 error 再 `fail_claim` | 见 P1.4；测试要 `ERROR` |
| P10 `sleep_claim` | 无函数 → `P10_SLEEP_UNAVAILABLE` | 全树会探测到函数，`test_p10_sleep_is_typed_but_unavailable_without_p04` 会红 |
| P10 宿主 `fail_claim` | 文档已说 P04 之后看 `get_job` | 成功可能表示已重试，不一定是 `ERROR` |
| P11 租约接管 | 过期后立刻 targeted claim，`attempt` 1→2 | 默认 stale → 30s `SLEEPING`，立刻接管失败 |

**修正：**

- P09：写明 enqueue 接受列默认、本轮不加 per-enqueue 政策参数；测默认值；预写失败按 P1.4 保持终态（或按拍板改契约）。
- P10：缺 `0004` 的拷贝树仍测 unavailable；**全树**加一条现有 client 发现并调用 `sleep_claim` 的测试；文档写清 `fail_claim=true` 可能是 retry；宿主对 `SETOF jobs` 多四列做一次解码回归。
- P11：立刻接管夹具显式把 base/max 退避设为 0（测的是交替认领，不是默认曲线）。默认 30s stale 留在 P04 自己的测试。
- W40/Exact commands 至少覆盖 P00–P11（外加 P19）现有模块；P05-only 截断树继续排除 `0004`。

## P2 — 可顺手

### 1. 把已关闭的浮点溢出对抗例写进命名测试

Component 2 要求饱和检测发生在 `power()` 溢出之前，但 `test_p04_retry_delay_defaults_caps_and_validation` 没有保住实现 Oracle 打过的例子（如 attempt 3、`base=1e-320`、`factor=1e155`：中间 `power` 溢、数学结果仍有限）。补 NaN/±Infinity、真饱和、unlimited 大 attempt。不挡 ready。

## 需要拍板才能折计划的问题

用户 2026-08-25 三问全选是：

1. **P1.1** 采纳「按 deadline 选、按事件键锁」。
2. **P1.4** 选推荐：已有 `error` 事件则 `fail_claim`（以及对应的 stale 路径）只终态、不重试。不开 `>0021` 文件。
3. **P1.5 / P11** 立刻接管夹具用零退避。默认 30s stale 留在 P04 测试。

P1.2 / P1.3 / P1.5 其余项与 P2.1 一并折进 `docs/plans/P04-sleep-retry-2026-08-24.md`。计划 Status 当时恢复 ready。实现仍须新开 Oracle review，不得续 `untitled-chat-4C838A`。

---

## 复审 — 折入用户拍板后的计划

Date: 2026-08-25
Oracle: `untitled-chat-0C5050`，`mode: review`
Export: `prompt-exports/oracle-review-2026-08-26-004902-untitled-chat-0c5050-59d4.md`

说明：这是计划复审，不是 AGENTS.md 的实现闸门轮次，也不续 `untitled-chat-4C838A`。原计划审查聊天属于另一个 RepoPrompt 标签页，当前标签页无法续聊，因此新开本复审聊天。

### 裁决

**NOT READY。** 无 P0，两个 P1，两个 P2。计划 Status 已退回 **needs revision**。

上一轮关闭情况：

- P1.1 timeout sweeper 死锁：**已关闭**。计划已明确按 deadline 选择固定候选集、按事件键顺序处理/加锁，并有双 sweeper 回归。
- P1.2 canonical replay：**部分关闭，仍有 P1**。
- P1.3 p06 基线过期：**已关闭**。截断树为 p04，产品树仍为 p21。
- P1.4 P09/P05 预写 `error`：**已关闭**。`error` 事件作为 `fail_claim` 与 stale recovery 的终态栅栏，不改 `0021`。
- P1.5 P09/P10/P11 消费者：**已关闭**。
- P2.1 浮点溢出回归覆盖：**已关闭**。

### P1 — 应修

1. **Replay 校验仍没有单一、可执行的合同。**
   - 四个 default、五个 CHECK 仍没有在计划中钉死 clean apply 的精确 canonical `pg_get_expr` 字符串；“由测试在 clean apply 上观察到什么就用什么”是循环定义。
   - `run_waits_deadline_idx` 同时允许 drop/recreate 或 validate，但对抗测试又要求同名不兼容索引使 apply 失败。修复漂移与拒绝漂移不能同时成立。
   - 需要拍成一种策略：计划和 SQL guard 共用明确常量；deadline index 若坚持“不兼容则失败”，则 absent 时创建、present 时完整校验并 raise，不 drop/recreate。

2. **计划写错 PostgreSQL `NaN` 语义。**
   - `col = col` 不会拒绝 PostgreSQL 浮点 `NaN`；PostgreSQL 把 `NaN` 视为等于自身，且大于普通有限值。
   - 因而 `factor >= 1` 加 `factor = factor` 仍可接受 `NaN`。
   - schema CHECK 与 `retry_delay_seconds` 参数校验都应使用 PostgreSQL 可行的有限界，例如严格大于 `'-Infinity'::double precision` 且严格小于 `'Infinity'::double precision`，再叠加业务范围；修正后再钉 canonical 表达式。

### P2 — 可顺手

1. stale recovery 命中预写 `error` 栅栏时，`run/claim_timeout(outcome='terminal')` 的精确 payload 尚未定义。它不应假装是 `MAX_RECOVERY_ATTEMPTS_EXCEEDED`。建议把 terminal 分成 budget exhaustion 与 prewritten-error fence 两个 writer 变体，并在命名测试里钉字段。
2. P05 deep plan 仍保留“全树失败路径配置 `max_attempts=1`”的旧交接句，与新的预写 `error` 栅栏规则冲突。建议加 dated supersession note，说明这些路径不再依赖 `max_attempts=1`。

### 进入实现前的条件

修正上述两个 P1 后，必须在 `untitled-chat-0C5050` 同一条 Oracle 计划复审聊天继续，直到明确给出 **READY TO IMPLEMENT**。在此之前不得写 `sql/0004_p04_sleep_retry.sql`、测试或其它实现文件。

### 复审 Round 2

Oracle export: `prompt-exports/oracle-review-2026-08-26-010608-untitled-chat-0c5050-73e1.md`

**NOT READY。** 前两条 P1 与两个 P2 均已关闭；新发现一个 P1：现行消费者 retarget 不完整。

- P11 的零退避只保持立即接管，但 P04 规定每次 stale recovery 必须 append `run/claim_timeout`。原 P11 测试和计划仍断言五行历史不变、stale release 不写 log；应改成两次 takeover 各一条精确 timeout 历史，且零延迟不产生 `run/sleep` / timer `run/wake`。
- P09 `tests/test_p09_in_db_worker.py::TREE_FILES` 精确文件串仍缺 `0004`；P04 计划必须点名修改。

已折入：P04 W40、Component 9、File-by-file、assertion matrix；P11 deep plan 的 stale flow、W112、精确 payload/log order 和 dated supersession note。等待同一聊天 Round 3 裁决。

### 复审 Round 3

Oracle export: `prompt-exports/oracle-review-2026-08-26-012136-untitled-chat-0c5050-5de8.md`

**NOT READY。** 运行时/算法/replay/消费者 retarget 已关闭；剩余两个文档一致性 P1：

1. P04 header 仍写 `needs revision`，与正文已折入 finding、无 open question 相冲突。
2. P11 已要求 P04 的零延迟 stale timeout 历史，但 header/non-goal 仍声称不依赖 P04。

已修正：

- P04 header 统一为 `ready to implement`，同时保留“实现仍需独立 AGENTS.md Oracle gate”。
- P11 header 明确：P09/P10 是原证明依赖，P04 是 full-tree stale-history integration dependency；non-goal 改为不测 sleep/default backoff/dead-letter，但明确消费 P04 zero-delay `release_stale`；实施顺序要求先落地/验证 P04，再跑 P11。

**空转上限：** 同一条 `untitled-chat-0C5050` 已连续三轮仍列 P1。按 `AGENTS.md` 开工规则 3，修正完成后停在这里；未经用户再次明确授权，不开启 Round 4，也不开始实现。

### 复审 Round 4 — 用户明确授权

用户在触及三轮上限后明确选择“授权 Round 4”。
Oracle export: `prompt-exports/oracle-review-2026-08-26-013245-untitled-chat-0c5050-73cc.md`
日期说明：本次评审发生于 **2026-08-25**；上面的 `2026-08-26` 是 RepoPrompt 实际生成的导出文件名，按原样记录。

**READY TO IMPLEMENT。** 无 P0，无 P1。上一轮全部 finding 已关闭：

- canonical replay defaults/CHECK/index 策略可执行且无矛盾；
- PostgreSQL `NaN`/`±Infinity` 校验正确；
- deadline selection / event-key lock order一致；
- prewritten-error fence、stale payload、共享 attempt/retry/dead-letter一致；
- P05/P09/P10/P11 对现行 p21 树的交接与测试 retarget 完整；
- P04 Status 与 P11 P04 dependency/non-goal 已统一。

Oracle 留下三个不挡闸 P2，已折入而未改变架构/ABI：

1. sweep invariant poison 改为只影响 global polling 与受损 run 的 targeted claim；无关 targeted run 不受影响，ACL 风险不再错误归给已落地的 P07。
2. P11 W114 cross-protocol 命令加入 `tests/test_p04_sleep_retry.py`。
3. P11 stale eligibility 改指向 P04 zero-delay 分支，deferred 范围缩为 explicit sleep/default backoff/unlimited/dead-letter，并修正实施顺序重复编号。

本裁决只是**计划 ready**，不是 P04 实现 Oracle 通过。实现完成后仍必须按 `AGENTS.md` 新开实现 review 聊天、关闭全部 P0/P1、立即 commit 并 push，成功前不得宣布 P04 完成。
