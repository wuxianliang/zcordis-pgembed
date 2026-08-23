# Plan: pg_cordis × DBOS 深度研究报告

## Stage 1 — 研究（deep-research-swarm, Route B 聚焦搜索 + 文件获取）
- 加载 deep-research-swarm SKILL.md
- 并行 explore 子代理：
  - A: 学术论文（VLDB2022、CIDR2022、arXiv2020、Apiary/Lotus）PDF 下载解析
  - B: dbos-transact-ts 源码（schema SQL、executor、recovery、queue/notifications）
  - C: dbos-transact-py / golang / java 源码对照
  - D: 官方文档 docs.dbos.dev + dbos.dev 博客 + LLM/agent 实践 + 边界教训
- 输出：带出处（URL+访问日期）的研究简报，逐题回应 Q1–Q12

## Stage 2 — 写作（report-writing）
- 按委托书第 4 节结构撰写中文报告（3000–6000 字主体）
- 含 Q1–Q13 逐题回答、表结构 diff、v0.1 修改建议清单
- 输出 .agent.final.md

## Stage 3 — 格式化（docx）
- 转为 .docx 交付到 /mnt/agents/output/
