# P04 计划评审 — 对照 planning 导出基线与已落地代码

Date: 2026-08-24
Scope: `docs/plans/P04-sleep-retry-2026-08-24.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-24-213630-p04-sleep-retry-deep-2f10.md`。导出含两份叠放草稿：编号第一稿（`## 1. Summary` 起，导出 122–1208 行）与后来的 P03 风格重写（第二个 `## Summary` 起，1210 行起）。**重写是保留基线**；第一稿除重写丢掉的独有可用细节外均已被取代。注意：第一稿在导出中本身是**中途截断**的（1208 行残留 "Reconnecting... 1/5"，止步于 Component 9 锁分析，Work items / Verification 从未写出），重写是唯一完整稿。

对承重引用做了代码定点核对：`sql/0001_p01_claim.sql`、`sql/0002_p02_log.sql`、`sql/0003_p03_wait_event.sql`、`sql/0006_p06_plugin_catalog.sql`、`tests/test_p00_sql_source.py`、`tests/test_p01_claim.py`、`tests/test_p03_wait_event.py`。

不重开：D1–D9、快照 §4，以及四条 mid-flow 用户决定（默认 `max_attempts=3`；`sleep_claim(uuid,text,timestamptz,integer)`；`release_stale` 与 `fail_claim` 共享 `jobs.attempt` 与退避/死信预算；死信 JSON 用 `reason` 键、原始 payload 嵌 `cause`）。

## 结论摘要

**维度 1（重写基线内容缺失/弱化）对重写本身无发现。** 现行计划与重写基线做了逐行 diff：全部差异恰为四条 mid-flow 决定的落实（decision 15 及全部六处 payload/断言处 `name`→`reason`，含 stale 死信嵌套 `cause.reason`）、标题/Status/checkpoint 注记、以及 deliverables 补列 `tests/test_p01_claim.py`。无任何实现承重内容被删或泛化。四条决定在 payload 示例、change/stay 矩阵、Verification 断言三处均一致落实，未发现漏改点。

承重代码引用抽查全部准确：`fail_claim(uuid,jsonb)` 两参且总是终态、不增 attempt、不写日志（`sql/0001_p01_claim.sql:252-282`）；`jobs_ready_idx` 现仅 PENDING（0001:56-58）；`release_stale` 现为整批 UPDATE、立即 PENDING、attempt+1、无日志（0001:89-113）；`emit_step_claimed` 六参默认 90、kind 白名单含 `run/sleep`/`run/wake`/`run/claim_timeout`、其 UPDATE 以 token+run_id+RUNNING+未过期为栅并取行锁（`sql/0002_p02_log.sql:72-145`）；`step_name` 仅 `llm`/`tool` 强制（0002:31-33）；`run_state` 在 0003 被重定义为含 `awaiting`，按最新 `run/await` 的 `await_id` 加 `seq >` 匹配 wake，且 `error` 优先于 `awaiting`（`sql/0003_p03_wait_event.sql:472-543`）——计划「retry 不得写 `error` kind」「timer wake 无 `await_id` 不会误关 await」两条论证成立；`emit_event` 事件行 `FOR UPDATE`（0003:362）、`await_event` 为 `FOR SHARE` + 私有 `P0301`（0003:141,169）；emit 扇出在**已持事件锁后**才快照 wait 集，timeout 赢者场景不会触发其 `NOT FOUND` 不变量异常（0003:394-426），计划的一胜者赛况分析与代码一致；`run_waits` 双 FK 与 `ON DELETE RESTRICT` 支持计划「缺 event/jobs 行即不变量错误」（0003:46-52）。

测试侧：`KERNEL_FUNCTIONS` 现为 19 项（`tests/test_p00_sql_source.py:23-43`），加三个新函数后与计划 Component 9 投影的 22 项列表及排序完全一致；文件清单断言格式（test_p00:56-60）与计划改法吻合；`test_p01_claim.py` 现断言 `error->>'reason'='boom'`（:317-320）与 stale 后 `attempt=2` 自动重领（:404-409），计划的 change 矩阵（死信包裹、零退避 fixture）正确对准；计划点名的既有测试名全部存在。**P03 的全部 22 个测试均走 `_apply_p03_only` 截断树**（`tests/test_p03_wait_event.py`），计划「P03-only 测试不受 0004 影响」的 stay 断言成立。

剩余发现全部为 **中/低**：两处第一稿独有、代码支持、被重写丢掉的细节（发现 1、2），一处两文均未覆盖的失败行为（发现 3），以及三条低价值钉子（发现 4–6）。无 P0/阻塞项。四条 mid-flow 决定折算完成后，计划 Status 可按 AGENTS.md 流程翻到 `ready to implement`。

---

## 发现

### 1.（中）`resolve_due_waits` 候选排序丢掉了第一稿的 deadline 优先 — 限额下会饿死排序靠后的到期 wait

第一稿 decision 14 的候选序是「deadline, event key, run ID」；重写（即现行计划 Component 4「Candidate selection」）改为只按 `event_scope_id, event_name, run_id`，deadline 不参与排序。两处后果：

- **饿死。** 候选谓词是 `deadline <= t0` 且 `LIMIT p_limit`（默认 100）。持续积压超过 100 条到期 wait 时，字典序靠后的 scope/name 永远排不进前 100，其 deadline 再早也不被解决；而新到期的字典序靠前 wait 不断插队。deadline 优先排序保证最老的先解决，扫荡有进度保证。
- **索引失配。** 计划自己新增的 `run_waits_deadline_idx` 是 `(deadline ASC, event_scope_id, event_name, run_id) WHERE deadline IS NOT NULL`——deadline 打头。按 event key 排序反而需要对全部到期行取出后再排序，索引只用于范围过滤。

**修正**：候选排序恢复为 `deadline ASC, event_scope_id, event_name, run_id`（与索引同形）。死锁安全性不受影响：deadline 在 wait 存续期内不可变（无更新路径），故任意两个并发 sweeper 看到的是同一全局确定序，事件行锁获取顺序仍一致；与 `emit_event`（只锁单一事件行）之间的相交仍靠事件行序列化，与计划既有论证兼容。对应改 W36 与 `test_p04_duplicate_timeout_resolution_is_noop`/资源饿死无需新测试，但计划文本三处（候选序、索引 rationale、并发分析）应同步。

### 2.（中）第一稿的「0004 不得含以 `{` 开头的 COMMENT」规则被重写丢掉 — 这是 P06 已落地的真实约束

第一稿 Component 1 文件规则里有一条「no comment beginning with `{`」，重写与现行计划均未保留（源边界断言清单里也没有）。这条不是风格项：`cordis.refresh_plugins` 扫描 **cordis schema 全部函数**的 `obj_description`，凡 `btrim` 后首字符为 `{` 的注释一律按插件定义解析（`sql/0006_p06_plugin_catalog.sql:493-504`）；解析失败的坏注释会让 `refresh_plugins` 整体报错并阻塞 `register_host_plugin`（`tests/test_p06_plugin_catalog.py::test_unrelated_bad_comment_blocks_register_and_preserves_rows`）。P04 恰好新增三个 cordis 函数；若实现或后人给它们加了 JSON 形注释，会在全树上被 P06 吞掉或炸掉。

**修正**：把该规则写回 0004 的文件规则（File-by-file impact 或 Component 1 对应节），并在 `test_p04_no_second_queue_or_direct_log_insert` 的源边界断言清单追加一条「0004 无 `COMMENT ON ... '{'` 形语句」。成本一行，收益是把 P06 的隐式全局约束显式化。

### 3.（中）两文均未命名：resolver/stale 的不变量异常会毒化全局 claim 路径

计划把 `resolve_due_waits` 与 `release_stale` 的不可能态定为 raise `object_not_in_prerequisite_state` 且整调用回滚（与 P03 的事务一致性偏好对齐，本评审不要求改设计）。但两文都没有写出运维后果：修订后**每次** `claim_job` 都先跑这两个 sweep，一条被越权 SQL 写坏的 wait/jobs 行（P07 之前 install role 可直写）会让**所有** worker 的所有 claim 调用永久抛错，直到人工修复该行——调度面可用性与 wait 表不变量从此耦合。P01 时代 claim 只依赖 jobs 自身约束，这是 P04 引入的新失败面。

**修正**：在 Risks and migration 增补一段命名此耦合（触发条件、影响范围、恢复手段是人工修正坏行或删除对应 `run_waits` 登记），并在 Open questions 的 residual 清单或 P07 交接处提一句权限收紧后此面收窄。不要求改成 skip-and-continue——那会把不变量破坏静默化，与 P03 先例相悖。

### 4.（低）timer wake 的 `wake_reason="sleep"` 同样覆盖 retry 退避唤醒 — 应显式钉住，防测试作者自造第三值

Component 7/8 的 timer wake payload 固定 `wake_reason="sleep"`。retry 进入的 SLEEPING 行到期被领取时，产生的也是这个 payload（区分要靠此前 `run/sleep` 的 `reason="retry"` 行）。两文都没有一句话说明「retry 唤醒不引入 `wake_reason="retry"`，就是 sleep」。建议在 Component 8 的 `run/wake` 三变体表加一行注记，并让 `test_p04_fail_requeues_same_row_with_default_backoff` 或后续领取断言里明确期望 `wake_reason="sleep"`，避免实现/测试各自发明第四种变体。

### 5.（低）「closed payload variants」是内核写入器约定，不是 schema 强制 — 一句话免除过强断言

Component 8 称 `run/sleep` 有「two closed payload variants」。实际上 `emit_step_claimed`/`checkpoint` 的 kind 白名单允许任何持活 claim 的调用方以任意 payload 追加 `run/sleep`/`run/wake`/`run/claim_timeout`/`error`（`sql/0002_p02_log.sql:102-109`），schema 不校验 payload 形状。这是 P02 既有事实、P07 权限工作的范围，P04 无需改；但计划应加一句「closed 指 P04 内核写入器只产出这些变体，不是日志表约束」，防止 W41 写出「全表只存在这些形状」的过强断言。

### 6.（低）两处欠钉的实现细节（不改设计，只补句子）

- **区间构造。** `retry_at = t0 + delay` 中 delay 为 double precision 秒；应钉为 `pg_catalog.make_interval(secs => delay)`（P01 先例，0001:162），避免实现者走 `delay * interval '1 second'` 之类未限定路径。顺带钉 `delay_seconds` 的 JSON 序列化：`to_jsonb(30::double precision)` 渲染为 `30`，Verification 里 `payload.delay_seconds = 30` 的断言按数值比较而非字符串。
- **无调用方时钟参数。** 第一稿明确写了 `resolve_due_waits` 不接受 caller-supplied "now"（防止提前解决未到期 wait）；重写只在签名上隐含。在 Component 4 的 rationale 补这半句，代价一行，防后续有人「为了可测性」加 `p_now` 参数。

---

## 需要用户/实现前拍板的问题

1. **发现 1 的排序修正是否采纳？** 采纳则 W36 的候选 SQL、索引 rationale、并发分析三处同步改；不采纳则计划必须写明接受 `p_limit` 下的字典序饿死及理由。这是唯一会改实现语义的项。
2. **发现 2 的 `{` 注释禁令是否进源边界测试？** 建议进；只改 W41 断言清单一行。
3. **发现 3 的全局毒化风险按「文档命名、不改行为」处理是否可接受？** 建议接受（与 P03 all-or-nothing 先例一致），残余交 P07。

以上无一触及 D1–D9、快照 §4 或四条 mid-flow 决定。发现 1–3 折进计划、4–6 顺手补句后，本 critique 无阻塞项遗留。
