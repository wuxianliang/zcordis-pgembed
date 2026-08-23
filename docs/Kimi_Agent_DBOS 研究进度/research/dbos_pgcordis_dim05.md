# DBOS Transact (TypeScript) 源码研究 — pg_cordis 维度 05

研究对象：`dbos-inc/dbos-transact-ts`（main 分支），系统库 schema 见 `schemas/system_db_schema.ts`[^1^]，DDL 迁移见 `src/sysdb_migrations/internal/migrations.ts`[^2^]，核心实现见 `src/system_database.ts`[^3^]。访问日期均为 2026-08-23。

---

## Q4 Workflow 版本化（application version）

### 记录与固化

- 每个 workflow 启动时在 `workflow_status` 表写入 `application_version` 列（`schemas/system_db_schema.ts` 中 `application_version?: string`）[^1^]。
- 版本值计算：若配置未提供 `applicationVersion`（可用 `DBOS__APPVERSION` 环境变量/配置固定），则启动时由 `DBOSExecutor.computeAppVersion()`（`src/dbos-executor.ts` L1591-1606）对所有已注册 workflow 函数源码 `.toString()` 排序后做 MD5（混入 DBOS 版本号与应用名），代码一变版本即变[^4^]。
- 版本注册到系统表：`application_versions (version_id, version_name, version_timestamp, created_at, application_name)`[^1^]，由 `SystemDatabase.createApplicationVersion()`（`src/system_database.ts` L4693 附近）以事务写入：先 `UPDATE application_versions SET application_name=$1 WHERE version_name=$2 AND application_name IS NULL` 认领无归属行，失败则 `INSERT ... ON CONFLICT DO NOTHING`，再由 `#resolveRowOwner` 校验归属冲突[^3^]。
- “最新版本”由 `updateApplicationVersionTimestamp()` 推进，`#latestApplicationVersionName()` 用 `SELECT version_name FROM application_versions ... ORDER BY version_timestamp DESC LIMIT 1` 取回（`src/system_database.ts` L963-975）[^3^]。

### 恢复时的版本匹配

- 恢复只取**同版本**的 PENDING workflow：`getPendingWorkflows` / `reenqueueWorkflowsForRecovery`（`src/system_database.ts` L1383-1427）：
  ```sql
  UPDATE workflow_status SET started_at_epoch_ms=NULL, status='ENQUEUED', queue_name=COALESCE(queue_name,$2)
  WHERE status='PENDING' AND executor_id=$4 AND application_version=$5 ...
  ```
  `DBOSExecutor.recoverPendingWorkflows()` 用当前 `globalParams.appVersion` 过滤（`src/dbos-executor.ts` L1340-1360）[^3^][^4^]。
- **版本不匹配即不恢复**（防止旧 checkpoint 在新代码上重放失败）。官方推荐 blue-green：旧版本进程保留直到旧 workflow 排空；新任务经 `getLatestApplicationVersion` 路由到最新版本[^5^]。
- 出队端同样做版本路由：dequeue SQL 中 `versionClause`——若本进程即最新版本则 `(application_version=$3 OR application_version IS NULL)`，否则只取 `application_version=$3`（`src/system_database.ts` L3564-3568）[^3^]。调度的 workflow 也总是入队到属主应用的最新版本（`src/scheduler/scheduler.ts` `enqueueScheduledWorkflow`）[^6^]。
- **patch 到旧版本靠 fork 而非原地改**：`SystemDatabase.forkWorkflow` / `bulkForkWorkflows`（`src/system_database.ts` L1872 起）从事务中复制原 workflow 的 `workflow_status` 行与 `operation_outputs` 中 `< startStep` 的 checkpoint，生成新 `workflow_uuid`、`status='ENQUEUED'`、可指定新 `applicationVersion`，并记录 `forked_from` / `was_forked_from`；`forkFromFailure` 支持从最后失败步/最后步/指定步名 fork[^3^][^7^]。文档明确这是“patching”因旧版本 bug 失败的 workflow 的手段[^8^]。
- 另有不依赖版本切换的 **Workflow Patching** 机制：`DBOSExecutor.checkPatch()`（`src/system_database.ts` L1607 起）把 patch 点作为名为 `DBOS.patch-<name>` 的特殊条目写入/查询 `operation_outputs`——重放时按历史记录决定走旧/新代码路径；支持 `deprecatePatch`（`enablePatching` 配置项）[^3^][^9^]。

---

## Q7 通知与队列

### notifications 表与 exactly-once

表结构演进（`src/sysdb_migrations/internal/migrations.ts`）[^2^]：
- 初始：`notifications (destination_uuid, topic, message, created_at_epoch_ms)`，无 PK；后续迁移加 `message_uuid`（默认 `uuid_generate_v4()`，设为主键）、`consumed BOOLEAN NOT NULL DEFAULT false`、索引 `idx_notifications(destination_uuid, topic)`、外键 `destination_uuid → workflow_status.workflow_uuid ON DELETE CASCADE`。
- 另有 `notifications_function()` TRIGGER 在 INSERT 后 `pg_notify('dbos_notifications_channel', payload)`，用于唤醒等待中的 recv（性能优化，正确性不依赖它）[^2^]。

**send**（`SystemDatabase.send`，`src/system_database.ts` L2640 起）：在 READ COMMITTED 事务中与 step 结果记录（`#runAndRecordResult` 写 `operation_outputs`）同事务提交：
```sql
INSERT INTO notifications (destination_uuid, topic, message, serialization, message_uuid)
VALUES ($1,$2,$3,$4,$5) ON CONFLICT (message_uuid) DO NOTHING;
```
`message_uuid = <idempotencyKey>::<destinationID>`——**幂等键+目标 workflow 作主键去重**，重复 send 被吸收；与 workflow step checkpoint 原子提交保证不重发[^3^]。

**recv**（`SystemDatabase.recv`，L2733 起）：
1. 先查 `operation_outputs`——该 functionID 若已记录过 recv 结果则直接返回（重放不消费第二条）；
2. 轮询/`pg_notify` 等待 `consumed=false` 消息；
3. 事务内“原子消费”：
```sql
UPDATE notifications SET consumed=true
WHERE destination_uuid=$1 AND topic=$2 AND consumed=false
  AND message_uuid = (SELECT message_uuid FROM notifications
                      WHERE destination_uuid=$1 AND topic=$2 AND consumed=false
                      ORDER BY created_at_epoch_ms ASC LIMIT 1)
RETURNING message, serialization;
```
4. 同事务把 recv 结果写入 `operation_outputs` 后 COMMIT。**exactly-once 的本质 = 单条 UPDATE 的原子消费 + recv 结果作为 workflow checkpoint 固化**；崩溃恢复后重放直接读 checkpoint，不会再取新消息[^3^]。

### 队列的表实现

- **不是独立的队列表**：队列 = `workflow_status` 表上 `status='ENQUEUED' AND queue_name=?` 的行（早期版本有 `workflow_queue` 表，迁移 L131；当前版本队列元数据存 `queues (queue_id, name, concurrency, worker_concurrency, rate_limit_max, rate_limit_period_sec, priority_enabled, partition_queue, ..., polling_interval_sec)`，L4893 注册时 INSERT）[^1^][^2^][^3^]。
- 出队 `findAndMarkStartableWorkflows`（`src/system_database.ts` L3440-3645）**是用了 `FOR UPDATE SKIP LOCKED`**：
  ```sql
  SELECT workflow_uuid FROM workflow_status
  WHERE status=$1 AND queue_name=$2 AND <versionClause> AND <appScope>
  ORDER BY priority ASC, created_at ASC
  LIMIT <maxTasks>
  FOR UPDATE SKIP LOCKED;   -- 有共享预算(全局并发/限速)时改用 FOR UPDATE NOWAIT + REPEATABLE READ/SERIALIZABLE
  ```
  随后同事务 `UPDATE ... SET status='PENDING', executor_id=$2, application_version=$3, started_at_epoch_ms=..., rate_limited=$4, recovery_attempts=recovery_attempts+1 WHERE workflow_uuid=ANY(...) AND status='ENQUEUED' RETURNING workflow_uuid` 二次校验（防止锁与更新之间状态被改）[^3^]。
- **并发/限速落库执行**：
  - `workerConcurrency`：进程内存计数（注释明确“avoids a DB round trip”）；`concurrency`（全局）：`SELECT COUNT(*) FROM workflow_status WHERE queue_name=$1 AND status='PENDING'` 落库统计；
  - `rateLimit`（滚动窗口）：`SELECT COUNT(*) ... WHERE queue_name=$1 AND rate_limited=TRUE AND status NOT IN ('ENQUEUED','DELAYED') AND started_at_epoch_ms > (now_ms - period)`——启动时间戳用数据库时钟写入，跨进程一致；
  - 共享预算时事务隔离升级为 REPEATABLE READ（跨分区写偏斜时 SERIALIZABLE），锁改 NOWAIT 让重叠出队者中止而非双花预算[^3^]。
- **优先级**：列 `workflow_status.priority`，出队 `ORDER BY priority ASC, created_at ASC`（数值小者优先，FIFO 打破平局）[^3^]。
- **分区队列**：`queue_partition_key` 列 + 递归 CTE 做 loose index scan 找分区、LATERAL 取每分区 head-of-line；候选集固定后 `FOR UPDATE SKIP LOCKED` 锁定（注释特别说明不能对 LIMIT 查询用 SKIP LOCKED，否则滑过被锁 head 导致乱序），分区级并发/限速各有独立列[^3^]。
- 恢复时 workflow 重新入队（`reenqueueWorkflowsForRecovery`），由队列的原子出队保证恰好一个 runner 接管[^3^]。

---

## Q8 调度器（cron）

- **调度定义落表** `workflow_schedules (schedule_id, schedule_name UNIQUE, workflow_name, workflow_class_name, schedule /*cron*/, status /*ACTIVE|PAUSED*/, context, last_fired_at, automatic_backfill, cron_timezone, queue_name, application_name)`（迁移 L253 起；`src/system_database.ts` L4460-4673 的 CRUD，applySchedules 用 `INSERT ... ON CONFLICT (schedule_name)` 保留运行时状态、只更新定义字段）[^1^][^2^][^3^]。
- **执行模型是“进程内循环 + 表做协调”，不是数据库轮询到期任务**：`DynamicSchedulerLoop`（`src/scheduler/scheduler.ts`）每 ~30s（启动后第一分钟每 1s）`listSchedules` 拉 ACTIVE 调度，为每个调度起一个本地循环；用 `TimeMatcher`（`src/scheduler/crontab.ts`）算 `nextWakeupTime`，睡到点（加 ≤10% 且 ≤10s 的随机抖动防惊群）再触发[^6^]。
- **防重复触发 = 确定性 workflow ID + 主键**：
  ```ts
  const workflowID = `sched-${scheduleName}-${date.toISOString()}`;
  const existing = await DBOS.getWorkflowStatus(workflowID);   // 幂等检查（仅为性能）
  await enqueueScheduledWorkflow(...);                          // initWorkflowStatus 以 workflow_uuid 主键去重
  await systemDatabase.updateLastFiredAt(scheduleName, date.toISOString());
  ```
  多 executor 同时到点只会有一个 INSERT 成功；`last_fired_at` 记录上次触发时间[^6^]。
- **backfill**：`automatic_backfill=true` 且 `lastFiredAt < now` 时，`backfillSchedule` 从 lastFiredAt 起按 cron 逐次补发（同样用确定性 ID 去重）；`triggerSchedule` 手动触发用 `sched-<name>-trigger-<ts>`[^6^]。
- 旧版（装饰器 `@DBOS.scheduled`）用 `scheduler_state (workflow_fn_name PK, last_run_time)` 表记录上次触发（迁移 L108），思路相同[^2^]。
- 触发的 workflow 以 `ENQUEUED` 写入 `workflow_status`（入内部队列或指定 `queue_name`），执行仍走 Q7 的队列出队路径，并固定到属主应用最新版本[^6^]。

---

## Q5 补偿（saga / undo）

- **源码中没有 saga/undo/补偿框架**：对 `src/*.ts` 全量 grep `compensat|saga|undo` 无任何匹配（除无关词）。`operation_outputs` 只记 output/error，无补偿栈；`workflow_status` 无 compensation 字段[^3^]。
- **官方立场：手写补偿步骤，靠 durable execution 保证补偿本身执行完**。DBOS 无 saga DSL；推荐模式是在 workflow 的失败分支显式调用 undo step（如 demo `widget-store` 的 `undo_reserve_inventory()`），补偿本身也是一个 checkpointed step，因此崩溃恢复后补偿仍会跑到完成；补偿需自行做到幂等[^10^][^11^]。
- 运维层面的“事后补偿/修复”则靠 **fork**：从失败步 fork 到新代码版本重跑（见 Q4），官方博客明确把 fork 定位为对下游故障、代码 bug 的批量修复手段[^7^]。

对 pg_cordis 的可借鉴点：补偿不做框架，文档约定“undo step 也是 step、结果进 checkpoint 表”；修复失败执行用“复制 status 行 + 复制 < N 的 step checkpoint + 新 ID”的 fork SQL。

---

## 引用

[^1^]: `schemas/system_db_schema.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/schemas/system_db_schema.ts ，访问 2026-08-23。
[^2^]: `src/sysdb_migrations/internal/migrations.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/sysdb_migrations/internal/migrations.ts ，访问 2026-08-23。
[^3^]: `src/system_database.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/system_database.ts ，访问 2026-08-23。
[^4^]: `src/dbos-executor.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/dbos-executor.ts ，访问 2026-08-23。
[^5^]: DBOS 文档 “Upgrading Workflow Code — Versioning”, https://docs.dbos.dev/typescript/tutorials/upgrading-workflows ，访问 2026-08-23。
[^6^]: `src/scheduler/scheduler.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/scheduler/scheduler.ts ，访问 2026-08-23。
[^7^]: DBOS 博客 “Handling Workflow Failures with Forks”, https://www.dbos.dev/blog/handling-failures-workflow-forks ，访问 2026-08-23。
[^8^]: DBOS 文档 “Workflow Management — Forking Workflows”, https://docs.dbos.dev/typescript/tutorials/workflow-management ，访问 2026-08-23。
[^9^]: DBOS 博客 “What's New in DBOS March 2026 — Workflow Patching”, https://www.dbos.dev/blog/dbos-new-features-march-2026 ，访问 2026-08-23。
[^10^]: Resonate “DBOS vs Resonate — Saga / compensation”（引 DBOS widget-store 补偿模式）, https://docs.resonatehq.io/evaluate/coming-from/dbos ，访问 2026-08-23。
[^11^]: resonate-skills “migrate-from-dbos — Pattern: Saga / compensation”（“DBOS has no saga DSL”）, https://github.com/resonatehq/resonate-skills/blob/main/resonate-migrate-from-dbos/SKILL.md ，访问 2026-08-23。
