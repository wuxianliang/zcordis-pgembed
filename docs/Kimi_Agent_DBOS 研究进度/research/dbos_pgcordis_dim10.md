# DBOS 边界、限制与商业架构 — pg_cordis 对照研究（Dimension 10）

> 研究日期：2026-08-23。为 pg_cordis（executor 即 PostgreSQL 内 SQL 函数、无外部进程）提供对照。
> 标注约定：【官方承认】= DBOS 官方文档/博客/仓库自述；【第三方】= 媒体/社区/客户；【推断】= 本报告分析。

## 1. 性能上限（官方口径）

【官方承认】
- DBOS 的开销**只有数据库写**：每 workflow 2–3 次写（开始记录输入、结束记录输出、可选 dequeue），每 step 额外 1 次 checkpoint 写。可扩展性"根本上由所连接的 Postgres 决定"。[^47^]
- 基准（AWS RDS db.m7i.24xlarge，96 vCPU，120K IOPS）：单 Postgres 服务器 **144K 写/秒**，**43K workflow/秒**（=86K 写/秒，约 40 亿 workflow/天）；瓶颈是 **WAL flush**。[^132^][^119^]
- **队列模式明显下降**：单队列仅 12.1K workflow/秒，瓶颈是 workflow_status 表队首行的**锁竞争**（SKIP LOCKED 也救不了）；多队列/分区后 30.6K/秒（约为直接启动的 2/3）。[^132^]
- 生产清单的保守口径：1000 actions/秒 需 4 个 Postgres vCPU；超过 1K/秒应做负载测试；接近或超过 40K/秒建议**跨多个 Postgres 分片**。[^124^]
- 2026 年优化项反推此前瓶颈：worker 并发度从数据库改为内存追踪、无全局并发限制时降级到 READ COMMITTED、为 workflow_status 加部分索引减少写放大和 autovacuum 抖动。[^119^]

【推断】对 pg_cordis 的对照点：DBOS 的每步一次跨进程 checkpoint 写 + 队列锁竞争，正是"executor 搬进数据库内"想消除的开销；但 DBOS 的 43K/s 数字是在 96 vCPU RDS 上测得，单机嵌入式 SQL executor 的对比基线需注意硬件差异。

## 2. 架构形态与商业分层

【官方承认】
- DBOS Transact 是**纯 library**："entirely contained in this open-source library, there's no additional infrastructure"，唯一外部依赖是 Postgres（任何兼容库：Neon/Supabase/RDS/Aurora）。[^6^][^125^]
- 恢复模型：executor 是**外部进程**（你的应用服务器），崩溃后由**另一个存活进程**轮询 Postgres 系统表接管恢复。"workers are fungible and can freely recover each other's state, so the system is available as long as the underlying database is available."[^133^] 即：最后一个 executor 死了、数据库还活着，workflow 不会自己继续——必须有外部进程重启。
- 商业分层（open-core）【官方+第三方】：DBOS Transact（开源 library，Python/TS/Go/Java/Kotlin）→ DBOS Conductor（控制面/可观测）→ DBOS Cloud（托管 serverless）。收入来自 Cloud 托管。[^118^]
- DBOS Cloud 架构：AWS 上基于 **Firecracker microVM** 的事务型 FaaS；状态在 Postgres，executor 是 ephemeral microVM，可自动扩缩/迁移/故障切换；代码更新按 workflow 版本路由（新请求进新 microVM，旧 workflow 由旧版本 microVM 后台跑完）。[^117^][^125^]
- **Time Travel Debugger 是 Cloud 专有**："replay any DBOS Cloud trace locally"；time travel queries 仅实验性。开源自托管只有 SQL 可查的系统表，没有回放调试器。[^112^][^123^][^125^]

【推断】DBOS 的整套商业结构（Cloud 托管 executor、Conductor 观测、Cloud 专有调试器）恰恰建立在"executor 是外部进程、需要被托管"这一前提上。pg_cordis 若把 executor 放进 PG 内部，则没有可托管的 executor 层——商业模式需另寻（扩展许可、托管 PG、工具链）。

## 3. 官方/社区承认的限制

【官方承认】
- **大 payload**：checkpoint 写大小 = 输入/输出大小；官方明确建议 step 避免大输出（大文件放 S3，step 只返回指针）。[^47^]
- **连接数**：Postgres 约 100 连接/GB 内存；每个 DBOS 应用服务器都要占连接，sys_db_pool_size 不建议低于 5；fan-out 下连接预算是硬约束。[^124^]
- **高 fan-out / 队列竞争**：见 §1，单队列 12.1K/s 的锁竞争瓶颈，需多队列/分区摊薄。[^132^]
- **确定性约束**：workflow 控制流必须确定性，非确定调用必须包进 step；TS 侧甚至写了 ESLint 静态分析工具查全局变量。[^125^][^39^]
- **step 副作用只是 at-least-once**：崩溃可能落在外部调用和 checkpoint 之间，外部调用必须幂等（Temporal 同款 caveat）。[^39^]
- 长事务风险的具体 GitHub issue：**未获取到**（检索未定位到官方承认"长事务"为限制的具体 issue/discussion；官方口径中 workflow 不是单个长事务，而是逐步 checkpoint 的短事务序列——这本身就是对长事务风险的规避设计）【推断】。

【第三方】
- fan-out 撞 max_connections 是普遍失败模式（Render 文章以 PgBouncer 事务池化解）。[^131^]
- 对比评测：DBOS 产品较新（2024 商用）、生态和社区小于 Temporal、需要懂数据库概念。[^116^]
- 自托管对比：DBOS 与 Python/TS+Postgres 耦合紧，复杂异构技术栈下是局限。[^126^]

## 4. DBOS 不做的事（官方定位）

【官方承认】
- 未找到逐字 "DBOS is not..." 官方句式（**未获取到**原文），但官方定位一致收敛为"lightweight durable execution library on Postgres"——即只做**持久化执行原语**（workflow/step/queue/schedule/notification），不做代码解析、检索或 agent 编排本身。[^6^][^7^]
- 佐证：agent 编排交给宿主框架——官方/生态集成（Pydantic AI `DBOSDurability`、LangGraph、Vercel AI SDK `durableCalls`）都是"把模型调用/工具调用包成 DBOS step"，DBOS 只提供 checkpoint，不提供 agent loop。[^71^][^66^]
- 第三方定位印证：Concord 架构文写道 "DBOS owns durable execution"，agent framework/workflow runtime/policy 均归别人。[^130^]

## 5. 与 Temporal 对比中 DBOS 自认的取舍

【官方承认】
- DBOS = Postgres-backed 轻量 library；Temporal = 外部编排 server，需要把程序重构为 worker + server + client 三件套。[^110^]
- **何时选 Temporal（官方自述）**：不想在栈里加 Postgres；需要 DBOS 尚不支持的语言。[^110^]
- 规模取舍：DBOS 上限 = 单 Postgres 上限，超过 40K/s 必须**手动分片**；Temporal 集群的横向扩展由服务端承担【推断：这是"library 简单性"换来的】。[^124^][^133^]
- 官方营销口径强调零运维、无 DSL、学习曲线低。[^121^]

## 6. 社区 Rust 移植说明了什么

- hwuiwon/dbos-transact-rust：独立社区实现（MIT，明确"非 DBOS Inc. 背书"），Postgres **或 SQLite** 双一等后端，`sqlite::memory:` 即可跑，含 queues/scheduling/debouncer/client/CLI。[^1^]
- 另有第二个 Rust 移植 SamuelXing/durare，同样复刻 operation_outputs checkpoint 模型。[^39^]
- Pydantic AI 文档亦用 `sqlite:///dbostest.sqlite` 做示例（"Postgres recommended for production"）。[^71^]

【推断】
1. DBOS 的编程模型已被社区视为**可移植协议**而非 Postgres 专有机制——checkpoint 表 + 轮询 dequeue 的模式在 SQLite 上也成立，说明其价值在语义而非存储引擎。
2. SQLite 移植同时也反证了 DBOS 架构的保守性：它只要求"一个能读写的数据库"，完全没有利用 PG 内部能力（PL/pgSQL、触发器、LISTEN/NOTIFY 之外的扩展钩子）。pg_cordis 的"executor 即 SQL 函数"是在同一状态模型上向数据库内部再迈一步，与 Rust 移植的"向外通用化"方向正好相反，构成差异化定位。

## 关键未获取到项
- DBOS GitHub issues 中关于长事务/大 payload 的具体承认帖：**未获取到**（官方文档建议已覆盖大 payload；长事务未见官方列为问题）。
- DBOS Cloud 内部 executor 实现的更多技术细节（microVM 与 PG 的连接拓扑）：仅获取到 Firecracker + 版本化路由的公开描述。
- "DBOS is not..." 逐字官方表述：未获取到。

## 来源
- [^1^] https://github.com/hwuiwon/dbos-transact-rust （访问 2026-08-23）
- [^6^] https://github.com/dbos-inc/dbos-transact-py （访问 2026-08-23）
- [^7^] https://github.com/dbos-inc/dbos-transact-ts （访问 2026-08-23）
- [^39^] https://github.com/SamuelXing/durare/ （访问 2026-08-23）
- [^47^] https://docs.dbos.dev/architecture （访问 2026-08-23）
- [^66^] https://github.com/dbos-inc/dbos-vercel-ai （访问 2026-08-23）
- [^71^] https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/ （访问 2026-08-23）
- [^110^] https://github.com/DBOS-project/dbos-transact-py （DBOS vs. Other Systems，访问 2026-08-23）
- [^112^] https://www.npmjs.com/package/@dbos-inc/dbos-sdk/v/1.18.3-preview （访问 2026-08-23）
- [^116^] https://www.respan.ai/market-map/compare/dbos-vs-temporal （访问 2026-08-23）
- [^117^] https://www.infoworld.com/article/2336467/ （访问 2026-08-23）
- [^118^] https://yespress.io/dbos-inc （访问 2026-08-23）
- [^119^] https://www.dbos.dev/blog/new-in-dbos-may-2026 （访问 2026-08-23）
- [^121^] https://www.dbos.dev/compare/compare-dbos-vs-temporal-dbos （访问 2026-08-23）
- [^123^] https://www.dbos.dev/blog/announcing-dbos （访问 2026-08-23）
- [^124^] https://docs.dbos.dev/production/checklist （访问 2026-08-23）
- [^125^] https://www.dbos.dev/blog/sf-systems-meetup-2024-talk （访问 2026-08-23）
- [^126^] https://void.abn.is/dbos-vs-temporal-choosing-your-durable-executor/ （访问 2026-08-23）
- [^130^] https://tushar1344.github.io/concord-architecture/what-concord-is.html （访问 2026-08-23）
- [^131^] https://render.com/articles/200-concurrent-task-runs-meet-your-postgres-connection-limit-the-fan-out-failure （访问 2026-08-23）
- [^132^] https://www.dbos.dev/blog/benchmarking-workflow-execution-scalability-on-postgres （访问 2026-08-23）
- [^133^] https://www.dbos.dev/blog/postgres-is-all-you-need-for-durable-execution （访问 2026-08-23）
