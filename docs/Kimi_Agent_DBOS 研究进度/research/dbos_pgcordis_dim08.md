# DBOS 官方文档研究：Durable Execution 核心机制（Dim 08）

- 来源站点：docs.dbos.dev 官方文档
- 访问日期：2026-08-23
- 语境：pg_cordis（PostgreSQL 原生 agent 插件运行时）官方文档层证据，与源码证据互证
- 说明：当前文档按语言分栏（Python/TypeScript/Go/Java），机制表述基本一致；以下以 Python 版为主。每条标注【文档承诺】或【营销表述】。

---

## 1. Durable Workflows / How Workflows Work / Exactly-Once Semantics

### 机制（checkpoint 模型）
- 【文档承诺】DBOS 通过把 workflow 与 step **checkpoint 到 Postgres** 实现 durable execution：workflow 启动前记录输入；每个 step 完成后记录输出（或异常）；workflow 结束时记录输出。恢复时从头重放 workflow 函数，遇到已有 checkpoint 的 step 直接取回存值跳过，执行到第一个没有 checkpoint 的 step 时正常执行——即"从最后完成的 step 恢复"[^55^]。
- 【文档承诺】workflow 函数必须**确定性**（相同输入→相同 step 序列、相同顺序）；非确定性操作（随机数、本地时间、外部 API、DB 访问）必须放进 step。不得修改全局变量等"自身作用域外的内存副作用"，否则 DBOS 不保证恢复后这些副作用存在[^54^][^55^]。

### Exactly-once 的精确定义与边界
官方的三条保证（注意：**不是**字面"所有东西 exactly-once"）[^54^]：
1. 【文档承诺】Workflow 总会运行到完成（假设进程与数据库崩溃后会被重启并回到在线）。
2. 【文档承诺】Step 是 **at-least-once**：step 内部失败可能重试；但一旦完成，绝不重执行。
3. 【文档承诺】Transaction（数据库事务）**exactly once commit**：一旦提交，绝不重试。

边界条件：
- 若 workflow 抛出未捕获异常，workflow 终止，记录异常、状态置 `ERROR`，**不再自动恢复**（uncaught exception 被视为不可恢复）[^54^]。
- Workflow ID 作为**幂等键**：同一 ID 多次调用只执行一次[^54^]。
- 【营销表述】首页/feature 区宣称 "Exactly-Once Event Processing"、"resilient to any failure"——需以上述三条精确定义为准；"exactly-once" 的营销口径实际由 step at-least-once + transaction exactly-once + idempotency key 组合达成[^53^]。

## 2. Recovery
- 【文档承诺】单服务器：每次进程重启，DBOS 恢复所有 `PENDING` workflow[^58^]。
- 【文档承诺】分布式自托管（无 Conductor）：需为每个 executor 配置唯一 executor ID；每个 workflow 打上启动它的 executor ID；重启时只恢复属于该 executor ID 且属于该 application 的 pending workflow（共享 system DB 的多个应用互不恢复对方的 workflow）[^58^]。
- 【文档承诺】接 Conductor 时恢复自动：executor 断连后状态转 `DISCONNECTED`，超时（默认 60s，可在 Console 配置）后转 `DEAD`，Conductor 通知另一 executor 接管其 workflow；恢复确认后删除该 executor 记录[^58^]。
- 【文档承诺】超过最大恢复次数的 workflow 状态为 `MAX_RECOVERY_ATTEMPTS_EXCEEDED`（见 workflow_status 表枚举与 metrics 失败口径）[^63^][^64^]；可通过 `DBOS.resume_workflow` 从最后完成 step 手动恢复[^65^]。

## 3. Workflow / Application Versioning
- 【文档承诺】所有 workflow 打上启动时的 application version；默认版本由 **workflow 源码 hash** 自动计算，也可配置指定[^59^]。
- 【文档承诺】恢复时**只恢复版本与当前应用版本匹配**的 workflow，防止依赖不同代码的 workflow 被不安全恢复[^59^]。
- 【文档承诺】两种升级策略：
  - **Patching**：`DBOS.patch(name)` 在 workflow history（`operation_outputs` 表新行）中插入 patch marker；插入成功/已存在→新 workflow 返回 True 走新代码；该位置已有记录→旧 workflow 返回 False 走旧代码。`DBOS.deprecate_patch()` 停止为新 workflow 插 marker 但兼容旧 history；所有旧 workflow 完成后可删除 patch。出错抛 `DBOSUnexpectedStepError`[^59^]。
  - **Versioning + 蓝绿部署**：新旧进程并存，新流量导向新版本（`DBOS.get_latest_application_version` + `SetEnqueueOptions(app_version=...)`），旧进程 drain 完毕（`DBOS.list_workflows(app_version=..., status=[ENQUEUED, PENDING])` 为空）后退役。回滚用 `DBOS.set_latest_application_version`。Scheduled workflow 自动入队到 owning app 的 latest version[^59^]。
- 存储：`dbos.application_versions` 表，latest 由最高 timestamp 决定；版本名在共享 system DB 的所有应用间唯一[^64^]。

## 4. Time Travel Debugging / Forking
- 现状：当前文档中**不再有名为 "time travel debugging" 的独立章节**（旧版文档曾有）。对应能力现为 **workflow fork**：
  - 【文档承诺】`DBOS.fork_workflow`（或 Console trace timeline 上点 step 上的 FORK 按钮）：生成新 workflow ID，把原 workflow 的输入与截至所选 step 的所有 step checkpoint **复制**到新 workflow，从所选 step 开始执行。用途：下游故障恢复后重跑失败 step；把因旧版本 bug 失败的 workflow fork 到修复后的 application version[^65^]。
  - 【文档承诺】AI 调试场景（Observability & Reproducibility）：因每步 outcome 都 checkpoint，可审计导致失败的每一步；fork 利用 checkpoint 信息**确定性重现**该 step 之前的 workflow 状态，从而在原条件下重跑出错 step、打补丁后验证修复[^62^]。
- 读哪张表：fork 复制来源为 `dbos.workflow_status`（inputs）与 `dbos.operation_outputs`（step 输出，按 `function_id` 单调序号）；`workflow_status.forked_from` / `was_forked_from` 记录 fork 谱系[^64^]。
- 是否 Cloud 专有：**否**——fork 是开源库 API（`DBOS.fork_workflow`），Console UI 只是入口之一[^65^]。

## 5. Queues（并发/速率/优先级）
- 【文档承诺】队列持久化在 system database（`dbos.queues` 表），对连接该库的所有进程/客户端可见；共享 system DB 时队列归注册它的 application 所有，只有该应用出队。FIFO 顺序启动[^56^][^64^]。
- 【文档承诺】并发控制：
  - `worker_concurrency`：单进程内该队列最大并发（用 `executor_id` 区分进程）。
  - `concurrency`（global）：全应用跨进程总并发；警告：所有 `PENDING` workflow（含旧版本残留）都计入限额，官方建议优先用 worker concurrency。
  - `concurrency=1` 保证事件严格顺序逐个处理[^56^]。
- 【文档承诺】Rate limit：`limiter={"limit": 50, "period": 30}`，全局跨进程生效[^56^]。
- 【文档承诺】优先级：`priority_enabled=True` 后可用 `SetEnqueueOptions(priority=N)`，N∈[1, 2^31-1]，**数值小=优先级高**；同优先级 FIFO；**未设优先级的 workflow 优先级最高**，先于任何设了优先级的出队[^56^]。
- 【文档承诺】其他：队列配置存 DB、可运行时改（`DBOS.retrieve_queue(...).set_*`，worker 下一轮轮询生效）；deduplication_id 去重（冲突抛 `DBOSQueueDeduplicatedError` 或 `return-existing` 单例策略）；partitioned queue 按 partition key 独立限流；delayed execution（`DELAYED` 状态 + `delay_until_epoch_ms`）；`DBOS.listen_queues` 做异构 worker 分工；支持从 PL/pgSQL `dbos.enqueue_workflow(...)` 入队[^56^][^64^]。

## 6. Notifications & Workflow Events
- 【文档承诺】send/recv：所有消息持久化到数据库（`dbos.notifications` 表，含 `topic`、`consumed` 列）；send 成功即保证目标 workflow 能 recv 到。**从 workflow 内 send 保证 exactly-once delivery**；从普通代码 send 需用 `SetWorkflowID`/idempotency key 保证 exactly-once（`dbos.send_message` PL/pgSQL 函数带 `idempotency_key` 参数）。recv 按 topic 消费下一条消息，超时返回 None[^60^][^64^]。
- 【文档承诺】set_event/get_event：event 为 per-workflow 键值对，持久化（`dbos.workflow_events` 当前值 + `dbos.workflow_events_history` 历史值，含设置它的 `function_id`）。若在 workflow 内调用 `get_event`，取到的值会被持久化，恢复时复用该值即使 event 后来被更新——这是 event 侧的确定性消费保证[^60^][^64^]。
- 另有 workflow streaming（`dbos.streams` 表，key + offset + function_id），用于实时流式输出[^60^][^64^]。

## 7. Observability
- 【文档承诺】Tracing：DBOS 自动为每个 workflow 和 step 生成 **OpenTelemetry** span（step span 是 workflow span 的子级）。发到**全局 OTel tracer provider**——应用已有 OTel 管线时零额外接入。可选功能：`pip install dbos[otel]` + `enable_otlp: True`。也可由 DBOS 直接导出 traces/logs 到任意 OTLP endpoint（`otlp_traces_endpoints` / `otlp_logs_endpoints`，后者导出 `DBOS.logger` 日志）[^61^]。
- 【文档承诺】入队 workflow 默认开新 trace；`PropagateOtelContext` 把 trace context **持久化**（durable 记录），使 workflow 无论何时何地（含 recovery）执行都接回调用方 trace[^61^]。
- 【文档承诺】落库而非走 OTel 的部分：workflow/step 状态、时间戳、输入输出、error 全部落 system DB（`workflow_status`、`operation_outputs` 等，见 §表结构）；workflow attributes 以 GIN 索引 JSONB 存储可检索（仅 Postgres system DB 支持属性过滤）[^64^][^65^]。
- 【文档承诺】Metrics：**依赖 Conductor**（控制面），提供 Prometheus/OpenMetrics 兼容 scrape endpoint `https://cloud.dbos.dev/v1/metrics`，全部 gauge，前缀 `dbos_conductor_v1_`，覆盖 workflow started/success/failed/cancelled rate、enqueued/pending count、queue wait/latency max、step duration、executor_count 等；按最近完成的对齐分钟窗口聚合。需 DBOS Python ≥2.23.0 / TS ≥4.19[^63^]。
- 【营销表述】"Built-in Observability…graphical UI"（首页）——UI 属 Conductor/Cloud Console，非开源库内置[^53^][^80^]。

## 8. Scheduled Workflows / Cron
- 【文档承诺】schedule 存数据库（`dbos.workflow_schedules`），支持运行时创建/暂停/恢复/删除/列表；cron 用 croniter 解析，5 或 6 段（可选首位秒），默认 UTC，可设 IANA `cron_timezone`。每次触发由**恰好一个** worker 执行[^57^][^64^]。
- 【文档承诺】Exactly-once 机制：DBOS 为每次调度执行构造幂等键 = **schedule 名 + 计划执行时间**的拼接，保证应用活跃期间每次调度恰好执行一次[^57^]。
- 【文档承诺】Backfill：`DBOS.backfill_schedule` 补跑错过的执行（已执行的自动跳过）；`automatic_backfill=True` 启动/恢复时自动补。注意 backfill 按**当前** cron 表达式计算错过点。可指定 `queue_name` 让调度执行走指定队列的流控。旧 `@DBOS.scheduled` 装饰器已 deprecated[^57^]。

## 9. Cancellation / Timeout / 补偿
- 【文档承诺】Timeout：`SetWorkflowTimeout`，到期 workflow **及其全部子 workflow** 被 cancel——状态置 `CANCELLED`，在**下一个 step 开始处**抢占执行；要立即中断正在执行的 async step 需把该 step 标记为 `preemptible`。Timeout 是 **start-to-completion**（入队等待不计时，出队开始执行才计时）且**durable**（存库、跨重启存活，可设很长）[^54^][^56^]。存储：`workflow_timeout_ms` 与派生的 `workflow_deadline_epoch_ms` 列[^64^]。
- 【文档承诺】Cancel：`DBOS.cancel_workflow` / UI / CLI；执行中→下一 step 开始处抢占；在队列中→直接移出队列[^65^]。
- 补偿（compensation）：**无专用补偿 API 章节**；官方模式是把补偿写成普通 step（示例：checkout 中 `undo_reserve_ticket` 作为 step，其结果被 checkpoint，崩溃恢复后不会重复补偿也不会跳过）[^55^]。
- Resume：`DBOS.resume_workflow` 从最后完成 step 恢复（可用于 cancelled 或超过最大恢复次数的 workflow，也可让入队任务立即开始）[^65^]。

## 附：System Database 表结构（pg_cordis 对标核心）
`dbos.workflow_status`（状态/输入输出/版本/executor_id/timeout/deadline/dedup/priority/owner_xid 防重复启动等）、`dbos.operation_outputs`（step checkpoint，function_id 单调递增，`DBOS.sleep`/`DBOS.send`/启动子 workflow 也记为 step）、`dbos.notifications`、`dbos.workflow_events`(+`_history`)、`dbos.streams`、`dbos.application_versions`、`dbos.workflow_schedules`、`dbos.queues`、`dbos.dbos_migrations`；另有 PL/pgSQL 函数 `dbos.enqueue_workflow`、`dbos.send_message`（向后兼容、原子 drop+recreate 更新）[^64^]。

## 未获取到的章节
- 独立 "Time Travel Debugging" 章节：当前站点结构下不存在（sitemap 无此 URL），能力已并入 Forking / AI Observability & Reproducibility（见 §4）。
- 独立的 compensation（saga）语义章节：不存在，仅有示例中的补偿 step 模式（见 §9）。

## 参考来源
[^53^]: https://docs.dbos.dev — Welcome to DBOS!（首页/Features），访问 2026-08-23
[^54^]: https://docs.dbos.dev/python/tutorials/workflow-tutorial — Workflows（含 Workflow Guarantees / Timeout / Idempotency），访问 2026-08-23
[^55^]: https://docs.dbos.dev/explanations/how-workflows-work — How Workflows Work（checkpoint 机制），访问 2026-08-23
[^56^]: https://docs.dbos.dev/python/tutorials/queue-tutorial — Queues & Concurrency，访问 2026-08-23
[^57^]: https://docs.dbos.dev/python/tutorials/scheduled-workflows — Scheduling Workflows，访问 2026-08-23
[^58^]: https://docs.dbos.dev/production/workflow-recovery — Workflow Recovery，访问 2026-08-23
[^59^]: https://docs.dbos.dev/python/tutorials/upgrading-workflows — Upgrading Workflow Code（patching/versioning），访问 2026-08-23
[^60^]: https://docs.dbos.dev/python/tutorials/workflow-communication — Communicating with Workflows（send/recv/events/streams），访问 2026-08-23
[^61^]: https://docs.dbos.dev/python/tutorials/logging-and-tracing — Logging & Tracing（OTel），访问 2026-08-23
[^62^]: https://docs.dbos.dev/ai/debugging — Observability & Reproducibility（fork 复现失败），访问 2026-08-23
[^63^]: https://docs.dbos.dev/production/metrics — Metrics（Conductor Prometheus endpoint），访问 2026-08-23
[^64^]: https://docs.dbos.dev/explanations/system-tables — DBOS System Database（表结构 + PL/pgSQL），访问 2026-08-23
[^65^]: https://docs.dbos.dev/python/tutorials/workflow-management — Workflow Management（cancel/resume/fork/attributes），访问 2026-08-23
[^79^]: https://docs.dbos.dev/why-dbos — Why DBOS?（定位与竞品对比），访问 2026-08-23
[^80^]: https://docs.dbos.dev/production/conductor — DBOS Conductor（控制面架构，out-of-band），访问 2026-08-23
