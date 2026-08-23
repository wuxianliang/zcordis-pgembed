# Oracle Review

## Summary

The implementation covers the core P00 deliverables: a canonical numbered SQL tree containing only the `cordis` namespace and `cordis.get_schema_version()`, a minimal `uv` project using the sibling `pgembed` dependency, dynamic SQL discovery, database creation/reset, advisory-lock serialization, tree-wide transactional application, post-commit bootstrap verification, and subprocess-based tests for replay, rollback, source-tree validation, and optional pg-agent composition. The current P00 SQL does not introduce P01+ objects, extensions, roles, grants, public objects, or vendored pg-agent SQL, and the CLI does not use the forbidden `PostgresServer.psql()` or `create_extension()` APIs. No P0/blocker issues were found.

## P1 — Should fix

### Source-tree safety rules are documented but not enforced by the loader

**File:** `tools/apply_pg_cordis.py` — `discover_sql_files()` and `apply_source_tree()`

The loader validates filenames and directory placement, but then sends each selected file’s raw contents directly to `psql`. It does not reject prohibited psql meta-commands such as `\connect`, `\include`, `\ir`, or `\!`, nor other globally forbidden operations such as transaction control, `CREATE DATABASE`, `CREATE EXTENSION`, role creation, or `GRANT`.

This matters because a validly named later file could switch the connection, execute a shell command, or invalidate the promised tree-wide transaction. The current `0000_kernel.sql` is clean, but the extensible source-tree contract is not protected against an accidental or malicious future file supplied through `--sql-root`.

Also, file contents are not read until after the target database has been created or reset. An unreadable or invalidly encoded numbered file therefore fails after database mutation rather than during source-tree validation.

**Suggestion:** Add a preflight phase that reads all selected files before `get_server()`/database creation and rejects the globally forbidden psql commands and DDL. Pass the preloaded contents into the apply phase. Add temporary-tree tests asserting that such files exit with code 2 and do not create the target database. The validator should avoid banning legitimate future `cordis` P01 DDL, such as tables that are intentionally introduced by later plan items.

## P2 — Nit / consider

### Bootstrap verification incorrectly considers overloads

**File:** `tools/apply_pg_cordis.py` — `verify_bootstrap()`

The verification query selects every function named `cordis.get_schema_version`, then requires the complete output to equal `|text`. If an existing database contains both the required no-argument function and an unrelated overload such as `cordis.get_schema_version(integer)`, the apply succeeds and commits, but verification returns exit code 1 even though the required bootstrap function exists.

This is inconsistent with the stated contract, which only requires the no-argument function returning `text`.

**Suggestion:** Restrict the catalog query to the no-argument overload, for example by adding `AND p.pronargs = 0`, and verify that exactly one matching function exists.

### The advisory lock is wrapped in an unnecessary `DO` block

**File:** `tools/apply_pg_cordis.py` — `apply_source_tree()`

The specification calls for `SELECT pg_advisory_xact_lock(hashtext('pg_cordis.apply'));` as the first statement. The implementation uses a PL/pgSQL `DO` block with `PERFORM` instead. It does acquire the intended transaction-scoped lock, so this is not a functional failure, but it adds an unnecessary dependency on the `plpgsql` language and deviates from the explicit protocol.

**Suggestion:** Emit the direct `SELECT pg_advisory_xact_lock(...)` statement as the first statement in the generated stream.

### The forbidden-scope test does not cover all P00 restrictions

**File:** `tests/test_p00_sql_source.py` — `test_sql_tree_has_no_forbidden_tokens()`

The test checks extensions, tables, leading `GRANT` statements, and lines beginning with a backslash, but it does not guard several documented restrictions, including role creation, database creation, transaction-control statements, `public` object definitions, `pg_cordis`/`absurd` namespaces, or the absence of P00 runtime objects beyond four relation names.

The current SQL is compliant, but these omissions make it easier for a future P00 edit to violate the contract without a test failure.

**Suggestion:** Expand the source-policy assertions for the restrictions that are globally forbidden, and add catalog assertions after a fresh install that the `cordis` schema contains only the bootstrap function and that no P00 objects appear in `public`.

### Composition testing does not fully prove database isolation and is not cleaned up

**File:** `tests/test_p00_sql_source.py` — `test_pg_agent_separate_database_composition()`

The composition test verifies that pg-agent’s `da_agent` retains `public.jobs` and that `cordis_p00` lacks several pg-agent relations, but it does not assert that `da_agent` lacks the P00 `cordis` schema/function. It also leaves `cordis_p00` in the external pg-agent PGDATA directory. Since the test uses an in-place apply rather than a fresh database, repeated runs can reuse objects from an earlier run and make the isolation check less deterministic.

**Suggestion:** Assert that `cordis` is absent from `da_agent`, and either use a unique disposable database name with a finalizer that force-drops it or explicitly document the persistent test database.

### `RESET_FORBIDDEN` is unused

**File:** `tools/apply_pg_cordis.py`

`RESET_FORBIDDEN` is declared but `validate_database_name()` duplicates the values with literals instead. This does not currently change behavior, but it is dead code and makes the reset policy less maintainable.

**Suggestion:** Either remove the constant or use it in the validation logic while preserving the special rule that `postgres` is allowed for non-reset in-place application but forbidden with `--reset`.