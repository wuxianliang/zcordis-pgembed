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

P00 creates schema `cordis` and `cordis.get_schema_version() → text`. This is an install marker, not agent runtime state. The latest numbered file wins:

```text
0000-only tree                  → p00
tree through 0001_p01_claim.sql → p01
tree through 0002_p02_log.sql   → p02
tree through 0003_p03_wait_event.sql → p03
tree through 0005_p05_one_step_driver.sql → p05
tree including 0006_p06_plugin_catalog.sql → p06
tree including 0007_p07_grant_registry.sql → p07  (current product tree)
```

`0002` adds `cordis.agent_steps` as the append-only history source of truth. Checkpoint is a log append (claim-fenced when `cordis.jobs` exists), not a `c_*` table. P02 does not create `agent_runs` or public objects.

`0003` adds kernel side tables `cordis.run_events` and `cordis.run_waits` plus `cordis.await_event` / `cordis.emit_event`. They serve the existing `cordis.jobs` row (status `WAITING`); they are not a second queue and not payload history. `run_events.payload` is a first-write fence (`SQL NULL` = not emitted). Canonical `event/emit` rows live on an internal `@event/<uuid>` log stream, which is not a jobs row. A tree that ends at `0003` reports `p03`.

`0005` adds the paradigm-neutral driver `cordis.step_once` and a replaceable SQL mock hook `cordis.invoke_llm`. One live claim processes at most one named step `s-N` (LLM checkpoint or mock invocation, then one mock tool observation or a final answer) and returns a text outcome. The caller maps yield / complete / fail through P01 claim verbs; P05 does not change jobs status, enqueue work, dispatch plugins, wait, retry, run a worker loop, or perform HTTP. Provider key is `md5(run_id || '/' || step_name)`. A tree that ends at `0005` reports `p05`; a tree that ends at `0006` reports `p06`; the current product tree ends at `0007` and reports `p07`.

`0006` adds `cordis.plugin_catalog` (compiled) and `cordis.host_plugin_definitions` (host source). In-database plugins author via `COMMENT` JSON on `cordis` functions; host tools use `cordis.register_host_plugin(jsonb)`. `cordis.refresh_plugins()` validates all candidates then `DELETE`+inserts the compiled catalog. After P06, `COMMENT` on `cordis` functions must not start with `{` unless it is a `cordis_plugin` definition. Put GRANT/END words in dollar-quoted function bodies, not in bare SQL.

Envelope (both COMMENT and host registration):

```json
{
  "cordis_plugin": {
    "identity": "host.worktree.apply_edits",
    "version": "0.1.0",
    "locus": "host",
    "invocation": "host_tool",
    "effect_class": "external",
    "retry_class": "idempotent",
    "reconciliation": "operation_key"
  }
}
```

Required: `identity`, `version`, `locus` (`in-db`|`host`), `invocation` (`queue`|`session_select`|`host_tool`), `effect_class`, `retry_class`, `reconciliation`. Legal pairs: in-db+queue, in-db+session_select, host+host_tool. `required_grants` is kinds only: `run` / `named_corpus` / `event` (no `named_corpus:<id>`). Optional DSH fields `inject` / `provide` / `intercept` / `capability` / `session_scope` / `config` are declarative metadata, never executed. Defaults when omitted: `name`→identity, `description`→name, `session_scope`→`run`, empty grants/inject/provide/capability/config objects or arrays as in the plan. JSON `null` for `capability` is rejected.

`0007` adds `cordis.named_corpora`, `cordis.slices`, and `cordis.grants`. Live rights are slice-bound D5 enums (`run` / `named_corpus:<id>` / `event:<scope>`). The model-facing writer is `cordis.request_grant` (never writes `issued`). Issue-family writers reject asserted `issuer_kind='model'` (provenance, not authentication). `named_corpus` is a live-root identity. A tree that ends at `0007` reports `p07`.

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
