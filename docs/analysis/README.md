# pg_cordis 架构探索（2026-08-23）

**从这里读：** [`2026-08-23-i-architecture-snapshot.md`](2026-08-23-i-architecture-snapshot.md) — 探索已结束，工作假设已冻。

签名合同：[`../decisions/2026-08-23-pending.md`](../decisions/2026-08-23-pending.md)。A–H 是证据，不要把文内「open questions」再当成架构分叉。

| 文 | 主题 |
|----|------|
| [A](2026-08-23-a-dsh-plugin-migration-to-pg-cordis.md) | DSH 插件迁移（迁角色，不复用 TS） |
| [B](2026-08-23-b-log-and-projection-contract.md) | session log + 投影 |
| [C](2026-08-23-c-codeact-and-rlm-on-pg-cordis.md) | CodeAct 与 RLM |
| [D](2026-08-23-d-pg-cordis-isolation-proposal.md) | 检索范围隔离 |
| [E](2026-08-23-e-absurd-durable-execution.md) | Absurd 耐久执行 |
| [F](2026-08-23-f-yield-loop-protocol-sketch.md) | yield-loop 协议 |
| [G](2026-08-23-g-rlm-one-step-driver.md) | 一步驱动 SQL 草图 |
| [H 输入](2026-08-23-h-vision-context-for-oracle.md) / [H 裁决](2026-08-23-h-vision-d1-d9-oracle-verdicts.md) | 愿景 vs D1–D9 |
| **[I 收尾](2026-08-23-i-architecture-snapshot.md)** | **工作假设快照** |

实现骨架（按条写 deep plan）：[`../plans/2026-08-23-pg-cordis-development.md`](../plans/2026-08-23-pg-cordis-development.md)。
P00 详细计划：[`../plans/P00-sql-source-2026-08-23.md`](../plans/P00-sql-source-2026-08-23.md)。
