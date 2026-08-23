# 维度01：DBOS 两篇奠基论文的论文层证据

> 研究问题：pg_cordis（PostgreSQL 原生 agent 控制平面插件运行时，一切皆表 + SQL 函数）应从 DBOS 借鉴什么。
> 本文档只提供两篇论文的一手证据，明确区分「论文主张（理论论证）」与「原型实测数据（DBOS-straw / VoltDB 原型）」。
> 所有内容于 2026-08-23 从公开 PDF 提取全文并逐节核对。

**所研读论文**：
- [P1] VLDB 2022《DBOS: A DBMS-oriented Operating System》（PVLDB 15(1): 21-30）[^1^]
- [P2] CIDR 2022《A Progress Report on DBOS: A Database-oriented Operating System》（CIDR'22）[^2^]

---

## 1. 为什么「一切皆事务/一切皆表」优于「一切皆文件」——核心论证（论文主张）

**P1 §1 Introduction**：论文直接宣判 Unix 抽象已过时：
> "the 'everything is a file' model for managing uniprocessor hardware — a revolutionary position for Unix in 1973 — is ill-suited to modern computing challenges." [^1^]

替代方案是：
> "a radical change towards an 'everything is a table' abstraction that represents all OS state as relational tables, leveraging modern DBMS technology to scale OS functionality to entire datacenters." [^1^]

论证链条（P1 §1–§2.1，均为理论主张）：
1. **规模论**：OS 资源管理问题已变成"big data problem"。"At scale, managing system services is a 'big data' problem, and Linux itself contains no such capabilities."（P1 §1）[^1^]
2. **抽象论**："Unix offers abstractions that are too few and too low-level for managing the multiple levels of complexity and huge amounts of state that modern systems must handle."（P1 §1）[^1^]
3. **一次实现论（do everything just once）**："transactions, high availability and multi-node support are provided exactly once, by the DBMS, and then used by everybody. This results in much simpler code, due to avoiding redundancy. Also, current non-transactional data structures get transactions essentially for free."（P1 §2.2）[^1^]；P2 §4.5 重复此主张："transactions and high availability can be implemented just once inside the DBMS and then used by all OS services as well as user-level tasks." [^2^]
4. **可观测性论**："in DBOS, the entire state of the OS and the application is available in structured tables that can simply be queried using SQL… Likewise, all in-flight IPC messages are queriable as a table, and can be retained for later analysis."（P1 §2.1 Level 4）[^1^]
5. **模式纪律论**："Moving to DBOS will force DBMS schema discipline on this information. It will also allow querying across the range of OS data using a single high-level language, SQL."（P1 §2.2）[^1^]
6. **历史类比**：论文把质疑者与 1970 年代 CODASYL 拥护者类比："They said 'you can't possibly do data management in a high-level language (tables and a declarative language). It will never perform.' History eventually proved them wrong."（P1 §2.2）[^1^]

**P2 §2** 把口号精确化为架构原则，与 pg_cordis 的「一切皆表+SQL 函数」几乎逐字对应：
> "DBOS centralizes system state and user data in a uniform data model as database tables and executes all operations on state as DBMS transactions, invoked from otherwise stateless processes." [^2^]
> "we believe that all levels of the system stack, from high-level applications down to core services like schedulers, file systems, and monitoring, should manage their state centrally in a distributed transactional DBMS." [^2^]

> **对 pg_cordis 的含义**：DBOS 的核心论据不是性能，而是 (a) 事务/HA 只做一次、(b) 全局状态可用单一声明式语言查询、(c) schema 纪律。pg_cordis 作为 PG 插件可原样继承这三条。

## 2. 调度、IPC、文件系统作为 DB-backed 服务：设计与性能

### 2.1 调度器（P1 §4.2；P2 §4.1）
- **设计**：两张表 `Task(p_key, task_id, worker_id, other_fields)` 与 `Worker(p_key, worker_id, unused_capacity)`；调度器是存储过程（P1 Figure 2 给出完整 FIFO 调度器 SQL 代码）。调度策略改变 = 改几行 SQL：least-loaded 调度器相对 FIFO "only required changing a single line of code, i.e., adding a 'order by unused_capacity desc' clause"。[^1^]
- **实测（原型数据，VoltDB，2 节点 40 分区，合成负载只调度不执行）**："the simple FIFO scheduler can schedule 750K tasks per second at a sub-millisecond tail latency while the median latency remains around 200 μs even at 1M tasks/sec load"（P1 §4.2）[^1^]。P2 §4.1 报告更新数据：40 分区下 "as many as one million tasks per second with sub-millisecond tail latency, and as many as two million tasks per second with sub-millisecond median latency"，吞吐随分区数近线性扩展；并论证两台服务器即可饱和 20 万核（100ms serverless 任务、调度开销 <1%），而"Spark cluster with tens of thousands of nodes can only launch a thousand tasks per second"。[^2^]

### 2.2 IPC（P1 §4.3）
- **设计**：单表 `Message(sender_id, receiver_id, message_id, data)`，按 receiver_id 分区；发送 = 单分区 INSERT，接收 = 本地读 + 删除（exactly-once）。"If we replicate the Message table, failover will allow the IPC system to continue in the face of failures, without loss of data, a stronger guarantee than what TCP or existing RPC systems provide." [^1^]
- **实测（原型数据）**：ping-pong 基准中 "DBOS achieves 24%–49% lower throughput and 1.3–2.5× higher median latency compared to gRPC, and DBOS achieves 4–9.5× lower performance than TCP/IP"；但批量（ping20-pong20）小消息场景 "DBOS outperforms gRPC by up to 2.7×"，扇出 40 接收者时 "2.3× higher throughput and 64% lower median latency than gRPC"。[^1^]
- **承认的限制（P1 §4.3.2）**：接收方必须轮询 Message 表；"support for database triggers would avoid polling altogether. Several DBMSs implement triggers, e.g., Postgres, but VoltDB does not." [^1^] —— 这是对 pg_cordis 最直接的一条证据：**DBOS 论文点名 Postgres 的 trigger 机制正是 VoltDB 所缺**。

### 2.3 文件系统（P1 §4.4）
- **设计**：五种表（Map/User/Directory/Localized_file/Parallel_file）；全限定文件名使 open/close 成为 no-op；"block-size can be changed by a single SQL update"。[^1^]
- **实测（原型数据）**：写性能匹配或超过 ext4（避开全局锁）；读性能显著落后，因为 "the invocation cost of VoltDB is around 40 microseconds, whereas the cost of a Linux system call is approximately 1 microsecond"；文件创建/删除比 ext4 快约 10×（单次 insert vs 目录遍历；P1 Table 1：create 67.48μs vs 656.78μs）；条件聚合分析：SQL 2 行 / 0.65ms vs C++ 98 行 / 9.90ms（P1 Table 2）；并行文件系统 4 个客户端即可打满 25Gbps 网络（Lustre 16 客户端只到 70%），节点数 >2 后近线性扩展。[^1^]

> **对 pg_cordis 的含义**：调度=表+存储过程、消息=表+INSERT/DELETE、策略演进=改 SQL，这三点已被原型验证；但 IPC/FS 的调用开销（VoltDB 40μs vs syscall 1μs）说明热路径需要共享内存/进程内调用，PG 插件架构（进程内 C 函数 + SPI）恰好比外部 DBMS 更接近这个目标。

## 3. Time-travel 调试的实现原则

**两篇论文中均未出现 "time-travel debugging" 一词**（该主题是 2023 年后 DBOS Transact / FoundationDB-recorded-workflow 论文的内容）。两篇论文中最接近的原语是 **provenance（来源追踪）**：

- P1 §1 把 provenance 列为第 (8) 项动机："Provenance data collection touches many elements of the system but is totally absent in most current OSes." [^1^]
- P2 §4.7 给出实现原则："All we needed was to capture all changes to system tables in a log (also a DB table) and then support SQL provenance queries to the log table." 由于历史 provenance 库巨大、不适合内存 OLTP，DBOS 被迫加入列存 OLAP DBMS（Vertica）成为 polystore："we needed to capture all writes and optionally all reads in VoltDB and spool them transactionally to Vertica." [^2^]
- 实测开销（原型数据）："capturing all object level reads and writes and streaming them into Vertica does not impact system performance until the transaction rate gets high (greater than 50K transactions per second)."（P2 §4.7）[^2^]
- P2 §5.1 展望 "pervasive monitoring"：用对象级 provenance 统一 Splunk/Prometheus 式监控。[^2^]

> **对 pg_cordis 的含义**：论文层的可借鉴原则是「把每一次状态变更捕获进日志表 + 用 SQL 查询日志表」。PG 生态可用触发器/逻辑解码/temporal 表在单库内实现，无需 polystore 拆分——这恰是 pg_cordis 相对 VoltDB 原型的潜在优势。

## 4. 确定性执行与重放恢复的原则

**两篇论文均未讨论确定性执行（deterministic execution）与重放恢复（replay recovery）**。检索全文，"deterministic" 仅出现于 P1 §1 对硬件趋势的描述（"even non-deterministic systems are just around the corner"），与执行语义无关；"replay" 未出现。两篇论文提供的相关原则只有：

- **事务化恢复**：VoltDB 提供 "serializability and transactional (or non-transactional) failover on a node failure"（P1 §4.1.1）[^1^]；"VoltDB manages the stored procedure library and executes all stored procedures transactionally, simplifying task execution and failure recovery"（P2 §4.2）[^2^]。
- **任务图模型作为替代容错手段**：由于 SP 不能互相调用，"DBOS provides a programming model where users submit graphs of subtasks and each subtask is executed on its parents' outputs"（P2 §4.6）[^2^]——DAG + 父输出传递是后来 DBOS 工作流确定性重放的雏形，但这两篇论文未做此论证。

> **明确标注：确定性执行/重放恢复 = 未获取到（不在这两篇论文范围内）**。

## 5. 微内核 vs DBOS 的代码复杂度对比

**两篇论文均未给出「微内核代码行数 vs DBOS 代码行数」的量化对比**。已有的复杂度证据：

- **论文主张（定性）**：摘要称 "a dramatic reduction in code complexity through implementing OS services as standard database queries, while implementing low-latency transactions and high availability only once"（P1 Abstract）[^1^]。
- **原型实测（微基准）**：P1 Table 2，条件聚合操作 SQL 2 行 vs C++ 98 行，且运行更快（0.65ms vs 9.90ms）[^1^]；调度策略变更只改一行 SQL（P1 §4.2）；"a 'hub and spoke' implementation of messaging is a few lines of SQL"（P1 §4.3.3）[^1^]。
- **工程经验（P2 §4.4）**："One of the unforeseen benefits of DBOS is the programmer productivity of SQL in both system evolution and initial system design… making even a small change to the widely used Spark or Kubernetes schedulers is a Herculean task… we were able to implement least-loaded and locality-aware schedulers simply by changing a couple of lines of SQL code." [^2^]

> **明确标注：微内核 vs DBOS 的 LoC 对比数据 = 未获取到**；论文只给出 OS 服务级的「几行 SQL vs 大量 C/C++」轶事性对比。

## 6. 论文承认的限制与开放问题

**P1（VLDB）承认的限制**：
- IPC 需轮询，缺触发器（§4.3.2）[^1^]
- VoltDB 调用开销 40μs vs 系统调用 1μs，读路径落后 ext4（§4.4）[^1^]
- IPC 相对 gRPC/TCP 仍有差距（轮询、额外拷贝、底层仍走 TCP）（§4.3.3）[^1^]
- 内存态数据集，spill-to-disk 留作 future work（§4.4）[^1^]
- 调度实验是合成的，"tasks are scheduled, but not executed"（§4.2）[^1^]

**P2（CIDR）承认的限制/开放问题**（§4.6–§4.13，§5）：
- VoltDB SP 模型：单分区串行执行 → head-of-line blocking；SP 不能调用 SP（无子程序）；无嵌套事务（§4.6）[^2^]
- 存储过程只能写 Java，难以使用 Tensorflow/PyTorch 生态（§4.2）[^2^]
- 多分区事务拿全局锁："0.1% multi-partition transactions decreased overall throughput by 50%"（§4.10）[^2^]
- 多租户安全不足：恶意 SP 可侵入 VoltDB 执行引擎内存（§4.11）[^2^]
- 缺 auto-scaling 与自动重分区（§4.12）；DBMS 调参困难（§4.9）；规模效应："things that work fine in the small fail for unforeseen reasons at scale"（§4.13）[^2^]
- provenance 是 "heavy lift"，需要更好的 polystore 支持；Vertica 不支持传递闭包（§4.7–4.8）[^2^]

> **对 pg_cordis 的含义**：P2 的限制清单几乎逐条指向 PG 的优势项——PG 有触发器、PL/pgSQL/Python/C 多语言存储过程、嵌套事务（savepoint）、行级安全/视图做保护域、成熟扩展机制。DBOS 团队被迫 work around 的 VoltDB 限制，恰是 PG 原生具备的。

## 7. CIDR 进展报告中的原型（VoltDB）实现细节

- **部署**：用户态原型，跑在 MIT Supercloud 与 Google Cloud；level 2 = VoltDB（OLTP）+ 后来加入 Vertica（OLAP，用于 provenance），构成 polystore（P2 §3, §4.7）[^2^]
- **Level 3 全为 SQL**：scheduler、file system、messaging 均 SQL 实现；另有 `ls`、`ls -r` 等 Linux 工具（§3）[^2^]
- **一切皆存储过程**："we have decided to implement all of level 3 in DBOS as stored procedures… Stored procedures naturally provide encapsulation and isolation."（§4.2）[^2^]
- **Serverless 环境（SE）**：子任务 = VoltDB 存储过程，DAG 存于数据库；启动时声明最大内存、结束后全部释放，以此回避复杂内存管理；"our SE can be faster than both Amazon Lambda and OpenWhisk on data-centric tasks as we can co-locate compute and data"（§4.3，主张，未给量化数据）[^2^]
- **硬件**：40 核双路 Xeon Gold 6248 2.5GHz、ConnectX-4 25Gbps NIC（§4.1）[^2^]
- **FIFO 调度器实测**：40 分区/2 服务器，1M tasks/s 亚毫秒尾延迟、2M tasks/s 亚毫秒中位延迟，吞吐随分区近线性（§4.1，实测）[^2^]
- **Provenance 实测**：捕获全部对象级读写并流入 Vertica，<50K TPS 时无性能影响（§4.7，引用 Poly'21 workshop 论文 [20]）[^2^]

---

## 参考文献

[^1^]: Skiadopoulos, A., Li, Q., Kraft, P., Kaffes, K., et al. "DBOS: A DBMS-oriented Operating System." PVLDB 15(1): 21-30, 2022. https://www.vldb.org/pvldb/vol15/p21-skiadopoulos.pdf （访问日期：2026-08-23）

[^2^]: Li, Q., Kraft, P., Kaffes, K., Skiadopoulos, A., et al. "A Progress Report on DBOS: A Database-oriented Operating System." CIDR 2022. https://people.eecs.berkeley.edu/~matei/papers/2022/cidr_dbos.pdf （访问日期：2026-08-23）
