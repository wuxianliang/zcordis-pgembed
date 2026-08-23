# P00 计划审查：对照导出基线与代码定点核查

Date: 2026-08-23
Reviewed plan: `docs/plans/P00-sql-source-2026-08-23.md`
Baseline: `prompt-exports/oracle-plan-2026-08-23-155824-p00-sql-tree-deep-pl-bc76.md`（第 104 行 `# P00: Canonical SQL source tree and apply path` 起为计划正文）
Folded answers (not reopened): Q1 dedicated schema；Q2 `da_agent` / `cordis_p00` 分库共 PGDATA；Q3 本仓新增 `pyproject.toml`（覆盖导出的"借 pg-agent uv"默认）。

实现注：Q1 的 SQL schema 是 **`cordis`**，不是 `pg_cordis`（PostgreSQL 保留 `pg_` 前缀）。

## 范围与方法

逐节对照计划与导出正文；对承重引用做了定点核查（未做广域探索）：

- `pg-agent/pyproject.toml`（Q3 镜像值来源）
- `pgembed/src/pgembed/postgres_server.py:245-246, 465-468, 471-481, 560-579`（`get_uri` / `psql()` / cleanup 生命周期 / `get_server` 签名）
- `pgembed/src/pgembed/utils.py:100-106`（URI 构造）
- `pgembed/src/pgembed/_commands.py:18` 与 `__init__.py:19`（`POSTGRES_BIN_PATH` 包级导出，确认）
- `pgembed/tests/test_bundled_tools.py:52`（bundled PG major = 18，`DROP DATABASE … WITH (FORCE)` 无版本风险）

总体结论：计划对导出的保真度高，Q3 覆盖的改写基本完整。以下为需要修正或定死的点，按类别列出。

## 发现

### 1. 导出中有、计划中缺失或弱化的实现承重内容

**1.1 权限/授权边界被弱化。** 导出 §Component 2 "Ownership and lifecycle"（398-402 行）明确：apply 命令不创建专用角色、不 `GRANT USAGE`、不 `ALTER DEFAULT PRIVILEGES`，权限管理推迟到后续 kernel/grant 工作。计划 Component 2 只保留了"不改既有 schema 的所有权/ACL"和 must-not-create 列表里的 "roles"。丢失的是对 `0000_kernel.sql` 内容的正向禁令（不得含任何 GRANT）与"推迟"声明——没有它，W00 评审可能顺手加 `GRANT USAGE ON SCHEMA pg_cordis`。建议在 Component 2 恢复一句。

**1.2 历史文件编辑政策丢失。** 导出 703 行："An edited historical file is replayed if it remains valid, but historical-file edits are not the intended release mechanism; future changes should append a new numbered file." 计划仅保留"删除源文件不删对象"（Component 4）。这条 append-only 发布政策是 `sql/README.md` 贡献规则的一部分（W00 done-when 要求 README 记录贡献契约），应恢复进 Component 1 的 "Rules for later Pxx files" 与 README 内容清单。

**1.3 创建竞态的失败分支省略。** 导出 492-497 行的竞态处理含 else 分支"otherwise report the original failure"；计划只写"already exists 则复查 `pg_database`，存在才继续"。小，但实现时该分支需要存在（复查后仍不存在 → exit 1 报原始错误）。

**1.4 验证 5 的断言弱化。** 导出（1117 行）要求测试检查"校验失败时目标数据库未被创建"；计划验证 5 只写"no target mutation"。建议 W02 明确断言：无效树用例执行后 `pg_database` 中不存在目标库。

**1.5 "任意目录可运行"属性（Q3 覆盖检查）。** 导出的运行形式 `uv run --project "$PG_AGENT_ROOT" …` 从任意目录可用；计划所有命令都要求 `cd "$CORDIS_ROOT"`。自有工程下等价形式是 `uv run --project "$CORDIS_ROOT" python tools/apply_pg_cordis.py …`，建议 README 附注该形式。**除此之外，Q3 覆盖没有丢掉导出的其他要求**：导出硬约束"不提供打包 Python 发行版"已正确改写为"最小 uv 工程、非发布包"；W02 运行环境、pytest 提供方式、风险段均已相应更新（但 pytest 的提供方式本身有问题，见 4.1）。

（导出 128 行的 "COMMENT JSON remains a later plugin-registration extension point" 背景句被丢弃——非 P00 承重，不算缺陷。）

### 2–3. 未定死的接缝、代码反证与错误引用

**2.1 数据库名大小写折叠冲突（导出与计划共有的缺陷，需精确修正）。** 两文档的校验正则均为 `[A-Za-z_][A-Za-z0-9_]*`，允许大写。若传 `--database Cordis_P00`：

- 未加引号的 `CREATE DATABASE Cordis_P00` 被 PostgreSQL 折叠为 `cordis_p00`；
- 而 `server.get_uri("Cordis_P00")` 把库名原样写入 URI（`pgembed/src/pgembed/utils.py:100-106`），连接 `Cordis_P00` 失败；
- `pg_database.datname` 的字面比较同样不匹配。

CREATE、URI、存在性查询三处语义不一致。**修正：把正则收紧为 `[a-z_][a-z0-9_]*`（小写专用）**，`template0`/`template1`/`postgres` 特判随之天然一致；备选方案（三处统一加引号并保留大小写）复杂且无收益。此修正需同步落到计划 Component 3 与 `sql/README.md`。

**2.2 "共享 postmaster"表述被代码反证。** `get_server` 默认 `cleanup_mode="stop"`（`postgres_server.py:560-579`），最后一个进程句柄退出即停 postmaster（`postgres_server.py:465-468`）。W03 的流程是先跑 `setup_db.py`（进程退出 → postmaster 停机），再跑 apply（重新启动）。因此计划 Component 5 的"so both databases share a postmaster"只在并发持有句柄时成立；顺序命令共享的是 **同一 PGDATA/catalog**，不是同一个 postmaster 进程。**修正措辞为"共享同一 PGDATA（同一实例目录与 catalog）"**；组合性证明不受影响，无需为 P00 增加并发共存用例（那是范围扩张）。附带影响：W02 以子进程逐次调 CLI 时每次都会 start/stop postmaster，测试变慢但正确，值得在计划注一句预期。

**2.3 pg-agent pyproject 引用行号错误；镜像值本身全部核实正确。** 计划引用 "pg-agent `pyproject.toml:6-16`"，实际文件共 15 行（pgembed 依赖在第 7 行，`[tool.uv.sources]` 在 14-15 行），应改为 `pyproject.toml:5-15`。已核实：`requires-python = ">=3.12"`、`pgembed>=0.3.0rc1`、`[tool.uv] prerelease = "allow"`、`pgembed = { path = "../pgembed", editable = true }` 均与计划一致。pg-agent 另带 `psycopg2-binary`，计划明确不带——与"apply 走 bundled psql"一致，正确。

**2.4 pgembed 引用确认（无需修改，记录备查）。** `PostgresServer.psql()` 在 `postgres_server.py:471-481`，调用 `self.get_uri()` 无库参数（默认落到 `postgres`，因 `utils.py:102-103` database 为 None 时取 user 值）——计划引用正确，导出的 "~469" 略偏。`PostgresServer.get_uri(database=None)`（245-246 行）单参即库名，`get_uri("postgres")` 作 admin URI 的用法成立。连接用户固定为 `postgres`、空密码——计划可顺带注明，这排除了"以其他角色执行"的路径，与外来所有权错误处理（exit 1）相关。`pgembed.POSTGRES_BIN_PATH` 包级导出确认。

### 4. 两文档皆缺的要求与边界

**4.1 pytest 的提供方式（Q3 引入，实质性）。** 计划写"Dev/test extra: pytest"。若做成 `[project.optional-dependencies]` 的 extra，`uv run pytest` **默认不安装 extra**，W02 done-when（`uv run pytest` 可用）不成立。**修正：用 `[dependency-groups] dev = ["pytest"]`**（uv sync/run 默认包含 dev 组）。

**4.2 虚拟工程声明缺失（Q3 引入）。** 计划说"importable package not required"，则 pyproject 不应带 `[build-system]`；建议明示 `[tool.uv] package = false`（或写明省略 build-system），否则部分 uv 版本会尝试构建本项目而失败（`tools/` 不是包）。

**4.3 测试执行机制未定。** W02 的 exit-2 校验与 rollback 用例最自然通过子进程调 CLI 断言退出码；若要直接单测 `discover_sql_files` 则需可导入，而 `tools/` 不是包。计划应二选一定死：**建议测试统一以 `subprocess`（`sys.executable` + 脚本路径）调 CLI，断言退出码与输出**，不导入脚本，避免实现时临时发明 sys.path 注入。

**4.4 advisory lock 键未定。** 两文档都只说"stable `pg_cordis` apply-lock key"，未给常量与形态（`pg_advisory_xact_lock(bigint)` 单参 vs 双 int32）。建议计划定死一个常量（如 `pg_advisory_xact_lock(hashtext('pg_cordis_apply'))` 或固定 bigint 字面量），并写明锁加在**目标库连接内**（advisory lock 按库隔离，两文档隐含但未言明）。

**4.5 锁等待无超时。** 并发 in-place apply 的第二个进程会无限阻塞在 advisory lock 上。P00 单机开发可接受，但计划应记一句已知行为，避免测试意外并发时 CI 挂死。低优先。

**4.6 `.gitignore` 遗漏 `.venv/`（Q3 后果）。** 计划 file impact 只提 `.pgdata/`；自有 uv 工程会生成 `.venv/`。一行修正。

**4.7 psql 元命令禁令无执行点。** 计划规定源文件不得含 `\connect`、`\include` 等，但文件名校验不看内容，验证 8 的 grep 也不扫元命令。最低成本修正：在验证 8 增加一个 `^\s*\\` 的 grep 模式（命中即失败）。是否让 `discover_sql_files` 做内容扫描可留给实现，但至少验证矩阵应覆盖。

**4.8 遗留测试库无清理约定。** 验证 4/6 会在共享 pgdata 留下 `cordis_p00_probe` 等库。低优先；注明"测试库允许残留"或让测试自清理即可。

### 5. 会实质影响设计或实现顺序的问题

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q-A | 数据库名是否收紧为小写专用（2.1）？ | W01 校验逻辑 + README 语法 | 直接采纳小写专用，不必等待 |
| Q-B | pytest 走 dependency-group 还是 extra（4.1）？ | pyproject 形状 + W02 命令是否成立 | dependency-group |
| Q-C | 测试子进程调 CLI 还是导入函数（4.3）？ | W02 结构、是否需要把工程做成包 | 子进程 |
| Q-D | W03 接受"共享 PGDATA、顺序执行"还是要求同 postmaster 并发共存（2.2）？ | W03 done-when 措辞 | 接受前者，改措辞；并发共存推迟到 P01 后评估 |
| Q-E | advisory lock 常量定成什么（4.4）？ | 实现细节，不阻塞顺序 | 实现前在计划中定死 |

## 建议（按优先级）

1. **必须改（会导致实现错误或 done-when 不成立）**：2.1 小写专用正则；4.1 `[dependency-groups] dev`；2.2 W03 "共享 postmaster" → "共享 PGDATA"。
2. **应该改（防止实现走偏）**：1.1 恢复无 GRANT/无角色/权限推迟声明；1.2 恢复 append-only 历史文件政策；4.2 `package = false`；4.3 定死子进程测试机制；4.4 定死锁常量与"锁在目标库连接内"。
3. **顺手改（低成本）**：2.3 引用行号 `pyproject.toml:5-15`；1.3 竞态 else 分支；1.4 验证 5 明确"库未创建"断言；1.5 README 附 `uv run --project` 形式；4.6 `.gitignore` 加 `.venv/`；4.7 验证 8 加元命令 grep；4.5/4.8 各记一句已知行为。

无需改动的确认项：pgembed 为 PG 18，`DROP DATABASE … WITH (FORCE)` 无版本风险；`get_uri` / `psql()` / `POSTGRES_BIN_PATH` 的计划引用与用法经代码核实成立；Q3 覆盖除上述 pytest/虚拟工程/ignore 三个衍生项外未丢导出要求。
