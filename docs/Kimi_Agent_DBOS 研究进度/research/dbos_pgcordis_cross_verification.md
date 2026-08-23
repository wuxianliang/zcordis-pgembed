# 交叉验证：pg_cordis × DBOS 研究

访问日期：2026-08-23。维度文件 dim01–dim10 全部就绪。

## High Confidence（≥2 独立来源一致）

1. **三层保证模型：workflow 必达完成 / step at-least-once / transaction exactly-once**。源码（dim04：callStepFunction 先执行后独立事务写 operation_outputs；nodepg-datasource invokeTransactionFunction 同事务 INSERT ON CONFLICT）、Python 源码（dim06：call_txn_as_step 同构）、官方文档（dim08：三层精确定义，"Exactly-Once Event Processing" 为营销口径）三方一致。
2. **operation_outputs PK=(workflow_uuid, function_id)，错误也作检查点写入**。dim03（TS DDL）、dim06（Py 逐列一致）、dim07（Go/Java 一致）、dim04/08（重放语义）一致。
3. **恢复 = 单条 UPDATE 把 PENDING 且同 executor_id、同 application_version 的行转 ENQUEUED，靠队列原子出队保证单一接管**。dim04、dim06、dim07、dim08 一致。
4. **版本化 = 全部 workflow 函数源码 MD5 → application_version；恢复/出队只领同版本行；修复旧版本用 fork（复制 status+<startStep checkpoint 到新 ID）；patch marker 写 operation_outputs**。dim05、dim06、dim08 一致。
5. **通知 exactly-once = message_uuid(幂等键::目的地) 主键 + ON CONFLICT DO NOTHING 发送；原子 UPDATE...consumed=true 消费且与 step checkpoint 同事务；重放读 checkpoint**。dim05（源码）+ dim08（文档）一致。
6. **队列出队 = SELECT ... FOR UPDATE SKIP LOCKED ORDER BY priority ASC, created_at ASC**。dim05（源码）+ dim08（文档语义）一致。
7. **无 saga/补偿框架**：源码零匹配（dim05），文档无专章（dim08），补偿即显式 checkpointed undo step。
8. **time travel 调试已演变为 fork-from-step**（复制输入+checkpoint 重跑），开源 API；Time Travel Debugger UI 为 DBOS Cloud 专有。dim08 + dim10 一致；论文（dim01）仅有 provenance 原则，无 time-travel 章节。
9. **系统表 schema 为跨语言共享规范**（SHARED_MIGRATION_BASE=100）：dim03/06/07 一致。9 张存留表清单一致；TS 独有 request 列与 event_dispatch_kv 表，Py 已移除。
10. **性能上限由 Postgres 决定**：144K 写/s、43K workflow/s（96 vCPU RDS），队列模式 12.1K/s（队首锁竞争），多分区 30.6K/s（dim10）；与论文中 FIFO 调度 1–2M tasks/s（VoltDB 原型，dim01）不矛盾——不同引擎。

## Medium Confidence（单一权威来源）

- DBOS Cloud = Firecracker microVM + PG 状态、版本化路由；最后一个 executor 死亡则 workflow 不自愈（dim10，官方文档/博客）。
- LLM/agent 实践：模型调用包装为 step、checkpoint 重放零 token 浪费、2026-07 协作式 step 超时（AbortSignal）、durable streams（LISTEN/NOTIFY）（dim09，官方文档+博客）。
- Apiary SFR 选择性记录将容错开销 2.2×→<5%（dim02，论文）。

## Conflict Zone

1. **time-travel 调试**：委托书假设其为核心论文机制；实际论文（dim01）未提，现行实现是 fork（dim08）+ Cloud 专有调试器（dim10）。已在报告中按"演变"处理，非矛盾。
2. **"DBOS 绑定 Postgres"**：Go/Py 支持 SQLite（dim07、dim10）。结论修正为"生产以 PG 为核心，SQLite 为单机可选"。
3. **旧表清单**：workflow_inputs、workflow_queue、scheduler_state 已于 2025-07-25 迁移 DROP 并入 workflow_status（dim03）——旧文档与委托书第 2.2 节表名清单部分过时，报告以最新源码为准。

## 未获取到（诚实标注）

- 论文中"确定性执行/重放恢复"的正式论述、微内核 LoC 对比（dim01：两篇论文未含，属后续 DBOS Transact 论文）
- 长事务风险的具体 GitHub issue、"DBOS is not..."逐字句（dim10）
- TS 逐条索引级迁移 SQL（dim06 标注）
