"""P03 run_waits / run_events and atomic wait/wake tests."""

from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import pytest
from pgembed import get_server

from tests.conftest import SQL, load_apply_module, psql, psql_session, run_apply

P03_ONLY_DB = "cordis_p03_only"
AWAIT_ID = (
    "cordis.await_event(uuid, text, text, text, uuid, timestamp with time zone, jsonb, integer)"
)
EMIT_ID = "cordis.emit_event(text, text, jsonb)"
RUN_STATE_ID = "cordis.run_state(text)"
EVENT_CONSTRAINTS = (
    "run_events_pkey",
    "run_events_event_log_run_id_key",
    "run_events_scope_nonblank_check",
    "run_events_name_nonblank_check",
    "run_events_event_log_run_id_check",
    "run_events_emit_seq_check",
    "run_events_emission_state_check",
)
WAIT_CONSTRAINTS = (
    "run_waits_pkey",
    "run_waits_await_id_key",
    "run_waits_job_fkey",
    "run_waits_event_fkey",
    "run_waits_await_step_fkey",
    "run_waits_scope_nonblank_check",
    "run_waits_name_nonblank_check",
    "run_waits_await_seq_check",
    "run_waits_ui_metadata_object_check",
)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _jsonb(value: str) -> str:
    return _sql_str(value) + "::jsonb"


def _apply_p03_only(pgdata: Path, tmp_path: Path) -> str:
    tree = tmp_path / "sql_p03_only"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir()
    for name in (
        "0000_kernel.sql",
        "0001_p01_claim.sql",
        "0002_p02_log.sql",
        "0003_p03_wait_event.sql",
    ):
        shutil.copy(SQL / name, tree / name)
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P03_ONLY_DB,
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def _insert_and_claim(
    server, database: str, run_id: str, worker: str = "worker-a"
) -> str:
    psql(
        server,
        database,
        "INSERT INTO cordis.jobs (run_id, job_type) "
        f"VALUES ({_sql_str(run_id)}, 'p03_test');",
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
        "CASE WHEN should_suspend THEN 't' ELSE 'f' END || '|' || "
        "COALESCE(payload::text, '') || '|' || COALESCE(source_run_id, '') || '|' || "
        "COALESCE(source_seq::text, '') FROM cordis.await_event("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, {_sql_str(scope)}, "
        f"{_sql_str(name)}, {_sql_str(await_id)}::uuid, {dl}, '{{}}'::jsonb, 90)"
    )


def _emit_sql(scope: str, name: str, payload: str) -> str:
    return (
        "SELECT CASE WHEN emitted THEN 't' ELSE 'f' END || '|' || woken_count::text || '|' || "
        "COALESCE(source_run_id, '') || '|' || COALESCE(source_seq::text, '') "
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


def _run_state(server, database: str, run_id: str) -> list[str]:
    return psql(
        server,
        database,
        "SELECT status || '|' || steps_used::text || '|' || "
        "COALESCE(answer, '') || '|' || COALESCE(error, '') "
        f"FROM cordis.run_state({_sql_str(run_id)});",
    ).split("|")


def test_p03_fresh_apply_catalog_and_version(pgdata: Path, tmp_path: Path) -> None:
    out = _apply_p03_only(pgdata, tmp_path)
    assert (
        "files=0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,"
        "0003_p03_wait_event.sql"
        in out
    )
    server = get_server(pgdata)
    assert psql(server, P03_ONLY_DB, "SELECT cordis.get_schema_version();") == "p03"
    for rel in ("run_events", "run_waits", "jobs", "agent_steps"):
        assert (
            psql(
                server,
                P03_ONLY_DB,
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                f"WHERE n.nspname = 'cordis' AND c.relkind = 'r' AND c.relname = '{rel}';",
            )
            == "1"
        )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname = 'plugin_catalog';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM pg_namespace WHERE nspname = 'absurd';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM pg_extension WHERE extname = 'pg_cordis';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname IN ('run_waits','run_events');",
        )
        == "0"
    )
    ids = psql(
        server,
        P03_ONLY_DB,
        "SELECT n.nspname || '.' || p.proname || '(' || "
        "pg_catalog.oidvectortypes(p.proargtypes) || ')' "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN "
        "('await_event','emit_event','run_state') ORDER BY 1;",
    ).splitlines()
    assert ids == sorted([AWAIT_ID, EMIT_ID, RUN_STATE_ID])
    vol = dict(
        line.split(":", 1)
        for line in psql(
            server,
            P03_ONLY_DB,
            "SELECT n.nspname || '.' || p.proname || '(' || "
            "pg_catalog.oidvectortypes(p.proargtypes) || '):' || "
            "p.provolatile::text || ':' || p.prosecdef::text "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cordis' AND p.proname IN "
            "('await_event','emit_event','run_state');",
        ).splitlines()
    )
    assert vol[AWAIT_ID] == "v:false"
    assert vol[EMIT_ID] == "v:false"
    assert vol[RUN_STATE_ID] == "s:false"
    version = psql(
        server,
        P03_ONLY_DB,
        "SELECT pg_get_function_identity_arguments(p.oid) || '|' || "
        "pg_get_function_result(p.oid) || '|' || l.lanname || '|' || "
        "p.provolatile::text || '|' || p.prosecdef::text "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_language l ON l.oid = p.prolang "
        "WHERE n.nspname = 'cordis' AND p.proname = 'get_schema_version' "
        "AND p.pronargs = 0;",
    )
    assert version == "|text|sql|i|false"
    for proname in ("await_event", "emit_event", "run_state"):
        assert (
            psql(
                server,
                P03_ONLY_DB,
                "SELECT count(*) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                f"WHERE n.nspname = 'cordis' AND p.proname = '{proname}';",
            )
            == "1"
        )


def test_p03_event_and_wait_constraints(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    event_names = psql(
        server,
        P03_ONLY_DB,
        "SELECT conname FROM pg_constraint x "
        "JOIN pg_class c ON c.oid = x.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'run_events' "
        "ORDER BY 1;",
    ).splitlines()
    for name in EVENT_CONSTRAINTS:
        assert name in event_names, event_names
    wait_names = psql(
        server,
        P03_ONLY_DB,
        "SELECT conname FROM pg_constraint x "
        "JOIN pg_class c ON c.oid = x.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'run_waits' "
        "ORDER BY 1;",
    ).splitlines()
    for name in WAIT_CONSTRAINTS:
        assert name in wait_names, wait_names
    emission = psql(
        server,
        P03_ONLY_DB,
        "SELECT pg_get_constraintdef(con.oid) FROM pg_constraint con "
        "JOIN pg_class c ON c.oid = con.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'run_events' "
        "AND con.conname = 'run_events_emission_state_check';",
    )
    assert "payload IS NULL" in emission
    assert "emit_seq IS NULL" in emission
    assert "emitted_at IS NULL" in emission
    deltype = psql(
        server,
        P03_ONLY_DB,
        "SELECT confdeltype FROM pg_constraint con "
        "JOIN pg_class c ON c.oid = con.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'run_waits' "
        "AND con.conname = 'run_waits_job_fkey';",
    )
    assert deltype == "r"
    indexes = psql(
        server,
        P03_ONLY_DB,
        "SELECT indexrelid::regclass::text FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'run_waits' "
        "ORDER BY 1;",
    )
    assert "run_waits_event_idx" in indexes
    psql(
        server,
        P03_ONLY_DB,
        "INSERT INTO cordis.run_events (event_scope_id, event_name, payload, emit_seq, emitted_at) "
        "VALUES ('scope-json-null', 'n', 'null'::jsonb, 1, pg_catalog.clock_timestamp());",
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT CASE WHEN payload IS NOT NULL THEN 't' ELSE 'f' END "
            "|| '|' || jsonb_typeof(payload) "
            "FROM cordis.run_events WHERE event_scope_id = 'scope-json-null';",
        )
        == "t|null"
    )


def test_p03_wait_transitions_atomically_and_is_unclaimable(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-wait"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    available_before = psql(
        server,
        P03_ONLY_DB,
        f"SELECT available_at::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    await_id = str(uuid.uuid4())
    deadline = "2099-01-01 00:00:00+00"
    row = psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-a", "ready", await_id, deadline),
    )
    accepted, should_suspend, payload, source, seq = row.split("|")
    assert accepted == "t"
    assert should_suspend == "t"
    assert payload == ""
    assert source == ""
    assert seq == ""
    job = psql(
        server,
        P03_ONLY_DB,
        "SELECT status || '|' || COALESCE(claim_token::text, '') || '|' || "
        "COALESCE(claimed_by, '') || '|' || COALESCE(claim_expires_at::text, '') || '|' || "
        f"available_at::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    status, claim_token, claimed_by, expires, available_after = job.split("|")
    assert status == "WAITING"
    assert claim_token == ""
    assert claimed_by == ""
    assert expires == ""
    assert available_after == available_before
    wait = psql(
        server,
        P03_ONLY_DB,
        "SELECT await_id::text || '|' || COALESCE(deadline::text, '') || '|' || await_seq::text "
        f"FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
    )
    wait_id, wait_deadline, await_seq = wait.split("|")
    assert wait_id == await_id
    assert "2099-01-01" in wait_deadline
    kinds = psql(
        server,
        P03_ONLY_DB,
        f"SELECT kind FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} ORDER BY seq;",
    ).splitlines()
    assert kinds == ["run/await"]
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND seq = {await_seq} AND kind = 'run/await';",
        )
        == "1"
    )
    assert _run_state(server, P03_ONLY_DB, run_id)[0] == "awaiting"
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.claim_job({_sql_str(run_id)}, 'worker-b', 90);",
        )
        == "0"
    )


def test_p03_wait_rollback_preserves_running_claim(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-rollback"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    await_id = str(uuid.uuid4())
    with psql_session(server, P03_ONLY_DB) as session:
        session.execute("BEGIN")
        row = session.execute(
            _await_sql(token, run_id, "scope-rb", "n", await_id)
        )
        assert row[0].startswith("t|t|")
        session.rollback()
    job = psql(
        server,
        P03_ONLY_DB,
        "SELECT status || '|' || claim_token::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    status, still = job.split("|")
    assert status == "RUNNING"
    assert still == token
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )


def test_p03_wait_visibility_has_no_partial_state(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-vis"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    await_id = str(uuid.uuid4())
    with psql_session(server, P03_ONLY_DB) as session:
        session.execute("BEGIN")
        session.execute(_await_sql(token, run_id, "scope-vis", "n", await_id))
        other_status = psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        other_waits = psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
        )
        assert other_status == "RUNNING"
        assert other_waits == "0"
        session.commit()
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "WAITING"
    )


def test_p03_emit_wakes_waiter_and_folds_state(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-wake"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    await_id = str(uuid.uuid4())
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-wake", "go", await_id),
    )
    assert _run_state(server, P03_ONLY_DB, run_id)[0] == "awaiting"
    emitted = psql(
        server, P03_ONLY_DB, _emit_sql("scope-wake", "go", '{"v":1}')
    )
    flag, woken, source, seq = emitted.split("|")
    assert flag == "t"
    assert woken == "1"
    assert source.startswith("@event/")
    assert int(seq) >= 1
    job = psql(
        server,
        P03_ONLY_DB,
        f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert job == "PENDING"
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )
    kinds = psql(
        server,
        P03_ONLY_DB,
        f"SELECT kind FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} ORDER BY seq;",
    ).splitlines()
    assert kinds == ["run/await", "run/wake"]
    cache = psql(
        server,
        P03_ONLY_DB,
        "SELECT payload::text || '|' || event_log_run_id || '|' || emit_seq::text "
        "FROM cordis.run_events WHERE event_scope_id = 'scope-wake' AND event_name = 'go';",
    )
    cache_payload, cache_run, cache_seq = cache.split("|")
    assert cache_payload == '{"v": 1}' or cache_payload == '{"v":1}'
    assert cache_run == source
    assert cache_seq == seq
    log_kind = psql(
        server,
        P03_ONLY_DB,
        f"SELECT kind FROM cordis.agent_steps WHERE run_id = {_sql_str(source)} AND seq = {seq};",
    )
    assert log_kind == "event/emit"
    assert _run_state(server, P03_ONLY_DB, run_id)[0] == "in-progress"
    new_token = psql(
        server,
        P03_ONLY_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'worker-b', 90);",
    )
    assert new_token
    assert new_token != token


def test_p03_emit_before_wait_resolves_without_yield(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-immediate"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    first = psql(server, P03_ONLY_DB, _emit_sql("scope-imm", "n", '{"ok":true}'))
    flag, woken, source, seq = first.split("|")
    assert flag == "t"
    assert woken == "0"
    await_id = str(uuid.uuid4())
    row = psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-imm", "n", await_id),
    )
    accepted, should_suspend, payload, src, src_seq = row.split("|")
    assert accepted == "t"
    assert should_suspend == "f"
    assert '"ok": true' in payload or '"ok":true' in payload
    assert src == source
    assert src_seq == seq
    job = psql(
        server,
        P03_ONLY_DB,
        "SELECT status || '|' || claim_token::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    status, still = job.split("|")
    assert status == "RUNNING"
    assert still == token
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )
    kinds = psql(
        server,
        P03_ONLY_DB,
        f"SELECT kind FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} ORDER BY seq;",
    ).splitlines()
    assert kinds == ["run/await", "run/wake"]
    assert _run_state(server, P03_ONLY_DB, run_id)[0] == "in-progress"


def test_p03_duplicate_emit_first_write_wins(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    first = psql(server, P03_ONLY_DB, _emit_sql("scope-dup", "n", '{"a":1}'))
    flag, woken, source, seq = first.split("|")
    assert flag == "t" and woken == "0"
    second = psql(server, P03_ONLY_DB, _emit_sql("scope-dup", "n", '{"a":2}'))
    flag2, woken2, source2, seq2 = second.split("|")
    assert flag2 == "f"
    assert woken2 == "0"
    assert source2 == source
    assert seq2 == seq
    payload = psql(
        server,
        P03_ONLY_DB,
        "SELECT payload::text FROM cordis.run_events "
        "WHERE event_scope_id = 'scope-dup' AND event_name = 'n';",
    )
    assert '"a": 1' in payload or '"a":1' in payload
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            "WHERE kind = 'event/emit' AND run_id LIKE '@event/%' "
            "AND payload->>'event_scope_id' = 'scope-dup';",
        )
        == "1"
    )


def test_p03_duplicate_wait_and_await_id_reuse(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-dup-wait"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    await_id = str(uuid.uuid4())
    first = psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-dw", "n", await_id),
    )
    assert first.startswith("t|t|")
    second = psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-dw", "n", str(uuid.uuid4())),
    )
    assert second.startswith("f|f|")
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_id)};",
        )
        == "1"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
        )
        == "1"
    )
    psql(server, P03_ONLY_DB, _emit_sql("scope-dw", "n", '{"x":1}'))
    new_token = psql(
        server,
        P03_ONLY_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'worker-b', 90);",
    )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P03_ONLY_DB,
            _await_sql(new_token, run_id, "scope-dw", "n", await_id),
        )


def test_p03_fanout_wakes_all_matching_waiters(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    runs = ("p03-fan-a", "p03-fan-b", "p03-fan-other")
    tokens = {
        run_id: _insert_and_claim(server, P03_ONLY_DB, run_id, f"w-{run_id}")
        for run_id in runs
    }
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(tokens["p03-fan-a"], "p03-fan-a", "scope-fan", "n", str(uuid.uuid4())),
    )
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(tokens["p03-fan-b"], "p03-fan-b", "scope-fan", "n", str(uuid.uuid4())),
    )
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(
            tokens["p03-fan-other"],
            "p03-fan-other",
            "scope-fan-other",
            "n",
            str(uuid.uuid4()),
        ),
    )
    emitted = psql(server, P03_ONLY_DB, _emit_sql("scope-fan", "n", '{"k":1}'))
    assert emitted.split("|")[0:2] == ["t", "2"]
    for run_id in ("p03-fan-a", "p03-fan-b"):
        assert (
            psql(
                server,
                P03_ONLY_DB,
                f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
            )
            == "PENDING"
        )
        assert _run_state(server, P03_ONLY_DB, run_id)[0] == "in-progress"
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT status FROM cordis.jobs WHERE run_id = 'p03-fan-other';",
        )
        == "WAITING"
    )


def test_p03_lost_claim_and_parameter_errors(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-lost"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    with pytest.raises(RuntimeError):
        psql(
            server,
            P03_ONLY_DB,
            "SELECT * FROM cordis.await_event("
            f"{_sql_str(token)}::uuid, '  ', 's', 'n', "
            f"{_sql_str(str(uuid.uuid4()))}::uuid, NULL, '{{}}'::jsonb, 90);",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P03_ONLY_DB,
            "SELECT * FROM cordis.emit_event('s', 'n', NULL);",
        )
    lost = psql(
        server,
        P03_ONLY_DB,
        "SELECT CASE WHEN accepted THEN 't' ELSE 'f' END || '|' || "
        "CASE WHEN should_suspend THEN 't' ELSE 'f' END FROM cordis.await_event("
        "NULL, 'p03-lost', 'scope-lost', 'n', "
        f"{_sql_str(str(uuid.uuid4()))}::uuid, NULL, '{{}}'::jsonb, 90);",
    )
    assert lost == "f|f"
    missing = psql(
        server,
        P03_ONLY_DB,
        _await_sql(
            "00000000-0000-0000-0000-000000000099",
            run_id,
            "scope-lost-miss",
            "n",
            str(uuid.uuid4()),
        ),
    )
    assert missing.startswith("f|f|")
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM cordis.run_events "
            "WHERE event_scope_id = 'scope-lost-miss';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "RUNNING"
    )


def test_p03_waiting_lease_expiry_is_not_reaped(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-stale"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-stale", "n", str(uuid.uuid4())),
    )
    assert (
        psql(server, P03_ONLY_DB, "SELECT cordis.release_stale(NULL, 100);")
        == "0"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.claim_job({_sql_str(run_id)}, 'worker-b', 90);",
        )
        == "0"
    )
    emitted = psql(server, P03_ONLY_DB, _emit_sql("scope-stale", "n", '{"z":1}'))
    assert emitted.startswith("t|1|")
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "PENDING"
    )


def test_p03_wait_emit_lock_order_no_deadlock(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_a = "p03-lock-a"
    token_a = _insert_and_claim(server, P03_ONLY_DB, run_a)
    await_a = str(uuid.uuid4())
    errors: list[BaseException] = []
    results: list[str] = []

    def emit_blocked() -> None:
        try:
            results.append(
                psql(
                    server,
                    P03_ONLY_DB,
                    "SET statement_timeout = '8s'; "
                    + _emit_sql("scope-lock", "n", '{"w":1}'),
                )
            )
        except Exception as exc:
            errors.append(exc)

    with psql_session(server, P03_ONLY_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        session.execute(_await_sql(token_a, run_a, "scope-lock", "n", await_a))
        thread = threading.Thread(target=emit_blocked)
        thread.start()
        _wait_for_blocked_backend(server, P03_ONLY_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert errors == []
    assert results and results[0].startswith("t|1|")
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_a)};",
        )
        == "PENDING"
    )

    run_b = "p03-lock-b"
    token_b = _insert_and_claim(server, P03_ONLY_DB, run_b)
    await_b = str(uuid.uuid4())
    await_results: list[str] = []
    await_errors: list[BaseException] = []

    def await_blocked() -> None:
        try:
            await_results.append(
                psql(
                    server,
                    P03_ONLY_DB,
                    "SET statement_timeout = '8s'; "
                    + _await_sql(token_b, run_b, "scope-lock-b", "n", await_b),
                )
            )
        except Exception as exc:
            await_errors.append(exc)

    with psql_session(server, P03_ONLY_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        session.execute(_emit_sql("scope-lock-b", "n", '{"q":1}'))
        thread = threading.Thread(target=await_blocked)
        thread.start()
        _wait_for_blocked_backend(server, P03_ONLY_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert await_errors == []
    assert await_results and await_results[0].startswith("t|f|")
    job = psql(
        server,
        P03_ONLY_DB,
        "SELECT status || '|' || claim_token::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_b)};",
    )
    status, still = job.split("|")
    assert status == "RUNNING"
    assert still == token_b
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT count(*) FROM cordis.run_waits WHERE run_id = {_sql_str(run_b)};",
        )
        == "0"
    )


def test_p03_await_skips_locked_claim_without_deadlock(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-skip-lock"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    await_id = str(uuid.uuid4())
    with (
        psql_session(server, P03_ONLY_DB) as holder,
        psql_session(server, P03_ONLY_DB) as busy,
    ):
        holder.execute("BEGIN")
        holder.execute("SET LOCAL statement_timeout = '8s'")
        claimed = holder.execute(
            f"SELECT cordis.emit_step_claimed({_sql_str(token)}::uuid, "
            f"{_sql_str(run_id)}, 'llm', {_jsonb('{}')}, 's-1');"
        )
        assert claimed == ["t"]
        busy.execute("BEGIN")
        busy.execute("SET LOCAL statement_timeout = '8s'")
        skipped = busy.execute(
            _await_sql(token, run_id, "scope-skip", "n", await_id)
        )
        assert skipped[0].startswith("f|f|")
        emitted = holder.execute(_emit_sql("scope-skip", "n", '{"ok":true}'))
        assert emitted[0].startswith("t|0|")
        holder.commit()
        busy.commit()
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "RUNNING"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT CASE WHEN payload IS NOT NULL THEN 't' ELSE 'f' END "
            "FROM cordis.run_events WHERE event_scope_id = 'scope-skip';",
        )
        == "t"
    )


def test_p03_json_null_emit_is_first_write(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    first = psql(
        server,
        P03_ONLY_DB,
        "SELECT CASE WHEN emitted THEN 't' ELSE 'f' END || '|' || woken_count::text "
        "|| '|' || COALESCE(source_run_id, '') || '|' || COALESCE(source_seq::text, '') "
        "FROM cordis.emit_event('scope-jsonnull', 'n', 'null'::jsonb);",
    )
    flag, woken, source, seq = first.split("|")
    assert flag == "t" and woken == "0"
    second = psql(
        server,
        P03_ONLY_DB,
        "SELECT CASE WHEN emitted THEN 't' ELSE 'f' END FROM cordis.emit_event("
        "'scope-jsonnull', 'n', '{\"v\":1}'::jsonb);",
    )
    assert second == "f"
    run_id = "p03-jsonnull"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    row = psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-jsonnull", "n", str(uuid.uuid4())),
    )
    accepted, should_suspend, payload, src, src_seq = row.split("|")
    assert accepted == "t" and should_suspend == "f"
    assert payload == "null"
    assert src == source
    assert src_seq == seq


def test_p03_missing_event_payload_field_raises(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    first = psql(server, P03_ONLY_DB, _emit_sql("scope-miss", "n", '{"v":1}'))
    _, _, source, seq = first.split("|")
    psql(
        server,
        P03_ONLY_DB,
        "UPDATE cordis.agent_steps "
        "SET payload = payload - 'payload' "
        f"WHERE run_id = {_sql_str(source)} AND seq = {seq};",
    )
    run_id = "p03-miss-payload"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    with pytest.raises(RuntimeError):
        psql(
            server,
            P03_ONLY_DB,
            _await_sql(token, run_id, "scope-miss", "n", str(uuid.uuid4())),
        )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        == "RUNNING"
    )


def test_p03_event_payload_log_is_source_of_truth(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    first = psql(server, P03_ONLY_DB, _emit_sql("scope-sot", "n", '{"v":1}'))
    _, _, source, seq = first.split("|")
    psql(
        server,
        P03_ONLY_DB,
        "UPDATE cordis.run_events SET payload = '{\"v\":2}'::jsonb "
        "WHERE event_scope_id = 'scope-sot' AND event_name = 'n';",
    )
    run_id = "p03-sot"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    row = psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-sot", "n", str(uuid.uuid4())),
    )
    accepted, should_suspend, payload, src, src_seq = row.split("|")
    assert accepted == "t" and should_suspend == "f"
    assert '"v": 1' in payload or '"v":1' in payload
    assert '"v": 2' not in payload and '"v":2' not in payload
    assert src == source
    assert src_seq == seq
    log_payload = psql(
        server,
        P03_ONLY_DB,
        f"SELECT payload->'payload' FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(source)} AND seq = {seq};",
    )
    assert log_payload in payload or payload in log_payload or '"v": 1' in log_payload


def test_p03_run_state_awaiting_precedence(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    empty = _run_state(server, P03_ONLY_DB, "p03-state-empty")
    assert empty[0] == "in-progress"
    psql(
        server,
        P03_ONLY_DB,
        "SELECT cordis.emit_step('p03-state-await', 'run/await', "
        f"{_jsonb('{\"await_id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\"}')});",
    )
    assert _run_state(server, P03_ONLY_DB, "p03-state-await")[0] == "awaiting"
    psql(
        server,
        P03_ONLY_DB,
        "SELECT cordis.emit_step('p03-state-await', 'run/wake', "
        f"{_jsonb('{\"await_id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\"}')});",
    )
    assert _run_state(server, P03_ONLY_DB, "p03-state-await")[0] == "in-progress"
    psql(
        server,
        P03_ONLY_DB,
        "SELECT cordis.emit_step('p03-state-err', 'run/await', "
        f"{_jsonb('{\"await_id\":\"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\"}')});",
    )
    psql(
        server,
        P03_ONLY_DB,
        "SELECT cordis.emit_step('p03-state-err', 'error', "
        f"{_jsonb('{\"message\":\"boom\"}')});",
    )
    err = _run_state(server, P03_ONLY_DB, "p03-state-err")
    assert err[0] == "error"
    psql(
        server,
        P03_ONLY_DB,
        "SELECT cordis.emit_step('p03-state-final', 'final', "
        f"{_jsonb('{\"answer\":\"done\"}')});",
    )
    psql(
        server,
        P03_ONLY_DB,
        "SELECT cordis.emit_step('p03-state-final', 'run/await', "
        f"{_jsonb('{\"await_id\":\"cccccccc-cccc-cccc-cccc-cccccccccccc\"}')});",
    )
    fin = _run_state(server, P03_ONLY_DB, "p03-state-final")
    assert fin[0] == "final"


def test_p03_emit_invariant_failure_rolls_back_fanout(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_a = "p03-inv-a"
    run_b = "p03-inv-b"
    token_a = _insert_and_claim(server, P03_ONLY_DB, run_a)
    token_b = _insert_and_claim(server, P03_ONLY_DB, run_b)
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(token_a, run_a, "scope-inv", "n", str(uuid.uuid4())),
    )
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(token_b, run_b, "scope-inv", "n", str(uuid.uuid4())),
    )
    psql(
        server,
        P03_ONLY_DB,
        f"UPDATE cordis.jobs SET status = 'PENDING' WHERE run_id = {_sql_str(run_b)};",
    )
    with pytest.raises(RuntimeError):
        psql(server, P03_ONLY_DB, _emit_sql("scope-inv", "n", '{"k":1}'))
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT CASE WHEN payload IS NULL THEN 't' ELSE 'f' END FROM cordis.run_events "
            "WHERE event_scope_id = 'scope-inv' AND event_name = 'n';",
        )
        == "t"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_a)};",
        )
        == "WAITING"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM cordis.run_waits "
            "WHERE event_scope_id = 'scope-inv' AND event_name = 'n';",
        )
        == "2"
    )
    assert (
        psql(
            server,
            P03_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps WHERE kind IN ('event/emit','run/wake') "
            "AND (payload->>'event_scope_id' = 'scope-inv' OR run_id IN "
            f"({_sql_str(run_a)}, {_sql_str(run_b)}));",
        )
        == "0"
    )


def test_p03_replay_preserves_waits_and_events(pgdata: Path, tmp_path: Path) -> None:
    _apply_p03_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p03-replay"
    token = _insert_and_claim(server, P03_ONLY_DB, run_id)
    await_id = str(uuid.uuid4())
    psql(
        server,
        P03_ONLY_DB,
        _await_sql(token, run_id, "scope-replay", "n", await_id),
    )
    before = psql(
        server,
        P03_ONLY_DB,
        "SELECT e.event_log_run_id || '|' || e.created_at::text || '|' || "
        "w.await_seq::text || '|' || w.created_at::text "
        "FROM cordis.run_events e JOIN cordis.run_waits w "
        "ON w.event_scope_id = e.event_scope_id AND w.event_name = e.event_name "
        f"WHERE w.run_id = {_sql_str(run_id)};",
    )
    tree = tmp_path / "sql_p03_only"
    replay = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P03_ONLY_DB,
        "--sql-root",
        str(tree),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    after = psql(
        server,
        P03_ONLY_DB,
        "SELECT e.event_log_run_id || '|' || e.created_at::text || '|' || "
        "w.await_seq::text || '|' || w.created_at::text "
        "FROM cordis.run_events e JOIN cordis.run_waits w "
        "ON w.event_scope_id = e.event_scope_id AND w.event_name = e.event_name "
        f"WHERE w.run_id = {_sql_str(run_id)};",
    )
    assert after == before
    assert psql(server, P03_ONLY_DB, "SELECT cordis.get_schema_version();") == "p03"


def test_p03_no_second_queue_notify_or_direct_log_insert() -> None:
    src = (SQL / "0003_p03_wait_event.sql").read_text()
    scanned = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    lines = []
    for line in scanned.splitlines():
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    scanned = "\n".join(lines)
    assert re.search(r"INSERT\s+INTO\s+cordis\.agent_steps", scanned, re.I) is None
    assert re.search(r"UPDATE\s+cordis\.agent_steps", scanned, re.I) is None
    assert re.search(r"DELETE\s+FROM\s+cordis\.agent_steps", scanned, re.I) is None
    assert re.search(r"\bLISTEN\b", scanned, re.I) is None
    assert re.search(r"\bNOTIFY\b", scanned, re.I) is None
    assert re.search(r"\bpg_notify\b", scanned, re.I) is None
    assert re.search(r"CREATE\s+SCHEMA\s+absurd", scanned, re.I) is None
    assert re.search(r"CREATE\s+EXTENSION", scanned, re.I) is None
    assert re.search(r"\bGRANT\b", scanned, re.I) is None
    assert "wake_event_" not in scanned
    assert re.search(r"COMMENT\s+ON", src, re.I) is None
    insert_re = re.compile(r"INSERT\s+INTO\s+cordis\.agent_steps", re.I)
    inserts = []
    block_comment = re.compile(r"/\*.*?\*/", re.S)
    for path in sorted(SQL.glob("*.sql")):
        body = path.read_text()
        body = block_comment.sub(" ", body)
        cleaned = []
        for line in body.splitlines():
            if "--" in line:
                line = line.split("--", 1)[0]
            cleaned.append(line)
        for match in insert_re.finditer("\n".join(cleaned)):
            inserts.append(path.name)
    assert inserts == ["0002_p02_log.sql"]
    module = load_apply_module()
    module.preflight_sql(SQL / "0003_p03_wait_event.sql", src)
