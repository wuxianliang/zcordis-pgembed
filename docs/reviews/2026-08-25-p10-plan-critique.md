# P10 计划评审 — 对照 planning 导出基线与已落地代码

Date: 2026-08-25
Scope: `docs/plans/P10-host-sql-seam-2026-08-25.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-25-211740-p10-host-sql-seam-de-be2e.md`。导出含两份叠放草稿：v1（导出 151 行起）与 v2（导出 984 行 `# P10` 起）。**v2 是保留基线**；v1 为同一设计，计划文首声明的五个 v1 独有 fold（`ClaimedJob` 全行字段含 `status`、显式 stdlib 导入清单、`VERBOSITY=verbose`、异常脱敏、不暴露 `refresh_plugins` 的 rationale）已逐一核对落实。

对承重引用做了代码定点核对：`sql/0001_p01_claim.sql`、`sql/0002_p02_log.sql`、`sql/0003_p03_wait_event.sql`、`sql/0005_p05_one_step_driver.sql`、`sql/0006_p06_plugin_catalog.sql`、`sql/0007_p07_grant_registry.sql`、`sql/0019_p19_paradigm_policies.sql`、`sql/0020_p08_four_seam_enforcement.sql`、`sql/0021_p09_in_db_worker.sql`、`tests/conftest.py`、`tests/test_p00_sql_source.py`，以及 `git log`/`git status` 实际仓库状态。

不重开：D1–D9、快照 §4，以及 2026-08-25 四条 mid-flow 用户锁定（同步 `psql` 子进程传输；不加编号 SQL；`authorize_host_tool` 仅授权不执行；客户端置于仓根 `pg_cordis_host/`）。四条锁定在计划 decision 2/3/11/7 中均一致落实，未发现违反。

## 结论摘要

**维度 1（导出基线内容缺失/弱化/泛化）基本无发现。** 现行计划与 v2 基线逐节比对：决策表（v2 的 15 条，含 v1 的 no-cache 与 response-loss 两条折入计划 decision 14/15）、六个组件设计、状态/数据流、错误表、file-by-file、W100–W108 与 18 个命名测试、fixture 规则、tradeoffs/risks、实施顺序 19 步、deferred 清单，全部忠实保留且多处更精确（如 v1 的完整 `ClaimedJob` 字段与 `jobs` DDL 逐列核对一致，`sql/0001_p01_claim.sql:4-54`）。唯一丢失项是 v1 的一条非目标（发现 6，低）。

**主要问题集中在计划相对导出新增的精度内容：** 计划新加的 file:line 引用系统性过期（发现 2，中）；计划的 P09 协调状态被仓库现状证伪——**P09 已提交**（`f6b3d70`，HEAD），计划仍写「HEAD is P08、P09 未提交」（发现 1，中）；验收 fixture 的三个常量未钉，其中 env 错误断言只在 paradigm=`rlm` 下成立，`codeact` 下被代码证伪（发现 3，中）。

**无 P0。** 三个 P1（发现 1–3）折叠成本均极低（改文字/行号，不动设计），六个 P2 顺手补句。折叠后计划可按 AGENTS.md 流程翻 `ready to implement`。

---

## 发现

### 1.（中 / P1）P09 已落地，计划的「HEAD is P08、P09 未提交」协调故事被仓库现状证伪

计划多处描述的状态已不存在。实际 `git log`：HEAD 为 `f6b3d70 Add pg_cordis P09 in-database worker.`，工作区无任何 P09 未提交文件；`tests/test_p00_sql_source.py:80,102` 已钉 `0021` 文件清单与 marker `p21`。受影响处：

- 计划 line 262：「HEAD is P08 (`fb8c11a`). P09 SQL/tests currently sit uncommitted in the working tree.」——错误。
- line 11 与 line 274-281：marker「`p21` when `0021` 存在否则 `p20`」的条件式现在可无条件钉死为 `p21`。
- line 953（file-by-file 的 P09 行 Ordering 列「Must be committed separately or isolated in another worktree」）、line 1202-1206（Risks 的「P09 working-tree contamination」）、line 1222（实施顺序第 3 步「P09 committed separately, or a clean P10 worktree」）——风险已消解，应改写为「P09 已提交于 `f6b3d70`；P10 在其后的主线上工作，commit 不含任何 P09 路径」。
- line 1133（W108 的 pre-P09 条件分支「omit only the nonexistent `tests/test_p09_in_db_worker.py`…marker remains `p20`」）——保留它会让实现者以为存在合法的 p20 基线变体；既然 P09 已落地，建议删除该分支，cross-protocol 套件无条件含 `test_p09_in_db_worker.py`，marker 断言无条件 `p21`。

**修正**：把上述六处统一改写为「基线为 P09 已提交树（`0021`/`p21`）；P10 不加 SQL，marker 与 `test_p00` pin 均不动」。这不改动任何设计决定（四条 mid-flow 锁定不受影响），只是把计划对齐到仓库事实；同时让 `test_p10_public_api_inventory_and_no_new_sql_marker` 的「baseline marker」从条件式变为常量 `p21`。若保留条件式作历史说明，也必须以「实际基线 = p21」为主表述。

### 2.（中 / P1）Background 动词清单的 file:line 引用系统性过期（函数名/签名/返回形状均核对无误）

计划相对导出新增的动词清单表（lines 172-190）与 P08 denylist 引用（line 231）中，约 14/18 个行号与当前代码不符。逐一核对后的正确值：

| 计划位置 | 引用对象 | 计划写 | 实际 |
|---|---|---|---|
| line 172 | `claim_job` | `0001:151` | `0001:117` |
| line 173 | `renew_claim` | `:207` | `:172` |
| line 174 | `yield_claim` | `:240` | `:198` |
| line 175 | `complete_claim` | `:270` | `:225` |
| line 176 | `fail_claim` | `:298` | `:252` |
| line 177 | `release_stale` | `:92` | `:64` |
| line 179 | `checkpoint` | `0002:119` | `0002:147` |
| line 180 | `emit_step_claimed` / `emit_step` | `:69` / `:39` | `:72` / `:40` |
| line 182 | `next_step_name` | `:211` | `:279` |
| line 183 | `llm_checkpoint` | `:245` | `:335` |
| line 184 | `run_state` | `:273` | `:366` |
| line 185 | `await_event` | `0003:81` | `0003:64` |
| line 186 | `emit_event` | `:213` | `:307` |
| line 189 | host 行 NULL entrypoint 约束 | `0006:96-106` | `0006:77-93`（`plugin_catalog_source_entrypoint_check`） |
| line 196 | P05 第二处 md5 | `0005:275` | `0005:363` |
| line 231 | `authorize_tool_dispatch` denylist | `0020:547-575` | 函数本体 `:598`，denylist `:647-673` |

核对无误的引用：line 181 `emit_step_scoped` `:145-153`、line 188 `register_host_plugin` `:716` / `unregister_host_plugin` `:742`、line 196 P05 guard `:37-39`、line 560 `p08_scope` 保留字段检查 `:197-200`。

**修正**：按上表改行号。签名与语义描述本身全部准确（见文末核对记录），这是纯引用修正，折叠成本极低；但一份声称 implementation-ready 的计划不应带着系统性错位的行号进入实现。

### 3.（中 / P1）验收/测试 fixture 三个常量未钉；其中 env 错误断言在 `codeact` 下被代码证伪

**(a) jobs 行产生机制未命名。** W105 步骤 1（line 1045）只说「trusted test setup creates one PENDING jobs row」。两个候选：trusted `psql` 直接 `INSERT`（`jobs` 约束允许 PENDING 直行，`0001:4-54`），或 P09 `enqueue_job`（`0021:95`）。后者与计划自己保留的 pre-P09 条件分支（line 1133）冲突；折叠发现 1 后冲突消失，但计划仍应钉死其一。**建议钉直接 INSERT**：它同时强化「host 客户端不接触 `enqueue_job`」的边界，且与 P09 语义解耦。

**(b) fold/env 的 paradigm 实参未命名。** `fold_slice_messages` 经 `cordis.paradigm_policy` 校验 paradigm 并要求 certified fold handler（`0020:488-498`）；P19 只种子了 `codeact` 与 `rlm` 两个 identity（`0019:666,698`）。W105 步骤 9/10（lines 1053-1054）与 W104/W107 的 fold 测试必须显式选一个。顺带钉死步骤 10 的第二 slice 设置：它必须同属该 run（否则 `slice_live_grants` 抛 `slice does not belong to run`，`0007:698-700`）且不带 run grant，期望结果是 `42501 P08_FOLD_RUN_GRANT_REQUIRED`（`0020:484-486`），把 line 1054 的「absent or denied」收敛为确定的 denied。

**(c) env 断言 paradigm 依赖被漏掉，现行表述被 `codeact` 证伪。** 计划 line 685 与 edge 表 line 920 写「authorized env currently raises `55000 P08_ENV_WORKSPACE_UNAVAILABLE`」。实际 `read_run_env` 先查 paradigm policy（`0020:579-587`）：`codeact` 种子为 `env_enabled=false, env_workspace='none'`（`0019:672-673`）→ 抛 `42501 P08_ENV_DISABLED`；只有 `rlm`（`env_enabled=true, env_workspace='run_vars'`，`0019:704-705`）在授权后走到 `55000 P08_ENV_WORKSPACE_UNAVAILABLE`（`0020:593-594`）。W104 的「env reaches the existing P08 unavailable error」与 `test_p10_four_seam_calls_are_slice_bound_and_not_cached` 的「env error preserved」只有用 `rlm` 才成立。

**修正**：在 Component 5 或 W105 fixture 段钉三行常量——jobs 行用 trusted INSERT；fold 用 `codeact`（或 `rlm`）；env 测试用 `rlm` 并断言 `55000 P08_ENV_WORKSPACE_UNAVAILABLE`。同时把 fixture 规则补一条：slice/grant 用 P07 trusted 动词（`create_slice` + `issue_grant`；live = `status='issued'`，`0007:711-714`），与既有 P08 测试 fixture 模式一致。

### 4.（低 / P2）传输契约「恰好一个 JSON 文档」缺少标量包装约定；错误注入机制未点名

计划传输算法第 9 步（line 465）要求 stdout 为「exactly one JSON response document」。但 `renew/yield/complete/fail/checkpoint/emit_step_scoped/sleep` 返回 boolean，`next_step_name`/`provider_idempotency_key` 返回 text；`psql -t -A` 下裸 `SELECT cordis.yield_claim(...)` 输出 `t`，不是 JSON。实现者需要明确：所有固定模板用 `to_jsonb(...)`（标量）或 `row_to_json`/`jsonb_build_object`（行）包装，使「一个 JSON 文档」契约对所有方法同形。顺带在 W100 verify 或 W107 夹具规则补一句：timeout/畸形输出/非零退出的错误注入用 `psql_path` 指向 stub 可执行文件实现（计划已要求这些错误映射到精确类型，但未说怎么测）。

### 5.（低 / P2）`claim_expires_at` 的「future」校验用主机时钟比数据库时间戳，时钟偏移下假阳性

计划 line 496 要求认领行 `claim_expires_at` 在未来。该值由数据库 `clock_timestamp()` 生成（`0001:145,162`），客户端将其与**主机**时钟比较；主机时钟落后超过 lease 余量时，合法认领会被误判为 `CordisProtocolError`。导出与计划均未覆盖此失败模式。本地 pgembed 测试同机不受影响，但 `docs/host-sql-seam.md` 与实现应一致。**修正**（二选一，建议前者）：claim 模板同时返回 DB 侧 `clock_timestamp()`，客户端用 DB 时间做 future 比较；或删掉该校验项（`status='RUNNING'` + 非空 token + `claimed_by` 匹配已足够识别本客户端的认领）。

### 6.（低 / P2）v1 独有非目标「不得宣称 acceptance 证明外部 provider 幂等」未折进计划

导出 v1 line 234 的非目标「claim that the acceptance fixture proves external provider idempotency」未出现在计划非目标列表（lines 78-109）。acceptance 在 fixture payload 里存了 provider key（W105 步骤 7），读者容易把「host 派生出与 P05 一致的 key」过度宣称为「外部幂等已证明」。补回一行，成本一行。

### 7.（低 / P2）`next_step_name` 的 resume 语义被「returns stable `s-N`」泛化

实际实现（`0002:299-322`）：无 llm 行 → `s-1`；最新 llm 步之后无同名 tool/final 行 → 返回**同一个** step 名（恢复/续跑语义）；否则 `s-(max+1)`。计划的未来 host LLM 排序（`next_step_name` → `llm_checkpoint` → skip-if-present，lines 595-608）恰好依赖这个 resume 行为才正确：崩溃后重领会得到同一个 `s-N`，再由 `llm_checkpoint` 命中已提交行跳过 HTTP。计划 Component 3（line 568）与动词表（line 182）只写「returns stable `s-N` based on committed log state」，未点名 resume 语义，「next」命名会误导实现者以为单调递增。补两句说明即可，不改设计。

### 8.（低 / P2）取消路径未覆盖：SIGINT/主机进程被杀时 in-flight `psql` 成为孤儿，仍可能提交

计划的 cancellation 节（lines 838-851）只覆盖「psql times out or is killed before commit」。`subprocess.run` 在 `KeyboardInterrupt` 时不会杀子进程；主机进程被 SIGINT/SIGKILL 打断时，in-flight `psql` 可能继续跑到提交。这与 timeout 同属 unknown-outcome 类，但计划未写。**修正**：在 cancellation 节加一行「主机侧取消/中断同样按 unknown-outcome 表 reconcile；客户端不在中断路径上自动重试或补刀」，W106 文档清单（line 1064）同步加一项。

### 9.（低 / P2）`RunState.status` 词表未写

`run_state` 实际返回 `final` / `error` / `in-progress`（`0002:388-392`），计划 `RunState` 类型（line 425）只写 `status` 不给词表。lost-response 对账表（lines 841-849）的 Complete/fail 行依赖该词表解释结果。在 Component 3 类型表补一句词表及出处。

---

## 需要用户/实现前拍板的问题

1. **发现 1 的折叠方式**：建议直接把基线钉死为「P09 已提交（`f6b3d70`），marker `p21`」，删除 W108 的 pre-P09 条件分支；若希望保留条件式作历史说明，主表述也必须以 p21 为实际基线。这决定 `test_p10_public_api_inventory_and_no_new_sql_marker` 的 marker 断言是常量还是条件式。
2. **发现 3(a) 的 jobs 行 fixture 机制**：建议钉 trusted `psql` 直接 INSERT（与「客户端不接触 `enqueue_job`」边界互证）；若选 `enqueue_job`，需在计划写明它属于 fixture  trusted setup 而非客户端 API。
3. **发现 5 的 `claim_expires_at` future 校验**：建议改为与 DB 侧 `clock_timestamp()` 比较（claim 模板多返回一列）；若认为同机部署假设足够，也可删该项校验。两者都改计划一句话。

以上无一触及 D1–D9、快照 §4 或四条 mid-flow 锁定。发现 1–3 折进计划、4–9 顺手补句后，本 critique 无阻塞项遗留。

**Orchestrator fold (2026-08-25):** all three 拍板 questions resolved in `docs/plans/P10-host-sql-seam-2026-08-25.md` without reopening mid-flow locks.

1. Baseline pinned to committed P09 `f6b3d70` / marker `p21`; W108 pre-P09 branch deleted.
2. Jobs fixture is trusted `psql` `INSERT`, not `enqueue_job`.
3. Host-clock `claim_expires_at` future check dropped; `status` + token + `claimed_by` identify the live claim.

P2.4 JSON wrapping, P2.6 v1 non-goal, P2.7 `next_step_name` resume, P2.8 SIGINT unknown-outcome, P2.9 live `run_state` vocabulary (`final`/`error`/`awaiting`/`in-progress` from `sql/0003_p03_wait_event.sql:517-522`), and stub-executable error injection are also folded. Status is `ready to implement`.

---

## 核对记录（代码定点抽查，全部通过 except 文中已列项）

- P01：`claim_job` 先 `release_stale` 再 `FOR UPDATE SKIP LOCKED` 认领、`NULL` run 全局轮询、返回整行（`0001:117-170`）；`complete_claim(token, jsonb DEFAULT NULL)`（`:225`）、`fail_claim` 的 reason 非空校验（`:263-266`）、当前 `fail_claim` 恒置 ERROR（`:268-272`）——计划描述全部准确。`jobs` DDL 列与 `ClaimedJob` 全字段逐列一致（`:4-19`），`UNIQUE(run_id)`（`:21`）支持 `get_job` 单数返回。
- P02：`checkpoint` 事件形状 `{run_id,kind,payload,step_name?}`、空数组合法且仅续租、单 run 强制、false 即未追加（`0002:147-277`）；`emit_step_claimed` 六参与 token+RUNNING+未过期栅（`:72-145`）；llm 步唯一索引存在（`:36-38`），`llm_checkpoint` 带 `LIMIT 1`（`:361-362`，故计划「多行即协议错误」为不可达的防御性检查，保留无害）；`run_state` 返回 `(status, steps_used, answer, text error)`（`:366-374`）。
- P03：`await_event(uuid,text,text,text,uuid,timestamptz,jsonb,integer)` 与计划客户端签名逐参一致，返回 `(accepted, should_suspend, payload, source_run_id, source_seq)`（`0003:64-80`），与 `AwaitEventResult` 一致。
- P05：provider-key guard `md5(p_run_id || '/' || p_step_name)` 在 `0005:37-38`；计划的数据库派生 key 与之逐字符一致。
- P06：`register_host_plugin` 内部调 `refresh_plugins()`（`0006:737`）、`unregister_host_plugin` 同（`:763`）——计划「不暴露 `refresh_plugins` 公共方法」的 rationale 被代码支持。catalog 含 `entrypoint regprocedure`（`:24`），host 行 NULL entrypoint 由 CHECK 强制（`:77-93`）。
- P07/P08：`slice_live_grants` live = `status='issued'`（`0007:711-714`）；`emit_step_scoped` 八参、run/corpus 授权检查、`p08_scope` 由库侧附加（`0020:145-231`）；`authorize_tool_dispatch` 描述符键集（identity/locus/invocation/entrypoint/effect_class/retry_class/reconciliation/bindings/required_grants/…，`0020:752-774`）与计划 `authorize_host_tool` 校验清单逐项对应，bindings 键集必须等于 `required_grants`（`:699-708`）；denylist 内容（含 `cordis.` 前缀双写）与计划 line 231 一致。
- P19：种子 paradigm 仅 `codeact`（env 关）与 `rlm`（env 开、`run_vars`）（`0019:664-715`）——发现 3(c) 的依据。
- P09：`enqueue_job`/`invoke_in_db_tool`/`worker_step` 存在且已提交（`0021:95,160,327`），marker `p21`（`:570-576`）；`test_p00` pin 已是 `0021` + `p21`（`tests/test_p00_sql_source.py:80-102`）。
- 夹具：`POSTGRES_BIN_PATH` 来自 `pgembed`、`server.get_uri(database)` 为既有 API（`tests/conftest.py:17,41-57`），计划 fixture 规则 3 与其一致。
