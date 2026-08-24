"""P06 plugin catalog tests. Apply stays a subprocess."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pgembed import get_server

from tests.conftest import SQL, next_sql_prefix, psql, run_apply

P06_DB = "cordis_p06"

PROOF = {
    "cordis_plugin": {
        "identity": "host.worktree.apply_edits",
        "version": "0.1.0",
        "name": "apply_edits",
        "description": "Apply an approved edit operation inside the bound worktree.",
        "locus": "host",
        "invocation": "host_tool",
        "required_grants": ["run"],
        "effect_class": "external",
        "retry_class": "idempotent",
        "reconciliation": "operation_key",
        "inject": ["worktree"],
        "provide": ["workspace.edit"],
        "intercept": {},
        "capability": ["worktree_write"],
        "session_scope": "run",
        "config": {},
    }
}


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _reset(pgdata: Path, database: str = P06_DB) -> None:
    result = run_apply(
        "--pgdata", str(pgdata), "--database", database, "--reset"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _register_sql(definition: dict) -> str:
    payload = json.dumps(definition, separators=(",", ":"))
    return (
        "SELECT cordis.register_host_plugin("
        + _sql_str(payload)
        + "::jsonb);"
    )


def _catalog_row(server, database: str, identity: str) -> str:
    return psql(
        server,
        database,
        "SELECT identity || '|' || version || '|' || locus || '|' || invocation "
        "|| '|' || required_grants::text || '|' || effect_class || '|' "
        "|| retry_class || '|' || reconciliation || '|' || source_kind || '|' "
        "|| (entrypoint IS NULL)::text "
        "FROM cordis.plugin_catalog "
        f"WHERE identity = {_sql_str(identity)};",
    )


def test_register_host_plugin_and_select(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    assert psql(server, P06_DB, "SELECT count(*) FROM cordis.plugin_catalog;") == "0"
    ident = psql(server, P06_DB, _register_sql(PROOF))
    assert ident == "host.worktree.apply_edits"
    assert (
        _catalog_row(server, P06_DB, ident)
        == "host.worktree.apply_edits|0.1.0|host|host_tool|{run}|external|"
        "idempotent|operation_key|host_registration|true"
    )
    inject = psql(
        server,
        P06_DB,
        "SELECT inject::text FROM cordis.plugin_catalog "
        f"WHERE identity = {_sql_str(ident)};",
    )
    assert json.loads(inject) == ["worktree"]
    provide = psql(
        server,
        P06_DB,
        "SELECT provide::text FROM cordis.plugin_catalog "
        f"WHERE identity = {_sql_str(ident)};",
    )
    assert json.loads(provide) == ["workspace.edit"]
    cap = psql(
        server,
        P06_DB,
        "SELECT capability::text FROM cordis.plugin_catalog "
        f"WHERE identity = {_sql_str(ident)};",
    )
    assert json.loads(cap) == ["worktree_write"]
    assert (
        psql(
            server,
            P06_DB,
            "SELECT session_scope FROM cordis.plugin_catalog "
            f"WHERE identity = {_sql_str(ident)};",
        )
        == "run"
    )
    config = psql(
        server,
        P06_DB,
        "SELECT config::text FROM cordis.plugin_catalog "
        f"WHERE identity = {_sql_str(ident)};",
    )
    assert json.loads(config) == {}
    metadata = psql(
        server,
        P06_DB,
        "SELECT metadata::text FROM cordis.plugin_catalog "
        f"WHERE identity = {_sql_str(ident)};",
    )
    assert json.loads(metadata) == PROOF
    assert psql(server, P06_DB, "SELECT cordis.refresh_plugins();") == "1"


def test_comment_refresh_compiles_cordis_function(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = tmp_path / "sql_comment"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    plugin = {
        "cordis_plugin": {
            "identity": "p06.session.echo",
            "version": "0.1.0",
            "locus": "in-db",
            "invocation": "session_select",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    body = (
        "CREATE OR REPLACE FUNCTION cordis.p06_session_echo()\n"
        "RETURNS jsonb\n"
        "LANGUAGE sql\n"
        "IMMUTABLE\n"
        "SECURITY INVOKER\n"
        "AS $$ SELECT jsonb_build_object('ok', true); $$;\n"
        "COMMENT ON FUNCTION cordis.p06_session_echo() IS $cmt$"
        + json.dumps(plugin, separators=(",", ":"))
        + "$cmt$;\n"
        "SELECT cordis.refresh_plugins();\n"
    )
    (tree / f"{prefix}_p06_comment.sql").write_text(body)
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p06_comment",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    server = get_server(pgdata)
    row = psql(
        server,
        "cordis_p06_comment",
        "SELECT source_kind || '|' || (entrypoint IS NOT NULL)::text "
        "|| '|' || entrypoint::text "
        "FROM cordis.plugin_catalog "
        "WHERE identity = 'p06.session.echo';",
    )
    assert row.startswith("comment|true|")
    assert "p06_session_echo" in row
    assert psql(
        server,
        "cordis_p06_comment",
        "SELECT n.nspname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE p.proname = 'p06_session_echo';",
    ) == "cordis"
    assert (
        psql(
            server,
            "cordis_p06_comment",
            "SELECT count(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'p06_session_echo';",
        )
        == "0"
    )
    assert (
        psql(server, "cordis_p06_comment", "SELECT cordis.refresh_plugins();")
        == "1"
    )


def test_in_place_replay_keeps_host_plugin(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(server, P06_DB, _register_sql(PROOF))
    psql(
        server,
        P06_DB,
        "CREATE TABLE IF NOT EXISTS public.p00_sentinel (id int);",
    )
    result = run_apply("--pgdata", str(pgdata), "--database", P06_DB)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode=in-place" in result.stdout
    assert "bootstrap verification ok" in result.stdout
    assert psql(server, P06_DB, "SELECT cordis.get_schema_version();") == "p07"
    assert (
        psql(
            server,
            P06_DB,
            "SELECT count(*) FROM cordis.host_plugin_definitions "
            "WHERE identity = 'host.worktree.apply_edits';",
        )
        == "1"
    )
    assert (
        _catalog_row(server, P06_DB, "host.worktree.apply_edits").endswith(
            "|host_registration|true"
        )
    )
    assert (
        psql(
            server,
            P06_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'p00_sentinel';",
        )
        == "1"
    )


def test_refresh_rejects_mutex_comment_and_preserves_previous_rows(
    pgdata: Path, tmp_path: Path
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(server, P06_DB, _register_sql(PROOF))
    before = _catalog_row(server, P06_DB, "host.worktree.apply_edits")
    tree = tmp_path / "sql_mutex"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    comment = {
        "cordis_plugin": {
            "identity": "p06.bad.mutex",
            "version": "0.1.0",
            "locus": "in-db",
            "invocation": "queue",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        },
        "job_handler": "nope",
        "workbench_plugin": "plugin_nope",
    }
    (tree / f"{prefix}_p06_bad_mutex.sql").write_text(
        "CREATE OR REPLACE FUNCTION cordis.p06_bad_mutex()\n"
        "RETURNS void LANGUAGE plpgsql AS $fn$\n"
        "BEGIN\n"
        "  NULL;\n"
        "END;\n"
        "$fn$;\n"
        "COMMENT ON FUNCTION cordis.p06_bad_mutex() IS $cmt$"
        + json.dumps(comment, separators=(",", ":"))
        + "$cmt$;\n"
        "SELECT cordis.refresh_plugins();\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P06_DB,
        "--sql-root",
        str(tree),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "mutex" in combined
    assert "22023" in combined or "mutex" in combined
    assert _catalog_row(server, P06_DB, "host.worktree.apply_edits") == before
    assert (
        psql(
            server,
            P06_DB,
            "SELECT count(*) FROM cordis.plugin_catalog "
            "WHERE identity = 'p06.bad.mutex';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P06_DB,
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cordis' AND p.proname = 'p06_bad_mutex';",
        )
        == "0"
    )


def test_refresh_rejects_malformed_comment_and_preserves_previous_rows(
    pgdata: Path, tmp_path: Path
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(server, P06_DB, _register_sql(PROOF))
    before_ts = psql(
        server,
        P06_DB,
        "SELECT refreshed_at::text FROM cordis.plugin_catalog "
        "WHERE identity = 'host.worktree.apply_edits';",
    )
    before = _catalog_row(server, P06_DB, "host.worktree.apply_edits")
    tree = tmp_path / "sql_malformed"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_p06_malformed.sql").write_text(
        "CREATE OR REPLACE FUNCTION cordis.p06_bad_json()\n"
        "RETURNS void LANGUAGE plpgsql AS $fn$\n"
        "BEGIN\n"
        "  NULL;\n"
        "END;\n"
        "$fn$;\n"
        "COMMENT ON FUNCTION cordis.p06_bad_json() IS $cmt${ \"cordis_plugin\": $cmt$;\n"
        "SELECT cordis.refresh_plugins();\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P06_DB,
        "--sql-root",
        str(tree),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "malformed JSON" in combined
    assert _catalog_row(server, P06_DB, "host.worktree.apply_edits") == before
    assert (
        psql(
            server,
            P06_DB,
            "SELECT refreshed_at::text FROM cordis.plugin_catalog "
            "WHERE identity = 'host.worktree.apply_edits';",
        )
        == before_ts
    )


def test_invalid_host_registration_preserves_previous_definition(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(server, P06_DB, _register_sql(PROOF))
    before_src = psql(
        server,
        P06_DB,
        "SELECT metadata::text FROM cordis.host_plugin_definitions "
        "WHERE identity = 'host.worktree.apply_edits';",
    )
    before = _catalog_row(server, P06_DB, "host.worktree.apply_edits")
    bad_pairs = [
        {
            **PROOF,
            "cordis_plugin": {**PROOF["cordis_plugin"], "locus": "host", "invocation": "queue"},
        },
        {
            **PROOF,
            "cordis_plugin": {
                **PROOF["cordis_plugin"],
                "required_grants": ["named_corpus:some-id"],
            },
        },
        {
            **PROOF,
            "cordis_plugin": {
                **PROOF["cordis_plugin"],
                "effect_class": "external",
                "retry_class": "replayable",
                "reconciliation": "none",
            },
        },
        {
            **PROOF,
            "cordis_plugin": {**PROOF["cordis_plugin"], "capability": None},
        },
    ]
    for bad in bad_pairs:
        try:
            psql(server, P06_DB, _register_sql(bad))
            raise AssertionError(f"expected failure for {bad['cordis_plugin']}")
        except RuntimeError as exc:
            msg = str(exc).lower()
            assert (
                "22023" in msg
                or "invalid" in msg
                or "illegal" in msg
                or "json null" in msg
                or "capability" in msg
            )
    assert (
        psql(
            server,
            P06_DB,
            "SELECT metadata::text FROM cordis.host_plugin_definitions "
            "WHERE identity = 'host.worktree.apply_edits';",
        )
        == before_src
    )
    assert _catalog_row(server, P06_DB, "host.worktree.apply_edits") == before


def test_unrelated_bad_comment_blocks_register_and_preserves_rows(
    pgdata: Path,
) -> None:
    db = "cordis_p06_pollute"
    _reset(pgdata, db)
    server = get_server(pgdata)
    psql(server, db, _register_sql(PROOF))
    before = _catalog_row(server, db, "host.worktree.apply_edits")
    psql(
        server,
        db,
        "CREATE OR REPLACE FUNCTION cordis.p06_unrelated()\n"
        "RETURNS void LANGUAGE plpgsql AS $fn$\n"
        "BEGIN\n"
        "  NULL;\n"
        "END;\n"
        "$fn$;\n"
        "COMMENT ON FUNCTION cordis.p06_unrelated() IS $cmt${ \"cordis_plugin\": $cmt$;",
    )
    second = {
        "cordis_plugin": {
            "identity": "host.worktree.read_file",
            "version": "0.1.0",
            "locus": "host",
            "invocation": "host_tool",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    try:
        psql(server, db, _register_sql(second))
        raise AssertionError("expected register to fail")
    except RuntimeError as exc:
        assert "malformed JSON" in str(exc)
    assert _catalog_row(server, db, "host.worktree.apply_edits") == before
    assert (
        psql(
            server,
            db,
            "SELECT count(*) FROM cordis.host_plugin_definitions "
            "WHERE identity = 'host.worktree.read_file';",
        )
        == "0"
    )


def test_refresh_rejects_non_function_cordis_plugin(pgdata: Path) -> None:
    db = "cordis_p06_proc"
    _reset(pgdata, db)
    server = get_server(pgdata)
    plugin = {
        "cordis_plugin": {
            "identity": "p06.bad.proc",
            "version": "0.1.0",
            "locus": "in-db",
            "invocation": "queue",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    psql(
        server,
        db,
        "CREATE PROCEDURE cordis.p06_bad_proc()\n"
        "LANGUAGE plpgsql AS $fn$\n"
        "BEGIN\n"
        "  NULL;\n"
        "END;\n"
        "$fn$;\n"
        "COMMENT ON PROCEDURE cordis.p06_bad_proc() IS $cmt$"
        + json.dumps(plugin, separators=(",", ":"))
        + "$cmt$;",
    )
    try:
        psql(server, db, "SELECT cordis.refresh_plugins();")
        raise AssertionError("expected refresh to fail")
    except RuntimeError as exc:
        assert "not an ordinary function" in str(exc)


def test_unregister_host_plugin(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(server, P06_DB, _register_sql(PROOF))
    assert psql(
        server, P06_DB, "SELECT cordis.unregister_host_plugin('host.worktree.apply_edits');"
    ) == "t"
    assert (
        psql(
            server,
            P06_DB,
            "SELECT count(*) FROM cordis.plugin_catalog "
            "WHERE identity = 'host.worktree.apply_edits';",
        )
        == "0"
    )
    assert psql(
        server, P06_DB, "SELECT cordis.unregister_host_plugin('host.worktree.apply_edits');"
    ) == "f"


def test_duplicate_identity_comment_vs_host(
    pgdata: Path, tmp_path: Path
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    dup = {
        "cordis_plugin": {
            "identity": "p06.dup",
            "version": "0.1.0",
            "locus": "host",
            "invocation": "host_tool",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    psql(server, P06_DB, _register_sql(dup))
    tree = tmp_path / "sql_dup"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    comment = {
        "cordis_plugin": {
            "identity": "p06.dup",
            "version": "0.1.0",
            "locus": "in-db",
            "invocation": "queue",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    (tree / f"{prefix}_p06_dup.sql").write_text(
        "CREATE OR REPLACE FUNCTION cordis.p06_dup()\n"
        "RETURNS void LANGUAGE plpgsql AS $fn$\n"
        "BEGIN\n"
        "  NULL;\n"
        "END;\n"
        "$fn$;\n"
        "COMMENT ON FUNCTION cordis.p06_dup() IS $cmt$"
        + json.dumps(comment, separators=(",", ":"))
        + "$cmt$;\n"
        "SELECT cordis.refresh_plugins();\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P06_DB,
        "--sql-root",
        str(tree),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "duplicate identity" in result.stdout + result.stderr
    assert (
        psql(
            server,
            P06_DB,
            "SELECT count(*) FROM cordis.host_plugin_definitions "
            "WHERE identity = 'p06.dup';",
        )
        == "1"
    )


def test_refresh_invalid_comment_metadata_includes_signature(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = tmp_path / "sql_invalid_meta"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    plugin = {
        "cordis_plugin": {
            "identity": "p06.bad.meta",
            "version": "0.1.0",
            "locus": "host",
            "invocation": "host_tool",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    (tree / f"{prefix}_p06_bad_meta.sql").write_text(
        "CREATE OR REPLACE FUNCTION cordis.p06_bad_meta()\n"
        "RETURNS void LANGUAGE plpgsql AS $fn$\n"
        "BEGIN\n"
        "  NULL;\n"
        "END;\n"
        "$fn$;\n"
        "COMMENT ON FUNCTION cordis.p06_bad_meta() IS $cmt$"
        + json.dumps(plugin, separators=(",", ":"))
        + "$cmt$;\n"
        "SELECT cordis.refresh_plugins();\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        "cordis_p06_bad_meta",
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "p06_bad_meta" in combined
    assert "invalid metadata" in combined


def test_register_host_plugin_preserves_registered_at(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(server, P06_DB, _register_sql(PROOF))
    first = psql(
        server,
        P06_DB,
        "SELECT registered_at::text || '|' || updated_at::text "
        "FROM cordis.host_plugin_definitions "
        "WHERE identity = 'host.worktree.apply_edits';",
    )
    first_reg, first_upd = first.split("|", 1)
    updated = {
        "cordis_plugin": {
            **PROOF["cordis_plugin"],
            "version": "0.1.1",
            "description": "Updated description for apply_edits.",
        }
    }
    psql(server, P06_DB, "SELECT pg_sleep(0.05);")
    psql(server, P06_DB, _register_sql(updated))
    second = psql(
        server,
        P06_DB,
        "SELECT registered_at::text || '|' || updated_at::text || '|' || version "
        "FROM cordis.host_plugin_definitions d "
        "JOIN cordis.plugin_catalog c USING (identity) "
        "WHERE identity = 'host.worktree.apply_edits';",
    )
    second_reg, rest = second.split("|", 1)
    second_upd, version = rest.rsplit("|", 1)
    assert second_reg == first_reg
    assert second_upd != first_upd
    assert version == "0.1.1"


def test_plugin_catalog_has_planned_checks_and_indexes(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    checks = psql(
        server,
        P06_DB,
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'cordis.plugin_catalog'::regclass "
        "AND contype = 'c' ORDER BY 1;",
    ).splitlines()
    for name in (
        "plugin_catalog_classification_check",
        "plugin_catalog_effect_class_check",
        "plugin_catalog_identity_check",
        "plugin_catalog_invocation_check",
        "plugin_catalog_locus_check",
        "plugin_catalog_locus_invocation_check",
        "plugin_catalog_reconciliation_check",
        "plugin_catalog_required_grants_check",
        "plugin_catalog_retry_class_check",
        "plugin_catalog_source_entrypoint_check",
        "plugin_catalog_source_kind_check",
        "plugin_catalog_version_check",
    ):
        assert name in checks
    indexes = psql(
        server,
        P06_DB,
        "SELECT indexrelid::regclass::text FROM pg_index "
        "WHERE indrelid = 'cordis.plugin_catalog'::regclass "
        "ORDER BY 1;",
    )
    assert "plugin_catalog_locus_invocation_idx" in indexes
    assert "plugin_catalog_required_grants_idx" in indexes
