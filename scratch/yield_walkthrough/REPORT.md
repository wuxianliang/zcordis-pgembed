# Yield walkthrough (scratch)

Date: 2026-08-23 · DB: `yield_scratch` (pgembed via pg-agent `.pgdata`; does not touch `da_agent`)

Command:

```bash
cd /Users/wxl/Projects/pg-agent && uv run python \
  /Users/wxl/Projects/zcordis-pgembed/scratch/yield_walkthrough/run.py
```

Result: **9/9 PASS**, `walkthrough OK`.

| Claim | Worker | jobs.status after | steps so far |
|-------|--------|-------------------|--------------|
| 1 | w1 | PENDING (token cleared) | llm,tool (`s-1`) |
| 2 | w2 | PENDING (token cleared) | … llm,tool (`s-2`) |
| 3 | w3 | DONE (token cleared) | … llm,final (`s-3`) |

Proved: three distinct `claim_token`s, three workers, mock queue drained, final answer `ok`.

Not proved: real `http_call_llm` idempotency headers, claim timeout fencing, TEMP VIEW across yields, hybrid WHILE, wait/sleep tables.
