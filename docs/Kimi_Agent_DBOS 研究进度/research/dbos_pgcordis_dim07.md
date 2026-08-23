# Dim07：Go/Java 版 API 与 schema 一致性对照

> 由只读子代理完成调查，主代理代笔落盘。访问日期：2026-08-23。

## 结论
DBOS 系统表结构已是跨语言"共享稳定规范"，不是各语言各自为政。Go 与 Java 的 PostgreSQL DDL 在核心表与列上高度一致；迁移编号 ≥100（SHARED_MIGRATION_BASE）被明确设计为各 SDK 对齐的共享迁移基线。

## 关键证据

1. Go 与 Java 初始 schema 均含 `workflow_status`、`operation_outputs`、`notifications`、`workflow_events`、`streams`、`event_dispatch_kv`；核心列一致：`workflow_uuid/status/name/output/error/executor_id/application_version/application_id/recovery_attempts/queue_name/inputs/deduplication_id/priority` 等。[^1^][^2^]
2. 后续演进一致：`queues` 表（migration 21）含 `queue_id/name/concurrency/worker_concurrency/rate_limit_*/priority_enabled/partition_queue`；后续增加 `application_name`、`application_versions`、attributes、schedule/debounce 字段。Java migration 42 注释明确："Java debouncer 不用这些列，但 peer SDK sharing this system database does"——共享 schema 约束的直接证据。[^2^]
3. 与 TS/Py 的差异是历史迁移路径而非最终逻辑模型：TS/Python 代码注明较早 migration index 属各语言历史，schema 收敛；从 SHARED_MIGRATION_BASE=100 起各 SDK 在相同 index 定义相同 migration。[^3^][^4^]
4. API 同构：Go `RegisterWorkflow/RunWorkflow/RunAsStep/Send/Recv/SetEvent/GetEvent/Sleep/RegisterQueue/CreateSchedule`；Java `registerWorkflow`/注解代理、`startWorkflow`、`runStep`、`send/recv`、`setEvent/getEvent`、`sleep`、`registerQueue/createSchedule`；对应 TS `DBOS.registerWorkflow/runStep/sleep/send/recv/setEvent/getEvent` 与 Python decorator 风格 API。
5. Go 支持 SQLite：`dbos/driver/sqlite/sqlite.go` 注册 `modernc.org/sqlite`，有独立 SQLite migrations（注释说明移植自 Python SQLite migration，仅方言转换）。修正表述：生产级分布式控制面以 Postgres/CockroachDB 为核心，SQLite 是 Go/Python 的单机/本地可选后端。[^1^]
6. recovery/versioning 一致：启动时登记当前 application version、查 latest version，仅恢复同版本 executor 的 PENDING workflow；重复恢复递增 `recovery_attempts`，超限进入 `MAX_RECOVERY_ATTEMPTS_EXCEEDED`。Go 见 `dbos/recovery.go`、`dbos/internal/sysdb/system_database.go`；Java 见 `DBOSExecutor.java` recovery query、`recoverPendingWorkflows` 与 application-version 检查。

## 参考文献
[^1^]: Go 初始 schema `dbos/internal/sysdb/migrations/1_initial_dbos_schema.sql`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-golang/main/dbos/internal/sysdb/migrations/1_initial_dbos_schema.sql （访问 2026-08-23）
[^2^]: Java `transact/src/main/java/dev/dbos/transact/migrations/MigrationManager.java`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-java/main/transact/src/main/java/dev/dbos/transact/migrations/MigrationManager.java （访问 2026-08-23）
[^3^]: Python `dbos/_migration.py`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_migration.py （访问 2026-08-23）
[^4^]: TS `src/sysdb_migrations/internal/migrations.ts`, https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/sysdb_migrations/internal/migrations.ts （访问 2026-08-23）
