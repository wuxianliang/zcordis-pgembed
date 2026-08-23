# P01 计划评审 — 对照 Oracle 导出基线与已落地代码

Date: 2026-08-23
Scope: `docs/plans/P01-jobs-claim-2026-08-23.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-23-171951-p01-claim-protocol-d-cc88.md` 的生成计划正文（`# P01 — cordis.jobs Upgrade and Dual-Locus Claim Protocol` 起），并对承重引用做了代码定点核对（`tools/apply_pg_cordis.py`、`tests/test_p00_sql_source.py`、`sql/0000_kernel.sql`、`pg-agent/v2/pg_agent_functional.sql:460-494`、pgembed 版本）。

已定事项（schema、动词集、UNIQUE(run_id)、90s、`clock_timestamp()`、fail 恒终态、测试拆分、无 enqueue、P00 测试重定向）未重开。

## 结论摘要

现行计划是导出基线的忠实超集：逐节比对未发现实现承重内容被删除或泛化；两个中途决定（`tests/test_p01_claim.py` + `tests/conftest.py` 拆分、不做 enqueue）已正确折叠，且 conftest 抽取满足了导出"不得复制测试基础设施"的底层关切。计划"Baseline corrections" 声称修正的行号已逐一核实为准确（导出的行号确实过期）。

但存在一个两份文档都断言错误、代码可直接证伪的**阻塞点**（发现 1），以及若干会在 W13 落地时才暴露的欠规格缝隙。

---

## 发现

### 1.（阻塞）preflight 事务控制正则会拒绝标准 plpgsql 函数体 — 两份文档均未覆盖

计划与导出都断言"loader 不改、新 SQL 通过现有 preflight"（计划 `tools/apply_pg_cordis.py — unchanged` 一节；导出 Component 8/9）。代码证伪：

```31:34:tools/apply_pg_cordis.py
    re.compile(
        r"(?:^|;)\s*(BEGIN|COMMIT|ROLLBACK|END|START\s+TRANSACTION)\s*;",
        re.I | re.M,
    ),
```

- `strip_sql_comments`（`tools/apply_pg_cordis.py:83-90`）只剥离注释，**不理解 dollar-quoting**，函数体会被整体扫描。
- 在 `re.M` 下，行首或分号后的 `END;` 命中 `(?:^|;)\s*END\s*;`。而计划规定六个动词全部 `LANGUAGE plpgsql`（Function packaging 节），常规写法的块终结符正是行首 `END;`（对照 pg-agent 同形态：`pg_agent_functional.sql:461`、`:493`）。
- 结果：`0001_p01_claim.sql` 按计划写出后，`preflight_sql` 直接 exit 2，apply 根本到不了数据库。P00 现有探针测试之所以没暴露，是因为探针函数全用 `LANGUAGE sql` 单表达式（`tests/test_p00_sql_source.py:148-151`、`:251-254`）。

计划的实施顺序把"loader 接受该文件"的冒烟放在第 6 步——这是一个会在第 6 步才被发现的第 1 步阻塞。必须在 W10 之前显式决策，二选一：

- **方案 A（不动 loader）**：立一条 house 规则——plpgsql 外层块的收尾 `END` 不带分号（`END$$;` 或 `END` 换行后接 `$$;` 均不命中正则），且 P01 动词体内不使用裸 `BEGIN…END;` 子块（`END IF;`/`END LOOP;` 本就不命中）。脆弱点：未来任何编辑者顺手补一个分号即破坏 apply；若采纳，建议在重定向后的 tree-scan 测试里加一条 `;`/行首 `END;` 的守卫断言，把风格规则固化为测试。
- **方案 B（最小 loader 修改）**：让 `strip_sql_comments`（或一个新的 strip 步骤）在扫描 `FORBIDDEN_STMTS` 前剥离 dollar-quoted 区段。语义上更诚实（现正则对任何含 plpgsql 的树都过粗），但触碰计划"loader 不改"的承诺行，需要同步：更新计划 `tools/apply_pg_cordis.py` 一节、保留裸 `BEGIN;`/`COMMIT;` 仍被拒的既有测试语义、并在 invalid-tree 参数化里加"dollar-quote 内的 BEGIN; 不误伤 / quote 外的仍拒绝"用例。

倾向方案 B：方案 A 把一个 loader 缺陷固化为永久书写约束，且 P02+（更复杂的 plpgsql）会反复撞上。但这改动"signed"边界，应由所有者拍板，不应由实现者在第 6 步临场决定。

### 2.（高）两连接互斥测试无法用现有 psql helper 实现 — 计划未给出机制

计划 W13/测试 2 要求"hold A's claim transaction open"期间由 B 发起 claim。但计划指定沿用的 harness 是一次性子进程：

```33:49:tests/test_p00_sql_source.py
def psql(server, database: str, sql: str, *extra: str) -> str:
    args = [
        str(POSTGRES_BIN_PATH / "psql"),
        server.get_uri(database),
        ...
    ]
    proc = subprocess.run(args, input=sql.encode(), capture_output=True, check=False)
```

`subprocess.run` 输入即关闭 stdin，事务无法跨越两次调用存活。旗舰 done-when 证明依赖这一能力，计划却只说"two separate psql subprocesses/connections"。conftest 规格需要补一个会话式 helper：`subprocess.Popen` 打开 psql、stdin 管道分步写入 `BEGIN; SELECT cordis.claim_job(...);`（读回 token）→ 令 B 走一次性 helper → 再向 A 写 `COMMIT;`。不要用 `pg_sleep` 定时背景法（计时脆弱）。这不扩大范围——是把 W13 已承诺的测试补到可实现。

### 3.（中）CHECK/UNIQUE 约束未命名 — 目录测试与后续迁移都需要稳定名字

计划给了两个索引名（`jobs_ready_idx`、`jobs_stale_claim_idx`），但五条约束（status、attempt、claim 字段 ↔ RUNNING、claimed_by 非空白、terminal ↔ completed_at）与两条 UNIQUE 都未命名：

- 目录契约测试要"assert 约束存在"，无名则只能按 `pg_constraint.conname` 的自动命名猜测，断言脆弱。
- 状态集演化（P03/P04 或未来 CANCELLED，见发现 7）只能走 `ALTER TABLE ... DROP CONSTRAINT IF EXISTS <name> / ADD CONSTRAINT <name>`，无稳定名即无法在后续编号文件中做可重放迁移。

修正：在 Component 1 显式命名，如 `jobs_status_check`、`jobs_attempt_check`、`jobs_claim_fields_check`、`jobs_claimed_by_nonblank_check`、`jobs_terminal_time_check`、`jobs_run_id_key`、`jobs_claim_token_key`。

### 4.（中）索引的重放安全未写明

表用 `CREATE TABLE IF NOT EXISTS`（重放时跳过，内联约束随之覆盖），但两个分部索引若写成裸 `CREATE INDEX`，第二次 in-place apply 会报 "already exists" → 整树事务回滚 → exit 1，直接违反计划自己的重放验收（Verification 7）。修正：明确 `CREATE INDEX IF NOT EXISTS`。（`CREATE OR REPLACE FUNCTION` 侧已覆盖。）

### 5.（中）forbidden-tokens 测试的"保留"清单与现状不符；新增事务控制扫描会撞上发现 1

计划（承自导出）要求重定向后的 `test_sql_tree_has_no_forbidden_tokens` "keep `CREATE EXTENSION`、psql 元命令、`GRANT`/`REVOKE`、database DDL、transaction-control、`CREATE SCHEMA absurd`"。实际现测试（`tests/test_p00_sql_source.py:291-301`）只查四样：`CREATE EXTENSION`、`CREATE TABLE`、行首 `GRANT`、行首反斜杠。REVOKE / database DDL / 事务控制 / absurd 检查**并不存在**——这些是新增，不是保留。两点修正：

- 措辞改为"扩展到与 preflight 契约对齐"，避免实现者去找不存在的断言。
- 若新增事务控制逐行扫描，`END;` 会在产品 plpgsql 上误报——该测试的实现必须与发现 1 的决策绑定（方案 A → 守卫风格规则；方案 B → 复用 dollar-quote 感知的剥离逻辑）。

### 6.（低）对照结论：计划相对导出无实质缺失；行号修正核实为真

- 逐节比对：Summary/Goal/执行索引/决策表/DDL 列契约/六动词算法/乱序矩阵/风险/实施顺序/验证矩阵均完整保留或加严（新增 Function packaging、enum 拒绝理由等）。唯一被丢弃的导出内容是第 9 步的"先全量后按测试名过滤迭代"提示——无实现影响。
- 计划 Baseline corrections 声称的修正逐一核实：loader 引用（`:17`、`:21-35`、`:44-81`、`:93-107`、`:202-208`、`:211-242`）、测试引用（`:57-111`、`:143-165`、`:168-184`、`:248-278`、`:291-301`、`:311-373`）与代码一致，导出的对应行号（`:49-100`、`:39-81`、`:83-105`、`:183-189`、`:191-222` 等）确实过期；`sql/0000_kernel.sql:7-14` 确为 `LANGUAGE sql IMMUTABLE SECURITY INVOKER`，计划补充的函数属性规格有代码依据；pg-agent claim 引用 `:472-476` 成立。
- 佐证一个计划前提：pgembed 捆绑 PostgreSQL 18.4（`pgembed/pgbuild/Makefile:53`），`gen_random_uuid()` 为内建（≥13），无需任何 extension——与"no CREATE EXTENSION"契约相容。

### 7.（两份文档均缺）取消路径与状态集演化空间

状态机没有任何 PENDING → 终态的边：要终止一个排队中的 run，唯一途径是先 claim 再 fail_claim（占用一次 lease 周期并递增语义混淆）。RUNNING 中的 run 也无外部强停原语。D4 五件套不含 cancel，P01 不实现是对的；问题在于 CHECK 硬编码六个状态值，而两份文档都未指认 cancel 的归属阶段，也未说明后续编号文件如何可重放地扩展该 CHECK。这正是发现 3（约束命名）的直接理由：命名后，未来任何状态集变更都是一条 `DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT` 的标准迁移。建议在计划风险节补一行"cancel 未分配，状态 CHECK 以命名约束预留迁移路径"，不新增任何 P01 行为。

### 8.（低）零散精确性问题

- `claim_expires_at = t + p_lease_seconds`：integer 不能直接与 timestamptz 相加，实现须写 `t + make_interval(secs => p_lease_seconds)` 或 `p_lease_seconds * interval '1 second'`。计划其余处极精确，此处宜补一笔以免实现分叉。
- Verification 11 的示意数据库名 `cordis_p01` 与 File-by-file 节"fixture 名可保留 `cordis_p00_comp`"并存——不算矛盾，但实现者可能误读为要求改名；建议统一措辞。
- 计划引用 invalid-tree 为 `:200-246`，参数化装饰器实际起于 `:186`；纯余量问题，不影响实现。

---

## 问题（答案会实质改变设计或顺序）

1. **发现 1 选 A 还是 B？** 这决定 W10 能否按"loader 不改"落地，且改变实施顺序：若选 B，loader 修改与其 preflight 测试必须先于（或伴随）`0001` 落地；若选 A，风格规则与守卫断言要写进计划正文。当前顺序把冒烟放第 6 步，无论哪个方案都应把"apply 接受含 plpgsql 的 0001"提前到首个函数写完立即验证。
2. **cancel 归属哪一期？** 若答案是"某期会加 CANCELLED 状态"，P01 就必须命名约束（发现 3 从建议升级为必需）并可考虑现在把值加进 CHECK（同 WAITING/SLEEPING 的预留逻辑）；若答案是"terminal ERROR 即取消语义"，风险节记录一行即可。
3. **重定向后的 tree-scan 测试可否 import loader 的 `strip_sql_comments`/`FORBIDDEN_STMTS` 求一致性？** 计划 conftest 节写了笼统的"Do not import `apply_pg_cordis.py` as a package"（本意针对 apply 执行路径必须走 subprocess）。若禁令按字面覆盖 token 测试，就得复制正则并承担漂移风险；若放行只读 import，测试与 preflight 永久同步。建议澄清禁令边界。
4. **`tests/test_p01_claim.py` 的会话式 psql helper（发现 2）是否进入 conftest 共享面？** 若 P02+ 的并发测试也要用，现在放 conftest；若仅 P01 用，留在模块内。影响 conftest 的抽取清单。

## 建议的计划修订清单（最小集）

1. 在 Design 增加"loader 兼容性"小节，落发现 1 的决策（推荐 B，或 A + 守卫测试），并把 apply 冒烟提前至实施顺序第 2-3 步之间。
2. Component 1 为全部约束与 UNIQUE 命名；索引改写为 `CREATE INDEX IF NOT EXISTS`。
3. W13/conftest 节补会话式 `psql_session`（Popen）helper 规格。
4. forbidden-tokens 测试一节把"keep"改为"extend 至 preflight 契约"，并注明扫描实现与发现 1 决策的耦合。
5. 风险节补 cancel 未分配 + 状态 CHECK 迁移路径一行；`make_interval` 一笔。
