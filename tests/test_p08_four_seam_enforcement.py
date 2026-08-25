"""P08 four-seam enforcement tests. Apply stays a subprocess."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from pgembed import get_server

from tests.conftest import SQL, load_apply_module, next_sql_prefix, psql, run_apply

P08_DB = "cordis_p08"
TREE_FILES = (
    "0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,"
    "0003_p03_wait_event.sql,0004_p04_sleep_retry.sql,"
    "0005_p05_one_step_driver.sql,"
    "0006_p06_plugin_catalog.sql,0007_p07_grant_registry.sql,"
    "0019_p19_paradigm_policies.sql,0020_p08_four_seam_enforcement.sql,"
    "0021_p09_in_db_worker.sql"
)
HOST_LOOKUP = {
    "cordis_plugin": {
        "identity": "host.p08.lookup",
        "version": "0.1.0",
        "name": "lookup",
        "description": "P08 leak-fixture host tool",
        "locus": "host",
        "invocation": "host_tool",
        "required_grants": ["named_corpus"],
        "effect_class": "read_only",
        "retry_class": "replayable",
        "reconciliation": "none",
    }
}
NO_GRANT_PLUGIN = {
    "cordis_plugin": {
        "identity": "host.p08.none",
        "version": "0.1.0",
        "locus": "host",
        "invocation": "host_tool",
        "required_grants": [],
        "effect_class": "read_only",
        "retry_class": "replayable",
        "reconciliation": "none",
    }
}


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _jsonb(value: object) -> str:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, separators=(",", ":"))
    return _sql_str(raw) + "::jsonb"


def _reset(pgdata: Path, database: str = P08_DB) -> None:
    result = run_apply(
        "--pgdata", str(pgdata), "--database", database, "--reset"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _psql_verbose(server, database: str, sql: str) -> str:
    return psql(server, database, sql, "-v", "VERBOSITY=verbose")


def _expect_error(
    server,
    sql: str,
    fragment: str,
    sqlstate: str | None = None,
    database: str = P08_DB,
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


def _register(server, corpus_id: str, label: str) -> None:
    psql(
        server,
        P08_DB,
        "SELECT cordis.register_named_corpus("
        f"{_sql_str(corpus_id)}, {_sql_str(label)}, 'host');",
    )


def _slice(server, run_id: str, name: str) -> str:
    return psql(
        server,
        P08_DB,
        "SELECT cordis.create_slice("
        f"{_sql_str(run_id)}, {_sql_str(name)}, 'host');",
    )


def _issue(
    server, run_id: str, slice_id: str, kind: str, target: str
) -> None:
    psql(
        server,
        P08_DB,
        "SELECT cordis.issue_grant("
        f"{_sql_str(run_id)}, {_sql_str(slice_id)}::uuid, "
        f"{_sql_str(kind)}, {_sql_str(target)}, 'host');",
    )


def _job_and_claim(server, run_id: str) -> str:
    payload = {
        "model": "mock",
        "max_steps": 1,
        "mock_llm": {"responses": {"s-1": {"action": "final", "answer": "ok"}}},
    }
    psql(
        server,
        P08_DB,
        "INSERT INTO cordis.jobs (run_id, job_type, payload) VALUES ("
        f"{_sql_str(run_id)}, 'p08', {_jsonb(payload)});",
    )
    token = psql(
        server,
        P08_DB,
        "SELECT claim_token::text FROM cordis.claim_job("
        f"{_sql_str(run_id)}, 'p08-worker', 90);",
    )
    assert token
    return token


def _scoped(
    server,
    token: str,
    run_id: str,
    slice_id: str,
    secret: str,
    corpus: str,
    step: str,
) -> None:
    ok = psql(
        server,
        P08_DB,
        "SELECT cordis.emit_step_scoped("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, "
        f"{_sql_str(slice_id)}::uuid, 'tool', "
        f"{_jsonb({'secret': secret})}, {_sql_str(step)}, "
        f"ARRAY[{_sql_str(corpus)}]::text[], 90);",
    )
    assert ok == "t"


def _setup_two_slice(server, run_id: str = "run-d5") -> tuple[str, str, str]:
    _register(server, "project-1", "Project 1")
    _register(server, "project-2", "Project 2")
    s1 = _slice(server, run_id, "fn-1")
    s2 = _slice(server, run_id, "fn-2-3")
    _issue(server, run_id, s1, "named_corpus", "project-1")
    _issue(server, run_id, s2, "named_corpus", "project-2")
    _issue(server, run_id, s1, "run", "")
    _issue(server, run_id, s2, "run", "")
    token = _job_and_claim(server, run_id)
    _scoped(server, token, run_id, s1, "project-1-secret", "project-1", "s-1")
    _scoped(server, token, run_id, s2, "project-2-secret", "project-2", "s-2")
    psql(
        server,
        P08_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(HOST_LOOKUP) + ");",
    )
    return s1, s2, token


def test_p08_fresh_apply_catalog_version_and_ready(pgdata: Path) -> None:
    result = run_apply(
        "--pgdata", str(pgdata), "--database", P08_DB, "--reset"
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert f"files={TREE_FILES}" in result.stdout
    server = get_server(pgdata)
    assert psql(server, P08_DB, "SELECT cordis.get_schema_version();") == "p21"
    assert (
        psql(
            server,
            P08_DB,
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relkind = 'r' AND c.relname IN "
            "('isolation_seams','isolation_fold_handlers');",
        )
        == "2"
    )
    assert (
        psql(
            server,
            P08_DB,
            "SELECT enabled FROM cordis.isolation_feature_status();",
        )
        == "t"
    )
    vol = psql(
        server,
        P08_DB,
        "SELECT p.proname || ':' || p.provolatile::text || ':' "
        "|| p.prosecdef::text || ':' || l.lanname "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_language l ON l.oid = p.prolang "
        "WHERE n.nspname = 'cordis' AND p.proname IN ("
        "'_fold_scoped_history','_require_isolation_feature',"
        "'authorize_tool_dispatch','emit_step_scoped',"
        "'fold_slice_messages','isolation_feature_status',"
        "'read_run_env','recall_named_corpus','get_schema_version',"
        "'fold_codeact_messages','fold_rlm_messages') "
        "ORDER BY 1;",
    ).splitlines()
    wanted = {
        "_fold_scoped_history:s:false:plpgsql",
        "_require_isolation_feature:s:false:plpgsql",
        "authorize_tool_dispatch:s:false:plpgsql",
        "emit_step_scoped:v:false:plpgsql",
        "fold_codeact_messages:s:false:sql",
        "fold_rlm_messages:s:false:sql",
        "fold_slice_messages:v:false:plpgsql",
        "get_schema_version:i:false:sql",
        "isolation_feature_status:s:false:plpgsql",
        "read_run_env:s:false:plpgsql",
        "recall_named_corpus:s:false:plpgsql",
    }
    assert set(vol) == wanted
    overloads = psql(
        server,
        P08_DB,
        "SELECT count(*) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN ("
        "'recall_named_corpus','fold_slice_messages','read_run_env',"
        "'authorize_tool_dispatch','emit_step_scoped') "
        "GROUP BY p.proname HAVING count(*) > 1;",
    )
    assert overloads == ""
    cfg = psql(
        server,
        P08_DB,
        "SELECT p.proname || '=' || array_to_string(p.proconfig, ',') "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN ("
        "'recall_named_corpus','fold_slice_messages','read_run_env',"
        "'authorize_tool_dispatch','emit_step_scoped',"
        "'isolation_feature_status') "
        "ORDER BY 1;",
    )
    assert "search_path=pg_catalog" in cfg
    assert (
        psql(
            server,
            P08_DB,
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_cordis';",
        )
        == "0"
    )


def test_p08_two_named_corpora_four_seam_leak_fixture(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-d5"
    s1, s2, _token = _setup_two_slice(server, run_id)

    r1 = psql(
        server,
        P08_DB,
        "SELECT corpus_id FROM cordis.recall_named_corpus("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'project-1');",
    )
    assert r1 == "project-1"
    assert (
        psql(
            server,
            P08_DB,
            "SELECT count(*) FROM cordis.recall_named_corpus("
            f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'project-2');",
        )
        == "0"
    )
    fold1 = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.fold_slice_messages("
            f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'codeact');",
        )
    )
    hist1 = json.dumps(fold1.get("history"))
    assert "project-1-secret" in hist1
    assert "project-2-secret" not in hist1
    assert fold1["named_corpora"] == ["project-1"]
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'rlm', 'question');",
        "P08_ENV_WORKSPACE_UNAVAILABLE",
        "55000",
    )
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'codeact', 'question');",
        "P08_ENV_DISABLED",
        "42501",
    )
    desc = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.authorize_tool_dispatch("
            f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'host.p08.lookup', "
            '\'{"named_corpus":"project-1"}\'::jsonb);',
        )
    )
    assert desc["identity"] == "host.p08.lookup"
    assert "inject" in desc
    _expect_error(
        server,
        "SELECT cordis.authorize_tool_dispatch("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'host.p08.lookup', "
        '\'{"named_corpus":"project-2"}\'::jsonb);',
        "P08_TOOL_GRANT_REQUIRED",
        "42501",
    )

    assert (
        psql(
            server,
            P08_DB,
            "SELECT corpus_id FROM cordis.recall_named_corpus("
            f"{_sql_str(run_id)}, {_sql_str(s2)}::uuid, 'project-2');",
        )
        == "project-2"
    )
    assert (
        psql(
            server,
            P08_DB,
            "SELECT count(*) FROM cordis.recall_named_corpus("
            f"{_sql_str(run_id)}, {_sql_str(s2)}::uuid, 'project-1');",
        )
        == "0"
    )
    fold2 = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.fold_slice_messages("
            f"{_sql_str(run_id)}, {_sql_str(s2)}::uuid, 'codeact');",
        )
    )
    hist2 = json.dumps(fold2.get("history"))
    assert "project-2-secret" in hist2
    assert "project-1-secret" not in hist2
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"{_sql_str(run_id)}, {_sql_str(s2)}::uuid, 'rlm', 'question');",
        "P08_ENV_WORKSPACE_UNAVAILABLE",
        "55000",
    )
    desc2 = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.authorize_tool_dispatch("
            f"{_sql_str(run_id)}, {_sql_str(s2)}::uuid, 'host.p08.lookup', "
            '\'{"named_corpus":"project-2"}\'::jsonb);',
        )
    )
    assert desc2["identity"] == "host.p08.lookup"
    inventory = psql(
        server,
        P08_DB,
        "SELECT count(*) FROM cordis.grants g "
        "JOIN cordis.slices s ON s.slice_id = g.slice_id "
        f"WHERE s.run_id = {_sql_str(run_id)} AND g.kind = 'named_corpus';",
    )
    assert inventory == "2"


def test_p08_legacy_step_once_still_unfiltered(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-legacy"
    _register(server, "project-1", "Project 1")
    _register(server, "project-2", "Project 2")
    s1 = _slice(server, run_id, "fn-1")
    s2 = _slice(server, run_id, "fn-2-3")
    _issue(server, run_id, s1, "named_corpus", "project-1")
    _issue(server, run_id, s2, "named_corpus", "project-2")
    _issue(server, run_id, s1, "run", "")
    _issue(server, run_id, s2, "run", "")
    token = _job_and_claim(server, run_id)
    for slice_id, secret, corpus in (
        (s1, "project-1-secret", "project-1"),
        (s2, "project-2-secret", "project-2"),
    ):
        ok = psql(
            server,
            P08_DB,
            "SELECT cordis.emit_step_scoped("
            f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, "
            f"{_sql_str(slice_id)}::uuid, 'run/yield', "
            f"{_jsonb({'secret': secret})}, NULL, "
            f"ARRAY[{_sql_str(corpus)}]::text[], 90);",
        )
        assert ok == "t"
    psql(
        server,
        P08_DB,
        "SELECT cordis.emit_step_claimed("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, 'run/yield', "
        f"{_jsonb({'secret': 'unscoped-secret'})}, NULL, 90);",
    )
    psql(
        server,
        P08_DB,
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text)\n"
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $h$\n"
        "BEGIN\n"
        "  UPDATE cordis.jobs\n"
        "     SET payload = payload || pg_catalog.jsonb_build_object(\n"
        "           '_p08_captured', p_request)\n"
        "   WHERE run_id = p_run_id;\n"
        "  RETURN pg_catalog.jsonb_build_object("
        "'action','final','answer','ok');\n"
        "END;$h$;",
    )
    outcome = psql(
        server,
        P08_DB,
        "SELECT cordis.step_once("
        f"{_sql_str(run_id)}, {_sql_str(token)}::uuid, 90);",
    )
    if outcome != "complete":
        err = psql(
            server,
            P08_DB,
            "SELECT payload::text FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'error' "
            "ORDER BY seq DESC LIMIT 1;",
        )
        raise AssertionError(f"step_once={outcome!r} error={err!r}")
    req = psql(
        server,
        P08_DB,
        "SELECT payload->>'_p08_captured' FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert "project-1-secret" in req
    assert "project-2-secret" in req
    fold = json.dumps(
        json.loads(
            psql(
                server,
                P08_DB,
                "SELECT cordis.fold_slice_messages("
                f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'codeact');",
            )
        )
    )
    assert "project-1-secret" in fold
    assert "project-2-secret" not in fold
    assert "unscoped-secret" not in fold
    _ = s2


def test_p08_fold_ignores_unscoped_malformed_and_cross_slice_rows(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-filter"
    s1, s2, token = _setup_two_slice(server, run_id)
    psql(
        server,
        P08_DB,
        "SELECT cordis.emit_step_claimed("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, 'tool', "
        f"{_jsonb({'p08_scope': 'bad', 'secret': 'malformed'})}, 's-4', 90);",
    )
    fold = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.fold_slice_messages("
            f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'codeact');",
        )
    )
    dumped = json.dumps(fold)
    assert "project-1-secret" in dumped
    assert "project-2-secret" not in dumped
    assert "malformed" not in dumped
    seqs = [item["seq"] for item in fold["history"]]
    assert seqs == sorted(seqs)
    _ = s2


def test_p08_live_issue_and_revoke_affect_next_call_without_freeze(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-live"
    s1, s2, token = _setup_two_slice(server, run_id)
    gid = psql(
        server,
        P08_DB,
        "SELECT grant_id::text FROM cordis.grants g "
        "JOIN cordis.slices s ON s.slice_id = g.slice_id "
        f"WHERE s.slice_id = {_sql_str(s1)}::uuid "
        "AND g.kind = 'named_corpus' AND g.target = 'project-1';",
    )
    psql(server, P08_DB, f"SELECT cordis.revoke_grant({_sql_str(gid)}::uuid, 'host');")
    fold = json.dumps(
        json.loads(
            psql(
                server,
                P08_DB,
                "SELECT cordis.fold_slice_messages("
                f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'codeact');",
            )
        )
    )
    assert "project-1-secret" not in fold
    assert (
        psql(
            server,
            P08_DB,
            "SELECT count(*) FROM cordis.recall_named_corpus("
            f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'project-1');",
        )
        == "0"
    )
    psql(
        server,
        P08_DB,
        "SELECT cordis.issue_grant("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, "
        "'named_corpus', 'project-1', 'host');",
    )
    fold2 = json.dumps(
        json.loads(
            psql(
                server,
                P08_DB,
                "SELECT cordis.fold_slice_messages("
                f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'codeact');",
            )
        )
    )
    assert "project-1-secret" in fold2
    assert (
        psql(
            server,
            P08_DB,
            "SELECT count(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname LIKE '%snapshot%';",
        )
        == "0"
    )
    _ = (s2, token)


def test_p08_recall_failure_contract(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    s1, _s2, _token = _setup_two_slice(server)
    assert (
        psql(
            server,
            P08_DB,
            "SELECT count(*) FROM cordis.recall_named_corpus("
            f"'run-d5', {_sql_str(s1)}::uuid, 'project-2');",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P08_DB,
            "SELECT count(*) FROM cordis.recall_named_corpus("
            f"'run-d5', {_sql_str(s1)}::uuid, 'no-such-corpus');",
        )
        == "0"
    )
    _expect_error(
        server,
        f"SELECT * FROM cordis.recall_named_corpus('run-d5', {_sql_str(s1)}::uuid, 'BAD');",
        "22023",
    )
    _expect_error(
        server,
        "SELECT * FROM cordis.recall_named_corpus('run-d5', "
        "'00000000-0000-0000-0000-000000000001'::uuid, 'project-1');",
        "22023",
    )


def test_p08_fold_failure_contract(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-fold-fail"
    s1, _s2, _token = _setup_two_slice(server, run_id)
    s3 = _slice(server, run_id, "no-run")
    _expect_error(
        server,
        "SELECT cordis.fold_slice_messages("
        f"{_sql_str(run_id)}, {_sql_str(s3)}::uuid, 'codeact');",
        "P08_FOLD_RUN_GRANT_REQUIRED",
        "42501",
    )
    s_empty_run = _slice(server, "run-empty", "only")
    _issue(server, "run-empty", s_empty_run, "run", "")
    empty_ok = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.fold_slice_messages("
            f"'run-empty', {_sql_str(s_empty_run)}::uuid, 'codeact');",
        )
    )
    assert empty_ok["history"] == []
    assert empty_ok["as_of_seq"] == 0
    _expect_error(
        server,
        "SELECT cordis.fold_slice_messages('run-d5', "
        "'00000000-0000-0000-0000-000000000001'::uuid, 'codeact');",
        "22023",
    )
    psql(
        server,
        P08_DB,
        "CREATE OR REPLACE FUNCTION cordis.p08_uncert_fold(p_run_id text)\n"
        "RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $u$\n"
        "  SELECT pg_catalog.jsonb_build_object('uncert', true, "
        "'run_id', p_run_id);\n"
        "$u$;",
    )
    psql(
        server,
        P08_DB,
        "SELECT cordis.register_paradigm_policy("
        + _jsonb(
            {
                "cordis_paradigm": {
                    "identity": "probe.customfold",
                    "version": "0.1.0",
                    "description": "x",
                    "action_surface": "structured_tools",
                    "parser_kind": "json_tool_calls",
                    "spawn_mode": "always_enqueue",
                    "env_enabled": False,
                    "env_workspace": "none",
                    "env_inherit": "none",
                    "observation_clip_chars": None,
                    "observation_full_in_env": False,
                    "system_prompt": "x",
                    "fold_fn": "cordis.p08_uncert_fold",
                    "parse_fn": "cordis.parse_codeact_decision",
                    "observe_fn": "cordis.observe_codeact",
                }
            }
        )
        + ");",
    )
    _expect_error(
        server,
        "SELECT cordis.fold_slice_messages("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'probe.customfold');",
        "P08_FOLD_POLICY_NOT_CERTIFIED",
        "42501",
    )


def test_p08_env_read_failure_contract(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-env"
    s1, _s2, _token = _setup_two_slice(server, run_id)
    s3 = _slice(server, run_id, "no-run")
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'rlm', '');",
        "invalid env key",
        "22023",
    )
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'codeact', 'question');",
        "P08_ENV_DISABLED",
        "42501",
    )
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"{_sql_str(run_id)}, {_sql_str(s3)}::uuid, 'rlm', 'question');",
        "P08_ENV_RUN_GRANT_REQUIRED",
        "42501",
    )
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'rlm', 'question');",
        "P08_ENV_WORKSPACE_UNAVAILABLE",
        "55000",
    )


def test_p08_tool_dispatch_failure_contract(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    s1, _s2, _token = _setup_two_slice(server)
    psql(
        server,
        P08_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(NO_GRANT_PLUGIN) + ");",
    )
    _expect_error(
        server,
        f"SELECT cordis.authorize_tool_dispatch('run-d5', {_sql_str(s1)}::uuid, "
        "'Bad.Name', '{}'::jsonb);",
        "invalid plugin identity",
        "22023",
    )
    _expect_error(
        server,
        f"SELECT cordis.authorize_tool_dispatch('run-d5', {_sql_str(s1)}::uuid, "
        "'host.missing', '{}'::jsonb);",
        "unknown plugin",
        "22023",
    )
    _expect_error(
        server,
        f"SELECT cordis.authorize_tool_dispatch('run-d5', {_sql_str(s1)}::uuid, "
        "'host.p08.lookup', '[]'::jsonb);",
        "invalid requested grants",
        "22023",
    )
    none = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.authorize_tool_dispatch("
            f"'run-d5', {_sql_str(s1)}::uuid, 'host.p08.none', '{{}}'::jsonb);",
        )
    )
    assert none["identity"] == "host.p08.none"


def test_p08_tool_dispatch_checks_exact_target_not_only_kind(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    s1, _s2, _token = _setup_two_slice(server)
    _expect_error(
        server,
        "SELECT cordis.authorize_tool_dispatch("
        f"'run-d5', {_sql_str(s1)}::uuid, 'host.p08.lookup', "
        '\'{"named_corpus":"project-2"}\'::jsonb);',
        "P08_TOOL_GRANT_REQUIRED",
        "42501",
    )
    ok = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.authorize_tool_dispatch("
            f"'run-d5', {_sql_str(s1)}::uuid, 'host.p08.lookup', "
            '\'{"named_corpus":"project-1"}\'::jsonb);',
        )
    )
    assert ok["identity"] == "host.p08.lookup"


def test_p08_control_plane_functions_are_not_model_tools(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    s1, _s2, _token = _setup_two_slice(server)
    for ident in (
        "issue_grant",
        "emit_step",
        "checkpoint",
        "cordis.emit_step_claimed",
    ):
        _expect_error(
            server,
            "SELECT cordis.authorize_tool_dispatch("
            f"'run-d5', {_sql_str(s1)}::uuid, {_sql_str(ident)}, '{{}}'::jsonb);",
            "unknown plugin",
            "22023",
        )
    blocked = {
        "cordis_plugin": {
            "identity": "cordis.emit_step",
            "version": "0.1.0",
            "locus": "host",
            "invocation": "host_tool",
            "required_grants": [],
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    psql(
        server,
        P08_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(blocked) + ");",
    )
    _expect_error(
        server,
        "SELECT cordis.authorize_tool_dispatch("
        f"'run-d5', {_sql_str(s1)}::uuid, 'cordis.emit_step', '{{}}'::jsonb);",
        "P08_CONTROL_PLANE_TOOL_DENIED",
        "42501",
    )


def test_p08_p19_blank_context_still_stubs(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    body = json.loads(
        psql(server, P08_DB, "SELECT cordis.fold_codeact_messages('run-1');")
    )
    assert body["p19_stub"] is True
    assert body["slot"] == "fold"
    assert body["run_id"] == "run-1"


@pytest.mark.parametrize(
    "seam",
    ["recall", "fold", "env_read", "tool_dispatch"],
)
def test_p08_feature_closed_when_any_seam_is_missing(
    pgdata: Path, tmp_path: Path, seam: str
) -> None:
    tree = tmp_path / f"sql_drop_{seam}"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_drop_seam.sql").write_text(
        f"DELETE FROM cordis.isolation_seams WHERE seam = '{seam}';\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P08_DB,
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    server = get_server(pgdata)
    assert psql(server, P08_DB, "SELECT cordis.get_schema_version();") == "p21"
    status = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT jsonb_build_object('enabled', enabled, "
            "'missing', missing_seams) FROM cordis.isolation_feature_status();",
        )
    )
    assert status["enabled"] is False
    assert seam in status["missing"]
    _register(server, "project-1", "P1")
    s1 = _slice(server, "run-d5", "fn-1")
    _issue(server, "run-d5", s1, "run", "")
    _expect_error(
        server,
        "SELECT * FROM cordis.recall_named_corpus("
        f"'run-d5', {_sql_str(s1)}::uuid, 'project-1');",
        "P08_ISOLATION_FEATURE_CLOSED",
        "42501",
    )
    _expect_error(
        server,
        "SELECT cordis.fold_slice_messages("
        f"'run-d5', {_sql_str(s1)}::uuid, 'codeact');",
        "P08_ISOLATION_FEATURE_CLOSED",
        "42501",
    )
    _expect_error(
        server,
        "SELECT cordis.read_run_env("
        f"'run-d5', {_sql_str(s1)}::uuid, 'rlm', 'question');",
        "P08_ISOLATION_FEATURE_CLOSED",
        "42501",
    )
    _expect_error(
        server,
        "SELECT cordis.authorize_tool_dispatch("
        f"'run-d5', {_sql_str(s1)}::uuid, 'host.p08.lookup', '{{}}'::jsonb);",
        "P08_ISOLATION_FEATURE_CLOSED",
        "42501",
    )
    _expect_error(
        server,
        "SELECT cordis.emit_step_scoped("
        "'00000000-0000-0000-0000-000000000001'::uuid, 'run-d5', "
        f"{_sql_str(s1)}::uuid, 'tool', '{{}}'::jsonb, 's-1', "
        "ARRAY[]::text[], 90);",
        "P08_ISOLATION_FEATURE_CLOSED",
        "42501",
    )


def test_p08_does_not_replace_legacy_driver_or_event_verbs() -> None:
    body = (SQL / "0020_p08_four_seam_enforcement.sql").read_text()
    assert "CREATE OR REPLACE FUNCTION cordis.step_once" not in body
    assert "CREATE OR REPLACE FUNCTION cordis.await_event" not in body
    assert "CREATE OR REPLACE FUNCTION cordis.emit_event" not in body


def test_p08_has_no_snapshot_env_table_or_run_union_helper(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    names = psql(
        server,
        P08_DB,
        "SELECT n.nspname || '.' || p.proname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN "
        "('run_live_grants','run_grants') ORDER BY 1;",
    )
    assert names == ""
    tables = psql(
        server,
        P08_DB,
        "SELECT relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relkind = 'r' "
        "AND relname IN ('rlm_vars','corpus_snapshots') ORDER BY 1;",
    )
    assert tables == ""


def test_p08_source_tree_append_monopoly_holds() -> None:
    insert_re = re.compile(r"INSERT\s+INTO\s+cordis\.agent_steps", re.I)
    inserts = []
    for path in sorted(SQL.glob("*.sql")):
        scanned = path.read_text()
        for match in insert_re.finditer(scanned):
            inserts.append(path.name)
    assert inserts == ["0002_p02_log.sql"]


def test_p08_replay_preserves_existing_workspace_and_log(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    s1, _s2, _token = _setup_two_slice(server)
    before_grant = psql(
        server,
        P08_DB,
        "SELECT status || '|' || created_at::text FROM cordis.grants "
        "ORDER BY created_at, grant_id;",
    )
    before_latch = psql(
        server,
        P08_DB,
        "SELECT seam || '|' || installed_at::text FROM cordis.isolation_seams "
        "ORDER BY seam;",
    )
    before_handlers = psql(
        server,
        P08_DB,
        "SELECT fold_fn::text || '|' || installed_at::text "
        "FROM cordis.isolation_fold_handlers ORDER BY 1;",
    )
    before_log = psql(
        server,
        P08_DB,
        "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'run-d5';",
    )
    replay = run_apply("--pgdata", str(pgdata), "--database", P08_DB)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert "mode=in-place" in replay.stdout
    assert psql(server, P08_DB, "SELECT cordis.get_schema_version();") == "p21"
    after_grant = psql(
        server,
        P08_DB,
        "SELECT status || '|' || created_at::text FROM cordis.grants "
        "ORDER BY created_at, grant_id;",
    )
    after_latch = psql(
        server,
        P08_DB,
        "SELECT seam || '|' || installed_at::text FROM cordis.isolation_seams "
        "ORDER BY seam;",
    )
    after_handlers = psql(
        server,
        P08_DB,
        "SELECT fold_fn::text || '|' || installed_at::text "
        "FROM cordis.isolation_fold_handlers ORDER BY 1;",
    )
    after_log = psql(
        server,
        P08_DB,
        "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'run-d5';",
    )
    assert after_grant == before_grant
    assert after_latch == before_latch
    assert after_handlers == before_handlers
    assert after_log == before_log
    assert (
        psql(
            server,
            P08_DB,
            "SELECT enabled FROM cordis.isolation_feature_status();",
        )
        == "t"
    )
    _ = s1


def test_p08_sql_tree_forbidden_words_and_dollar_tag() -> None:
    apply_mod = load_apply_module()
    path = SQL / "0020_p08_four_seam_enforcement.sql"
    body = path.read_text()
    assert "$p08$" in body
    scanned = apply_mod.sanitize_sql_for_preflight(body)
    assert apply_mod.FORBIDDEN_STMTS[4].search(scanned) is None


def test_p08_lost_claim_scoped_append_writes_nothing(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    s1, _s2, _token = _setup_two_slice(server)
    before = psql(
        server,
        P08_DB,
        "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'run-d5';",
    )
    lost = psql(
        server,
        P08_DB,
        "SELECT cordis.emit_step_scoped("
        "'00000000-0000-0000-0000-000000000099'::uuid, 'run-d5', "
        f"{_sql_str(s1)}::uuid, 'run/yield', '{{}}'::jsonb, NULL, "
        "ARRAY[]::text[], 90);",
    )
    assert lost == "f"
    after = psql(
        server,
        P08_DB,
        "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'run-d5';",
    )
    assert after == before


def test_p08_missing_fold_handler_closes_feature(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(
        server,
        P08_DB,
        "DELETE FROM cordis.isolation_fold_handlers "
        "WHERE fold_fn = 'cordis.fold_codeact_messages(text)'::regprocedure;",
    )
    assert (
        psql(
            server,
            P08_DB,
            "SELECT enabled FROM cordis.isolation_feature_status();",
        )
        == "f"
    )
    s1 = _slice(server, "run-d5", "fn-1")
    _issue(server, "run-d5", s1, "run", "")
    _expect_error(
        server,
        "SELECT cordis.fold_slice_messages("
        f"'run-d5', {_sql_str(s1)}::uuid, 'codeact');",
        "P08_ISOLATION_FEATURE_CLOSED",
        "42501",
    )


def test_p08_replay_repairs_swapped_gate_fns(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    before = psql(
        server,
        P08_DB,
        "SELECT seam || '|' || gate_fn::text || '|' || installed_at::text "
        "FROM cordis.isolation_seams ORDER BY seam;",
    )
    psql(
        server,
        P08_DB,
        "CREATE OR REPLACE FUNCTION cordis.p08_tmp_gate("
        "p_run_id text, p_slice_id uuid, p_corpus_id text)\n"
        "RETURNS TABLE(grant_id uuid, corpus_id text, label text)\n"
        "LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO pg_catalog "
        "AS $t$ SELECT NULL::uuid, NULL::text, NULL::text WHERE false; $t$;\n"
        "UPDATE cordis.isolation_seams "
        "SET gate_fn = 'cordis.p08_tmp_gate(text,uuid,text)'::regprocedure "
        "WHERE seam = 'recall';\n"
        "UPDATE cordis.isolation_seams "
        "SET gate_fn = 'cordis.recall_named_corpus(text,uuid,text)'::regprocedure "
        "WHERE seam = 'fold';\n"
        "UPDATE cordis.isolation_seams "
        "SET gate_fn = 'cordis.fold_slice_messages(text,uuid,text)'::regprocedure "
        "WHERE seam = 'recall';",
    )
    assert (
        psql(
            server,
            P08_DB,
            "SELECT enabled FROM cordis.isolation_feature_status();",
        )
        == "f"
    )
    replay = run_apply("--pgdata", str(pgdata), "--database", P08_DB)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    after = psql(
        server,
        P08_DB,
        "SELECT seam || '|' || gate_fn::text || '|' || installed_at::text "
        "FROM cordis.isolation_seams ORDER BY seam;",
    )
    assert after == before
    assert (
        psql(
            server,
            P08_DB,
            "SELECT enabled FROM cordis.isolation_feature_status();",
        )
        == "t"
    )


def test_p08_llm_checkpoint_is_not_control_plane_denied(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    s1, _s2, _token = _setup_two_slice(server)
    plugin = {
        "cordis_plugin": {
            "identity": "cordis.llm_checkpoint",
            "version": "0.1.0",
            "locus": "host",
            "invocation": "host_tool",
            "required_grants": [],
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    psql(
        server,
        P08_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(plugin) + ");",
    )
    desc = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.authorize_tool_dispatch("
            f"'run-d5', {_sql_str(s1)}::uuid, 'cordis.llm_checkpoint', "
            "'{}'::jsonb);",
        )
    )
    assert desc["identity"] == "cordis.llm_checkpoint"


def test_p08_event_scope_binding_is_opaque(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-event"
    s1, _s2, _token = _setup_two_slice(server, run_id)
    _issue(server, run_id, s1, "event", "Acme/scope:v1")
    event_plugin = {
        "cordis_plugin": {
            "identity": "host.p08.event",
            "version": "0.1.0",
            "locus": "host",
            "invocation": "host_tool",
            "required_grants": ["event"],
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
        }
    }
    psql(
        server,
        P08_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(event_plugin) + ");",
    )
    ok = json.loads(
        psql(
            server,
            P08_DB,
            "SELECT cordis.authorize_tool_dispatch("
            f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'host.p08.event', "
            '\'{"event":"Acme/scope:v1"}\'::jsonb);',
        )
    )
    assert ok["identity"] == "host.p08.event"
    _expect_error(
        server,
        "SELECT cordis.authorize_tool_dispatch("
        f"{_sql_str(run_id)}, {_sql_str(s1)}::uuid, 'host.p08.event', "
        '\'{"event":"other"}\'::jsonb);',
        "P08_TOOL_GRANT_REQUIRED",
        "42501",
    )
