# P06 计划评审 — 对照 Oracle 导出基线与已落地代码

Date: 2026-08-23
Scope: `docs/plans/P06-plugin-catalog-2026-08-23.md`（现行计划）对照 `prompt-exports/oracle-plan-2026-08-23-174556-p06-plugin-catalog-d-42f5.md` 的生成计划正文（`# P06 — 插件目录：Implementation-Ready Deep Plan` 起），并对承重引用做了代码定点核对（`tools/apply_pg_cordis.py`、`tests/test_p00_sql_source.py`、`sql/0000_kernel.sql`、`sql/README.md`、`pg-agent/v2/pg_agent_functional.sql:303-327`、`pg-agent/v2/pg_agent_workbench_core.sql:1-28`、`docs/plans/P01-jobs-claim-2026-08-23.md:738-746`）。

已定事项未重开：host 授权路径（`host_plugin_definitions` + `register_host_plugin(jsonb)`、无 stub 函数、不直插编译表）、`invocation` 含 `session_select`、`required_grants` 仅存种类（有意替换导出的 D5 全字面量，P07 签发具体 ID）、effect/retry/reconciliation 交叉 CHECK 矩阵。

## 结论摘要

现行计划是导出基线的忠实收敛：逐节比对未发现实现承重内容被意外删除；仅存种类的 grant 决定折叠一致（导出第 9–10 步的 `named_corpus:<id>` 语法与无效注册用例 `named_corpus:`，计划均按种类制正确改写为拒绝一切冒号字面量）。计划对导出"loader 不改"的修正**已按用户要求对照当前代码确认成立**（发现 3.1）。

需要处理的问题：一处两份文档共同的、代码可证伪的先例事实错误（3.3）；一个两份文档都未讨论、有更简单替代的设计点（`TRUNCATE` → `DELETE`，4.1）；刷新失败的"污染半径"未被任何一方写成运营事实（4.2）；以及若干会在 W61/W62/W66 落地时暴露的欠规格缝隙（第 2 节）。

---

## 1. 导出内容在计划中缺失或弱化

逐节比对后仅两处，均低危：

### 1.1（低）"不依赖常驻 postmaster"测试守则被丢弃

导出 Verification 12 有一条"no test relies on a permanently running postmaster between sequential CLI subprocesses"，计划的 Full suite（§12）没有保留。这是给 W66 测试作者的行为约束（子进程间不得假设服务器存活），一句话即可恢复。

### 1.2（低）`v2/setup_db.py` 的部署时计数闸门未被显式弃用

导出 Reuse 列表含 "`v2/setup_db.py` 的 apply-time refresh/count-gate idea"；计划只保留了 apply 末尾 `SELECT cordis.refresh_plugins();`，计数闸门（部署后断言编译行数符合预期）消失且未说明。纯 SQL 末句确实无法自断言返回值，弃用合理，但计划应写一句"计数闸门由 W66 测试承担"（另见 4.4：现有命名测试也没断言返回值）。

其余抽查均为保真或有意改写：确定性扫描顺序、缺省值表、mutex 规则、validate-before-rebuild 步骤、psql 调用细节（计划折叠为"沿用现有 psql helper"，`tests/test_p00_sql_source.py:33-49` 确认该 helper 存在且形态一致）、导出校验第 8 步的措辞混淆（"host_registration must be host_tool" 把 locus 与 invocation 混为一谈）计划已改正为 `host` + `host_tool`。

---

## 2. 欠规格缝隙、含糊归属与引用瑕疵

### 2.1（高）dollar-quote 剥离的必要性被低估：不止 `END;`，还有 `\bGRANT\b`

计划把 loader 缺口只归因于事务控制正则（`apply_pg_cordis.py:31-34`）。但 `FORBIDDEN_STMTS` 还包括：

```26:27:tools/apply_pg_cordis.py
    re.compile(r"\bGRANT\b", re.I),
    re.compile(r"\bREVOKE\b", re.I),
```

这两条对**整份文件**任意位置的单词生效。P06 的 plpgsql 校验器几乎必然在报错字符串里写 "grant"（如 `'invalid required grant kind'`）——没有 W09 剥离时，`0006` 会在 `END;` 之外再撞多个模式；有剥离后，dollar-quote **体外**的任何含该词文本（如未来某条纯 SQL `COMMENT ON ... IS '... grant ...'`）仍会误伤。（`required_grants` 标识符因 `\b` 前后均为词字符而安全。）

修正：W65/README 补一条书写规则——`0006` 中含 GRANT/REVOKE/BEGIN/END 等敏感词的自然语言文本只能出现在 dollar-quote 体内或 SQL 注释内。这不是扩大范围，是把"为什么必须有 W09"的完整依据写实，避免实现者以为只需绕开 `END;`。

### 2.2（中）`name` 与 `session_scope` 的长度/语法上限两份文档均未给出

校验器第 6 步声称检查 "version / name / description / session_scope 的长度与控制字符"，但全文只给了 identity ≤128 字节、version 1–64 字节、description ≤500 字符；`name` 和 `session_scope` 没有任何数字或语法。W61 的 done-when（"rejects … shapes"）与 W66 测试无法据此写出。需要在 Component 2 补上两个上限（并说明 `session_scope` 是自由文本还是标识符语法）。

### 2.3（中）description/name 规则的归属面未声明

编译表的 Checks 清单（1–8 条）不含 description ≤500/无控制字符——该规则只出现在列含义栏和校验器第 6 步。由于 `refresh_plugins()` 是唯一写入方，validator-only 是成立的，但 W60 的 done-when 说"exact columns/CHECKs"，实现者无从判断这条要不要落成表级 CHECK。应逐条声明：哪些规则是表 CHECK（矩阵、枚举、grant 子集、source_kind↔entrypoint），哪些仅在校验器（长度、控制字符、重复 grant、冒号字面量）。

### 2.4（中）refresh 阶段错误的 SQLSTATE/报文形态未定

校验器定了 SQLSTATE `22023`，但 refresh 自身的错误——坏 JSON、重复 identity、legacy mutex、entrypoint 检查失败——没有指定错误码或稳定报文片段。W66 的验证 5/6 只写"refresh error in output"/"JSON parse error"，测试将被迫匹配 PostgreSQL 内部 cast 报文（跨版本脆弱）。建议统一：refresh 内所有候选级失败都 `RAISE ... USING ERRCODE='22023'` 并带 `identity`/函数签名上下文，测试匹配自定义片段。

### 2.5（中）`prokind <> 'f'` 且带 `cordis_plugin` 注释：报错还是无声排除？

两份文档都只说 refresh "要求 `pg_proc.prokind='f'`"。若这是扫描谓词（`WHERE prokind='f'`），那么一个误写成 `CREATE PROCEDURE` 的插件会**无声消失**——与全文 fail-closed 姿态矛盾；若是候选级校验，则应报错。建议明确为后者：扫描全部 `cordis` `pg_proc` 行，凡携带 `cordis_plugin` 而 `prokind<>'f'` 的报错，并加一条 W66 用例。

### 2.6（低）upsert 必须保留 `registered_at` 未写入 register 步骤

列定义说 `registered_at` = "First insert"，但 Component 4 的五步流程没说 `ON CONFLICT DO UPDATE` 只更新 `metadata`/`updated_at`。一句话补齐，否则实现者可能整行覆盖。

### 2.7（引用瑕疵，极低）

- 计划引 `sql/README.md:16` 说明"gaps allowed"，实际在第 17 行（16 行是 `0000_kernel.sql is required`）。
- Execution index 的 W65 行 Key files 漏 `sql/README.md`，详细 W65 又包含它——两处应一致。

其余承重行号全部核实准确：`apply_pg_cordis.py:17`、`:21-35`、`:30`、`:31-34`、`:44-80`、`:48-54`、`:93-106`、`:109-122`、`:202-208`、`:203`、`:211-242`；`tests/test_p00_sql_source.py:57-111`、`:143-165`、`:291-301`、`:311-333`、`:333`；`sql/0000_kernel.sql:5-14`；`sql/README.md:41-45`；`P01-jobs-claim-2026-08-23.md:738-746`。计划所述落地状态（`sql/` 仅 `0000_kernel.sql`、无 `tests/conftest.py`、无 `tests/test_p01_claim.py`）与当前树一致。

---

## 3. 代码证伪 / 已确认的修正

### 3.1（确认）loader 修正成立：当前预检没有 dollar-quote 剥离，`END;` 必然拒绝 `0006`

按要求对照当前 `tools/apply_pg_cordis.py` 确认，不再重推导：

```31:34:tools/apply_pg_cordis.py
    re.compile(
        r"(?:^|;)\s*(BEGIN|COMMIT|ROLLBACK|END|START\s+TRANSACTION)\s*;",
        re.I | re.M,
    ),
```

`strip_sql_comments`（`:83-90`）只剥注释；plpgsql 收尾的行首 `END;` 命中正则 → exit 2。导出 "No loader changes" 一节被证伪；计划 W65 的条件补丁（与 P01 W09 同一份剥离）是正确且必要的修正。同时核实：`--sql-root` 参数存在（`:249-253`），预检失败 exit 2、SQL 失败 exit 1（`:171`、`:103-106`）——验证 5/6/9/10 的退出码期望与代码一致。

### 3.2（确认）导出对 `apply_pg_cordis.py` 的行号已过期，以计划为准

导出引 `:112-128`（preflight）、`:213-253`（verify）、`:44-95`（discovery）；当前文件分别在 `:93-106`、`:211-242`、`:44-80`。计划的行号全部核实准确。实现时不要回引导出的行号。

### 3.3（中，两份文档共同错误）`refresh_handlers` 并非"无声跳过坏 JSON"，而是 TRUNCATE 后 cast 报错

导出与计划（Background "pg-agent precedent" 节）都写 "Malformed JSON silently skipped"。代码证伪：

```314:323:pg-agent/v2/pg_agent_functional.sql
BEGIN
    TRUNCATE handlers;
    INSERT INTO handlers (job_type, fn)
    SELECT obj_description(p.oid, 'pg_proc')::jsonb ->> 'job_handler',
           p.oid::regproc
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND obj_description(p.oid, 'pg_proc') ~ '^\s*\{'
       AND obj_description(p.oid, 'pg_proc')::jsonb ? 'job_handler';
```

`{` 开头但非法的 JSON 会在 `::jsonb` cast 处**抛错**——且发生在 `TRUNCATE` 之后。真正被无声跳过的只是不以 `{` 开头的注释。先例的真实缺陷是"先 truncate 再中途报错"，不是"静默跳过"。此更正不改变 P06 设计（P06 本就先校验后重建、坏 JSON 报错），但该句是设计依据的一部分，记录应准确。

---

## 4. 两份文档均缺失的问题

### 4.1（高，有更简单的替代设计）重建用 `TRUNCATE`：MVCC 不安全、锁级过重、权限过强 — `DELETE` 完全替代

两份文档都指定 `TRUNCATE cordis.plugin_catalog` 后批量插入（承袭 pg-agent 先例），但均未讨论其后果：

- **MVCC 不安全**：PostgreSQL 文档明确 `TRUNCATE` 对并发快照不安全——一个在刷新提交前取快照（REPEATABLE READ 及以上）的事务，之后读目录会看到**空表**而非旧行。"失败保留旧目录"的保证只覆盖回滚路径，成功路径反而可能让并发读者短暂看到零插件。P08/P09/P10 未来都是本表读者。
- **锁级**：`TRUNCATE` 取 ACCESS EXCLUSIVE，阻塞一切读者直至刷新事务结束；apply 场景下即整棵树事务的时长。
- **权限**：`SECURITY INVOKER` 下 `TRUNCATE` 需要表 owner 或 TRUNCATE 权限；`DELETE` 只需 DELETE 权限。v0 单角色无碍，但无必要地收紧了未来调用者的最低权限。

替代：`DELETE FROM cordis.plugin_catalog;` + 批量插入。目录量级是几十行，性能差异为零；MVCC 安全、锁级为 ROW EXCLUSIVE、事务回滚语义与全部既有测试期望（"prior rows survive failure"、同一 `refreshed_at`）不变。建议 W62 直接改词；若坚持 `TRUNCATE`，必须在 Risks 写明 MVCC 告警并声明 v0 无并发读者。

### 4.2（中）刷新失败的"污染半径"未写成运营事实，且缺一条测试

任何 `cordis` 函数只要注释以 `{` 开头且非法（或含双 legacy 键），**所有**后续刷新都会失败——包括每一次 `register_host_plugin`（内部调 refresh）和每一次树 apply（`0006` 末句是 refresh）。fail-closed 是既定选择，但两份文档都没写：一条坏注释会让宿主插件注册与整库 apply 全部瘫痪，唯一恢复路径是修复/删除该注释（无 force/skip 逃生口）。应在 Risks 加一句，并给 W66 补一条用例：无关函数的坏注释导致 `register_host_plugin` 失败且源表/编译表不变（现有测试只覆盖 apply 路径的刷新失败）。

连带的库级书写约束：P06 落地后，`cordis` 内任何函数的散文 COMMENT 都不得以 `{` 开头——这是 P06 新造的全库规则，两份文档的 README 更新条目都没提。

### 4.3（低）锁序不变量未声明

apply 路径持 `pg_cordis.apply` 锁后在末句 refresh 内再取 `pg_cordis.plugin_refresh`；`register_host_plugin` 只取后者。当前无死锁，但这依赖"永远先 apply 后 refresh、无反向路径"的不变量。后续 Px 文件会继续在 apply 事务内调 refresh，建议计划用一句话把锁序写成显式约束，防止未来某工具先取 refresh 锁再触发 apply。另一运营事实可顺带写明：一次长 apply 会阻塞所有并发的宿主注册（等待无超时，可被 cancel/statement_timeout 打断）。

### 4.4（低）无任何测试断言 `refresh_plugins()` 的返回值

接口定义"返回插入的编译行数"，八个命名测试没有一个断言它。在 `test_register_host_plugin_and_select`（期望 1）与 `test_comment_refresh_compiles_cordis_function`（期望含新函数的计数）里各加一个断言即可，顺带落实 1.2 的计数闸门。

---

## 5. 答案会实质改变设计或实现顺序的问题

1. **W62 重建原语**：`TRUNCATE` 还是 `DELETE`（4.1）？决定 W62 函数体、Risks 措辞，及是否需要 MVCC 告警。建议 `DELETE`。
2. **坏 JSON 的候选资格**（4.2）：维持"任何 `{` 开头非法注释 = 全库刷新失败"，还是把候选资格收窄（如仅当文本含 `"cordis_plugin"` 子串才强制解析）？前者半径大但规则简单，后者削弱 legacy-mutex 检出。答案决定 refresh 的扫描谓词与 4.2 的测试形态。倾向维持并写明半径。
3. **`prokind<>'f'` 携带 `cordis_plugin`**（2.5）：报错还是排除？决定扫描谓词与一条测试。
4. **refresh 错误的 SQLSTATE 映射**（2.4）：决定 W66 断言的精确度与跨版本稳定性。
5. **`name`/`session_scope` 上限**（2.2）：决定校验器第 6 步与对应负例测试能否写出。
6. **W09 剥离正则对 `0006` 函数体的充分性**：P01 W09 是单遍非贪婪 `$tag$…$tag$` 剥离（`P01-jobs-claim-2026-08-23.md:742`）。异名嵌套标签可处理，但体内出现裸 `$$` 子串或 `$` 邻接会错配配对。最省事的答案：约束 `0006` 统一用外层 `$$`、体内不嵌套 dollar 标签、字符串中不含相邻 `$$`，并在 README 记一句——即可确认"同一补丁"充分，无需分叉预检设计。

## 建议汇总

- W62：`TRUNCATE` 改 `DELETE`（4.1）；refresh 错误统一 ERRCODE + identity 上下文（2.4）；`prokind` 检查定为候选级报错（2.5）。
- W61：补 `name`/`session_scope` 上限（2.2）；声明规则归属面（2.3）。
- W63：写明 upsert 保留 `registered_at`（2.6）。
- W65/README：dollar-quote 体外敏感词书写规则（2.1）；`{` 开头散文注释禁令（4.2）；`0006` 体内引号约定（问题 6）；锁序不变量一句（4.3）。
- W66：补"无关坏注释阻断 register"用例（4.2）；两处 refresh 返回值断言（4.4）；恢复"不依赖常驻 postmaster"守则（1.1）。
- Background：更正 `refresh_handlers` 先例描述（3.3）；修 README 行号与 W65 key-files 一致性（2.7）。
