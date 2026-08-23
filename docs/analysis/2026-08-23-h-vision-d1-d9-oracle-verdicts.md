# H — 宏观愿景 vs D1–D9：oracle 裁决

Date: 2026-08-23  
Oracle: `prompt-exports/oracle-plan-2026-08-23-150327-untitled-chat-145b87-8ee1.md`（chat `untitled-chat-145B87`）  
输入简报: `docs/analysis/2026-08-23-h-vision-context-for-oracle.md`  
**D1–D9 已由用户全部签名（2026-08-23）。** 见 `docs/decisions/2026-08-23-pending.md`。探索收尾：`docs/analysis/2026-08-23-i-architecture-snapshot.md`。

## 一句话

愿景裁决的九条均已写入 pending「决定」。切片绑定的检索 grant 进 v0。pg-agent 的 `pg_temp` 数据分析路径退役/延期，真正的 DA 插件是以后的 DuckDB 工作台。

## 锁级

| 级 | 含义 |
|----|------|
| `lock_option` | 愿景+证据已选出字母，可当实现基线，仍要你点头再写「决定」 |
| `lock_direction` | 不变量已定，字母或签发人仍要你选 |
| `defer` | 明确分期，禁止偷偷做成另一个选项 |
| `still_user` | 愿景几乎不约束（本轮 **没有** 落到这一档） |

## 九问总表

| ID | 锁级 | 建议拍 | 置信 | 相对 Kimi 表 | 一句话 |
|----|------|--------|------|--------------|--------|
| D1 | **已签名** | **D**（退役 PG-TEMP DA，DuckDB 插件后做） | 0.97 | **改写** 主建议 A | 先做 CE 编码 agent；分析表不进 Postgres |
| D2 | **已签名** | **A+C** | 0.95 | 对齐 | 文件编辑/未来 DuckDB 相对 PG claim 都是非事务 |
| D3 | **已签名** | **B** | 0.92 | 对齐 | `jobs` 调度；`run_waits`/`run_events` 旁表 |
| D4 | **已签名** | **A** 五件套进核 | 0.91 | 对齐 | 审批、子 agent、重试都要等人 |
| D5 | **已签名** | **C** + 模型只能申请；禁止 B/D | — | 先拍 | v0 枚举范围，按 slice 生效；模型不能写 grant |
| D6 | **已签名** | **C** 步数/深度/扇出 | 0.91 | 对齐 | token 池是以后的事；CE 的 token 预算是 context-builder 插件 |
| D7 | **已签名** | **D** SQL 源在本仓 | 0.98 | 对齐 | workspace/context-builder/DuckDB 都是插件，不是各自 EXTENSION |
| D8 | **已签名** | **A** + 最小插件目录 | 0.94 | 对齐并加目录 | 编码 agent **就是** host locus，不能再推迟宿主 |
| D9 | **已签名** | **D** 子 run 一律 enqueue | 0.97 | 从 B/D 收窄到 D | 对齐 prime-agent：`rlm()` 只返回 admission handle |

## 愿景改写了什么

先前 pending 把 D1 写成「Postgres TEMP VIEW 怎么和 yield 共存」。你现在的产品顺序是：

- **先** 做 RepoPrompt-CE 类编码 agent：workspace / context builder / selection / worktree / `apply_edits` 全部是 **pg_cordis 插件**（改旧文件）。
- **后** 做 DuckDB 2.0 数据分析插件（造新表）。InfiniSynapse 逆向和 pg-agent DA SQL 都是探索，不是运行时。
- 两者在 pg_cordis 上协调：同一套 log、claim、grant、spawn、插件目录。
- **CodeAct 为主体**（一步 = 一次 LLM + 它的 tools）；**RLM 来自 prime-agent**（kernel + 异步子 agent），不是同步 `rlm_loop(child)`。
- 独特功能：提示词由 **按切片检索出的片段组合**；「项目 A 做功能 1、项目 B 做功能 2 和 3」不能进同一个 workspace 并集。

因此：

- D1 不再选 A（把分析中间表做成 PG run 级 workspace）。选 **D 的新读法**：PG 只保留协调态（selection、grant、log、lineage）；分析物化在 DuckDB。B/C 亲和会话仍然否决。
- D5 不再「第一版偏 C、可以先不做」。**切片绑定必须进 v0**；run_id 当唯一范围（D5-D）否决；任意 SQL 谓词（B）否决。
- D8 不再可以「只保证库内 worker」：编码 agent 的文件工具在宿主进程，最小 SQL seam **现在就要有**。
- D9 不再保留「很浅仍同步」：prime-agent 的 `await rlm(...)` 从不返回孩子答案。

未找到现成的「DuckDB 2.0 工作台」仓库。本地官方 DuckDB 树是 **v1.5.5 / main**；ghidra 设计稿是 Python + 进程内 DuckDB + SQLite 元数据回放。按你的原话，那是 **要开发的插件**，不是已经落地的运行时。

## D5 已拍（2026-08-23）

- 语法：**C** — `run` / `named_corpus:<id>` / `event:<scope>`。工作例 = 两个 named corpus，绑在不同 slice 上。
- 签发：**模型只能申请**；写入库的是用户或受信宿主/编排器。
- 禁止：B（SQL 谓词）、D（`run_id` 当唯一范围）、run 级 grant 并集检索。
- 升级路径 A 本轮不做。
- 仍开、不挡 v0：corpus 是否整根/带版本、是否按 run 冻结、撤销对进行中 prompt 的影响。

## 其余八条：已于 2026-08-23 确认写入「决定」

D1 D / D2 A+C / D3 B / D4 A / D6 C / D7 D / D8 A+catalog / D9 D。

## 编码 agent v0 要证明的五件事

1. 两个 worker 能交替认领同一次编码 run。
2. 宿主文件 mutation 能走 call/result 恢复，且不出现未分类的双写。
3. 项目 1 / 项目 2 三功能例：**检索和 log fold 都不串切片**。
4. RLM/context-builder 子任务返回 handle，独立跑，事后用消息/文件交结果。
5. 先 emit 再 wait、重复事件、retry、租约过期，都仍是 **一条 jobs 队列**。

## DuckDB 插件后做、且明确不做的

后做：进程/服务 DuckDB、`SELECT … AS` 造表、可回放清单、父子 merge、产物归档、DuckDB 工具的 D2 分类。

不做：第二队列、第二套 claim、钉 PG 后端、把 `plugin_temp_views.sql` 迁进核、DuckDB 单独 `CREATE EXTENSION`、同步整棵 RLM 子树。
