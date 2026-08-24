# P19 计划评审 — 对照 Oracle review 与现行代码

Date: 2026-08-24  
Scope: `docs/plans/P19-paradigm-policies-2026-08-24.md`（当时 Status: draft）  
Oracle: `prompt-exports/oracle-review-2026-08-24-214138-untitled-chat-136564-8da5.md`（chat `untitled-chat-136564`，`mode: review`）  
核对：`sql/0006_p06_plugin_catalog.sql` invocation CHECK、`tests/test_p00_sql_source.py` `KERNEL_FUNCTIONS` 与 `'p06'`、`sql/README.md` 产品树段落、骨架 P19、D8/D9、快照 §5。

已定事项不重开：D1–D9、快照 §4、不 `CREATE EXTENSION`、不把政策塞进 `plugin_catalog` 当工具行（Oracle 同意这是与 D8/P06 的正确切分）。

## 结论摘要

**第一轮裁决：Not pass。无 P0；五条 P1；三条 P2。**

Oracle 同意：独立表 `cordis.paradigm_policies` 不违反 D8；省略 `rlm_vars` / `jobs.paradigm` / 真 fold 实现是正确的 P19 范围；种子 identity 与 RLM `always_enqueue` 对齐 D9。

P1 全部折进计划后再送同一条 Oracle 聊天。未改架构、未重开合同。

## Oracle 原裁决（忠实）

- **P0：** 无。
- **P1.1** 函数名无共同签名，P05 仍可能按 identity/parser 分叉；lookup 测试只证明选行。
- **P1.2** 精确 A∨B bundle CHECK 把两种行为冻进 schema，第三行只是别名。
- **P1.3** CodeAct `spawn_mode='none'` 把「一步内普通工具不是 spawn」误写成「CodeAct 不能显式生子」。
- **P1.4** apply 对种子 UPSERT 会盖掉运行时/后续文件的 prompt；与「P05/P13 可 upsert」及编号顺序冲突。
- **P1.5** `metadata` 三套说法互斥，W191 无法确定实现。
- **P2.1** `'CodeAct'` 应报 `invalid identity` 而非 `unknown paradigm`。
- **P2.2** 源码正则测 `CASE identity` 脆，且不能证明可分派。
- **P2.3** `sql/README.md` 现行 `p06` 行大约在 `:46`，不是 `:39-44`。

## 折进计划的处理

| ID | 处理 |
|---|---|
| P1.1 | 锁定三槽共同签名；P19 提供六枚 stub（`p19_stub` JSON），函数名可 `EXECUTE`；P05 只换函数体。枚举不再当分派开关。 |
| P1.2 | 删除精确 A∨B CHECK。改为 env 自洽 + 禁止 sync spawn；`action_surface` / `parser_kind` / clip 独立。 |
| P1.3 | `spawn_mode` 只表示**显式**子 run 准入，闭集仅 `always_enqueue`（D9）。两份种子都是该值。普通工具仍不是 spawn。 |
| P1.4 | 种子改为 `INSERT … SELECT validate ON CONFLICT DO NOTHING`。运行时 `register` 仍 upsert。Replay 只补回被删的种子，不覆盖已改 prompt。种子修订必须编号 > `0019`。 |
| P1.5 | `metadata` = 完整原始 `p_definition`（对齐 P06）。 |
| P2.1 | W195：`'CodeAct'` → `invalid identity`。 |
| P2.2 | 删除仓库级 CASE 正则；改用第三政策 + 按行内函数名调用 stub。 |
| P2.3 | README 引用改为 `:39-46`。 |

未采纳：把政策塞回 `plugin_catalog`；为过审重开 D9 同步子树；在 P19 建 `rlm_vars`。

## Round 2（同一聊天 `untitled-chat-136564`）

Oracle: `prompt-exports/oracle-review-2026-08-24-215433-untitled-chat-136564-db6e.md`
裁决：**Not pass。** Round-one P1.2–P1.5 **Closed**；P1.1 部分关闭并拆成五条新 P1。

| Round 2 P1 | 折进计划 |
|---|---|
| `0019` CREATE OR REPLACE 会盖掉 `0005` 真实现 | P19 拥有六槽名字；真 body 必须编号 **> 0019**。W195：`0020` sentinel 经全量 replay 仍在。 |
| `to_regprocedure(fold_fn)` 无参列表；未校验签名 | 注册/校验解析 `name||'(text)'` / `'(jsonb)'` 且 `prorettype=jsonb`；缺函数 `22023`。 |
| fold 标成 IMMUTABLE | fold stub **STABLE**；parse/observe **IMMUTABLE**。 |
| 校验器未复制表级 CHECK，会变成 `23514` | 校验器复制全部 enum/env/spawn/fn 规则，失败 `22023`。 |
| clip 列与 observe ABI 脱节 | 核函数 `apply_observation_policy(obs, clip, full_in_env)`；驱动通用截断，不按 identity 分支。 |

## Round 3（同一聊天）

Oracle: `prompt-exports/oracle-review-2026-08-24-220807-untitled-chat-136564-cd14.md`
裁决：**Not pass。** Round-two 1/4/5 Closed；剩余一条 P1（任意注册行的槽 ABI 不完整）。

折进计划：校验器在 `to_regprocedure` 之后要求 `prokind='f'`、`proretset=false`、`prorettype=jsonb`、fold `provolatile='s'`、parse/observe `'i'`。W195 增加 SETOF / VOLATILE / RETURNS text 三例。P2：`COALESCE(shown,'')`；clip 测试不依赖 `probe.alias`；`0020` sentinel 钉 `search_path`。

## Round 4（同一聊天）

Oracle: `prompt-exports/oracle-review-2026-08-24-221506-untitled-chat-136564-cb70.md`
裁决：**Not pass。** Round-three P1 Closed；新 P1：`apply_observation_policy` 被写成 `LANGUAGE sql` 却要 `RAISE`。

折进计划：wrapper 改为 `LANGUAGE plpgsql IMMUTABLE`，显式 `RAISE EXCEPTION 'invalid observation' USING ERRCODE='22023'`。P2：`[]::jsonb` 拒绝；parse/observe 各补一例错误签名。

## Round 5（同一聊天）

Oracle: `prompt-exports/oracle-review-2026-08-24-221702-untitled-chat-136564-335f.md`
裁决：**Pass。** 无剩余 P0/P1。计划 Status 改为 `ready to implement`。

计划 critique 不能代替实现 Oracle 通过。实现完成仍走 `Agents.md` 闸门。



