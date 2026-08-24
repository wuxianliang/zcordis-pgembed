# P05 — 一步驱动 + LLM 幂等 A+B

Date: 2026-08-24  
Status: **ready to implement**  
Parent: `docs/plans/2026-08-23-pg-cordis-development.md` P05  
Depends on: P01 and P02, implemented  
Parallel with: P03 (implemented; wait remains stubbed here), P06 (implemented), P19 (plan-only)  
Primary deliverables: `sql/0005_p05_one_step_driver.sql`, `tests/test_p05_one_step_driver.py`, current-tree assertion updates, and `sql/README.md` updates

Mid-flow (2026-08-24) confirmed: `cordis.step_once`; fail-closed wait stub; fixture-only `mock.observe`; no pre-hook `renew_claim`.

Plan critique (`docs/reviews/2026-08-24-p05-plan-critique.md`) findings 1–7 are folded in: corrected file:line anchors, P04 plan-status wording, unmatched-await zero-false-positive rationale, unique-violation propagation, guard vs wait error codes, envelope `step_name` for the guard, and the `emit_step_claimed` six-argument call form.

## Summary

P05 adds the paradigm-neutral SQL execution primitive `cordis.step_once`: one invocation under one live `cordis.jobs` claim processes at most one named step `s-N`, consisting of one LLM decision plus either one mock tool observation or a final answer, and then returns a textual outcome for its caller to map through the existing P01 claim verbs. The driver implements LLM idempotency A+B by deriving `provider_key = md5(run_id || '/' || step_name)`, passing it to a replaceable SQL-callable `cordis.invoke_llm` hook, persisting it with a request fingerprint on the `llm` log event, and skipping the hook whenever a matching `llm` checkpoint already exists. The shipped hook and tool face are deliberately deterministic mocks backed by `cordis.jobs.payload`; there is no HTTP client, arbitrary SQL evaluator, host dispatch, enqueue verb, worker loop, wait transition, spawn, grant enforcement, or paradigm policy package. This is a targeted addition over P01/P02’s existing claim and log APIs rather than a port of G or scratch SQL.

---

## Goal

Implement the P05 contract from `docs/plans/2026-08-23-pg-cordis-development.md`:

- Add a SQL-callable, paradigm-neutral `cordis.step_once`.
- Let one invocation process no more than one named step.
- Use P02’s `cordis.next_step_name` and `cordis.llm_checkpoint`; do not reproduce G’s step-counting or payload lookup.
- Use P02’s `cordis.emit_step_claimed` for every P05 log append; do not add another direct writer to `cordis.agent_steps`.
- Derive the provider idempotency key solely from `(run_id, step_name)`.
- Persist the provider key and deterministic request fingerprint on every P05 `llm` event.
- On checkpoint hit, validate the stored key/fingerprint and skip `cordis.invoke_llm`.
- Append `llm` before parsing/executing the mock tool path.
- Support deterministic crash-shaped resume:
  - no `llm` row → invoke with the same provider key;
  - `llm` exists without `tool`/`final` → skip invocation and resume the action;
  - `tool` exists → the next claim advances to the next step;
  - `final` or `error` exists → return the matching terminal outcome without another model call.
- Reproduce three claims = three named steps using the canonical SQL tree:
  - claim 1: `llm` + `tool` for `s-1`, then yield;
  - claim 2: `llm` + `tool` for `s-2`, then yield;
  - claim 3: `llm` + `final` for `s-3`, then complete.
- Keep all scheduler transitions outside `step_once`; tests and future P09 map outcomes through P01 verbs.
- Keep wait fail-closed and stubbed: P05 must never put a job into `WAITING`.
- Keep the full product version marker at `p06`, while a tree ending at `0005` reports `p05`.

P05 is complete when automated tests prove the three-claim flow, stable provider-key propagation, checkpoint-based invocation skipping, fingerprint mismatch failure, lost-claim fencing, max-step behavior, wait stubbing, source boundaries, replay safety, and compatibility with the current P00–P06 tree.

---

## Execution index

P03 used `W27`–`W33`; P04 reserves `W34+`; P06 used `W60`–`W66`. P05 uses exactly `W50`–`W59`.

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W50 | Add the P05 SQL file and mock invocation hook | `cordis.invoke_llm(text,text,jsonb,text)` validates the provider key and returns the configured step response without network or side effects | `sql/0005_p05_one_step_driver.sql` | P01 | Medium |
| W51 | Add claim/config/terminal handling to `step_once` | Exact live claim is checked; malformed parameters raise; lost ownership returns `lost_claim`; existing final/error short-circuits; configuration is validated | `sql/0005_p05_one_step_driver.sql` | W50, P01, P02 | Medium |
| W52 | Add request folding, provider key, fingerprint, and checkpoint reuse | The pre-LLM request is deterministic; checkpoint hits rebuild the original request boundary, validate key/fingerprint/raw, and do not call the hook | `sql/0005_p05_one_step_driver.sql` | W51, P02 | Large |
| W53 | Add the new-LLM path and durability ordering | Checkpoint miss invokes the hook with the stable key, then appends one claimed `llm` before any mock tool/final/error branch | `sql/0005_p05_one_step_driver.sql` | W50–W52 | Medium |
| W54 | Add decision handling and textual outcomes | Mock tool, final, invalid decision, wait-stub, max-step, and lost-claim paths have exact log/outcome behavior; no jobs status transition occurs inside the driver | `sql/0005_p05_one_step_driver.sql` | W51–W53 | Large |
| W55 | Advance and document the P05 marker | A P05-ending tree reports `p05`; the full tree remains `p06`; README documents the mock-only driver boundary | `sql/0005_p05_one_step_driver.sql`, `sql/README.md` | W50–W54 | Small |
| W56 | Add catalog, payload-contract, and source-boundary tests | Exact signatures, volatility/security, no enum/table/enqueue/worker/eval/spawn/wait mutation, and no second log writer are proven | `tests/test_p05_one_step_driver.py` | W50–W55 | Medium |
| W57 | Add the canonical three-claim proof | Three worker IDs and three distinct claim tokens produce `llm,tool,llm,tool,llm,final`, `s-1…s-3`, and terminal `DONE` | `tests/test_p05_one_step_driver.py` | W51–W55 | Large |
| W58 | Add idempotency, crash-resume, lease, max-step, and failure tests | A and B seams, fingerprint mismatch, lost claims, checkpoint resume, post-tool recovery, wait stub, and terminal recovery are covered | `tests/test_p05_one_step_driver.py` | W51–W57 | Large |
| W59 | Retarget current-tree assertions and run regressions | Full file/function lists include P05; full version remains `p06`; all P00/P01/P02/P03/P05/P06 suites pass | `tests/test_p00_sql_source.py` and regression suite | W55–W58 | Medium |

---

## Background

### Skeleton and locked contracts

| Fact | Location |
|---|---|
| P05 migrates G/scratch **semantics**, not their SQL ABI; one claim step is one LLM plus its then-available tools; mock LLM is acceptable; done = three claims / three steps on canonical SQL | `docs/plans/2026-08-23-pg-cordis-development.md` P05 |
| P09 owns `worker_step`; P10 owns the host seam; P19 owns CodeAct/RLM policies; P17 owns asynchronous spawn | parent plan P09/P10/P17/P19 |
| Yield hybrid D: the default yield boundary is a completed LLM-plus-tools step | `docs/decisions/2026-08-23-pending.md` locked Yield row |
| LLM idempotency A+B: provider key is `H(run_id, step_name)` and a committed matching `llm` row skips transport; tools are explicitly excluded | pending LLM row; architecture snapshot §4 |
| D1 forbids session affinity and the old `pg_temp` data-analysis path | pending D1; architecture snapshot §4 |
| D2 classifies real tools separately; non-PG side effects eventually require `tool/call` then `tool/result` | pending D2 |
| D7 requires canonical numbered SQL in this repository and forbids `CREATE EXTENSION` | pending D7 |
| D8 requires SQL-callable verbs usable by future in-DB and host workers | pending D8 |
| D9 forbids synchronous child loops; every child run eventually enqueues | pending D9 |
| Scratch proved three claims and three tokens only; it did not prove real HTTP headers, timeout fencing, wait/sleep, or TEMP behavior | `scratch/yield_walkthrough/REPORT.md` |

These contracts are closed. P05 must not reopen D1–D9 or architecture snapshot §4.

Load-bearing file:line sources (spot-checked):

| Fact | Location |
|---|---|
| P05 do/don’t/done; function-name decision; wait may be stubbed | `docs/plans/2026-08-23-pg-cordis-development.md:35`, `:75`, `:154-162` |
| Yield hybrid D; LLM A+B does not cover tools; D9 enqueue children | `docs/decisions/2026-08-23-pending.md:49-50`; snapshot §4 `:90-91`, `:101` |
| D1 no `pg_temp` / session affinity; D7 no `CREATE EXTENSION` | pending.md `:58`, `:70-72`; snapshot `:93`, `:99` |
| F happy path + llm-before-tools durability; tools not exactly-once | `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md:111-154` |
| G research SQL, not ABI; three-claim walkthrough | `docs/analysis/2026-08-23-g-rlm-one-step-driver.md:1-3`, `:507-514` |
| Scratch 9/9 proof and unproven areas | `scratch/yield_walkthrough/REPORT.md` |
| P01 verbs; PENDING-only claim; default 90s lease; no enqueue | `sql/0001_p01_claim.sql:23-40`, `:128-237`; `docs/plans/P01-jobs-claim-2026-08-23.md:601`, `:728`, `:914` |
| P02 envelope, unique llm index, `emit_step` monopoly, resume `next_step_name`, `llm_checkpoint` | `sql/0002_p02_log.sql:5-39`, `:43-80`, `:279-364` |
| P03 implemented; WAITING dead-end until P04 timeout | `sql/0003_p03_wait_event.sql`; `docs/plans/P03-wait-event-2026-08-24.md:1540-1542` |
| P04 deep plan is ready to implement (`W34`–`W41`) but no `sql/0004_*` exists | `docs/plans/P04-sleep-retry-2026-08-24.md:1-8`, `:61` |
| P06 catalog does not execute tools | `sql/0006_p06_plugin_catalog.sql:465+`; P06 plan `:39` |
| Gaps allowed; `0005` then `0006` still reports `p06`; KERNEL_FUNCTIONS exact list | `sql/README.md:9-51`; `tests/test_p00_sql_source.py:23-43`, `:57-65` |
| Test helpers `run_apply` / `psql` / `psql_session` | `tests/conftest.py:28-128` |
| Work-item numbering: P03 `W27`–`W33`; P04 `W34`–`W41`; P06 `W60`–`W66`; P05 uses `W50`–`W59` | P03 plan `:48`; P04 plan `:61` |

### F protocol: semantic order

`docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` defines the order P05 preserves:

```text
live claim
→ fold prior log
→ derive stable step name
→ derive provider key and request fingerprint
→ checkpoint hit? reuse : invoke provider
→ append llm
→ parse
→ execute tools
→ append tool/final/error
→ caller yields/completes/fails
```

Load-bearing details:

- `provider_key = H(run_id, step_name)`, never attempt or fingerprint.
- The request fingerprint covers the request inputs, model/tool declaration, and prior folded history.
- A stored checkpoint with a different fingerprint is a protocol error, not a new step.
- `llm` is ordered before tools.
- Tools are not exactly-once.
- A lost token prevents further claim-owned appends.
- Crash after provider acceptance but before a committed `llm` reuses the same provider key.
- Crash after committed `llm` but before `tool` skips provider invocation and resumes the tool.
- Crash after `tool` treats the step as complete and advances.
- Default execution yields after that completed step.

P05 preserves this ordering but uses a local deterministic hook and mock observation. It does not claim to prove real HTTP behavior.

### What P01 already shipped

`sql/0001_p01_claim.sql` owns the only scheduler row and all claim-state mutation:

- `cordis.jobs` is unique by `run_id`.
- Statuses are `PENDING|RUNNING|WAITING|SLEEPING|DONE|ERROR`.
- A live claim is represented by `claim_token`, `claimed_by`, and `claim_expires_at`.
- `claim_job` selects only due `PENDING` rows.
- `renew_claim`, `yield_claim`, `complete_claim`, and `fail_claim` use token-and-expiry fencing.
- `release_stale` requeues expired work and increments `attempt`.
- The default claim/renew duration is 90 seconds.
- P01 intentionally ships no enqueue or worker-loop function.
- Tests and trusted producers insert directly into `cordis.jobs`.
- P04 may later revise terminal `fail_claim` into retry/requeue behavior.

P05 must not add direct `UPDATE cordis.jobs` claim logic or aliases such as `claim_is_live`/`heartbeat_claim`. It may read the authoritative row, while every P05 log mutation remains fenced through P02.

### What P02 already shipped

`sql/0002_p02_log.sql` owns the append-only history and named-step APIs:

- Envelope: `run_id`, `seq`, `kind`, `payload`, `step_name`, `created_at`.
- `llm` and `tool` require an envelope `step_name` matching `^s-[1-9][0-9]*$`.
- The unique partial index on `(run_id, step_name)` permits only one `llm` for a named step.
- `cordis.emit_step` contains the only direct `INSERT INTO cordis.agent_steps`.
- `cordis.emit_step_claimed(p_claim_token uuid, p_run_id text, p_kind text, p_payload jsonb, p_step_name text DEFAULT NULL, p_extend_seconds integer DEFAULT 90) RETURNS boolean` atomically fences a live token/run pair, extends the lease with `GREATEST`, and delegates to `emit_step` (`sql/0002_p02_log.sql:72-79`).
- `cordis.next_step_name` returns the latest incomplete `llm` step until a later same-step `tool` or `final` exists; otherwise it advances to `s-(max+1)`.
- `cordis.llm_checkpoint` returns the full matching `agent_steps` row or no row.
- P02 deliberately does not interpret fingerprints, provider keys, provider transport, or decisions.
- `run_state` remains a log projection; P03 later added `awaiting`.

P05 must reuse these APIs. In particular, it must not copy G’s `COUNT(llm)+1` name calculation or look for `payload.step_name`.

### What P03, P04, and P06 mean for P05

- P03 is implemented and exposes `await_event`/`emit_event`, but a committed `WAITING` job has no timeout path until P04 SQL lands. P05 therefore must not invoke `await_event`.
- P04 has a deep plan (ready to implement, `W34`–`W41`) but no `sql/0004_*`; the gap remains reserved and no timeout/retry machinery exists in the tree.
- P05 failure outcomes are terminal under current P01 semantics. P04 owns retry/requeue integration later.
- P06 catalogs plugin metadata but executes nothing. P05 must not route through `plugin_catalog`, run host tools, or interpret P06 retry/effect classes.
- P19 will select paradigm policy. P05 therefore uses `cordis.step_once`, not an RLM-specific name, and must not import RLM prompts/parsers.

### SQL tree, numbering, and tests

Current source files before P05:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0006_p06_plugin_catalog.sql
```

P05 adds:

```text
0005_p05_one_step_driver.sql
```

A P05-ending test tree contains:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0005_p05_one_step_driver.sql
```

It excludes `0004` and `0006`, and reports `p05`. The full product tree applies `0006` after `0005`, so it continues to report `p06`.

Existing test infrastructure to reuse:

- `run_apply`
- `psql`
- `psql_session`
- `SQL`
- `load_apply_module`

No new PostgreSQL driver, server harness, apply script, package dependency, or HTTP client is needed.

### Canonical proof target

The test fixture inserts one job directly:

```json
{
  "input": {"question": "p05 proof"},
  "model": "mock",
  "max_steps": 3,
  "tools": [{"name": "mock.observe", "effect_class": "read_only"}],
  "mock_llm": {
    "responses": {
      "s-1": {
        "action": "tool",
        "tool_name": "mock.observe",
        "arguments": {"index": 1}
      },
      "s-2": {
        "action": "tool",
        "tool_name": "mock.observe",
        "arguments": {"index": 2}
      },
      "s-3": {
        "action": "final",
        "answer": "ok"
      }
    }
  },
  "mock_tools": {
    "observations": {
      "s-1": {"success": true, "value": "o1"},
      "s-2": {"success": true, "value": "o2"}
    }
  }
}
```

Expected history:

```text
seq order: llm, tool, llm, tool, llm, final
step_name: s-1, s-1, s-2, s-2, s-3, s-3
```

The fixture is proof configuration in the existing jobs payload, not a new historical store or general producer ABI.

### Hard bans

P05 must not add:

- `CREATE EXTENSION`, including `http` or `pgcrypto`;
- a second queue or `absurd` schema;
- `agent_runs`, `rlm_vars`, TEMP objects, or session affinity;
- copied pg-agent/scratch/G SQL;
- `rlm_step_once`, `rlm_loop`, `worker_step`, handler dispatch, or enqueue;
- arbitrary SQL evaluation;
- host-tool or P06 execution;
- synchronous or asynchronous spawn;
- grant enforcement;
- sleep/retry logic;
- a `CREATE TYPE` outcome enum;
- direct `INSERT`, `UPDATE`, or `DELETE` against `cordis.agent_steps`;
- direct claim-state updates to `cordis.jobs`;
- `run/yield` emission.

---

## Current-state analysis

### Existing responsibilities and ownership

| Component | Current responsibility | P05 extension |
|---|---|---|
| `cordis.jobs` | One scheduler/claim row per run; stores producer payload | P05 reads the claimed row and its mock configuration; it does not transition status |
| `cordis.claim_job` | Produces a live claim token | Called by tests and later P09 before `step_once` |
| P01 transition verbs | Yield/complete/fail and stale recovery | Called by the P05 test driver and later P09 after the returned outcome |
| `cordis.agent_steps` | Append-only historical truth | Receives P05 `llm`, `tool`, `final`, and terminal `error` events |
| `cordis.emit_step_claimed` | Claim/run fence plus sole append delegation | Used for every new P05 event |
| `cordis.next_step_name` | Stable incomplete-step recovery | Used unchanged |
| `cordis.llm_checkpoint` | Existing LLM row lookup by envelope step name | Used unchanged |
| `cordis.run_state` | Final/error/awaiting/in-progress projection | P05 reads history directly for terminal and await checks; it does not replace the projection |
| `cordis.await_event` | Atomic event suspension | Deliberately not called by P05 |
| `cordis.plugin_catalog` | Metadata only | No P05 dependency |
| Future P09 | Claim → one step → outcome transition | First production caller of `step_once` |
| Future P19 | Select CodeAct/RLM policy | May replace the stub request/decision policy without renaming the driver |

### Current control-flow gap

P01/P02 can already express this manually:

```text
claim_job
→ next_step_name
→ optional llm_checkpoint
→ emit_step_claimed(llm)
→ emit_step_claimed(tool/final)
→ yield_claim/complete_claim
```

What is missing is one canonical function that owns:

- deterministic pre-LLM folding;
- provider-key construction;
- request fingerprinting;
- checkpoint validation and skip;
- mock-provider invocation;
- mock-decision parsing;
- exact one-step outcome semantics.

G and scratch contain research versions, but they depend on absent pg-agent objects and duplicate already-shipped claim/log behavior.

### End-to-end data flow after P05

```text
trusted producer/test
  → INSERT cordis.jobs(run_id, job_type, payload)

worker/test
  → cordis.claim_job(run_id, worker_id, lease)
      → RUNNING + token

worker/test
  → cordis.step_once(run_id, token)
      → read exact live jobs row and immutable request config
      → terminal/await guard
      → cordis.next_step_name
      → cordis.llm_checkpoint
      → build canonical request from config + pre-step log
      → provider_key + fingerprint
      → checkpoint hit:
           validate and reuse raw decision
        checkpoint miss:
           cordis.invoke_llm
           cordis.emit_step_claimed(kind=llm)
      → parse decision
      → mock observation or final/error append
      → text outcome

worker/test
  → yield_claim | complete_claim | fail_claim
```

Every operation is synchronous in the caller’s PostgreSQL transaction. There is no background task, callback, notification, event loop, or connection affinity.

### Mutation points

P05 introduces only these runtime mutations:

1. `step_once` appends through `emit_step_claimed`:
   - `llm`;
   - one `tool`, `final`, or terminal `error`.
2. Existing `emit_step_claimed` may extend the live lease without shortening it.
3. The caller separately invokes a P01 status transition.

`invoke_llm` is read-only in P05’s shipped mock implementation, although its volatility is declared for future provider replacement.

### Why this is a targeted change

P01 already owns claim state, P02 already owns step identity/checkpoints/appends, and P03/P06 already expose their independent extension points. P05 needs only two functions and no new table. Adding a run registry, handler layer, provider table, outcome enum, enqueue API, parser framework, or worker loop would preempt P09/P19 and create parallel responsibilities.

---

## Design

## Resolved decisions

| # | Decision | Rationale | Rejected alternative |
|---:|---|---|---|
| 1 | Name the driver `cordis.step_once`. | The kernel loop primitive is paradigm-neutral; P19 will select CodeAct/RLM policy without renaming the execution ABI. | `cordis.rlm_step_once`, which would freeze the G research paradigm into the kernel. |
| 2 | Wait is fail-closed and stubbed. A mock `action="wait"` produces a terminal P05 error and `fail`; P05 never returns an active `wait` outcome or calls `await_event`. | Without P04, a `WAITING` job has no timeout recovery except exact-key emit. Entering it from a mock decision would create a dead-end. | Calling P03 `await_event`, silently yielding, or treating wait as a tool observation. |
| 3 | P05 adds no enqueue function. Tests insert directly into `cordis.jobs`, following P01. | Three claims require only one existing jobs row. Handler-aware enqueue belongs to P09, and a P05-only wrapper would become an unnecessary second producer ABI. | `cordis.enqueue_job`, `rlm_enqueue`, or an agent-runs table. |
| 4 | Add a replaceable SQL hook `cordis.invoke_llm(text,text,jsonb,text) RETURNS jsonb`; P05’s implementation reads deterministic responses from `jobs.payload.mock_llm.responses`. | It is callable from SQL/P09, gives the provider key an explicit transport parameter, and needs no extension or Python dependency. | Inlined fixture lookup only, a fixture table, Python-driven decisions, or an HTTP extension. |
| 5 | The only P05 tool is one replayable mock observation named `mock.observe`, read from `jobs.payload.mock_tools.observations[step_name]`. | This proves LLM-plus-tool ordering without arbitrary SQL, host dispatch, P06 execution, or D2 external effects. | `rlm_eval`, arbitrary `SELECT`, file tools, plugin dispatch, or multiple tool calls in one step. |
| 6 | `H(run_id, step_name) = pg_catalog.md5(run_id || '/' || step_name)`. | Core PostgreSQL provides `md5(text)`; the key is stable across claims and attempts and requires no extension. | `digest`/SHA from `pgcrypto`, attempt-dependent keys, or using the request fingerprint as the provider key. |
| 7 | `step_once` returns text constants: `yield`, `complete`, `fail`, `wait`, `lost_claim`. No enum is created. | Text avoids a migration-hostile closed PostgreSQL type. The function validates its own closed return set; P09 will map it explicitly. | `CREATE TYPE cordis.step_outcome AS ENUM` or a jobs status return. |
| 8 | Folding and parsing are P05 stubs: a deterministic JSONB request is built from selected jobs payload fields plus ordered log envelopes; the hook returns an already-structured JSON decision. | This exercises fingerprinting and replay while preserving P19’s ownership of prompts/parsers. | Copying pg-agent’s RLM prompt, parser, decision type, or eval functions. |
| 9 | `step_once` does not append `run/yield`. | P01 `yield_claim` has no log effect, and P05 should not create a second partial scheduler-history integration. The kind remains reserved. | Logging yield in the driver or modifying P01. |
| 10 | Exact driver signature is `cordis.step_once(text,uuid,integer DEFAULT 90) RETURNS text`. | The extension duration is passed to each claimed append; future P09 can use the same SQL ABI with an explicit lease margin. | A two-argument function with a hidden fixed extension or extra provider/tool callbacks in the signature. |
| 11 | `step_once` never changes jobs status. The caller maps outcomes through P01 verbs. | P09 owns the worker state machine, while P05 owns only the step body. This also lets host and in-DB callers share the same step semantics. | Calling `yield_claim`, `complete_claim`, or `fail_claim` internally. |
| 12 | The shipped mock uses `jobs.payload.max_steps`, default `10`, requiring a positive JSON integer in the PostgreSQL integer range. | No product `agent_runs` table exists. The jobs payload is the existing producer input for this proof. | A new run-policy table, an unlimited mock loop, or deriving max steps from claim attempt. |
| 13 | A matching checkpoint may always finish its action even when the LLM count already equals `max_steps`. A new LLM is forbidden once the count reaches the cap. A non-final tool on the last allowed LLM appends max-step error and returns `fail` instead of yielding for an extra claim. | Recovery must not strand an already-paid checkpoint; the cap limits LLM calls, not completion of an existing call. Immediate failure avoids a useless fourth claim. | Failing before finishing a checkpoint or waiting until the next claim to discover the cap. |
| 14 | The fingerprint request boundary excludes the current checkpoint row. On checkpoint hit, history is folded only through `seq < llm_checkpoint.seq`; on miss, all current history is folded. | This reconstructs the request that originally produced the stored LLM instead of including the LLM response in its own fingerprint. | Folding the full log on resume, which guarantees a false mismatch. |
| 15 | Fingerprint is `md5(request_jsonb::text)`, where the request has an exact P05 field set and ordered history. | PostgreSQL JSONB text is deterministic within the canonical SQL implementation and needs no extension. | Hashing raw jobs payload, which would include fixture responses, or hashing only messages without model/tool parameters. |
| 16 | Mock provider response scripts and mock observations are excluded from the request fingerprint. | They are fixture/provider internals, not provider request inputs. Excluding them also permits tests to replace or instrument the hook without changing the request identity. | Hashing the complete jobs payload. |
| 17 | P05 performs a fresh non-locking exact-claim read before invoking the bounded mock hook, but does not call `renew_claim` before it. Authoritative ownership is enforced by each `emit_step_claimed`. | Renewing inside one SQL function would hold the jobs row lock across a future provider call. The local mock is immediate; an expired claim after invocation is safely handled by `lost_claim` plus the same provider key. | A pre-hook jobs UPDATE/heartbeat inside `step_once`, parallel fence SQL, or assuming the initial read guarantees ownership at append time. |
| 18 | All P05 `fail` paths are non-retryable protocol/configuration failures and append terminal `error` history before returning, when the claim remains live. | P04 retry semantics are absent, and current `run_state` treats any error as terminal. P05 must not invent a retryable event shape. | Returning fail without history, or pretending hook failures can already enter P04 retry. |
| 19 | Exactly one executor invocation is permitted per claim before the caller performs its outcome transition. P05 does not persist the live claim token or a token hash in the log to police API misuse. | P09’s worker state machine provides serialization. Logging a live capability would be unsafe, and adding a scheduler cursor would exceed P05. | Allowing P09 to loop `step_once` under one claim or persisting claim tokens in `llm` payloads. |
| 20 | The textual `wait` outcome is reserved in the ABI but unreachable in P05. | It keeps the planned outcome vocabulary stable for the eventual P04/P19 integration without entering an unsupported scheduler state now. | Removing `wait` from the documented outcome set or returning it without durable wait registration. |

No implementation question remains open.

Mid-flow user confirmations (2026-08-24), matching decisions 1, 2, 5, and 17:

| Fork | User choice |
|---|---|
| Function name | `cordis.step_once`, not `cordis.rlm_step_once` |
| Wait | Fail-closed stub; never enter `WAITING` or return `wait` |
| Tool face | Fixture `mock.observe` only; no SELECT evaluator |
| Pre-hook lease | No `renew_claim` before `invoke_llm`; fence is `emit_step_claimed` |

---

## G/scratch-to-P05 difference list

| G / scratch behavior | P05 product behavior | Reason |
|---|---|---|
| `rlm_step_once(run_id, token)` | `cordis.step_once(run_id, token, extend_seconds DEFAULT 90)` | Paradigm-neutral kernel ABI; explicit append-extension parameter |
| `rlm_step_outcome` PostgreSQL enum | Text return with five documented constants | Avoid enum migration and premature type ABI |
| `claim_is_live` / `heartbeat_claim` helpers | Exact read for early exit; authoritative mutation fencing through existing `emit_step_claimed` | Do not duplicate P01/P02 claim SQL |
| Inline jobs status updates in `h_rlm_continue` | No status mutation in P05; caller uses P01 verbs | Worker transition belongs to P09 |
| G’s count-based `rlm_next_step_name` | Existing `cordis.next_step_name` | Preserves incomplete-LLM resume semantics |
| G’s payload-based checkpoint lookup | Existing `cordis.llm_checkpoint` on envelope `step_name` | Reuses P02 ABI and unique index |
| `agent_runs` for question/config | Existing `cordis.jobs.payload` for P05 mock input only | No product run registry exists; adding one is out of scope |
| `rlm_vars`, prompts, fold functions, parser type | Exact P05 JSONB request and structured mock decision | P19 owns policies; pg-agent SQL is not copied |
| `http_call_llm` / `sql_retry` | `cordis.invoke_llm` default mock, no network | No HTTP extension or client dependency |
| Notional HTTP idempotency header | Explicit `p_provider_key` hook argument and persisted `llm.payload.provider_key` | Establishes the transport contract without claiming real header proof |
| `md5(messages::text)` fingerprint | `md5(exact_request_jsonb::text)` | Includes model, parameters, tools, input, and pre-step history |
| `md5(run_id || '/' || step)` provider key | Same core expression | This G semantic is adopted |
| `rlm_eval` arbitrary code | One `mock.observe` action with configured observation | No SQL eval or external effects |
| Data-analysis final latch | No DA path or latch | D1 retired this path; DuckDB is P20 |
| `rlm_maybe_async_spawn` | No spawn recognition or stub | D9/P17 owns enqueue admission |
| `wait` outcome can drive WAITING | Wait decision appends terminal unsupported error and returns fail | P04 timeout path is absent |
| `rlm_enqueue` | Tests insert one jobs row directly | P01 convention; P09 owns producer/dispatch integration |
| `worker_step` | Tests manually claim, call, and transition | P09 owns the production worker |
| Session-pinned compatibility `rlm_loop` | No compatibility loop | Session affinity and multi-step claims are non-compliant |
| Scratch audit table | No product audit table | Tests retain tokens in Python and use test-local hook instrumentation |
| Scratch functions in `public` | All new objects in `cordis` | Canonical namespace |
| Scratch `llm` payload embeds `step_name` | P02 envelope column is authoritative; payload omits duplicate step identity except in error details | Reuse product log contract |
| Scratch files are installed into pg-agent research DB | New numbered SQL is independently authored in this repository | D7 and scratch-to-ABI ban |

---

## Detailed design

## Component 1 — `sql/0005_p05_one_step_driver.sql`

**Kind:** numbered SQL source file  
**Path:** `sql/0005_p05_one_step_driver.sql`  
**Applied:** after P03 and before P06 in the current tree  
**Persistent tables added:** none

File order:

1. `cordis.invoke_llm`;
2. `cordis.step_once`;
3. replacement `cordis.get_schema_version()` returning `p05`.

Both P05 functions are:

- `LANGUAGE plpgsql`;
- `VOLATILE`;
- `SECURITY INVOKER`;
- `SET search_path TO pg_catalog`.

Every table/function reference is schema-qualified. Builtins use `pg_catalog` qualification where supported.

The file must contain no function comment beginning with `{`; P05 functions are kernel seams, not P06 plugin definitions. It does not call `cordis.refresh_plugins`.

---

## Component 2 — Mock job payload and request contract

### Jobs payload

P05 requires `cordis.jobs.payload` to be a JSON object. Recognized root fields:

| Field | Type | Default | Fingerprinted? | Purpose |
|---|---|---|---:|---|
| `input` | any JSON | JSON `null` | yes | User/run input presented to the mock request |
| `model` | nonblank JSON string | `"mock"` | yes | Provider/model identity |
| `llm_params` | JSON object | `{}` | yes | Stub model parameters |
| `tools` | JSON array | one `mock.observe` declaration | yes | Request-visible tool declaration |
| `max_steps` | positive JSON integer | `10` | no | Kernel step budget for this mock run |
| `mock_llm.responses` | JSON object keyed by `s-N` | required when invoked | no | Default hook response script |
| `mock_tools.observations` | JSON object keyed by `s-N` | required for tool actions | no | Replayable mock observation |

Default tools value:

```json
[
  {
    "name": "mock.observe",
    "effect_class": "read_only"
  }
]
```

P05 ignores unrecognized jobs payload fields. Mock response and observation data are excluded from the fingerprint because they represent provider/tool fixture internals, not the outbound request.

Trusted producers/tests must treat request-shaping fields as immutable after the first `llm` checkpoint. Mutation is not silently accepted: checkpoint resume rebuilds the request and fails on fingerprint mismatch.

### Canonical request

For one step, construct a JSONB object with exactly these fields:

```json
{
  "protocol": "cordis.p05.mock.v1",
  "run_id": "<run>",
  "step_name": "s-N",
  "job_type": "<jobs.job_type>",
  "model": "<model>",
  "parameters": {},
  "tools": [],
  "input": null,
  "history": []
}
```

`history` is an ordered JSON array of:

```json
{
  "seq": 123,
  "kind": "llm",
  "step_name": "s-1 or null",
  "payload": {}
}
```

Rules:

- Order strictly by `agent_steps.seq`.
- Exclude `created_at`; wall-clock data must not perturb a replay fingerprint.
- On checkpoint miss, include all existing events for the run.
- On checkpoint hit, include only events with `seq < checkpoint.seq`.
- Include all event kinds within the boundary, not only `llm`/`tool`; claim timeout, wake, and lineage events are legitimate prior history for later steps.
- An empty history is `[]`, not SQL NULL.

Fingerprint:

```text
request_fingerprint = pg_catalog.md5(request_jsonb::text)
```

Provider key:

```text
provider_key = pg_catalog.md5(run_id || '/' || step_name)
```

The two hashes have different purposes and must never be substituted for one another.

---

## Component 3 — `cordis.invoke_llm`

### Interface

```text
cordis.invoke_llm(
    p_run_id      text,
    p_step_name   text,
    p_request     jsonb,
    p_provider_key text
) RETURNS jsonb
```

Catalog identity:

```text
cordis.invoke_llm(text,text,jsonb,text)
```

### Input validation

Direct calls raise `invalid_parameter_value` for:

- null/blank run ID;
- step name not matching `^s-[1-9][0-9]*$`;
- SQL NULL or non-object request;
- null/blank provider key;
- provider key not exactly equal to `md5(run_id || '/' || step_name)`.

The hook then loads the unique `cordis.jobs` row for `p_run_id`. Missing jobs row raises `object_not_in_prerequisite_state`.

### Default mock implementation

Read:

```text
jobs.payload.mock_llm.responses[p_step_name]
```

Requirements:

- `jobs.payload` is an object;
- `mock_llm` is an object;
- `responses` is an object;
- the requested step exists;
- the response is a JSON object.

Missing or malformed fixture data raises `object_not_in_prerequisite_state`. The function returns the configured response unchanged.

The default hook:

- does not validate or mutate claim ownership;
- does not append history;
- does not update jobs;
- does not invoke HTTP;
- does not sleep or retry;
- does not cache provider results;
- does not execute tools.

`step_once` is the only product caller in P05. The hook remains separately SQL-callable so tests can instrument it and a later numbered file can replace the transport while preserving its key/request contract.

### Future replacement contract

A real implementation of this signature must use `p_provider_key` as the provider `Idempotency-Key`. It must not derive another key from attempt, worker, lease, fingerprint, or request body.

P05 does not authorize replacing the mock with a long-running network call without separately resolving transaction duration and lease budgeting. The ABI is replaceable; real transport behavior is not claimed as implemented here.

---

## Component 4 — `cordis.step_once`

### Interface

```text
cordis.step_once(
    p_run_id         text,
    p_claim_token    uuid,
    p_extend_seconds integer DEFAULT 90
) RETURNS text
```

Catalog identity:

```text
cordis.step_once(text,uuid,integer)
```

Documented return set:

| Outcome | Meaning | Required caller action |
|---|---|---|
| `yield` | One LLM/tool step completed and the run is nonterminal | `cordis.yield_claim(token)` |
| `complete` | A final event already existed or was appended | `cordis.complete_claim(token, latest final payload)` |
| `fail` | A terminal P05 error already existed or was appended | `cordis.fail_claim(token, latest error payload)` |
| `wait` | Reserved for future integration; unreachable in P05 | Treat as protocol error if observed |
| `lost_claim` | Ownership could not be proven at a required mutation boundary | Stop; do not mutate jobs with the old token |

The caller must perform exactly one outcome mapping and must check the P01 verb’s boolean result. A false transition result means ownership was lost after `step_once` returned.

### Parameter behavior

Raise `invalid_parameter_value` before reading runtime state for:

- null/blank `p_run_id`;
- null or non-positive `p_extend_seconds`.

A null claim token is not malformed configuration; it returns `lost_claim`.

### Initial claim and jobs lookup

Capture a fresh wall-clock timestamp and read exactly one jobs row where:

```text
run_id = p_run_id
claim_token = p_claim_token
status = RUNNING
claim_expires_at > captured
```

This read does not acquire a row lock and does not renew the claim. If no row matches, return `lost_claim` with:

- no hook invocation;
- no log append;
- no jobs mutation.

Capture `job_type` and `payload` from this row for the remainder of the invocation.

This read is an early filter, not the ownership fence. Each log mutation is fenced later by `emit_step_claimed`, which may return false if the lease expires or ownership changes.

### Existing terminal and unsupported-await guards

Before selecting a new step:

1. If any `final` event exists, return `complete`.
2. Else if any `error` event exists, return `fail`.
3. Else inspect the latest `run/await`:
   - if it has a later same-`await_id` `run/wake`, continue;
   - if it is unmatched while jobs is nevertheless `RUNNING`, append a terminal `P05_INVALID_HISTORY` error through `emit_step_claimed` (envelope `step_name` SQL NULL) and return `fail`;
   - if that append loses the claim, return `lost_claim`.

The unmatched-await guard is log-only and does not require P03 side tables. A normal P03 wait atomically moves jobs to `WAITING` and clears the token (`sql/0003_p03_wait_event.sql:227-242`); emit-before-wait appends a paired `run/await`/`run/wake` while remaining `RUNNING` (`:271-295`). P03 itself therefore cannot produce a live `RUNNING` claim plus unmatched await. The guard catches only malformed or manual state and has zero false positives on the P03 happy path.

Final keeps precedence over error, matching `run_state`.

### Configuration validation

Validate captured jobs payload before invoking the hook:

- payload is a JSON object;
- `model`, if present, is a nonblank string;
- `llm_params`, if present, is an object;
- `tools`, if present, is an array;
- `max_steps`, if present:
  - is a JSON number;
  - its text form contains only a positive base-10 integer;
  - it fits PostgreSQL `integer`;
  - it is at least 1;
- `mock_llm`/tool fixture fields are validated lazily only when their branch needs them.

A malformed job configuration is a terminal protocol failure:

1. append `error` with code `P05_INVALID_JOB_CONFIG`;
2. return `fail`;
3. return `lost_claim` instead if the append is fenced out.

Do not raise raw JSON cast errors to the worker after the claim has been recognized. Convert them to the durable error path.

### Step identity and checkpoint selection

After configuration validation:

1. Count committed `llm` rows as `steps_used`.
2. Call `cordis.next_step_name(p_run_id)` to obtain `v_step_name`.
3. Query `cordis.llm_checkpoint(p_run_id, v_step_name)` for sequence and payload.

If there is no checkpoint and `steps_used >= max_steps`:

- append `P05_MAX_STEPS_EXCEEDED`;
- include `steps_used`, `max_steps`, and attempted `step_name`;
- return `fail` or `lost_claim`.

If there is no checkpoint but a `tool` or `final` already exists with the selected step name, treat that as malformed out-of-order history:

- append `P05_INVALID_HISTORY`;
- return `fail` or `lost_claim`.

A checkpoint hit is allowed even when `steps_used == max_steps`, because its action still has to finish.

### Request, key, and fingerprint

Build the canonical request as specified above.

Derive:

```text
provider_key = md5(run_id || '/' || step_name)
fingerprint  = md5(request_jsonb::text)
```

Neither includes claim token, claimed worker, jobs attempt, lease expiry, or wall-clock time.

### Checkpoint-hit branch: idempotency B

Require checkpoint payload to contain:

| Field | Required shape |
|---|---|
| `protocol` | string equal to `cordis.p05.mock.v1` |
| `raw` | JSON object |
| `fingerprint` | string equal to the newly computed fingerprint |
| `provider_key` | string equal to the newly computed provider key |
| `model` | string equal to the request model |

If any field is missing, malformed, or different:

- do not call `invoke_llm`;
- do not execute the mock tool;
- append terminal `P05_LLM_CHECKPOINT_MISMATCH`, including expected/stored key and fingerprint where present;
- return `fail`, or `lost_claim` if the error append loses ownership.

On a valid hit:

- set the current decision to `checkpoint.payload.raw`;
- do not append another `llm`;
- proceed to decision handling.

This is the B guarantee.

### Checkpoint-miss branch: idempotency A seam

Immediately before invoking the hook, perform a second non-locking exact-claim read with a fresh wall-clock timestamp. If it no longer matches, return `lost_claim` without invoking the hook.

Otherwise:

1. Call `cordis.invoke_llm(run_id, step_name, request, provider_key)` inside an exception sub-block.
2. If the hook raises:
   - append terminal `P05_LLM_INVOCATION_FAILED`;
   - include the provider key, SQLSTATE, and a bounded error message;
   - return `fail`, or `lost_claim` if that append is fenced out.
3. Require the returned value to be a JSON object; otherwise use the same failure code.
4. Append the claimed `llm` event before parsing or tool handling, using the six-argument form:

   ```text
   cordis.emit_step_claimed(
       p_claim_token,
       p_run_id,
       'llm',
       llm_payload,
       v_step_name,
       p_extend_seconds
   )
   ```

   Tool, final, and error appends use the same argument order. Envelope `step_name` is SQL NULL only for errors discovered before step selection.
5. If `emit_step_claimed` returns false:
   - return `lost_claim`;
   - append nothing else;
   - the provider may already have accepted the request, so the next claim must derive the same provider key.
6. If append succeeds, proceed with the returned response as the current decision.

The `llm` payload is exactly:

```json
{
  "protocol": "cordis.p05.mock.v1",
  "raw": {},
  "fingerprint": "<32 lowercase hex>",
  "provider_key": "<32 lowercase hex>",
  "model": "<model>"
}
```

The named step lives in the `agent_steps.step_name` envelope column and is not duplicated as a payload field.

P05’s default hook is immediate and read-only. A future real provider must fit within the caller’s committed lease budget or use a redesigned host/transport path. P05 deliberately does not hold a jobs-row heartbeat lock across the hook.

### Decision parser

The decision is already JSON, so P05 performs structural validation only. `action` must be a JSON string with one of:

```text
tool | final | wait
```

Unknown/missing action uses terminal `P05_INVALID_LLM_DECISION`.

P05 supports one tool action per LLM. Multiple tool calls are out of scope because P02 currently considers the first later same-step `tool` sufficient to complete a named step; introducing partial multi-tool correlation would require a broader log protocol.

### Tool branch

Required response shape:

```json
{
  "action": "tool",
  "tool_name": "mock.observe",
  "arguments": {}
}
```

Rules:

- `tool_name` must equal `mock.observe`.
- `arguments` may be absent, defaulting to `{}`.
- If present, `arguments` must be a JSON object.
- Load the observation from captured jobs payload at:

  ```text
  mock_tools.observations[step_name]
  ```

- The observation may be any JSON value, including JSON `null`, but the key must exist.

Missing/malformed tool fixture data uses terminal `P05_MOCK_TOOL_OBSERVATION_MISSING` or `P05_INVALID_LLM_DECISION`, as appropriate.

Append one claimed `tool` event:

```json
{
  "tool_name": "mock.observe",
  "arguments": {},
  "observation": null,
  "mock": true
}
```

Use the same envelope `step_name`.

If the append loses ownership, return `lost_claim`.

After a successful tool append:

- `steps_used_after` equals the committed count including the current `llm`;
- if `steps_used_after >= max_steps`:
  - append terminal `P05_MAX_STEPS_EXCEEDED`;
  - include `steps_used`, `max_steps`, and the completed step name;
  - return `fail` or `lost_claim`;
- otherwise return `yield`.

The mock observation is read-only and replayable. P05 does not add `tool/call`/`tool/result`; D2/P16 owns real nontransactional tools.

### Final branch

Required response shape:

```json
{
  "action": "final",
  "answer": "..."
}
```

`answer` must be a JSON string; an empty string is permitted.

Append one claimed `final` event:

```json
{
  "answer": "...",
  "source": "p05.mock"
}
```

Use the current envelope `step_name`.

- Append success → return `complete`.
- Lost fence → return `lost_claim`.

A final answer is allowed on the last permitted LLM.

### Wait branch

A response with:

```json
{"action": "wait"}
```

must not call `cordis.await_event`, insert `run_waits`, change jobs status, append `run/await`, or return `wait`.

Instead:

1. the preceding `llm` remains the decision checkpoint;
2. append terminal `error` code `P05_WAIT_UNSUPPORTED`;
3. return `fail`, or `lost_claim` if the append is fenced out.

### Terminal error payload

Every P05-created terminal error uses:

```json
{
  "code": "P05_*",
  "message": "bounded human-readable message",
  "step_name": "s-N or null",
  "details": {}
}
```

The envelope `step_name` is:

- the active `s-N` when known (including a mock `action="wait"` decision, which uses `P05_WAIT_UNSUPPORTED`);
- SQL NULL for failures discovered before step selection: `P05_INVALID_JOB_CONFIG` and the unmatched-await guard (`P05_INVALID_HISTORY`).

Closed P05 codes:

```text
P05_INVALID_JOB_CONFIG
P05_INVALID_HISTORY
P05_MAX_STEPS_EXCEEDED
P05_LLM_INVOCATION_FAILED
P05_LLM_CHECKPOINT_MISMATCH
P05_INVALID_LLM_DECISION
P05_MOCK_TOOL_OBSERVATION_MISSING
P05_WAIT_UNSUPPORTED
```

All are terminal in P05. Messages derived from exceptions must be bounded to 1000 characters.

---

## Component 5 — Outcome mapping and scheduler lifecycle

`step_once` does not perform these transitions. The caller follows this exact mapping:

| `step_once` result | Caller operation |
|---|---|
| `yield` | `yield_claim(token)` |
| `complete` | Load latest final payload, then `complete_claim(token, payload)` |
| `fail` | Load latest error payload, then `fail_claim(token, payload)` |
| `lost_claim` | No mutation with the old token |
| `wait` | Unreachable in P05; caller raises a protocol error and must not fabricate WAITING |

For `yield`, `complete`, and `fail`, a false P01 result means the claim expired after the step result was committed. The caller stops; later stale recovery/new claim reconciles from the log.

P09 may eventually wrap `step_once` and the transition in one SQL function/transaction. P05 tests deliberately exercise the verbs as separate calls as well, because that exposes crash-shaped recovery states.

---

## State and data flow

### New LLM plus tool

Trigger: worker calls `step_once` with a live claim and no checkpoint.

```text
jobs claim/config
  → exact live read
  → prior log fold
  → step name
  → request/key/fingerprint
  → invoke_llm mock
  → emit_step_claimed(llm)
  → parse action=tool
  → jobs.payload mock observation lookup
  → emit_step_claimed(tool)
  → outcome yield
  → caller yield_claim
```

Observed after successful transition:

- two new log rows with one step name;
- jobs is due `PENDING`;
- token cleared;
- attempt unchanged;
- next claim gets a new token and advances to the next step.

### Checkpoint resume

Trigger: a committed `llm` exists with no later same-step `tool`/`final`.

```text
next_step_name returns existing step
  → llm_checkpoint hit
  → rebuild request with history before llm.seq
  → validate fingerprint/provider key
  → skip invoke_llm
  → re-run replayable mock tool or final branch
```

Duplicate or out-of-order delivery does not create another `llm`; the P02 unique index is an additional structural fence.

### Final recovery

Trigger: final log append committed, but the caller did not complete the jobs row.

A later live claim calls `step_once`:

```text
existing final
  → outcome complete
  → no hook, no append
  → caller complete_claim
```

The same pattern applies to existing terminal error → `fail`.

### Max-step flow

- No checkpoint and LLM count already at cap: no provider call; append error and fail.
- Checkpoint at cap: finish its action.
- Final at cap: complete.
- Tool at cap: append the tool, then append max-step error and fail.

### Wait action

```text
llm checkpoint
  → action=wait
  → terminal unsupported error
  → fail
  → caller fail_claim
```

No P03 mutation occurs.

### Duplicate and dropped operations

| Situation | Required result |
|---|---|
| Duplicate call with an expired/cleared token | `lost_claim`, no hook or append |
| Same checkpoint revisited under a new claim | Hook skipped; action resumes |
| Hook accepted, lease expires before `llm` append | `lost_claim`; no P05 log; next claim sends same provider key |
| `llm` committed, action missing | New claim skips hook and resumes action |
| `tool` committed, yield response dropped | After stale recovery/new claim, next step advances; no duplicate prior tool |
| `final` committed, complete response dropped | New claim returns `complete` without another append |
| Error committed, fail response dropped | New claim returns `fail` without another append |
| Fingerprinted request config changes | Checkpoint mismatch error; no hook/tool |
| Two concurrent `step_once` calls with one token | Unsupported caller violation; the P02 unique `llm` index prevents duplicate checkpoint identity, but P05 does not promise graceful multiwriter arbitration |

### Execution context

All P05 execution is synchronous within the caller’s PostgreSQL transaction.

- No asynchronous cancellation object exists.
- PostgreSQL rollback removes all P05 log writes from that transaction.
- The mock hook has no external side effect.
- A future external hook may have accepted a request even if PostgreSQL rolls back; stable provider key A is the recovery mechanism.
- A worker process interruption does not cancel the PostgreSQL lease automatically.
- Stale claim recovery remains P01/P04 responsibility.

---

## Crash-resume matrix

This implements the applicable cases from F §10:

| Interruption point | Durable state | Next claim behavior |
|---|---|---|
| Before hook | No current-step `llm` | Build same step/key and invoke normally |
| Hook/provider accepted, before committed `llm` | No current-step `llm`; external provider may know key | Invoke again with identical provider key |
| After committed `llm`, before action | Matching `llm`, no `tool`/`final` | Validate fingerprint/key, skip hook, replay action |
| During mock tool before `tool` append | Matching `llm`, no `tool` | Same as above; mock observation is replayable |
| After `tool`, before yield | Completed step in log; jobs may still be RUNNING | After new claim, `next_step_name` advances |
| After `final`, before complete | Final history; jobs may still be RUNNING | Return `complete`, then complete jobs |
| After error, before fail | Error history; jobs may still be RUNNING | Return `fail`, then fail jobs |
| Claim expires before any required append | No append at that boundary | Return `lost_claim`; old worker stops |
| Checkpoint fingerprint differs | Existing `llm` plus new terminal mismatch error | No hook/tool; caller fails job |

Within one ordinary `step_once` SQL call, `llm` is issued before the mock action, but both become visible only when the caller transaction commits. P05 nevertheless supports a separately committed `llm`-only state because future host execution and crash reconciliation use the same P02 log primitives. It does not claim autonomous subtransactions or an independently committed mid-function checkpoint.

---

## Work items

### W50 — Add the mock invocation hook

**File:** `sql/0005_p05_one_step_driver.sql`

Add:

- exact `cordis.invoke_llm(text,text,jsonb,text)` signature;
- input validation;
- provider-key equality check;
- jobs payload response lookup;
- object-return validation;
- no writes/network/extensions.

**Done when:**

- direct valid invocation returns the configured response;
- wrong key or malformed request raises;
- missing run/response raises prerequisite-state error;
- source inspection finds no HTTP, retry, sleep, or table mutation.

### W51 — Add `step_once` preconditions and terminal handling

**File:** `sql/0005_p05_one_step_driver.sql`

Add:

- exact signature and text return;
- scalar validation;
- null/lost token handling;
- exact live jobs read;
- captured payload/config validation;
- existing final/error short-circuits;
- unmatched-await failure;
- max-step parsing.

**Done when:**

- malformed scalar inputs raise;
- lost claims return `lost_claim` without hook/log mutation;
- existing final/error returns terminal outcome idempotently;
- invalid configuration is durably failed when the claim remains live.

### W52 — Add fold and checkpoint validation

**File:** `sql/0005_p05_one_step_driver.sql`

Add:

- P02 `next_step_name`;
- P02 `llm_checkpoint`;
- pre-checkpoint history boundary;
- exact request JSON;
- MD5 key/fingerprint;
- checkpoint raw/key/fingerprint/model validation;
- skip path.

**Done when:**

- a valid seeded `llm` checkpoint causes zero hook calls and resumes the tool;
- request mutation causes terminal mismatch;
- no duplicate `llm` is appended.

### W53 — Add the invocation path

**File:** `sql/0005_p05_one_step_driver.sql`

Add:

- second fresh claim read before hook;
- `invoke_llm` call and exception handling;
- claimed `llm` append before action handling;
- lost-claim behavior after provider return;
- exact `llm` payload.

**Done when:**

- first invocation writes exactly one LLM checkpoint;
- provider key is persisted;
- a provider-return/lease-expiry fixture returns lost and writes no LLM;
- the next claim uses the identical key.

### W54 — Add decision and outcome handling

**File:** `sql/0005_p05_one_step_driver.sql`

Add:

- tool action validation and mock observation lookup;
- final action;
- wait failure;
- invalid decision failure;
- max-step post-tool failure;
- exact text outcomes;
- no jobs status transition and no `run/yield`.

**Done when:**

- tool → `yield`;
- final → `complete`;
- wait/invalid/missing observation/max → `fail`;
- any failed claimed append → `lost_claim`;
- `wait` is never returned.

W51–W54 are one logical function and must land atomically in the final P05 change set.

### W55 — Version and README

**Files:**

- `sql/0005_p05_one_step_driver.sql`
- `sql/README.md`

At the end of `0005`, redefine the unchanged zero-argument version function to return `p05`.

README must add:

```text
tree ending at 0005_p05_one_step_driver.sql → p05
full tree including 0006                    → p06
```

Also document:

- `step_once` is paradigm-neutral;
- P05’s provider/tool face is mock-only;
- caller owns outcome transitions;
- no worker/enqueue/wait/retry/HTTP is shipped.

### W56 — Catalog and source-boundary tests

**File:** `tests/test_p05_one_step_driver.py`

Add P05-ending-tree tests for:

- exact file set and version;
- function identities;
- volatility/security;
- no enum;
- no new table;
- no enqueue/worker;
- no direct log writer;
- no jobs status updates;
- no wait/event call;
- no eval/spawn/HTTP/extension;
- default mock response validation.

### W57 — Three-claim proof

**File:** `tests/test_p05_one_step_driver.py`

Use direct jobs insert and existing P01 verbs:

1. insert fixture job;
2. worker 1 claim → step → yield;
3. worker 2 claim → step → yield;
4. worker 3 claim → step → complete.

Assert:

- three distinct tokens;
- three worker IDs;
- one persistent jobs row;
- attempt remains 1;
- exact kinds and step names;
- provider keys equal MD5 of run/step;
- final answer `ok`;
- jobs `DONE`;
- result matches latest final payload;
- no `run/yield`.

### W58 — Recovery/error/lease tests

**File:** `tests/test_p05_one_step_driver.py`

Add:

- checkpoint skip with a test-local hook that would fail/count if invoked;
- provider-key reuse after the hook expires the claim before checkpoint append;
- fingerprint mismatch;
- crash after tool before yield followed by stale release/new claim;
- existing final/error recovery;
- max-step behavior;
- wait-stub behavior (`action="wait"` → `P05_WAIT_UNSUPPORTED`);
- unmatched-await guard (`P05_INVALID_HISTORY`, NULL envelope `step_name`);
- malformed hook return (non-object → `P05_LLM_INVOCATION_FAILED`);
- malformed response/config/tool observation;
- lost claim before hook;
- append extension does not shorten a longer lease;
- replay with existing jobs/log rows.

Test-only replacement of `cordis.invoke_llm` must occur in an isolated reset database or be restored by reapplying the P05-ending tree in `finally`. No test may leave the shared database with an instrumented hook.

### W59 — Current-tree retarget and regressions

**Files:**

- `tests/test_p00_sql_source.py`
- all existing regression modules, unchanged unless an exact current-tree assertion requires P05

Update:

- exact full-tree file output;
- exact sorted `KERNEL_FUNCTIONS`.

Keep:

- full-tree version `p06`;
- P02-only/P03-only versions and absence assertions;
- P02 append monopoly;
- P03 event behavior;
- P06 catalog behavior.

---

## File-by-file impact

### `docs/plans/P05-one-step-driver-2026-08-24.md` — replaced by this planning task

- Status changes from scaffold to `ready to implement`.
- All nine scaffold questions and additional execution details are resolved.
- Background evidence is retained/refined.
- No runtime behavior changes in this planning pass.

### `sql/0005_p05_one_step_driver.sql` — added during implementation

Adds:

- `cordis.invoke_llm(text,text,jsonb,text)`;
- `cordis.step_once(text,uuid,integer)`;
- replacement `cordis.get_schema_version()` returning `p05`.

Adds no table, enum, index, comment metadata, direct log writer, worker, or enqueue function.

Ordering dependency:

- `invoke_llm` must be defined before `step_once`;
- both require P01 jobs;
- `step_once` requires P02 log functions;
- no P03 or P06 object is called;
- version marker is last.

### `sql/README.md` — modified during implementation

Add P05 version composition and the mock-only driver boundary. Preserve all filename, replay, namespace, forbidden-statement, and current-P06 rules.

### `tests/test_p05_one_step_driver.py` — added during implementation

Owns P05 catalog, payload, three-claim, idempotency, recovery, error, lease, replay, and source-boundary tests.

Use:

- `_apply_p05_only`, copying `0000`, `0001`, `0002`, `0003`, `0005`;
- direct jobs inserts;
- existing `claim_job`, `yield_claim`, `complete_claim`, `fail_claim`;
- test-local hook replacement only in isolated/restored databases.

### `tests/test_p00_sql_source.py` — modified during implementation

Change the exact full-tree file list to:

```text
0000_kernel.sql,
0001_p01_claim.sql,
0002_p02_log.sql,
0003_p03_wait_event.sql,
0005_p05_one_step_driver.sql,
0006_p06_plugin_catalog.sql
```

Add to the exact alphabetically sorted function list:

```text
cordis.invoke_llm
cordis.step_once
```

The resulting relevant order is:

```text
cordis.get_schema_version
cordis.invoke_llm
cordis.llm_checkpoint
...
cordis.run_state
cordis.step_once
cordis.unregister_host_plugin
```

Keep `get_schema_version() = p06`.

### Files explicitly unchanged

- `sql/0000_kernel.sql`
- `sql/0001_p01_claim.sql`
- `sql/0002_p02_log.sql`
- `sql/0003_p03_wait_event.sql`
- `sql/0006_p06_plugin_catalog.sql`
- `tools/apply_pg_cordis.py`
- `tests/conftest.py`
- `tests/test_p01_claim.py`
- `tests/test_p02_agent_steps.py`, unless a current-tree assertion unexpectedly names the file set; validate before deciding
- `tests/test_p03_wait_event.py`
- `tests/test_p06_plugin_catalog.py`
- `pyproject.toml`
- `uv.lock`
- `scratch/yield_walkthrough/*`
- pg-agent files

If implementation discovers that an unchanged test encodes the exact current file/function list, update only that assertion and record the validation in the implementation review. Do not refactor the test harness.

---

## Errors and edge cases

### Parameter errors: raise

`invoke_llm` raises for:

- blank run;
- invalid step format;
- non-object request;
- blank/wrong provider key.

`step_once` raises for:

- blank run;
- null/non-positive extension duration.

These are caller/API errors and occur before runtime recovery behavior.

### Lost ownership: return `lost_claim`

Return `lost_claim` for:

- null token;
- unknown token;
- token belonging to another run;
- non-RUNNING row;
- expired token;
- token cleared by another transition;
- lease lost before the second pre-hook check;
- any `emit_step_claimed` returning false.

Lost ownership must not be converted into an `error` event because the caller no longer owns append authority.

### Missing jobs row

- `step_once` with no exact claimed row returns `lost_claim`.
- Direct `invoke_llm` with no jobs row raises prerequisite-state error because it is a provider fixture configuration failure, not an ownership API.

### SQL NULL versus JSON null

- SQL NULL `jobs.payload` is prevented by P01.
- JSON `null` payload is not an object and fails P05 configuration.
- JSON null `input` and mock observation are valid.
- Missing mock observation key differs from an existing key whose value is JSON null; only the former fails.
- Hook return must be an object; JSON null is invalid.

### Empty history

Use `[]`; request and fingerprint remain deterministic.

### Empty final answer

Allowed if it is a JSON string.

### Missing model or tools

Use exact defaults. Present but malformed values fail configuration; do not silently coerce strings/objects.

### Max-step boundaries

- `max_steps=1` plus immediate final: complete.
- `max_steps=1` plus tool: log tool, then max-step error, fail.
- Existing `llm s-1` at the cap: finish its tool/final branch.
- Zero, fractional, negative, string, exponent-form non-integer, or integer overflow: invalid configuration.
- Ordinary yield never increments `jobs.attempt`.

### Existing terminal history

- Any final wins and returns `complete`, even if a later error exists, matching current projection precedence.
- Error without final returns `fail`.
- No new event is appended in either case.

### Existing unmatched await

A live RUNNING claim with unmatched await history is inconsistent with the P05 no-wait contract and with P03's own transitions. Append `P05_INVALID_HISTORY` with SQL NULL envelope `step_name` and fail rather than invoking the model. Do not reuse `P05_WAIT_UNSUPPORTED` here: that code is reserved for a mock decision whose `action` is `wait` after an `llm` checkpoint already exists.

### Checkpoint corruption

Missing/malformed raw, key, fingerprint, protocol, or model is terminal mismatch. Do not accept a stored raw response merely because an `llm` row exists.

### Request mutation

Changing input/model/parameters/tools/job type after a checkpoint produces fingerprint mismatch. Changing only `mock_llm` or `mock_tools` fixture data does not alter the request fingerprint.

### Hook failure

A default mock-hook error is configuration/protocol failure. P05 logs it and fails terminally. A later real provider must integrate with P04 before treating transport errors as retryable.

### Duplicate execution with one token

P05 assumes the worker serializes one `step_once` invocation per claim. Concurrent calls sharing a token are misuse. If two executors both miss the checkpoint and both try to append `llm` for the same `(run_id, step_name)`, the second insert hits `agent_steps_llm_step_idx` (`sql/0002_p02_log.sql:36-38`) and PostgreSQL unique-violation `23505` **propagates unchanged**. Do not catch it into a P05 error event or rewrite it as `fail`/`lost_claim`. The only exceptions that propagate directly from `step_once` are malformed scalar parameters and unhandled database invariant violations of this kind.

### Transaction rollback

- Rollback removes all P05 log rows and lease extensions from that transaction.
- Sequence gaps are acceptable.
- Default mock invocation has no external effect.
- A future provider may retain an accepted request after PostgreSQL rollback; stable provider key is mandatory.

### Dropped transition response

If `yield_claim`/`complete_claim`/`fail_claim` commits but its response is lost, the old token is cleared and cannot repeat the transition. Read jobs/log state by run ID.

---

## Tradeoffs

1. **Generic ABI, mock policy:** `step_once` has the correct kernel name, but its initial request/decision policy is intentionally a proof stub. P19 replaces policy behavior later rather than introducing a second loop.
2. **No enqueue convenience:** tests are slightly more verbose, but P05 avoids freezing an unvalidated producer/handler contract.
3. **Text outcomes:** easier evolution and replay-safe DDL, at the cost of compile-time enum checking. P09 must use an exhaustive CASE with an unknown-value failure branch.
4. **MD5:** sufficient for deterministic idempotency naming and available in core, but not a security proof. Provider keys are not authorization credentials.
5. **Single mock tool call:** avoids inventing partial multi-tool checkpoint semantics. Full CodeAct tool batches require a later log-protocol decision.
6. **No pre-hook heartbeat:** avoids holding a jobs lock across a future provider call. The default hook is bounded; real transports need explicit lease/transaction design.
7. **Terminal mock failures:** consistent with current `run_state` and P01 fail behavior, but not yet suitable for transient provider retries.
8. **JSONB text fingerprint:** deterministic in the SQL implementation and adequate for P05; cross-language canonicalization remains a P10 concern if a host rebuilds requests independently.
9. **LLM-before-tool ordering without autonomous commit:** the log order is correct, but one in-DB function transaction cannot independently commit the LLM row before its mock tool. The resume shape is still supported for host/separately committed checkpoints.
10. **No yield event:** preserves existing P01/P02 boundaries but leaves scheduler yield invisible in history until a future coordinated log integration.

---

## Risks and migration

### Real HTTP is not proven

P05 proves:

- key derivation;
- explicit hook propagation;
- persistence on `llm`;
- same-key recovery;
- checkpoint-based skip.

It does not prove a real HTTP `Idempotency-Key` header, provider retention policy, timeout behavior, billing deduplication, or response equality. Documentation and implementation review must not overstate this.

### Long-running replacement hook

Replacing the local hook with blocking network I/O could exceed the 90-second lease. The worker must claim with a sufficient lease or renew in a separately committed operation before entering `step_once`. Do not add an in-function pre-hook UPDATE that holds the jobs row lock across I/O without a separate design review.

### Mutable jobs payload

The install role can currently modify jobs payload directly. Fingerprint mismatch fails closed, but P07 permissions are still needed to prevent untrusted mutation.

### P04 retry integration

Every P05-created error is terminal because current `run_state` treats any error as terminal. P04 must not simply requeue a P05-failed job while leaving that error unqualified; it must explicitly revise the failure/log projection contract if transient retries are introduced.

P05-ending tests copy `0000`–`0003` plus `0005` and exclude `0004`, so they keep P01’s always-terminal `fail_claim`. If `sql/0004_*` is in the full tree when P05 regressions run there, map `fail` through `fail_claim` only with a jobs retry policy that dead-letters immediately (P04 `max_attempts=1`). Do not make P05 protocol errors retryable.

### Hook replacement and replay

`0005` uses `CREATE OR REPLACE FUNCTION` for the default mock hook. Reapplying the source tree restores the canonical P05 hook body and overwrites test-local or out-of-band replacements. Production transport replacements must land in a later numbered SQL file, not as manual drift.

### Version composition

A P05-only tree reports `p05`; the current full tree reports `p06`. Tests that assume the highest conceptual plan number equals the reported full-tree version will be wrong.

### No persistent schema migration

P05 adds functions only. Existing jobs/log rows require no transformation. In-place replay preserves them.

Downgrading to a source tree without `0005` does not remove the functions and is unsupported. Use `--reset` for disposable downgrade tests.

### Concurrent writer misuse

Two executors using the same token can still both call a provider before the unique LLM constraint chooses a durable checkpoint. They use the same provider key, limiting external duplication when the provider honors it, but worker-level serialization remains required.

### Rollback

A failed apply rolls back `0005` functions and its marker with the tree transaction. The database may remain created under the existing apply contract.

---

## Implementation order

1. Add the empty numbered file `sql/0005_p05_one_step_driver.sql` with only source-policy comments.
2. Add `cordis.invoke_llm` with the exact signature, validation, stable-key check, and jobs-payload response lookup.
3. Apply a P05-ending temporary tree and inspect the hook catalog identity.
4. Add the `step_once` signature, parameter checks, exact live-claim read, and terminal short-circuits.
5. Add jobs payload validation and max-step extraction.
6. Add unmatched-await protection, `next_step_name`, LLM count, and checkpoint lookup.
7. Add canonical request construction, provider-key derivation, and fingerprint derivation.
8. Add checkpoint-hit validation and hook skipping.
9. Add checkpoint-miss invocation, exception handling, and claimed `llm` append.
10. Add tool/final/wait/invalid decision branches and exact error codes.
11. Add post-tool max-step handling and closed textual outcomes.
12. Add the `p05` marker at the end of `0005`.
13. Update `sql/README.md`.
14. Add P05-ending-tree catalog and source-boundary tests.
15. Add the three-claim proof.
16. Add B checkpoint-skip and fingerprint mismatch tests.
17. Add A same-key-after-provider/lost-claim instrumentation tests.
18. Add crash-after-tool, terminal recovery, max-step, wait-stub, malformed-config, lease, and replay tests.
19. Retarget `tests/test_p00_sql_source.py` full-tree file/function assertions.
20. Run all required test commands.
21. Follow `AGENTS.md`: obtain Oracle implementation review with no unresolved P0/P1, record it, then commit and push only the P05 change set. P05 is not complete before the gate and successful push.

Steps 4–11 form one function and must land atomically in the final change. The SQL file, P05 tests, README update, and full-tree assertion retargeting must also be one P05 implementation change set.

---

## Verification

### Test module and helpers

Add:

```text
tests/test_p05_one_step_driver.py
```

Use an `_apply_p05_only` helper that copies exactly:

```text
0000_kernel.sql
0001_p01_claim.sql
0002_p02_log.sql
0003_p03_wait_event.sql
0005_p05_one_step_driver.sql
```

Apply to a dedicated database such as `cordis_p05_only` with `--reset`.

Use existing `psql`/`psql_session`; do not introduce psycopg, another server fixture, or another apply path.

### Required named tests

| Test | Required proof |
|---|---|
| `test_p05_fresh_apply_catalog_and_version` | Exact P05-ending file list, version `p05`, no P06 dependency, exact function identities |
| `test_p05_function_volatility_security_and_no_enum` | Both functions volatile/invoker/search-path pinned; no P05 enum or table |
| `test_p05_mock_hook_validates_key_and_returns_response` | Correct key returns scripted object; wrong key/missing response/malformed request raises |
| `test_p05_three_claims_three_steps` | Three workers/tokens; exact six-event history; two yields then complete/DONE |
| `test_p05_provider_keys_match_run_and_step` | Each LLM payload key is exact MD5 of run/step and independent of jobs attempt/worker |
| `test_p05_checkpoint_skips_hook_and_resumes_tool` | Seeded matching `llm`; instrumented hook call count remains zero; one tool append |
| `test_p05_provider_key_reused_after_lost_claim_before_checkpoint` | Test hook records key, expires claim before append; next claim records same key and succeeds |
| `test_p05_fingerprint_mismatch_is_terminal` | Changed request-shaping config skips hook/tool and appends mismatch error |
| `test_p05_llm_precedes_tool_or_final` | Sequence ordering is always LLM before its action event |
| `test_p05_crash_after_tool_advances_on_new_claim` | Commit tool without yield, expire/reap/reclaim, then next step is `s-2`, not duplicate `s-1` |
| `test_p05_existing_final_and_error_return_terminal_outcomes` | No additional hook/log call; returns complete/fail respectively |
| `test_p05_max_steps_allows_checkpoint_completion` | Checkpoint at cap still runs action |
| `test_p05_max_steps_fails_after_last_nonfinal_tool` | Tool is logged, then max error; no extra claim/LLM required |
| `test_p05_wait_action_fails_without_waiting` | After an `llm` checkpoint, `action="wait"` appends `P05_WAIT_UNSUPPORTED` with envelope `s-N`; jobs remains RUNNING until caller fails; no wait row/await/wake; no `wait` return |
| `test_p05_unmatched_await_is_invalid_history` | Manual `run/await` without `run/wake` on a live RUNNING claim appends `P05_INVALID_HISTORY` with SQL NULL envelope `step_name`; hook is not invoked |
| `test_p05_invalid_config_hook_and_decision_fail_durably` | Each malformed class produces the exact terminal error code; a non-object hook return is `P05_LLM_INVOCATION_FAILED`, not `P05_INVALID_LLM_DECISION` |
| `test_p05_lost_claim_never_invokes_or_appends` | Missing/expired/wrong token returns lost with no source mutation |
| `test_p05_claimed_append_does_not_shorten_longer_lease` | Existing longer expiry remains at least as long after successful append |
| `test_p05_does_not_emit_run_yield` | Yield outcome plus `yield_claim` produces no `run/yield` |
| `test_p05_replay_preserves_jobs_logs_and_hook_contract` | In-place apply preserves runtime rows and restores canonical functions |
| `test_p05_source_boundaries` | No direct agent_steps insert/update/delete; no direct jobs status update; no enqueue/worker/eval/spawn/wait call/extension/HTTP |

### Exact catalog assertions

New identities:

```text
cordis.invoke_llm(text,text,jsonb,text)
cordis.step_once(text,uuid,integer)
```

Assert:

- one overload of each;
- `RETURNS jsonb` for hook;
- `RETURNS text` for driver;
- both `VOLATILE`;
- both `SECURITY INVOKER`;
- no type named `step_outcome` or `rlm_step_outcome`;
- no P05-created table;
- version function remains zero-argument SQL/immutable/invoker.

### Three-claim proof details

For each claim:

1. Call `claim_job(run_id, worker-N, 90)` and record the token.
2. Call `step_once(run_id, token, 90)`.
3. Map:
   - first/second `yield` → `yield_claim`;
   - third `complete` → `complete_claim` using latest final payload.
4. Require every P01 transition to return true.

Final assertions:

```text
tokens: three distinct UUIDs
workers: worker-1, worker-2, worker-3
jobs rows for run: 1
job status: DONE
attempt: 1
steps_used: 3
run_state: final
answer: ok
kinds: llm,tool,llm,tool,llm,final
names: s-1,s-1,s-2,s-2,s-3,s-3
run/yield count: 0
```

### Checkpoint-skip test shape

The test helper constructs the exact canonical request/fingerprint in SQL using the documented field set and history boundary, then seeds one claimed `llm` through `emit_step_claimed`.

In a dedicated transaction/database:

1. Replace `cordis.invoke_llm` with a test hook that increments a test-local counter or raises if called.
2. Invoke `step_once`.
3. Assert:
   - outcome `yield`;
   - counter remains zero;
   - no second LLM;
   - one tool with the same step name.
4. Roll back the replacement or reapply the P05-ending tree.

Do not add a product call-audit table.

### Provider-return/lost-claim test shape

Use an isolated test replacement hook that:

1. records `p_provider_key` in a test-only table;
2. sets the claimed job’s expiry to the past;
3. returns the scripted decision normally.

Then:

1. `step_once` returns `lost_claim`;
2. no LLM row exists;
3. stale-release/reclaim produces a new token;
4. restore/use a normal recording hook;
5. the next call records the same provider key;
6. the persisted LLM payload contains that key.

This is the P05 proof of the A seam. It still does not claim real HTTP header behavior.

### Source-boundary assertions

Inspect `0005` and the product tree using existing sanitizer/helper patterns where appropriate. Assert:

- no direct `INSERT INTO cordis.agent_steps` in `0005`;
- no update/delete of `agent_steps`;
- P02 remains the sole direct insert implementation;
- no direct `UPDATE cordis.jobs SET status`;
- no `CREATE TYPE`;
- no `CREATE TABLE`;
- no `CREATE EXTENSION`;
- no `public`/`absurd` objects;
- no `rlm_loop`, `rlm_eval`, `worker_step`, `enqueue`, `spawn`, `await_event`, `run_waits`, HTTP function, `LISTEN`, or `NOTIFY`;
- no `run/yield` append;
- no function comment beginning with `{`.

Avoid naïve substring assertions where comments may mention forbidden concepts; use the existing preflight sanitizer or catalog behavior when possible.

### Current-tree assertion updates

`tests/test_p00_sql_source.py` must expect the full source list:

```text
0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,
0003_p03_wait_event.sql,0005_p05_one_step_driver.sql,
0006_p06_plugin_catalog.sql
```

Add `cordis.invoke_llm` and `cordis.step_once` to `KERNEL_FUNCTIONS`, preserving alphabetical order.

Keep:

```text
cordis.get_schema_version() = p06
```

P02-only/P03-only database helpers remain unchanged.

### Exact commands

Fast P05 suite:

```bash
uv run pytest tests/test_p05_one_step_driver.py -q
```

Required numbered-tree and protocol regression suite:

```bash
uv run pytest \
  tests/test_p00_sql_source.py \
  tests/test_p01_claim.py \
  tests/test_p02_agent_steps.py \
  tests/test_p03_wait_event.py \
  tests/test_p05_one_step_driver.py \
  tests/test_p06_plugin_catalog.py \
  -q
```

Required named regression checks:

```bash
uv run pytest \
  tests/test_p00_sql_source.py::test_fresh_apply_lists_current_tree_and_p06 \
  tests/test_p01_claim.py::test_reserved_waiting_sleeping_not_claimed \
  tests/test_p02_agent_steps.py::test_p02_crash_shaped_next_step_name \
  tests/test_p02_agent_steps.py::test_p02_source_tree_append_monopoly \
  tests/test_p03_wait_event.py::test_p03_no_second_queue_notify_or_direct_log_insert \
  tests/test_p05_one_step_driver.py::test_p05_three_claims_three_steps \
  tests/test_p05_one_step_driver.py::test_p05_checkpoint_skips_hook_and_resumes_tool \
  tests/test_p05_one_step_driver.py::test_p05_provider_key_reused_after_lost_claim_before_checkpoint \
  -q
```

If an existing exact test name differs from the referenced current repository name, use that module’s actual corresponding test; do not rename unrelated older tests solely to match this plan.

---

## Out of scope

P05 does not implement:

- `worker_step`, handler routing, polling, or an in-DB worker loop;
- host SDK or host HTTP;
- real LLM transport, headers, provider retry, streaming, or billing;
- enqueue or run creation;
- `agent_runs`, workspace tables, or `rlm_vars`;
- CodeAct/RLM policy selection, prompts, parser plugins, truncation, or environment policy;
- P06 plugin execution;
- arbitrary SQL/code evaluation;
- host tools, file edits, worktrees, DuckDB, or D2 call/result;
- multiple tool calls in one named step;
- wait registration, sleep, timeout, task retry, or dead-letter;
- asynchronous spawn or child admission;
- grant registration/enforcement;
- `run/yield` logging;
- a compatibility `rlm_loop`;
- `CREATE EXTENSION`;
- changes to scratch or pg-agent;
- cross-language canonical JSON rules for P10;
- provider-side proof that an idempotency key is honored.

---

## Open questions

None remaining for implementation. The nine scaffold questions, the additional max-step / lease / crash-boundary / request-canonicalization / terminal-error / caller-transition decisions, and the 2026-08-24 mid-flow forks are resolved above.

---

## References

- `docs/plans/2026-08-23-pg-cordis-development.md` — P05, P09/P10/P17/P19 ownership
- `docs/decisions/2026-08-23-pending.md` — Yield hybrid D, LLM A+B, D1/D2/D7/D8/D9
- `docs/analysis/2026-08-23-i-architecture-snapshot.md` — signed contracts and coding-agent scope
- `docs/analysis/2026-08-23-f-yield-loop-protocol-sketch.md` — happy path, tool overlap, failure ordering
- `docs/analysis/2026-08-23-g-rlm-one-step-driver.md` — research semantics, not ABI
- `scratch/yield_walkthrough/REPORT.md` — three-claim proof and unproven areas
- `scratch/yield_walkthrough/install_driver.sql` — semantic comparison only
- `docs/plans/P01-jobs-claim-2026-08-23.md`
- `docs/plans/P02-agent-steps-log-2026-08-23.md`
- `docs/plans/P03-wait-event-2026-08-24.md`
- `docs/plans/P04-sleep-retry-2026-08-24.md`
- `docs/plans/P06-plugin-catalog-2026-08-23.md`
- `sql/0000_kernel.sql`
- `sql/0001_p01_claim.sql`
- `sql/0002_p02_log.sql`
- `sql/0003_p03_wait_event.sql`
- `sql/0006_p06_plugin_catalog.sql`
- `sql/README.md`
- `tests/conftest.py`
- `tests/test_p00_sql_source.py`
- `tests/test_p01_claim.py`
- `tests/test_p02_agent_steps.py`
- `tests/test_p03_wait_event.py`
- `tests/test_p06_plugin_catalog.py`
- `AGENTS.md`
