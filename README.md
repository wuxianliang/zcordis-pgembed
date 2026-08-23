# zcordis-pgembed

Postgres-hosted Cordis kernel (`pg_cordis`) developed as SQL in this repository, applied onto [pgembed](https://github.com/wuxianliang/pgembed).

P00 is the empty kernel: schema `cordis` plus `cordis.get_schema_version()`.

```bash
uv sync
uv run python tools/apply_pg_cordis.py --pgdata .pgdata --database cordis_p00
uv run pytest tests/test_p00_sql_source.py -q
```

Contract: `docs/decisions/2026-08-23-pending.md`  
Architecture: `docs/analysis/2026-08-23-i-architecture-snapshot.md`  
Development skeleton: `docs/plans/2026-08-23-pg-cordis-development.md`  
P00 plan: `docs/plans/P00-sql-source-2026-08-23.md`
