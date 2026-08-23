"""P00 source-tree and apply CLI tests. Invokes tools/apply_pg_cordis.py via subprocess."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pgembed import POSTGRES_BIN_PATH, get_server

REPO = Path(__file__).resolve().parents[1]
APPLY = REPO / "tools" / "apply_pg_cordis.py"
SQL = REPO / "sql"


def run_apply(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(APPLY), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        env=merged,
    )


def psql(server, database: str, sql: str, *extra: str) -> str:
    args = [
        str(POSTGRES_BIN_PATH / "psql"),
        server.get_uri(database),
        "--no-psqlrc",
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
        "-t",
        "-A",
        *extra,
    ]
    proc = subprocess.run(args, input=sql.encode(), capture_output=True, check=False)
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed ({proc.returncode}):\n{out}")
    return out.strip()


@pytest.fixture(scope="session")
def pgdata(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("pgdata")


def test_fresh_apply_lists_kernel_and_p00(pgdata: Path) -> None:
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p00",
        "--reset",
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "files=0000_kernel.sql" in result.stdout
    assert "mode=reset" in result.stdout
    assert "bootstrap verification ok" in result.stdout

    server = get_server(pgdata)
    assert psql(server, "cordis_p00", "SELECT cordis.get_schema_version();") == "p00"
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname IN "
            "('jobs','agent_steps','run_waits','run_events');",
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
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT n.nspname || '.' || p.proname FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cordis' ORDER BY 1;",
        )
        == "cordis.get_schema_version"
    )
    assert (
        psql(
            server,
            "cordis_p00",
            "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('cordis','public') AND c.relkind = 'r' "
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
    (tree / "0001_p01_probe.sql").write_text(
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
    assert "files=0000_kernel.sql,0001_p01_probe.sql" in result.stdout
    server = get_server(pgdata)
    assert psql(server, "cordis_p00_probe", "SELECT cordis.p00_probe();") == "probe"
    assert not (SQL / "0001_p01_probe.sql").exists()


def test_preflight_allows_later_cordis_table(pgdata: Path, tmp_path: Path) -> None:
    tree = tmp_path / "sql_table"
    shutil.copytree(SQL, tree)
    (tree / "0001_p01_table.sql").write_text(
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
        if mutator == "missing_0000":
            (tree / "0000_kernel.sql").unlink()
        elif mutator == "bad_name":
            (tree / "bad.sql").write_text("SELECT 1;\n")
        elif mutator == "hyphen_name":
            (tree / "0001-p01.sql").write_text("SELECT 1;\n")
        elif mutator == "duplicate_prefix":
            (tree / "0001_first.sql").write_text("SELECT 1;\n")
            (tree / "0001_second.sql").write_text("SELECT 1;\n")
        elif mutator == "nested":
            nested = tree / "migrations"
            nested.mkdir()
            (nested / "0001.sql").write_text("SELECT 1;\n")
        elif mutator == "meta_connect":
            (tree / "0001_p01_bad.sql").write_text("\\connect postgres\nSELECT 1;\n")
        elif mutator == "grant":
            (tree / "0001_p01_bad.sql").write_text(
                "GRANT USAGE ON SCHEMA cordis TO PUBLIC;\n"
            )
        elif mutator == "create_database":
            (tree / "0001_p01_bad.sql").write_text("CREATE DATABASE evil;\n")
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
    (tree / "0001_p01_fail.sql").write_text(
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
    for path in SQL.rglob("*.sql"):
        for line in path.read_text().splitlines():
            stripped = line.lstrip()
            if stripped.startswith("--"):
                continue
            upper = stripped.upper()
            assert "CREATE EXTENSION" not in upper, path
            assert "CREATE TABLE" not in upper, path
            assert not upper.startswith("GRANT"), path
            assert not stripped.startswith("\\"), path


@pytest.mark.skipif(
    not (
        Path(os.environ.get("PG_AGENT_ROOT", REPO.parent / "pg-agent")).is_dir()
        and (Path(os.environ.get("PG_AGENT_ROOT", REPO.parent / "pg-agent")) / "v2" / "setup_db.py").is_file()
    ),
    reason="pg-agent checkout not available",
)
def test_pg_agent_separate_database_composition() -> None:
    agent_root = Path(os.environ.get("PG_AGENT_ROOT", REPO.parent / "pg-agent")).resolve()
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
        assert psql(server, db, "SELECT cordis.get_schema_version();") == "p00"
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
