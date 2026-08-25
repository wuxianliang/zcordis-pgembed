# P11 计划评审 — 对照 planning 导出基线与已落地代码

Date: 2026-08-25
Plan: `docs/plans/P11-alternating-claim-2026-08-25.md`
Export（保留基线）: `prompt-exports/oracle-plan-2026-08-25-225006-p11-alternating-clai-58e3.md` — 仅 `# P11 — Dual-worker alternating claim proof` 起的 Generated Plan 响应为基线；其前的组合 prompt 与选件转储只是上下文。
Verdict: **pass with nits** — 无 P0，无 P1；四条 P2。

方法：逐节 diff 导出基线与现行计划；对承重 `file:line` 引用做定点核对（`sql/0001_p01_claim.sql`、`sql/0002_p02_log.sql`、`sql/0005_p05_one_step_driver.sql`、`sql/0007_p07_grant_registry.sql`、`sql/0020_p08_four_seam_enforcement.sql`、`sql/0021_p09_in_db_worker.sql`、`pg_cordis_host/client.py`、`tests/conftest.py`、`tests/test_p00_sql_source.py`、`tests/test_p01_claim.py`、`tests/test_p09_in_db_worker.py`、`tests/test_p10_host_sql_seam.py`，以及 P09/P10 计划、骨架、快照的被引行）。

不重开：D1–D9、快照 §4，以及计划 §Mid-flow lock 记录的四条锁（host `run/yield` 且 SQL `step_name=NULL`；反向 steal 用 raw `claim_job` 留 RUNNING 再过期；单合并测试 `test_p11_in_db_host_in_db_alternation_and_bidirectional_stale_takeover`；tests-only / marker `p21`）。四条锁与导出 resolved decisions 1/3/5 及 W111 拓扑一致，且与当前代码无矛盾。

## 结论摘要

**维度 1（导出基线内容缺失/弱化/泛化）：无发现。** 计划保留了导出的全部实现承重内容（六个 resolved decisions、十二条约束、契约/数据流/错误表/W110–W114/文件清单/风险/实施顺序），并在六处加强而非泛化：

1. 两个 canonical worker identity 钉成确切值（`in-db:p11:worker-a`；`host:p11proof:0123456789abcdef0123456789abcdef`），并正确指出 `new_host_worker_id` 的 `instance_id` 是 `uuid.UUID`（`pg_cordis_host/client.py:251-259`）；
2. 完整 `P11_PAYLOAD` 字典，与 P09 `PROOF_PAYLOAD`（`tests/test_p09_in_db_worker.py:21-47`）逐键一致（仅 question 字符串不同），且不含 `paradigm` 键——与 `enqueue_job` 拒绝 payload 自带 `paradigm`、自行注入的校验（`sql/0021_p09_in_db_worker.sql:125-129,145-148`）相容；
3. 新增「Canonical P07 slice/grant fixture」节，`create_slice(run_id, 'p11-host', 'host')` / `issue_grant(run_id, slice_id, 'run', '', 'host')` 与 `sql/0007_p07_grant_registry.sql:166-170,336-342` 签名及 P10 夹具（`tests/test_p10_host_sql_seam.py:133-153,484`）完全吻合；
4. API 块给出精确 client 签名（`claim_job(run_id, lease_seconds=90)`、`emit_step_scoped(claim_token, run_id, slice_id, kind, payload, *, step_name=None, corpus_ids=(), extend_seconds=90)` 等），与 `client.py:524-526,668-679,730,744,794` 一致；
5. §Mid-flow lock 把四条用户决定落成显式锁；
6. References 增补 decisions 与 absurd TE5 文档，并给 SQL 引用补上（绝大多数准确的）行号。

**维度 2/3（欠钉、矛盾、被代码证伪）：** 一处 P10 先例的错误定性（P2-1），`sql/0001` 四处行号漂移（P2-2），文首 Status 与 §Mid-flow lock 自相矛盾（P2-3）。

**维度 4（两文均缺）：** 一条承重但未写明的基线假设——yield/stale-release 后立即可重领（P2-4，本次评审已代码核实安全）。其余面——取消（`CordisCommandTimeout` 即失败不重放）、失败清理（不加 auto-yield，交给下次 `--reset`）、所有权（token 权威、`claimed_by` 仅观测）、生命周期（一行不变量、attempt 1→2→3）、可测性（确定性 backdate、无 sleep/轮询）——两文均已覆盖。

**维度 5（会改设计/顺序的问题）：** 无。六个骨架开放问题全部以代码核实的依据关闭；四条 mid-flow 锁与之一致。

## 核对后确认准确的承重引用（抽查记录，供 fold 后免复查）

- `sql/0002_p02_log.sql`：`emit_step_claimed` 起 :72；kind 白名单含 `run/yield`（:102-108）；`llm`/`tool` 强制 `step_name`、`run/yield` 不强制（:109-112）；append 前以 token+run_id+RUNNING+未过期为栅并 `GREATEST` 续租；`next_step_name` 只看 `kind='llm'`（:299-305，函数 :279-343）。计划 :198-199、:215 的引用成立。
- `sql/0020_p08_four_seam_enforcement.sql`：`emit_step_scoped` :145-230；非 object payload 拒绝恰在 :171-174；`reserved field p08_scope` :197-200；run grant 检查与事件 kind 无关（:203-206）——`'run'`/`''` grant 即足够，这正是计划 fixture 的形状；`p08_scope` 注入 :214-220。
- `sql/0021_p09_in_db_worker.sql`：`enqueue_job(p_run_id, p_job_type, p_paradigm, p_payload, p_priority)` :95-102；`worker_step(p_worker_id, p_run_id, p_lease_seconds)` :327-337。与计划的调用形参序一致。
- `pg_cordis_host/client.py`：`_WORKER_ID_RE` :21-23 与 W110 Verify 的正则逐字符一致；`_claimed_job` 对 `claimed_by` 不匹配抛 `CordisProtocolError`（:396-397），计划 :193 的括注属实；`ClaimedJob` 含 `attempt`/`status`（:124-140），W112 宿主侧断言可直接读 `ClaimedJob`。
- `sql/0005_p05_one_step_driver.sql`：llm checkpoint 恢复校验 protocol/fingerprint/provider_key，不匹配即 `P05_LLM_CHECKPOINT_MISMATCH`（:361-385）——计划「host `llm/s-2` 会被下一步 `worker_step` 当 resume 拒掉」的风险论证成立，decision 3 / mid-flow 锁 1 的代码依据充分。
- 文档引用：P09 计划 :72、:1051 及 decision 13（:263「P09 adds no `run/yield` log event」）、P10 计划 :109、:504、:1188、:1262、快照 :198、骨架 :54-58 与 :239-245，全部属实。
- 测试面：`tests/` 下恰有计划交叉套件点名的 11 个文件；`PGCORDIS_PGDATA` 确由 `tools/apply_pg_cordis.py:255` 读取；`tests/test_p00_sql_source.py:79-101` 的 `0021`/`p21` pin 与计划「不动它」相容。

## 发现

### P2-1. 计划 :198 把 P10 的 `run/yield` 先例误述为「scoped」——P10 只经 `checkpoint` 发过 `run/yield`

计划 §Canonical host step 第 7 条称「host prior art: `tests/test_p10_host_sql_seam.py` scoped `run/yield` appends」。代码事实：P10 的宿主 `run/yield` 事件全部走 `client.checkpoint` 批量事件（`CheckpointEvent(run_id, "run/yield", …)`，`tests/test_p10_host_sql_seam.py:426-427`，断言 :429-437），出现在 `test_p10_checkpoint_and_scoped_append_are_claim_fenced`；该文件全部 10 处 `emit_step_scoped` 调用的 kind 均为 `llm`（如 :302-308、:447-448、:490-497、:544-546）。即 P11 的宿主事件将是**首个**经 P08 的 scoped `run/yield`，并无 scoped 先例。

设计不受影响（mid-flow 锁 1 不重开）：`run/yield` 在 P02 kind 白名单内（`sql/0002_p02_log.sql:104`）、不强制 `step_name`（:109-112）、P08 的 grant 检查与 kind 无关（`sql/0020_p08_four_seam_enforcement.sql:203-206`），且 P10 的 checkpoint 先例已证明宿主客户端能以 NULL step_name 追加 `run/yield`。

**修正**：把 :198 括注改为「host prior art: `tests/test_p10_host_sql_seam.py:426-437` 经 `checkpoint` 的宿主 `run/yield` 追加；P11 是首个 scoped（P08）`run/yield`」。顺带把 decision 3 rationale（计划 :548）的「P10 already emits host `run/yield` events in fencing tests」钉到具体测试与动词（`checkpoint`，`test_p10_checkpoint_and_scoped_append_are_claim_fenced`），避免后人按「scoped append 先例」去查。

### P2-2. `sql/0001_p01_claim.sql` 四处行号漂移（引用对象正确，仅行号偏）

- 计划 :319「`UNIQUE (run_id)`, `sql/0001_p01_claim.sql:22`」——实际在 :21（:22 是 `jobs_claim_token_key`）。
- 计划 :386「`release_stale`（`sql/0001_p01_claim.sql:64-107`）」——函数体实际 :64-115（:107 是 UPDATE 列表中间的 `result = NULL,`）。
- 计划 :286 与 :386「invoked … (`:140`)」——`PERFORM cordis.release_stale(p_run_id, 100);` 实际在 :144（:140 是 `p_lease_seconds` 校验的 RAISE 行）。
- 计划 :400「targeted claims filter by exact `run_id` (`:148-152`)」——`AND (p_run_id IS NULL OR run_id = p_run_id)` 实际在 :153。

**修正**：四处行号按上值改。同文件其余引用（`claim_job` :117-170、claim 字段 CHECK :27-38、DDL 内 UNIQUE 落于 :3-22 区间内）准确，无需动。

### P2-3. 文首 Status/Involvement 与 §Mid-flow lock 自相矛盾

计划 :9「Status: **draft — pending mid-flow checkpoint and plan-critique fold**」与 :18「Involvement: Mid-flow (user checkpoint after this draft, before design critique)」都说 mid-flow checkpoint 尚未发生；但 :348-357 明确记录四条锁已于 2026-08-25 与用户锁定（Phase 5 checkpoint）。读者无法从文首判断还剩哪道闸。

**修正**：fold 本 critique 时把文首改为「pending plan-critique fold」（mid-flow 已完成），并在 P0/P1 折完后按 AGENTS.md 把 Status 翻到 `ready to implement`。本 critique 无 P0/P1，翻页条件即「P2 顺手改完」。

### P2-4. 两文均未写明一条承重假设：yield / stale-release 之后下一跳能**立即**重领

P11 的串行相位推进（A→B→C 及两个方向的 takeover）每一步都隐含「上一个动作把行释放后，下一次 targeted `claim_job` 立刻能选中它」。这取决于 `available_at` 语义，而导出与计划都未列入 §Outstanding concerns 的基线验证清单。本次评审已核实当前代码安全：`yield_claim` 置 `available_at = clock_timestamp()`（`sql/0001_p01_claim.sql:210`）、`release_stale` 置 `available_at = t0`（:101）、`claim_job` 过滤 `available_at <= t_claim`（:152）——两条路径都立即可重领，且 P01 的 `test_stale_reap_and_auto_claim`（`tests/test_p01_claim.py:338-401`）已证明同语句内 reap+重领。

**修正**：在 §Outstanding concerns 的验证清单加第 7 条：「`yield_claim` 与 `release_stale` 仍把 `available_at` 置为当前时间（不引入退避），使下一次 targeted claim 立即可见该行。」防止未来 P01/P04 引入 yield 退避时静默打破 P11 的串行设计。纯文档补句，不改任何设计。

## 需要用户/实现前拍板的问题

无。四条 P2 均为文档级修正（两处错误定性、四处行号、一处文首状态、一条补句），不改事件 kind、测试拓扑、stale 机制或文件清单——按计划 §Plan-critique fold 的规则，直接折进计划即可，无需重审。
