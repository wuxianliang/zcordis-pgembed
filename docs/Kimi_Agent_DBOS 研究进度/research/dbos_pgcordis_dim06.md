# DBOS 系统表结构与恢复机制：Python (dbos-transact-py) vs TypeScript (dbos-transact-ts) 对照

研究目的：为 pg_cordis（PostgreSQL 原生 agent 插件运行时）提供 DBOS 系统表结构的多语言一致性证据。
访问日期：2026-08-23。分支：两仓库均为 `main`。

来源文件：
- Python: `dbos/_schemas/system_database.py`（SQLAlchemy Table 定义，即 DDL 真源）[^48^]
- Python: `dbos/_sys_db.py`（SystemDatabase 抽象基类：步骤记录、恢复扫描、出队、版本化）[^50^]
- Python: `dbos/_recovery.py`（启动恢复循环）[^49^]
- TS: `src/system_database.ts`（内联 SQL）[^51^]
- TS: `schemas/system_db_schema.ts`（行类型接口）[^52^]

Python 版没有独立 .sql DDL 文件：表结构由 SQLAlchemy `MetaData(schema=SCHEMA_PLACEHOLDER)` 声明，经 `schema_translate_map` 映射到实际 schema（默认 `dbos`），由 `run_migrations()` 迁移应用（`_migration.py`，本次未逐条展开）[^48^][^50^]。

---

## 1. 系统表完整 DDL（Python 版，逐列）

### 1.1 workflow_status（schema 默认 `dbos`，后缀 `_dbos_sys` 为系统库命名约定）[^48^]

| 列 | 类型 | 约束/默认 |
|---|---|---|
| workflow_uuid | Text | PRIMARY KEY |
| status | Text | nullable |
| name | Text | nullable |
| authenticated_user | Text | nullable |
| assumed_role | Text | nullable |
| authenticated_roles | Text | nullable（JSON 列表） |
| output | Text | nullable（序列化结果） |
| error | Text | nullable |
| executor_id | Text | nullable |
| created_at | BigInteger | NOT NULL（epoch ms） |
| updated_at | BigInteger | NOT NULL |
| application_version | Text | nullable |
| application_id | Text | nullable |
| class_name | String(255) | nullable |
| config_name | String(255) | nullable |
| recovery_attempts | BigInteger | nullable |
| queue_name | Text | nullable |
| workflow_timeout_ms | BigInteger | nullable |
| workflow_deadline_epoch_ms | BigInteger | nullable |
| started_at_epoch_ms | BigInteger | nullable（出队时写入） |
| deduplication_id | Text | nullable |
| inputs | Text | （序列化输入） |
| priority | Integer | NOT NULL |
| queue_partition_key | Text | nullable |
| forked_from | Text | nullable |
| was_forked_from | Boolean | NOT NULL, default false |
| owner_xid | Text | nullable（事务所有权令牌） |
| parent_workflow_id | Text | nullable |
| serialization | Text | nullable |
| delay_until_epoch_ms | BigInteger | nullable |
| rate_limited | Boolean | NOT NULL, default false |
| completed_at | BigInteger | nullable |
| attributes | JSON/JSONB(pg) | nullable |
| schedule_name | Text | nullable |
| debounce_deadline_epoch_ms | BigInteger | nullable |
| is_debounced | Boolean | NOT NULL, default false |
| application_name | Text | nullable（NULL=未被认领，任何应用可认领） |

索引（Python 声明）[^48^]：`workflow_status_created_at_index`(created_at)；`idx_workflow_status_delayed`(delay_until_epoch_ms WHERE status='DELAYED')；`idx_workflow_status_pending`(created_at WHERE status='PENDING')；`idx_workflow_status_failed`(status, created_at WHERE status IN ERROR/CANCELLED/MAX_RECOVERY_ATTEMPTS_EXCEEDED)；`idx_workflow_status_in_flight`(queue_name,status,priority,created_at WHERE status IN ENQUEUED/PENDING)；`idx_workflow_status_rate_limited`(queue_name,started_at_epoch_ms WHERE rate_limited)；`idx_workflow_status_completed_at`（部分）；`idx_workflow_status_started_at`（部分）；`idx_workflow_status_attributes`(GIN, pg-only)；`idx_workflow_status_schedule_name`（部分）；`uq_workflow_status_dedup_id`(queue_name,deduplication_id) UNIQUE WHERE deduplication_id IS NOT NULL。（代码另引用 `idx_workflow_status_partition_dequeue_v2`，应定义于迁移文件，本次未单独展开迁移 SQL。）

### 1.2 operation_outputs[^48^]
workflow_uuid (Text, FK→workflow_status.workflow_uuid ON UPDATE/DELETE CASCADE, NOT NULL)；function_id (Integer, NOT NULL)；function_name (Text, NOT NULL)；output (Text)；error (Text)；child_workflow_id (Text)；started_at_epoch_ms (BigInteger)；completed_at_epoch_ms (BigInteger)；serialization (Text)；application_name (Text)。PRIMARY KEY(workflow_uuid, function_id)。索引 idx_operation_outputs_completed_at_function_name(completed_at_epoch_ms, function_name)。

### 1.3 notifications[^48^]
destination_uuid (Text, FK→workflow_status, NOT NULL)；topic (Text)；message (Text, NOT NULL)；created_at_epoch_ms (BigInteger, NOT NULL, default `(EXTRACT(epoch FROM now())*1000.0)::bigint`)；message_uuid (Text, PK, default gen_random_uuid())；serialization (Text)；consumed (Boolean, NOT NULL, default false)。索引 idx_workflow_topic(destination_uuid, topic)。

### 1.4 workflow_events[^48^]
workflow_uuid (Text, FK)；key (Text, NOT NULL)；value (Text, NOT NULL)；serialization (Text)。PK(workflow_uuid, key)。

### 1.5 workflow_events_history（不可变历史，为 fork 兼容）[^48^]
workflow_uuid (Text, FK)；key (Text, NOT NULL)；value (Text, NOT NULL)；function_id (Integer, NOT NULL)；serialization (Text)。PK(workflow_uuid, key, function_id)。

### 1.6 streams[^48^]
workflow_uuid (Text, FK)；key (Text, NOT NULL)；value (Text, NOT NULL)；offset (Integer, NOT NULL)；function_id (Integer, NOT NULL)；serialization (Text)。PK(workflow_uuid, key, offset)。

### 1.7 workflow_schedules[^48^]
schedule_id (Text, PK)；schedule_name (Text, NOT NULL UNIQUE)；workflow_name (Text, NOT NULL)；workflow_class_name (Text)；schedule (Text, NOT NULL)；status (Text, NOT NULL, default 'ACTIVE')；context (Text, NOT NULL)；last_fired_at (Text)；automatic_backfill (Boolean, NOT NULL, default false)；cron_timezone (Text)；queue_name (Text)；application_name (Text)。

### 1.8 application_versions[^48^]
version_id (Text, PK)；version_name (Text, NOT NULL UNIQUE)；version_timestamp (BigInteger, NOT NULL)；created_at (BigInteger, NOT NULL)；application_name (Text)。两个部分唯一索引：uq_application_versions_owner_version(application_name, version_name WHERE application_name IS NOT NULL) 与 uq_application_versions_unclaimed_version(version_name WHERE application_name IS NULL)。

### 1.9 queues[^48^]
queue_id (Text, PK, default gen_random_uuid()::TEXT)；name (Text, NOT NULL UNIQUE)；concurrency (Integer)；worker_concurrency (Integer)；rate_limit_max (Integer)；rate_limit_period_sec (Float)；priority_enabled (Boolean, NOT NULL, default false)；partition_queue (Boolean, NOT NULL, default false)；partition_concurrency / partition_worker_concurrency (Integer)；partition_rate_limit_max (Integer)；partition_rate_limit_period_sec (Float)；polling_interval_sec (Float, NOT NULL, default 1.0)；created_at、updated_at (BigInteger, NOT NULL)；application_name (Text)。

### 1.10 与 TS 版的列级 diff

TS 行类型在 `schemas/system_db_schema.ts`[^52^]：

- **workflow_status：TS 多一列 `request`**（序列化的 HTTP 请求/事件分发数据），Python 版**没有此列**。其余 36 列两版同名同义（含 delay_until_epoch_ms、rate_limited、completed_at、attributes、schedule_name、debounce_*、is_debounced、application_name、owner_xid、parent_workflow_id、was_forked_from 等全部对齐）。
- **event_dispatch_kv：仅 TS 有**（service_name, workflow_fn_name, key, value, update_time, update_seq）；Python 版无此表（Python 已用 workflow_schedules 持久化调度器替代事件分发器路径）。
- operation_outputs、workflow_events、workflow_events_history、streams、workflow_schedules、application_versions、queues：两版列名完全一致（逐列比对相同，含 application_name 反规范化列与 completed_at_epoch_ms 等）。
- notifications：列一致（TS 接口只列常用子集，但 SQL 使用 destination_uuid/topic/message/serialization/message_uuid/consumed 相同）[^51^][^52^]。
- 索引/迁移级 DDL 的 TS 侧定义位于 `src/sysdb_migrations/internal/migrations`（本次未逐条抓取，标注「迁移 SQL 未获取到」），但所有共享列名、索引名（如 idx_workflow_status_partition_dequeue_v2）在两版代码注释中一致出现，说明迁移同源对齐。

结论：**核心持久化表列级一致**，唯一结构差异是 TS 独有的 `workflow_status.request` 列与 `event_dispatch_kv` 表。对 pg_cordis 而言，若只做步骤检查点/队列/事件语义，可完全忽略这两个 TS 遗留面。

## 2. 步骤执行事务边界（operation_outputs 写入点）[^50^]

- 普通步骤：`call_function_as_step` / `call_coroutine_as_step` 先 `check_operation_execution`（OAOO 检查），**执行 fn() 之后**再单独事务 `record_operation_result`（`engine.begin()` 一事务），输出序列化后写入 operation_outputs——副作用执行与输出记录**不在同一事务**（at-least-once 执行 + 检查点幂等）。
- 事务性步骤：`call_txn_as_step` 在**同一事务**内先 `_check_operation_execution_txn`，再 `op(c)` 执行用户 SQL，再 `_record_operation_result_txn`——副作用与检查点原子提交，exactly-once。TS 对应物 `runTransactionalStep` 结构完全相同（BEGIN READ COMMITTED → 检查 → callback(client) → recordOperationResultInternal → COMMIT）[^51^]。
- 写入语义：`_record_operation_result_txn` 用 `INSERT ... ON CONFLICT (workflow_uuid, function_id) DO UPDATE SET completed_at_epoch_ms = <原值> RETURNING`，若已有行且 completed_at 与本次不同则抛 `DBOSWorkflowConflictIDError`（重复执行检测）；TS `recordOperationResultInternal` 逐字对应（23505/40001 → DBOSWorkflowConflictError）[^50^][^51^]。
- send/setEvent/writeStream/recv_consume 等内置步骤均在**同一事务**内完成"效果写入 + operation_outputs 记录"（如 `recv_consume`：UPDATE notifications SET consumed + 记录结果；`set_event_from_workflow`：双写 workflow_events + workflow_events_history + 记录），与 TS 一致[^50^][^51^]。

## 3. 恢复循环[^49^][^50^]

- 扫描：`get_pending_workflows(executor_id, app_version)` 只扫 `status='PENDING'` 且 `executor_id=<指定执行器>` 且 `application_version=<本进程版本>` 且 application_name 属于本应用（或未认领）的行。启动时 `startup_recovery_thread` 对本执行器后台恢复；`recover_pending_workflows(executor_ids)` 可对多个（死亡）执行器恢复。
- 恢复动作不是直接执行，而是 `reenqueue_for_recovery`：`UPDATE ... SET status='ENQUEUED', started_at_epoch_ms=NULL, queue_name=COALESCE(queue_name, 内部队列) WHERE status='PENDING' AND executor_id IN (...)`——executor_id 谓词使恢复幂等（活执行器一旦出队会改写 executor_id，重复恢复匹配不到行）。随后走队列的原子 ENQUEUED→PENDING 出队，保证恰好一个 runner。
- 跳过已完成步骤：恢复后工作流从头重放，每个步骤先 `check_operation_execution`/`_check_operation_execution_txn` 查 operation_outputs；命中则反序列化已记录 output 直接返回（或重放已记录 error）；function_name 不匹配抛 `DBOSUnexpectedStepError`（检测非确定性代码变更）；workflow 已 CANCELLED 抛 `DBOSWorkflowCancelledError`。
- recovery_attempts 只在出队（ENQUEUED→PENDING flip）时 +1；超过上限由 `dead_letter_workflows` 置 MAX_RECOVERY_ATTEMPTS_EXCEEDED。TS 版机制逐点一致（getPendingWorkflows / reenqueueWorkflowsForRecovery / #getOperationResultAndThrowIfCancelled）[^51^]。

## 4. Workflow 版本化[^48^][^50^][^51^]

- 字段：workflow_status.application_version（行级版本戳）+ application_versions 表（version_id/version_name/version_timestamp/created_at/application_name）。
- 逻辑：dequeue 只领 `application_version = <本进程版本>` 的行；若本进程版本是该应用的 latest（按 version_timestamp 排序，scope=本应用+未认领），NULL 版本的旧行也可被领（升级排空）。恢复（get_pending_workflows）同样按 application_version 过滤——旧版本执行器的 PENDING 工作流不会被新版本进程接管。`create_application_version` / `update_application_version_timestamp`（提升为 latest）带应用所有权冲突检测。TS 版 `#latestApplicationVersionName` 与 versionClause 逻辑完全一致。
- 另有代码级补丁机制 `patch`/`deprecate_patch`（在 operation_outputs 里写 `DBOS.patch-<name>` 标记实现重放兼容），TS 对应 `checkPatch`。

## 引用

[^48^]: dbos-transact-py `dbos/_schemas/system_database.py`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_schemas/system_database.py （访问 2026-08-23)
[^49^]: dbos-transact-py `dbos/_recovery.py`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_recovery.py （访问 2026-08-23)
[^50^]: dbos-transact-py `dbos/_sys_db.py`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_sys_db.py （访问 2026-08-23)
[^51^]: dbos-transact-ts `src/system_database.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/system_database.ts （访问 2026-08-23)
[^52^]: dbos-transact-ts `schemas/system_db_schema.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/schemas/system_db_schema.ts （访问 2026-08-23)
