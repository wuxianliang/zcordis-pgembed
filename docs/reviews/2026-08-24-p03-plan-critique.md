# P03 计划评审 — 对照 context_builder 导出基线与已落地代码

Date: 2026-08-24
Scope: `docs/plans/P03-wait-event-2026-08-24.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-24-173519-p03-wait-event-deep-7dc1.md` 的生成计划正文（`# P03 — run_waits / run_events and atomic wait/wake` 起；其前的 composed prompt 与 selection 清单只作上下文），并对承重引用做了代码定点核对（`sql/0001_p01_claim.sql`、`sql/0002_p02_log.sql`、`tests/test_p00_sql_source.py`、`tests/test_p02_agent_steps.py`、`tests/conftest.py`、`docs/decisions/2026-08-23-pending.md` D3、`docs/plans/2026-08-23-pg-cordis-development.md` P03、`docs/plans/P02-agent-steps-log-2026-08-23.md` W 编号）。

已定事项不重开：D1–D9、快照 §4，以及计划的 12 条 resolved decisions（含 mid-flow 补充的 decision 12：挂起 wait 不写 `jobs.available_at`）。用户已声明的五处刻意修正（decision 12、file:line 证据表、KERNEL_FUNCTIONS 精确列表、`pg_catalog` 限定、W27–W33 编号）不作为缺失处理，且本次核对确认五处均已在计划全文一致落实。

## 结论摘要

**维度 1（导出内容缺失/弱化）无发现。** 现行计划是导出生成计划的严格超集：逐节比对后，全部差异恰为五处已声明修正加纯增量内容（References 节、Open questions 残余风险清单、decision 12 及其 mid-flow 注记、W 编号说明句）。导出中唯一被改写的实现语义是挂起分支 `available_at = COALESCE(deadline, infinity)` → 「不赋值」，且计划在 decision 12、Component 4 第 5 步、Verification「available_at unchanged from the pre-wait RUNNING row」三处保持一致；`claim_job` 落地代码确实不改 `available_at`（`sql/0001_p01_claim.sql:158-168`），该断言可测。

承重代码引用绝大多数核实准确：`agent_steps_pkey (run_id, seq)` 存在，`run_waits_await_step_fkey` 合法；`emit_step` 返回 `bigint` seq，「capture await_seq」成立；`agent_steps` 无 jobs FK 且 `run_id` 仅要求非空白，`@event/<uuid>` 流可写；`step_name` 仅 `llm`/`tool` 强制，P03 三种 kind 传 NULL 合法；现行 `run_state` 的 `steps_used` 只数 `kind='llm'`（`sql/0002_p02_log.sql:393`），新增 await/wake 行不会污染它；`KERNEL_FUNCTIONS` 走 Postgres `ORDER BY 1`（C collation，`_validate` 排首），计划给出的 19 项结果列表排序正确；P02 测试的 change/stay 矩阵与 `tests/test_p02_agent_steps.py:122-132`、`:586-596`、`:866-875` 现状逐条吻合。

剩余发现全部为 **中/低**：一处死锁论证缺口（发现 1）、若干欠规格接缝（发现 2、6、7）、两处代码可证伪的论证措辞（发现 3、10）、两处两文均未覆盖的生命周期问题（发现 4、5）、两处行号引用错误与两处文内一致性 nit（发现 8、9）。无 P0/阻塞项。

---

## 发现

### 1.（中）死锁论证漏掉「同事务先 claim-fenced 写 log、再 emit_event」的组合调用 — 结论仍成立，但理由要换

Component 7「Why there is no deadlock」断言：「Emit and await never hold jobs while waiting for an event row. P02 checkpoint may hold a jobs row and append the same run's log, but it never requests an event row, so it cannot form the reverse edge.」

这句只覆盖了单独调用 P02 写入器的事务。真实 worker（P05/P17 形态）完全可能在**同一事务**里先 `emit_step_claimed`/`checkpoint`（其 UPDATE 已取走自己 RUNNING jobs 行的行锁，`sql/0002_p02_log.sql:128-136`）、再调 `cordis.emit_event(...)` 对外发事件——该事务此刻**正是**「持有 jobs 行、等待 event 行」，反向边存在。

不成环的真正理由计划没有写出来：emit 的 fan-out 只锁**匹配活跃 wait 的 WAITING 行**，而任何被 claim-fenced 写入器持锁的行必为 RUNNING（`jobs_claim_fields_check` 强制 WAITING 行 token 全空，`sql/0001_p01_claim.sql:27-40`），且 RUNNING 行不可能有 `run_waits` 登记（await 挂起与清 token 同事务原子）。所以「emit 想要的 jobs 行」与「claim 持有者锁着的 jobs 行」集合不相交，环不可能闭合。

修正：把 Component 7 的论证替换/补强为上述「fan-out 目标集与 claim 持锁集不相交」论证，或者显式禁止在持有 claim-fenced jobs 行锁的事务内调用 `emit_event`（不推荐，会给 P05/P17 埋雷）。二选一，写进计划正文；这也决定问题 2（见文末）的答案。

### 2.（中）重复 await 检查未绑定到两个分支，检查谓词与复用范围欠规格

三个相互关联的欠规格点：

- **分支绑定。** 「Duplicate-wait checks」节写在分支拆分之前（「After obtaining a valid jobs lock」），但 Suspended/Immediate 两个编号序列都只说「Validate and lock as above」，未列出重复检查。而 Verification 的 `test_p03_emit_before_wait_resolves_without_yield` 断言「exactly one await and one wake for that await ID」——这要求 **immediate 分支同样执行 await_id 复用 raise**，否则重复调用会追加第二对 await/wake。应在两个序列里显式各加一步「duplicate checks（existing run_waits row；await_id reuse in this run's log）在任何 log append 之前执行」。
- **谓词形状。** 「an earlier `run/await` in the same run log with the same `await_id`」的实现谓词未钉。建议写明：`EXISTS (SELECT 1 FROM cordis.agent_steps WHERE run_id = p_run_id AND kind = 'run/await' AND payload->>'await_id' = p_await_id::text)`，走 `agent_steps_pkey` 的 run_id 前缀，O(单 run 日志)。不钉的话实现者可能扫 `run/wake` 或全表。
- **复用范围。** 复用检测是 per-run 的；`run_waits_await_id_key` 只在 wait 活跃期内全局唯一。于是**另一个 run** 在无活跃 wait 时复用同一 `await_id` 会被放行。这对 `run_state` fold 无害（匹配只在单 run 日志内做），但计划应写一句「跨 run 复用不检测、不承诺唯一」，否则测试作者可能写出错误的全局唯一断言。

### 3.（中）「无法建 FK」的理由被代码证伪 — 决定可保留，论证必须改

Component 2 对 `run_events` 写：「No foreign key points from `run_events` to `agent_steps`, because the source log stream is stored as text and the sentinel state has no sequence yet.」两个理由都不成立：

- `agent_steps` 有 `agent_steps_pkey PRIMARY KEY (run_id, seq)`（`sql/0002_p02_log.sql:12`），`FOREIGN KEY (event_log_run_id, emit_seq) REFERENCES cordis.agent_steps (run_id, seq)` 是合法组合 FK；
- 默认 `MATCH SIMPLE` 语义下，`emit_seq IS NULL` 的哨兵行**不参与检查**，哨兵态天然通过。

FK 事实上可行：emit 在同事务内先 append 后 update，引用行必已存在；`agent_steps` 只追加、不删不改，不会触发级联问题。不建 FK 依然是合理选择（FK 表达不了 kind/scope/name 语义检查；且给未来日志保留策略留自由度），但计划必须把理由换成这两条真话，避免 Oracle 实现审查时按错误前提争论。

### 4.（低）`run_waits_job_fkey ... ON DELETE CASCADE` 未论证 — 静默吞 wait 的唯一路径

导出与计划都未解释 CASCADE 的选择。P03 没有任何删除 jobs 行的动词，但一旦未来运维/保留迁移删除一个 WAITING 的 jobs 行，CASCADE 会**无 `run/wake` 记录**地静默删掉活跃登记，日志永久停在 `awaiting`——这恰是计划在 emit fan-out 里宁可 raise 也不肯静默跳过所要避免的状态。建议改 `RESTRICT`（删除等待中的 job 大声失败），或在 DDL 注记里写明选 CASCADE 的理由。这是现在就落进 DDL 的 ABI 级选择，不应无声通过。

### 5.（低）P04 之前 WAITING run 无任何终止/取消路径 — 后果应写进 Risks

`complete_claim` / `fail_claim` / `yield_claim` 全部要求 live RUNNING + token（`sql/0001_p01_claim.sql:198-282`），`release_stale` 只碰 RUNNING。计划已写「deadline 是描述性的」「时间流逝不改变 WAITING」，但没有点破操作后果：**P04 落地前，一个事件永不到来的 WAITING run 对全部产品动词不可达**，唯一恢复手段是对准确 `(event_scope_id, event_name)` 补一次 `emit_event`（或手工 SQL）。这是刻意的阶段排序，不用改设计；但 Risks 节应加一句，免得运维/测试期望 `fail_claim` 能救回卡住的 waiter。

### 6.（低）await 分支的 jobs 行锁模式未指明

emit fan-out 明确「Lock its `cordis.jobs` row `FOR UPDATE`」，await 的全局锁序第 3 步只写「Lock the exact jobs row by run_id + claim_token + status='RUNNING'」。应钉死实现形态：`SELECT ... FOR UPDATE` 或像 `emit_step_claimed` 那样直接以 fence UPDATE 取锁；并顺带写明 lost-claim 语义——WHERE 匹配零行时**不取任何锁**、直接走 accepted=false，这是「no lasting mutation」证明的一部分。另注：并发测试里 B 会话可能阻塞在哨兵 `INSERT ... ON CONFLICT` 的 speculative-insertion 等待上而非显式行锁上，「blocks then correct branch」的断言不受影响，但值得在 Concurrency test shape 里注一句，免实现者误判。

### 7.（低）`run/await` payload 的 `deadline` 序列化格式未钉

Component 3 只写 `"<timestamptz JSON string or null>"`。`to_jsonb(timestamptz)`（ISO-8601 带偏移）与 `::text` 拼接产物格式不同；P04 要读它，测试要断言它。钉为 `pg_catalog.to_jsonb(p_deadline)`（SQL NULL → JSON null）。

### 8.（低）两处行号引用错误 — 内容正确，行号需修

Background 证据表核对结果：

- 「Five-proof row 5 shared with P04 — `docs/plans/2026-08-23-pg-cordis-development.md:67-68`」→ 该行实际在 **:62**；:67-68 是「一览」表头。
- 「complete/fail/release_stale do not emit log — `sql/0001_p01_claim.sql:226-272`」→ 该区间只覆盖 complete/fail；`release_stale` 在 **:64-115**，应并列引用。

其余抽查项均准确（骨架 :130-138；pending.md :51、:165-168、:179、:204-207；0001 :23-40、:56-58、:150-158、:172-196；0002 :14-27、:64-66、:72-145、:366-413；test_p00 :23-41、:54-58、:95-105；test_p02 :122-132、:586-596、:866-875）。

### 9.（低）两处文内一致性 nit

- 第 48 行「Work-item IDs continue the P02 series (`W19`–`W26`).」事实正确（已核对 P02 计划确用 W19–W26），但括号紧跟「continue」易被读成 P03 使用 W19–W26，与两行后的 W27–W33 表相抵。改写为「P02 used W19–W26; P03 continues with W27–W33」即可。
- File-by-file impact 写「All 11 design questions are resolved」，而决定表已有 12 行。应注明 decision 12 是 11 条脚手架问题之外的 mid-flow 补充。

### 10.（低）fan-out `run_id` 排序的死锁理由空洞 — 价值在确定性，不在防倒序

Decision 2 / Component 7 称 run_id 升序「preventing emit/emit row-order inversion」。实际上：同键的两次 emit 在 event 行 `FOR UPDATE` 上完全串行；异键 emit 的 waiter 集因 `run_waits_pkey (run_id)`（一 run 至多一 wait、指向恰一键）而**不相交**，jobs 锁序倒置无从发生。排序的真实价值是确定性唤醒顺序与可断言的测试。保留排序，修正归因即可——与发现 1 同属「结论对、论证换」。

---

## 问题（答案会实质影响设计或实现顺序）

1. **`p_deadline` 是否做输入卫生？** 现计划任意值直存 `run_waits.deadline`（过去时刻、`±infinity` 均放行）。P03 不 tick 它，但 P04 要消费；现在不拒绝，P04 就要定义这些角例。拒绝（raise `invalid_parameter_value` for past/non-finite）会改动 Component 4 验证清单与 `test_p03_lost_claim_and_parameter_errors`。
2. **是否允许在持有 claim-fenced jobs 行锁的事务内调用 `emit_event`？**（发现 1）允许 → 采用不相交论证；禁止 → 写进合同并告知 P05/P17。默认应允许。
3. **跨 run 的 `await_id` 复用是否接受？**（发现 2）接受 → 在计划里写明「唯一性仅限活跃期 + 单 run 日志」；不接受 → 需要全局检查方案（当前没有便宜实现），会改 DDL/验证。
4. **`run_state('@event/<uuid>')` 返回 `in-progress` 是否需要文档说明？** 事件流只有 `event/emit` 行，fold 视其为普通 run。无行为问题，但 README/计划一句话可防误用。

---

## 核对方法附记

- 导出→计划 diff：逐节比对生成计划正文（导出 :131-1924）与计划全文；差异清单：Background file:line 表（增）、decision 12 行与 mid-flow 注记（增）、Component 4 第 5 步 `available_at`（改，已声明）、Component 1 `pg_catalog` 限定句（增）、DDL 默认值/CHECK 的 `pg_catalog.` 前缀（改，已声明）、KERNEL_FUNCTIONS 精确列表（强化，已声明）、W 编号句与 W27–W33（已声明）、Verification 挂起断言 `available_at`（随 decision 12 改）、Open questions 残余清单与 References 节（增）。无删除、无弱化。
- 排序核验：`test_fresh_apply_lists_current_tree_and_p06` 以 `ORDER BY 1` 取回并与 `KERNEL_FUNCTIONS` 比对（`tests/test_p00_sql_source.py:114-121`）；现库排序把 `_validate_plugin_definition` 排在 `checkpoint` 之前，证明 C collation 语义，计划列表中 `await_event` 居第二、`emit_event` 先于 `emit_step` 均正确。
