# DBOS 深度研究报告：pg_cordis 应借鉴什么

> 报告对象：pg_cordis —— PostgreSQL 原生 agent 控制平面插件运行时（schema `cordis`，核心纯 SQL，execution_tools 不可变快照，(execution_id, tool_call_id) 幂等，SQL 函数即工具协议）。
> 研究基准：DBOS 两篇奠基论文、Apiary/Lotus 论文、DBOS Transact 四语言 SDK 源码（TS/Py/Go/Java，main 分支）、官方文档、官方博客与第三方材料。访问日期统一为 2026-08-23。
> 事实分级约定：【论文主张】= 理论论证；【源码事实】= 以 dim03/06/07 提取的 DDL/源码为准；【文档承诺】= 官方文档语义；【营销表述】= 存疑口径。交叉验证产生的 Conflict Zone 三条在 §2.6、§6 显式呈现；「未获取到」项如实标注。

---

## 0. 执行摘要：pg_cordis 应从 DBOS 借鉴的 5 件事

1. **把工具调用显式分层为"事务性 / 非事务性"两类（P0）。** DBOS 的三层保证模型——workflow 必达完成、step at-least-once、transaction exactly-once——是跨 TS/Py/Go/Java 四语言源码与官方文档一致确认的核心设计^1^ ^2^ ^3^。pg_cordis 的 (execution_id, tool_call_id) 幂等 + "副作用与结果记录同事务提交"恰好等价于 DBOS 的 transactional step（`transaction_completion` 表（部分迁移文件中写作复数 `transaction_completions`，以 datasource.ts 为准）PK=(workflow_id, function_num) + 同事务 `INSERT ... ON CONFLICT DO NOTHING RETURNING`，0 行则回滚重放）^4^ ^5^。但 DBOS 证明这只覆盖一半：对外部 HTTP/LLM 调用这类非事务副作用，必须在 ABI 层暴露 at-least-once 语义与崩溃窗口（副作用生效 → checkpoint 提交之间），而不是假装 exactly-once（洞察 I2）。
2. **恢复机制直接整体移植，不要自研（P0）。** DBOS 的恢复循环是纯 SQL：`UPDATE workflow_status SET status='ENQUEUED' WHERE status='PENDING' AND executor_id=… AND application_version=… RETURNING`，靠队列 `FOR UPDATE SKIP LOCKED` 原子出队保证恰好一个接管者，配 `recovery_attempts` 计数与 `MAX_RECOVERY_ATTEMPTS_EXCEEDED` 死信状态^6^ ^7^。pg_cordis 单库内可去掉 executor_id 维度，但应引入"执行快照版本"过滤替代 application_version，并直接采纳 recovery_attempts + 死信状态机（洞察 I3）。
3. **补 `fork_execution()`：从指定步骤复制 checkpoint 到新执行 ID 重跑（P1）。** DBOS 的 workflow fork（复制 workflow_status.inputs + operation_outputs 中 `< startStep` 的 checkpoint，生成新 uuid、可换新 application_version）是其修复失败执行、"打补丁"换版本重跑、agent eval/调试的统一手段^8^ ^9^。pg_cordis 的 execution_tools 不可变快照粒度（执行级）优于 DBOS 的应用级 MD5 版本，但当前缺少"修改执行定义后继续"的机制——fork 正是答案（洞察 I4）。
4. **事件/通知子系统升级为"幂等键主键 + 原子消费 + 与 checkpoint 同事务"三件套（P1）。** DBOS notifications 以 `message_uuid = <幂等键>::<目的地>` 为主键 `ON CONFLICT DO NOTHING` 发送，消费是单条原子 `UPDATE ... SET consumed=true ... RETURNING` 且与 recv 结果的 checkpoint 写入同一事务；同时保留 pg_notify 触发器做唤醒——NOTIFY 只做唤醒、表做真相^10^ ^11^。pg_cordis 的 events+NOTIFY 方向正确，缺消费侧原子性与幂等键（洞察 I5）。
5. **观测内建于事务：metrics/traces 直接落 `cordis` 表（P2）。** DBOS 论文的核心承诺是"整个系统状态可用 SQL 查询"^12^，但 DBOS 开源版的观测反而退回外挂 OpenTelemetry provider、metrics 依赖商业 Conductor^13^ ^14^——论文愿景未在产品兑现。pg_cordis 全在库内，有机会以 `cordis.metrics` 表 + SQL 视图直接兑现这一愿景，形成对 DBOS 的差异化优势（洞察 I7）。

---

## 1. DBOS 全景

**一句话定位**：DBOS 是"把操作系统/工作流控制平面的全部状态放进 DBMS 表、把一切操作做成事务"的架构运动——从 Stonebraker 等人的学术提案出发，落地为 Postgres 上的开源 durable execution 库（DBOS Transact），再商业化为托管 serverless 平台（DBOS Cloud）。

**时间线**（【论文主张】/【源码事实】/【官方承认】分层标注）：

| 时间 | 节点 | 性质 |
|---|---|---|
| 2020-07 | arXiv 愿景论文《DBOS: A Proposal for a Data-Centric Operating System》（Cafarella/DeWitt/Stonebraker/Zaharia 等）^15^ ^16^ | 论文主张：所有 OS 状态=表，一切操作=无状态任务发起的事务 |
| 2022-01 | VLDB 2022《DBOS: A DBMS-oriented Operating System》，VoltDB 原型^12^ | 论文主张 + 原型实测 |
| 2022-01 | CIDR 2022《A Progress Report on DBOS》^17^ | 原型进展：调度 1–2M tasks/s、provenance 落 Vertica |
| 2022-08 | Apiary（arXiv:2208.13068）：函数编译为 VoltDB 存储过程，函数即 ACID 事务，exactly-once = 同事务记录输出^9^ ^18^ | 论文 + 原型，DBOS Transact 前身 |
| 2022 | Lotus（PVLDB 15(11)）：修补 VoltDB 多分区事务短板^19^ | 论文，引擎层 |
| 2024 | DBOS Transact 开源商用化（Python/TS 先行），纯 library 形态^20^ | 源码事实 |
| 2024–2026 | Go/Java/Kotlin SDK；系统表 schema 收敛为跨语言共享规范（SHARED_MIGRATION_BASE=100）^11^ ^21^ | 源码事实 |
| 2025-07 | 合并重构：workflow_inputs / workflow_queue / scheduler_state 三表 DROP，并入 workflow_status^11^ | 源码事实（Conflict Zone 3） |
| 2026 | AI/agent 集成爆发：Pydantic AI、Vercel AI SDK、OpenAI Agents SDK、Google ADK；step 级协作超时、durable streams（LISTEN/NOTIFY）^22^ ^23^ | 官方文档/博客 |
| 持续 | DBOS Conductor（控制面）+ DBOS Cloud（AWS Firecracker microVM + PG 状态，版本化路由）^24^ ^25^ | 官方承认 |

对 pg_cordis 最重要的定位判断（洞察 I1）：**"executor 即 SQL 函数"不是异端，而是 DBOS 谱系的下一站**。CIDR 论文的限制清单——无触发器、存储过程不能互调、无嵌套事务、只能写 Java^17^——几乎逐条是 PostgreSQL 的强项；VLDB 论文甚至点名"Postgres 有触发器而 VoltDB 没有，触发器可免除 IPC 轮询"^12^。Apiary 把函数**编译为**存储过程所达到的形态，正是 pg_cordis 的原生形态。而 DBOS Cloud 存在的理由之一（executor 是外部进程，最后一个 executor 死亡则 workflow 不自愈^24^）在 pg_cordis 中因 executor 在库内而大幅缓解。pg_cordis 应把"全在 PG"定位为对 DBOS 架构的推进而非妥协。

---

## 2. 关键机制详解（Q1–Q12）

### Q1. Exactly-once 事务模式与崩溃窗口

**机制（源码事实）**：DBOS 把步骤分两类，语义截然不同^1^ ^4^ ^5^：

- **transaction（`DBOS.transaction`）= exactly-once**。以 nodepg-datasource 为例，`invokeTransactionFunction` 在**同一个 client、同一个事务**内执行用户函数并以 `INSERT INTO dbos.transaction_completion (workflow_id, function_num, output, ...) ON CONFLICT DO NOTHING RETURNING workflow_id` 记录结果；返回 0 行说明并发重复执行已先记录，抛内部 `DBOSStepAlreadyRecordedError` 使整条用户事务回滚，再回放已记录结果。即：**副作用要么与结果记录一起提交，要么整体回滚**。PK=(workflow_id, function_num) ≡ pg_cordis 的 (execution_id, tool_call_id)。序列化失败（SQLSTATE 40001）自动指数退避重试（1ms 起、×1.5、封顶 2s）。
- **step（`DBOS.step`）= at-least-once**。`callStepFunction`（`src/dbos-executor.ts`）先同步分配单调 funcID，先查 `operation_outputs`（命中则回放不重跑，函数名不符抛 `DBOSUnexpectedStepError`），**然后执行用户代码，成功后才用系统库连接独立 INSERT `operation_outputs`**。**崩溃窗口 = 用户代码副作用生效 → checkpoint INSERT 提交之间**；窗口内崩溃 → 无 checkpoint → 恢复时整个 step 重执行，副作用再次发生。源码注释明写："A durable checkpoint will be made after the step completes. This ensures at least once execution"^26^。
- **错误也是 checkpoint**：重试耗尽后 error 序列化写入 `operation_outputs.error`，恢复时回放为抛错而非重跑；但被协作取消打断的 step 刻意**不**写 checkpoint，resume 时重跑^4^ ^3^。

**对 pg_cordis 的含义（洞察 I2、I6）**：pg_cordis 的幂等设计已是 DBOS transaction 模型的同构物，应直接复用"同事务 INSERT ON CONFLICT DO NOTHING RETURNING + 0 行回滚 + 统一回放路径"模式（DBOS 专门抽象了 `replayRecordedStep` 保证预读检查与冲突回放两条路径不漂移）。同时必须在工具 ABI 中增加"事务性/非事务性"分类：非事务工具（LLM、HTTP）只能承诺 at-least-once，崩溃窗口必须向插件作者显式文档化。"错误即 checkpoint、恢复时回放抛错"应明确采纳。

### Q2. 恢复机制

**机制（源码事实，四语言一致）**^6^ ^2^ ^7^ ^3^：

1. 启动时 `DBOSExecutor.launch()` → `recoverPendingWorkflows(executorID)`；
2. 核心是**一条 UPDATE**（重入队而非直接执行）：
   ```sql
   UPDATE dbos.workflow_status
   SET started_at_epoch_ms=NULL, status='ENQUEUED', queue_name=COALESCE(queue_name, <内部队列>)
   WHERE status='PENDING' AND executor_id=$4 AND application_version=$5
   RETURNING workflow_uuid;
   ```
   executor_id 谓词使恢复幂等（活执行器一出队就改写 executor_id，重复恢复匹配不到行）；
3. 接管单一性不靠恢复本身，而靠**队列的原子出队**（ENQUEUED→PENDING，`FOR UPDATE SKIP LOCKED`）——"queue 的原子 dequeue 保证恰好一个 runner 接管"；
4. 出队后**从头确定性重放** workflow，逐步查 checkpoint 命中即短路，直到第一个无 checkpoint 的 step——无快照/续跑，全靠"确定性重放 + 单调 function_id 对齐"；
5. `recovery_attempts` 仅在出队翻转时 +1；超限（默认 50/100）由 `deadLetterWorkflows` 置 `MAX_RECOVERY_ATTEMPTS_EXCEEDED`；终态写入 `#recordWorkflowOutcome` 带 `WHERE status='PENDING'` 守卫（"Only a PENDING row owns its outcome"）；
6. 文档层补充：workflow 抛未捕获异常则置 ERROR **不再自动恢复**（视为不可恢复）；`DBOS.resume_workflow` 可从最后完成 step 手动恢复^3^ ^27^。

**对 pg_cordis 的含义（洞察 I3）**：恢复不必自研。以上全部是纯 SQL/PL/pgSQL 可实现的模式。单库内可删 executor_id 维度，但**版本过滤必须保留**——用执行快照版本（execution_tools 快照 ID）替代 application_version，防止旧 checkpoint 在新执行定义上重放。recovery_attempts + MAX_RECOVERY_ATTEMPTS_EXCEEDED + "终态写入带 PENDING 守卫"三件应原样采纳。

### Q3. 真实表结构

**机制（源码事实，以 dim03/06/07 提取的 DDL 为准）**：系统库 schema 默认 `dbos`，经迁移数组收敛（DDL 内嵌于 `migrations.ts`，非 .sql 文件）；从 `SHARED_MIGRATION_BASE=100` 起所有语言 SDK 在相同索引定义相同迁移，schema 是**跨语言共享规范**^11^ ^21^。最终存留 9+1 张表：

| 表 | 主键 | 角色 |
|---|---|---|
| `workflow_status` | workflow_uuid | 状态/输入输出/版本/队列/超时/优先级/fork 谱系/attributes(JSONB,GIN) 等 ~40 列 |
| `operation_outputs` | (workflow_uuid, function_id) | step checkpoint；**错误也写入**；function_id 单调；FK→workflow_status CASCADE |
| `notifications` | message_uuid（幂等键::目的地） | 通知；consumed 列；保留 pg_notify 触发器 |
| `workflow_events` | (workflow_uuid, key) | per-workflow KV 当前值 |
| `workflow_events_history` | (workflow_uuid, function_id, key) | KV 不可变历史（为 fork 兼容） |
| `streams` | (workflow_uuid, key, offset) | append-only 流（durable streams） |
| `workflow_schedules` | schedule_id（schedule_name UNIQUE） | cron 调度定义 + last_fired_at + backfill |
| `application_versions` | version_id（version_name 部分唯一索引） | 版本注册与 latest 路由 |
| `queues` | queue_id（name UNIQUE） | 队列元数据：并发/限速/优先级/分区 |
| `dbos_migrations` | version | 迁移版本记录 |

数据库内建函数：`dbos.enqueue_workflow(...) RETURNS TEXT`（plpgsql，ON CONFLICT DO UPDATE，unique_violation 转 'DBOS queue duplicated'）、`dbos.send_message(...)`（ON CONFLICT DO NOTHING）^11^。关键设计细节：**队列不是独立表**，队列 = workflow_status 上 `status='ENQUEUED' AND queue_name=?` 的行 + `queues` 元数据表。索引策略大量使用部分索引（`WHERE status='PENDING'` 等）控制写放大与 autovacuum 抖动^28^。

**Conflict Zone 3（显式呈现）**：旧文档/旧研究常引用的 `workflow_inputs`、`workflow_queue`、`scheduler_state` 三张表已于 2025-07-25 迁移 `20250725_drop_consolidated_tables` 中 DROP，内容并入 workflow_status（inputs 列、queue_* 列）^11^。本报告一律以最新源码为准。

**对 pg_cordis 的含义**：cordis schema 可对标的不是表数量而是**职责划分**：一行总账（executions ↔ workflow_status）+ 单调序号 checkpoint 表（tool_calls ↔ operation_outputs）+ 幂等键通知表 + append-only 流表。TS 独有的 `request` 列与 `event_dispatch_kv` 表是 HTTP 入口遗留，pg_cordis 可完全忽略（dim06 结论）。

### Q4. Workflow 版本固化

**机制（源码事实）**^29^ ^3^ ^30^：版本 = 全部已注册 workflow 函数源码 `.toString()` 排序后的 MD5（`computeAppVersion()`），混入 DBOS 版本号与应用名；亦可用 `DBOS__APPVERSION` 固定。每个 workflow 行写 `application_version` 列；恢复与出队**只领同版本行**（versionClause：本进程为 latest 时 `(application_version=$3 OR IS NULL)` 兼容旧行排空，否则严格等值）。官方推荐 blue-green：旧进程 drain 至 `list_workflows(app_version=…, status=[ENQUEUED,PENDING])` 为空再退役。修复旧版本失败 workflow 用 **fork**：`forkWorkflow` 在事务中复制 status 行 + `operation_outputs` 中 `< startStep` 的 checkpoint 到新 uuid（记录 `forked_from`/`was_forked_from`），可指定新 application_version。另有 **patch marker** 机制（2026-03）：`DBOS.patch(name)` 向 operation_outputs 写 `DBOS.patch-<name>` 特殊行，重放时按历史记录决定走新/旧代码路径，`deprecatePatch` 停止为新 workflow 插 marker^31^。

**对 pg_cordis 的含义（洞察 I4）**：pg_cordis 启动时固化的 execution_tools 不可变快照 ≈ DBOS 的 application_version 固化，但**粒度更优**——DBOS 因代码在库外只能按应用整体 MD5 版本化，pg_cordis 的 catalog 在库内可按 execution 粒度固化。反过来，DBOS 的 fork 正是 pg_cordis 缺失的"修改执行定义后继续"原语：v0.1 应增加 `fork_execution(exec_id, from_step, new_snapshot_id)`，语义 = 复制执行行 + 复制 `< from_step` 的 tool_call checkpoint + 新 ID。patch marker 是 P2 可选项。

### Q5. 补偿（saga / undo）

**机制（源码事实）**：**不存在**。对 TS 源码全量 grep `compensat|saga|undo` 零匹配；operation_outputs 无补偿栈，workflow_status 无补偿字段^29^。官方立场是手写补偿步骤：在 workflow 失败分支显式调用 undo step（示例 `undo_reserve_inventory()`），**补偿本身也是 checkpointed step**——崩溃恢复后补偿仍会跑到完成、且不会重复（靠 checkpoint），但补偿需自行幂等^32^ ^33^。运维层"事后修复"靠 fork（见 Q4）。

**对 pg_cordis 的含义**：pg_cordis"不实现自动业务回滚"的决策与 DBOS 完全一致，可保持。应补的是**文档约定**："undo step 也是 step，结果进 checkpoint 表"——这给插件作者一个被证明足够的模式，而非一个框架。

### Q6. Time travel 调试

**机制（文档承诺 + Conflict Zone 1，显式呈现）**：委托书假设"time travel 调试是核心论文机制"——**实际两篇奠基论文均未出现 "time-travel debugging" 一词**，最接近的原语是 provenance：P2 §4.7 "capture all changes to system tables in a log (also a DB table) and then support SQL provenance queries"，因历史库巨大而被迫拆出 Vertica 构成 polystore^17^。**现行实现是 fork-from-step**（见 Q4）：复制输入 + checkpoint 确定性重现某 step 之前的状态，在原条件下重跑出错 step、打补丁后验证修复^27^ ^34^；fork 是**开源 API**（`DBOS.fork_workflow`），而图形化 Time Travel Debugger UI 为 **DBOS Cloud 专有**^24^ ^35^。三者非矛盾，是演变：论文 provenance 原则 → 开源 fork API → Cloud 专有调试器。

**对 pg_cordis 的含义**：不必造"time travel"名词。落地两件事：(a) checkpoint 表（tool_calls）天然支持"审计每一步"，这是 AI 调试场景的核心^34^；(b) fork_execution（Q4）即覆盖调试/重跑场景。provenance 原则"每次状态变更捕获进日志表 + SQL 可查"在 PG 单库内可用触发器/temporal 表实现，无需 polystore——这正是 pg_cordis 相对 VoltDB 原型的结构性优势。

### Q7. 队列/通知 exactly-once 消费

**机制（源码事实）**^10^ ^11^ ^36^：

- **send**：在 READ COMMITTED 事务中与 step checkpoint 同事务提交：
  ```sql
  INSERT INTO notifications (destination_uuid, topic, message, serialization, message_uuid)
  VALUES (...) ON CONFLICT (message_uuid) DO NOTHING;
  -- message_uuid = <幂等键>::<目的地workflow>
  ```
- **recv**：先查 operation_outputs（重放不消费第二条）；等待 consumed=false 消息（pg_notify 唤醒 + 轮询兜底）；然后单事务内**原子消费 + 写 checkpoint**：
  ```sql
  UPDATE notifications SET consumed=true
  WHERE destination_uuid=$1 AND topic=$2 AND consumed=false
    AND message_uuid=(SELECT message_uuid FROM notifications
                      WHERE destination_uuid=$1 AND topic=$2 AND consumed=false
                      ORDER BY created_at_epoch_ms ASC LIMIT 1)
  RETURNING message, serialization;
  ```
- **NOTIFY 的角色**：notifications 保留 INSERT 后 pg_notify 触发器（payload=destination::topic）做唤醒，**正确性不依赖它**（表是真相）；workflow_events/streams 的触发器反而在 2025-07 迁移中被删除（改为写入端合并通知）^11^。
- **队列出队**：`SELECT ... WHERE status='ENQUEUED' AND queue_name=? ORDER BY priority ASC, created_at ASC LIMIT n FOR UPDATE SKIP LOCKED`，随后同事务二次校验 UPDATE 翻转为 PENDING（防锁与更新之间状态被改）；有全局并发/限速共享预算时升级 REPEATABLE READ + NOWAIT，让重叠出队者中止而非双花预算^10^。

**对 pg_cordis 的含义（洞察 I5）**：pg_cordis 的 events+NOTIFY 方向被 DBOS 证明正确，但需升级三件套：事件表加幂等键主键（`(execution_id, event_seq)` 或 `producer_key::consumer_id`）、消费侧单条原子 UPDATE consumed + 与消费结果 checkpoint 同事务、NOTIFY 只做唤醒。分区队列的 loose index scan CTE + LATERAL 是 v0.1 可省略的高级项。

### Q8. 调度器：SQL 选任务 / 重试 / 优先级 / 并行

**机制（源码事实）**^10^ ^37^ ^38^：

- **cron 调度**：定义落 `workflow_schedules` 表（schedule_name UNIQUE，支持运行时增删暂停）；执行模型是"**进程内循环 + 表做协调**"而非数据库轮询——每 ~30s 拉 ACTIVE 调度，本地 TimeMatcher 算 nextWakeupTime，睡到点（加 ≤10% 且 ≤10s 随机抖动防惊群）触发。防重复 = **确定性 workflow ID + 主键**：`sched-<scheduleName>-<ISO时间>`，多 executor 同时到点只有一个 INSERT 成功；backfill 从 last_fired_at 逐次补发（同样靠确定性 ID 去重）。
- **重试**：step 级 `retriesAllowed/intervalSeconds(1)/maxAttempts(3)/backoffRate(2)/shouldRetry(error)`，封顶 3600s；每轮先 checkIfCanceled 使取消立即生效；耗尽抛 `DBOSMaxStepRetriesError`^39^。
- **优先级**：`priority` 列，数值小者优先，同优先级 FIFO；**未设优先级的 workflow 优先级最高**。
- **并行/限流**：`worker_concurrency` 用进程内存计数（避免 DB 往返）；全局 `concurrency` 用 `SELECT COUNT(*) ... WHERE status='PENDING'` 落库统计；rate limit 用数据库时钟写 started_at_epoch_ms 保证跨进程一致的滚动窗口。

**对 pg_cordis 的含义**：pg_cordis 的调度循环可以完全用 PL/pgSQL + pg_cron（或后台 worker）实现：确定性执行 ID（`sched-<name>-<时间>`）+ 主键去重是零成本防重复；worker 并发内存计数在库内场景不适用（executor 无进程概念），但限速应同样**用数据库时钟**写时间戳；优先级语义（小值优先 + 未设者优先级最高 + FIFO 平局）可直接照抄。

### Q9. LLM / agent 工作流专门实践

**机制（文档承诺 + 源码事实）**^22^ ^40^ ^41^：DBOS 对"不幂等、贵、慢"的 LLM 调用**没有发明新机制**，答案是"checkpoint 重放零成本"：模型调用包装为 step（Vercel AI 集成 `durableCalls()` 拦截 doGenerate/doStream，完整结果含 usage/finish reason checkpoint 到 PG），恢复时**不再联系模型供应商、不重复烧 token**。配套：(a) step 级重试 + `should_retry` 谓词（401/invalid-request 等供应商标记的不可重试错误快速失败）；(b) step 级**协作式**超时（2026-07，AbortSignal 通知而非抢占；忽略信号则后台继续但结果丢弃）；(c) durable streams——append-only 表 + LISTEN/NOTIFY（2026-06），workflow 内写 exactly-once、**step 内写 at-least-once**（重试重复写对读者可见）；(d) workflow 必须确定性——同一 workflow 内并发 durable 模型调用被**检测并拒绝**，fan-out 并行须拆 child workflow；(e) fork 用于 agent eval/调试。token 预算/计费原语**不存在**（只有"不重复重放省 token" + OTel token 属性观测）。

**对 pg_cordis 的含义（洞察 I6）**：pg_cordis 不实现 token 流式的决策可保持——DBOS durable streams 是 2026 年才补的，且就是一张 append-only 表 + LISTEN/NOTIFY，pg_cordis 应**预留 streams 式追加表**（PK=(execution_id, key, offset)）以备将来。SQL 函数即工具协议的决策下，"LLM 调用必须放在短事务之间"是硬纪律（Apiary：外部调用必须幂等，长时计算是 non-goal^18^）。协作式超时（结果丢弃而非强杀）与被取消 step 不 checkpoint 这两条语义值得照抄。

### Q10. 观测：metrics 落表

**机制（文档承诺 + 营销表述并存）**：落库而非走 OTel 的部分：workflow/step 状态、时间戳、输入输出、error、attributes（JSONB + GIN 部分索引，可 SQL 检索，仅 PG 后端支持）^42^。**外挂的部分**：tracing 走全局 OpenTelemetry provider（可选 `enable_otlp`）；metrics **依赖商业 Conductor**（Prometheus 兼容 endpoint `cloud.dbos.dev/v1/metrics`，gauge 前缀 `dbos_conductor_v1_`，覆盖 workflow rate、enqueued/pending count、step duration 等）^13^ ^14^。"Built-in Observability…graphical UI" 是营销表述，UI 属 Conductor/Cloud 非开源库内置^43^。

**对 pg_cordis 的含义（洞察 I7）**：DBOS 开源版在观测上退回外挂 OTel，未兑现论文"一切皆表则可查"的承诺——这是 pg_cordis 的差异化机会：metrics/traces 直接落 `cordis.metrics` 表（step 时长、重试次数、token 用量属性），配 SQL 视图即兑现论文愿景；Apiary 的数据可作论据——tracing 内建于事务开销 <15%，而手工日志 92%^18^。

### Q11. 论文"OS services on DBMS"论证对 agent 控制平面的适用性

**机制（论文主张）**^12^ ^17^ ^15^：核心论证五条——(a) 规模论（管理问题=大数据问题）；(b) 一次实现论（"transactions, high availability and multi-node support are provided exactly once, by the DBMS, and then used by everybody"）；(c) 可观测性论（全局状态/in-flight 消息皆可 SQL 查询）；(d) schema 纪律论；(e) 历史类比（CODASYL 拥护者当年也说"高级语言做不了数据管理"）。P2 精确化为："centralizes system state … as database tables and executes all operations on state as DBMS transactions, invoked from otherwise stateless processes"^17^。

**适用性判断**：这五条对"agent 控制平面"的映射几乎逐字成立——pg_cordis 的插件生命周期/能力注册/工具分发/钩子折叠/持久事件/执行快照全部是"系统服务状态"，全部因落表而免费获得事务、HA、SQL 可观测。"一次实现论"对 pg_cordis 甚至更强：DBOS 还要跨进程连 PG，pg_cordis 的事务就在库内。论文承认的限制（VoltDB 调用开销 40μs vs syscall 1μs；SP 不能互调；无触发器；多分区事务全局锁降吞吐 50%^12^ ^17^）在 PG 插件架构下逐一消解或大幅缓解（进程内 SPI、PL/pgSQL 互调、触发器、单库无分区）。**但要诚实标注**：两篇论文未含"确定性执行/重放恢复"的正式论述与微内核 LoC 对比（**未获取到**，属后续 DBOS Transact 论文范围）；调度 1–2M tasks/s 是 VoltDB 原型合成负载（只调度不执行），与 Postgres 实测 43K workflow/s（§6）不矛盾——不同引擎。

### Q12. DBOS 边界与教训

**机制（官方承认为主）**^28^ ^44^ ^45^：

1. **性能上限=Postgres 上限**：每 workflow 2–3 次写 + 每 step 1 次 checkpoint 写；96 vCPU RDS 实测 144K 写/s、43K workflow/s，瓶颈是 WAL flush；**单队列仅 12.1K/s（队首行锁竞争，SKIP LOCKED 也救不了），多分区 30.6K/s**；生产口径：>1K actions/s 需负载测试，>40K/s 须手动分片。
2. **最后一个 executor 死亡则不自愈**：worker 可互换恢复彼此，但必须有外部进程活着；"the system is available as long as the underlying database is available"的前提是有进程轮询^46^。
3. **大 payload**：checkpoint 写大小=输出大小，官方建议大文件放对象存储、step 只返回指针。
4. **连接预算**：~100 连接/GB，fan-out 撞 max_connections 是普遍失败模式。
5. **确定性纪律是硬约束**：TS 侧甚至写了 ESLint 静态分析查全局变量。
6. **DBOS 只做持久化执行原语**：agent 编排、MCP、检索全部交给宿主框架（Pydantic AI/LangGraph/Vercel AI SDK 集成都是"把模型/工具调用包成 step"）——与 pg_cordis"SQL 函数即工具协议、不实现 agent loop 编排语法"的定位互相印证。
7. **商业模式建立在"executor 是外部进程"上**：Cloud 托管 microVM、Conductor 观测、Cloud 专有 Time Travel Debugger；pg_cordis 没有可托管的 executor 层，商业模式需另寻（【推断】）。

---

## 3. DBOS ↔ pg_cordis 表结构与 API 对照 diff

> DBOS 侧一律以 dim03/06/07 提取的源码 DDL 为准；pg_cordis 侧按委托书记述的当前设计。判定：✅该抄 / 🔧该改 / ❌不该抄。

| 维度 | DBOS（真实结构） | pg_cordis（当前设计） | 判定 |
|---|---|---|---|
| 总账表 | `workflow_status`：单行承载状态机+inputs+output/error+版本+队列+优先级+超时+fork 谱系+attributes(JSONB)，~40 列、大量部分索引 | executions + execution_tools 快照等分散多表 | 🔧该改：采纳"单行总账 + 部分索引"思想；至少合并状态/输入/输出/快照 ID/优先级/超时列 |
| 步骤 checkpoint | `operation_outputs` PK=(workflow_uuid, function_id)，**错误也写入**，function_name 校验非确定性变更，FK CASCADE | (execution_id, tool_call_id) 幂等 + 同事务提交 | ✅该抄：补 function/tool 名列 + 错误即 checkpoint；PK 结构已同构 |
| exactly-once 写入 | `INSERT ... ON CONFLICT DO NOTHING RETURNING`，0 行→回滚→统一 `replayRecordedStep` 回放 | "副作用与结果记录同事务提交"（目标） | ✅该抄：模式完全同构，直接采用 0 行回滚 + 单一回放路径 |
| 恢复 | 单条 `UPDATE ... PENDING→ENQUEUED WHERE executor_id AND application_version RETURNING` + SKIP LOCKED 出队 + recovery_attempts + MAX_RECOVERY_ATTEMPTS_EXCEEDED | 恢复为 PG 表+SQL 函数（细节未指定死信/次数上限） | ✅该抄：整体移植（I3）；executor_id 可删，快照版本过滤必须加 |
| 版本固化 | 全量源码 MD5 = application_version，应用级粒度；恢复/出队版本过滤 | 启动时固化 execution 级 execution_tools 不可变快照 | 🔧该改：粒度已更优（I4），补快照版本进入恢复/出队谓词 |
| fork | `forkWorkflow`：复制 status 行 + `< startStep` checkpoint → 新 uuid，记 forked_from | 无 | ✅该抄：`fork_execution(exec, from_step, new_snapshot)`（P1） |
| patch marker | `DBOS.patch-<name>` 特殊 checkpoint 行 | 无 | ❌不该抄（v0.1 之后再说） |
| 通知 | `notifications` PK=message_uuid（幂等键::目的地）+ consumed 原子 UPDATE + 与 checkpoint 同事务 + pg_notify 触发器唤醒 | events + NOTIFY | 🔧该改：加幂等键主键与原子消费（I5）；NOTIFY 只唤醒已正确 |
| 事件 KV | `workflow_events`(当前) + `workflow_events_history`(带 function_id 的不可变历史，为 fork) | 持久事件 | 🔧该改：拆"当前值/历史"两表可后置于 fork 落地时 |
| 流 | `streams` PK=(workflow_uuid, key, offset)，append-only | 不实现 token 流式（决策） | 🔧该改：只预留空表/DDL 形状，不实现读写路径（I6） |
| 调度 | `workflow_schedules` + 确定性 ID `sched-<name>-<ts>` 主键去重 + last_fired_at + backfill | （pg_cordis 调度能力未在委托书中展开） | ✅该抄：确定性 ID + 主键去重是零成本 exactly-once 触发 |
| 队列 | 无独立队列表；`queues` 元数据表 + workflow_status 上状态谓词；SKIP LOCKED ORDER BY priority ASC, created_at ASC | 工具分发/执行排队（SQL 函数） | ✅该抄：状态谓词式队列 + 优先级语义照抄 |
| 补偿 | 无框架；undo step 也是 checkpointed step | 不实现自动业务回滚 | ❌不该抄框架；✅该抄文档约定（Q5） |
| 观测 | 状态落表 + 外挂 OTel + metrics 靠 Conductor（商业） | （未展开） | 🔧该改：直接落 cordis.metrics 表 + SQL 视图，超越 DBOS（I7） |
| PL/pgSQL 入口 | `dbos.enqueue_workflow` / `dbos.send_message`（库内函数，供任意 SQL 客户端驱动） | 核心纯 SQL（已是此形态） | ✅该抄：pg_cordis 已在此形态，DBOS 反向验证了它 |
| TS 独有遗留 | `workflow_status.request` 列、`event_dispatch_kv` 表 | — | ❌不该抄（HTTP 入口遗留，dim06 结论） |
| 已 DROP 旧表 | workflow_inputs / workflow_queue / scheduler_state（2025-07 DROP） | — | ❌不该抄；对照旧文档时警惕（Conflict Zone 3） |

---

## 4. absurd × DBOS：谁更适合 pg_cordis

> 本节以 research/absurd_dim11.md 的源码研究为准；absurd 侧【源码事实】均出自 `sql/absurd.sql` 全文与官方文档，「未获取到」项不展开。

### 4.1 absurd 全景

**一句话定位（README 原文）**："Absurd is the simplest durable execution workflow system you can think of. It's entirely based on Postgres and nothing else."^47^ 整个引擎就是**一个 SQL 文件** `sql/absurd.sql`（3150 行 PL/pgSQL），直接 apply 到任意 PostgreSQL 库，不需要 Postgres 之外的任何服务^47^。

- **作者与背书**：组织账号 `earendil-works`；公告博文发在 Armin Ronacher（mitsuhiko，Flask 作者）的博客 lucumr.pocoo.org（README 链接指向该文）^47^。README 自带 AI 辅助开发声明（作者表述："A combination of hand written code, Codex and Claude Code was used"）。
- **活跃度（GitHub API 2026-08-23 快照）**：创建 2025-10-20，最近 push 2026-08-10，star 2363，open issues 33，License Apache-2.0^48^。repo 自述 "An experiment in durability"——实验性质需清醒认知。
- **辅助组件**：`absurdctl`（CLI：schema init/migrate、队列管理、spawn/retry 任务）与 `habitat`（Go + SolidJS 的 Web 观测面板，Overview/Queues/Tasks/TaskRuns/EventLog 视图）随仓库提供^47^；内建 metrics 导出**未获取到**（无 Prometheus 端点代码，观测靠系统表 + habitat UI）。队列分 unpartitioned/partitioned 两种存储模式，后者按周分区并带 detach/清理机制^49^——这套分区生命周期管理对 pg_cordis 是后置参考项。
- **与 DBOS 的架构形态差异**：absurd 作者在 comparison 文档中自己点题——"Absurd pushes more of the durable behavior into stored procedures and keeps the SDKs relatively light. DBOS, by contrast, has rather beefy SDKs in comparison"，并给出 SDK 行数对比：DBOS Python SDK 约 4 万行、Temporal Python SDK 约 17 万行，而 absurd 的 Python SDK 不足 2000 行^50^。即 DBOS 是"固定系统表 + 库外厚 SDK 写表"，absurd 把全部行为压进存储过程、SDK 只做薄封装——这正是 §1 洞察 I1 所指"DBOS 谱系下一站"在另一个项目上的独立兑现。

### 4.2 机制逐项对比

| 机制维度 | DBOS | absurd | 对 pg_cordis 意义 |
|---|---|---|---|
| 表结构与 DDL 风格 | schema `dbos` 下 9+1 张共享规范表（跨四语言 SDK 同一迁移序列，§2 Q3），DDL 内嵌于 SDK 迁移代码^11^ | 全局唯一静态表 `absurd.queues`；**每个队列**由 `ensure_queue_tables` 动态生成 `t_/r_/c_/e_/w_/i_` 六表（任务/运行/checkpoint/事件/等待注册/幂等键侧表），全部逻辑在 3150 行 PL/pgSQL 内^49^ | absurd 的 DDL 即 PG 原生 DDL、可直接阅读改写，移植成本远低于从 TS 源码反推 DBOS DDL；六表分工（尤其 run 与 task 分离、checkpoint 独立表）可直接借鉴 |
| 任务认领 | `SELECT ... WHERE status='ENQUEUED' ... ORDER BY priority, created_at FOR UPDATE SKIP LOCKED` + 同事务二次校验翻转 PENDING（§2 Q7）^10^ | `claim_task` 单 CTE：candidate 子查询 `FOR UPDATE SKIP LOCKED` → 同事务 UPDATE run 置 running+租约 → 同步 task 状态 → 清理过期 wait，**一条语句完成**^49^ | 两者核心同为 SKIP LOCKED，但 absurd 的单 CTE 形态更适合纯 SQL executor 直接照搬 |
| 持久化模型 | checkpoint 表 `operation_outputs` + 确定性重放（单调 function_id 对齐，§2 Q1）^4^ | `c_<q>` checkpoint 表 UPSERT（PK=(task_id, checkpoint_name)）；**写 checkpoint 的同一函数调用可附带延长租约**（同事务）；attempt 防护——仅新 attempt 才能覆盖旧 checkpoint^49^ | "checkpoint 写入与租约延长合并进一次调用"是崩溃窗口收敛的关键技巧，pg_cordis 应吸收 |
| exactly-once 语义 | 三层模型：transaction exactly-once / step at-least-once / workflow 必达完成（§2 Q1）^1^ ^3^ | Concepts 原文承认 lease 崩溃窗口："brief overlapping execution is possible"——**非严格 exactly-once**，窗口=claim timeout；外部副作用须自行派生幂等键^51^ | pg_cordis executor 在库内（PG backend 进程内），"副作用与结果记录同事务"可做到 absurd 因 worker 在库外而做不到的严格性——语义上限学 DBOS，不必退到 absurd 的 lease 语义 |
| 恢复 | 单条 UPDATE 重入队 + 版本过滤 + SKIP LOCKED 原子出队 + recovery_attempts 死信（§2 Q2）^6^ | lease（默认 30s）+ 自动心跳（checkpoint 自动续租）+ **惰性回收**：每次 `claim_task` 顺带扫过期租约并 fail，无独立 reaper；task 级重试支持 fixed/exponential backoff，**全局上限 86400s（1 天）**，手动 `retry_task` 可原地续跑或 spawn_new 克隆^49^ ^51^ ^52^ | 惰性回收（claimer 顺带当 reaper）对纯 SQL executor 极友好；但 absurd 无版本过滤、无死信状态机，恢复纪律仍须学 DBOS |
| 接口形态 | SDK 进程外为主，库内仅 `enqueue_workflow`/`send_message` 两个入口函数（§2 Q3）^11^ | **纯 SQL 一等接口**：`spawn_task / claim_task / complete_run / fail_run / retry_task / set_task_checkpoint_state / await_event / emit_event / cancel_task / extend_claim / create_queue / enable_cron` 等全部是 `absurd.*` schema 函数，任何 PL/pgSQL 可直接 enqueue/claim^49^ | 直接证明 pg_cordis "executor 即 SQL 函数"形态可行且有同路人；函数清单可作 cordis API 设计对照表 |
| non-goals | （见 §2 Q12：长时计算、抢占式取消等） | 明确不做 push（"It does not support push at all"）、无优先级、无服务端并发限流/限速、不做确定性 workflow 运行时（"relies on explicit step boundaries and persisted step results"）^47^ ^50^ | 边界宣言的写法值得学习；但优先级（DBOS 已有成熟语义）pg_cordis 不应跟 absurd 一起放弃 |

### 4.3 选型判断

**结论：机制学 DBOS、形态学 absurd。** absurd 是比 DBOS 离 pg_cordis 更近的参照系，但成熟度上限低于 DBOS，两者互补而非二选一。理由逐条：

1. **哲学同构**：absurd 的"行为全部压进存储过程、SDK 薄到 <2000 行"^50^ 与 pg_cordis "一切皆 PG 表 + SQL 函数、executor 即 SQL 函数"是同一哲学；absurd 作者也自认 DBOS "is probably the closest project on this list in spirit"^50^——三者构成同一谱系，pg_cordis 是其中 executor 最深入库内的极端形态。
2. **可直接借鉴的具体物**：t_/r_/c_/e_/w_/i_ 六表分工与状态机 check 约束、claim 单 CTE、惰性 lease 回收、checkpoint+续租合并调用、attempt 防护写、事件 first-write-wins（`ON CONFLICT ... WHERE payload IS NULL`）与哨兵行 FOR SHARE→FOR UPDATE 固定锁序——全部是 PL/pgSQL 源码事实，移植=改写而非逆向^49^ ^51^。
3. **但语义上限必须学 DBOS**：absurd 公开承认 lease 崩溃窗口内可能重叠执行、非严格 exactly-once^51^；pg_cordis executor 在 PG backend 进程内，能做到 absurd 结构上做不到的"副作用与结果记录同事务"，没有理由退到 lease 语义。DBOS 的 transaction_completion 模式（§2 Q1）仍是 exactly-once 的唯一正解^4^ ^5^。
4. **版本治理/恢复纪律 absurd 缺位**：absurd 无版本固化、无 fork、无死信状态机（研究中未获取到相关机制）；checkpoint 重放模型、版本过滤、fork 这三件仍只能学 DBOS（§2 Q1/Q2/Q4）。
5. **分工结论**：把 absurd 当作"形态与 DDL 的模板"（表怎么建、函数怎么切分、锁序怎么排），把 DBOS 当作"语义与纪律的模板"（exactly-once 怎么证、恢复怎么兜底、版本怎么固化）。两者都不覆盖的部分——agent 控制平面的插件生命周期与能力注册——仍是 pg_cordis 自己的设计空间。

### 4.4 对 §5 修改建议清单的影响

absurd 的证据**不改变** §5 的 P0 方向（事务性/非事务性二分、同事务 checkpoint、恢复整体移植均仍以 DBOS 为师），但为若干 P0/P1 建议提供了更贴近纯 SQL 实现的落地形态，并新增 4 条建议（#16–#19，见 §5 表）：认领 SQL 改单 CTE（强化 #3/#10 的落地形态）、lease 惰性回收与续租合并（新增，补足恢复建议中"executor 在库内时如何探测自身死亡"的空档）、事件锁序（强化 #6）。同时 #10（优先级）保留 DBOS 语义，**不**采纳 absurd 的无优先级 non-goal。

---

## 5. 对 pg_cordis v0.1 的修改建议清单（Q13）

| # | 机制来源 | 当前设计 | 修改方案 | 优先级 | 出处 |
|---|---|---|---|---|---|
| 1 | DBOS transaction/step 二分 | 统一幂等，未区分副作用类型 | 工具 ABI 增加"事务性/非事务性"分类；非事务工具文档化 at-least-once 与崩溃窗口 | **P0** | ^1^ ^4^ ^3^（I2） |
| 2 | `transaction_completion` 写入模式 | "副作用与结果记录同事务提交"（目标） | 落地为 `INSERT ... ON CONFLICT (execution_id, tool_call_id) DO NOTHING RETURNING`，0 行→整体回滚→统一回放函数 | **P0** | ^4^ ^5^ |
| 3 | 恢复循环 | 恢复由 PG 表+SQL 实现 | 移植"单条 UPDATE 重入队 + 快照版本过滤 + SKIP LOCKED 原子出队"；恢复谓词幂等化 | **P0** | ^6^ ^2^ ^7^（I3） |
| 4 | recovery_attempts 死信 | 无 | 出队翻转时 +1；超限置 `MAX_RECOVERY_ATTEMPTS_EXCEEDED`；终态写入带 `WHERE status='RUNNING'` 守卫 | **P0** | ^6^ ^3^ |
| 5 | 错误即 checkpoint | 未明确 | tool_call 失败也写 checkpoint（error 列），恢复时回放为抛错；被协作取消的调用不写 checkpoint 以便重跑 | **P0** | ^4^ ^39^（I6） |
| 6 | 事件消费三件套 | events+NOTIFY，缺消费原子性 | 事件表加幂等键主键 + 单条原子 `UPDATE consumed=true ... RETURNING` + 与消费 checkpoint 同事务；NOTIFY 仅唤醒 | **P1** | ^10^ ^11^（I5） |
| 7 | fork | 无 | `fork_execution(exec_id, from_step, new_snapshot_id)`：事务内复制执行行 + `< from_step` 的 checkpoint + 记谱系列 | **P1** | ^29^ ^27^（I4） |
| 8 | 版本/快照过滤 | execution_tools 快照已固化 | 恢复与出队谓词加入快照版本等值过滤；提供"旧快照排空"查询视图（等价 blue-green drain） | **P1** | ^29^ ^30^（I4） |
| 9 | 调度防重 | 未展开 | 定时触发用确定性执行 ID（`sched-<名>-<时刻>`）+ 主键去重；last_fired_at + backfill 表列 | **P1** | ^37^ ^38^ |
| 10 | 优先级/队列语义 | 工具分发 | 执行行加 `priority`（小值优先、NULL 最高、FIFO 平局）+ 出队 `ORDER BY priority ASC, created_at ASC FOR UPDATE SKIP LOCKED` | **P1** | ^10^ ^53^ |
| 11 | 观测落表 | 未展开 | `cordis.metrics` 表（step 时长/重试/token 属性）+ SQL 聚合视图；不引入外挂 OTel 依赖 | **P2** | ^13^ ^18^（I7） |
| 12 | streams 预留 | 不实现 token 流式（保持） | 仅预留 append-only 表 DDL（PK=(execution_id, key, offset)），不实现读写路径 | **P2** | ^22^ ^54^（I6） |
| 13 | step 级协作超时 | 无 | 超时=信号通知 + 结果丢弃（不抢占强杀）；workflow 超时 start-to-completion 且持久存库 | **P2** | ^23^ ^3^ |
| 14 | 补偿文档约定 | 不实现自动业务回滚（保持） | 文档明确"undo tool_call 也是 checkpointed step、需自行幂等"；不建 saga 框架 | **P2** | ^32^ ^33^ |
| 15 | 大 payload 纪律 | 未明确 | 文档约束：大输出放对象存储，checkpoint 只存指针（DBOS 官方同款建议） | **P2** | ^44^ |
| 16 | absurd claim 单 CTE | 出队为"SELECT SKIP LOCKED + 二次校验 UPDATE"两步（建议 #3/#10） | 改写为 absurd 式单 CTE：candidate `FOR UPDATE SKIP LOCKED` → 同事务 UPDATE 置 running+lease → 同步父任务状态 → 清理过期等待，一条语句完成 | **P0** | research/absurd_dim11.md §3；^49^ |
| 17 | absurd lease + 惰性回收 | 恢复仅"重入队"（建议 #3），executor 在库内时自身死亡探测未覆盖 | 执行行加 `claim_expires_at` + 部分索引 `(claim_expires_at) WHERE state='running'`；每次出队顺带扫过期租约并 fail（claimer 即 reaper，无独立进程）；重试 backoff 上限照抄 86400s | **P1** | research/absurd_dim11.md §4；^49^ ^51^ |
| 18 | absurd checkpoint+续租合并、attempt 防护 | checkpoint 写入独立（建议 #2） | `set_checkpoint` 函数同调用附带 `p_extend_claim_by` 参数（写入与续租同事务）；checkpoint 覆盖加 attempt 防护：仅新 attempt 可覆盖旧值，防迟到写 | **P1** | research/absurd_dim11.md §3；^49^ |
| 19 | absurd 事件 first-write-wins 与锁序 | 事件消费三件套（建议 #6），锁序未定 | emit 侧 `ON CONFLICT DO UPDATE ... WHERE payload IS NULL`（重复 emit 直接返回）；await 侧预插哨兵行 `FOR SHARE` → run 行 `FOR UPDATE` 固定锁序防死锁 | **P1** | research/absurd_dim11.md §6/§7；^49^ |

**P0 五条对应执行摘要 1–3；P1 五条对应摘要 3–4 与版本治理；P2 为差异化与纪律项。**

---

## 6. 风险与边界

1. **Conflict Zone 三条（显式呈现）**：
   - **Time travel 调试的演变**：论文仅有 provenance 原则（捕获变更进日志表 + SQL 查询），"Time Travel Debugger" 是 DBOS Cloud 专有 UI，开源等价物是 fork-from-step。pg_cordis 不应以"复刻 time travel"立项，应以"checkpoint 可审计 + fork"立项（Q6）^17^ ^24^ ^34^。
   - **"DBOS 绑定 Postgres"的修正**：Go/Python SDK 支持 SQLite（社区 Rust 移植亦双后端），结论应修正为"生产以 PG/CockroachDB 为核心，SQLite 为单机可选"。这说明 DBOS 模型的价值在**语义**而非存储引擎——pg_cordis 选择 PG 专有深度（触发器/PL/pgSQL/进程内执行）是主动放弃可移植性换能力，与 Rust 移植的"向外通用化"方向相反，需清醒认知这一取舍^21^ ^55^。
   - **旧表已 DROP**：workflow_inputs / workflow_queue / scheduler_state 已于 2025-07-25 DROP 并入 workflow_status；任何基于旧文档的对照（含委托书表名清单）部分过时，以最新源码为准^11^。
2. **学术主张 vs 生产事实**：论文调度 1–2M tasks/s 是 VoltDB 原型合成负载（只调度不执行）^12^ ^17^；Postgres 实测是 43K workflow/s 直接启动、**单队列 12.1K/s 队首锁竞争**^45^。pg_cordis 若把 executor 搬进库内可消除跨进程 checkpoint 往返，但队首锁竞争、WAL flush 瓶颈、autovacuum 抖动（DBOS 2026 年优化项反推）依然适用——"全在 PG"不改变"上限由 PG 决定"。同时单机嵌入式的对比基线需注意 DBOS 数字产自 96 vCPU RDS。
3. **架构差异带来的风险**：(a) DBOS 的故障隔离是"进程死了换进程"，pg_cordis executor 在库内，执行器 bug 可能影响数据库本体——需要比 DBOS 更强的资源隔离/权限纪律（PG 行级安全、角色、statement_timeout）；(b) DBOS 可用 blue-green 进程并存做升级，pg_cordis 的"版本"只能以快照粒度在库内并存，运维故事需要自证（建议 #8）；(c) DBOS 明确"长时计算是 non-goal、不在事务内等 I/O"——pg_cordis 调用 LLM 时若在库内同步等待，将阻塞 PG worker，必须走"异步任务表 + 短事务轮询/唤醒"而非事务内调用。
4. **营销口径存疑项**：首页 "Exactly-Once Event Processing"、"resilient to any failure"、"Built-in Observability…graphical UI" 均为营销表述；真实保证是三层模型（Q1）、真实观测是外挂 OTel + Conductor（Q10）^3^ ^43^。
5. **未获取到（诚实标注）**：两篇奠基论文未含确定性执行/重放恢复的正式论述与微内核 LoC 对比；长事务风险的具体 GitHub issue 与 "DBOS is not..." 逐字官方表述未获取到；TS 逐条索引级迁移 SQL 未单独展开（以收敛后 DDL 为准）；Python/Java 版 step 级超时在 2026-07 公告时为 "coming soon"，之后是否发布未核实。

---

## 7. 参考文献

访问日期均为 2026-08-23。

### 论文
- ^12^: Skiadopoulos et al., "DBOS: A DBMS-oriented Operating System", PVLDB 15(1):21-30, 2022. https://www.vldb.org/pvldb/vol15/p21-skiadopoulos.pdf
- ^17^: Li et al., "A Progress Report on DBOS: A Database-oriented Operating System", CIDR 2022. https://people.eecs.berkeley.edu/~matei/papers/2022/cidr_dbos.pdf
- ^15^: DBOS Committee, "DBOS: A Proposal for a Data-Centric Operating System", arXiv:2007.11112. https://arxiv.org/abs/2007.11112v1
- ^16^: 同上正文节选镜像. https://www.modb.pro/doc/126523
- ^9^: Kraft et al., "Apiary: A DBMS-Integrated Transactional Function-as-a-Service Framework", arXiv:2208.13068 abs. https://arxiv.org/abs/2208.13068
- ^18^: 同上 HTML 全文. https://arxiv.org/html/2208.13068
- ^19^: Zhou, Yu, Graefe, Stonebraker, "Lotus: Scalable Multi-Partition Transactions on Single-Threaded Partitioned Databases", PVLDB 15(11):2939-2952. https://www.vldb.org/pvldb/vol15/p2939-zhou.pdf

### 源码文件
- ^1^: dbos-transact-ts `src/dbos-executor.ts`. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/dbos-executor.ts
- ^26^: dbos-transact-ts `src/dbos.ts`（L2107 "at least once" 注释）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/dbos.ts
- ^11^: dbos-transact-ts `src/sysdb_migrations/internal/migrations.ts`（全部系统表 DDL、DROP 迁移、内建函数）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/sysdb_migrations/internal/migrations.ts
- ^4^: dbos-transact-ts `src/system_database.ts`（recordOperationResultInternal L5307、reenqueueWorkflowsForRecovery L1404、send/recv、出队）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/system_database.ts
- ^5^: dbos-transact-ts `packages/nodepg-datasource/index.ts`（invokeTransactionFunction 同事务模式）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/packages/nodepg-datasource/index.ts
- ^6^: dbos-transact-ts `src/datasource.ts`（transaction_completion DDL、replayRecordedStep）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/datasource.ts
- ^29^: dbos-transact-ts `src/dbos-executor.ts` / `src/system_database.ts`（computeAppVersion、forkWorkflow、checkPatch）. 同 ^1^ ^4^
- ^2^: dbos-transact-py `dbos/_sys_db.py`（call_txn_as_step、reenqueue_for_recovery）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_sys_db.py
- ^7^: dbos-transact-py `dbos/_schemas/system_database.py`（SQLAlchemy DDL 真源）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_schemas/system_database.py
- ^8^: dbos-transact-ts `schemas/system_db_schema.ts`. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/schemas/system_db_schema.ts
- ^10^: dbos-transact-ts `src/system_database.ts`（send L2640、recv L2733、findAndMarkStartableWorkflows L3440-3645）. 同 ^4^
- ^21^: Go 初始 schema `dbos/internal/sysdb/migrations/1_initial_dbos_schema.sql`；Java `MigrationManager.java`；Python `dbos/_migration.py`. https://raw.githubusercontent.com/dbos-inc/dbos-transact-golang/main/dbos/internal/sysdb/migrations/1_initial_dbos_schema.sql ; https://raw.githubusercontent.com/dbos-inc/dbos-transact-java/main/transact/src/main/java/dev/dbos/transact/migrations/MigrationManager.java
- ^37^: dbos-transact-ts `src/scheduler/scheduler.ts`（DynamicSchedulerLoop、确定性调度 ID）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/scheduler/scheduler.ts
- ^39^: dbos-transact-ts `src/step.ts`（StepConfig/重试语义）. https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/step.ts
- ^40^: dbos-inc/dbos-vercel-ai（durableCalls middleware）. https://github.com/dbos-inc/dbos-vercel-ai
- ^55^: hwuiwon/dbos-transact-rust（社区移植，PG+SQLite）. https://github.com/hwuiwon/dbos-transact-rust
- ^49^: earendil-works/absurd `sql/absurd.sql`（3150 行 PL/pgSQL 全文：ensure_queue_tables、claim_task、fail_run/retry_delay_seconds、set_task_checkpoint_state、await_event/emit_event、cancel_task、enable_cron）. https://raw.githubusercontent.com/earendil-works/absurd/main/sql/absurd.sql
- ^52^: earendil-works/absurd `sdks/python/src/absurd_sdk/__init__.py`（自动心跳 heartbeat_interval_ms）. https://raw.githubusercontent.com/earendil-works/absurd/main/sdks/python/src/absurd_sdk/__init__.py

### 文档
- ^3^: Workflows（三层保证/Timeout/Idempotency）. https://docs.dbos.dev/python/tutorials/workflow-tutorial
- ^13^: Metrics（Conductor Prometheus endpoint）. https://docs.dbos.dev/production/metrics
- ^14^: Logging & Tracing（OTel）. https://docs.dbos.dev/python/tutorials/logging-and-tracing
- ^20^: dbos-transact-py 仓库（纯 library 定位）. https://github.com/dbos-inc/dbos-transact-py
- ^27^: Workflow Management（cancel/resume/fork）. https://docs.dbos.dev/python/tutorials/workflow-management
- ^30^: Upgrading Workflow Code（patching/versioning/蓝绿）. https://docs.dbos.dev/python/tutorials/upgrading-workflows
- ^34^: Observability & Reproducibility（fork 复现失败）. https://docs.dbos.dev/ai/debugging
- ^36^: Communicating with Workflows（send/recv/events/streams）. https://docs.dbos.dev/python/tutorials/workflow-communication
- ^38^: Scheduling Workflows（幂等键/backfill）. https://docs.dbos.dev/python/tutorials/scheduled-workflows
- ^41^: Pydantic AI 集成文档. https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/
- ^42^: DBOS System Database（表结构 + PL/pgSQL 函数）. https://docs.dbos.dev/explanations/system-tables
- ^44^: Architecture（开销=数据库写、大 payload 建议）. https://docs.dbos.dev/architecture
- ^53^: Queues & Concurrency. https://docs.dbos.dev/python/tutorials/queue-tutorial
- ^54^: 同 ^36^（streams 语义）
- ^47^: earendil-works/absurd README.md（定位原文、pull-based/无 push、AI 辅助声明、Armin Ronacher 博客链接）. https://raw.githubusercontent.com/earendil-works/absurd/main/README.md
- ^48^: GitHub API earendil-works/absurd 仓库元数据（star 2363、Apache-2.0、created 2025-10-20、pushed 2026-08-10）. https://api.github.com/repos/earendil-works/absurd
- ^50^: earendil-works/absurd `docs/comparison.md`（beefy SDK 对比、SDK 行数、non-goals、DBOS 段作者原文）. https://raw.githubusercontent.com/earendil-works/absurd/main/docs/comparison.md
- ^51^: earendil-works/absurd `docs/concepts.md`（lease 崩溃窗口重叠执行承认、checkpoint 自动续租、数据默认永久保留）. https://raw.githubusercontent.com/earendil-works/absurd/main/docs/concepts.md

### 博客
- ^22^: AI Quickstart / What's New June-July 2026（durable streams LISTEN/NOTIFY、step 超时）. https://docs.dbos.dev/ai/ai-quickstart ; https://www.dbos.dev/blog/new-in-dbos-june-2026 ; https://www.dbos.dev/blog/new-in-dbos-july-2026
- ^23^: 同 ^22^（July 2026 发布说明）
- ^24^: Announcing DBOS / SF Systems Meetup（Cloud 架构、Time Travel Debugger Cloud 专有）. https://www.dbos.dev/blog/announcing-dbos ; https://www.dbos.dev/blog/sf-systems-meetup-2024-talk
- ^25^: InfoWorld DBOS Cloud 报道. https://www.infoworld.com/article/2336467/
- ^28^: What's New May 2026（性能优化项反推瓶颈）. https://www.dbos.dev/blog/new-in-dbos-may-2026
- ^31^: What's New March 2026（Workflow Patching）. https://www.dbos.dev/blog/dbos-new-features-march-2026
- ^32^: Handling Workflow Failures with Forks（补偿=checkpointed undo step）. https://www.dbos.dev/blog/handling-failures-workflow-forks
- ^33^: Resonate "DBOS vs Resonate — Saga/compensation"（第三方佐证无 saga DSL）. https://docs.resonatehq.io/evaluate/coming-from/dbos
- ^35^: npm @dbos-inc/dbos-sdk 1.18.3-preview（time travel queries 实验性）. https://www.npmjs.com/package/@dbos-inc/dbos-sdk/v/1.18.3-preview
- ^43^: docs.dbos.dev 首页（营销表述样例）. https://docs.dbos.dev
- ^45^: Benchmarking Workflow Execution Scalability on Postgres（144K 写/s、43K/s、队列 12.1K/s）. https://www.dbos.dev/blog/benchmarking-workflow-execution-scalability-on-postgres
- ^46^: Postgres Is All You Need for Durable Execution（worker 互换恢复）. https://www.dbos.dev/blog/postgres-is-all-you-need-for-durable-execution

---

## 附录 A：DBOS 系统表关键 DDL 详情（以源码为准，供 cordis DDL 对照）

### A.1 `dbos.operation_outputs`（checkpoint 表，对标 cordis tool_calls）
```sql
create table dbos.operation_outputs (
  workflow_uuid text not null,
  function_id   int4 not null,
  output text, error text,                       -- 错误也作 checkpoint 写入
  constraint operation_outputs_pkey primary key (workflow_uuid, function_id));
alter table dbos.operation_outputs add column function_name text not null default '';
alter table dbos.operation_outputs add column child_workflow_id text;
alter table dbos.operation_outputs add column started_at_epoch_ms bigint,
                                     add column completed_at_epoch_ms bigint;
alter table dbos.operation_outputs add column serialization text default null;
alter table dbos.operation_outputs add column application_name text default null;
alter table dbos.operation_outputs add foreign key (workflow_uuid)
  references dbos.workflow_status(workflow_uuid) on update cascade on delete cascade;
create index idx_operation_outputs_completed_at_function_name
  on dbos.operation_outputs(completed_at_epoch_ms, function_name);
```
写入路径（exactly-once 核心）：
```sql
INSERT INTO dbos.operation_outputs (...) VALUES (...)
ON CONFLICT (workflow_uuid, function_id) DO UPDATE
  SET completed_at_epoch_ms = operation_outputs.completed_at_epoch_ms
RETURNING completed_at_epoch_ms;   -- 冲突行 completed_at 不同 → DBOSWorkflowConflictError
```

### A.2 `dbos.notifications`（对标 cordis events/通知）
```sql
create table dbos.notifications (
  destination_uuid text not null references dbos.workflow_status(workflow_uuid)
    on update cascade on delete cascade,
  topic text, message text not null,
  created_at_epoch_ms bigint not null default (EXTRACT(EPOCH FROM now())*1000)::bigint,
  message_uuid text not null default uuid_generate_v4() primary key,  -- = <幂等键>::<目的地>
  serialization text default null,
  consumed boolean not null default false);
create index idx_notifications on dbos.notifications(destination_uuid, topic);
-- 保留触发器：INSERT 后 pg_notify('dbos_notifications_channel', destination_uuid||'::'||topic)
```

### A.3 队列与调度相关（workflow_status 关键列与索引）
```sql
-- workflow_status 关键列（收敛后）：
-- workflow_uuid PK / status / inputs / output / error / executor_id
-- application_version / queue_name / priority int4 not null default 0
-- deduplication_id / queue_partition_key / recovery_attempts bigint default 0
-- workflow_timeout_ms / workflow_deadline_epoch_ms / delay_until_epoch_ms
-- forked_from / was_forked_from bool / parent_workflow_id / owner_xid
-- attributes jsonb / schedule_name / started_at_epoch_ms / completed_at
create unique index uq_workflow_status_dedup_id
  on dbos.workflow_status(queue_name, deduplication_id) where deduplication_id is not null;
create index idx_workflow_status_in_flight
  on dbos.workflow_status(queue_name,status,priority,created_at)
  where status in ('ENQUEUED','PENDING');
-- 出队：
SELECT workflow_uuid FROM dbos.workflow_status
WHERE status='ENQUEUED' AND queue_name=$2 AND <versionClause> AND <appScope>
ORDER BY priority ASC, created_at ASC LIMIT $n FOR UPDATE SKIP LOCKED;
-- 同事务二次校验翻转：
UPDATE dbos.workflow_status SET status='PENDING', executor_id=$2, application_version=$3,
  started_at_epoch_ms=$4, recovery_attempts=recovery_attempts+1
WHERE workflow_uuid=ANY($1) AND status='ENQUEUED' RETURNING workflow_uuid;
```

### A.4 恢复 UPDATE（移植模板）
```sql
UPDATE dbos.workflow_status
SET started_at_epoch_ms=NULL, status='ENQUEUED',
    queue_name=COALESCE(queue_name, '_dbos_internal_queue')
WHERE status='PENDING' AND executor_id=$4 AND application_version=$5
RETURNING workflow_uuid;
-- pg_cordis 版建议：executor_id 谓词删除，application_version 谓词替换为 execution_snapshot_id
```

### A.5 其他表 DDL（简）
```sql
create table dbos.streams (
  workflow_uuid text not null references dbos.workflow_status on delete cascade,
  key text not null, value text not null, offset int4 not null,
  function_id int4 not null default 0, serialization text default null,
  primary key (workflow_uuid, key, offset));
create table dbos.workflow_events (
  workflow_uuid text not null references dbos.workflow_status on delete cascade,
  key text not null, value text not null, serialization text default null,
  primary key (workflow_uuid, key));
create table dbos.workflow_events_history (
  workflow_uuid text not null references dbos.workflow_status on delete cascade,
  function_id int4 not null, key text not null, value text not null,
  serialization text default null, primary key (workflow_uuid, function_id, key));
create table dbos.workflow_schedules (
  schedule_id text primary key, schedule_name text not null unique,
  workflow_name text not null, workflow_class_name text, schedule text not null,
  status text not null default 'ACTIVE', context text not null,
  last_fired_at text default null, automatic_backfill boolean not null default false,
  cron_timezone text default null, queue_name text, application_name text default null);
create table dbos.application_versions (
  version_id text primary key, version_name text not null unique,
  version_timestamp bigint not null, created_at bigint not null,
  application_name text default null);
create table dbos.queues (
  queue_id text primary key default gen_random_uuid()::text, name text not null unique,
  concurrency int4, worker_concurrency int4,
  rate_limit_max int4, rate_limit_period_sec double precision,
  priority_enabled boolean not null default false, partition_queue boolean not null default false,
  partition_concurrency int4, partition_worker_concurrency int4,
  partition_rate_limit_max int4, partition_rate_limit_period_sec double precision,
  polling_interval_sec double precision not null default 1.0,
  application_name text default null, created_at bigint not null, updated_at bigint not null);
-- 库内入口函数：
-- dbos.enqueue_workflow(workflow_name, queue_name, positional_args json[], named_args json,
--   class_name, config_name, workflow_id, app_version, timeout_ms, deadline_epoch_ms,
--   deduplication_id, priority, queue_partition_key, authenticated_user, authenticated_roles,
--   delay_until_epoch_ms, application_name) RETURNS text
-- dbos.send_message(destination_id, message json, topic, message_id) RETURNS void
--   （INSERT ... ON CONFLICT (message_uuid) DO NOTHING）
```

*（报告完。事实依据：dim01–dim10 维度研究、cross_verification 置信度分级、insight I1–I7。）*
