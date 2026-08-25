"""P04 sleep, wait-timeout, and task-level retry tests."""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import pytest
from pgembed import get_server

from tests.conftest import SQL, load_apply_module, psql, psql_session, run_apply

P04_ONLY_DB = "cordis_p04_only"
P04_FILES = (
    "0000_kernel.sql",
    "0001_p01_claim.sql",
    "0002_p02_log.sql",
    "0003_p03_wait_event.sql",
    "0004_p04_sleep_retry.sql",
)
NEW_IDS = (
    "cordis.resolve_due_waits(text,integer)",
    "cordis.retry_delay_seconds(integer,double precision,double precision,double precision)",
    "cordis.sleep_claim(uuid,text,timestamp with time zone,integer)",
)
REVISED_IDS = (
    "cordis.claim_job(text,text,integer)",
    "cordis.fail_claim(uuid,jsonb)",
    "cordis.release_stale(text,integer)",
)
POLICY_CONSTRAINTS = (
    "jobs_max_attempts_check",
    "jobs_retry_backoff_base_check",
    "jobs_retry_backoff_factor_check",
    "jobs_retry_backoff_max_check",
    "jobs_retry_backoff_bounds_check",
)
EXPECTED_DEFAULTS = {
    "max_attempts": "3",
    "retry_backoff_base_seconds": "30",
    "retry_backoff_factor": "2",
    "retry_backoff_max_seconds": "86400",
}
EXPECTED_CHECKS = {
    "jobs_max_attempts_check": "((max_attempts IS NULL) OR (max_attempts >= 1))",
    "jobs_retry_backoff_base_check": "((retry_backoff_base_seconds > '-Infinity'::double precision) AND (retry_backoff_base_seconds < 'Infinity'::double precision) AND (retry_backoff_base_seconds >= (0)::double precision) AND (retry_backoff_base_seconds <= (86400)::double precision))",
    "jobs_retry_backoff_bounds_check": "(retry_backoff_base_seconds <= retry_backoff_max_seconds)",
    "jobs_retry_backoff_factor_check": "((retry_backoff_factor > '-Infinity'::double precision) AND (retry_backoff_factor < 'Infinity'::double precision) AND (retry_backoff_factor >= (1)::double precision))",
    "jobs_retry_backoff_max_check": "((retry_backoff_max_seconds > '-Infinity'::double precision) AND (retry_backoff_max_seconds < 'Infinity'::double precision) AND (retry_backoff_max_seconds >= (0)::double precision) AND (retry_backoff_max_seconds <= (86400)::double precision))",
}


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _jsonb(value: str) -> str:
    return _sql_str(value) + "::jsonb"


def _apply_p04_only(pgdata: Path, tmp_path: Path) -> str:
    tree = tmp_path / "sql_p04_only"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir()
    for name in P04_FILES:
        shutil.copy(SQL / name, tree / name)
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P04_ONLY_DB,
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def _insert_and_claim(
    server, database: str, run_id: str, worker: str = "worker-a", **job_set: str
) -> str:
    extra = ""
    if job_set:
        assignments = ", ".join(f"{k} = {v}" for k, v in job_set.items())
        extra = f"; UPDATE cordis.jobs SET {assignments} WHERE run_id = {_sql_str(run_id)}"
    psql(
        server,
        database,
        "INSERT INTO cordis.jobs (run_id, job_type) "
        f"VALUES ({_sql_str(run_id)}, 'p04_test'){extra};",
    )
    token = psql(
        server,
        database,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, "
        f"{_sql_str(worker)}, 90);",
    )
    assert token, run_id
    return token


def _await_sql(
    token: str,
    run_id: str,
    scope: str,
    name: str,
    await_id: str,
    deadline: str | None = None,
) -> str:
    dl = "NULL" if deadline is None else _sql_str(deadline) + "::timestamptz"
    return (
        "SELECT CASE WHEN accepted THEN 't' ELSE 'f' END || '|' || "
        "CASE WHEN should_suspend THEN 't' ELSE 'f' END FROM cordis.await_event("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, {_sql_str(scope)}, "
        f"{_sql_str(name)}, {_sql_str(await_id)}::uuid, {dl}, '{{}}'::jsonb, 90)"
    )


def _emit_sql(scope: str, name: str, payload: str) -> str:
    return (
        "SELECT CASE WHEN emitted THEN 't' ELSE 'f' END || '|' || woken_count::text "
        f"FROM cordis.emit_event({_sql_str(scope)}, {_sql_str(name)}, {_jsonb(payload)})"
    )


def _wait_for_blocked_backend(server, database: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        waiting = psql(
            server,
            database,
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND wait_event_type = 'Lock' "
            "AND pid <> pg_backend_pid();",
        )
        if int(waiting) >= 1:
            return
        time.sleep(0.05)
    raise AssertionError("expected another backend to wait on a lock")


def _run_state(server, database: str, run_id: str) -> str:
    return psql(
        server,
        database,
        f"SELECT status FROM cordis.run_state({_sql_str(run_id)});",
    )


def _strip_sql_comments(src: str) -> str:
    scanned = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    lines = []
    for line in scanned.splitlines():
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def test_p04_fresh_apply_catalog_and_version(pgdata: Path, tmp_path: Path) -> None:
    out = _apply_p04_only(pgdata, tmp_path)
    assert (
        "files=0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,"
        "0003_p03_wait_event.sql,0004_p04_sleep_retry.sql"
        in out
    )
    server = get_server(pgdata)
    assert psql(server, P04_ONLY_DB, "SELECT cordis.get_schema_version();") == "p04"
    for rel in ("jobs", "agent_steps", "run_events", "run_waits"):
        assert (
            psql(
                server,
                P04_ONLY_DB,
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                f"WHERE n.nspname = 'cordis' AND c.relkind = 'r' AND c.relname = '{rel}';",
            )
            == "1"
        )
    tables = psql(
        server,
        P04_ONLY_DB,
        "SELECT c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relkind = 'r' "
        "ORDER BY 1;",
    ).splitlines()
    assert tables == ["agent_steps", "jobs", "run_events", "run_waits"]
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'cordis' "
            "AND c.relname = 'plugin_catalog';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT count(*) FROM pg_namespace WHERE nspname = 'absurd';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
            "AND c.relkind = 'r' AND c.relname NOT LIKE 'pg_%';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT count(*) FROM pg_extension WHERE extname = 'pg_cordis';",
        )
        == "0"
    )
    for identity in NEW_IDS + REVISED_IDS:
        assert (
            psql(
                server,
                P04_ONLY_DB,
                f"SELECT to_regprocedure({_sql_str(identity)}) IS NOT NULL;",
            )
            == "t"
        ), identity
    delay_meta = psql(
        server,
        P04_ONLY_DB,
        "SELECT p.provolatile::text || '|' || p.prosecdef::text || '|' || "
        "COALESCE(array_to_string(p.proconfig, ','), '') "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname = 'retry_delay_seconds';",
    )
    assert delay_meta.startswith("i|false|")
    assert "search_path=pg_catalog" in delay_meta
    for name in ("sleep_claim", "resolve_due_waits", "fail_claim", "release_stale", "claim_job"):
        meta = psql(
            server,
            P04_ONLY_DB,
            "SELECT p.provolatile::text || '|' || p.prosecdef::text || '|' || l.lanname "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_language l ON l.oid = p.prolang "
            f"WHERE n.nspname = 'cordis' AND p.proname = '{name}';",
        )
        assert meta.startswith("v|false|plpgsql"), (name, meta)
    version_meta = psql(
        server,
        P04_ONLY_DB,
        "SELECT p.provolatile::text || '|' || p.prosecdef::text || '|' || l.lanname || '|' || "
        "p.pronargs::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_language l ON l.oid = p.prolang "
        "WHERE n.nspname = 'cordis' AND p.proname = 'get_schema_version' AND p.pronargs = 0;",
    )
    assert version_meta == "i|false|sql|0"
    overloads = psql(
        server,
        P04_ONLY_DB,
        "SELECT proname || '=' || count(*)::text FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN "
        "('sleep_claim','resolve_due_waits','retry_delay_seconds',"
        "'fail_claim','release_stale','claim_job') "
        "GROUP BY proname HAVING count(*) <> 1;",
    )
    assert overloads == ""


def test_p04_retry_policy_columns_constraints_and_indexes(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    cols = psql(
        server,
        P04_ONLY_DB,
        "SELECT attname || ':' || pg_catalog.format_type(atttypid, atttypmod) "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs' "
        "AND a.attnum > 0 AND NOT a.attisdropped;",
    )
    assert "max_attempts:integer" in cols
    assert "retry_backoff_base_seconds:double precision" in cols
    assert "retry_backoff_factor:double precision" in cols
    assert "retry_backoff_max_seconds:double precision" in cols
    names = psql(
        server,
        P04_ONLY_DB,
        "SELECT conname FROM pg_constraint x "
        "JOIN pg_class c ON c.oid = x.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs';",
    )
    for constraint in POLICY_CONSTRAINTS:
        assert constraint in names, names
    defaults_catalog = dict(
        line.split("|", 1)
        for line in psql(
            server,
            P04_ONLY_DB,
            "SELECT a.attname || '|' || pg_get_expr(d.adbin, d.adrelid) "
            "FROM pg_attribute a JOIN pg_attrdef d "
            "ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE a.attrelid = 'cordis.jobs'::regclass "
            "AND a.attname IN ('max_attempts','retry_backoff_base_seconds',"
            "'retry_backoff_factor','retry_backoff_max_seconds') ORDER BY a.attname;",
        ).splitlines()
    )
    assert defaults_catalog == EXPECTED_DEFAULTS
    checks_catalog = psql(
        server,
        P04_ONLY_DB,
        "SELECT jsonb_object_agg(conname, pg_get_expr(conbin, conrelid) "
        "ORDER BY conname)::text FROM pg_constraint "
        "WHERE conrelid = 'cordis.jobs'::regclass AND contype = 'c' AND "
        "(conname LIKE 'jobs_retry_%_check' OR conname = 'jobs_max_attempts_check');",
    )
    assert json.loads(checks_catalog) == EXPECTED_CHECKS
    ready = psql(
        server,
        P04_ONLY_DB,
        "SELECT pg_get_indexdef(c.oid) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs_ready_idx';",
    )
    assert "PENDING" in ready and "SLEEPING" in ready
    assert "WAITING" not in ready
    deadline_idx = psql(
        server,
        P04_ONLY_DB,
        "SELECT pg_get_indexdef(c.oid) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'run_waits_deadline_idx';",
    )
    assert deadline_idx == (
        "CREATE INDEX run_waits_deadline_idx ON cordis.run_waits USING btree "
        "(deadline, event_scope_id, event_name, run_id) "
        "WHERE (deadline IS NOT NULL)"
    )
    defaults = psql(
        server,
        P04_ONLY_DB,
        "INSERT INTO cordis.jobs (run_id, job_type) VALUES ('p04-defaults', 't'); "
        "SELECT coalesce(max_attempts::text, 'null') || '|' || "
        "retry_backoff_base_seconds::text || '|' || "
        "retry_backoff_factor::text || '|' || "
        "retry_backoff_max_seconds::text "
        "FROM cordis.jobs WHERE run_id = 'p04-defaults';",
    )
    assert defaults.split("|") == ["3", "30", "2", "86400"]
    psql(
        server,
        P04_ONLY_DB,
        "INSERT INTO cordis.jobs (run_id, job_type, max_attempts) "
        "VALUES ('p04-unlimited', 't', NULL);",
    )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P04_ONLY_DB,
            "INSERT INTO cordis.jobs (run_id, job_type, max_attempts) "
            "VALUES ('p04-bad-max', 't', 0);",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P04_ONLY_DB,
            "INSERT INTO cordis.jobs (run_id, job_type, retry_backoff_factor) "
            "VALUES ('p04-nan-factor', 't', 'NaN'::float8);",
        )
    for bad_sql in (
        "INSERT INTO cordis.jobs (run_id, job_type, retry_backoff_base_seconds) "
        "VALUES ('p04-nan-base', 't', 'NaN'::float8);",
        "INSERT INTO cordis.jobs (run_id, job_type, retry_backoff_base_seconds) "
        "VALUES ('p04-neg-base', 't', -1);",
        "INSERT INTO cordis.jobs (run_id, job_type, retry_backoff_factor) "
        "VALUES ('p04-inf-factor', 't', 'Infinity'::float8);",
        "INSERT INTO cordis.jobs (run_id, job_type, retry_backoff_max_seconds) "
        "VALUES ('p04-neg-max', 't', -1);",
        "INSERT INTO cordis.jobs (run_id, job_type, "
        "retry_backoff_base_seconds, retry_backoff_max_seconds) "
        "VALUES ('p04-base-over-cap', 't', 40, 30);",
    ):
        with pytest.raises(RuntimeError):
            psql(server, P04_ONLY_DB, bad_sql)
    tiny = psql(
        server,
        P04_ONLY_DB,
        "SELECT cordis.retry_delay_seconds(8, 1e-320::float8, 2, 86400) "
        "IS DISTINCT FROM 'Infinity'::float8;",
    )
    assert tiny == "t"


def test_p04_retry_delay_defaults_caps_and_validation(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    assert psql(server, P04_ONLY_DB, "SELECT cordis.retry_delay_seconds(1);") == "30"
    assert psql(server, P04_ONLY_DB, "SELECT cordis.retry_delay_seconds(2);") == "60"
    assert psql(server, P04_ONLY_DB, "SELECT cordis.retry_delay_seconds(3);") == "120"
    assert (
        psql(server, P04_ONLY_DB, "SELECT cordis.retry_delay_seconds(2, 30, 1, 86400);")
        == "30"
    )
    assert (
        psql(server, P04_ONLY_DB, "SELECT cordis.retry_delay_seconds(5, 0, 2, 86400);")
        == "0"
    )
    capped = psql(server, P04_ONLY_DB, "SELECT cordis.retry_delay_seconds(20);")
    assert capped == "86400"
    huge = psql(server, P04_ONLY_DB, "SELECT cordis.retry_delay_seconds(1000);")
    assert huge == "86400"
    no_overflow = psql(
        server,
        P04_ONLY_DB,
        "SELECT cordis.retry_delay_seconds("
        "3, 1e-320::float8, 1e155::float8, 86400);",
    )
    assert no_overflow not in ("Infinity", "-Infinity", "NaN")
    assert abs(float(no_overflow) - 1e-10) / 1e-10 < 0.05
    for bad in (
        "SELECT cordis.retry_delay_seconds(0);",
        "SELECT cordis.retry_delay_seconds(1, 'NaN'::float8, 2, 86400);",
        "SELECT cordis.retry_delay_seconds(1, 30, 'Infinity'::float8, 86400);",
        "SELECT cordis.retry_delay_seconds(1, 30, 'NaN'::float8, 86400);",
        "SELECT cordis.retry_delay_seconds(1, '-Infinity'::float8, 2, 86400);",
        "SELECT cordis.retry_delay_seconds(1, 30, 2, 'Infinity'::float8);",
        "SELECT cordis.retry_delay_seconds(1, 40, 2, 30);",
        "SELECT cordis.retry_delay_seconds(1, 30, 0.5, 86400);",
    ):
        with pytest.raises(RuntimeError):
            psql(server, P04_ONLY_DB, bad)


def test_p04_sleep_claim_logs_and_transitions(pgdata: Path, tmp_path: Path) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-sleep"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    until = "2099-06-01 00:00:00+00"
    ok = psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, {_sql_str(run_id)}, "
        f"{_sql_str(until)}::timestamptz, 90);",
    )
    assert ok == "t"
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || available_at::text || '|' || attempt::text || '|' || "
        "(claim_token IS NULL)::text || '|' || (claimed_by IS NULL)::text || '|' || "
        "(claim_expires_at IS NULL)::text || '|' || (completed_at IS NULL)::text || '|' || "
        "(result IS NULL)::text || '|' || (error IS NULL)::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    parts = row.split("|")
    assert parts[0] == "SLEEPING"
    assert until in parts[1] or parts[1].startswith("2099-06-01")
    assert parts[2:] == ["1", "true", "true", "true", "true", "true", "true"]
    log = psql(
        server,
        P04_ONLY_DB,
        "SELECT kind || '|' || coalesce(step_name, '') || '|' || (payload->>'reason') "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} ORDER BY seq DESC LIMIT 1;",
    )
    assert log == "run/sleep||sleep"


def test_p04_sleep_rollback_preserves_running_claim(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-sleep-rb"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    with psql_session(server, P04_ONLY_DB) as session:
        session.execute("BEGIN")
        ok = session.execute(
            f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, {_sql_str(run_id)}, "
            f"'2099-01-01 00:00:00+00'::timestamptz, 90);"
        )
        assert ok == ["t"]
        session.rollback()
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || claim_token::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    status, still = row.split("|")
    assert status == "RUNNING"
    assert still == token
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} "
            "AND kind = 'run/sleep';",
        )
        == "0"
    )


def test_p04_sleep_lost_claim_and_parameter_errors(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-sleep-err"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    with pytest.raises(RuntimeError):
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, '  ', "
            f"'2099-01-01 00:00:00+00'::timestamptz, 90);",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, {_sql_str(run_id)}, "
            f"'infinity'::timestamptz, 90);",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, {_sql_str(run_id)}, "
            f"'2099-01-01 00:00:00+00'::timestamptz, 0);",
        )
    lost = psql(
        server,
        P04_ONLY_DB,
        "SELECT cordis.sleep_claim('00000000-0000-0000-0000-000000000099'::uuid, "
        f"{_sql_str(run_id)}, '2099-01-01 00:00:00+00'::timestamptz, 90);",
    )
    assert lost == "f"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "RUNNING"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )


def test_p04_due_sleep_is_claimed_and_logs_wake(pgdata: Path, tmp_path: Path) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    future_id = "p04-sleep-future"
    token = _insert_and_claim(server, P04_ONLY_DB, future_id)
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, {_sql_str(future_id)}, "
        f"'2099-01-01 00:00:00+00'::timestamptz, 90);",
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.claim_job({_sql_str(future_id)}, 'w2', 90);",
        )
        == "0"
    )
    due_id = "p04-sleep-due"
    due_token = _insert_and_claim(server, P04_ONLY_DB, due_id)
    job_id = psql(
        server,
        P04_ONLY_DB,
        f"SELECT job_id::text FROM cordis.jobs WHERE run_id = {_sql_str(due_id)};",
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.sleep_claim({_sql_str(due_token)}::uuid, {_sql_str(due_id)}, "
        f"clock_timestamp() - interval '1 second', 90);",
    )
    claimed = psql(
        server,
        P04_ONLY_DB,
        "SELECT job_id::text || '|' || run_id || '|' || attempt::text || '|' || "
        "status || '|' || (claim_token IS NOT NULL)::text || '|' || claim_token::text "
        f"FROM cordis.claim_job({_sql_str(due_id)}, 'w2', 90);",
    )
    parts = claimed.split("|")
    assert parts[0] == job_id
    assert parts[1] == due_id
    assert parts[2] == "1"
    assert parts[3] == "RUNNING"
    assert parts[4] == "true"
    assert parts[5] != due_token
    wake = psql(
        server,
        P04_ONLY_DB,
        "SELECT kind || '|' || (payload->>'wake_reason') || '|' || "
        "coalesce(payload->>'await_id','') "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(due_id)} AND kind = 'run/wake';",
    )
    assert wake == "run/wake|sleep|"


def test_p04_due_sleep_claim_rollback_has_no_wake(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-sleep-claim-rb"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, {_sql_str(run_id)}, "
        f"clock_timestamp() - interval '1 second', 90);",
    )
    with psql_session(server, P04_ONLY_DB) as session:
        session.execute("BEGIN")
        claimed = session.execute(
            f"SELECT status FROM cordis.claim_job({_sql_str(run_id)}, 'w2', 90);"
        )
        assert claimed == ["RUNNING"]
        session.rollback()
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "SLEEPING"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} "
            "AND kind = 'run/wake';",
        )
        == "0"
    )


def _suspend_due_wait(server, run_id: str, scope: str, deadline: str | None) -> str:
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    await_id = str(uuid.uuid4())
    row = psql(
        server,
        P04_ONLY_DB,
        _await_sql(token, run_id, scope, "n", await_id, deadline),
    )
    assert row.startswith("t|t|") or row == "t|t"
    return await_id


def test_p04_wait_timeout_wakes_and_folds_state(pgdata: Path, tmp_path: Path) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-timeout"
    await_id = _suspend_due_wait(
        server, run_id, "scope-timeout", "2000-01-01 00:00:00+00"
    )
    assert _run_state(server, P04_ONLY_DB, run_id) == "awaiting"
    n = psql(server, P04_ONLY_DB, "SELECT cordis.resolve_due_waits(NULL, 100);")
    assert n == "1"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "PENDING"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT CASE WHEN payload IS NULL THEN 't' ELSE 'f' END "
            "FROM cordis.run_events WHERE event_scope_id = 'scope-timeout';",
        )
        == "t"
    )
    wake = psql(
        server,
        P04_ONLY_DB,
        "SELECT (payload->>'wake_reason') || '|' || (payload->>'await_id') "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} AND kind = 'run/wake';",
    )
    assert wake == f"timeout|{await_id}"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps WHERE kind = 'event/emit';",
        )
        == "0"
    )
    assert _run_state(server, P04_ONLY_DB, run_id) == "in-progress"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.claim_job({_sql_str(run_id)}, 'w2', 90);",
        )
        == "RUNNING"
    )


def test_p04_wait_deadline_null_past_and_infinities(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    past_id = "p04-dl-past"
    _suspend_due_wait(server, past_id, "scope-dl-past", "-infinity")
    null_id = "p04-dl-null"
    _suspend_due_wait(server, null_id, "scope-dl-null", None)
    inf_id = "p04-dl-inf"
    _suspend_due_wait(server, inf_id, "scope-dl-inf", "infinity")
    before_avail = psql(
        server,
        P04_ONLY_DB,
        f"SELECT available_at::text FROM cordis.jobs WHERE run_id = {_sql_str(null_id)};",
    )
    n = psql(server, P04_ONLY_DB, "SELECT cordis.resolve_due_waits(NULL, 100);")
    assert n == "1"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(past_id)};",
        )
        == "PENDING"
    )
    for run_id in (null_id, inf_id):
        assert (
            psql(
                server,
                P04_ONLY_DB,
                f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
            )
            == "WAITING"
        )
        assert (
            psql(
                server,
                P04_ONLY_DB,
                f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
            )
            == "1"
        )
    after_avail = psql(
        server,
        P04_ONLY_DB,
        f"SELECT available_at::text FROM cordis.jobs WHERE run_id = {_sql_str(null_id)};",
    )
    assert after_avail == before_avail
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps WHERE kind = 'run/wake';",
        )
        == "1"
    )


def test_p04_duplicate_timeout_resolution_is_noop(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-dup-timeout"
    _suspend_due_wait(server, run_id, "scope-dup-to", "2000-01-01 00:00:00+00")
    assert psql(server, P04_ONLY_DB, "SELECT cordis.resolve_due_waits(NULL, 100);") == "1"
    assert psql(server, P04_ONLY_DB, "SELECT cordis.resolve_due_waits(NULL, 100);") == "0"


def test_p04_timeout_selects_oldest_deadline_first(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    older = "p04-dl-older"
    newer = "p04-dl-newer"
    _suspend_due_wait(server, older, "zz-scope", "1990-01-01 00:00:00+00")
    _suspend_due_wait(server, newer, "aa-scope", "2000-01-01 00:00:00+00")
    n = psql(server, P04_ONLY_DB, "SELECT cordis.resolve_due_waits(NULL, 1);")
    assert n == "1"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(older)};",
        )
        == "PENDING"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(newer)};",
        )
        == "WAITING"
    )


def test_p04_two_sweepers_older_deadline_insert_does_not_deadlock(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-sweep-replaced"
    pause_run = "p04-sweep-pause"
    old_scope = "scope-a-old"
    new_scope = "scope-b-new"
    pause_scope = "scope-z-pause"
    _suspend_due_wait(server, run_id, old_scope, "2000-01-01 00:00:00+00")
    _suspend_due_wait(server, pause_run, pause_scope, "2000-01-02 00:00:00+00")
    psql(
        server,
        P04_ONLY_DB,
        "INSERT INTO cordis.run_events (event_scope_id, event_name) "
        f"VALUES ({_sql_str(new_scope)}, 'n');",
    )

    first_results: list[str] = []
    first_errors: list[BaseException] = []
    second_results: list[str] = []
    second_errors: list[BaseException] = []

    def sweep_first() -> None:
        try:
            first_results.append(
                psql(
                    server,
                    P04_ONLY_DB,
                    "SET statement_timeout = '8s'; "
                    "SELECT cordis.resolve_due_waits(NULL, 100);",
                )
            )
        except BaseException as exc:
            first_errors.append(exc)

    def sweep_second() -> None:
        try:
            second_results.append(
                psql(
                    server,
                    P04_ONLY_DB,
                    "SET statement_timeout = '8s'; "
                    f"SELECT cordis.resolve_due_waits({_sql_str(run_id)}, 100);",
                )
            )
        except BaseException as exc:
            second_errors.append(exc)

    with psql_session(server, P04_ONLY_DB) as old_blocker, psql_session(
        server, P04_ONLY_DB
    ) as pause_blocker:
        old_blocker.execute("BEGIN")
        old_blocker.execute("SET LOCAL statement_timeout = '8s'")
        old_blocker.execute(
            "SELECT event_scope_id FROM cordis.run_events "
            f"WHERE event_scope_id={_sql_str(old_scope)} AND event_name='n' "
            "FOR UPDATE"
        )
        pause_blocker.execute("BEGIN")
        pause_blocker.execute("SET LOCAL statement_timeout = '8s'")
        pause_blocker.execute(
            "SELECT event_scope_id FROM cordis.run_events "
            f"WHERE event_scope_id={_sql_str(pause_scope)} AND event_name='n' "
            "FOR UPDATE"
        )

        first = threading.Thread(target=sweep_first)
        first.start()
        _wait_for_blocked_backend(server, P04_ONLY_DB)

        # Trusted test-only mutation simulates a legitimately replaced wait
        # after sweeper A materialized the old event-key candidate.
        psql(
            server,
            P04_ONLY_DB,
            "UPDATE cordis.run_waits SET event_scope_id="
            f"{_sql_str(new_scope)} WHERE run_id={_sql_str(run_id)};",
        )
        second = threading.Thread(target=sweep_second)
        second.start()
        second.join(timeout=10)
        assert not second.is_alive()
        assert second_errors == []
        assert second_results == ["1"]

        # A now passes the stale old-event candidate and blocks on pause_scope.
        # The fixed implementation never locked jobs(run_id), so NOWAIT works.
        # The pre-fix implementation retained that jobs lock and fails here.
        old_blocker.commit()
        _wait_for_blocked_backend(server, P04_ONLY_DB)
        assert psql(
            server,
            P04_ONLY_DB,
            "SELECT job_id FROM cordis.jobs "
            f"WHERE run_id={_sql_str(run_id)} FOR UPDATE NOWAIT;",
        )

        pause_blocker.commit()
        first.join(timeout=10)
        assert not first.is_alive()

    assert first_errors == []
    assert first_results == ["1"]
    assert psql(
        server,
        P04_ONLY_DB,
        "SELECT run_id || '|' || count(*)::text FROM cordis.agent_steps "
        "WHERE kind='run/wake' GROUP BY run_id ORDER BY run_id;",
    ).splitlines() == [f"{pause_run}|1", f"{run_id}|1"]

def test_p04_emit_timeout_race_has_one_wake(pgdata: Path, tmp_path: Path) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)

    run_a = "p04-race-to"
    await_a = _suspend_due_wait(server, run_a, "scope-race-to", "2000-01-01 00:00:00+00")
    emit_results: list[str] = []
    emit_errors: list[BaseException] = []

    def emit_blocked() -> None:
        try:
            emit_results.append(
                psql(
                    server,
                    P04_ONLY_DB,
                    "SET statement_timeout = '8s'; "
                    + _emit_sql("scope-race-to", "n", '{"w":1}'),
                )
            )
        except Exception as exc:
            emit_errors.append(exc)

    with psql_session(server, P04_ONLY_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        resolved = session.execute("SELECT cordis.resolve_due_waits(NULL, 100);")
        assert resolved == ["1"]
        thread = threading.Thread(target=emit_blocked)
        thread.start()
        _wait_for_blocked_backend(server, P04_ONLY_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert emit_errors == []
    assert emit_results and emit_results[0] == "t|0"
    wakes = psql(
        server,
        P04_ONLY_DB,
        f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_a)} "
        "AND kind = 'run/wake';",
    )
    assert wakes == "1"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT payload->>'wake_reason' FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_a)} AND kind = 'run/wake';",
        )
        == "timeout"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_a)};",
        )
        == "0"
    )
    assert await_a

    run_b = "p04-race-em"
    _suspend_due_wait(server, run_b, "scope-race-em", "2000-01-01 00:00:00+00")
    timeout_results: list[str] = []
    timeout_errors: list[BaseException] = []

    def timeout_blocked() -> None:
        try:
            timeout_results.append(
                psql(
                    server,
                    P04_ONLY_DB,
                    "SET statement_timeout = '8s'; SELECT cordis.resolve_due_waits(NULL, 100);",
                )
            )
        except Exception as exc:
            timeout_errors.append(exc)

    with psql_session(server, P04_ONLY_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        emitted = session.execute(_emit_sql("scope-race-em", "n", '{"e":1}'))
        assert emitted[0] == "t|1"
        thread = threading.Thread(target=timeout_blocked)
        thread.start()
        _wait_for_blocked_backend(server, P04_ONLY_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert timeout_errors == []
    assert timeout_results and timeout_results[0] == "0"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_b)} "
            "AND kind = 'run/wake';",
        )
        == "1"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT payload ? 'source_run_id' FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_b)} AND kind = 'run/wake';",
        )
        == "t"
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_b)};",
        )
        == "PENDING"
    )


def test_p04_claim_piggybacks_wait_timeout(pgdata: Path, tmp_path: Path) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-piggy"
    _suspend_due_wait(server, run_id, "scope-piggy", "2000-01-01 00:00:00+00")
    claimed = psql(
        server,
        P04_ONLY_DB,
        f"SELECT status FROM cordis.claim_job({_sql_str(run_id)}, 'w2', 90);",
    )
    assert claimed == "RUNNING"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )


def test_p04_fail_requeues_same_row_with_default_backoff(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-fail-retry"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    job_id = psql(
        server,
        P04_ONLY_DB,
        f"SELECT job_id::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    t0 = psql(server, P04_ONLY_DB, "SELECT clock_timestamp()::text;")
    ok = psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, {_jsonb('{\"reason\":\"boom\"}')});",
    )
    assert ok == "t"
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT job_id::text || '|' || run_id || '|' || status || '|' || attempt::text || '|' || "
        "(claim_token IS NULL)::text || '|' || (error IS NULL)::text || '|' || "
        "EXTRACT(EPOCH FROM (available_at - clock_timestamp()))::int::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    parts = row.split("|")
    assert parts[0] == job_id
    assert parts[1] == run_id
    assert parts[2] == "SLEEPING"
    assert parts[3] == "2"
    assert parts[4] == "true"
    assert parts[5] == "true"
    lag = int(parts[6])
    assert 20 <= lag <= 40, lag
    log = psql(
        server,
        P04_ONLY_DB,
        "SELECT kind || '|' || (payload->>'reason') || '|' || (payload->>'failed_attempt') "
        "|| '|' || (payload->>'next_attempt') || '|' || (payload->>'delay_seconds') "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} ORDER BY seq DESC LIMIT 1;",
    )
    assert log == "run/sleep|retry|1|2|30"
    psql(
        server,
        P04_ONLY_DB,
        "UPDATE cordis.jobs SET available_at = '-infinity'::timestamptz "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    claimed = psql(
        server,
        P04_ONLY_DB,
        f"SELECT status FROM cordis.claim_job({_sql_str(run_id)}, 'w2', 90);",
    )
    assert claimed == "RUNNING"
    wake = psql(
        server,
        P04_ONLY_DB,
        "SELECT payload->>'wake_reason' FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)} AND kind = 'run/wake';",
    )
    assert wake == "sleep"
    _ = t0


def test_p04_fail_with_prewritten_error_is_terminal(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-fail-prewritten"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    payload = '{"protocol":"p04.test","code":"PREWRITTEN"}'
    assert psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.emit_step_claimed({_sql_str(token)}::uuid, "
        f"{_sql_str(run_id)}, 'error', {_jsonb(payload)}, NULL, 90);",
    ) == "t"
    assert psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, "
        f"{_jsonb('{\"reason\":\"ignored\"}')});",
    ) == "t"
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || attempt::text || '|' || "
        "(error->>'code') || '|' || (completed_at IS NOT NULL)::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert row == "ERROR|1|PREWRITTEN|true"
    counts = psql(
        server,
        P04_ONLY_DB,
        "SELECT count(*) FILTER (WHERE kind='error')::text || '|' || "
        "count(*) FILTER (WHERE kind='run/sleep')::text "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
    )
    assert counts == "1|0"


def test_p04_fail_preserves_incomplete_step_name(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-step"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.emit_step_claimed({_sql_str(token)}::uuid, {_sql_str(run_id)}, "
        f"'llm', {_jsonb('{\"k\":1}')}, 's-1', 90);",
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, {_jsonb('{\"reason\":\"x\"}')});",
    )
    psql(
        server,
        P04_ONLY_DB,
        "UPDATE cordis.jobs SET available_at = '-infinity'::timestamptz "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'w2', 90);",
    )
    nxt = psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.next_step_name({_sql_str(run_id)});",
    )
    assert nxt == "s-1"


def test_p04_fail_over_limit_dead_letters(pgdata: Path, tmp_path: Path) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-dead"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id, max_attempts="1")
    ok = psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, {_jsonb('{\"reason\":\"boom\"}')});",
    )
    assert ok == "t"
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || attempt::text || '|' || (error->>'reason') || '|' || "
        "(error->'cause'->>'reason') || '|' || (completed_at IS NOT NULL)::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert row.split("|") == ["ERROR", "1", "MAX_RECOVERY_ATTEMPTS_EXCEEDED", "boom", "true"]
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} "
            "AND kind = 'error';",
        )
        == "1"
    )


def test_p04_fail_unlimited_and_zero_backoff(pgdata: Path, tmp_path: Path) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-zero"
    token = _insert_and_claim(
        server,
        P04_ONLY_DB,
        run_id,
        max_attempts="NULL",
        retry_backoff_base_seconds="0",
        retry_backoff_max_seconds="0",
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, {_jsonb('{\"reason\":\"z\"}')});",
    )
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || attempt::text || '|' || "
        "(available_at <= clock_timestamp())::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert row.split("|") == ["PENDING", "2", "true"]


def test_p04_release_stale_retries_and_logs_timeout(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-stale"
    old = _insert_and_claim(server, P04_ONLY_DB, run_id)
    psql(
        server,
        P04_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at = clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    n = psql(server, P04_ONLY_DB, f"SELECT cordis.release_stale({_sql_str(run_id)}, 100);")
    assert n == "1"
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || attempt::text || '|' || (claim_token IS NULL)::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert row.split("|") == ["SLEEPING", "2", "true"]
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT cordis.renew_claim({_sql_str(old)}::uuid, 90);",
        )
        == "f"
    )
    log = psql(
        server,
        P04_ONLY_DB,
        "SELECT kind || '|' || (payload->>'outcome') || '|' || (payload->>'reason') "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} "
        "AND kind = 'run/claim_timeout';",
    )
    assert log == "run/claim_timeout|retry|claim_timeout"


def test_p04_release_stale_over_limit_dead_letters(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-stale-dead"
    _insert_and_claim(server, P04_ONLY_DB, run_id, max_attempts="1")
    psql(
        server,
        P04_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at = clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    n = psql(server, P04_ONLY_DB, f"SELECT cordis.release_stale({_sql_str(run_id)}, 100);")
    assert n == "1"
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || attempt::text || '|' || (error->>'reason') || '|' || "
        "(error->>'failure_source') "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert row.split("|") == ["ERROR", "1", "MAX_RECOVERY_ATTEMPTS_EXCEEDED", "claim_timeout"]
    kinds = psql(
        server,
        P04_ONLY_DB,
        "SELECT string_agg(kind, ',' ORDER BY seq) "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
    )
    assert kinds.endswith("run/claim_timeout,error")


def test_p04_release_stale_with_prewritten_error_is_terminal(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-stale-prewritten"
    token = _insert_and_claim(server, P04_ONLY_DB, run_id)
    payload = '{"protocol":"p04.test","code":"STALE_PREWRITTEN"}'
    assert psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.emit_step_claimed({_sql_str(token)}::uuid, "
        f"{_sql_str(run_id)}, 'error', {_jsonb(payload)}, NULL, 90);",
    ) == "t"
    error_seq = psql(
        server,
        P04_ONLY_DB,
        f"SELECT seq::text FROM cordis.agent_steps WHERE run_id={_sql_str(run_id)} "
        "AND kind='error' ORDER BY seq DESC LIMIT 1;",
    )
    psql(
        server,
        P04_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at=clock_timestamp()-interval '1 second' "
        f"WHERE run_id={_sql_str(run_id)};",
    )
    assert psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.release_stale({_sql_str(run_id)}, 100);",
    ) == "1"
    row = psql(
        server,
        P04_ONLY_DB,
        "SELECT status || '|' || attempt::text || '|' || (error->>'code') "
        f"FROM cordis.jobs WHERE run_id={_sql_str(run_id)};",
    )
    assert row == "ERROR|1|STALE_PREWRITTEN"
    timeout = psql(
        server,
        P04_ONLY_DB,
        "SELECT (payload->>'outcome') || '|' || "
        "(payload->>'terminal_reason') || '|' || (payload->>'error_seq') || '|' || "
        "(payload ? 'dead_letter')::text FROM cordis.agent_steps "
        f"WHERE run_id={_sql_str(run_id)} AND kind='run/claim_timeout';",
    )
    assert timeout == f"terminal|PREWRITTEN_ERROR_EVENT|{error_seq}|false"
    counts = psql(
        server,
        P04_ONLY_DB,
        "SELECT count(*) FILTER (WHERE kind='error')::text || '|' || "
        "count(*) FILTER (WHERE kind='run/sleep')::text "
        f"FROM cordis.agent_steps WHERE run_id={_sql_str(run_id)};",
    )
    assert counts == "1|0"


def test_p04_shared_attempt_counter_across_fail_and_lease_expiry(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-shared"
    token = _insert_and_claim(
        server,
        P04_ONLY_DB,
        run_id,
        retry_backoff_base_seconds="0",
        retry_backoff_max_seconds="0",
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, {_jsonb('{\"reason\":\"a\"}')});",
    )
    assert (
        psql(
            server,
            P04_ONLY_DB,
            f"SELECT attempt::text || '|' || status FROM cordis.jobs "
            f"WHERE run_id = {_sql_str(run_id)};",
        )
        == "2|PENDING"
    )
    token2 = psql(
        server,
        P04_ONLY_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'w2', 90);",
    )
    psql(
        server,
        P04_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at = clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    psql(server, P04_ONLY_DB, f"SELECT cordis.release_stale({_sql_str(run_id)}, 100);")
    row = psql(
        server,
        P04_ONLY_DB,
        f"SELECT attempt::text || '|' || status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert row == "3|PENDING"
    assert token2 != token


def test_p04_retry_and_lease_expiry_stay_on_one_jobs_row(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p04-one-row"
    token = _insert_and_claim(
        server,
        P04_ONLY_DB,
        run_id,
        retry_backoff_base_seconds="0",
        retry_backoff_max_seconds="0",
    )
    job_id = psql(
        server,
        P04_ONLY_DB,
        f"SELECT job_id::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, {_jsonb('{\"reason\":\"a\"}')});",
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT claim_token FROM cordis.claim_job({_sql_str(run_id)}, 'w2', 90);",
    )
    psql(
        server,
        P04_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at = clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    psql(server, P04_ONLY_DB, f"SELECT cordis.release_stale({_sql_str(run_id)}, 100);")
    rows = psql(
        server,
        P04_ONLY_DB,
        "SELECT count(*) || '|' || min(job_id)::text || '|' || min(run_id) "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert rows == f"1|{job_id}|{run_id}"
    assert (
        psql(
            server,
            P04_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relkind = 'r' AND c.relname = 'jobs';",
        )
        == "1"
    )


def test_p04_replay_preserves_policy_sleep_wait_and_logs(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p04_only(pgdata, tmp_path)
    server = get_server(pgdata)
    sleep_id = "p04-replay-sleep"
    token = _insert_and_claim(
        server, P04_ONLY_DB, sleep_id, max_attempts="7", retry_backoff_base_seconds="12"
    )
    psql(
        server,
        P04_ONLY_DB,
        f"SELECT cordis.sleep_claim({_sql_str(token)}::uuid, {_sql_str(sleep_id)}, "
        f"'2099-01-01 00:00:00+00'::timestamptz, 90);",
    )
    wait_id = "p04-replay-wait"
    _suspend_due_wait(server, wait_id, "scope-replay", None)
    before = psql(
        server,
        P04_ONLY_DB,
        "SELECT j.max_attempts::text || '|' || j.retry_backoff_base_seconds::text || '|' || "
        "j.status || '|' || w.await_id::text || '|' || "
        "(SELECT count(*) FROM cordis.agent_steps s WHERE s.run_id = j.run_id)::text "
        "FROM cordis.jobs j LEFT JOIN cordis.run_waits w ON w.run_id = j.run_id "
        f"WHERE j.run_id = {_sql_str(sleep_id)} "
        "UNION ALL "
        "SELECT j.max_attempts::text || '|' || j.retry_backoff_base_seconds::text || '|' || "
        "j.status || '|' || w.await_id::text || '|' || "
        "(SELECT count(*) FROM cordis.agent_steps s WHERE s.run_id = j.run_id)::text "
        "FROM cordis.jobs j LEFT JOIN cordis.run_waits w ON w.run_id = j.run_id "
        f"WHERE j.run_id = {_sql_str(wait_id)} "
        "ORDER BY 1;",
    )
    tree = tmp_path / "sql_p04_only"
    replay = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P04_ONLY_DB,
        "--sql-root",
        str(tree),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    after = psql(
        server,
        P04_ONLY_DB,
        "SELECT j.max_attempts::text || '|' || j.retry_backoff_base_seconds::text || '|' || "
        "j.status || '|' || w.await_id::text || '|' || "
        "(SELECT count(*) FROM cordis.agent_steps s WHERE s.run_id = j.run_id)::text "
        "FROM cordis.jobs j LEFT JOIN cordis.run_waits w ON w.run_id = j.run_id "
        f"WHERE j.run_id = {_sql_str(sleep_id)} "
        "UNION ALL "
        "SELECT j.max_attempts::text || '|' || j.retry_backoff_base_seconds::text || '|' || "
        "j.status || '|' || w.await_id::text || '|' || "
        "(SELECT count(*) FROM cordis.agent_steps s WHERE s.run_id = j.run_id)::text "
        "FROM cordis.jobs j LEFT JOIN cordis.run_waits w ON w.run_id = j.run_id "
        f"WHERE j.run_id = {_sql_str(wait_id)} "
        "ORDER BY 1;",
    )
    assert after == before
    assert psql(server, P04_ONLY_DB, "SELECT cordis.get_schema_version();") == "p04"


def test_p04_rejects_incompatible_max_attempts_type(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = tmp_path / "sql_p04_conflict"
    tree.mkdir()
    for name in P04_FILES[:4]:
        shutil.copy(SQL / name, tree / name)
    first = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_conflict",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    server = get_server(pgdata)
    psql(
        server,
        "cordis_p04_conflict",
        "ALTER TABLE cordis.jobs ADD COLUMN max_attempts text;",
    )
    shutil.copy(SQL / "0004_p04_sleep_retry.sql", tree / "0004_p04_sleep_retry.sql")
    second = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_conflict",
        "--sql-root",
        str(tree),
    )
    assert second.returncode != 0, second.stdout + second.stderr


def test_p04_replay_rejects_nonconstant_default(pgdata: Path, tmp_path: Path) -> None:
    tree = tmp_path / "sql_p04_bad_default"
    tree.mkdir()
    for name in P04_FILES[:4]:
        shutil.copy(SQL / name, tree / name)
    first = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_bad_default",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    server = get_server(pgdata)
    psql(
        server,
        "cordis_p04_bad_default",
        "ALTER TABLE cordis.jobs ADD COLUMN retry_backoff_factor "
        "double precision NOT NULL DEFAULT (2 + random() * 0);",
    )
    shutil.copy(SQL / "0004_p04_sleep_retry.sql", tree / "0004_p04_sleep_retry.sql")
    second = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_bad_default",
        "--sql-root",
        str(tree),
    )
    assert second.returncode != 0, second.stdout + second.stderr
    assert "incompatible" in (second.stdout + second.stderr)


def test_p04_replay_rejects_weaker_factor_check(pgdata: Path, tmp_path: Path) -> None:
    tree = tmp_path / "sql_p04_fake_check"
    tree.mkdir()
    for name in P04_FILES[:4]:
        shutil.copy(SQL / name, tree / name)
    first = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_fake_check",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    server = get_server(pgdata)
    psql(
        server,
        "cordis_p04_fake_check",
        "ALTER TABLE cordis.jobs "
        "ADD COLUMN retry_backoff_factor double precision NOT NULL DEFAULT 2; "
        "ALTER TABLE cordis.jobs ADD CONSTRAINT jobs_retry_backoff_factor_check "
        "CHECK (retry_backoff_factor >= 1 "
        "AND retry_backoff_factor <> 'Infinity'::double precision);"
    )
    shutil.copy(SQL / "0004_p04_sleep_retry.sql", tree / "0004_p04_sleep_retry.sql")
    second = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_fake_check",
        "--sql-root",
        str(tree),
    )
    assert second.returncode != 0, second.stdout + second.stderr
    assert "incompatible" in (second.stdout + second.stderr)


def test_p04_replay_rejects_incompatible_deadline_index(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = tmp_path / "sql_p04_bad_deadline_index"
    tree.mkdir()
    for name in P04_FILES[:4]:
        shutil.copy(SQL / name, tree / name)
    first = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_bad_deadline_index",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    server = get_server(pgdata)
    psql(
        server,
        "cordis_p04_bad_deadline_index",
        "CREATE INDEX run_waits_deadline_idx ON cordis.run_waits "
        "(event_scope_id, deadline) WHERE deadline IS NOT NULL;",
    )
    shutil.copy(SQL / "0004_p04_sleep_retry.sql", tree / "0004_p04_sleep_retry.sql")
    second = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p04_bad_deadline_index",
        "--sql-root",
        str(tree),
    )
    assert second.returncode != 0, second.stdout + second.stderr
    assert "incompatible run_waits_deadline_idx" in (
        second.stdout + second.stderr
    )


def test_p04_no_second_queue_or_direct_log_insert() -> None:
    src = (SQL / "0004_p04_sleep_retry.sql").read_text()
    scanned = _strip_sql_comments(src)
    assert re.search(r"INSERT\s+INTO\s+cordis\.agent_steps", scanned, re.I) is None
    assert re.search(r"UPDATE\s+cordis\.agent_steps", scanned, re.I) is None
    assert re.search(r"DELETE\s+FROM\s+cordis\.agent_steps", scanned, re.I) is None
    assert re.search(r"\bLISTEN\b", scanned, re.I) is None
    assert re.search(r"\bNOTIFY\b", scanned, re.I) is None
    assert re.search(r"\bpg_notify\b", scanned, re.I) is None
    assert re.search(r"CREATE\s+SCHEMA\s+absurd", scanned, re.I) is None
    assert re.search(r"CREATE\s+EXTENSION", scanned, re.I) is None
    assert re.search(r"\bGRANT\b", scanned, re.I) is None
    assert re.search(r"retry_class", scanned, re.I) is None
    assert re.search(r"plugin_catalog", scanned, re.I) is None
    assert re.search(r"host_plugin_definitions", scanned, re.I) is None
    claim_pred = re.search(
        r"j\.status\s+IN\s*\(([^)]+)\)",
        scanned,
    )
    assert claim_pred is not None
    assert "WAITING" not in claim_pred.group(1)
    assert re.search(r"available_at\s*=\s*w\.deadline", scanned, re.I) is None
    assert re.search(r"COMMENT\s+ON", src, re.I) is None
    insert_re = re.compile(r"INSERT\s+INTO\s+cordis\.agent_steps", re.I)
    inserts = []
    for path in sorted(SQL.glob("*.sql")):
        body = _strip_sql_comments(path.read_text())
        if insert_re.search(body):
            inserts.append(path.name)
    assert inserts == ["0002_p02_log.sql"]
    assert re.search(r"CREATE\s+TABLE", scanned, re.I) is None
    module = load_apply_module()
    module.preflight_sql(SQL / "0004_p04_sleep_retry.sql", src)
