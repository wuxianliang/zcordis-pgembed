# P08 计划评审 — 对照 planning 导出基线与已落地代码

Date: 2026-08-24
Scope: `docs/plans/P08-four-seam-enforcement-2026-08-24.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-25-013020-p08-four-seam-plan-3-a90b.md`。导出前缀（1–124 行）是拼装 prompt 与选中文件转储，不算计划内容。正文叠放三份草稿：**版本 1（导出 131–944 行）是保留基线**，本身在 File-by-file impact 表格中途截断（944 行残留 "Reconnecting... 1/5"，Implementation order / Verification / Risks / Open questions 从未写出）；版本 2（944–2273 行）的 `step_once` 重写与版本 3（2275 行起）的「无写入器 / env 返回 NULL」简化已按用户 mid-flow 决定作为 rejected alternatives 记录。现行计划的 Verification / 实现顺序 / 两 slice 协议来自版本 2 的改编——本评审唯一的 P0 恰好出在这次改编上。

对承重引用做了代码定点核对：`sql/0002_p02_log.sql`（`emit_step`/`emit_step_claimed` 签名、追加垄断）、`sql/0006_p06_plugin_catalog.sql`（catalog 列、`required_grants` 约束、effect/retry/reconciliation 组合）、`sql/0007_p07_grant_registry.sql`（`slice_live_grants`/`slice_has_grant` 签名、`run` 空 target、corpus 语法、六个 issuer 签名）、`sql/0019_p19_paradigm_policies.sql`（fold stub 形状、`paradigm_policy` env 列、版本函数形状）、`tests/test_p00_sql_source.py`（`KERNEL_FUNCTIONS` 41 项、表计数 pin、`test_fresh_apply_lists_current_tree_and_p19` 命名）、`tests/test_p01_claim.py`、`tests/test_p02_agent_steps.py`、`tests/test_p05_one_step_driver.py`、`tests/test_p06_plugin_catalog.py`、`tests/test_p07_grant_registry.py`、`tests/test_p19_paradigm_policies.py`、`tests/conftest.py:60`（`next_sql_prefix` 为动态函数）。

不重开：D1–D9、快照 §4、no `CREATE EXTENSION`、`sql/` 无 GRANT/ROLE、无 run-union 读取器、不包装 P03 emit/await、schema `cordis`、编号 SQL 只追加；以及三条 mid-flow 用户决定（`step_once` 不包装；`0020` 内替换两个 P19 fold body；获准 env 读报 `55000 P08_ENV_WORKSPACE_UNAVAILABLE`）。

## 结论摘要

**维度 1（基线内容缺失/弱化）：基线核心全部保留。** 四门 API 签名、latch 双表、`p08_scope` 信封与 fold 资格五条件、`emit_step_scoped` 九步算法、`_fold_scoped_history` 适配器语义、逐门错误表、控制面 blocklist、descriptor 字段、`KERNEL_FUNCTIONS` 49 项精确列表（现行 41 项 + 8 个新身份，与 `tests/test_p00_sql_source.py:23-65` 核对一致）逐项对齐。仅两处基线细则被压缩掉（发现 4、5，均 P2）。

**维度 3（代码证伪的内容）：基线的 `$p20$` dollar tag 被仓库证伪，计划的 `$p08$` 偏离正确，应保留。** 实测 tag 普查：`$p04$`×16、`$p05$`×4、`$p06$`×9、`$p07$`×19、`$p19$`×23（`0002` 用 `$fn$`）——全部按计划号，无一按文件前缀。基线「All P08 PL/pgSQL bodies use `$p20$`」不符合仓库既有约定；现行计划 decision 2 的改法与 rejected-alternative 说明成立，不要求回改。基线的 critique 路径日期（2026-08-25）也已被计划改正为 2026-08-24。

**承重引用抽查全部准确**：`emit_step_claimed(uuid,text,text,jsonb,text DEFAULT NULL,integer DEFAULT 90)`（`sql/0002_p02_log.sql:72-79`），`emit_step_scoped` 的委托参数与 `p_extend_seconds` 默认 90 对得上；追加垄断成立（唯一 `INSERT INTO cordis.agent_steps` 在 `emit_step`，0002:64，`emit_step_claimed` 经 `PERFORM cordis.emit_step` 委托）；`slice_live_grants` 返回 `(grant_id, kind, target, d5_literal)`（0007:664-673），recall 的 `grant_id` 列有来源；`run` grant 空 target 由 `grants_target_by_kind_check` 强制（0007:68-69）；corpus 语法 `^[a-z][a-z0-9_-]{0,127}$`（0007:72）；blocklist 六个 issuer 签名逐一正确（0007:111,166,336,471,536,601）；P19 fold stub 形状 `{p19_stub,slot,run_id}` 与 `LANGUAGE sql STABLE` 正确（0019:530-552）；`paradigm_policy` 返回表含 `env_enabled`/`env_workspace`/`action_surface`/`parser_kind`（0019:477-489）；descriptor 点名的全部列（version/locus/invocation/effect/retry/reconciliation/entrypoint/session_scope/capability/config）在 `plugin_catalog` 存在（0006:5-24）；计划点名的三个 P19 测试名全部存在（test_p19:539,641,689）；版本函数为 `LANGUAGE sql IMMUTABLE` 无 `search_path`（0019:717-724），与计划「historical no-search_path shape」一致。

**发现一个 P0**：强制两 slice 协议自相矛盾（`run` grant 只发 `s1`，却要求 `s2` 走 `emit_step_scoped` 写日志并镜像 fold 断言，两者按计划自身算法都要求 live `run` grant）。另有一个 P1（控制面 blocklist 漏掉日志写入器，`p08_scope` 伪造可从 tool 门本身走通）与四个 P2。P0/P1 折进计划前，Status 不得翻 `ready to implement`。

---

## 发现

### 1.（P0）强制两 slice 协议不可实现：`run` grant 只发 `s1`，但 `s2` 被要求写 scoped 日志并镜像 fold

`test_p08_two_named_corpora_four_seam_leak_fixture` 的步骤 3 写明「`run`/`''` 发给 **`s1` only**」，随后：

- 步骤 4 要求 `s2` 经 `emit_step_scoped` 写入 `project-2-secret`——但 Component 3 算法第 5 步「Require live `run` grant」无条件适用，`s2` 的写入会报 `42501`（append-specific fragment），sentinel 根本进不了日志；
- 断言段「Mirror recall/fold/tool for `s2`」——fold 镜像按 decision 6 / 错误表要求 live `run` grant，`fold_slice_messages(run, s2, …)` 只会得到 `42501 P08_FOLD_RUN_GRANT_REQUIRED`，不是「含 `project-2-secret`、不含 `project-1-secret`」。

矛盾来源可考：版本 2 的原始协议（导出 2044-2081 行）**没有发 `run` grant 这一步**，因为版本 2 的 fold/emit 设计不要求 run grant（走 `activate_slice_context`）；orchestrator 把版本 1 的「fold 与 scoped append 需 live `run` grant」和版本 2 的 fixture 拼在一起时未做调和。协议是该 P 的验收核心（骨架「Done when: leak tests red/green」），照文实现必然红，定 P0。

**修正**（不扩 scope，三处局部改动）：

1. 步骤 3 改为 `run`/`''` 同时发给 `s1` 和 `s2`；泄漏证明的对象本来就是 corpus 隔离，不是 run grant 的有无。
2. fixture 中 `read_run_env(run, s2, 'rlm', 'question')` 报 `P08_ENV_RUN_GRANT_REQUIRED` 的断言随之失效，改为 `s2` 也得到 `55000 P08_ENV_WORKSPACE_UNAVAILABLE`；缺 `run` grant 的 env/fold 失败已由 `test_p08_env_read_failure_contract` 与 `test_p08_fold_failure_contract` 覆盖，在那两处用一个不发 `run` 的第三 slice（或复用现有构造）承载即可。
3. 「Also assert …」段与 `test_p08_legacy_step_once_still_unfiltered`（依赖同一份两 slice scoped 历史）按同一设定顺改。

### 2.（P1）控制面 blocklist 漏掉日志写入器：`p08_scope` 伪造可从 tool 门本身走通

`authorize_tool_dispatch` 第 5 步在 grant 检查前拒绝六个 issuer 入口（`register_named_corpus`/`create_slice`/`issue_grant`/`approve_grant`/`deny_grant`/`revoke_grant`），理由是 issue-family 不得成为 model tool。但同一标准下，**任何能把调用方自选 payload 原样写进 `agent_steps` 的函数**也不能成为 in-db tool entrypoint：一条 catalog 行若把 `entrypoint` 指向 `cordis.emit_step(text,text,jsonb,text)` 或 `cordis.emit_step_claimed(…)`，则模型通过完全「获准」的 tool 路径就能伪造任意 `p08_scope`（含别的 slice 的 UUID 与 corpus 列表），fold 隔离整个被击穿——这正是 P08 唯一的 DB 侧 chokepoint 本应挡住的类别。

计划 decision 12 与 Risks 把 raw `emit_step` 伪造归为 same-user 控制面漏洞、靠「P09/P10 不暴露」的约定兜底；但计划既然已经为 issue-family 选择了 DB 侧 deny（`P08_CONTROL_PLANE_TOOL_DENIED`），对同级别的 scope 伪造面只留约定，是无理由的不对称。修补是纯追加：blocklist 扩到 `emit_step(text,text,jsonb,text)`、`emit_step_claimed(uuid,text,text,jsonb,text,integer)`、`emit_step_scoped(uuid,text,uuid,text,jsonb,text,text[],integer)`，并把判据一句话写明（「in-db entrypoint 不得解析到任何可持久化调用方自选 payload 进 `agent_steps` 的函数」），P02 的 `checkpoint`（0002:270 起逐元素 `PERFORM cordis.emit_step`）与 `llm_checkpoint` 若符合该判据一并列入。`test_p08_control_plane_functions_are_not_model_tools` 追加对应用例。不改变 host 侧结论：host 注册无 SQL entrypoint，P10 仍负责宿主侧冒充。

### 3.（P2）File-by-file impact 两行与测试现状不符

- **`tests/test_p05_one_step_driver.py` 行写「Full-tree version/file-list pins → `p20`」，但该文件没有任何全树 pin。** 全部 P05 测试走 `_apply_p05_only` 截断树：文件清单断言止于 `0005`（test_p05:218-220），版本断言是 `'p05'`（:223、:1252），无 `'p19'` 出现。该行应改为「**No change**（P05-only 树保持 `p05`）；回归验证即可」，W87 的表述同步收窄。
- **`tests/test_p19_paradigm_policies.py` 行写「`next_sql_prefix` sentinel becomes `0021`」，但这不是测试改动。** `next_sql_prefix` 是 conftest 里按树内容动态计算的函数（`tests/conftest.py:60`，test_p19:646 调用），`0020` 入树后自动返回 `0021`，无需编辑。该文件真正要改的只有三处全树版本断言 `'p19'` → `'p20'`（test_p19:112、:451、:669）。计划应把这行改为事实描述，防止实现者去找不存在的硬编码 sentinel。

### 4.（P2）基线的 latch 表细则被压缩掉：`isolation_fold_handlers` 列规格与 `isolation_seams` 四个命名约束

基线（导出 400-417、382-388 行）给出了 `isolation_fold_handlers` 的完整列表格（`fold_fn regprocedure` PK；`contract_version` 恰为 `p08.v1` 的 CHECK；`installed_at timestamptz NOT NULL DEFAULT clock_timestamp()`）和 `isolation_seams` 的四个命名约束（`isolation_seams_pkey` / `isolation_seams_gate_fn_key` / `isolation_seams_name_check` / `isolation_seams_contract_check`）。现行计划把前者压成一段无列规格的散文（Component 1「isolation_fold_handlers」节），后者只剩匿名行内约束。这些是实现承重内容：W80 的建表和 `test_p08_fresh_apply_catalog_version_and_ready` 的结构断言都要引用它们。**修正**：把两块规格原样写回 Component 1。

### 5.（P2）种子 replay 语义欠钉：「upsert」需写明 `ON CONFLICT … DO UPDATE` 且决定 `installed_at` 的 replay 行为

基线明确「missing rows are restored; **mismatched canonical rows are corrected**」；现行计划压缩为「Replay restores canonical rows (upsert; no runtime customization)」。两个坑：其一，P19 种子的现成形状是 `ON CONFLICT … DO NOTHING`（0019:683、:715），照抄它无法纠正被改坏的行，四行 latch 是安装闩，必须是 `ON CONFLICT (seam) DO UPDATE SET gate_fn = …, contract_version = …`（fold handler 表同理）；其二，DO UPDATE 若连 `installed_at` 一起覆写，`test_p08_replay_preserves_existing_workspace_and_log` 的时间戳保持断言范围就必须把 latch 表排除或计划写明「replay 刷新 `installed_at`」。**修正**：Component 1 写出精确的 ON CONFLICT 形状并二选一钉死 `installed_at` 的 replay 行为，测试断言随之对齐。

### 6.（P2）scoped append 的 `42501` fragment 未命名

逐门错误表里其它每个 `42501` 都有精确 stable fragment（`P08_FOLD_RUN_GRANT_REQUIRED` 等），唯独 scoped append 写「`42501` with append-specific fragment」不给名字。W88 的测试要按精确字符串断言，实现者被迫自造。**修正**：在 Component 3 与错误表钉死名字（建议 `P08_SCOPED_APPEND_RUN_GRANT_REQUIRED` 与 `P08_SCOPED_APPEND_CORPUS_GRANT_REQUIRED`，或一个共用 fragment，二选一即可，但要写下来）。

---

## 需要用户/实现前拍板的问题

**Q1. dispatch descriptor 是否携带 P06 的 `inject`/`provide`/`intercept`（以及 `name`/`description`）？** 计划的 descriptor 字段清单（Component 6 第 9 步）只排除了「raw source metadata」（`metadata`/`source_kind`），但同样静默省略了 catalog 现有的生命周期信封 `inject`/`provide`/`intercept`（0006:16-18）。descriptor 是 P09/P16 的事实 ABI：P09 执行器若需要这些字段，届时要么改 P08 函数（触发再送审），要么绕门直读 catalog（违背「不得独立解释」的交接）。基线与三份草稿都未讨论。建议现在拍板并把结论写进 Component 6（多带三个字段的成本近零；不带则写明「P09 需要时以后续编号文件扩展 descriptor」）。

**Q2. `p_paradigm` 是调用方真值，run 侧无 paradigm 记录——现在是否在计划/README 写明这是 trusted-worker 输入？** fold 与 env 门的 paradigm 由调用方传入，数据库里没有 run↔paradigm 的绑定。P08 内无害：fold 输出的 `paradigm` 是 wrapper-owned 字段，env 获准路径恒 `55000`。但后续 env 计划落地 `run_vars` 后，调用方对 CodeAct run 谎报 `'rlm'` 即可绕过 `env_enabled=false` 的策略拦截。这不改 P08 的实现顺序，但两文都没有一句话把「paradigm 归属权在 trusted worker，run 级绑定是后续 env/P09 计划的前置问题」说出来。建议在 decision 表或 README 清单加一句，并列入 Open questions 的 deferred 清单。

---

## 维度对照小结

- 维度 1（基线缺失/弱化）：发现 4、5、6。
- 维度 2（欠钉的缝 / 矛盾 / 错误引用）：发现 1（矛盾）、3（错误引用）、5、6（欠钉）。
- 维度 3（代码证伪 / 更简设计取代）：`$p20$` → `$p08$` 偏离已被仓库证据支持，维持现行计划；无其它证伪项。
- 维度 4（两文皆缺）：发现 2（blocklist 不对称）、Q2（paradigm 真值归属）。
- 维度 5（拍板问题）：Q1、Q2。
