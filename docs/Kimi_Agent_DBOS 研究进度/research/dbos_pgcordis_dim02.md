# DBOS 愿景层与原型论文研读：pg_cordis 应借鉴什么

研究维度：DBOS 愿景层（状态全入 DBMS、一切操作即事务）及其实现原型（Apiary、Lotus）对 pg_cordis（PostgreSQL 原生 agent 控制平面插件运行时，executor 即 SQL 函数、全在 PG 内）的启示。
访问日期：2026-08-23。

---

## 1. DBOS 愿景论文（arXiv 2020）

**论文**：The DBOS Committee (Cafarella, DeWitt, Gadepally, Kepner, Kozyrakis, Kraska, Stonebraker, Zaharia), *DBOS: A Proposal for a Data-Centric Operating System*, arXiv:2007.11112, 2020-07-21。[^1^][^2^]

### 核心论证（愿景层）

- **问题诊断**：主流 OS 源自 1980 年代单处理器设计，面对今天云环境（数十万个处理器、异构硬件、百万级用户、大规模并行任务）在可扩展性、可用性、安全性上不堪重负。[^2^]
- **核心主张（data-centric 架构）**：**所有 OS 状态统一表示为数据库表**（process table、scheduler state、flow tables、permissions tables 全部变成表），**对这些状态的操作全部通过查询，由 otherwise-stateless 的任务发起**。即状态与计算显式分离，全部状态集中到统一数据模型。[^1^][^2^]
- **理由（为什么是 DBMS 表+事务）**：
  1. 可扩展性工作可共享——不必为几十个内核数据结构分别做多核扩展，只需扩展通用表操作的实现一次；[^1^]
  2. 调试、监控、安全特性针对统一表格数据模型实现一次即可，无需与每个 OS 组件分别集成；[^1^]
  3. 状态显式隔离后，可实现根本性能力：zero-downtime 升级、分布式横向扩展（scale-out）、丰富监控、新安全模型、ML 驱动决策。[^1^][^2^]
- **实现路线**：直接在**scale-out DBMS 引擎之上构建 OS**（"build a database operating system, DBOS"），复用 DBMS 数十年关键任务工程的可靠性与运维经验；DBMS 引擎只需少量引导性资源管理功能。[^1^] 论文指出 DBMS 已在管理全球最大系统中最关键的信息（如云厂商控制平面），因此足以承担下一代 OS 的状态管理。[^1^]

### 对 pg_cordis 的直接映射

DBOS 的"OS 状态=表，OS 操作=无状态任务发起的事务查询"与 pg_cordis 的"agent 控制平面状态（任务、会话、消息、lease、审计日志）=PG 表，executor=PG 内 SQL/PL 函数"是同一论点在不同层面的实例化。DBOS 论文为 pg_cordis 提供的正当性论证：**把控制平面状态放入 DBMS 而非外部进程内存，是为了让扩展、可观测、安全、升级等横切能力只针对表模型实现一次**。pg_cordis 应把"任何控制平面状态变更都必须经事务落库、executor 不持有权威内存状态"作为架构红线。

---

## 2. Apiary（DBMS-integrated FaaS，DBOS 团队原型）

**论文**：Kraft, Li, Kaffes, Skiadopoulos, Kumar, Cho, Li, Redmond, Weckwerth, Xia, Bailis, Cafarella, Graefe, Kepner, Kozyrakis, Stonebraker, Suresh, Yu, Zaharia (Stanford/MIT/CMU/Google/VMware/UW-Madison), *Apiary: A DBMS-Integrated Transactional Function-as-a-Service Framework*, arXiv:2208.13068（v1 2022-08，v2 2023-06）。[^3^][^4^] 这是 DBOS 愿景的 FaaS 层实现（DBOS Transact 前身）。

### 2.1 架构与 executor/数据库职责划分

- **动机数据**：数据密集型 FaaS 应用 93–99% 的运行时花在与 DBMS 通信或执行 DBMS 操作上；OpenWhisk 函数一次点更新中通信占 98%。[^4^]
- **架构**：Apiary **包裹一个分布式 DBMS（VoltDB），把函数编译为存储过程**（非 SQL 语言例程，原生作为 DBMS 事务运行），从而"函数成为控制流与原子性的基本单位"。三层：Client → Frontend（dispatcher 编排工作流、registrar 注册/插桩/编译）→ Backend（DBMS 服务器上事务性执行函数）。[^4^]
- **职责划分**：**数据库负责**执行、数据管理、操作日志、容错记录、弹性伸缩（依赖 DBMS 原生 scale-out）；**frontend dispatcher 是无状态的编排者**——故障后客户端用唯一 workflow ID 重发请求，新 dispatcher 从头重放工作流并跳过已完成函数。[^4^]

### 2.2 短事务执行 + 状态落库 ⇒ exactly-once

- **每个函数作为可串行化 ACID 事务执行**；支持 *multi-function transactions*（把工作流中连通子图编译为单个存储过程），避免整工作流单大事务的性能问题。[^4^]
- **保证**：工作流 run-to-completion + 每个函数 exactly-once。机制：函数被插桩，在返回前**在同一事务内把输出记录进 DBMS**（以 workflow ID 派生的唯一 function invocation ID 为键）；重放时先查记录、命中则直接返回已记录输出而不重执行。[^4^]
- **SFR（Selective Function Recording）优化**：朴素地记录所有函数输出开销高达 2.2×；通过注册时静态分析，只记录"有写操作的函数"以及"到多个被记录函数存在不相交路径的只读函数"，开销降到 <5%（实际只有 0.2%–25% 的事务执行需要记录）。[^4^]
- **函数三规则**：SQL 全部为静态参数化 prepared statement（供静态分析与 tracing）；函数必须确定性；外部调用必须幂等。[^4^]
- **性能**：比 OpenWhisk 快 7–68×，比 Boki/Cloudburst 快 2–27×；可观测性 tracing 开销 <15%（手工日志 92%）。[^3^][^4^]

### 2.3 对 pg_cordis 的意义

- Apiary 证明"executor 就是存储过程、全在 DBMS 内"不仅可行而且**更快更强保证**——pg_cordis 把 executor 做成 SQL 函数恰是 Apiary 的编译目标，省去了 Apiary 的编译/插桩前端。
- exactly-once 的最小机制 = **"执行记录与业务写在同一事务提交"**（输出表/结果表以 invocation ID 为唯一键），重放 = 从头重跑 + 命中记录即短路。pg_cordis 可直接用 PG 唯一约束 + ON CONFLICT 实现，无需额外事务管理器。
- 可借鉴 SFR 思想：只对有副作用（写表/发消息/调用外部工具）的步骤强制落库记录，纯只读推理步骤可安全重跑。
- multi-function transaction 对应 pg_cordis 中"多个 agent 步骤打包为一个 PG 事务"的能力——这是"全在 PG 内"独有的、外部编排器做不到的原子性粒度。
- 局限提示：Apiary 明确把**长时计算密集任务**列为 non-goal（交给外部服务）。pg_cordis 若 executor 要调用 LLM（长延迟外部调用），不能把它包在长事务里；应借鉴其"外部调用必须幂等 + 调用结果落库"的规则，把 LLM 调用放在短事务之间。

---

## 3. Lotus（VLDB 2022）

**论文**：Xinjing Zhou, Xiangyao Yu, Goetz Graefe, Michael Stonebraker, *Lotus: Scalable Multi-Partition Transactions on Single-Threaded Partitioned Databases*, PVLDB 15(11): 2939–2952, 2022。[^5^][^6^]

### 3.1 核心内容

- 重新审视 H-Store/VoltDB 的 **RCST（run-to-completion-single-thread）** 并发控制：每分区绑定单线程，事务run-to-completion 执行，单分区（SP）事务无锁、极快（数百万 TPS），但多分区（MP）事务性能糟糕（全局串行、分区级锁、2PC+同步复制）。[^5^]
- 两个贡献：(1) **granule-level locking**（分区细分为逻辑 granule 作为锁与复制单元，S2PL + NO_WAIT），把 MP 并发度提上来，使 RCST 在广泛 MP 负载上优于 OCC/2PL+2PC（最高 60% 吞吐优势）；(2) **MEST（multiplexed-execution single-thread）**：一批 MP 事务交错执行、批量一次提交，摊薄网络与提交开销，SP 事务吞吐最高 21× 于 Aria/Calvin 类批式确定性方案，且对 straggler 更鲁棒（无需集群级同步）。[^5^]
- 日志/提交：command logging（记录事务输入+锁序的 coordinator/participant records），批量 flush 即提交，近似 1PC，无强制 2PC vote 日志；副本异步确定性重放。[^5^]

### 3.2 与 DBOS 的关系（直接证据）

论文原文明确写道："**DBOS which runs on top of VoltDB is overwhelmingly SP transactions. However, as noted in [40], better support for MP transactions would make DBOS life a lot easier.**"[^5^] 即 Lotus 是 DBOS 团队为修补其执行底座（VoltDB/H-Store RCST 模型）MP 事务短板而做的引擎层工作；Apiary 论文也把 Lotus 列为解决 VoltDB 多分区事务低效的相关研究。[^4^]

### 3.3 对 pg_cordis executor 模型的启示

- **"短事务、run-to-completion、分区内单线程无锁"是 DBOS executor 高性能的根源**；代价是跨分区（多 agent/多租户共享数据）事务贵。pg_cordis 运行在单实例 PG 上，天然没有 MP 问题，但 Lotus 的教训仍然适用：
  - **数据分区亲和性设计**：Lotus/Apiary 都假设绝大多数事务 single-sited（按 tenant/agent/session 分区）。pg_cordis 应让 executor 事务尽量只触碰单个 agent/会话的状态行，跨 agent 操作走显式消息表而非共享状态大事务。
  - **短事务纪律**：RCST 模型下单个长事务会阻塞整个分区线程；对应到 PG，executor 的长事务持有锁/膨胀 WAL 同样会阻塞整个控制平面。Lotus 的 MEST"交错执行+批量提交"思想提示：pg_cordis 的调度循环应批量处理到期任务、避免在事务内等待外部 I/O。
  - **确定性 + command logging ⇒ 可重放恢复**：Lotus 靠记录输入+顺序实现确定性重放；pg_cordis 若要求 executor 函数确定性（与 Apiary 规则一致），恢复/重放/审计都可简化为重放输入日志。

---

## 4. 综合：pg_cordis 应从 DBOS 借鉴的清单

1. **状态全部落库（DBOS 愿景）**：任务队列、会话、lease、结果、审计全为 PG 表；executor 无权威内存状态，任何状态变更经事务。收益：可观测/调试/安全/升级只需针对表模型做一次。[^1^][^2^]
2. **executor = 存储过程化的事务（Apiary）**：每个执行步骤是一个短的可串行化 ACID 事务；函数是控制流与原子性的统一单位。[^4^]
3. **exactly-once = 同事务记录输出 + 重放短路（Apiary §4）**：invocation ID 唯一键，结果与业务写同一事务提交；dispatcher 故障后用 ID 重放，命中记录即返回。[^4^]
4. **选择性记录（SFR）**：只强制记录有副作用的步骤，纯计算步骤可重跑，把容错开销从 2.2× 降到 <5%。[^4^]
5. **函数三规则**：静态 SQL、确定性、外部调用幂等——前两者使恢复/重放/审计可行，第三者约束 LLM 等外部调用的事务边界。[^4^]
6. **multi-function transaction**：需要原子性的相邻步骤合并为一个 PG 事务，避免"整个 agent 循环一个大事务"。[^4^]
7. **短事务纪律与单分区亲和（Lotus/H-Store）**：executor 不在事务内做网络等待；跨 agent 交互走消息表（single-sited 事务为主）；批处理调度循环摊薄提交成本。[^5^]
8. **可观测性内建（Apiary §5 / DBOS 愿景）**：tracing/审计通过事务内 CDC 式捕获自动产生，而非事后手工日志（开销 15% vs 92%）。[^4^]
9. **明确 non-goal 边界**：长时计算/外部 LLM 调用不进事务，采用"幂等外部调用 + 结果落库"模式（Apiary non-goals 与函数规则 3）。[^4^]

---

## 引用

- [^1^]: DBOS Committee, "DBOS: A Proposal for a Data-Centric Operating System"（正文节选镜像）, https://www.modb.pro/doc/126523 ，访问日期 2026-08-23。
- [^2^]: DBOS Committee, "DBOS: A Proposal for a Data-Centric Operating System", arXiv:2007.11112 abs 页, https://arxiv.org/abs/2007.11112v1 （PDF: https://arxiv.org/pdf/2007.11112 ），访问日期 2026-08-23。
- [^3^]: Kraft et al., "Apiary: A DBMS-Integrated Transactional Function-as-a-Service Framework", arXiv:2208.13068 abs 页, https://arxiv.org/abs/2208.13068 ，访问日期 2026-08-23。
- [^4^]: Kraft et al., "Apiary: A DBMS-Integrated Transactional Function-as-a-Service Framework", arXiv:2208.13068 HTML 全文, https://arxiv.org/html/2208.13068 ，访问日期 2026-08-23。
- [^5^]: Zhou, Yu, Graefe, Stonebraker, "Lotus: Scalable Multi-Partition Transactions on Single-Threaded Partitioned Databases", PVLDB 15(11): 2939–2952, 2022, https://www.vldb.org/pvldb/vol15/p2939-zhou.pdf ，访问日期 2026-08-23。
- [^6^]: Lotus 引用条目（PVLDB 15(11) 2939–2952）见于 Styx 论文参考文献, https://arxiv.org/html/2312.06893v4 ，访问日期 2026-08-23。

注：三篇论文全文/摘要均已成功获取，无"未获取到"项。
