# pg_cordis SQL source tree

Canonical kernel SQL lives here. Later plan items add higher-numbered files; they must not edit the apply command’s file list.

## Filename contract

The apply command loads **direct children** of this directory whose names match. It reads every selected file **before** starting PostgreSQL or creating the target database. Psql meta-commands (`\\connect`, `\\include`, `\\ir`, `\\!`), `CREATE/DROP DATABASE`, `CREATE EXTENSION`, `GRANT`/`REVOKE`, role DDL, `BEGIN`/`COMMIT`/`ROLLBACK`, and `CREATE TABLE public.*` are rejected with exit 2. Later `cordis` table DDL is allowed.

```text
NNNN_slug.sql
```

- `NNNN` is exactly four decimal digits.
- `slug` starts with a lowercase letter or digit; remaining characters are `[a-z0-9_]`.
- Numeric prefixes must be unique.
- `0000_kernel.sql` is required.
- Gaps are allowed (`0000` then `0010`).
- Nested directories of `.sql` files are rejected.
- `README.md` is not executed.

Invalid examples: `kernel.sql`, `001_p01.sql`, `0001-p01.sql`, `0001_p01.SQL`.

Ordering is the numeric prefix. Discovery does not use a manifest.

## Release policy

Append a new numbered file for later work. Editing a historical file is not the intended release mechanism.

Every numbered file must be:

- safe to replay after the preceding files
- valid inside one tree-wide transaction
- schema-qualified (`cordis.*`), independent of `search_path`
- free of `\connect`, `\include`, `\ir`, `\!`, transaction-control, and database-creation commands
- free of `GRANT`, role creation, `CREATE EXTENSION`, and `public` objects

## Namespace

P00 creates schema `cordis` and `cordis.get_schema_version() → text`. The P00-only tree returns `p00`. This is an install marker, not agent runtime state.

The product is still called pg_cordis. PostgreSQL rejects schema names with the `pg_` prefix (`unacceptable schema name "pg_cordis"`), so the SQL namespace is `cordis`.

Kernel objects belong in `cordis`, not `public`. pg-agent’s research objects (`public.jobs`, …) are a different database.

## Apply command

From this repository:

```bash
cd "$CORDIS_ROOT"
uv run python tools/apply_pg_cordis.py \
  --pgdata "$CORDIS_ROOT/.pgdata" \
  --database cordis_p00
```

From any working directory:

```bash
uv run --project "$CORDIS_ROOT" python tools/apply_pg_cordis.py \
  --pgdata "$CORDIS_ROOT/.pgdata" \
  --database cordis_p00
```

`--database` must be a lowercase identifier `[a-z_][a-z0-9_]*`. `--reset` drops and recreates the target database (destructive; refused for `postgres` / `template0` / `template1`). Default without `--reset` is in-place replay.

`--pgdata` defaults to `$PGCORDIS_PGDATA` or `$CORDIS_ROOT/.pgdata`.

Do not call `CREATE EXTENSION`. Do not copy pg-agent SQL into this tree. `scratch/yield_walkthrough/` is proof-only and is not a source dependency.
