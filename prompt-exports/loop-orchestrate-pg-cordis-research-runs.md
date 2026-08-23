# Loop Orchestrate: pg_cordis sequential research A→B→C→D

- Goal: Four sequential research reports exist under `docs/analysis/` covering topics A–D with the user's 2026-08-23 guidance; each lists tradeoffs with analysis and opinions, not locked architecture decisions (D may propose an isolation design but must mark it as a proposal). Loop succeeds when all four reports pass the frozen rubric.
- Frozen check: L3 structural (report path + required section headings present) plus L4 rubric grade. L4 prefers `ask_oracle`; if oracle is unavailable (provider stream fail), use a `design` agent for the same rubric review (writes under `docs/reviews/`). No L1/L2 command. Rubric is per-turn (see below). Do not weaken, skip, xfail, or replace this check.
- Scope: `zcordis-pgembed/docs/analysis/` (new research markdown), `zcordis-pgembed/prompt-exports/` (this memory file only if the Orchestrate run is asked to note findings — parent owns this file). Read-only across `pg-agent`, `pgembed`, `deepseek-harness`, `Zleap-Agent`, `zcordis-pgembed/docs/*.md` papers.
- Out of scope: product code, SQL implementations, `CREATE EXTENSION` scaffolding, rewriting other repos, deciding the final `pg_cordis` architecture as fact.
- Stop states: success, no-op, blocked, stalled, exhausted
- Brakes: max 5 Orchestrate attempts, stop after 2 stagnant attempts
- Irreversible-action gate: no git push, no deletes outside `docs/analysis/` and this memory file, no edits to other workspace roots. Analysis markdown under `docs/analysis/` is expected and allowed.
- Turn order (parent-chosen, one per Orchestrate run): A → B → C → D. Turn 5 reserved for repair/synthesis if a prior report fails the rubric.
- Working assumptions already locked by the user (do not reopen unless a report proves they conflict):
  1. Append-only session event log is the unique source of truth for conversation/runtime history.
  2. First plugin authoring hypothesis is SQL/PL/pgSQL (migration target, not "reuse DSH TypeScript as-is").
  3. `pg_cordis` extension vs plugin capability split is still a research question — reports must analyze, not freeze it.

## Frozen rubric (all turns)

A report **passes** iff all of the following are true:

1. File lives at the path named in that turn's objective under `docs/analysis/`.
2. Required section headings for that topic exist (parent verifies with search).
3. Claims about other repos name concrete files/modules; no invented APIs.
4. Tradeoffs are listed as options with analysis + **opinion**, explicitly **not a decision**.
5. The report does not ship a "build this" architecture as if already chosen — except topic D, which must include an isolation **proposal** labeled as proposal.
6. Parent L3 check + L4 judgment both pass.

### Topic A required sections

- `## DSH plugin surface to migrate`
- `## What pg_cordis would need to accept`
- `## Database-unique value (why migrate, not reuse)`
- `## Obstacles`
- `## Already in Postgres / pgembed / pg-agent vs must build`
- `## Key tradeoffs (opinion, not decision)`
- `## Open questions for B/C/D`

### Topic B required sections

- `## Session log as SoT in Postgres (content preserved, files abandoned)`
- `## Projection as cognitive layer (human + agent)`
- `## Log + projection as pg_cordis plugin contract`
- `## What of Zleap to drop vs keep as projection ideas`
- `## Key tradeoffs (opinion, not decision)`
- `## Open questions for C/D`

### Topic C required sections

- `## CodeAct paradigm on pg_cordis`
- `## RLM paradigm on pg_cordis`
- `## Shared substrate vs paradigm-specific`
- `## Key tradeoffs (opinion, not decision)`
- `## Open questions for D`

### Topic D required sections

- `## Isolation ≠ Zleap workspace`
- `## Retrieval-scoped context as isolation`
- `## Worked example (two reference projects, three functions)`
- `## pg_cordis isolation proposal`
- `## Key tradeoffs (opinion, not decision)`
- `## Residual open questions`

## User guidance (authoritative; do not dilute)

### A — plugin structure, DSH compatibility, migrate not reuse

Consider the structure `pg_cordis` will eventually accept **and** compatibility with deepseek-harness plugins (the harness plugin set will be very rich). Requirements: (1) DSH plugins must be **migratable** to pg_cordis plugins; (2) migration is **not** direct reuse, because under pg_cordis there will be database-unique advantages — that is why pg_cordis exists. Investigate: where the value is, where the obstacles are, which parts the database already has, which parts must be built. List key tradeoffs first, analyze them, give **opinions not decisions**.

### B — persistence, projection, plugin contract

Replace DSH persistence with the database; abandon file form but **keep information content**. A raw log is unreadable for developers; Zleap's database-centric role is **projection for humans and agents** (cognitive). Do **not** insist on Zleap's product inventory — that would contradict pg_cordis. Log + projection is itself a **pg_cordis contract**, because new plugins may touch the log layer and the projection layer. Do not assume plugins are simple stateless tools.

### C — two agent paradigms

Run **two** agent paradigms on pg_cordis: **CodeAct** and **RLM**.

### D — isolation design

`pg_cordis` is the foundation of everything. Treat Zleap isolation broadly: in a prompt sent to an LLM, different parts are retrieved within ranges. The original intent of pg-agent is that **context is retrieved by the agent**, and retrieval has a range — that **is** isolation. Do not be bound to Zleap's workspace. Example: "use project 1's code to develop function 1; use project 2's code to develop functions 2 and 3" exceeds Zleap workspace isolation. **Produce a pg_cordis isolation design proposal.**

## Prior exploration (do not re-derive from scratch; spot-check)

- pg-agent v2: SQL plugins via `COMMENT` (`workbench_plugin` vs `job_handler`); RLM loop in PL/pgSQL; no `pg_cordis` extension yet.
- pgembed: embeddable PG 18 wheel + attested extensions; pattern for adding `pg_cordis` as bundled or standalone ext.
- DSH: Cordis kernel (`vendor/cordis`) + everything-is-a-plugin; session log SoT; JSONL/SQLite write-behind; `cordis-host-runner` node:vm dynamic plugins.
- Zleap: product tables + `source/event/entity` memory graph; loop still in Node; own postgres-bundle, not pgembed.
- Papers in `zcordis-pgembed/docs/`: Spatiotemporal Composability (Cordis theory), RLM, Zleapai X articles.

## Deliverable paths (Orchestrate must write these)

| Turn | Topic | Path |
|------|-------|------|
| 1 | A | `docs/analysis/2026-08-23-a-dsh-plugin-migration-to-pg-cordis.md` |
| 2 | B | `docs/analysis/2026-08-23-b-log-and-projection-contract.md` |
| 3 | C | `docs/analysis/2026-08-23-c-codeact-and-rlm-on-pg-cordis.md` |
| 4 | D | `docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md` |

| Turn | Orchestrate session | Turn objective | Result | Delta vs baseline | Verified by | Terminal state | Notes |
|------|---------------------|----------------|--------|-------------------|-------------|----------------|-------|
| 0 | — | baseline | no `docs/analysis/` reports; only three papers under `docs/` | — | L3 file tree of `zcordis-pgembed` | no | before first Orchestrate |
| 1* | `52A058F7-6A9E-4877-A845-BD21A5FE9C07` | A — write DSH plugin migration report | failed to start (stream disconnect to api.tu-zi.com); no files written | 0 | L3 tree + session log | no | retry same turn; does not consume stagnation |
| 1* | `CF946650-5A00-46A5-833A-4C3DF069190C` | A — retry (pair/codex) | failed to start same way; no files written | 0 | L3 + session log | no | parent switches Orchestrate agent to `engineer` (Claude Code) because pair Codex endpoint is down |
| 1 | `92D03E89-BABA-412A-A4DA-B5D74F008C20` | A — DSH plugin migration report | wrote `docs/analysis/2026-08-23-a-dsh-plugin-migration-to-pg-cordis.md`; 7/7 headings | 0→1 Topic A report | L3 headings + parent rubric; L4 design-agent `325C9EC0-4243-4EA0-BF58-CD5AF4212B2E` → `docs/reviews/2026-08-23-l4-review-topic-a.md` PASS | no | A complete. |
| 2 | `2CB6D309-4F71-4700-B21E-3508396A6EA3` | B — log + projection contract | wrote `docs/analysis/2026-08-23-b-log-and-projection-contract.md`; 6/6 headings | 1→2 reports | L3 headings + parent read; L4 via Orchestrate oracle (available this turn) PASS | no | Spot-checked `DEFAULT_RRF_K` and `interruptedTurnClosers`. |
| 3 | `949EFE9B-CCE9-44B9-BE5B-508C5283202E` | C — CodeAct + RLM | wrote `docs/analysis/2026-08-23-c-codeact-and-rlm-on-pg-cordis.md`; 5/5 headings | 2→3 reports | L3 headings; L4 design-agent `66E5F5E3-6B53-4B2A-8E6E-A107904280F6` → `docs/reviews/2026-08-23-l4-review-topic-c.md` PASS | no | Oracle skipped (watchdog). D must reconcile C workspace-tier vs B unique-log-SoT. |
| 4 | `7F207409-E5BD-4692-99AE-C30A4FFB5728` | D — isolation proposal | wrote `docs/analysis/2026-08-23-d-pg-cordis-isolation-proposal.md`; 6/6 headings | 3→4 reports | L3 headings + parent read; L4 via Orchestrate oracle (inlined report) PASS | success | Two writer sub-agents hung; orchestrator wrote D itself. Spot-checked `CoreScope` at Zleap `types.ts:12`. Loop goal met; no turn 5. |
| E | parent (this session) | Absurd durable execution vs pg_cordis | wrote `docs/analysis/2026-08-23-e-absurd-durable-execution.md` | 4→5 reports | parent research from absurd.sql + docs; user locks: upgrade jobs, dual worker, checkpoint⊂log; placement still open | no | Not part of original A–D frozen loop. |
| F | parent (this session) | yield-loop protocol sketch | wrote `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` | 5→6 reports | implements oracle synthesis next-artifact; Q1 D / Q2 A+B / Q3 C / Q4 C | no | Sleep/event/retry placement still open. |}
