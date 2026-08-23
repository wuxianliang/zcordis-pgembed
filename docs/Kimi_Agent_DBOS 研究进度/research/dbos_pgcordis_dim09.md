# DBOS 在 LLM/Agent 工作流上的专门实践（dim09）

> 面向 pg_cordis（PostgreSQL 原生 agent 控制平面插件运行时）专题研究。
> 核心问题：DBOS 如何处理 LLM 这种「不幂等、贵、慢」的步骤。
> 检索与访问日期：2026-08-23。

## 0. TL;DR

DBOS 对 LLM 步骤的官方答案是一贯且明确的：**把每次 LLM 调用 / 工具调用建模为 `@DBOS.step`（或集成的 `DBOS.runStep`），把输出整体 checkpoint 到 Postgres；恢复时确定性重放 workflow，已完成的 step 直接从 checkpoint 重放结果，不再联系模型供应商**——用「输出缓存重放」把不幂等、贵、慢的调用变成恢复时零成本。配合 step 级 retry（指数退避 + `should_retry` 谓词）、step/workflow 级超时（协作式取消）、durable streams（可断线重连的 token 流）、durable queues（限流/并发控制）和 workflow fork（从某一步分叉重跑，用于 eval/调试）。

---

## 1. LLM 调用不幂等：输出缓存重放（step checkpointing）

**官方文档/源码事实**：

- 任何「非确定性操作」（调用外部 API/服务、随机数、时间等）都应标注为 `@DBOS.step`；workflow 中断后从**最后一个已完成的 step** 恢复[^1^]。这是 DBOS 对不幂等步骤的根本机制：step 结果（要求可序列化）写入系统数据库，恢复时确定性重放 workflow，已完成的 step 直接返回缓存结果，**不重新执行**。
- Vercel AI SDK 集成（`@dbos-inc/vercel-ai`，2026-07 发布）说得更直白：`durableCalls()` 是标准 AI SDK middleware，拦截 `doGenerate`/`doStream`，每次模型调用经 `DBOS.runStep` 执行，**完整结果（content、usage、finish reason、response metadata）checkpoint 到 Postgres；恢复时已完成的调用从 checkpoint 重放，不接触模型供应商**[^2^]。
- 在 workflow 之外（或另一个 step 内）调用被包装的模型时，直接走供应商、不做 checkpoint——同一模型可在应用任意处使用[^2^]。
- Pydantic AI 集成同理：`DBOSAgent`/`DBOSDurability` 自动把模型调用和 **MCP 通信**包装为 DBOS step[^3^][^4^]。**崩溃后不会重跑已完成的模型调用、不重复烧 token**[^3^]。
- 对数据库写操作：transactional step / 可插拔 datasource 把 step checkpoint 与应用写放在**同一事务**里，实现 exactly-once（2026-06 起 Python 支持多库异步 datasource）[^5^]。对 pg_cordis 这类「控制平面就在 Postgres 里」的架构，这一点直接相关。
- 确定性约束：workflow 必须确定性重放。Vercel AI 集成**检测并拒绝同一 workflow 内并发 durable 模型调用**（AI SDK 并发调用顺序不确定）；要 fan-out 并行须给每次调用一个 child workflow[^6^]。

**博客观点**：DBOS 官方博客把 agent 失败定性为「可观测性 + 可复现性问题」——LLM 本质非确定，唯一的解法是 checkpoint 全部执行轨迹使失败可重放、可 fork、可做 eval[^7^]。

## 2. Step 级 retry 语义（贵步骤的成本保护）

**官方文档事实**[^1^]：

```
@DBOS.step(retries_allowed=False, interval_seconds=1.0, max_attempts=3,
           backoff_rate=2.0, should_retry=None)
```

- 指数退避自动重试；重试耗尽抛 `DBOSMaxStepRetriesExceeded` 给 workflow（不捕获则 workflow 终止）。
- `should_retry` 谓词可按异常类型过滤（例如 4xx/校验错误不重试，网络错误重试）；async step 支持 async 谓词[^1^]。
- Vercel AI 集成**默认开启 retry**（默认 maxAttempts=3，可配 `timeoutMS` 每次尝试超时），其默认 `should_retry` 把供应商标记为不可重试的错误（如 401、invalid-request 400）和 abort/timeout 视为终止性错误、快速失败——即在 step 内部吸收瞬时错误，避免一次抖动导致整个 durable step 失败重放[^2^]。
- Pydantic AI 文档补充：durable 边界内**重试副作用需保持幂等**——若 workflow 在 step checkpoint 前恢复，事件 handler 可能跑多次[^4^]。

**Token 成本**：DBOS 未提供 token 预算/计费原语；官方立场是「崩溃恢复不重放已完成 step ⇒ 不重复花 token」[^3^]，外加 tracing 文档示例：在 step 内用 `DBOS.span` 记录 `gen_ai.usage.input_tokens`/`output_tokens` 等 OTel 属性做成本观测[^8^]。

## 3. 超时、取消、deadline

**官方文档事实**：

- **Workflow 超时**：`SetWorkflowTimeout` / `startWorkflow({timeoutMS})`；超时到期 workflow **及其所有子 workflow 被取消**。超时是 start-to-completion（排队不计时）且**持久**（存库、跨重启），支持超长超时[^9^][^10^]。
- **Step 超时（2026-07 新增）**：协作式（cooperative）而非抢占式——经 AbortSignal 通知，step 超时抛 `DBOSStepTimeoutError`，开 retry 时自动重试；step 若忽略信号则后台继续但结果被丢弃。TS 已发布，Go 用 `context.Context`，Python/Java 「coming soon」[^11^]。
- **取消**：`DBOS.cancel_workflow` / Conductor UI / `dbos workflow cancel`；执行中的 workflow 在**下一个 step 起点**被抢占；要立刻中断执行中的 async step 可标记 `preemptible`[^12^]。Go 版支持协作取消：step 里 `select ctx.Done()` 提前返回，被中断的 step **刻意不 checkpoint**，resume 时重跑[^13^]。
- **Pydantic AI 集成的限制**：模型流在 durable step 内消费，workflow 侧无法 `AgentStream.cancel()`；`CancellationToken` 不能传入 durable run；要从外部停 run，只能取消 DBOS workflow[^4^]。
- **全局超时**：Conductor 可配 retention 全局超时，超期未完成 workflow 自动取消（默认关）[^14^]。

## 4. 长时间运行 agent 的崩溃恢复

**官方文档事实**：

- 进程崩溃/重启/重新部署后，workflow 自动从最后完成的 step 恢复；`max_recovery_attempts`（默认 100）控制恢复重试上限，超限置 `MAX_RECOVERY_ATTEMPTS_EXCEEDED`[^15^]。
- `DBOS.recv(timeout_seconds=...)` 支持等人数天的人工审批（human-in-the-loop）；`DBOS.sleep()` 持久睡眠（唤醒时间存库，跨重启仍准时）[^9^][^16^]。
- **Fork**：`DBOS.fork_workflow` 从指定 step 分叉出新 workflow（复制输入和之前所有 step 的 checkpoint），用于下游故障恢复、「打补丁」修复 bug 版本、以及 **eval/调试 agent 某一步**[^12^][^17^]。
- **幂等键**：`SetWorkflowID` 给 run 固定 ID，崩溃重启后重连同一 run（队列侧还有 `deduplication_id`）[^18^]。
- Google ADK 插件文档总结的能力表（官方集成页）：LLM 调用被拦截为 DBOS step、崩溃后从最后成功 step 恢复「减少浪费的 token 支出」；任何能访问同一 DB 的 worker 可接管执行（分布式 failover）；并行工具调用「replay-safe 地并发分发、在下一次 LLM step 前 join」；支持 run 数小时/天/月[^19^]。

## 5. Streaming

**官方文档事实**：

- **Durable streams**：append-only 通道，`DBOS.write_stream(key, value)` / `DBOS.read_stream(workflow_id, key)` / `close_stream`；客户端断线后可重连不丢进度。语义：workflow 内写 exactly-once；**step 内写 at-least-once**（step 重试可能重复写，读者会看到所有尝试的值）[^20^]。
- 2026-06：`read_stream` 改用 Postgres **LISTEN/NOTIFY** 降低 token 流延迟（polling 兜底）[^21^]；2026-07：吞吐提升 20x，官方定位即「可靠投递 LLM token、工具结果、进度更新」，支持数万并发流[^11^]。
- Pydantic AI 集成：`run_stream()`/`run_stream_events()` 在 DBOS workflow 内可用，但事件是**缓冲后重放**而非实时；要实时事件须用 `DBOSDurability(event_stream_handler=...)`（在 durable step 内实时投递）[^4^]。
- AI Quickstart 把「durable streaming」列为集成 DBOS 的四大收益之一[^22^]。

## 6. 与 agent 框架 / MCP 的集成（官方）

**官方文档/源码事实**（AI Quickstart 列出的原生集成）[^22^]：

| 框架 | 集成方式 | 仓库/文档 |
|---|---|---|
| Pydantic AI | `DBOSDurability` capability（`DBOSAgent` 包装器已 deprecated，v3 移除）；模型调用 + MCP 通信自动成 step | [^3^][^4^] |
| OpenAI Agents SDK | `dbos-openai-agents` 包，`DBOSRunner.run()` drop-in 替换 `Runner.run()`，工具/guardrail 标 `@DBOS.step` | [^23^] |
| Vercel AI SDK (TS) | `@dbos-inc/vercel-ai` middleware `durableCalls` / `durableMCPTools` / `durableEmbeddingCalls` | [^2^][^6^] |
| Google ADK | `dbos-google-adk` 的 `DBOSPlugin` | [^19^] |
| LlamaIndex | 原生集成（awesome-dbos 列出；示例 rag-slackbot） | [^24^][^25^] |
| LangGraph | 无官方插件；博客示例：把 `@DBOS.workflow` 函数包成 LangChain `@tool`，配合 LangGraph `PostgresSaver` 做 agent 状态 checkpoint | [^16^] |
| MCP（反向） | DBOS 官方提供 **DBOS MCP server**（开源），让 coding agent 查询 workflow 状态/调试；Vercel AI 集成里 `durableMCPTools` 自动 checkpoint MCP 工具调用 | [^26^][^2^] |

**GitHub dbos-inc 组织下的 agent 示例仓库（源码事实）**：
- `dbos-inc/dbos-demo-apps`：`python/reliable-refunds-langchain`（客服退款 agent，含 "Crash System" 按钮演示崩溃恢复）、`python/pydantic-research-agent`（多 agent 深度研究：规划 Sonnet / 并行搜索 Gemini Flash / 综合 Sonnet）[^16^][^3^]
- `dbos-inc/dbos-vercel-ai`[^2^]、`dbos-inc/dbos-openai-agents`[^23^]、`dbos-inc/durable-swarm`（已被 OpenAI Agents SDK 集成取代）[^27^]
- `dbos-inc/awesome-dbos`（集成清单，另列社区项目如 Code Puppy durable coding agent）[^24^]
- DBOS MCP server 开源仓库（awesome-dbos / 博客引用）[^26^]

## 7. 对 pg_cordis 的映射要点（推断，非官方）

- DBOS 的全部机制都落在 Postgres 系统表上（checkpoint、队列、LISTEN/NOTIFY 唤醒、JSONB+GIN 可查询 workflow 属性[^11^]）——与 pg_cordis「Postgres 原生控制平面」同构，可直接借鉴其 schema 设计。
- 关键语义清单可直接抄：step 输出缓存重放（不幂等贵步骤的唯一解）、`should_retry` 谓词区分 4xx/5xx、协作式 step 超时（AbortSignal + 结果丢弃）、step 内流写 at-least-once vs workflow 内 exactly-once、fork-from-step 做 eval、被协作取消的 step 不 checkpoint 以便 resume 重跑。
- 已知边界：workflow 必须确定性（并发模型调用需拆 child workflow）；Python 尚无 step 级超时（2026-07 时 TS only）；durable 边界内不可 stream-cancel。

---

## 引用

[^1^]: Steps | DBOS Docs, https://docs.dbos.dev/python/tutorials/step-tutorial （访问 2026-08-23）【官方文档】
[^2^]: dbos-inc/dbos-vercel-ai (GitHub README), https://github.com/dbos-inc/dbos-vercel-ai （访问 2026-08-23）【官方源码】
[^3^]: Build Reliable AI Agents with Durable Execution, Pydantic 官方博客, https://pydantic.dev/articles/pydantic-ai-dbos （2026-02-19；访问 2026-08-23）【合作方官方博客，含 FAQ】
[^4^]: Durable Execution with DBOS, Pydantic AI 文档, https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/ （访问 2026-08-23）【官方文档】
[^5^]: What's New in DBOS - June 2026, https://www.dbos.dev/blog/new-in-dbos-june-2026 （2026-06-22；访问 2026-08-23）【官方博客】
[^6^]: Vercel AI SDK | DBOS Docs, https://docs.dbos.dev/integrations/vercel-ai （访问 2026-08-23）【官方文档】
[^7^]: Building Durable Agents with DBOS and Databricks, https://www.dbos.dev/blog/building-durable-agents-dbos-databricks （2026-04-07；访问 2026-08-23）【官方博客观点】
[^8^]: Logging & Tracing | DBOS Docs, https://docs.dbos.dev/python/tutorials/logging-and-tracing （访问 2026-08-23）【官方文档】
[^9^]: Workflows | DBOS Docs (Python), https://docs.dbos.dev/python/tutorials/workflow-tutorial （访问 2026-08-23）【官方文档】
[^10^]: Workflows | DBOS Docs (TypeScript), https://docs.dbos.dev/typescript/tutorials/workflow-tutorial （访问 2026-08-23）【官方文档】
[^11^]: What's New in DBOS - July 2026, https://www.dbos.dev/blog/new-in-dbos-july-2026 （2026-07-23；访问 2026-08-23）【官方博客/发布说明】
[^12^]: Workflow Management | DBOS Docs (Python), https://docs.dbos.dev/python/tutorials/workflow-management （访问 2026-08-23）【官方文档】
[^13^]: Workflow Management | DBOS Docs (Go), https://docs.dbos.dev/golang/tutorials/workflow-management （访问 2026-08-23）【官方文档】
[^14^]: Workflow Retention Policies | DBOS Docs, https://docs.dbos.dev/production/dbos-cloud/retention （访问 2026-08-23）【官方文档】
[^15^]: DBOS Client | DBOS Docs, https://docs.dbos.dev/python/reference/client （访问 2026-08-23）【官方文档】
[^16^]: Durable Execution for Building Crashproof AI Agents, DBOS 博客, https://www.dbos.dev/blog/durable-execution-crashproof-ai-agents （2025-02-24；访问 2026-08-23）【官方博客，含 LangGraph 集成示例】
[^17^]: Why DBOS? | DBOS Docs, https://docs.dbos.dev/why-dbos （访问 2026-08-23）【官方文档】
[^18^]: Building Durable AI Agents with Pydantic AI, DBOS, and Neon, https://neon.com/guides/pydantic-ai-dbos-neon （访问 2026-08-23）【合作方教程】
[^19^]: DBOS plugin for ADK, https://adk.dev/integrations/dbos/ （访问 2026-08-23）【Google ADK 官方集成文档】
[^20^]: Communicating with Workflows | DBOS Docs, https://docs.dbos.dev/python/tutorials/workflow-communication （访问 2026-08-23）【官方文档】
[^21^]: What's New in DBOS - June 2026（durable streams LISTEN/NOTIFY）, https://www.dbos.dev/blog/new-in-dbos-june-2026 （访问 2026-08-23）【官方博客】
[^22^]: AI Quickstart | DBOS Docs, https://docs.dbos.dev/ai/ai-quickstart （访问 2026-08-23）【官方文档】
[^23^]: dbos-inc/dbos-openai-agents (GitHub), https://github.com/dbos-inc/dbos-openai-agents （访问 2026-08-23）【官方源码】；另见 DBOS Product Enhancements March 2026, https://www.dbos.dev/blog/dbos-new-features-march-2026
[^24^]: dbos-inc/awesome-dbos (GitHub), https://github.com/dbos-inc/awesome-dbos （访问 2026-08-23）【官方清单】
[^25^]: AI-Powered Slackbot | DBOS Docs, https://docs.dbos.dev/python/examples/rag-slackbot （访问 2026-08-23）【官方文档】
[^26^]: Building an Open Source Developer Experience Agents will Love, DBOS 博客, https://www.dbos.dev/blog/how-to-build-a-developer-experience-agents-will-love （2026-05-11；访问 2026-08-23）【官方博客，DBOS MCP server】
[^27^]: dbos-inc/durable-swarm (GitHub，已弃用), https://github.com/dbos-inc/durable-swarm （访问 2026-08-23）【官方源码】

## 未获取到 / 未覆盖

- DBOS 未提供 token 预算/配额/成本上限原语（仅有「不重复重放省 token」+ OTel token 属性观测）；未找到官方成本治理文档，判定为**不存在该功能**而非检索遗漏。
- Python/Java 版 step 级超时在 2026-07 公告时为「coming soon」，之后是否发布未核实。
- LangChain/LangGraph 无官方 DBOS 插件（仅博客模式与 demo），第三方插件未检索。
