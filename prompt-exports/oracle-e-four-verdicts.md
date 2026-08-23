# Oracle adjudication: four Topic-E questions

- Goal: Independent oracle verdicts on Q1–Q4, then one oracle synthesis review.
- Frozen: research opinions, not product code. Do not weaken A–E locked assumptions (log SoT; SQL-first hypothesis; upgrade jobs not dual-queue; dual worker locus; checkpoints ⊂ log; TE1 placement still open until this process freezes or defers it).
- Dependency: Q2 weakly depends on Q1 (overlap frequency). Adjudicate Q2 under each yield option rather than waiting. Q3 independent. Q4 independent except option “wait for yield sketch” references Q1.

| Q | Topic | Options | Evidence owner | Oracle verdict | Status |
|---|--------|---------|----------------|----------------|--------|
| 1 | Yield boundary | A per-LLM / B per-tool / C await-only / D mixed | `2AE21C12` | **D mixed** (high): default completed LLM+tools step; async/yield past spawn depth/cost. Export `prompt-exports/oracle-plan-2026-08-23-135909-untitled-chat-7f1a8d-8a74.md` | done |
| 2 | http_call_llm idempotency | A provider key / B log-skip / C classify+accept / D no lease timeout | `A0917BA1` | **A+B** (0.94): provider key H(run_id,step_name) + log skip+fingerprint. Tools NOT covered. Export `prompt-exports/oracle-plan-2026-08-23-140044-untitled-chat-637755-e117.md` | done |
| 3 | Event names vs grants | A global / B grant prefix / C capability / D system-events-only | `FDAF0DC5` | **C + constrained B naming** (0.94): capabilities on (event_scope_id, name); prefix is storage. Export `prompt-exports/oracle-plan-2026-08-23-140310-untitled-chat-357406-b697.md` | done |
| 4 | Freeze TE1 | A freeze now / B wait for yield sketch / C freeze only jobs+protocol / D leave durable optional | `E5DABDB3` | **C targeted freeze**: one jobs queue + one claim protocol + log checkpoints; sleep/event/retry placement open. Export `prompt-exports/oracle-plan-2026-08-23-140502-untitled-chat-63121b-b38b.md` | done |
| S | Synthesis | consistency of Q1–Q4 | — | **CONFIRMED no amendments.** Next: yield-loop protocol sketch (not TE1 freeze). Export `prompt-exports/oracle-review-2026-08-23-140806-untitled-chat-3b05f2-5276.md` | done |
| F | Yield-loop sketch | protocol not TE1 freeze | parent | wrote `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` | done |
| G | rlm one-step driver | research SQL replacing WHILE | parent | wrote `docs/analysis/2026-08-23-g-rlm-one-step-driver.md` | done |

Locked from user (2026-08-23 E):
- Upgrade `jobs`/`worker()`, no second queue
- Both in-DB loop and host SDK worker, one claim protocol
- Checkpoints are log events/folds, not a second SoT
- Kernel vs plugin placement was still open; Q4 may freeze TE1 or not
