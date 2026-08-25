# Oracle Review



The P10 change adds the planned repo-local synchronous Python host seam over existing `cordis` SQL: typed claim lifecycle and reconciliation, claim-fenced checkpoint/scoped append operations, step recovery and provider-key derivation, P03 await, optional P04 sleep detection, P06 catalog access, and authorize-only P08 host-tool metadata. It correctly adds no numbered SQL, dependency, worker loop, host callable execution, cache, P09 wrapper, or schema-marker change, and all 18 planned test names are present. The overall architecture and skeleton completion proof match the deep plan, but two safety/contract issues should be fixed before passing review.

## P1 — Should fix

1. **`pg_cordis_host/client.py` — timeout and parse exception chaining retains secrets that the error contract promises not to store**
   
   `_run()` re-raises `subprocess.TimeoutExpired` using `raise ... from exc`. The chained `TimeoutExpired` retains its `cmd`, which includes the full DSN passed to `psql`; a normal formatted traceback can therefore expose a URI password even though `repr(client)` is safe. Similarly, the chained `JSONDecodeError` retains the complete stdout document in `__cause__.doc`, which could contain a partial claimed-job response and claim token. This directly violates the deep plan’s requirement that exceptions not retain the DSN, argument document, SQL, or claim capabilities in structured fields.
   
   The current transport test does not catch this: the timeout client uses a credential-free DSN, and the `CordisSqlError` assertion checks `"supersecret"` against an error produced by a different, credential-free client.
   
   **Suggestion:** raise sanitized transport/protocol exceptions with `from None`, or construct a sanitized cause that excludes command arguments and response bodies. Also sanitize bounded server output before placing it in `CordisSqlError`, at least removing the DSN, full envelope, and known claim-token values. Add a regression test that formats the complete exception traceback and recursively inspects `__cause__`, `args`, and attributes after a timeout using a credential-bearing DSN.

2. **`pg_cordis_host/client.py` — fixed templates and the provider-key calculation depend on the ambient `search_path`**
   
   The client schema-qualifies `cordis` functions but leaves PostgreSQL helpers and types unqualified, including `md5`, `to_jsonb`, `jsonb_build_object`, `jsonb_agg`, `jsonb_array_elements_text`, `array_agg`, `to_regprocedure`, `jsonb`, and `timestamptz`. If the role or database explicitly configures a path such as `application, pg_catalog`, an application-schema overload can shadow these objects. Most importantly, `provider_idempotency_key()` can return an attacker- or application-defined `md5(text)` result that still matches the 32-hex local check but differs from P05, whose function executes with `search_path=pg_catalog`. This breaks the locked provider-key contract and may also execute unintended helper functions during otherwise fixed queries.
   
   **Suggestion:** qualify all built-ins and casts with `pg_catalog`, including the concatenation operator where needed, or otherwise establish a trusted startup search path before parsing the templates. Add a test using a database/role search path with a shadow `md5(text)` function and prove the client still returns `pg_catalog.md5(run_id || '/' || step_name)`.

## P2 — Consider

1. **`pg_cordis_host/client.py: CordisHostClient.sleep_claim` and `docs/host-sql-seam.md` — successful sleep uses two subprocesses despite the documented one-method/one-process contract**
   
   The absent-feature path launches one presence probe, but once P04 exists, one `sleep_claim()` call launches a second `psql` process for the mutation. That contradicts both “Each public method launches one `psql` process” and “One method = one committed statement,” and leaves a feature-check/use race: removing the function between calls produces a generic SQL error rather than `P10_SLEEP_UNAVAILABLE`.
   
   **Suggestion:** either redesign the fixed transport so the optional check and invocation use one process, or explicitly document `sleep_claim` as the sole two-command feature-probe exception. If retaining the current design, translate an invocation-time `42883` race into `P10_SLEEP_UNAVAILABLE` and document that only the second statement mutates state.

2. **`pg_cordis_host/client.py: _run`, `_parse_dt`, and `__init__` — protocol validation is looser than the declared typed contract**
   
   - stdout is decoded with `errors="replace"`, so a non-UTF-8 client encoding can silently corrupt JSON data while still yielding a successful typed result;
   - `_parse_dt()` accepts timestamps without an offset, although all result timestamps are documented as timezone-aware;
   - `_require_aware()` checks only `tzinfo is not None`, not that `utcoffset()` is available;
   - `command_timeout_seconds` accepts `NaN` and positive infinity.
   
   **Suggestion:** decode successful stdout strictly and map `UnicodeDecodeError` to `CordisProtocolError`; require parsed timestamps to have a usable UTC offset; and validate the timeout with `math.isfinite()`.

3. **`tests/test_p10_host_sql_seam.py` — all required test names exist, but several named tests do not cover their full deep-plan assertions**
   
   Notable omissions:
   
   - `test_p10_psql_transport_errors_and_output_validation` does not test the 8 MiB bound, NUL/NaN rejection, empty success output, or the credential-bearing timeout cause described above.
   - `test_p10_await_event_immediate_and_suspend_paths` does not exercise an aware deadline or nonempty `ui_metadata`.
   - `test_p10_sleep_is_typed_but_unavailable_without_p04` proves only one absent lookup, not that absence is uncached or that installing the exact signature after the first call is detected.
   - `test_p10_authorize_host_tool_is_read_only_and_non_executing` rejects an in-database queue row and a host external row, but not an in-database `session_select` row as W104 requires.
   - `test_p10_provider_key_matches_postgres_and_p05_guard` varies the worker and obtains a claim, but never changes `jobs.attempt` as its named proof requires.
   
   **Suggestion:** extend the existing named tests with those cases. A disposable test-only sleep function and in-database `session_select` COMMENT fixture are sufficient; no product SQL is needed.

4. **`docs/plans/P10-host-sql-seam-2026-08-25.md` — one stale status sentence contradicts the finalized plan**
   
   The plan header and critique fold correctly say `ready to implement`, but the Resolved Decisions section still says, “The only reason Status is not yet `ready to implement` is the required plan-critique gate.”
   
   **Suggestion:** replace it with a sentence confirming that the critique gate has been completed and all blocking findings were folded.