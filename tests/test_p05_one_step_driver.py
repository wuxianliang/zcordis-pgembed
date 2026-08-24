"""P05 one-step driver and mock LLM hook tests."""

from __future__ import annotations

import copy
import json
import re
import shutil
import threading
import time
from pathlib import Path

import pytest
from pgembed import get_server

from tests.conftest import SQL, load_apply_module, psql, psql_session, run_apply

P05_ONLY_DB = "cordis_p05_only"
INVOKE_ID = "cordis.invoke_llm(text, text, jsonb, text)"
STEP_ID = "cordis.step_once(text, uuid, integer)"
P05_FILES = (
    "0000_kernel.sql",
    "0001_p01_claim.sql",
    "0002_p02_log.sql",
    "0003_p03_wait_event.sql",
    "0005_p05_one_step_driver.sql",
)
PROOF_PAYLOAD = {
    "input": {"question": "p05 proof"},
    "model": "mock",
    "max_steps": 3,
    "tools": [{"name": "mock.observe", "effect_class": "read_only"}],
    "mock_llm": {
        "responses": {
            "s-1": {
                "action": "tool",
                "tool_name": "mock.observe",
                "arguments": {"index": 1},
            },
            "s-2": {
                "action": "tool",
                "tool_name": "mock.observe",
                "arguments": {"index": 2},
            },
            "s-3": {"action": "final", "answer": "ok"},
        }
    },
    "mock_tools": {
        "observations": {
            "s-1": {"success": True, "value": "o1"},
            "s-2": {"success": True, "value": "o2"},
        }
    },
}


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _jsonb(value: object) -> str:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, separators=(",", ":"))
    return _sql_str(raw) + "::jsonb"


def _apply_p05_only(pgdata: Path, tmp_path: Path, *, reset: bool = True) -> Path:
    tree = tmp_path / "sql_p05_only"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir()
    for name in P05_FILES:
        shutil.copy(SQL / name, tree / name)
    args = [
        "--pgdata",
        str(pgdata),
        "--database",
        P05_ONLY_DB,
        "--sql-root",
        str(tree),
    ]
    if reset:
        args.append("--reset")
    result = run_apply(*args)
    assert result.returncode == 0, result.stdout + result.stderr
    return tree


def _insert_job(
    server, run_id: str, payload: object, job_type: str = "p05_test"
) -> None:
    psql(
        server,
        P05_ONLY_DB,
        "INSERT INTO cordis.jobs (run_id, job_type, payload) VALUES ("
        f"{_sql_str(run_id)}, {_sql_str(job_type)}, {_jsonb(payload)});",
    )


def _claim(server, run_id: str, worker: str, lease: int = 90) -> str:
    token = psql(
        server,
        P05_ONLY_DB,
        "SELECT claim_token::text FROM cordis.claim_job("
        f"{_sql_str(run_id)}, {_sql_str(worker)}, {lease});",
    )
    assert token, run_id
    return token


def _step(server, run_id: str, token: str, extend: int = 90) -> str:
    return psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.step_once("
        f"{_sql_str(run_id)}, {_sql_str(token)}::uuid, {extend});",
    )


def _map_outcome(server, outcome: str, token: str, run_id: str) -> str:
    if outcome == "yield":
        return psql(
            server,
            P05_ONLY_DB,
            f"SELECT cordis.yield_claim({_sql_str(token)}::uuid);",
        )
    if outcome == "complete":
        return psql(
            server,
            P05_ONLY_DB,
            "SELECT cordis.complete_claim("
            f"{_sql_str(token)}::uuid, "
            "(SELECT payload FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'final' "
            "ORDER BY seq DESC LIMIT 1));",
        )
    if outcome == "fail":
        return psql(
            server,
            P05_ONLY_DB,
            "SELECT cordis.fail_claim("
            f"{_sql_str(token)}::uuid, "
            "(SELECT payload FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'error' "
            "ORDER BY seq DESC LIMIT 1));",
        )
    raise AssertionError(outcome)


def _kinds_names(server, run_id: str) -> tuple[str, str]:
    kinds = psql(
        server,
        P05_ONLY_DB,
        "SELECT string_agg(kind, ',' ORDER BY seq) FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    names = psql(
        server,
        P05_ONLY_DB,
        "SELECT string_agg(coalesce(step_name, ''), ',' ORDER BY seq) "
        "FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    return kinds, names


def _error_code(server, run_id: str) -> str:
    return psql(
        server,
        P05_ONLY_DB,
        "SELECT payload->>'code' FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)} AND kind = 'error' "
        "ORDER BY seq DESC LIMIT 1;",
    )


def _fingerprint_sql(run_id: str, step_name: str, before_seq: str | None) -> str:
    bound = "TRUE" if before_seq is None else f"s.seq < {before_seq}"
    return (
        "SELECT md5(jsonb_build_object("
        "'history', coalesce(("
        "SELECT jsonb_agg(jsonb_build_object("
        "'kind', s.kind, 'payload', s.payload, 'seq', s.seq, "
        "'step_name', to_jsonb(s.step_name)) ORDER BY s.seq) "
        f"FROM cordis.agent_steps s WHERE s.run_id = {_sql_str(run_id)} "
        f"AND ({bound})), '[]'::jsonb), "
        "'input', CASE WHEN j.payload ? 'input' THEN j.payload->'input' "
        "ELSE 'null'::jsonb END, "
        "'job_type', j.job_type, "
        "'model', CASE WHEN j.payload ? 'model' THEN j.payload->>'model' "
        "ELSE 'mock' END, "
        "'parameters', CASE WHEN j.payload ? 'llm_params' "
        "THEN j.payload->'llm_params' ELSE '{}'::jsonb END, "
        "'protocol', 'cordis.p05.mock.v1', "
        "'run_id', j.run_id, "
        f"'step_name', {_sql_str(step_name)}, "
        "'tools', CASE WHEN j.payload ? 'tools' THEN j.payload->'tools' "
        "ELSE '[{\"effect_class\":\"read_only\",\"name\":\"mock.observe\"}]'::jsonb END"
        ")::text) FROM cordis.jobs j "
        f"WHERE j.run_id = {_sql_str(run_id)};"
    )


def test_p05_fresh_apply_catalog_and_version(pgdata: Path, tmp_path: Path) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P05_ONLY_DB,
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert (
        "files=0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,"
        "0003_p03_wait_event.sql,0005_p05_one_step_driver.sql"
        in result.stdout
    )
    server = get_server(pgdata)
    assert psql(server, P05_ONLY_DB, "SELECT cordis.get_schema_version();") == "p05"
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'cordis' "
            "AND c.relname IN ('plugin_catalog','paradigm_policies');",
        )
        == "0"
    )
    ids = psql(
        server,
        P05_ONLY_DB,
        "SELECT n.nspname || '.' || p.proname || '(' || "
        "pg_catalog.oidvectortypes(p.proargtypes) || ')' "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN "
        "('invoke_llm','step_once') ORDER BY 1;",
    ).splitlines()
    assert ids == sorted([INVOKE_ID, STEP_ID])


def test_p05_function_volatility_security_and_no_enum(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    rows = psql(
        server,
        P05_ONLY_DB,
        "SELECT n.nspname || '.' || p.proname || '(' || "
        "pg_catalog.oidvectortypes(p.proargtypes) || ')|' || "
        "pg_get_function_result(p.oid) || '|' || p.provolatile::text || '|' || "
        "p.prosecdef::text || '|' || coalesce(array_to_string(p.proconfig, ','), '') "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN "
        "('invoke_llm','step_once') ORDER BY 1;",
    ).splitlines()
    by_id = {line.split("|", 1)[0]: line.split("|")[1:] for line in rows}
    assert by_id[INVOKE_ID][0] == "jsonb"
    assert by_id[STEP_ID][0] == "text"
    for ident in (INVOKE_ID, STEP_ID):
        assert by_id[ident][1] == "v"
        assert by_id[ident][2] == "false"
        assert "search_path=pg_catalog" in by_id[ident][3]
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace WHERE n.nspname = 'cordis' "
            "AND p.proname IN ('invoke_llm','step_once');",
        )
        == "2"
    )
    version = psql(
        server,
        P05_ONLY_DB,
        "SELECT pg_get_function_identity_arguments(p.oid) || '|' || "
        "pg_get_function_result(p.oid) || '|' || l.lanname || '|' || "
        "p.provolatile::text || '|' || p.prosecdef::text "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_language l ON l.oid = p.prolang "
        "WHERE n.nspname = 'cordis' AND p.proname = 'get_schema_version' "
        "AND p.pronargs = 0;",
    )
    assert version == "|text|sql|i|false"
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM pg_type t JOIN pg_namespace n "
            "ON n.oid = t.typnamespace WHERE n.nspname = 'cordis' "
            "AND t.typname IN ('step_outcome','rlm_step_outcome');",
        )
        == "0"
    )
    tables = psql(
        server,
        P05_ONLY_DB,
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
        "ON n.oid = c.relnamespace WHERE n.nspname = 'cordis' "
        "AND c.relkind = 'r' ORDER BY 1;",
    ).splitlines()
    assert tables == ["agent_steps", "jobs", "run_events", "run_waits"]


def test_p05_mock_hook_validates_key_and_returns_response(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-hook"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    key = psql(
        server,
        P05_ONLY_DB,
        f"SELECT md5({_sql_str(run_id)} || '/' || 's-1');",
    )
    got = psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.invoke_llm("
        f"{_sql_str(run_id)}, 's-1', {_jsonb({'protocol': 'x'})}, "
        f"{_sql_str(key)});",
    )
    assert json.loads(got)["action"] == "tool"
    with pytest.raises(RuntimeError):
        psql(
            server,
            P05_ONLY_DB,
            "SELECT cordis.invoke_llm("
            f"{_sql_str(run_id)}, 's-1', {_jsonb({'protocol': 'x'})}, "
            f"{_sql_str('not-a-key')});",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P05_ONLY_DB,
            "SELECT cordis.invoke_llm("
            f"{_sql_str(run_id)}, 's-9', {_jsonb({'protocol': 'x'})}, "
            f"(SELECT md5({_sql_str(run_id)} || '/' || 's-9')));",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P05_ONLY_DB,
            "SELECT cordis.invoke_llm("
            f"{_sql_str(run_id)}, 's-1', '[]'::jsonb, {_sql_str(key)});",
        )


def test_p05_three_claims_three_steps(pgdata: Path, tmp_path: Path) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-three"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    tokens = []
    for i, expected in enumerate(("yield", "yield", "complete"), start=1):
        worker = f"worker-{i}"
        token = _claim(server, run_id, worker)
        tokens.append(token)
        claimed_by = psql(
            server,
            P05_ONLY_DB,
            "SELECT claimed_by FROM cordis.jobs "
            f"WHERE run_id = {_sql_str(run_id)};",
        )
        assert claimed_by == worker
        outcome = _step(server, run_id, token)
        assert outcome == expected, (i, outcome)
        mapped = _map_outcome(server, outcome, token, run_id)
        assert mapped == "t"
    assert len(set(tokens)) == 3
    kinds, names = _kinds_names(server, run_id)
    assert kinds == "llm,tool,llm,tool,llm,final"
    assert names == "s-1,s-1,s-2,s-2,s-3,s-3"
    job = psql(
        server,
        P05_ONLY_DB,
        "SELECT count(*)::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert job == "1"
    job_state = psql(
        server,
        P05_ONLY_DB,
        "SELECT status || '|' || attempt::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert job_state == "DONE|1"
    state = psql(
        server,
        P05_ONLY_DB,
        "SELECT status || '|' || steps_used::text || '|' || coalesce(answer, '') "
        f"FROM cordis.run_state({_sql_str(run_id)});",
    )
    assert state == "final|3|ok"
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'run/yield';",
        )
        == "0"
    )
    workers = psql(
        server,
        P05_ONLY_DB,
        "SELECT result->>'answer' FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert workers == "ok"


def test_p05_provider_keys_match_run_and_step(pgdata: Path, tmp_path: Path) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-keys"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    for i in range(1, 4):
        token = _claim(server, run_id, f"worker-{i}")
        outcome = _step(server, run_id, token)
        _map_outcome(server, outcome, token, run_id)
    keys = psql(
        server,
        P05_ONLY_DB,
        "SELECT step_name || '=' || (payload->>'provider_key') "
        "FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)} AND kind = 'llm' "
        "ORDER BY seq;",
    ).splitlines()
    expected = []
    for n in (1, 2, 3):
        digest = psql(
            server,
            P05_ONLY_DB,
            f"SELECT md5({_sql_str(run_id)} || '/' || 's-{n}');",
        )
        expected.append(f"s-{n}={digest}")
    assert keys == expected


def test_p05_checkpoint_skips_hook_and_resumes_tool(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-skip"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w-skip")
    fp = psql(server, P05_ONLY_DB, _fingerprint_sql(run_id, "s-1", None))
    key = psql(
        server,
        P05_ONLY_DB,
        f"SELECT md5({_sql_str(run_id)} || '/' || 's-1');",
    )
    raw = {
        "action": "tool",
        "tool_name": "mock.observe",
        "arguments": {"index": 1},
    }
    payload = {
        "protocol": "cordis.p05.mock.v1",
        "raw": raw,
        "fingerprint": fp,
        "provider_key": key,
        "model": "mock",
    }
    asserted = psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.emit_step_claimed("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, 'llm', "
        f"{_jsonb(payload)}, 's-1', 90);",
    )
    assert asserted == "t"
    psql(
        server,
        P05_ONLY_DB,
        "CREATE TABLE p05_hook_calls (n integer NOT NULL); "
        "INSERT INTO p05_hook_calls VALUES (0);",
    )
    psql(
        server,
        P05_ONLY_DB,
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN UPDATE public.p05_hook_calls SET n = n + 1; "
        "RAISE EXCEPTION 'hook should not run'; END; $$;",
    )
    try:
        outcome = _step(server, run_id, token)
        assert outcome == "yield"
        assert (
            psql(server, P05_ONLY_DB, "SELECT n FROM p05_hook_calls;") == "0"
        )
        kinds, names = _kinds_names(server, run_id)
        assert kinds == "llm,tool"
        assert names == "s-1,s-1"
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr


def test_p05_provider_key_reused_after_lost_claim_before_checkpoint(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-reuse"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w-expire")
    psql(
        server,
        P05_ONLY_DB,
        "CREATE TABLE p05_hook_keys (provider_key text NOT NULL); "
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN INSERT INTO public.p05_hook_keys VALUES (p_provider_key); "
        "UPDATE cordis.jobs SET claim_expires_at = "
        "pg_catalog.clock_timestamp() - interval '1 second' "
        "WHERE run_id = p_run_id AND status = 'RUNNING'; "
        "RETURN pg_catalog.jsonb_build_object('action','tool',"
        "'tool_name','mock.observe','arguments',"
        "pg_catalog.jsonb_build_object('index', 1)); END; $$;",
    )
    try:
        outcome = _step(server, run_id, token)
        assert outcome == "lost_claim"
        assert (
            psql(
                server,
                P05_ONLY_DB,
                "SELECT count(*) FROM cordis.agent_steps "
                f"WHERE run_id = {_sql_str(run_id)} AND kind = 'llm';",
            )
            == "0"
        )
        first_key = psql(
            server,
            P05_ONLY_DB,
            "SELECT provider_key FROM p05_hook_keys ORDER BY 1 LIMIT 1;",
        )
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr
        psql(
            server,
            P05_ONLY_DB,
            "CREATE TABLE IF NOT EXISTS p05_hook_keys (provider_key text NOT NULL); "
            "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
            "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
            "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
            "SET search_path TO pg_catalog AS $$ "
            "BEGIN INSERT INTO public.p05_hook_keys VALUES (p_provider_key); "
            "RETURN pg_catalog.jsonb_build_object('action','tool',"
            "'tool_name','mock.observe','arguments',"
            "pg_catalog.jsonb_build_object('index', 1)); END; $$;",
        )
        token2 = _claim(server, run_id, "w-retry")
        outcome2 = _step(server, run_id, token2)
        assert outcome2 == "yield"
        keys = psql(
            server,
            P05_ONLY_DB,
            "SELECT provider_key FROM p05_hook_keys ORDER BY 1;",
        ).splitlines()
        assert keys == [first_key, first_key]
        stored = psql(
            server,
            P05_ONLY_DB,
            "SELECT payload->>'provider_key' FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'llm';",
        )
        assert stored == first_key
        expect = psql(
            server,
            P05_ONLY_DB,
            f"SELECT md5({_sql_str(run_id)} || '/' || 's-1');",
        )
        assert stored == expect
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr


def test_p05_fingerprint_mismatch_is_terminal(pgdata: Path, tmp_path: Path) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-fp"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w-fp")
    fp = psql(server, P05_ONLY_DB, _fingerprint_sql(run_id, "s-1", None))
    key = psql(
        server,
        P05_ONLY_DB,
        f"SELECT md5({_sql_str(run_id)} || '/' || 's-1');",
    )
    payload = {
        "protocol": "cordis.p05.mock.v1",
        "raw": {
            "action": "tool",
            "tool_name": "mock.observe",
            "arguments": {"index": 1},
        },
        "fingerprint": fp,
        "provider_key": key,
        "model": "mock",
    }
    psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.emit_step_claimed("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, 'llm', "
        f"{_jsonb(payload)}, 's-1', 90);",
    )
    psql(
        server,
        P05_ONLY_DB,
        "UPDATE cordis.jobs SET payload = payload || "
        f"{_jsonb({'input': {'question': 'changed'}})} "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    psql(
        server,
        P05_ONLY_DB,
        "CREATE TABLE p05_hook_calls (n integer NOT NULL); "
        "INSERT INTO p05_hook_calls VALUES (0); "
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN UPDATE public.p05_hook_calls SET n = n + 1; "
        "RAISE EXCEPTION 'hook should not run'; END; $$;",
    )
    try:
        outcome = _step(server, run_id, token)
        assert outcome == "fail"
        assert _error_code(server, run_id) == "P05_LLM_CHECKPOINT_MISMATCH"
        assert (
            psql(server, P05_ONLY_DB, "SELECT n FROM p05_hook_calls;") == "0"
        )
        kinds, _names = _kinds_names(server, run_id)
        assert kinds == "llm,error"
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr


def test_p05_checkpoint_nonstring_model_is_mismatch(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-ckpt-type"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["model"] = "true"
    _insert_job(server, run_id, payload)
    token = _claim(server, run_id, "w-type")
    fp = psql(server, P05_ONLY_DB, _fingerprint_sql(run_id, "s-1", None))
    key = psql(
        server,
        P05_ONLY_DB,
        f"SELECT md5({_sql_str(run_id)} || '/' || 's-1');",
    )
    raw = {
        "action": "tool",
        "tool_name": "mock.observe",
        "arguments": {"index": 1},
    }
    psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.emit_step_claimed("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, 'llm', "
        "jsonb_build_object("
        "'protocol', 'cordis.p05.mock.v1', "
        f"'raw', {_jsonb(raw)}, "
        f"'fingerprint', {_sql_str(fp)}, "
        f"'provider_key', {_sql_str(key)}, "
        "'model', 'true'::jsonb), 's-1', 90);",
    )
    psql(
        server,
        P05_ONLY_DB,
        "CREATE TABLE p05_hook_calls (n integer NOT NULL); "
        "INSERT INTO p05_hook_calls VALUES (0); "
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN UPDATE public.p05_hook_calls SET n = n + 1; "
        "RAISE EXCEPTION 'hook should not run'; END; $$;",
    )
    try:
        assert _step(server, run_id, token) == "fail"
        assert _error_code(server, run_id) == "P05_LLM_CHECKPOINT_MISMATCH"
        assert (
            psql(server, P05_ONLY_DB, "SELECT n FROM p05_hook_calls;") == "0"
        )
        kinds, _ = _kinds_names(server, run_id)
        assert kinds == "llm,error"
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr


def test_p05_llm_precedes_tool_or_final(pgdata: Path, tmp_path: Path) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-order"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    for i, expected in enumerate(("yield", "yield", "complete"), start=1):
        token = _claim(server, run_id, f"w{i}")
        outcome = _step(server, run_id, token)
        assert outcome == expected
        _map_outcome(server, outcome, token, run_id)
    pairs = psql(
        server,
        P05_ONLY_DB,
        "SELECT a.kind || '>' || b.kind FROM cordis.agent_steps a "
        "JOIN cordis.agent_steps b ON b.run_id = a.run_id "
        "AND b.step_name = a.step_name AND b.seq > a.seq "
        f"WHERE a.run_id = {_sql_str(run_id)} AND a.kind = 'llm' "
        "AND b.kind IN ('tool','final') ORDER BY a.seq;",
    ).splitlines()
    assert pairs == ["llm>tool", "llm>tool", "llm>final"]


def test_p05_crash_after_tool_advances_on_new_claim(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-crash-tool"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w1")
    assert _step(server, run_id, token) == "yield"
    psql(
        server,
        P05_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at = "
        "clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    token2 = _claim(server, run_id, "w2")
    assert token2 != token
    outcome = _step(server, run_id, token2)
    assert outcome == "yield"
    kinds, names = _kinds_names(server, run_id)
    assert kinds == "llm,tool,llm,tool"
    assert names == "s-1,s-1,s-2,s-2"


def test_p05_existing_final_and_error_return_terminal_outcomes(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    final_id = "p05-exist-final"
    _insert_job(server, final_id, PROOF_PAYLOAD)
    token = _claim(server, final_id, "w-final")
    psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.emit_step("
        f"{_sql_str(final_id)}, 'final', {_jsonb({'answer': 'done'})}, 's-1');",
    )
    psql(
        server,
        P05_ONLY_DB,
        "CREATE TABLE p05_hook_calls (n integer NOT NULL); "
        "INSERT INTO p05_hook_calls VALUES (0); "
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN UPDATE public.p05_hook_calls SET n = n + 1; "
        "RAISE EXCEPTION 'hook should not run'; END; $$;",
    )
    try:
        assert _step(server, final_id, token) == "complete"
        kinds, _ = _kinds_names(server, final_id)
        assert kinds == "final"
        assert (
            psql(server, P05_ONLY_DB, "SELECT n FROM p05_hook_calls;") == "0"
        )
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr

    error_id = "p05-exist-error"
    _insert_job(server, error_id, PROOF_PAYLOAD)
    token = _claim(server, error_id, "w-error")
    psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.emit_step("
        f"{_sql_str(error_id)}, 'error', "
        f"{_jsonb({'code': 'PRIOR'})}, NULL);",
    )
    assert _step(server, error_id, token) == "fail"
    assert _error_code(server, error_id) == "PRIOR"


def test_p05_max_steps_allows_checkpoint_completion(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-max-ckpt"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["max_steps"] = 1
    _insert_job(server, run_id, payload)
    token = _claim(server, run_id, "w-max")
    fp = psql(server, P05_ONLY_DB, _fingerprint_sql(run_id, "s-1", None))
    key = psql(
        server,
        P05_ONLY_DB,
        f"SELECT md5({_sql_str(run_id)} || '/' || 's-1');",
    )
    ckpt = {
        "protocol": "cordis.p05.mock.v1",
        "raw": {"action": "final", "answer": "capped"},
        "fingerprint": fp,
        "provider_key": key,
        "model": "mock",
    }
    psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.emit_step_claimed("
        f"{_sql_str(token)}::uuid, {_sql_str(run_id)}, 'llm', "
        f"{_jsonb(ckpt)}, 's-1', 90);",
    )
    assert _step(server, run_id, token) == "complete"
    kinds, names = _kinds_names(server, run_id)
    assert kinds == "llm,final"
    assert names == "s-1,s-1"


def test_p05_max_steps_fails_after_last_nonfinal_tool(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-max-tool"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["max_steps"] = 1
    _insert_job(server, run_id, payload)
    token = _claim(server, run_id, "w-max-tool")
    assert _step(server, run_id, token) == "fail"
    kinds, names = _kinds_names(server, run_id)
    assert kinds == "llm,tool,error"
    assert names == "s-1,s-1,s-1"
    assert _error_code(server, run_id) == "P05_MAX_STEPS_EXCEEDED"


def test_p05_wait_action_fails_without_waiting(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-wait"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["mock_llm"]["responses"]["s-1"] = {"action": "wait"}
    _insert_job(server, run_id, payload)
    token = _claim(server, run_id, "w-wait")
    assert _step(server, run_id, token) == "fail"
    kinds, names = _kinds_names(server, run_id)
    assert kinds == "llm,error"
    assert names == "s-1,s-1"
    assert _error_code(server, run_id) == "P05_WAIT_UNSUPPORTED"
    env = psql(
        server,
        P05_ONLY_DB,
        "SELECT step_name FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)} AND kind = 'error';",
    )
    assert env == "s-1"
    status = psql(
        server,
        P05_ONLY_DB,
        f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert status == "RUNNING"
    assert (
        psql(server, P05_ONLY_DB, "SELECT count(*) FROM cordis.run_waits;")
        == "0"
    )
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind IN "
            "('run/await','run/wake');",
        )
        == "0"
    )


def test_p05_unmatched_await_is_invalid_history(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-await"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w-await")
    psql(
        server,
        P05_ONLY_DB,
        "SELECT cordis.emit_step("
        f"{_sql_str(run_id)}, 'run/await', "
        f"{_jsonb({'await_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'})}, "
        "NULL);",
    )
    psql(
        server,
        P05_ONLY_DB,
        "CREATE TABLE p05_hook_calls (n integer NOT NULL); "
        "INSERT INTO p05_hook_calls VALUES (0); "
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN UPDATE public.p05_hook_calls SET n = n + 1; "
        "RAISE EXCEPTION 'hook should not run'; END; $$;",
    )
    try:
        assert _step(server, run_id, token) == "fail"
        assert _error_code(server, run_id) == "P05_INVALID_HISTORY"
        env = psql(
            server,
            P05_ONLY_DB,
            "SELECT CASE WHEN step_name IS NULL THEN 'NULL' ELSE step_name END "
            "FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'error';",
        )
        assert env == "NULL"
        assert (
            psql(server, P05_ONLY_DB, "SELECT n FROM p05_hook_calls;") == "0"
        )
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr


def test_p05_invalid_config_hook_and_decision_fail_durably(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)

    cfg_id = "p05-bad-config"
    psql(
        server,
        P05_ONLY_DB,
        "INSERT INTO cordis.jobs (run_id, job_type, payload) VALUES ("
        f"{_sql_str(cfg_id)}, 'p05_test', '[]'::jsonb);",
    )
    token = _claim(server, cfg_id, "w-cfg")
    assert _step(server, cfg_id, token) == "fail"
    assert _error_code(server, cfg_id) == "P05_INVALID_JOB_CONFIG"

    model_id = "p05-bad-model"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["model"] = ""
    _insert_job(server, model_id, payload)
    token = _claim(server, model_id, "w-model")
    assert _step(server, model_id, token) == "fail"
    assert _error_code(server, model_id) == "P05_INVALID_JOB_CONFIG"

    steps_id = "p05-bad-steps"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["max_steps"] = 0
    _insert_job(server, steps_id, payload)
    token = _claim(server, steps_id, "w-steps")
    assert _step(server, steps_id, token) == "fail"
    assert _error_code(server, steps_id) == "P05_INVALID_JOB_CONFIG"
    env = psql(
        server,
        P05_ONLY_DB,
        "SELECT CASE WHEN step_name IS NULL THEN 'NULL' ELSE step_name END "
        "FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(cfg_id)} AND kind = 'error';",
    )
    assert env == "NULL"

    dec_id = "p05-bad-decision"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["mock_llm"]["responses"]["s-1"] = {"action": "nope"}
    _insert_job(server, dec_id, payload)
    token = _claim(server, dec_id, "w-dec")
    assert _step(server, dec_id, token) == "fail"
    assert _error_code(server, dec_id) == "P05_INVALID_LLM_DECISION"

    miss_id = "p05-miss-obs"
    payload = copy.deepcopy(PROOF_PAYLOAD)
    payload["mock_tools"] = {"observations": {}}
    _insert_job(server, miss_id, payload)
    token = _claim(server, miss_id, "w-miss")
    assert _step(server, miss_id, token) == "fail"
    assert _error_code(server, miss_id) == "P05_MOCK_TOOL_OBSERVATION_MISSING"

    hook_id = "p05-bad-hook"
    _insert_job(server, hook_id, PROOF_PAYLOAD)
    token = _claim(server, hook_id, "w-hook")
    psql(
        server,
        P05_ONLY_DB,
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN RETURN '[]'::jsonb; END; $$;",
    )
    try:
        assert _step(server, hook_id, token) == "fail"
        assert _error_code(server, hook_id) == "P05_LLM_INVOCATION_FAILED"
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr


def test_p05_lost_claim_never_invokes_or_appends(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-lost"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w-lost")
    psql(
        server,
        P05_ONLY_DB,
        "CREATE TABLE p05_hook_calls (n integer NOT NULL); "
        "INSERT INTO p05_hook_calls VALUES (0); "
        "CREATE OR REPLACE FUNCTION cordis.invoke_llm("
        "p_run_id text, p_step_name text, p_request jsonb, p_provider_key text) "
        "RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER "
        "SET search_path TO pg_catalog AS $$ "
        "BEGIN UPDATE public.p05_hook_calls SET n = n + 1; "
        "RAISE EXCEPTION 'hook should not run'; END; $$;",
    )
    try:
        assert (
            psql(
                server,
                P05_ONLY_DB,
                f"SELECT cordis.step_once({_sql_str(run_id)}, NULL, 90);",
            )
            == "lost_claim"
        )
        bogus = "00000000-0000-0000-0000-000000000000"
        assert (
            psql(
                server,
                P05_ONLY_DB,
                "SELECT cordis.step_once("
                f"{_sql_str(run_id)}, '{bogus}'::uuid, 90);",
            )
            == "lost_claim"
        )
        psql(
            server,
            P05_ONLY_DB,
            "UPDATE cordis.jobs SET claim_expires_at = "
            "clock_timestamp() - interval '1 second' "
            f"WHERE run_id = {_sql_str(run_id)};",
        )
        assert _step(server, run_id, token) == "lost_claim"
        assert (
            psql(server, P05_ONLY_DB, "SELECT n FROM p05_hook_calls;") == "0"
        )
        assert (
            psql(
                server,
                P05_ONLY_DB,
                "SELECT count(*) FROM cordis.agent_steps "
                f"WHERE run_id = {_sql_str(run_id)};",
            )
            == "0"
        )
    finally:
        replay = run_apply(
            "--pgdata",
            str(pgdata),
            "--database",
            P05_ONLY_DB,
            "--sql-root",
            str(tree),
        )
        assert replay.returncode == 0, replay.stdout + replay.stderr


def test_p05_claimed_append_does_not_shorten_longer_lease(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-lease"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w-lease")
    psql(
        server,
        P05_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at = "
        "clock_timestamp() + interval '1 hour' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    before = psql(
        server,
        P05_ONLY_DB,
        "SELECT claim_expires_at FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert _step(server, run_id, token) == "yield"
    after = psql(
        server,
        P05_ONLY_DB,
        "SELECT claim_expires_at FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    cmp_ = psql(
        server,
        P05_ONLY_DB,
        f"SELECT ({_sql_str(after)}::timestamptz >= "
        f"{_sql_str(before)}::timestamptz);",
    )
    assert cmp_ == "t"


def test_p05_does_not_emit_run_yield(pgdata: Path, tmp_path: Path) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-no-yield-kind"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w1")
    assert _step(server, run_id, token) == "yield"
    assert _map_outcome(server, "yield", token, run_id) == "t"
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'run/yield';",
        )
        == "0"
    )


def test_p05_replay_preserves_jobs_logs_and_hook_contract(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-replay"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w1")
    assert _step(server, run_id, token) == "yield"
    assert _map_outcome(server, "yield", token, run_id) == "t"
    before = psql(
        server,
        P05_ONLY_DB,
        "SELECT string_agg(kind || coalesce(step_name, ''), ',' ORDER BY seq) "
        "FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    replay = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P05_ONLY_DB,
        "--sql-root",
        str(tree),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    after = psql(
        server,
        P05_ONLY_DB,
        "SELECT string_agg(kind || coalesce(step_name, ''), ',' ORDER BY seq) "
        "FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert after == before
    assert psql(server, P05_ONLY_DB, "SELECT cordis.get_schema_version();") == "p05"
    token2 = _claim(server, run_id, "w2")
    assert _step(server, run_id, token2) == "yield"


def test_p05_source_boundaries() -> None:
    src = (SQL / "0005_p05_one_step_driver.sql").read_text()
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
    assert re.search(r"UPDATE\s+cordis\.jobs\s+SET\s+status", scanned, re.I) is None
    assert re.search(r"CREATE\s+TYPE", scanned, re.I) is None
    assert re.search(r"CREATE\s+TABLE", scanned, re.I) is None
    assert re.search(r"CREATE\s+EXTENSION", scanned, re.I) is None
    assert re.search(r"\bLISTEN\b", scanned, re.I) is None
    assert re.search(r"\bNOTIFY\b", scanned, re.I) is None
    assert re.search(r"CREATE\s+SCHEMA\s+absurd", scanned, re.I) is None
    assert re.search(r"\bGRANT\b", scanned, re.I) is None
    assert re.search(r"\brlm_loop\b", scanned, re.I) is None
    assert re.search(r"\brlm_eval\b", scanned, re.I) is None
    assert re.search(r"\bworker_step\b", scanned, re.I) is None
    assert re.search(r"\benqueue\b", scanned, re.I) is None
    assert re.search(r"\bspawn\b", scanned, re.I) is None
    assert re.search(r"\bawait_event\b", scanned, re.I) is None
    assert re.search(r"\brun_waits\b", scanned, re.I) is None
    assert re.search(r"COMMENT\s+ON", src, re.I) is None
    assert re.search(r"^COMMENT", src, re.I | re.M) is None
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
        for _match in insert_re.finditer("\n".join(cleaned)):
            inserts.append(path.name)
    assert inserts == ["0002_p02_log.sql"]
    module = load_apply_module()
    module.preflight_sql(SQL / "0005_p05_one_step_driver.sql", src)


def test_p05_duplicate_llm_unique_violation_propagates(
    pgdata: Path, tmp_path: Path
) -> None:
    _apply_p05_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p05-uniq"
    _insert_job(server, run_id, PROOF_PAYLOAD)
    token = _claim(server, run_id, "w-uniq")
    errors: list[str] = []

    def rival() -> None:
        try:
            psql(
                server,
                P05_ONLY_DB,
                "SELECT cordis.step_once("
                f"{_sql_str(run_id)}, {_sql_str(token)}::uuid, 90);",
            )
        except RuntimeError as exc:
            errors.append(str(exc))

    with psql_session(server, P05_ONLY_DB) as sess:
        sess.execute("BEGIN")
        first = sess.execute(
            "SELECT cordis.step_once("
            f"{_sql_str(run_id)}, {_sql_str(token)}::uuid, 90);"
        )
        assert first == ["yield"]
        rival_thread = threading.Thread(target=rival)
        rival_thread.start()
        blocked = False
        deadline = time.time() + 5
        while time.time() < deadline:
            waiting = psql(
                server,
                P05_ONLY_DB,
                "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                "WHERE wait_event_type = 'Lock' "
                "AND query ILIKE '%p05-uniq%';",
            )
            if waiting != "0":
                blocked = True
                break
            time.sleep(0.05)
        assert blocked, "rival session did not block on the live claim"
        sess.commit()
        rival_thread.join(timeout=10)
        assert not rival_thread.is_alive()

    assert errors, "second step_once should have failed"
    assert "23505" in errors[0] or "unique" in errors[0].lower()
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'error';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P05_ONLY_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND kind = 'llm';",
        )
        == "1"
    )
