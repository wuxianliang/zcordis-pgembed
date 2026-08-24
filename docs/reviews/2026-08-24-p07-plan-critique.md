# P07 计划评审 — 对照 Oracle review 与已落地代码

Date: 2026-08-24  
Scope: `docs/plans/P07-grant-registry-2026-08-24.md`（现行计划）对照 Oracle review 导出 `prompt-exports/oracle-review-2026-08-24-214119-untitled-chat-8ac134-2c49.md`。承重引用已对照 `sql/0002_p02_log.sql`、`sql/0003_p03_wait_event.sql`、`sql/0006_p06_plugin_catalog.sql`、`tools/apply_pg_cordis.py`、`tests/test_p00_sql_source.py`、`sql/README.md`、D5、骨架 P07。

已定事项不重开：D1–D9、快照 §4。尤其 D5 C + 模型只能申请 + slice 绑定；禁止 SQL 谓词与 `run_id` 顶替隔离；结构化描述符 A 本轮不做。`sql/` 禁止 GRANT/ROLE。P06 `required_grants` 只存种类。四缝强制是 P08。不包装 P03 emit/await。

## 结论摘要

第一轮 Oracle 裁决：**Not ready**。无 P0。六条 P1（动词被写成认证、run_id 与 P02 不一致且 grants 重复列、并发不可线性化、corpus 冻结未真正拍板、denied/revoked 行变成第二套历史、event scope 另造语法）和三条 P2（校验组混用、测试未钉住组合证明、KERNEL_FUNCTIONS 误称 C collation）。

本笔记记录该裁决。P1/P2 已折进现行计划后再送同一条 Oracle 聊天确认。

## Round 2（同一聊天 `untitled-chat-8AC134`）

导出：`prompt-exports/oracle-review-2026-08-24-215516-untitled-chat-8ac134-87ec.md`  
裁决：仍 **not ready**。Round-1 P1.1/1.2/1.4/1.5/1.6 **closed**。P1.3 锁序表与 issue-vs-deny 期望仍自相矛盾（open）。新 P1：`requested_by_kind` 在重复 pending request 上未拍死。P2：W71 与 corpus 幂等、`22023` 参数化测试、P06 CHECK 行号。

Round-2 处理已折进计划：grant locator 无锁 → slice `FOR UPDATE` → grant `FOR UPDATE`；并发结果按线性化顺序（deny-then-issue ⇒ issued；issue-then-deny ⇒ deny `22023`）；`requested_by_kind` = 当前 pending cycle 的开启者；W71 改写；`test_p07_api_errors_are_22023`；引用 `plugin_catalog_required_grants_check`。

## Round 3（同一聊天）

导出：`prompt-exports/oracle-review-2026-08-24-220147-untitled-chat-8ac134-87ec.md`  
裁决：**Ready to implement**。无 P0/P1。两条 P2（NULL target 测试措辞过宽；version 函数 snippet 未 pin `search_path`）已折进计划：run 的 NULL target 正规化为 `''`；version 函数与 `0001`–`0006` 一样是字面量 SQL、不设 `search_path`。

计划 Status 现为 **ready to implement**。

## Oracle 裁决（忠实）

- 日期：2026-08-24
- 导出：`prompt-exports/oracle-review-2026-08-24-214119-untitled-chat-8ac134-2c49.md`
- 聊天：`untitled-chat-8AC134`
- 计划：`docs/plans/P07-grant-registry-2026-08-24.md`
- 裁决：第一轮 **not ready**（无 P0，六条 P1，三条 P2）

### P0

无。

### P1

1. Decision 1 把 `p_issuer_kind` 写成了比「声称来源」更强的权威；测试名像在证明调用者身份。
2. `run_id` 被 trim/限长，与 `agent_steps` 不一致；`grants.run_id` 无库级与 slice 对齐。
3. 并发 request/issue/deny/revoke 在部分唯一索引下不可线性化。
4. 「不静默扩权」被写成 corpus 内容冻结，但 P07 没有快照钩子，实际是 live root。
5. denied/revoked 行当 audit 保留，形成 log 之外的第二套历史。
6. event target 另造 charset/长度，破坏 P03 opaque `event_scope_id`（P03 只要求 `btrim <> ''`）。

### P2

1. 「每个 writer 同一套校验」与 approve/deny/revoke/create 签名不符。
2. 两 slice + pending 的骨架证明被拆到两个测试，没有一个命名测试跑完整序列。
3. `KERNEL_FUNCTIONS` 声称 `ORDER BY 1` 保证 C collation。

## 折进计划的处理

| Oracle | 计划改动 |
|---|---|
| P1.1 | Decision 1：`p_issuer_kind` = 声称来源，不是认证。issue 族是 trusted control-plane。测试改名为 `test_p07_issue_rejects_asserted_model_kind`。P07 不是对用户/模型暴露的产品面；P08/P10 不得把 issue 族派给模型。 |
| P1.2 | `run_id` 与 P02 相同：非空、不 trim、不加 P07 专有长度。删除 `grants.run_id`；`p_run_id` 只与 `slices.run_id` 精确相等做所有权围栏。 |
| P1.3 | 写路径锁序 **slice `FOR UPDATE` → grant 行 `FOR UPDATE`**。每 tuple 一行（全状态 UNIQUE）。两个 `psql_session` 覆盖 request/issue、issue/revoke、issue/deny。 |
| P1.4 | 明确拍 **live-root identity**：`named_corpus:<id>` 命名登记根，成员可变。P07 不冻结文件内容。「不静默扩权」只约束 grant **集合**（不自动批准、目标不可变、无 run 并集检索）。测试 `test_p07_corpus_is_live_root_identity`。 |
| P1.5 | `grants` 是当前态：`(slice_id, kind, target)` 一行到底，复用 `grant_id`。denied/revoked 不是 audit 历史；不写 `agent_steps`。 |
| P1.6 | event `target` 复制 P03：`btrim(target) <> ''`，原样存储。测试用 P03 能接受的带 `/` 和 `:` 的 scope 往返。 |
| P2.1 | 校验拆成 issuer / requester / run-slice / kind-target / grant-state 五组，每个函数点名用哪一组。 |
| P2.2 | `test_p07_two_named_corpus_on_two_slices` 必须跑完整 D5 序列（两签发 + 跨 slice 的 model request 仍 pending）。 |
| P2.3 | 删除 C collation 声称；`KERNEL_FUNCTIONS` 对齐现有 `test_p00` 的 `ORDER BY 1` 查询，不改 collation。 |
