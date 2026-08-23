# absurd 源码研究报告（对照 DBOS，服务于 pg_cordis 参照选型）

调研日期：2026-08-23。仓库：https://github.com/earendil-works/absurd ，默认分支 `main`。所有源码引用均来自 `raw.githubusercontent.com/earendil-works/absurd/main/...`。

## 1. 项目定位 / 作者 / 活跃度 / License

- 一句话定位（README 原文）："Absurd is the simplest durable execution workflow system you can think of. It's entirely based on Postgres and nothing else."[^1^] 整个引擎就是**一个 SQL 文件** `sql/absurd.sql`（3150 行），直接 apply 到任意 PostgreSQL 库，无需任何外部服务[^1^]。
- 作者/背景：组织账号 `earendil-works`；公告博文发在 `lucumr.pocoo.org`（Armin Ronacher，mitsuhiko，Flask 作者）的博客：`https://lucumr.pocoo.org/2025/11/3/absurd-workflows/`（README 链接指向该文）[^1^]。README 自带 AI 使用声明："This codebase has been built with a lot of support of AI. A combination of hand written code, Codex and Claude Code was used"[^1^]。
- 活跃度（GitHub API 2026-08-23 快照）：创建 2025-10-20，最近 push 2026-08-10，**star 2363**，open issues 33，维护活跃[^2^]。
- License：**Apache-2.0**[^2^]。repo 描述："An experiment in durability"[^2^]。
- 辅助组件：`absurdctl`（CLI，schema init/migrate、队列管理、spawn/retry 任务）与 `habitat`（Go + SolidJS 的 Web UI 观测面板）[^1^]。

## 2. 真实表结构 DDL（全部来自 `sql/absurd.sql`，行号对应文件）

全局唯一一张静态表 `absurd.queues`（行 131-150）：

```sql
create table if not exists absurd.queues (
  queue_name text primary key,
  created_at timestamptz not null default absurd.current_time(),
  storage_mode text not null default 'unpartitioned'
    check (storage_mode in ('unpartitioned', 'partitioned')),
  default_partition text not null default 'enabled' check (default_partition in ('enabled','disabled')),
  partition_lookahead interval not null default interval '28 days',
  partition_lookback interval not null default interval '1 day',
  cleanup_ttl interval not null default interval '30 days',
  cleanup_limit integer not null default 1000 check (cleanup_limit >= 1),
  detach_mode text not null default 'none' check (detach_mode in ('none','empty')),
  detach_min_age interval not null default interval '30 days'
);
```

**每个队列动态生成一组表**（`ensure_queue_tables`，行 184-362；前缀注释见行 8-14）：

`t_<queue>` 任务表（行 223-243）：
```sql
task_id uuid primary key,
task_name text not null,
params jsonb not null,
headers jsonb,
retry_strategy jsonb,
max_attempts integer,
cancellation jsonb,
enqueue_at timestamptz not null default absurd.current_time(),
first_started_at timestamptz,
state text not null check (state in ('pending','running','sleeping','completed','failed','cancelled')),
attempts integer not null default 0,
last_attempt_run uuid,
completed_payload jsonb,
cancelled_at timestamptz,
idempotency_key text unique   -- unpartitioned 模式；partitioned 模式无 unique，改用 i_ 侧表
-- unpartitioned 表带 with (fillfactor=70)；partitioned 表 partition by range (task_id)
```

`r_<queue>` 运行表（每次 attempt 一行，行 246-265）：
```sql
run_id uuid primary key,
task_id uuid not null,
attempt integer not null,
state text not null check (state in ('pending','running','sleeping','completed','failed','cancelled')),
claimed_by text,
claim_expires_at timestamptz,
available_at timestamptz not null,
wake_event text,
event_payload jsonb,
started_at timestamptz,
completed_at timestamptz,
failed_at timestamptz,
result jsonb,
failure_reason jsonb,
created_at timestamptz not null default absurd.current_time()
```

`c_<queue>` checkpoint 表（行 268-279）：
```sql
task_id uuid not null,
checkpoint_name text not null,
state jsonb,
status text not null default 'committed',
owner_run_id uuid,
updated_at timestamptz not null default absurd.current_time(),
primary key (task_id, checkpoint_name)
```

`e_<queue>` 事件表（行 282-288）：`event_name text primary key, payload jsonb, emitted_at timestamptz`。

`w_<queue>` 等待注册表（行 291-302）：`task_id uuid, run_id uuid, step_name text, event_name text, timeout_at timestamptz, created_at timestamptz, primary key (run_id, step_name)`。

`i_<queue>` 幂等键侧表（仅 partitioned，行 306-311）：`idempotency_key text primary key, task_id uuid not null`。

索引（行 314-357）：`r_<q>_sai` on `(state, available_at)`；`r_<q>_ti` on `(task_id)`；`r_<q>_cei` on `(claim_expires_at) where state='running' and claim_expires_at is not null`（部分索引，服务 lease 过期扫描）；`w_<q>_eni` on `(event_name)`；`w_<q>_ti` on `(task_id)`；`e_<q>_eai` on `(emitted_at)`；`i_<q>_ti` on `(task_id)`。partitioned 模式按周分区（`partition_week_tag`，行 2396），有 default partition 与 detach 机制[^3^]。

## 3. 事务模式 / exactly-once

- **认领（claim）使用 `FOR UPDATE SKIP LOCKED`**。`claim_task`（行 908-1070）核心是一个 CTE：
  ```sql
  with candidate as (
     select r.run_id from absurd.r_<q> r join absurd.t_<q> t on t.task_id = r.task_id
    where r.state in ('pending','sleeping')
      and t.state in ('pending','sleeping','running')
      and r.available_at <= $1
    order by r.available_at, r.run_id
    limit $2
    for update skip locked
  ), updated as (update r set state='running', claimed_by=$3, claim_expires_at=$4, ...),
  task_upd as (update t set state='running', ...), ...
  ```
  认领 = 单事务内「runs 行加锁 → 置 running+租约 → 同步 task 状态 → 清理过期 wait」[^3^]。
- **checkpoint 与状态落库**：`set_task_checkpoint_state`（行 1460-1545）把 step 返回值 UPSERT 进 `c_<q>`（PK `(task_id, checkpoint_name)`），且**同一个 PL/pgSQL 函数调用里可附带 `p_extend_claim_by` 同步延长租约**（行 1507-1517）。由于 SDK 在同一连接/事务里调用，checkpoint 写入与租约延长天然同事务。带 attempt 防护：仅当 `v_new_attempt >= v_existing_attempt` 才覆盖旧 checkpoint（行 1532），防止旧 run 的迟到写入覆盖新 run。
- **副作用语义**：README/Concepts 明确——副作用必须放进 step；step 之外的代码"may execute multiple times across retries"。README 原文："Code that runs outside of steps will potentially be executed multiple times."[^1^] step 的 checkpoint 在 step 闭包返回**之后**才落库，因此 step 内副作用+结果记录**不是**与副作用本身同事务的（副作用通常是外部系统调用，本来也无法同事务）；对数据库内副作用，SDK 允许传入外层事务连接从而做到原子（需 SDK 层确认细节）。
- **崩溃窗口定义**（Concepts 原文）："If the worker crashes or stops making progress before the claim expires, the task becomes available again and another worker can pick it up. **That means brief overlapping execution is possible**, so tasks should make observable progress well within the claim timeout"[^5^]。即：lease 模型，**不保证严格 exactly-once**，崩溃窗口 = claim timeout；README 也承认 step 内若调用外部系统应自行派生幂等键（`f"{ctx.task_id}:payment"`）[^5^]。

## 4. 恢复 / 重试

- **租约+心跳**：claim 默认 30s（`p_claim_timeout integer default 30`）。`extend_claim`（行 1547-1606）校验 run 仍在 running 且租约未过期后延长；Python SDK 在执行器里**自动心跳**：`heartbeat_interval_ms = max(500, int((self._claim_timeout * 1000) / 2))`，每个 step 前后检查是否该 heartbeat（`absurd_sdk/__init__.py` 行 860-868）[^6^]。此外**每次写 checkpoint 自动延长租约**（Concepts："that claim is extended whenever the task writes a checkpoint"）[^5^]。
- **崩溃回收**：`claim_task` 每次被调用时先清扫过期租约（行 977-1006）：`select ... where state='running' and claim_expires_at <= $1 ... for update skip locked`，对每个过期 run 调 `fail_run(..., '$ClaimTimeout', 'worker did not finish task within claim interval', ...)` —— 即**惰性恢复（lazy recovery）**，由下一个 claimer 顺带完成，无独立 reaper 进程。
- **重试策略**：`fail_run`（行 1181-1324）将当前 run 置 failed 并写入 `failure_reason`，若 `attempt+1 <= max_attempts`（null = 无限）则插入新 run 行，`available_at = now + retry_delay_seconds(...)`。`retry_delay_seconds`（行 56-129）支持 `kind in ('none','fixed','exponential')`，参数 `base_seconds/factor/max_seconds`，**全局上限 86400s（1 天）**，指数溢出饱和。延迟>0 时任务进入 `sleeping`，到期后由 `(state, available_at)` 索引被 claim 捞起。
- **手动重试**：`retry_task`（行 1335-1458）支持原地增加 max_attempts 续跑或 `spawn_new` 以原参数克隆新任务。
- **自动取消策略**：spawn 时可带 `cancellation: {max_delay, max_duration}`，`claim_task` 认领前批量把超龄任务置 cancelled（行 951-975）[^3^]。

## 5. 架构形态

- **需要外部 worker 进程**：pull-based，worker 是宿主语言进程轮询 `claim_task`。README："Absurd is a pull-based system, which means that your code pulls tasks from Postgres as it has capacity. It does not support push at all"[^1^]。**没有**协调器/服务器进程——"without needing any other services to run in addition to Postgres"[^1^]。
- **纯 SQL 接口：有，且是一等公民**。所有行为都是 `absurd.*` schema 下的 PL/pgSQL 函数：`spawn_task / claim_task / complete_run / schedule_run / fail_run / retry_task / set_task_checkpoint_state / get_task_checkpoint_state(s) / await_event / emit_event / cancel_task / extend_claim / create_queue / drop_queue / list_queues / cleanup_* / enable_cron / disable_cron`（`sql/absurd.sql` 全文）[^3^]。任何 PL/pgSQL 函数都可以直接 `select * from absurd.spawn_task('q','task','{}'::jsonb)` enqueue；claim 同样是纯 SQL 函数（返回表）。SDK 只是薄封装——README 原文："Absurd's goal is to move the complexity of SDKs into the underlying stored functions"[^1^]；comparison 文档："thin SDKs with most of the durable behavior in stored procedures"，"Temporal's Python SDK is 170.000 lines of code, Absurd's is under 2000"[^4^]。
- SDK 语言：TypeScript/JS（`absurd-sdk` npm 包）、Python（`absurd-sdk`，约 <2000 行）、Go（experimental bootstrap）[^1^]。

## 6. 队列语义

- **优先级：无**。claim 顺序固定为 `order by r.available_at, r.run_id`（行 1016），纯 FIFO-by-availability；SQL 全文 grep 无 priority 列。
- **延迟任务**：有，sleep 通过 `schedule_run` 把 run 置 `sleeping` + `available_at=未来时间`（行 1135-1179）；spawn 后首个 run 的 `available_at=now`，但 retry/sleep 都用同一机制延迟。
- **并发控制**：无 server 端 concurrency limit（`set_queue_policy` 只接受分区/清理/detach 键，行 504+ 白名单校验会拒绝未知键）；并发 = worker 数 × `claim_task` 的 `p_qty` 批量参数。
- **取消**：`cancel_task`（行 1976-2040）锁序注释明确（"Lock active runs before the task row so cancel_task() uses the same lock acquisition order as complete_run()/fail_run()"），运行中的任务"detect cancellation at the next checkpoint or heartbeat"（写 checkpoint / extend_claim 时检查 task 状态抛 `AB001`）。另有 spawn 期 `cancellation.max_delay / max_duration` 策略[^3^][^5^]。
- **去重/幂等键**：spawn 期 `idempotency_key`——unpartitioned 靠 `t_<q>.idempotency_key unique` + `on conflict do nothing` 返回既有 task（行 858-880）；partitioned 用 `i_<q>` 侧表 + `for key share` 读回（行 817-854）。

## 7. 事件 / 等待 / 休眠 / fan-out

- **await_event**（行 1692-1877）：先查 `c_<q>` 是否已有该 step 的 checkpoint（重放短路）；否则在 `e_<q>` 预插一行 `payload=null, emitted_at='epoch'` 哨兵行并 `for share` 加锁（锁序：event 行 FOR SHARE → run 行 FOR UPDATE，注释明言为防死锁），事件已到则把 payload 写为 checkpoint 返回；未到则在 `w_<q>` 注册等待并把 run 置 sleeping，`available_at = coalesce(timeout_at, 'infinity')`。
- **emit_event**（行 1879-1971）：**first-write-wins**（`on conflict do update ... where e.payload is null`；重复 emit 直接 return，不重放副作用），然后单 CTE 内：删过期 wait → 唤醒所有 sleeping runs（置 pending、写 `event_payload`）→ 把 payload 预写成各任务的 checkpoint → 删 wait。事件是"持久化等待原语"，不是消息总线。
- **sleep**：`ctx.sleepFor/sleepUntil` → `schedule_run`；超时等待复用 `available_at=timeout_at`，醒后发现 `wake_event` 匹配且无 payload 则判超时返回 null（行 1834-1843）。
- **fan-out**：支持——任务内可调 `spawn_task` 生成子任务，再用 `awaitTaskResult`/事件回收结果（README 示例注释 "If triggered from within a task, you can also await it"）[^1^]。无专门 child-workflow 原语。
- **cron**：有 `enable_cron/disable_cron`（行 2921/3081）集成 pg_cron（测试目录有 `test_cron_pgcron_e2e.py`）[^3^]。

## 8. 观测

- 状态查询 = 直接 SELECT 系统表；`absurd.get_task_result`（行 722+）取任务结果；`get_task_checkpoint_states` 按 run 的 attempt 过滤可见 checkpoint（"checkpoints from later attempts are hidden"，行 1637+）。
- **habitat**：随仓库的 Go Web UI（Overview/Queues/Tasks/TaskRuns/EventLog 视图，`habitat/ui/src/views/`）[^1^]。
- **metrics：未获取到内建指标导出**（无 Prometheus/metrics 端点代码；观测靠表 + habitat UI + `absurdctl`）。

## 9. 设计取舍与 non-goals（文档原文）

- "Absurd is not trying to win on feature count. It is trying to make durable execution feel as close to 'just use Postgres' as possible."[^4^]
- 明确不做 push："It does not support push at all, which would require a coordinator... If you need this, you can write yourself a simple service that consumes messages and makes HTTP requests."[^1^]
- 不做确定性 workflow 运行时："Absurd is intentionally less invasive. It does **not** try to turn your code into a deterministic workflow runtime. Instead, it relies on explicit step boundaries and persisted step results."[^4^]
- 结果："you get fewer built-in guarantees and fewer high-level primitives"[^4^]；无优先级、无服务端并发限制、无速率限制（对比 Inngest 段落列出的 concurrency limits/throttling/debounce/rate limiting/prioritization/batching 均属"Inngest has... Absurd deliberately does not try to own"）[^4^]。
- 重叠执行是公认代价（见第 3 节引用）[^5^]。
- 数据默认永久保留："By default data lives forever."[^5^]

## 10. 与 DBOS 的差异（作者原文，docs/comparison.md 行 126-138）

> "[DBOS](https://docs.dbos.dev/) is probably the closest project on this list in spirit. It also builds durable execution on top of Postgres and tries to avoid forcing you into a separate orchestration cluster. Like Absurd, DBOS is trying to keep durability close to the application and the database rather than building a giant external workflow brain. In particular, **Absurd pushes more of the durable behavior into stored procedures and keeps the SDKs relatively light. DBOS, by contrast, has rather beefy SDKs in comparison that try to do more.** For instance the Python SDK clocks in at 40.000 lines of code."[^4^]

补充（调研者观察，非作者原文）：DBOS 的系统表是固定的一组（workflow_status / operation_outputs / notifications 等）由"beefy SDK"写入；absurd 则每队列一组表、逻辑全部在 PL/pgSQL 函数里——**absurd 的架构形态与 pg_cordis 的"一切皆 PG 表 + SQL 函数"哲学高度同构**，DBOS 反而更偏"库内嵌引擎 + 厚 SDK"。

## 对 pg_cordis 的借鉴要点（调研者结论）

1. **表结构直接可抄**：t_/r_/c_/e_/w_/i_ 六表分工 + 状态机 check 约束 + 部分索引（`claim_expires_at where state='running'`）是成熟设计。
2. **claim CTE 模式**（候选 SKIP LOCKED → 更新 run → 同步 task → 清理 wait，单语句）和**惰性 lease 回收**（claimer 顺带扫过期租约）适合纯 SQL executor。
3. **checkpoint + 租约延长合并进同一函数调用**，以及 attempt 防护写（新 attempt 才能覆盖旧 checkpoint），是崩溃窗口收敛的关键技巧。
4. **事件 first-write-wins + 哨兵行 + FOR SHARE/FOR UPDATE 锁序**，是 pg_cordis 实现 agent 间 signal/wait 的现成范式。
5. 差异点：pg_cordis 的 executor 是 SQL 函数（进程内执行即 PG backend），可做到"副作用与结果记录同事务"的更强保证——absurd 因 worker 在外部进程做不到这点；同时 pg_cordis 可借 `absurd.fake_now`（`current_setting` 假时钟）的测试技巧。

[^1^]: README.md, https://raw.githubusercontent.com/earendil-works/absurd/main/README.md （访问 2026-08-23）
[^2^]: GitHub API repo metadata, https://api.github.com/repos/earendil-works/absurd （访问 2026-08-23：stargazers_count=2363, license Apache-2.0, created_at 2025-10-20, pushed_at 2026-08-10）
[^3^]: sql/absurd.sql, https://raw.githubusercontent.com/earendil-works/absurd/main/sql/absurd.sql （访问 2026-08-23）
[^4^]: docs/comparison.md, https://raw.githubusercontent.com/earendil-works/absurd/main/docs/comparison.md （访问 2026-08-23）
[^5^]: docs/concepts.md, https://raw.githubusercontent.com/earendil-works/absurd/main/docs/concepts.md （访问 2026-08-23）
[^6^]: sdks/python/src/absurd_sdk/__init__.py, https://raw.githubusercontent.com/earendil-works/absurd/main/sdks/python/src/absurd_sdk/__init__.py （访问 2026-08-23）
