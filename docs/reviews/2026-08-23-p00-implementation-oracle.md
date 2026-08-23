# Oracle review: P00 implementation

Date: 2026-08-23  
Oracle: `prompt-exports/oracle-review-2026-08-23-164305-untitled-chat-a2176d-9101.md`  
Spec: `docs/plans/P00-sql-source-2026-08-23.md`  
Verdict: **no P0/blocker**. Core W00–W03 deliverables present. Intended schema rename `pg_cordis` → `cordis` accepted.

## P1 — should fix

Loader does not preflight file contents. Filename/layout only; `
connect` / `GRANT` / `CREATE DATABASE` etc. can still reach `psql` after DB create. Read files before `get_server()`; reject globally forbidden commands; exit 2 without creating the target DB. Do not ban legitimate later `cordis` table DDL.

## P2 — nits

- `verify_bootstrap()` should require `pronargs = 0` (overloads can fail a successful apply).
- Advisory lock uses a `DO`/`PERFORM` block instead of the specified `SELECT pg_advisory_xact_lock(...)`.
- Forbidden-token test is incomplete; add catalog assertion that `cordis` contains only the bootstrap function.
- Composition test should assert `cordis` is absent from `da_agent` and clean up `cordis_p00` (or unique disposable name).
- `RESET_FORBIDDEN` is unused; wire it into `validate_database_name()`.
