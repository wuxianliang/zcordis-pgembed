# 维度03：DBOS Transact (TS) 系统数据库真实表结构（DDL）

- 仓库：`dbos-inc/dbos-transact-ts`，分支 `main`（tree sha `f4e76a0…`）
- 访问日期：2026-08-23
- 核心结论：系统表 DDL **不是**以 .sql 文件存在，而是作为 SQL 字符串内嵌在 `src/sysdb_migrations/internal/migrations.ts` 的迁移数组里，按序执行后收敛为最终 schema；`schemas/system_db_schema.ts` 给出对应的 TypeScript interface（可用于交叉验证列名）。

## 0. 命名与迁移机制约定

- **Schema 名**：默认 `dbos`，可通过配置 `system_database_schema_name` 覆盖（dbos-config.schema.json：「The schema name for DBOS system tables (default: 'dbos')」）[^3^]。所有 DDL 都用参数化的 `"${schemaName}"`。
- **数据库**：由配置项 `system_database_url` 指定连接 URL[^3^]；系统库与应用（用户）数据库分离，应用库中仅有用户业务表 + `transaction_completions`（datasource 侧，不在本维度）。
- **迁移机制**：`src/sysdb_migrations/migration_runner.ts` + `src/sysdb_migrations/internal/migrations.ts`。`export const SHARED_MIGRATION_BASE = 100`（migration_runner.ts:7）[^2^]：
  - 索引 0–99 为各语言 SDK 各自历史迁移（TS 实际定义 ~50 条，其余用空迁移 padding 到 99）；
  - 索引 ≥100 为「shared migrations」，**所有语言 SDK 在同一索引上定义完全相同的 DDL**，使多语言应用可共享同一个系统库（migrations.ts 注释原文：「Migrations from SHARED_MIGRATION_BASE on, defined identically by every SDK at the same index」）[^1^]。
  - 版本记录表：`dbos.dbos_migrations (version bigint PRIMARY KEY)`[^1^]。
  - `online: true` 标记的迁移用 `CREATE INDEX CONCURRENTLY`（CockroachDB 下省略关键字）做在线建索引。

## 1. `dbos.workflow_status`（最终态逐列）

初始创建（20240123183021_tables）：`workflow_uuid text PK, status, name, authenticated_user, assumed_role, authenticated_roles, request, output, error, executor_id` 全为 text[^1^]，之后经多次 ALTER 收敛为：

| 列 | 类型 | 约束/默认 | 来源迁移 |
|---|---|---|---|
| workflow_uuid | TEXT | PRIMARY KEY | 初始 |
| status | TEXT | | 初始；索引 idx_workflow_status_failed 部分索引 |
| name | TEXT | | 初始 |
| authenticated_user | TEXT | | 初始 |
| assumed_role | TEXT | | 初始 |
| authenticated_roles | TEXT | 序列化角色列表 | 初始 |
| request | TEXT | 序列化 HTTPRequest | 初始 |
| output | TEXT | | 初始 |
| error | TEXT | | 初始 |
| executor_id | TEXT | local 或 microVM ID | 初始；原索引 workflow_status_executor_id_index 后被 DROP |
| created_at | BIGINT | NOT NULL DEFAULT (EXTRACT(EPOCH FROM now())*1000)::bigint | 20240124015239 |
| updated_at | BIGINT | 同上 NOT NULL DEFAULT | 20240124015239 |
| application_version | TEXT | | 20240516004341 |
| application_id | TEXT | | 20240516004341 |
| class_name | VARCHAR(255) | DEFAULT NULL | 20240517000000 |
| config_name | VARCHAR(255) | DEFAULT NULL | 20240517000000 |
| recovery_attempts | BIGINT | DEFAULT '0' | 20240621000000 |
| queue_name | TEXT | DEFAULT NULL | 20240924000000 |
| workflow_timeout_ms | BIGINT | | 20252505000000 |
| workflow_deadline_epoch_ms | BIGINT | | 20252505000000 |
| inputs | TEXT | NULL（序列化 JSON args） | 20252523000000 |
| started_at_epoch_ms | BIGINT | NULL | 20252528000000 |
| deduplication_id | TEXT | NULL | 20252528000000 |
| priority | INT4 | NOT NULL DEFAULT '0' | 20252528000000 |
| queue_partition_key | TEXT | | 20252810000000 |
| forked_from | TEXT | | 无名迁移 |
| owner_xid | VARCHAR(40) | DEFAULT NULL | 无名迁移 |
| parent_workflow_id | TEXT | DEFAULT NULL | 无名迁移 |
| serialization | TEXT | DEFAULT NULL（如 'portable_json'） | 无名迁移 |
| delay_until_epoch_ms | BIGINT | DEFAULT NULL | 无名迁移 |
| was_forked_from | BOOLEAN | NOT NULL DEFAULT FALSE | 无名迁移 |
| rate_limited | BOOLEAN | NOT NULL DEFAULT FALSE | 无名迁移 |
| completed_at | BIGINT | | 无名迁移 |
| attributes | JSONB | | 无名迁移（GIN 部分索引） |
| schedule_name | TEXT | | 无名迁移 |
| debounce_deadline_epoch_ms | BIGINT | DEFAULT NULL | 无名迁移 |
| is_debounced | BOOLEAN | NOT NULL DEFAULT FALSE | 无名迁移 |
| application_name | TEXT | DEFAULT NULL（NULL=未认领，任何 app 可认领） | shared 100 |

索引（最终存留）：主键 (workflow_uuid)；`workflow_status_created_at_index (created_at)`；`uq_workflow_status_dedup_id UNIQUE (queue_name, deduplication_id) WHERE deduplication_id IS NOT NULL`；`idx_workflow_status_delayed (delay_until_epoch_ms) WHERE status='DELAYED'`；`idx_workflow_status_forked_from (forked_from) WHERE forked_from IS NOT NULL`；`idx_workflow_status_parent_workflow_id (parent_workflow_id) WHERE parent_workflow_id IS NOT NULL`；`idx_workflow_status_pending (created_at) WHERE status='PENDING'`；`idx_workflow_status_failed (status, created_at) WHERE status IN ('ERROR','CANCELLED','MAX_RECOVERY_ATTEMPTS_EXCEEDED')`；`idx_workflow_status_in_flight (queue_name,status,priority,created_at) WHERE status IN ('ENQUEUED','PENDING')`；`idx_workflow_status_rate_limited (queue_name,started_at_epoch_ms) WHERE rate_limited=TRUE`；`idx_workflow_status_completed_at (completed_at) WHERE completed_at IS NOT NULL`；`idx_workflow_status_started_at (started_at_epoch_ms) WHERE started_at_epoch_ms IS NOT NULL`；`idx_workflow_status_attributes GIN (attributes) WHERE attributes IS NOT NULL`；`idx_workflow_status_schedule_name (schedule_name) WHERE schedule_name IS NOT NULL`；`idx_workflow_status_partition_dequeue_v2 (queue_name,status,queue_partition_key,priority,created_at,workflow_uuid) WHERE status IN ('ENQUEUED','PENDING') AND queue_partition_key IS NOT NULL`[^1^]。

TS 接口（schemas/system_db_schema.ts:3-42）另含 `attributes?: Record<string,unknown>|null` 注释「stored as JSONB」，与 DDL 一致[^4^]。

## 2. `dbos.operation_outputs`

```sql
create table dbos.operation_outputs (
  workflow_uuid text not null,
  function_id   int4 not null,
  output text, error text,
  constraint operation_outputs_pkey primary key (workflow_uuid, function_id));
-- 后续 ALTER:
add column function_name text not null default '';        -- 20250312171547
add column child_workflow_id text;                        -- 20250319190617
add column started_at_epoch_ms bigint, completed_at_epoch_ms bigint;
add column serialization text default null;
add column application_name text default null;            -- shared 104
-- 约束/索引：
foreign key (workflow_uuid) references workflow_status(workflow_uuid) on update cascade on delete cascade; -- 20240205223925
create index idx_operation_outputs_completed_at_function_name on (completed_at_epoch_ms, function_name);
```
[^1^]

## 3. `dbos.workflow_events`

```sql
create table dbos.workflow_events (
  workflow_uuid text not null, key text not null, value text not null,
  constraint workflow_events_pkey primary key (workflow_uuid, key));
add column serialization text default null;
foreign key (workflow_uuid) references workflow_status(workflow_uuid) on update cascade on delete cascade;
```
曾有的 `dbos_workflow_events_trigger`（pg_notify 'dbos_workflow_events_channel'）在迁移 `20250716_drop_workflow_events_trigger` 中被删除（事件通知改为写入端合并）[^1^]。

## 4. `dbos.notifications`

```sql
create table dbos.notifications (
  destination_uuid text not null, topic text, message text not null,
  created_at_epoch_ms bigint not null default (EXTRACT(EPOCH FROM now())*1000)::bigint);
-- 后续：
add column message_uuid text not null default uuid_generate_v4();  -- 依赖 create extension "uuid-ossp"
add constraint notifications_pkey primary key (message_uuid);      -- 20240201213211
foreign key (destination_uuid) references workflow_status(workflow_uuid) on update cascade on delete cascade;
add column serialization text default null;
add column consumed boolean not null default false;
create index idx_notifications on (destination_uuid, topic);  -- （早期 idx_workflow_topic 同列）
```
触发器 `dbos_notifications_trigger`（INSERT 后 pg_notify 'dbos_notifications_channel'，payload = destination_uuid||'::'||topic）**仍保留**（notifications 可从任意进程发送）[^1^]。

## 5. 其他系统表（最终存留）

### `dbos.workflow_events_history`
```sql
CREATE TABLE dbos.workflow_events_history (
  workflow_uuid TEXT NOT NULL, function_id INT4 NOT NULL,
  key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (workflow_uuid, function_id, key),
  FOREIGN KEY (workflow_uuid) REFERENCES workflow_status(workflow_uuid) ON UPDATE CASCADE ON DELETE CASCADE);
-- 后续 add column serialization TEXT DEFAULT NULL
```
[^1^]

### `dbos.streams`
```sql
create table dbos.streams (
  workflow_uuid text not null, key text not null, value text not null, offset int4 not null,
  constraint streams_pkey primary key (workflow_uuid, key, offset));
foreign key (workflow_uuid) references workflow_status(workflow_uuid) on update cascade on delete cascade;
add column function_id int4 not null default 0;
add column serialization text default null;
```
streams 的 NOTIFY 触发器在 `20250714_drop_streams_trigger` 中被删除[^1^]。

### `dbos.event_dispatch_kv`
```sql
create table dbos.event_dispatch_kv (
  service_name text not null, workflow_fn_name text not null, key text not null,
  value text, update_seq decimal(38,0), update_time decimal(38,15),
  constraint event_dispatch_kv_pkey primary key (service_name, workflow_fn_name, key));
```
（20241009150000）[^1^]

### `dbos.workflow_schedules`
```sql
CREATE TABLE dbos.workflow_schedules (
  schedule_id TEXT PRIMARY KEY,
  schedule_name TEXT NOT NULL UNIQUE,
  workflow_name TEXT NOT NULL,
  workflow_class_name TEXT,
  schedule TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  context TEXT NOT NULL);
-- 后续 add: last_fired_at TEXT DEFAULT NULL; automatic_backfill BOOLEAN NOT NULL DEFAULT FALSE;
--          cron_timezone TEXT DEFAULT NULL; queue_name TEXT DEFAULT NULL;
--          application_name TEXT DEFAULT NULL   (shared 102)
```
[^1^]

### `dbos.application_versions`
```sql
CREATE TABLE dbos.application_versions (
  version_id TEXT NOT NULL, version_name TEXT NOT NULL UNIQUE,
  version_timestamp BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM now())*1000.0)::bigint,
  created_at BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM now())*1000.0)::bigint,
  CONSTRAINT application_versions_pkey PRIMARY KEY (version_id));
-- shared 103: add column application_name TEXT DEFAULT NULL
-- shared 106: unique index uq_application_versions_owner_version (application_name, version_name) WHERE application_name IS NOT NULL
-- shared 107: unique index uq_application_versions_unclaimed_version (version_name) WHERE application_name IS NULL
```
[^1^]

### `dbos.queues`
```sql
CREATE TABLE dbos.queues (
  queue_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
  name TEXT NOT NULL UNIQUE,
  concurrency INT4, worker_concurrency INT4,
  rate_limit_max INT4, rate_limit_period_sec DOUBLE PRECISION,
  priority_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  partition_queue BOOLEAN NOT NULL DEFAULT FALSE,
  polling_interval_sec DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at BIGINT NOT NULL DEFAULT ..., updated_at BIGINT NOT NULL DEFAULT ...);
-- shared 101: application_name TEXT DEFAULT NULL
-- shared 108: partition_concurrency INT4, partition_worker_concurrency INT4,
--             partition_rate_limit_max INT4, partition_rate_limit_period_sec DOUBLE PRECISION
```
[^1^]

### `dbos.dbos_migrations`
`version bigint not null, primary key (version)` — 迁移版本记录[^1^]。

## 6. 已被 DROP 的历史表（注意！勿按旧文档对照）

迁移 `20250725_drop_consolidated_tables` 明确删除了三张表（注释：「Long-abandoned tables whose contents moved onto workflow_status」）[^1^]：
- `dbos.workflow_inputs`（原 workflow_uuid PK, inputs text）→ 合并入 workflow_status.inputs
- `dbos.workflow_queue`（原 queue_name, workflow_uuid PK, created/started/completed_at_epoch_ms, executor_id, deduplication_id, priority）→ 合并入 workflow_status 的 queue_* 列
- `dbos.scheduler_state`（原 workflow_fn_name PK, last_run_time bigint）→ 废弃

## 7. 数据库内建函数（对 pg_cordis 有参考价值）

- `dbos.enqueue_workflow(workflow_name, queue_name, positional_args JSON[], named_args JSON, class_name, config_name, workflow_id, app_version, timeout_ms BIGINT, deadline_epoch_ms BIGINT, deduplication_id, priority INT4, queue_partition_key, authenticated_user, authenticated_roles, delay_until_epoch_ms BIGINT, application_name) RETURNS TEXT` — plpgsql，向 workflow_status 插入 'ENQUEUED'/'DELAYED' 行，ON CONFLICT (workflow_uuid) DO UPDATE updated_at；unique_violation 转为 'DBOS queue duplicated'；非 CockroachDB 时 SET search_path = pg_catalog, pg_temp[^1^]。
- `dbos.send_message(destination_id, message JSON, topic, message_id) RETURNS VOID` — 插入 notifications，ON CONFLICT (message_uuid) DO NOTHING；topic 空时存 `'__null__topic__'`；serialization='portable_json'[^1^]。
- `dbos.notifications_function()` 触发器函数（保留）；workflow_events/streams 的触发器已删。

## 8. 未获取到 / 备注

- `dbos.workflow_queue`、`dbos.scheduler_state`、`dbos.workflow_inputs`：**当前 main 分支已不存在**（见 §6），若 pg_cordis 对照旧文档需注意。
- TS 接口中的 `step_info`、`event_dispatch_kv` 的反序列化视图等仅为代码类型，无额外表。
- 未抓取每个迁移的独立文件（不存在；全部在 migrations.ts 一个文件内）。

## 引用来源

[^1^]: src/sysdb_migrations/internal/migrations.ts（main, 41,977 bytes）— https://github.com/dbos-inc/dbos-transact-ts/blob/main/src/sysdb_migrations/internal/migrations.ts ／ raw: https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/sysdb_migrations/internal/migrations.ts （访问 2026-08-23）
[^2^]: src/sysdb_migrations/migration_runner.ts（SHARED_MIGRATION_BASE=100，L7）— https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/sysdb_migrations/migration_runner.ts （访问 2026-08-23）
[^3^]: dbos-config.schema.json（system_database_url / system_database_schema_name default 'dbos'）— https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/dbos-config.schema.json （访问 2026-08-23）
[^4^]: schemas/system_db_schema.ts（TS 接口逐列定义）— https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/schemas/system_db_schema.ts （访问 2026-08-23）
