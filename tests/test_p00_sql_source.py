"""P00 source-tree and apply CLI tests. Invokes tools/apply_pg_cordis.py via subprocess."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pgembed import POSTGRES_BIN_PATH, get_server

from tests.conftest import (
    REPO,
    SQL,
    load_apply_module,
    next_sql_prefix,
    psql,
    run_apply,
)

P01_FUNCTIONS = (
    "cordis.claim_job",
    "cordis.complete_claim",
    "cordis.fail_claim",
    "cordis.get_schema_version",
    "cordis.release_stale",
    "cordis.renew_claim",
    "cordis.yield_claim",
)


def test_fresh_apply_lists_current_tree_and_p01(pgdata: Path) -> None:
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p00",
        "--reset",
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "files=0000_kernel.sql,0001_p01_claim.sql" in result.stdout
    assert "mode=reset" in result.stdout
    assert "bootstrap verification ok" in result.stdout

    server = get_server(pgdata)
    assert psql(server, "cordis_p00", "SELECT cordis.get_schema_version();") == "p01"
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname = 'jobs';",
        )
        == "1"
    )
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname IN "
            "('agent_steps','run_waits','run_events');",
        )
        == "0"
    )
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_cordis';",
        )
        == "0"
    )
    names = psql(
        server,
        "cordis_p00",
        "SELECT n.nspname || '.' || p.proname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' ORDER BY 1;",
    ).splitlines()
    assert names == list(P01_FUNCTIONS)
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "AND c.relname NOT LIKE 'pg_%';",
        )
        == "0"
    )


def test_second_in_place_apply_succeeds(pgdata: Path) -> None:
    first = run_apply("--pgdata", str(pgdata), "--database", "cordis_p00")
    assert first.returncode == 0, first.stdout + first.stderr
    second = run_apply("--pgdata", str(pgdata), "--database", "cordis_p00")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "mode=in-place" in second.stdout


def test_in_place_preserves_public_sentinel(pgdata: Path) -> None:
    assert run_apply("--pgdata", str(pgdata), "--database", "cordis_p00").returncode == 0
    server = get_server(pgdata)
    psql(
        server,
        "cordis_p00",
        "CREATE TABLE IF NOT EXISTS public.p00_sentinel (id int);",
    )
    result = run_apply("--pgdata", str(pgdata), "--database", "cordis_p00")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'p00_sentinel';",
        )
        == "1"
    )


def test_numbered_file_extension_without_loader_change(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = tmp_path / "sql"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    probe_name = f"{prefix}_test_probe.sql"
    (tree / probe_name).write_text(
        "CREATE OR REPLACE FUNCTION cordis.p00_probe()\n"
        "RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT 'probe'::text; $$;\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p00_probe",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        f"files=0000_kernel.sql,0001_p01_claim.sql,{probe_name}" in result.stdout
    )
    server = get_server(pgdata)
    assert psql(server, "cordis_p00_probe", "SELECT cordis.p00_probe();") == "probe"
    assert not (SQL / probe_name).exists()


def test_preflight_allows_later_cordis_table(pgdata: Path, tmp_path: Path) -> None:
    tree = tmp_path / "sql_table"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_p00_allowed.sql").write_text(
        "CREATE TABLE IF NOT EXISTS cordis.p00_allowed (id int PRIMARY KEY);\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p00_table",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_plpgsql_end_inside_dollar_quotes_applies(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = tmp_path / "sql_plpgsql"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_plpgsql_end.sql").write_text(
        "CREATE OR REPLACE FUNCTION cordis.p01_plpgsql_probe()\n"
        "RETURNS text\n"
        "LANGUAGE plpgsql\n"
        "AS $fn$\n"
        "BEGIN\n"
        "  RETURN 'ok';\n"
        "END;\n"
        "$fn$;\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p01_plpgsql",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    server = get_server(pgdata)
    assert (
        psql(server, "cordis_p01_plpgsql", "SELECT cordis.p01_plpgsql_probe();")
        == "ok"
    )


@pytest.mark.parametrize(
    "stmt,db",
    [
        ("BEGIN;", "cordis_bad_begin"),
        ("COMMIT;", "cordis_bad_commit"),
        ("ROLLBACK;", "cordis_bad_rollback"),
        ("END;", "cordis_bad_end"),
        ("START TRANSACTION;", "cordis_bad_start"),
    ],
)
def test_top_level_transaction_control_exits_2(
    pgdata: Path, tmp_path: Path, stmt: str, db: str
) -> None:
    assert run_apply("--pgdata", str(pgdata), "--database", "cordis_p00").returncode == 0
    tree = tmp_path / db
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_txn_bad.sql").write_text(f"{stmt}\nSELECT 1;\n")
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        db,
        "--sql-root",
        str(tree),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    server = get_server(pgdata)
    found = psql(
        server,
        "postgres",
        f"SELECT COUNT(*) FROM pg_database WHERE datname = '{db}';",
    )
    assert found == "0"


@pytest.mark.parametrize(
    "mutator,db",
    [
        ("missing_0000", "cordis_bad_a"),
        ("bad_name", "cordis_bad_b"),
        ("hyphen_name", "cordis_bad_c"),
        ("duplicate_prefix", "cordis_bad_d"),
        ("nested", "cordis_bad_e"),
        ("empty", "cordis_bad_f"),
        ("meta_connect", "cordis_bad_g"),
        ("grant", "cordis_bad_h"),
        ("create_database", "cordis_bad_i"),
        ("include", "cordis_bad_j"),
    ],
)
def test_invalid_tree_exits_2_without_creating_database(
    pgdata: Path, tmp_path: Path, mutator: str, db: str
) -> None:
    assert run_apply("--pgdata", str(pgdata), "--database", "cordis_p00").returncode == 0
    tree = tmp_path / mutator
    if mutator == "empty":
        tree.mkdir()
    else:
        shutil.copytree(SQL, tree)
        prefix = next_sql_prefix(tree)
        if mutator == "missing_0000":
            (tree / "0000_kernel.sql").unlink()
        elif mutator == "bad_name":
            (tree / "bad.sql").write_text("SELECT 1;\n")
        elif mutator == "hyphen_name":
            (tree / f"{prefix}-p01.sql").write_text("SELECT 1;\n")
        elif mutator == "duplicate_prefix":
            (tree / f"{prefix}_first.sql").write_text("SELECT 1;\n")
            (tree / f"{prefix}_second.sql").write_text("SELECT 1;\n")
        elif mutator == "nested":
            nested = tree / "migrations"
            nested.mkdir()
            (nested / f"{prefix}.sql").write_text("SELECT 1;\n")
        elif mutator == "meta_connect":
            (tree / f"{prefix}_p01_bad.sql").write_text(
                "\\connect postgres\nSELECT 1;\n"
            )
        elif mutator == "grant":
            (tree / f"{prefix}_p01_bad.sql").write_text(
                "GRANT USAGE ON SCHEMA cordis TO PUBLIC;\n"
            )
        elif mutator == "create_database":
            (tree / f"{prefix}_p01_bad.sql").write_text("CREATE DATABASE evil;\n")
        elif mutator == "include":
            (tree / f"{prefix}_p01_bad.sql").write_text(
                "\\include foo.sql\nSELECT 1;\n"
            )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        db,
        "--sql-root",
        str(tree),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    server = get_server(pgdata)
    found = psql(
        server,
        "postgres",
        f"SELECT COUNT(*) FROM pg_database WHERE datname = '{db}';",
    )
    assert found == "0"


def test_sql_failure_rolls_back_tree(pgdata: Path, tmp_path: Path) -> None:
    tree = tmp_path / "rollback_sql"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_p01_fail.sql").write_text(
        "CREATE OR REPLACE FUNCTION cordis.should_not_exist()\n"
        "RETURNS text LANGUAGE sql AS $$ SELECT 'x'::text; $$;\n"
        "SELECT 1 / 0;\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p00_fail",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    server = get_server(pgdata)
    exists = psql(
        server,
        "postgres",
        "SELECT COUNT(*) FROM pg_database WHERE datname = 'cordis_p00_fail';",
    )
    assert exists == "1"
    nsp = psql(
        server,
        "cordis_p00_fail",
        "SELECT COUNT(*) FROM pg_namespace WHERE nspname = 'cordis';",
    )
    assert nsp == "0"


def test_uppercase_database_name_rejected(pgdata: Path) -> None:
    result = run_apply("--pgdata", str(pgdata), "--database", "Cordis_P00")
    assert result.returncode == 2


def test_missing_database_flag_exits_2() -> None:
    result = run_apply()
    assert result.returncode == 2


def test_sql_tree_has_no_forbidden_tokens() -> None:
    apply_mod = load_apply_module()
    create_table_re = re.compile(
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[^\s(]+)",
        re.I,
    )
    for path in SQL.rglob("*.sql"):
        body = path.read_text()
        for line in body.splitlines():
            assert not line.lstrip().startswith("\\"), path
        scanned = apply_mod.sanitize_sql_for_preflight(body)
        for pattern in apply_mod.FORBIDDEN_STMTS:
            assert pattern.search(scanned) is None, (path, pattern.pattern)
        for match in create_table_re.finditer(scanned):
            name = match.group("name").strip('"')
            assert name.lower().startswith("cordis."), path


def test_sanitize_keeps_commit_between_string_dollar_lookalikes() -> None:
    apply_mod = load_apply_module()
    payload = (
        "CREATE TABLE cordis.before_commit (id integer);\n"
        "SELECT '$hide$';\n"
        "COMMIT;\n"
        "SELECT '$hide$';\n"
        "SELECT 1 / 0;\n"
    )
    scanned = apply_mod.sanitize_sql_for_preflight(payload)
    assert re.search(r"(?:^|;)\s*COMMIT\s*;", scanned, re.I | re.M)
    e_payload = (
        "SELECT E'$hide$';\n"
        "COMMIT;\n"
        "SELECT E'$hide$';\n"
    )
    e_scanned = apply_mod.sanitize_sql_for_preflight(e_payload)
    assert re.search(r"(?:^|;)\s*COMMIT\s*;", e_scanned, re.I | re.M)


def test_string_dollar_lookalike_cannot_hide_commit(
    pgdata: Path, tmp_path: Path
) -> None:
    assert run_apply("--pgdata", str(pgdata), "--database", "cordis_p00").returncode == 0
    tree = tmp_path / "hide_commit"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_hide_commit.sql").write_text(
        "CREATE TABLE cordis.before_commit (id integer);\n"
        "SELECT '$hide$';\n"
        "COMMIT;\n"
        "SELECT '$hide$';\n"
        "SELECT 1 / 0;\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_hide_commit",
        "--sql-root",
        str(tree),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    server = get_server(pgdata)
    found = psql(
        server,
        "postgres",
        "SELECT COUNT(*) FROM pg_database WHERE datname = 'cordis_hide_commit';",
    )
    assert found == "0"


@pytest.mark.skipif(
    not (
        Path(os.environ.get("PG_AGENT_ROOT", REPO.parent / "pg-agent")).is_dir()
        and (
            Path(os.environ.get("PG_AGENT_ROOT", REPO.parent / "pg-agent"))
            / "v2"
            / "setup_db.py"
        ).is_file()
    ),
    reason="pg-agent checkout not available",
)
def test_pg_agent_separate_database_composition() -> None:
    agent_root = Path(
        os.environ.get("PG_AGENT_ROOT", REPO.parent / "pg-agent")
    ).resolve()
    agent_pgdata = agent_root / ".pgdata"
    db = "cordis_p00_comp"
    setup = subprocess.run(
        ["uv", "run", "python", "v2/setup_db.py"],
        cwd=str(agent_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    server = get_server(agent_pgdata)
    try:
        result = run_apply(
            "--pgdata",
            str(agent_pgdata),
            "--database",
            db,
            "--reset",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert psql(server, db, "SELECT cordis.get_schema_version();") == "p01"
        assert (
            psql(
                server,
                db,
                "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'cordis' AND c.relname = 'jobs';",
            )
            == "1"
        )
        assert (
            psql(
                server,
                db,
                "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname IN ('jobs','agent_runs','agent_steps');",
            )
            == "0"
        )
        assert (
            psql(
                server,
                "da_agent",
                "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = 'jobs';",
            )
            == "1"
        )
        assert (
            psql(
                server,
                "da_agent",
                "SELECT COUNT(*) FROM pg_namespace WHERE nspname = 'cordis';",
            )
            == "0"
        )
        assert not list(SQL.glob("pg_agent*.sql"))
    finally:
        subprocess.run(
            [
                str(POSTGRES_BIN_PATH / "psql"),
                server.get_uri("postgres"),
                "--no-psqlrc",
                "-v",
                "ON_ERROR_STOP=1",
                "-q",
            ],
            input=f"DROP DATABASE IF EXISTS {db} WITH (FORCE);\n".encode(),
            capture_output=True,
            check=False,
        )
