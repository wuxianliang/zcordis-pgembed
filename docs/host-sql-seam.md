# Host SQL seam (P10)

Runtime contract for `pg_cordis_host.CordisHostClient`. Durable behavior stays in `cordis` SQL. This module is a thin, trusted-worker client — not a model tool surface, not a published package, and not a second scheduler.

## Public API

Import from `pg_cordis_host`:

- `CordisHostClient(dsn, worker_id, *, psql_path="psql", command_timeout_seconds=30.0)`
- `new_host_worker_id(service, instance_id=None)` → `host:<service>:<32-hex>`
- Result records: `ClaimedJob`, `JobSnapshot`, `CheckpointEvent`, `AgentStep`, `RunState`, `AwaitEventResult`, `NamedCorpusRef`, `PluginCatalogEntry`, `AuthorizedHostTool`
- Errors: `CordisHostError`, `CordisInputError`, `CordisCommandTimeout`, `CordisSqlError`, `CordisProtocolError`, `CordisFeatureUnavailable`

There is no `execute`, `query`, transaction object, HTTP client, worker loop, or host-callable registry.

`repr(client)` does not include the DSN, claim tokens, SQL, or argument envelopes. Exceptions do not store those values as structured fields. `CordisSqlError` keeps `returncode`, optional `sqlstate`, and at most 4 KiB of server output.

## Transport

Each public method launches one `psql` process (`shell=False`), sends one fixed SQL template on standard input, and exits. Dynamic values travel in one JSON envelope, dollar-quoted as a data literal (limit 8 MiB). Kernel results are returned as exactly one JSON document (`to_jsonb` / `row_to_json` / native `jsonb`).

Flags: `--no-psqlrc -v ON_ERROR_STOP=1 -v VERBOSITY=verbose -q -t -A`.

A password in a URI may appear in the `psql` process argument list. Non-test use should prefer `.pgpass`, a service file, or libpq environment variables.

## Transactions and crash windows

One method = one committed statement. Checkpoint or `emit_step_scoped` must succeed **before** `yield_claim` / `complete_claim` / `fail_claim`. A crash between append and yield leaves durable history and a RUNNING row until lease recovery. The next claimant reads `llm_checkpoint` / `next_step_name` and must not blindly repeat a committed named step.

This client does not keep a pinned backend or wrap a whole host step in one database transaction. Use test-only `psql_session` when an explicit multi-statement transaction is required.

## Claims

`claim_job(run_id, lease_seconds=90)` calls `cordis.claim_job` with this client’s `worker_id`. Targeted `run_id` is the default usage. `run_id=None` preserves global P01 polling but P10 has no job-type router — do not poll globally unattended.

Worker IDs are observational (`claimed_by`). The claim token is the capability. `get_job` never returns the token; a lost `claim_job` response cannot be recovered by guessing ownership. Wait for expiry/recovery.

Default lease is 90 seconds. There is no heartbeat thread. Before a blocking external call, renew and keep lease ≥ operation timeout + 30 seconds; for long work renew at intervals no greater than `min(30s, lease/3)`. A false renew means stop and append nothing.

Boolean transitions (`renew_claim`, `yield_claim`, `complete_claim`, `fail_claim`) return SQL’s boolean unchanged. `false` means the token is dead. Do not retry it and do not issue unfenced `UPDATE`s. On the P04 product tree, `fail_claim=true` may mean retry/requeue or terminal exhaustion; inspect `get_job` instead of assuming `ERROR`. If the run already has a committed `error` event, P04 treats it as a terminality fence and the jobs row becomes `ERROR` without a second error append.

Do not compare `claim_expires_at` to the host clock. Expiry is fenced in SQL with `clock_timestamp()`.

## Provider key

`provider_idempotency_key(run_id, step_name)` asks PostgreSQL for `md5(run_id || '/' || step_name)` (32 lowercase hex). It does not include worker, token, attempt, model, fingerprint, or tools. Future host HTTP must send `Idempotency-Key` with that value and skip HTTP when `llm_checkpoint` already has the named row. The P10 proof stores the key in a fixture payload; that does **not** prove external provider idempotency.

`next_step_name` resumes: no llm row → `s-1`; latest llm without a later same-name tool/final → the same `s-N`; otherwise `s-(max+1)`.

## Isolation

User-facing history uses `emit_step_scoped` with explicit `run_id` and `slice_id`. Callers must not put `p08_scope` in the payload. Generic `checkpoint` is a trusted kernel batch append, not an isolated model write.

`recall_named_corpus`, `fold_slice_messages`, `read_run_env`, and `authorize_host_tool` always hit live P08 gates. Nothing is cached across calls. Revoke is visible on the next statement.

`read_run_env` with paradigm `rlm` currently raises `55000 P08_ENV_WORKSPACE_UNAVAILABLE`. Paradigm `codeact` raises `42501 P08_ENV_DISABLED`.

## Host tools (authorize only)

`authorize_host_tool` calls `authorize_tool_dispatch`, then requires `locus=host`, `invocation=host_tool`, null entrypoint, `read_only` / `replayable` / `none`. It returns metadata and never invokes a callable. In-database, queue, transactional, and external descriptors are protocol errors even if P08 authorized the identity.

`get_plugin` is a trusted catalog read of any locus. Model routing must use `authorize_host_tool`, not `get_plugin`. `register_host_plugin` / `unregister_host_plugin` are control-plane only; they already refresh the compiled catalog.

## Sleep

`sleep_claim` is present on the product tree through `0004_p04_sleep_retry.sql`. It is the only method that may use two `psql` processes: a non-mutating `to_regprocedure` probe, then the invocation if present. A successful call appends `run/sleep`, changes the row to `SLEEPING`, stores `available_at`, and releases the claim atomically. On a deliberately truncated tree without 0004, a negative probe—or an invocation failure with SQLSTATE `42883`—raises `CordisFeatureUnavailable` with code `P10_SLEEP_UNAVAILABLE`; the client never emulates sleep. Presence is not cached across calls.

## Await

`await_event` is a trusted worker verb. `accepted=false` → stop using the token. `should_suspend=true` → P03 already set WAITING and released the claim. Immediate resolve keeps the claim live. Do not expose `await_event` or `emit_event` as model tools unless a catalog row carries the exact `event` binding and P08 authorizes it. This client does not wrap `emit_event`.

## Lost responses and cancellation

Treat command timeout, killed `psql`, host SIGINT/SIGKILL, and orphan `psql` children as **unknown outcome**. `subprocess.run` does not kill the child on `KeyboardInterrupt`; an in-flight statement may still commit. Never automatically retry a mutation.

| Lost call | Reconcile with |
|---|---|
| Claim | `get_job`; do not assume ownership |
| Renew | inspect expiry; stop external work if uncertain |
| Checkpoint / scoped append | `llm_checkpoint` / fold / log by known run and step |
| Yield | `get_job` (`PENDING` vs still `RUNNING`) |
| Complete / fail | `get_job` and `run_state` (`final` / `error` / `awaiting` / `in-progress`) |
| Await | jobs status, `run_state`, P03 diagnostics |
| Register / unregister | `get_plugin` |

Deleting a client object does not yield a live token. Lease recovery owns cleanup.

## Not a model-tool surface

No `CordisHostClient` method is automatically a model tool. Do not put these in a model action schema:

- P01 claim / renew / yield / complete / fail / `release_stale`
- P02 `emit_step`, `emit_step_claimed`, `emit_step_scoped`, `checkpoint`
- P06 register / unregister / refresh
- P07 register / create / issue / approve / deny / revoke and `create_slice`
- P08 latch and internal fold helpers
- P09 `enqueue_job`, `worker_step`, `invoke_in_db_tool`, `_resolve_in_db_queue_handler`
- P03 `emit_event` / `await_event` unless catalog + P08 authorized
- P05 `step_once` / `kernel.step_once` / `invoke_llm`

P09 is a sibling in-database dispatcher. This client never calls it. Both loci share `cordis.jobs` and P01 verbs with distinct worker IDs.

## Packaging

Repo-local import only. `[tool.uv] package = false` stays false. No new runtime dependency. Tests pass `server.get_uri(database)` and `POSTGRES_BIN_PATH / "psql"` into the constructor.
