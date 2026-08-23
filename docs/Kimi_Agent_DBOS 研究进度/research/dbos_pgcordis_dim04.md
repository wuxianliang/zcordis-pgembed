# DBOS-Transact-TS 源码研究：Exactly-Once 事务模式 与 崩溃恢复循环

- 仓库：`dbos-inc/dbos-transact-ts`，分支 `main`
- 访问日期：2026-08-23
- 对照目标：pg_cordis（工具调用幂等 PK=(execution_id, tool_call_id)，「副作用与结果记录同事务提交」）

---

## 结论速览（对 pg_cordis 最重要的一条）

DBOS 把「用户副作用」分成两类，语义截然不同：

1. **transaction（`DBOS.transaction` / 数据源事务）= exactly-once**：用户函数与结果记录 INSERT 在**同一个 Postgres 事务、同一个 client 连接**里提交——这正是 pg_cordis 的目标模型。[^7^][^8^]
2. **step（`DBOS.step`）= at-least-once**：用户代码先跑完，**之后**才用系统库连接单独 INSERT `operation_outputs`。副作用与输出记录**不在同一事务**，存在崩溃窗口，恢复时会重执行整个 step。[^3^][^6^]

---

## Q1：step 执行的事务边界与崩溃窗口

### 1.1 step 的检查点流程（`callStepFunction`）

文件 `src/dbos-executor.ts`，函数 `DBOSExecutor.callStepFunction`（约 L1020–1300）：[^3^]

1. **分配函数序号**：`const funcID = functionIDGetIncrement();`（在任何 await 之前同步递增，避免并发竞争）。
2. **读缓存（OAOO 检查）**：
   ```ts
   const checkr = await this.systemDatabase
     .getOperationResultAndThrowIfCancelled(wfid, funcID)
     .catch(endSpanAndRethrow);
   if (checkr) {
     if (checkr.functionName !== stepFnName) { /* DBOSUnexpectedStepError */ }
     return await DBOSExecutor.reviveResultOrError<R>(checkr, this.serializer); // 直接回放，不执行用户代码
   }
   ```
3. **执行用户代码**（可带重试，见 Q2.5）。**用户副作用发生在这里，且不在任何 DBOS 控制的事务内。**
4. **成功后才记录输出**（同函数尾部）：
   ```ts
   const funcResult = await serializeFunctionInputOutput(result, ...);
   await this.systemDatabase.recordOperationResult(wfid, funcID, stepFnName, true, startTime, Date.now(), {
     output: funcResult.stringified, serialization: funcResult.sername,
   });
   ```

`recordOperationResult` → `recordOperationResultInternal`（`src/system_database.ts` L5307）是**独立的一条 INSERT**（走系统库 pool 连接，隐式单语句事务）：[^4^]

```sql
INSERT INTO ${schema}.operation_outputs
 (workflow_uuid, function_id, output, error, function_name, child_workflow_id,
  started_at_epoch_ms, completed_at_epoch_ms, serialization, application_name)
VALUES ($1..$10)
ON CONFLICT (workflow_uuid, function_id) DO UPDATE
 SET completed_at_epoch_ms = operation_outputs.completed_at_epoch_ms
RETURNING completed_at_epoch_ms;
```

配合 `checkConflict`：若冲突行已有更早的 `completed_at_epoch_ms`，说明并发执行已先写入 → 抛 `DBOSWorkflowConflictError`（同时把 `workflow_status.executor_id` 认领为本执行器）。

### 1.2 崩溃窗口的精确定义（step）

- **窗口 = 从「用户代码副作用生效」到「`recordOperationResultInternal` 的 INSERT 提交成功」之间。**
- 崩溃发生在 INSERT 提交**之前**（包括副作用已完成后、记录前的任意时刻，以及 step 执行中途）→ `operation_outputs` 无此 (workflow_uuid, function_id) 行 → 恢复重放时 `getOperationResultAndThrowIfCancelled` 返回空 → **step 整体重执行，副作用会再次发生**（at-least-once）。
- 崩溃发生在 INSERT 提交**之后** → 恢复时命中缓存回放输出 → step **不会**重执行。
- DBOS 官方在注释/文档中明确这一语义：`src/dbos.ts` L2107 注释：*「A durable checkpoint will be made after the step completes. This ensures "at least once" execution of the step」*。[^2^]

### 1.3 对照：transaction 如何做到 exactly-once（pg_cordis 目标模型）

以 `packages/nodepg-datasource/index.ts` 为例（knex/drizzle/prisma/typeorm 等同构）：[^7^]

`NodePostgresTransactionHandler.invokeTransactionFunction`：

```ts
while (true) {
  const previousResult = saveResults ? await this.#checkExecution(workflowID, stepID!) : undefined;
  if (previousResult) return replayRecordedStep<Return>(previousResult);   // 已执行过 → 回放
  try {
    const result = await this.#transaction(async (client) => {
      const result = await func.call(target, ...args);                    // 用户代码（同一 client）
      if (saveResults) {
        await NodePostgresTransactionHandler.#recordOutput(               // 结果记录（同一 client！）
          client, workflowID, stepID!, SuperJSON.stringify(result), this.schemaName);
      }
      return result;
    }, config);  // #transaction: BEGIN [ISOLATION LEVEL …] → func → COMMIT / ROLLBACK
    return result;
  } catch (error) {
    if (error instanceof DBOSStepAlreadyRecordedError) return this.#replayConflictingStep(...);
    if (isPGRetriableTransactionError(error)) { /* 40001 serialization failure → 指数退避重试(×1.5, ≤2s) */ continue; }
    if (saveResults) await this.#recordError(workflowID, stepID!, SuperJSON.stringify(error)); // 错误也在用户库记录
    throw error;
  }
}
```

关键点（与 pg_cordis PK 设计完全对应）：

- 结果表是**用户库**里的 `dbos.transaction_completion`，DDL（`src/datasource.ts` `createTransactionCompletionTablePG`）：[^6^]
  ```sql
  CREATE TABLE IF NOT EXISTS "dbos".transaction_completion (
    workflow_id TEXT NOT NULL, function_num INT NOT NULL,
    output TEXT, error TEXT, created_at BIGINT ...,
    PRIMARY KEY (workflow_id, function_num)   -- ≡ pg_cordis 的 (execution_id, tool_call_id)
  );
  ```
- `#recordOutput` 用 `INSERT … ON CONFLICT (workflow_id, function_num) DO NOTHING RETURNING workflow_id`；返回 0 行说明并发重复执行已先记录 → 抛内部 `DBOSStepAlreadyRecordedError` **使整条用户事务回滚**，再回放已记录结果（`#replayConflictingStep`）。即：**副作用要么与结果记录一起提交，要么整体回滚**——exactly-once 由「同一事务 + PK 唯一约束」保证。
- 执行前检查 `#checkExecution` 与冲突回放共用 `replayRecordedStep`（`src/datasource.ts` L316），注释明确两条路径不可漂移。
- 序列化失败（SQLSTATE 40001）自动重试（`isPGRetriableTransactionError`），起始 1ms、×1.5、上限 2s；唯一键冲突 23505 与事务中止 25P02 有专门判别函数（`isPGKeyConflictError` / `isPGFailedSqlTransactionError`）。
- 只读事务（`readOnly: true`）不记录结果，每次重放都重跑。

---

## Q2：崩溃恢复循环（recovery loop）

### 2.1 启动入口

`DBOSExecutor.launch()`（`src/dbos-executor.ts` L435）：[^3^]

```ts
await this.recoverPendingWorkflows([this.executorID]);
```

`recoverPendingWorkflows`（L1340）对每个 executorID 调 `systemDatabase.reenqueueWorkflowsForRecovery(execID, appVersion, INTERNAL_QUEUE_NAME)`。

### 2.2 扫描哪些状态

`reenqueueWorkflowsForRecovery`（`src/system_database.ts` L1404）：[^4^]

```sql
UPDATE "dbos".workflow_status
SET started_at_epoch_ms = NULL, status = 'ENQUEUED', updated_at = …,
    queue_name = COALESCE(queue_name, $2 /* _dbos_internal_queue */)
WHERE status = 'PENDING'
  AND executor_id = $4 AND application_version = $5
  AND application_name = …            -- 只回收自己 executor + 同 app version 的
RETURNING workflow_uuid
```

- 只扫 **PENDING**（`StatusString` 枚举见 `src/workflow.ts` L228：PENDING / SUCCESS / ERROR / ENQUEUED / DELAYED / CANCELLED / MAX_RECOVERY_ATTEMPTS_EXCEEDED）。
- 恢复方式是**重入队而非直接执行**：注释写明「queue 的原子 dequeue 保证恰好一个 runner 接管」。
- 另有 `getPendingWorkflows`（L1383，同条件 SELECT）供查询用。

### 2.3 重新执行到断点

队列 dispatch 后走 `executeDequeuedWorkflow`（`src/dbos-executor.ts` L1421）：

- 反序列化 `workflow_status.inputs`（失败则把 workflow 记为 ERROR，避免卡 PENDING）；
- 检查 `recovery_attempts`，超过 `maxRecoveryAttempts`（默认 50）→ `deadLetterWorkflows` 置 `MAX_RECOVERY_ATTEMPTS_EXCEEDED` 并抛 `DBOSMaxRecoveryAttemptsExceededError`（L680–690）；
- 只有仍属 PENDING 的行才执行（「Only a PENDING row owns its outcome」）；
- 然后**从头重新执行 workflow 函数**——workflow 代码必须确定性，因为每个 step/transaction/子 workflow 调用先查 `operation_outputs` / `transaction_completion` 缓存：
  - step：`callStepFunction` 里的 `getOperationResultAndThrowIfCancelled`（命中 → 反序列化回放，函数名不符抛 `DBOSUnexpectedStepError`）；
  - 子 workflow：`workflow()` 启动前先查 `operation_outputs` 中 `child_workflow_id`（`src/dbos-executor.ts` L670–678，注释说明 `operation_outputs` 对 `workflow_status` 有外键约束）；
  - transaction：`#checkExecution` 查 `transaction_completion`。
- 新执行的 step 通过 `functionIDGetIncrement()` 重新分配同样的 function_id 序列，与缓存行对齐——这就是「重放到断点」的机制：**无快照/续跑，全靠确定性重放 + 逐步缓存命中**。

### 2.4 幂等性靠什么保证

- **workflow 级**：`workflow_status.workflow_uuid` 是主键（migration 1：`constraint "workflow_status_pkey" primary key ("workflow_uuid")`）。[^5^] `insertWorkflowStatus`（`src/system_database.ts` L5093）用 `INSERT … ON CONFLICT (workflow_uuid) DO UPDATE`，`initWorkflowStatusInternal` 校验同名/同类，靠 `owner_xid` 比较（`shouldExecuteOnThisExecutor: ownerXid === resRow.owner_xid`）判定本次调用是否赢得执行权——同一 workflow_id 只执行一次。队列另有 `uq_workflow_status_queue_name_dedup_id unique (queue_name, deduplication_id)` 做入队去重。
- **step 级**：`operation_outputs` PK = `(workflow_uuid, function_id)`（migration 1），`ON CONFLICT DO UPDATE` + `completed_at_epoch_ms` 比较检测并发冲突 → `DBOSWorkflowConflictError`（`recordOperationResultInternal`）。[^4^]
- **transaction 级**：`transaction_completion` PK = `(workflow_id, function_num)` + 同事务 INSERT + `DBOSStepAlreadyRecordedError` 回滚（见 Q1.3）。[^7^]
- **终态写入归属**：`#recordWorkflowOutcome`（`src/system_database.ts` L1369）只在 `status='PENDING'` 时更新 SUCCESS/ERROR（`where: { status: PENDING }`），防止并发执行互相覆盖。

### 2.5 step 错误/重试语义

`src/step.ts` `StepConfig`（含完整注释）：[^1^]

- `retriesAllowed`（默认 false）、`intervalSeconds`（首次间隔秒，默认 1）、`maxAttempts`（默认 3）、`backoffRate`（默认 2）、`shouldRetry(error)` 谓词、`timeoutMS`（单次尝试超时，触发 `DBOSStepTimeoutError` + `stepStatus.timeoutSignal` AbortSignal，代码不强制终止，结果丢弃）。
- 实现见 `callStepFunction` 重试循环（`src/dbos-executor.ts` L1127–1185）：失败后 `sleepms(intervalSeconds*1000)`，`intervalSeconds *= backoffRate`，封顶 `maxRetryIntervalSec = 3600` 秒；每轮先 `checkIfCanceled` 使取消立即生效；超限抛 `DBOSMaxStepRetriesError`。
- **无论是否重试，最终 error 都会写入 `operation_outputs.error`** 再抛出（`recordOperationResult(..., { error: serializer.stringify(serializeError(err)) })`）——错误也是检查点，恢复时回放为抛错而非重跑（注意：这与「副作用已发生但进程崩溃」不同，进程崩溃不留任何记录 → 重跑）。
- 例外：`DBOSWorkflowCancelledError` 打断的 step **不**做检查点，恢复后重执行（`runInternalStep` L1290 注释）。

---

## 顺带：输入输出序列化存储

- `src/serialization.ts`：默认序列化器 **SuperJSON**（`name: 'js_superjson'`，注册 Buffer 等 recipe），另有 `DBOSPortableJSON` 跨语言格式；错误用 `serialize-error`。[^9^]
- workflow 输入：`serializeFunctionInputOutput` 序列化后存 `workflow_status.inputs`（TEXT 列，migration 加列 `inputs text null`），`serialization` 列记录格式名。
- step 输出/错误：`operation_outputs.output` / `.error`（TEXT）+ `serialization` 列；回放路径 `reviveResultOrError` / `deserializeValue` 按列值选反序列化器。
- transaction 输出：`transaction_completion.output` / `.error`，固定 SuperJSON。
- 终态：`#recordWorkflowOutcome` 写 `workflow_status.output/.error` + `completed_at`。

---

## 对 pg_cordis 的映射建议（推断，非源码事实）

- pg_cordis 的 PK=(execution_id, tool_call_id) 与 DBOS 的 `(workflow_uuid, function_id)` / `(workflow_id, function_num)` 一一对应。
- 「副作用与结果记录同事务提交」= DBOS **transaction** 模型（`transaction_completion` 在用户库、同事务 INSERT、PK 冲突回滚 + 回放）。直接复用 `INSERT … ON CONFLICT DO NOTHING RETURNING` + 0 行回滚模式即可。
- 崩溃窗口消除靠「同事务」；执行前 `#checkExecution` 预读 + 冲突时 `#replayConflictingStep` 两条回放路径必须共用同一反序列化逻辑（DBOS 专门抽象了 `replayRecordedStep`）。
- 恢复端借鉴：状态机只回收 PENDING、用原子 UPDATE…RETURNING（reenqueue）保证单一接管者、recovery_attempts 上限 + dead letter、终态写入加 `WHERE status='PENDING'` 守卫。

---

## 引用

[^1^]: `src/step.ts`（StepConfig/validateStepConfig），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/step.ts ，访问 2026-08-23
[^2^]: `src/dbos.ts` L2107–2112（DBOS.step 装饰器注释「at least once」），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/dbos.ts ，访问 2026-08-23
[^3^]: `src/dbos-executor.ts`（`launch` L435、`recoverPendingWorkflows` L1340、`callStepFunction` L1020–1300、`runInternalStep` L1254、`executeDequeuedWorkflow` L1421），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/dbos-executor.ts ，访问 2026-08-23
[^4^]: `src/system_database.ts`（`recordOperationResultInternal` L5307、`reenqueueWorkflowsForRecovery` L1404、`getPendingWorkflows` L1383、`#recordWorkflowOutcome` L1369、`insertWorkflowStatus` L5093、`initWorkflowStatus` L1053），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/system_database.ts ，访问 2026-08-23
[^5^]: `src/sysdb_migrations/internal/migrations.ts`（`workflow_status_pkey` / `operation_outputs_pkey` DDL），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/sysdb_migrations/internal/migrations.ts ，访问 2026-08-23
[^6^]: `src/datasource.ts`（`createTransactionCompletionTablePG`、`replayRecordedStep` L316、`DBOSStepAlreadyRecordedError`、`isPGRetriableTransactionError`），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/datasource.ts ，访问 2026-08-23
[^7^]: `packages/nodepg-datasource/index.ts`（`invokeTransactionFunction`、`#transaction` BEGIN/COMMIT/ROLLBACK、`#recordOutput` ON CONFLICT DO NOTHING RETURNING），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/packages/nodepg-datasource/index.ts ，访问 2026-08-23
[^8^]: `src/datasource.ts` `runTransaction` / `registerTransaction`（事务经 `runInternalStep` 包一层 sysdb 检查点），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/datasource.ts ，访问 2026-08-23
[^9^]: `src/serialization.ts`（DBOSSerializer、`js_superjson`、DBOSPortableJSON），https://raw.githubusercontent.com/dbos-inc/dbos-transact-ts/main/src/serialization.ts ，访问 2026-08-23
