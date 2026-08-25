# P10 implementation Oracle review

Date: 2026-08-25  
Oracle export (round 1): `prompt-exports/oracle-review-2026-08-25-220724-untitled-chat-7901c8-26c8.md`  
Oracle export (round 2): `prompt-exports/oracle-review-2026-08-25-221613-untitled-chat-7901c8-de99.md`  
Chat: `untitled-chat-7901C8`  
Plan: `docs/plans/P10-host-sql-seam-2026-08-25.md`  
Plan critique: `docs/reviews/2026-08-25-p10-plan-critique.md`

## Round 1

**Verdict:** not ready (no P0; two P1; four P2).

### P0

None.

### P1

1. `TimeoutExpired` / `JSONDecodeError` chained from `_run()` retained DSN (`cmd`) and stdout (`doc`). **Fix:** raise transport/protocol errors `from None`; replace DSN in `CordisSqlError` output; credential-bearing timeout traceback test.
2. Unqualified `md5` / JSON helpers could be search_path-shadowed, breaking P05 provider-key parity. **Fix:** qualify `pg_catalog.md5`, `to_jsonb`, `jsonb_agg`, `jsonb_build_object`, `jsonb_array_elements_text`, `array_agg`, `to_regprocedure`, and casts. `COALESCE`/`NULLIF` stay SQL keywords (`pg_catalog.coalesce(jsonb, jsonb)` does not exist). Shadow-`md5` test added.

### P2

1. `sleep_claim` uses two processes (probe then invoke). Documented; `42883` maps to `P10_SLEEP_UNAVAILABLE`.
2. Timeout/timestamp/UTF-8 validation tightened (`math.isfinite`, timezone `utcoffset()`, strict UTF-8 success decode).
3. Named-test gaps filled: NUL, empty stdout, `jobs.attempt`, await deadline/metadata, sleep presence after CREATE FUNCTION, in-db `session_select` refusal.
4. Stale plan sentence about critique gate. Folded.

## Round 2

**Verdict: ready.** P0 none, P1 none. P2 nits: 8 MiB envelope / NaN JSON coverage; record cross-protocol rerun. P2 does not block.

Tests: `uv run pytest tests/test_p10_host_sql_seam.py -q` → 18 passed after P1 fixes. Cross-protocol P00–P09/P19/P10 → 211 passed on the pre-P1 tree; P10-local suite re-verified after template qualification.
