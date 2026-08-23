# 跨维度洞察：pg_cordis × DBOS

访问日期 2026-08-23。每条洞察由 ≥2 维度证据支撑。

## I1. pg_cordis 的"executor 即 SQL 函数"不是异端，而是 DBOS 谱系的下一站
- 来源：Dim01（CIDR 原型限制清单：无触发器、SP 不能互调、无嵌套事务、仅 Java——几乎逐条是 PG 的强项）、Dim02（Apiary 把函数编译为 VoltDB 存储过程，函数即 ACID 事务）、Dim10（DBOS 未利用 PG 内部能力，恢复依赖外部进程）。
- 推理：DBOS 学术原型受 VoltDB 所限的每一条，PG 原生都能做；Apiary 的编译目标形态正是 pg_cordis 的原生形态。DBOS Cloud 存在的理由（最后一个 executor 死亡则不自愈）在 pg_cordis 中因 executor 在库内而大幅缓解。
- 含义：报告应把"全在 PG"定位为对 DBOS 架构的推进而非妥协。置信度：高。

## I2. exactly-once 的正确答案已在 pg_cordis 当前设计中，但只覆盖了一半
- 来源：Dim04/06/08（DBOS 三层模型；transaction 步骤"同事务 INSERT ON CONFLICT DO NOTHING RETURNING，0 行则回滚重放"与 pg_cordis 目标完全同构）、Dim04（普通 step 是 at-least-once，崩溃窗口=副作用生效→checkpoint 提交之间）。
- 推理：pg_cordis 的 (execution_id, tool_call_id) 幂等 + 同事务提交 = DBOS 的 transactional step。pg_cordis 缺的是对"非事务性副作用"（如外部 HTTP/LLM 调用）的分层：必须显式区分两类 tool_call 并向插件作者暴露 at-least-once 语义与崩溃窗口。
- 含义：v0.1 应在工具 ABI 中增加"事务性/非事务性"分类。置信度：高。

## I3. 恢复机制不必自研——DBOS 的"PENDING→ENQUEUED 单条 UPDATE + 版本过滤 + 原子出队"是纯 SQL 可完整移植的
- 来源：Dim04/05/06/07（四语言同一套 SQL 模式）、Dim08。
- 推理：DBOS 的恢复循环本身就是几条 SQL（UPDATE...RETURNING、FOR UPDATE SKIP LOCKED），pg_cordis 用 PL/pgSQL 可实现等价物，且不需要 executor_id 维度（单库内）——但需引入"执行快照版本"过滤来替代 application_version。
- 含义：recovery_attempts 计数与 MAX_RECOVERY_ATTEMPTS_EXCEEDED 状态应直接采纳。置信度：高。

## I4. pg_cordis 的 execution_tools 不可变快照 ≈ DBOS 的 application_version 固化，但粒度更优
- 来源：Dim05（DBOS 版本=全量源码 MD5，粒度是整个应用）、Dim08（版本不匹配即不恢复、blue-green 排空）、pg_cordis 设计（启动时固化执行级快照）。
- 推理：DBOS 因代码在库外只能按应用整体版本化；pg_cordis 的 catalog 在库内，可按 execution 粒度固化工具集快照——比 DBOS 更细。但 DBOS 的 fork（复制 status + <startStep checkpoint 到新 ID 换版本重跑）正是 pg_cordis 需要的"修改执行定义后继续"机制，当前设计缺失。
- 含义：v0.1 应增加 fork_execution()。置信度：高。

## I5. 通知/事件子系统：pg_cordis 的 events+NOTIFY 应升级为 DBOS notifications 的"幂等键主键 + 原子消费 + 与 checkpoint 同事务"三件套
- 来源：Dim05（notifications DDL 与消费 SQL）、Dim08（send exactly-once/外部需幂等键）、Dim03（保留 pg_notify 触发器——NOTIFY 只做唤醒、表做真相）。
- 推理：DBOS 证明 NOTIFY 与持久表互补而非互斥；pg_cordis 当前设计方向正确但缺消费侧原子性与幂等键。
- 含义：event_consumers 表需加 consumed 原子更新与幂等键。置信度：高。

## I6. LLM/agent 层的答案是"checkpoint 重放零成本"而非特殊机制
- 来源：Dim09（模型调用=step，恢复时 checkpoint 重放不再调模型；step 级重试谓词；协作式超时 AbortSignal；durable streams）、Dim04（错误也作 checkpoint 写入，恢复时回放为抛错）。
- 推理：DBOS 没有为 LLM 发明新机制，而是把确定性重放纪律做到极致。pg_cordis 不实现 token 流式的决策与 DBOS durable streams（2026 新增、LISTEN/NOTIFY）对照后可保持不做，但应预留 streams 式追加表。
- 含义：错误即 checkpoint、恢复时回放抛错这一点 pg_cordis 应明确采纳。置信度：高。

## I7. 观测应"内建于事务"而非外挂 OTel
- 来源：Dim02（Apiary tracing 内建于事务）、Dim08（DBOS 开源版观测依赖外部 OTel provider，metrics 依赖 Conductor——外挂形态）、Dim01（DBOS 论文主张 SQL 全局可查是核心优势）。
- 推理：DBOS 开源版在观测上反而退回外挂 OTel，未兑现论文"一切皆表则可查"的承诺；pg_cordis 全在库内，有机会把 metrics/traces 直接落表兑现论文愿景，形成对 DBOS 的差异化优势。
- 含义：v0.1 可加 cordis.metrics 表 + SQL 查询视图。置信度：中。
