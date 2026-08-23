# AGENTS.md

对本仓动手的 agent **必须**遵守本文件。用户说「做 Pxx」或宣称某条 P 完成时，以这里为准，而不是默认的「改完自己看一眼」。

## 这是什么仓

`pg_cordis` 的规范 SQL 源，APPLY 到旁边的 [pgembed](https://github.com/wuxianliang/pgembed)。SQL 命名空间是 schema **`cordis`**（PostgreSQL 禁止 `pg_` schema 前缀）。产品名仍是 pg_cordis。

| 先读 | 路径 |
|------|------|
| 合同（D1–D9 已锁，不要重开） | `docs/decisions/2026-08-23-pending.md` |
| 开发骨架 P00–P20 | `docs/plans/2026-08-23-pg-cordis-development.md` |
| 架构快照 | `docs/analysis/2026-08-23-i-architecture-snapshot.md` |
| 该条 deep plan | `docs/plans/Pxx-<slug>-<date>.md` |

硬禁令：不 `CREATE EXTENSION`；不把 pg-agent SQL 搬进本仓；不把 `scratch/` 抬成 ABI；后续 Px 只往 `sql/` **追加**更高编号文件，不用改历史编号文件当发布手段。

## 开工规则

这些是 agent 会踩、别处又散的硬规则。细节仍以指向的文件为准，不要在本文件里复制骨架或 `sql/README.md`。

1. **没计划不准写代码。** 该 P 必须已有 `docs/plans/Pxx-*.md`，文首 Status 为 `ready to implement`，且 `docs/reviews/` 里对应 plan-critique 的阻塞项已经折进计划。没有就先写/改计划，不要直接改 `sql/`、`tools/`、`tests/`。
2. **合同压过 Oracle。** Oracle 若建议重开 D1–D9、快照 §4、`CREATE EXTENSION`、第二队列、或把 `scratch/` 抬成 ABI：合同和快照赢。把冲突写进 review 笔记并**停下来问用户**。用户拍板后，把决定和对应合同/快照条款送回**同一条** Oracle 聊天，直到该条 finding 被明确撤回或关闭。用户口头答复本身不是 Oracle 通过。不要为了「过审」去改架构。
3. **空转上限。** 同一条 P 连续 3 轮 review 仍有未关闭的 **P0 或 P1**，停下来问用户。`ask_oracle` 不可用时同样停，不要用 `/review` skill 或 design agent 顶替本闸门。
4. **仓边界。** 默认只改 `zcordis-pgembed`。不要为了选库去改 `pgembed` 的 `PostgresServer.psql()`；不要把核 SQL 写进 pg-agent。pg-agent 只是另一库（默认 `da_agent`）的测试床，与 `cordis_*` 分库共 PGDATA。
5. **SQL 树。** 新文件 `sql/NNNN_slug.sql`；对象落在 schema `cordis`（不是 `pg_cordis`、不是 `public`）；`cordis.get_schema_version()` 的返回值在**新文件**里改，不改 `0000_kernel.sql`。apply 默认不改，除非该 P 计划写明。完整文件名/禁令见 `sql/README.md`。
6. **测试走现有夹具。** 集成/APPLY 测试用已有的 `run_apply`、`psql`、`psql_session`。针对 loader 的白盒测试可以用已有的 `load_apply_module()`。不要把 `tools/` 做成包，不要再写第二套起库/APPLY 脚本。

## P 开发完成闸门（强制）

每一条带编号的 **P**（骨架里的 P00–P20）在实现做完之后，**不算完成**，直到：

1. Oracle **审核通过**；
2. 通过后若还改了实现（SQL、代码、测试、计划、其它行为），再次通过；
3. **立刻** `git commit` 并且 `git push`。

不要把未过闸的实现交给用户当「Pxx 已完成」。不要过闸后把 diff 留在工作区等下次再说。push 成功之前，聊天里也不要说完成。

**过渡：** 本文件落地时 `origin/main` 已有 P00、P01、P02（`709fea1`）。这三条**不**按本闸门追溯重开，也**不得**称为已按本闸门通过。完整闸门从**下一条尚未作为该 P 提交的实现**开始（不论编号是 P03、P06 还是其它）。

闸门打在 **实现完成**，不是 deep plan 完稿。计划审查继续写 `docs/reviews/YYYY-MM-DD-pxx-plan-critique.md`；计划 critique **不能**代替实现 Oracle 通过。

一条 P 内部的 W00/W01… 不是独立闸门。宣称该 P 的骨架「完成」条件已满足时，才走本流程。默认一条 P 一次过闸、一次提交；用户没有要求的话不要把半成品 push 成完成态。

### 送审之前

1. 按该 P 的 deep plan 实现，守住文内「做 / 不做」。
2. 该 P 点名的测试全绿。最少：

   ```bash
   uv run pytest tests/test_pxx_*.py -q
   ```

   若该 P 改了 apply 工具、共享夹具/环境（`tests/conftest.py`、`pyproject.toml`/`uv.lock`）、或编号 SQL 树，还要跑 `tests/test_p00_sql_source.py` 以及 deep plan 点名的更早协议测试。
3. 工作区里准备提交的就是这一条 P 的船集：不要夹带调试垃圾，不要把另一条 Px 的未完成 diff 混进来。可以并且应该自查 diff。
4. 相对上游尚未推送的提交（`git log @{u}..HEAD`；无上游则相对 `origin/main`）也只能属于这一条 P。若已有无关或未过闸的本地提交，停下来问用户，不要开审。

### Oracle 审核循环

必须用 RepoPrompt 的 `ask_oracle`，`mode: "review"`。可以并且应该自查 diff，但 **禁止**以自审、`/review` skill 或 design-agent 报告替代本闸门要求的 Oracle review。

1. `git` `op: "diff"` 且 `artifacts: true`（review 模式需要 diff 工件）。范围只含这一条 P 的实现 diff。
2. `manage_selection`：实现 diff **加上**该 P 已有 deep plan，以及审查需要的合同/骨架/`sql/README.md` 等依据（即使这些文件本轮没改）。第一轮不要把尚未存在的 review 笔记放进 selection；后续轮次带上笔记的当前版本。
3. **第一轮**：`ask_oracle`，`mode: "review"`，`new_chat: true`，`export_response: true`。消息里写清：P 编号、deep plan 路径、骨架里的完成条件，并要求按计划（不是品味）打 P0 / P1 / P2。
4. 把结论落到 `docs/reviews/YYYY-MM-DD-pxx-implementation-oracle.md`，至少包含：日期、Oracle 导出路径（`prompt-exports/oracle-review-*.md`）、计划路径、裁决、P0/P1/P2 列表。**忠实记录**导出的 Oracle 裁决（含补写/更新这篇笔记）**不**使本轮通过作废，不必因此再开一轮。
5. **通过** = 最近一轮 Oracle 审查 **没有 P0/blocker，也没有未关闭的 P1/should-fix**。P2 nit：便宜就改；不挡过闸。合同或快照 §4 冲突按开工规则 2 处理：不能带着未关闭的这类 P1 宣布通过。
6. 未通过：按 P0/P1 修改（合同或快照 §4 冲突除外，走规则 2）→ 再跑测试 → 同一条 Oracle 聊天继续（`new_chat: false`，`export_response: true`）→ 更新 implementation-oracle 笔记。重复直到通过，或触及规则 3 的 3 轮上限。
7. 通过之后若还改了 SQL、代码、测试、计划、或其它实现行为，必须再送审。只更新 review 笔记以记录已通过的裁决，不用再审。
8. 上下文压缩后：先 `oracle_chat_log` `limit: 1`，再 `new_chat: false` 续聊。中途不要无故新开 Oracle 聊天。

第一轮如果列出了 P1，即使文风像「整体不错」，也 **没有通过**。必须改完再审。

### 通过后立刻提交并推送

提交范围只含这一条 P：实现、测试、随代码落地的该 P 计划、implementation-oracle 笔记。其他 Px、scratch、无关文档不要塞进这次 commit。

```bash
# 只 add 本 P 的路径，不要 git add -A
git add sql/NNNN_pxx_*.sql tests/test_pxx_*.py docs/reviews/YYYY-MM-DD-pxx-implementation-oracle.md
# …以及本 P 实际改到的其它文件

git commit -m "$(cat <<'EOF'
Add pg_cordis Pxx <short English title>.

Oracle review passed: docs/reviews/YYYY-MM-DD-pxx-implementation-oracle.md
EOF
)"

git status
# 再确认工作区 + @{u}..HEAD（含刚打的 commit）都只含本 P，再推
git push -u origin HEAD
```

- 提交说明用英文，对齐现有历史（例：`Add pg_cordis P00 empty kernel and apply path.`）。
- 不要 `--force` / `--force-with-lease`，除非用户当场要求。
- 不要提交 `.pgdata/`、`.venv/`、密钥、Oracle 聊天以外的一次性导出垃圾。`prompt-exports/oracle-review-*.md` 若被 review 笔记引用，可以一起提交。
- push 会送出 `HEAD` 相对上游的**全部**提交。推之前必须确认这段范围只有本 P；有无关或未过闸提交则停，不要推。
- `git push` 失败则报告错误；该 P **仍未完成**。

### 禁止

- 因为「改动很小」而跳过 Oracle。
- 带着未关的 P0/P1 提交或推送。
- 两条 P 打成一次 commit。
- 在某条 P 里重开 D1–D9 或快照 §4。
- push 成功前在对话里宣布 Pxx 完成。
