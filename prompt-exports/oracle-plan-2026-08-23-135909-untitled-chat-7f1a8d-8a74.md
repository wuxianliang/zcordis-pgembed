# Oracle Plan

VERDICT: D  
CONFIDENCE: high

WHY:
- `v2/pg_agent_rlm.sql` (~429–494) already forms a natural resumable unit: fold state → one LLM decision → optional tool execution → observation/final event.
- `packages/core/agent-loop/src/agent.ts` uses the same semantic boundary: `preStep`, one LLM step, then complete tool draining before advancing.
- `docs/analysis/2026-08-23-e-absurd-durable-execution.md` maps Absurd’s named `ctx.step` checkpoint and delta persistence to this completed-step boundary, supporting B as the default.
- Releasing after that boundary lets either SQL or host workers resume from the same log without exposing a half-applied model decision.
- However, `rlm_spawn` in `v2/pg_agent_rlm.sql` (~522–545) executes children synchronously and transactionally, so plain B can hide an entire recursive subtree inside one tool drain.
- TC2 in `docs/analysis/2026-08-23-c-codeact-and-rlm-on-pg-cordis.md` supplies the necessary bound: retain synchronous execution for shallow/cheap children, but checkpoint, enqueue, and yield once depth or cost crosses policy limits.
- Therefore D preserves B’s coherent default while preventing recursive or expensive tools from recreating the whole-handler pinning found in `worker()` (`v2/pg_agent_functional.sql:465–476`).

REJECTED:
- **A** — It releases between the LLM decision and its tool effects, creating a half-step recovery state and unnecessary protocol complexity.
- **B** — It is the correct default but is incomplete because synchronous `rlm_spawn` can make one “tool-complete step” unbounded.
- **C** — It continues holding the backend and claim across ordinary iterations, defeating durable handoff except when an explicit wait occurs.

COUPLING: Q2 must make every LLM invocation addressable by a stable, attempt-independent step identity because a lease may overlap or fail after the call but before the B-style step checkpoint. Async children created by D need their own stable run/step identities; the choice among provider idempotency, log-based reuse, or another Q2 mechanism remains undecided.