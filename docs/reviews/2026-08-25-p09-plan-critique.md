# P09 计划评审 — 对照 planning 导出基线与已落地代码

Date: 2026-08-25
Scope: `docs/plans/P09-in-db-worker-2026-08-25.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-25-201110-p09-in-db-worker-pla-5a29.md`。导出含两份叠放草稿：版本 1（第一个 `# P09 — In-database worker`，导出约 118 行起）在 W90 验证测试清单处**中途截断**（残留 "Reconnecting... 1/5"）；版本 2（约 1273 行起）是唯一完整稿。现行计划以版本 2 为保留基线并折入版本 1 独有细节——该整合选择正确。

对承重引用做了代码定点核对：`sql/0001_p01_claim.sql`、`sql/0002_p02_log.sql`、`sql/0003_p03_wait_event.sql`、`sql/0005_p05_one_step_driver.sql`、`sql/0006_p06_plugin_catalog.sql`、`sql/0019_p19_paradigm_policies.sql`、`sql/0020_p08_four_seam_enforcement.sql`、`tests/test_p00_sql_source.py`、`tests/test_p05_one_step_driver.py`、`tests/conftest.py`。

不重开：D1–D9、快照 §4、no `CREATE EXTENSION`、单队列、scratch/G 不抬 ABI、P08 mid-flow「`step_once` 不包不换」。P09 mid-flow 用户锁（2026-08-25）：保留 `invoke_in_db_tool`；wait 作为 P03 确认；现有 `step_once` 直接 COMMENT 注册为 `kernel.step_once`。三条锁在计划 decision 7、4、1 中均已落实，本评审不质疑。

## 结论摘要

**维度 1（导出内容缺失/弱化）无实质发现。** 对版本 2 基线做了逐节比对：现行计划结构与内容完整保留（决策表 14 条、五个组件、状态机、边界条件、file-by-file、W90–W99、21 个命名测试、tradeoffs、风险、实现顺序、deferred 清单）。版本 1 独有细节按整合注记折入且可逐一定位：四键 `details` 错误信封与 1000 字符上限（计划 590–609 行）、`P09_INVALID_TOOL_REQUEST`（406/440 行）、`config.protocol='cordis.p05.mock.v1'`（330 行）、pin 清点三分类（814–818 行）、dropped-responses 指引（693 行）、pg-agent 组合标记（800 行）。命名冲突按声明解决且两处使用点一致：`P09_JOB_HANDLER_UNSUPPORTED`（309/751 行）、`config.isolated=false`（331/922 行）。计划在验收断言上反而强于两稿（`run_state` `final|3|ok`、`jobs.result.answer='ok'`、零 `run/yield` 事件）。

承重代码引用抽查全部准确，计划的关键前提逐条被代码支持：

- **resolver ABI 检查对得上规范 handler。** `cordis.step_once(text,uuid,integer DEFAULT 90) RETURNS text` 恰为 VOLATILE、SECURITY INVOKER、`SET search_path TO pg_catalog`（`sql/0005_p05_one_step_driver.sql:69-78`）——decision 6 的全部 pg_proc 检查项在规范注册对象上均通过，`kernel.step_once` 不会被自家 resolver 拒掉。
- **enqueue 注入 `payload.paradigm` 不破坏 P05 走查。** `step_once` 的 payload 校验只对已知键（`model`/`llm_params`/`tools`/`max_steps`/`mock_llm`）做类型检查，不拒未知顶层键（0005:195-232），故 `PROOF_PAYLOAD || {"paradigm": ...}` 安全。
- **P06 侧全部前提成立。** `plugin_catalog.config jsonb` 存在（0006:21）且 `_validate_plugin_definition` 接受任意对象键（0006:418-426），`config.worker_abi` 标记可落地；`required_grants text[]` 允许空数组（0006:90-91）；identity 文法与 128 字节上限收 `kernel.step_once`（0006:27-29）；queue 的 `transactional+idempotent+none` 是合法组合（0006:434-442）；description ≤500（0006:267-269）；apply 时文件级 `SELECT cordis.refresh_plugins();` 已有先例（0006:779）。
- **P01/P02 动词与计划逐字吻合。** `claim_job(text,text,integer DEFAULT 90) RETURNS SETOF jobs`，先 `release_stale` 再 `SKIP LOCKED`，序 `priority DESC, available_at ASC, job_id ASC`（0001:117-170）；`yield_claim(uuid)` / `complete_claim(uuid, jsonb DEFAULT NULL)` / `fail_claim(uuid, jsonb 非空)` 三者栅栏谓词均为 token+RUNNING+未过期（0001:198-282）；`jobs` 有 `attempt DEFAULT 1`、`available_at DEFAULT '-infinity'`（即立即可领）、`jobs_run_id_key` UNIQUE、claim-fields 约束保证非 RUNNING 行 claim 字段全 NULL（0001:4-45）——计划 wait 确认里的 NULL 检查因此不可能被半清空状态骗过。`emit_step_claimed(uuid,text,text,jsonb,text DEFAULT NULL,integer DEFAULT 90) RETURNS boolean` 允许 `kind='error'` 且 `step_name` NULL（0002:72-111）。
- **P08 接口吻合。** `authorize_tool_dispatch(text,uuid,text,jsonb) RETURNS jsonb`，描述符含 `locus/invocation/effect_class/retry_class/reconciliation/entrypoint/config`（0020:598-774）；`_require_isolation_feature` 与 `P08_ISOLATION_FEATURE_CLOSED` 字面一致（0020:121,136）。
- **P19 归一化闭环成立。** `paradigm_policy` 自做文法校验、`btrim` 归一化、返回 `identity` 列、未知抛 `22023`（0019:477-528）；`codeact` 种子在 0019 落地（:666）——enqueue 直接存返回行的 `identity` 即可，无需前置文法检查（版本 1 的前置检查被 v2/计划省略是等价简化，非弱化）。
- **wait 确认的健全性论证成立。** `run_waits` 以 `run_id` 为主键并 FK 到 jobs（0003:44-47），"恰一行"即"存在"；`claim_job` 的 UPDATE 使本事务持有该 jobs 行锁，claim 后能把它改成 WAITING 的只有本事务内的 `await_event`——handler 谎报 `wait` 必然被 RUNNING 分支抓住。`await_event(uuid,text,text,text,uuid,...)` 的签名允许只持 (run, token, lease) 的夹具 handler 自造 scope/name/await_id 注册（0003:64-73）。
- **测试针脚。** `test_fresh_apply_lists_current_tree_and_p20` 与 pg-agent 组合测试实名存在（test_p00:76,545）；`next_sql_prefix` 在 conftest（:60）；`PROOF_PAYLOAD` 在 test_p05:28。

剩余发现：**1 条 P1**（测试夹具注册纪律欠规格，两稿与计划均未写），**5 条 P2**。无 P0。P1 折入后计划可翻 `ready to implement`。

---

## 发现

### 1.（P1）W97–W98 的 COMMENT 夹具纪律欠规格 — schema 限定与精确清点断言会互相踩

计划（943 行）允许「测试自定义 queue/tool 函数装入一次性测试库并经 COMMENT + `refresh_plugins()` 注册」，但两稿与计划都没写三件实现必然撞上的事：

1. **夹具必须建在 schema `cordis` 里。** `refresh_plugins` 的 COMMENT 扫描硬限定 `ns.nspname = 'cordis'`（`sql/0006_p06_plugin_catalog.sql:495-496`）。放在别的 schema 的夹具会**静默**不入目录，`test_p09_queue_handler_resolver_rejects_wrong_shape` 等测试将拿到 `P09_UNKNOWN_JOB_HANDLER` 而不是预期的形状类错误，排错成本高。
2. **夹具与精确清点断言冲突。** `test_p09_fresh_apply_catalog_version_and_signatures` 断言「恰四个新 identity、无 overload/类型/表」，`test_p06` 全树断言精确目录数——若 P09 模块沿用同库共享 apply（`test_p01` 的 `_ensure_p01` 模式），先跑夹具测试再跑清点测试就会数出多余的 cordis 函数与目录行。计划需写明：清点/签名断言在 fresh `--reset` apply 之后、任何夹具安装之前执行，或独立数据库。
3. **坏 COMMENT 毒化全局。** cordis schema 内任何 `{` 开头但解析失败的注释会让 `refresh_plugins` 整体抛错（P06 既有测试 `test_unrelated_bad_comment_blocks_register_and_preserves_rows` 固化了这一行为）。夹具 COMMENT 必须是完整合法的 `cordis_plugin` 定义；负例（wrong-shape）夹具要靠**合法元数据 + 非法函数形状**构造，不能靠坏 JSON。

**修正**：在 W97–W98 夹具段补一段三点纪律（schema `cordis`、清点断言先于夹具、COMMENT 必须可解析），并在 `test_p09_source_boundaries` 或模块布局注记里点明测试内的 apply/reset 顺序。纯计划文本，成本一段话；不折则测试实现阶段必返工。

### 2.（P2）`KERNEL_FUNCTIONS` 插入位置写错一处 — `invoke_in_db_tool` 排在 `invoke_llm` 之前

计划 728 行称 `cordis.invoke_in_db_tool` 插在「after `invoke_llm`」。字典序 `invoke_in_db_tool` < `invoke_llm`（`in` < `ll`），正确位置是 `cordis.get_schema_version` 与 `cordis.invoke_llm` 之间（对照 `tests/test_p00_sql_source.py:45-46`）。其余三个位置（`_resolve_in_db_queue_handler` 在 `_require_isolation_feature` 后、`worker_step` 在 `unregister_paradigm_policy` 后、`enqueue_job` 未声明位置）核对无误。照抄会立刻被 P00 测试抓住，属自纠错误，但计划文本应改。

### 3.（P2）v1 queue ABI 的 payload 获取契约在两稿与计划中都只是隐式的

handler 只收 `(run_id, claim_token, lease_seconds)`，payload 不在参数里；规范 handler `step_once` 是自己回读 claimed jobs 行取 `job_type`/`payload` 的（`sql/0005_p05_one_step_driver.sql:129-138`）。W98 要求测试作者写多个自定义 ABI 兼容 handler（terminal-without-log、wait 注册、异常、慢 handler），他们需要这条契约。**修正**：在 Component 1 的 ABI 定义或 README 清单里加一句「v1 queue handler 通过自己的 claim 读取 `cordis.jobs` 行获得 payload；worker 不传递 payload」。

### 4.（P2）合成错误路径的 `emit_step_claimed` 续租秒数未指定

`emit_step_claimed` 第六参 `p_extend_seconds DEFAULT 90`（0002:78）。worker 的合成错误 append（admission 失败、`P09_*_WITHOUT_*`、`P09_INVALID_STEP_OUTCOME`）应传 `p_lease_seconds` 还是吃默认 90，计划未说。行为差异仅在于紧接着的 `fail_claim` 前几毫秒的租约长度，无实际后果，但测试若断言精确调用形状需要一个定论。**修正**：一句话选定（建议传 `p_lease_seconds`，与 handler 调用一致）。

### 5.（P2）`invoke_in_db_tool` 第 2 步显式闩锁与 `authorize_tool_dispatch` 内部闩锁重复 — 保留则应写明意图

`authorize_tool_dispatch` 自己会 `PERFORM cordis._require_isolation_feature()`（0020:638）。计划算法把显式闩锁放在第 2 步（claim 检查之前），效果是「闩锁错误先于 claim 错误」的报错优先序——与只靠第 4 步内部闩锁（claim 错误先出）不同。两种都自洽；计划应写明第 2 步是有意的优先序选择（decision 14 的「tool invocation 前置闩锁」落点），避免实现者当冗余删掉后改变错误顺序、W92 测试对不上。

### 6.（P2）整合注记残留：`legacy_unscoped` 字面并未真正落进 description 要求

计划 16 行称命名冲突解决为「`config.isolated=false` + description 用语 `legacy_unscoped`」，但计划正文对 COMMENT description 的要求只有「说明是 P05 mock/proof body、非隔离驱动」（316 行），从未要求 `legacy_unscoped` 字面。无行为影响。**修正**：要么把该 token 写进 description 要求，要么从整合注记里删去这半句，避免实现者去满足一个不存在的断言。

---

## 问题（维度 5）

无改变设计或实现顺序的开放问题。一条实现注记随发现 4/5 顺带记录：`test_p09_in_db_tool_checks_claim_before_and_after_execution` 的「后过期」场景最简构法是短租约（如 1 秒）+ 夹具内 `pg_sleep`——PostgreSQL 不强制被调函数遵守声明的 volatility，STABLE 夹具里 sleep 是合法的；不要尝试从第二连接缩短活租约（P01 没有该动词，`renew_claim` 只能延长）。

## 裁决

**尚未 ready to implement——差一条 P1。** 计划对版本 2 基线的保留完整，版本 1 独有细节按整合注记如实折入，全部承重代码引用与接缝（resolver ABI 对 `step_once`、P06 `config`/文法/效果矩阵、P01/P02/P08/P19 签名、wait 确认健全性、payload 注入兼容性）经代码核对成立，锁定项无一被触碰。折入发现 1（夹具纪律，一段文本）后即可按 AGENTS.md 将 Status 翻为 `ready to implement`；发现 2–6 为廉价文本修正，建议同批折入。

### Resolution (2026-08-25, post-critique)

Finding 1 (fixture discipline) and P2 nits 2–6 were folded into `docs/plans/P09-in-db-worker-2026-08-25.md`. Plan status is **ready to implement**. This note does not rewrite the original verdict above.
