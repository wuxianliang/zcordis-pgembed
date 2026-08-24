"""P07 grant registry tests. Apply stays a subprocess."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from pgembed import get_server

from tests.conftest import SQL, load_apply_module, psql, psql_session, run_apply

P07_DB = "cordis_p07"
P07_FILES = (
    "0000_kernel.sql",
    "0001_p01_claim.sql",
    "0002_p02_log.sql",
    "0003_p03_wait_event.sql",
    "0006_p06_plugin_catalog.sql",
    "0007_p07_grant_registry.sql",
)
WRITER_IDS = (
    "cordis.register_named_corpus(text, text, text)",
    "cordis.create_slice(text, text, text)",
    "cordis.request_grant(text, uuid, text, text, text)",
    "cordis.issue_grant(text, uuid, text, text, text)",
    "cordis.approve_grant(uuid, text)",
    "cordis.deny_grant(uuid, text)",
    "cordis.revoke_grant(uuid, text)",
)
LIVE_ID = "cordis.slice_live_grants(text, uuid)"
HAS_ID = "cordis.slice_has_grant(text, uuid, text, text)"
GRANT_CONSTRAINTS = (
    "grants_pkey",
    "grants_slice_kind_target_key",
    "grants_slice_fkey",
    "grants_kind_check",
    "grants_status_check",
    "grants_requested_by_kind_check",
    "grants_decided_by_kind_check",
    "grants_revoked_by_kind_check",
    "grants_target_by_kind_check",
    "grants_status_times_check",
)


def _sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _apply_p07_tree(pgdata: Path, tmp_path: Path, database: str = P07_DB) -> str:
    tree = tmp_path / "sql_p07"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir()
    for name in P07_FILES:
        shutil.copy(SQL / name, tree / name)
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        database,
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def _psql_verbose(server, database: str, sql: str) -> str:
    return psql(server, database, sql, "-v", "VERBOSITY=verbose")


def _expect_error(
    server, database: str, sql: str, fragment: str, sqlstate: str | None = None
) -> str:
    try:
        _psql_verbose(server, database, sql)
    except RuntimeError as exc:
        msg = str(exc)
        assert fragment in msg, msg
        if sqlstate is not None:
            assert sqlstate in msg, msg
        return msg
    raise AssertionError(f"expected error containing {fragment!r} for {sql}")


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


def _create_slice(server, database: str, run_id: str, name: str) -> str:
    return psql(
        server,
        database,
        "SELECT cordis.create_slice("
        f"{_sql_str(run_id)}, {_sql_str(name)}, 'host');",
    )


def test_p07_fresh_apply_catalog_and_version(pgdata: Path, tmp_path: Path) -> None:
    out = _apply_p07_tree(pgdata, tmp_path)
    assert (
        "files=0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,"
        "0003_p03_wait_event.sql,0006_p06_plugin_catalog.sql,"
        "0007_p07_grant_registry.sql"
        in out
    )
    server = get_server(pgdata)
    assert psql(server, P07_DB, "SELECT cordis.get_schema_version();") == "p07"
    for rel in (
        "named_corpora",
        "slices",
        "grants",
        "jobs",
        "agent_steps",
        "run_events",
        "plugin_catalog",
    ):
        assert (
            psql(
                server,
                P07_DB,
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                f"WHERE n.nspname = 'cordis' AND c.relkind = 'r' AND c.relname = '{rel}';",
            )
            == "1"
        )
    assert (
        psql(
            server,
            P07_DB,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'cordis' AND table_name = 'grants' "
            "AND column_name = 'run_id';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P07_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
            "AND c.relname IN ('named_corpora','slices','grants');",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P07_DB,
            "SELECT count(*) FROM pg_extension WHERE extname = 'pg_cordis';",
        )
        == "0"
    )
    ids = psql(
        server,
        P07_DB,
        "SELECT n.nspname || '.' || p.proname || '(' || "
        "pg_catalog.oidvectortypes(p.proargtypes) || ')' "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN ("
        "'register_named_corpus','create_slice','request_grant',"
        "'issue_grant','approve_grant','deny_grant','revoke_grant',"
        "'slice_live_grants','slice_has_grant') ORDER BY 1;",
    ).splitlines()
    assert ids == sorted(WRITER_IDS + (LIVE_ID, HAS_ID))
    vol = dict(
        line.split(":", 1)
        for line in psql(
            server,
            P07_DB,
            "SELECT n.nspname || '.' || p.proname || '(' || "
            "pg_catalog.oidvectortypes(p.proargtypes) || '):' || "
            "p.provolatile::text || ':' || p.prosecdef::text "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cordis' AND p.proname IN ("
            "'register_named_corpus','create_slice','request_grant',"
            "'issue_grant','approve_grant','deny_grant','revoke_grant',"
            "'slice_live_grants','slice_has_grant');",
        ).splitlines()
    )
    for ident in WRITER_IDS:
        assert vol[ident] == "v:false", ident
    assert vol[LIVE_ID] == "s:false"
    assert vol[HAS_ID] == "s:false"
    version = psql(
        server,
        P07_DB,
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
    for proname in (
        "register_named_corpus",
        "create_slice",
        "request_grant",
        "issue_grant",
        "approve_grant",
        "deny_grant",
        "revoke_grant",
        "slice_live_grants",
        "slice_has_grant",
    ):
        assert (
            psql(
                server,
                P07_DB,
                "SELECT count(*) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                f"WHERE n.nspname = 'cordis' AND p.proname = '{proname}';",
            )
            == "1"
        )


def test_p07_constraints_and_tuple_unique(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    names = psql(
        server,
        P07_DB,
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'cordis.grants'::regclass "
        "AND conname NOT LIKE '%\\_not\\_null' ESCAPE '\\' "
        "ORDER BY 1;",
    ).splitlines()
    assert names == sorted(GRANT_CONSTRAINTS)
    fkey = psql(
        server,
        P07_DB,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'grants_slice_fkey';",
    )
    assert "ON DELETE RESTRICT" in fkey
    uniq = psql(
        server,
        P07_DB,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'grants_slice_kind_target_key';",
    )
    assert "UNIQUE (slice_id, kind, target)" in uniq
    target_check = psql(
        server,
        P07_DB,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'grants_target_by_kind_check';",
    )
    assert "btrim" in target_check.lower()
    assert "event" in target_check
    assert (
        psql(
            server,
            P07_DB,
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname = 'cordis' AND indexname = 'grants_slice_status_idx';",
        )
        == "1"
    )


def test_p07_two_named_corpus_on_two_slices(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'Project 1', 'host');")
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-2', 'Project 2', 'host');")
    s1 = _create_slice(server, P07_DB, "run-d5", "fn-1")
    s2 = _create_slice(server, P07_DB, "run-d5", "fn-2-3")
    psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-d5', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
    )
    psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-d5', "
        f"{_sql_str(s2)}::uuid, 'named_corpus', 'project-2', 'host');",
    )
    pending = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-d5', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-2', 'model');",
    )
    live1 = psql(
        server,
        P07_DB,
        "SELECT d5_literal FROM cordis.slice_live_grants('run-d5', "
        f"{_sql_str(s1)}::uuid);",
    )
    live2 = psql(
        server,
        P07_DB,
        "SELECT d5_literal FROM cordis.slice_live_grants('run-d5', "
        f"{_sql_str(s2)}::uuid);",
    )
    assert live1 == "named_corpus:project-1"
    assert live2 == "named_corpus:project-2"
    assert (
        psql(
            server,
            P07_DB,
            "SELECT cordis.slice_has_grant('run-d5', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-2');",
        )
        == "f"
    )
    row = psql(
        server,
        P07_DB,
        "SELECT status || '|' || requested_by_kind FROM cordis.grants "
        f"WHERE grant_id = {_sql_str(pending)}::uuid;",
    )
    assert row == "pending|model"
    inventory = psql(
        server,
        P07_DB,
        "SELECT count(*) FROM cordis.grants g "
        "JOIN cordis.slices s ON s.slice_id = g.slice_id "
        "WHERE s.run_id = 'run-d5';",
    )
    assert inventory == "3"


def test_p07_model_request_stays_pending(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    gid = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'model');",
    )
    assert (
        psql(
            server,
            P07_DB,
            f"SELECT status FROM cordis.grants WHERE grant_id = {_sql_str(gid)}::uuid;",
        )
        == "pending"
    )
    assert (
        psql(
            server,
            P07_DB,
            "SELECT cordis.slice_has_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1');",
        )
        == "f"
    )
    assert (
        psql(
            server,
            P07_DB,
            "SELECT count(*) FROM cordis.slice_live_grants('run-a', "
            f"{_sql_str(s1)}::uuid);",
        )
        == "0"
    )


def test_p07_issue_rejects_asserted_model_kind(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    _expect_error(
        server,
        P07_DB,
        "SELECT cordis.register_named_corpus('project-1', 'P1', 'model');",
        "issuer must not be model",
        "42501",
    )
    _expect_error(
        server,
        P07_DB,
        "SELECT cordis.create_slice('run-a', 's1', 'model');",
        "issuer must not be model",
        "42501",
    )
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    _expect_error(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'model');",
        "issuer must not be model",
        "42501",
    )
    gid = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'model');",
    )
    for fn in ("approve_grant", "deny_grant"):
        _expect_error(
            server,
            P07_DB,
            f"SELECT cordis.{fn}({_sql_str(gid)}::uuid, 'model');",
            "issuer must not be model",
            "42501",
        )
    issued = psql(
        server,
        P07_DB,
        f"SELECT cordis.approve_grant({_sql_str(gid)}::uuid, 'host');",
    )
    _expect_error(
        server,
        P07_DB,
        f"SELECT cordis.revoke_grant({_sql_str(issued)}::uuid, 'model');",
        "issuer must not be model",
        "42501",
    )
    assert (
        psql(server, P07_DB, "SELECT count(*) FROM cordis.named_corpora;")
        == "1"
    )


def test_p07_approve_and_deny_pending(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-2', 'P2', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    g1 = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'model');",
    )
    psql(server, P07_DB, f"SELECT cordis.approve_grant({_sql_str(g1)}::uuid, 'host');")
    assert (
        psql(
            server,
            P07_DB,
            "SELECT cordis.slice_has_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1');",
        )
        == "t"
    )
    g2 = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-2', 'model');",
    )
    psql(server, P07_DB, f"SELECT cordis.deny_grant({_sql_str(g2)}::uuid, 'user');")
    assert (
        psql(
            server,
            P07_DB,
            f"SELECT status FROM cordis.grants WHERE grant_id = {_sql_str(g2)}::uuid;",
        )
        == "denied"
    )
    assert (
        psql(
            server,
            P07_DB,
            "SELECT cordis.slice_has_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-2');",
        )
        == "f"
    )


def test_p07_request_is_idempotent_and_does_not_approve(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    g1 = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'model');",
    )
    g2 = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'user');",
    )
    assert g1 == g2
    assert (
        psql(
            server,
            P07_DB,
            "SELECT status || '|' || requested_by_kind FROM cordis.grants "
            f"WHERE grant_id = {_sql_str(g1)}::uuid;",
        )
        == "pending|model"
    )
    issued = psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
    )
    again = psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'user');",
    )
    assert issued == again
    observed = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'model');",
    )
    assert observed == issued
    assert (
        psql(
            server,
            P07_DB,
            "SELECT status || '|' || requested_by_kind FROM cordis.grants "
            f"WHERE grant_id = {_sql_str(issued)}::uuid;",
        )
        == "issued|model"
    )
    assert (
        psql(server, P07_DB, "SELECT count(*) FROM cordis.grants;")
        == "1"
    )


def test_p07_rejects_sql_predicate_and_version_suffix(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    for kind, target in (
        ("named_corpus:project-1", "project-1"),
        ("named_corpus", "project-1:v1"),
        ("named_corpus", "project-1 WHERE true"),
        ("run OR true", ""),
    ):
        _expect_error(
            server,
            P07_DB,
            "SELECT cordis.issue_grant('run-a', "
            f"{_sql_str(s1)}::uuid, {_sql_str(kind)}, {_sql_str(target)}, 'host');",
            "22023",
        )


def test_p07_unknown_corpus_and_slice_mismatch(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    _expect_error(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'missing', 'host');",
        "unknown named corpus",
        "22023",
    )
    _expect_error(
        server,
        P07_DB,
        "SELECT cordis.slice_has_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'missing');",
        "unknown named corpus",
        "22023",
    )
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    _expect_error(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-b', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
        "slice does not belong to run",
        "22023",
    )


def test_p07_event_and_run_kinds(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'run', NULL, 'host');",
    )
    psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'event', 'scope-1', 'host');",
    )
    lits = psql(
        server,
        P07_DB,
        "SELECT string_agg(d5_literal, ',' ORDER BY d5_literal) "
        "FROM cordis.slice_live_grants('run-a', "
        f"{_sql_str(s1)}::uuid);",
    )
    assert lits == "event:scope-1,run"
    assert (
        psql(server, P07_DB, "SELECT count(*) FROM cordis.run_events;")
        == "0"
    )


def test_p07_event_scope_round_trips_p03_opacity(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    psql(
        server,
        P07_DB,
        "SELECT cordis.emit_event('Acme/scope:v1', 'n', '{}'::jsonb);",
    )
    psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'event', 'Acme/scope:v1', 'host');",
    )
    row = psql(
        server,
        P07_DB,
        "SELECT target || '|' || d5_literal FROM cordis.slice_live_grants('run-a', "
        f"{_sql_str(s1)}::uuid);",
    )
    assert row == "Acme/scope:v1|event:Acme/scope:v1"
    assert (
        psql(
            server,
            P07_DB,
            "SELECT count(*) FROM cordis.run_events "
            "WHERE event_scope_id = 'Acme/scope:v1';",
        )
        == "1"
    )


def test_p07_revoke_drops_live_not_log(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    gid = psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
    )
    before = psql(
        server,
        P07_DB,
        "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'run-a';",
    )
    psql(server, P07_DB, f"SELECT cordis.revoke_grant({_sql_str(gid)}::uuid, 'host');")
    assert (
        psql(
            server,
            P07_DB,
            "SELECT cordis.slice_has_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1');",
        )
        == "f"
    )
    after = psql(
        server,
        P07_DB,
        "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'run-a';",
    )
    assert before == after == "0"
    again = psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
    )
    assert again == gid
    assert (
        psql(
            server,
            P07_DB,
            "SELECT cordis.slice_has_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1');",
        )
        == "t"
    )


def test_p07_corpus_is_live_root_identity(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
    )
    cols = psql(
        server,
        P07_DB,
        "SELECT string_agg(column_name, ',' ORDER BY column_name) "
        "FROM information_schema.columns "
        "WHERE table_schema = 'cordis' "
        "AND table_name IN ('named_corpora','grants') "
        "AND column_name ~ 'revision|fingerprint|snapshot';",
    )
    assert cols == ""
    # Live-root: P07 names the registered corpus; it does not freeze file contents.


def test_p07_concurrent_request_issue_deny_revoke(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")

    errors: list[BaseException] = []
    results: list[str] = []

    def issue_blocked() -> None:
        try:
            results.append(
                psql(
                    server,
                    P07_DB,
                    "SET statement_timeout = '8s'; "
                    "SELECT cordis.issue_grant('run-a', "
                    f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
                )
            )
        except Exception as exc:
            errors.append(exc)

    with psql_session(server, P07_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        req = session.execute(
            "SELECT cordis.request_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'model');"
        )
        assert len(req) == 1
        thread = threading.Thread(target=issue_blocked)
        thread.start()
        _wait_for_blocked_backend(server, P07_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert errors == []
    assert results and results[0] == req[0]
    assert (
        psql(
            server,
            P07_DB,
            f"SELECT status FROM cordis.grants WHERE grant_id = {_sql_str(results[0])}::uuid;",
        )
        == "issued"
    )

    # issue then deny from pending on a fresh tuple
    s_deny = _create_slice(server, P07_DB, "run-a", "s-deny")
    pending_deny = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s_deny)}::uuid, 'named_corpus', 'project-1', 'model');",
    )
    deny_errors: list[BaseException] = []

    def deny_blocked() -> None:
        try:
            _psql_verbose(
                server,
                P07_DB,
                "SET statement_timeout = '8s'; "
                f"SELECT cordis.deny_grant({_sql_str(pending_deny)}::uuid, 'host');",
            )
        except Exception as exc:
            deny_errors.append(exc)

    with psql_session(server, P07_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        issued_pending = session.execute(
            "SELECT cordis.issue_grant('run-a', "
            f"{_sql_str(s_deny)}::uuid, 'named_corpus', 'project-1', 'host');"
        )
        assert issued_pending == [pending_deny]
        thread = threading.Thread(target=deny_blocked)
        thread.start()
        _wait_for_blocked_backend(server, P07_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert deny_errors
    deny_msg = str(deny_errors[0])
    assert "grant is not pending" in deny_msg
    assert "22023" in deny_msg

    # revoke then issue: final issued, same id
    revoke_then: list[str] = []
    issue_after: list[str] = []

    def issue_after_revoke() -> None:
        try:
            issue_after.append(
                psql(
                    server,
                    P07_DB,
                    "SET statement_timeout = '8s'; "
                    "SELECT cordis.issue_grant('run-a', "
                    f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
                )
            )
        except Exception as exc:
            errors.append(exc)

    with psql_session(server, P07_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        revoked = session.execute(
            f"SELECT cordis.revoke_grant({_sql_str(results[0])}::uuid, 'host');"
        )
        revoke_then.extend(revoked)
        thread = threading.Thread(target=issue_after_revoke)
        thread.start()
        _wait_for_blocked_backend(server, P07_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert issue_after == revoke_then == [results[0]]
    assert (
        psql(
            server,
            P07_DB,
            f"SELECT status FROM cordis.grants WHERE grant_id = {_sql_str(results[0])}::uuid;",
        )
        == "issued"
    )

    # deny then issue from pending on a second slice
    s2 = _create_slice(server, P07_DB, "run-a", "s2")
    pending2 = psql(
        server,
        P07_DB,
        "SELECT cordis.request_grant('run-a', "
        f"{_sql_str(s2)}::uuid, 'named_corpus', 'project-1', 'model');",
    )
    issue2: list[str] = []

    def issue_after_deny() -> None:
        try:
            issue2.append(
                psql(
                    server,
                    P07_DB,
                    "SET statement_timeout = '8s'; "
                    "SELECT cordis.issue_grant('run-a', "
                    f"{_sql_str(s2)}::uuid, 'named_corpus', 'project-1', 'host');",
                )
            )
        except Exception as exc:
            errors.append(exc)

    with psql_session(server, P07_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        session.execute(
            f"SELECT cordis.deny_grant({_sql_str(pending2)}::uuid, 'host');"
        )
        thread = threading.Thread(target=issue_after_deny)
        thread.start()
        _wait_for_blocked_backend(server, P07_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert issue2 == [pending2]
    assert (
        psql(
            server,
            P07_DB,
            f"SELECT status FROM cordis.grants WHERE grant_id = {_sql_str(pending2)}::uuid;",
        )
        == "issued"
    )

    # issue then revoke
    rev_errors: list[BaseException] = []

    def revoke_blocked() -> None:
        try:
            psql(
                server,
                P07_DB,
                "SET statement_timeout = '8s'; "
                f"SELECT cordis.revoke_grant({_sql_str(pending2)}::uuid, 'host');",
            )
        except Exception as exc:
            rev_errors.append(exc)

    with psql_session(server, P07_DB) as session:
        session.execute("BEGIN")
        session.execute("SET LOCAL statement_timeout = '8s'")
        session.execute(
            "SELECT cordis.issue_grant('run-a', "
            f"{_sql_str(s2)}::uuid, 'named_corpus', 'project-1', 'host');"
        )
        thread = threading.Thread(target=revoke_blocked)
        thread.start()
        _wait_for_blocked_backend(server, P07_DB)
        session.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert rev_errors == []
    assert (
        psql(
            server,
            P07_DB,
            f"SELECT status FROM cordis.grants WHERE grant_id = {_sql_str(pending2)}::uuid;",
        )
        == "revoked"
    )


def test_p07_api_errors_are_22023(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    cases = [
        ("SELECT cordis.register_named_corpus(NULL, 'P1', 'host');", "invalid corpus id"),
        ("SELECT cordis.register_named_corpus('project-2', NULL, 'host');", "invalid corpus label"),
        ("SELECT cordis.register_named_corpus('project-1', 'Other', 'host');", "corpus already registered"),
        ("SELECT cordis.create_slice(NULL, 's1', 'host');", "invalid run_id"),
        ("SELECT cordis.create_slice('run-a', NULL, 'host');", "invalid slice name"),
        ("SELECT cordis.create_slice('run-a', 's1', 'host');", "duplicate slice name"),
        ("SELECT cordis.create_slice('run-a', 's2', 'other');", "invalid issuer_kind"),
        (
            "SELECT cordis.request_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'nope');",
            "invalid requester_kind",
        ),
        (
            "SELECT cordis.issue_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'named_corpus', NULL, 'host');",
            "invalid grant target",
        ),
        (
            "SELECT cordis.issue_grant('run-a', "
            f"{_sql_str(s1)}::uuid, 'event', NULL, 'host');",
            "invalid grant target",
        ),
        (
            "SELECT cordis.issue_grant('run-a', "
            f"{_sql_str(s1)}::uuid, NULL, 'project-1', 'host');",
            "unknown grant kind",
        ),
        (
            "SELECT cordis.slice_has_grant('run-a', "
            f"{_sql_str(s1)}::uuid, NULL, 'project-1');",
            "unknown grant kind",
        ),
        (
            "SELECT cordis.register_named_corpus('project-x', E'bad\\x01label', 'host');",
            "invalid corpus label",
        ),
        (
            "SELECT cordis.register_named_corpus("
            "'project-y', pg_catalog.chr(133), 'host');",
            "invalid corpus label",
        ),
        ("SELECT cordis.approve_grant(NULL, 'host');", "grant not found"),
    ]
    for sql, fragment in cases:
        _expect_error(server, P07_DB, sql, fragment, "22023")
    gid = psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'run', NULL, 'host');",
    )
    assert (
        psql(
            server,
            P07_DB,
            f"SELECT target FROM cordis.grants WHERE grant_id = {_sql_str(gid)}::uuid;",
        )
        == ""
    )


def test_p07_no_run_union_retrieval_function(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    assert (
        psql(
            server,
            P07_DB,
            "SELECT count(*) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cordis' "
            "AND p.proname IN ('run_live_grants','run_grants');",
        )
        == "0"
    )


def test_p07_replay_preserves_grants(pgdata: Path, tmp_path: Path) -> None:
    _apply_p07_tree(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(server, P07_DB, "SELECT cordis.register_named_corpus('project-1', 'P1', 'host');")
    s1 = _create_slice(server, P07_DB, "run-a", "s1")
    gid = psql(
        server,
        P07_DB,
        "SELECT cordis.issue_grant('run-a', "
        f"{_sql_str(s1)}::uuid, 'named_corpus', 'project-1', 'host');",
    )
    before = psql(
        server,
        P07_DB,
        "SELECT status || '|' || created_at::text || '|' || decided_at::text "
        f"FROM cordis.grants WHERE grant_id = {_sql_str(gid)}::uuid;",
    )
    tree = tmp_path / "sql_p07"
    replay = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P07_DB,
        "--sql-root",
        str(tree),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    after = psql(
        server,
        P07_DB,
        "SELECT status || '|' || created_at::text || '|' || decided_at::text "
        f"FROM cordis.grants WHERE grant_id = {_sql_str(gid)}::uuid;",
    )
    assert after == before


def test_p07_sql_tree_grant_word_only_in_quotes_or_comments() -> None:
    apply_mod = load_apply_module()
    path = SQL / "0007_p07_grant_registry.sql"
    body = path.read_text()
    assert "$p07$" in body
    scanned = apply_mod.sanitize_sql_for_preflight(body)
    assert apply_mod.FORBIDDEN_STMTS[4].search(scanned) is None
