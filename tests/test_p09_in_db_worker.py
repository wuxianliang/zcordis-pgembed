"""P09 in-database worker tests. Apply execution stays a subprocess."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pgembed import get_server

from tests.conftest import SQL, load_apply_module, psql, run_apply

P09_DB = "cordis_p09"
TREE_FILES = (
    "0000_kernel.sql,0001_p01_claim.sql,0002_p02_log.sql,"
    "0003_p03_wait_event.sql,0005_p05_one_step_driver.sql,"
    "0006_p06_plugin_catalog.sql,0007_p07_grant_registry.sql,"
    "0019_p19_paradigm_policies.sql,0020_p08_four_seam_enforcement.sql,"
    "0021_p09_in_db_worker.sql"
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
NEW_FNS = (
    "cordis._resolve_in_db_queue_handler",
    "cordis.enqueue_job",
    "cordis.invoke_in_db_tool",
    "cordis.worker_step",
)
HOST_NONE = {
    "cordis_plugin": {
        "identity": "host.p09.none",
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


def _reset(pgdata: Path, database: str = P09_DB) -> None:
    result = run_apply(
        "--pgdata", str(pgdata), "--database", database, "--reset"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _psql_verbose(server, sql: str, database: str = P09_DB) -> str:
    return psql(server, database, sql, "-v", "VERBOSITY=verbose")


def _expect_error(
    server,
    sql: str,
    fragment: str,
    sqlstate: str | None = None,
) -> str:
    try:
        _psql_verbose(server, sql)
    except RuntimeError as exc:
        msg = str(exc)
        assert fragment in msg, msg
        if sqlstate is not None:
            assert sqlstate in msg, msg
        return msg
    raise AssertionError(f"expected error containing {fragment!r} for {sql}")


def _plugin_comment(identity: str, extra: dict) -> str:
    plugin = {
        "identity": identity,
        "version": "0.1.0",
        "locus": "in-db",
        "invocation": extra.get("invocation", "queue"),
        "required_grants": extra.get("required_grants", []),
        "effect_class": extra.get("effect_class", "transactional"),
        "retry_class": extra.get("retry_class", "idempotent"),
        "reconciliation": extra.get("reconciliation", "none"),
        "config": extra.get(
            "config",
            {"worker_abi": "cordis.p09.queue.v1"},
        ),
    }
    return json.dumps({"cordis_plugin": plugin}, separators=(",", ":"))


def _install_queue(
    server,
    fn_name: str,
    identity: str,
    body: str,
    *,
    extra: dict | None = None,
    security: str = "INVOKER",
    set_search_path: bool = True,
    args: str = "p_run_id text, p_claim_token uuid, p_lease integer",
    rettype: str = "text",
    lang: str = "plpgsql",
    volatility: str = "VOLATILE",
) -> None:
    path = "SET search_path TO pg_catalog" if set_search_path else ""
    if lang == "plpgsql":
        src = (
            f"CREATE OR REPLACE FUNCTION cordis.{fn_name}({args})\n"
            f"RETURNS {rettype}\nLANGUAGE plpgsql {volatility} "
            f"SECURITY {security}\n{path}\nAS $h$\nBEGIN\n{body}\nEND;\n$h$;"
        )
    else:
        src = (
            f"CREATE OR REPLACE FUNCTION cordis.{fn_name}({args})\n"
            f"RETURNS {rettype}\nLANGUAGE sql VOLATILE "
            f"SECURITY {security}\n{path}\nAS $h$ {body} $h$;"
        )
    psql(server, P09_DB, src)
    type_args = ", ".join(part.strip().split()[-1] for part in args.split(","))
    comment = _plugin_comment(identity, extra or {})
    psql(
        server,
        P09_DB,
        f"COMMENT ON FUNCTION cordis.{fn_name}({type_args}) IS "
        f"{_sql_str(comment)};",
    )
    psql(server, P09_DB, "SELECT cordis.refresh_plugins();")


def _install_tool(
    server,
    fn_name: str,
    identity: str,
    body: str,
    *,
    extra: dict | None = None,
    sleep_seconds: float | None = None,
    returns_null: bool = False,
) -> None:
    if sleep_seconds is not None:
        src = (
            f"CREATE OR REPLACE FUNCTION cordis.{fn_name}(p_arguments jsonb)\n"
            "RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER\n"
            "SET search_path TO pg_catalog\nAS $h$\nBEGIN\n"
            f"  PERFORM pg_catalog.pg_sleep({sleep_seconds});\n"
            "  RETURN p_arguments;\nEND;\n$h$;"
        )
    elif returns_null:
        src = (
            f"CREATE OR REPLACE FUNCTION cordis.{fn_name}(p_arguments jsonb)\n"
            "RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER\n"
            "SET search_path TO pg_catalog\nAS $h$ SELECT NULL::jsonb; $h$;"
        )
    else:
        src = (
            f"CREATE OR REPLACE FUNCTION cordis.{fn_name}(p_arguments jsonb)\n"
            "RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER\n"
            f"SET search_path TO pg_catalog\nAS $h$ {body} $h$;"
        )
    psql(server, P09_DB, src)
    fields = {
        "invocation": "session_select",
        "effect_class": "read_only",
        "retry_class": "replayable",
        "reconciliation": "none",
        "required_grants": ["run"],
        "config": {},
    }
    if extra:
        fields.update(extra)
    comment = _plugin_comment(identity, fields)
    psql(
        server,
        P09_DB,
        f"COMMENT ON FUNCTION cordis.{fn_name}(jsonb) IS {_sql_str(comment)};",
    )
    psql(server, P09_DB, "SELECT cordis.refresh_plugins();")


def _enqueue(
    server,
    run_id: str,
    payload: object | None = None,
    job_type: str = "kernel.step_once",
    paradigm: str = "codeact",
    priority: int = 0,
) -> str:
    body = "{}" if payload is None else payload
    return psql(
        server,
        P09_DB,
        "SELECT cordis.enqueue_job("
        f"{_sql_str(run_id)}, {_sql_str(job_type)}, {_sql_str(paradigm)}, "
        f"{_jsonb(body)}, {priority})::text;",
    )


def _step(
    server, worker: str, run_id: str | None = None, lease: int = 90
) -> str:
    run_sql = "NULL" if run_id is None else _sql_str(run_id)
    return psql(
        server,
        P09_DB,
        "SELECT coalesce(job_id::text, '') || '|' || coalesce(run_id, '') "
        f"|| '|' || outcome FROM cordis.worker_step("
        f"{_sql_str(worker)}, {run_sql}, {lease});",
    )


def _slice_and_run_grant(server, run_id: str) -> str:
    corpus = "c-" + run_id
    psql(
        server,
        P09_DB,
        "SELECT cordis.register_named_corpus("
        f"{_sql_str(corpus)}, 'c', 'host');",
    )
    slice_id = psql(
        server,
        P09_DB,
        "SELECT cordis.create_slice("
        f"{_sql_str(run_id)}, 'fn-1', 'host');",
    )
    psql(
        server,
        P09_DB,
        "SELECT cordis.issue_grant("
        f"{_sql_str(run_id)}, {_sql_str(slice_id)}::uuid, "
        "'run', '', 'host');",
    )
    return slice_id


def test_p09_fresh_apply_catalog_version_and_signatures(pgdata: Path) -> None:
    result = run_apply(
        "--pgdata", str(pgdata), "--database", P09_DB, "--reset"
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert f"files={TREE_FILES}" in result.stdout
    server = get_server(pgdata)
    assert psql(server, P09_DB, "SELECT cordis.get_schema_version();") == "p21"
    names = psql(
        server,
        P09_DB,
        "SELECT n.nspname || '.' || p.proname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN ("
        "'_resolve_in_db_queue_handler','enqueue_job',"
        "'invoke_in_db_tool','worker_step') ORDER BY 1;",
    ).splitlines()
    assert names == list(NEW_FNS)
    rows = psql(
        server,
        P09_DB,
        "SELECT p.proname || '|' || "
        "pg_get_function_identity_arguments(p.oid) || '|' || "
        "pg_get_function_result(p.oid) || '|' || p.provolatile::text || '|' || "
        "p.prosecdef::text || '|' || "
        "coalesce(array_to_string(p.proconfig, ','), '') "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN ("
        "'_resolve_in_db_queue_handler','enqueue_job',"
        "'invoke_in_db_tool','worker_step') ORDER BY 1;",
    ).splitlines()
    by_name = {line.split("|", 1)[0]: line.split("|")[1:] for line in rows}
    assert by_name["_resolve_in_db_queue_handler"][0] == "p_identity text"
    assert by_name["_resolve_in_db_queue_handler"][1] == "regprocedure"
    assert by_name["_resolve_in_db_queue_handler"][2] == "s"
    assert by_name["enqueue_job"][0] == (
        "p_run_id text, p_job_type text, p_paradigm text, "
        "p_payload jsonb, p_priority integer"
    )
    assert by_name["enqueue_job"][1] == "bigint"
    assert by_name["enqueue_job"][2] == "v"
    assert by_name["invoke_in_db_tool"][0] == (
        "p_claim_token uuid, p_run_id text, p_slice_id uuid, "
        "p_identity text, p_bindings jsonb, p_arguments jsonb"
    )
    assert by_name["invoke_in_db_tool"][1] == "jsonb"
    assert by_name["invoke_in_db_tool"][2] == "v"
    assert by_name["worker_step"][0] == (
        "p_worker_id text, p_run_id text, p_lease_seconds integer"
    )
    assert "job_id" in by_name["worker_step"][1]
    assert by_name["worker_step"][2] == "v"
    for spec in by_name.values():
        assert spec[3] == "false"
        assert "search_path=pg_catalog" in spec[4]
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace WHERE n.nspname = 'cordis' "
            "AND p.proname IN ('_resolve_in_db_queue_handler','enqueue_job',"
            "'invoke_in_db_tool','worker_step');",
        )
        == "4"
    )
    assert (
        psql(
            server,
            P09_DB,
            "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'cordis' "
            "AND c.relkind = 'r' AND c.relname LIKE 'p09%';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P09_DB,
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_cordis';",
        )
        == "0"
    )


def test_p09_kernel_step_once_is_direct_queue_handler(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    row = psql(
        server,
        P09_DB,
        "SELECT entrypoint::text || '|' || (config->>'worker_abi') || '|' || "
        "(config->>'protocol') || '|' || (config->>'isolated') || '|' || "
        "locus || '|' || invocation || '|' || "
        "coalesce(array_to_string(required_grants, ','), '') "
        "FROM cordis.plugin_catalog WHERE identity = 'kernel.step_once';",
    )
    assert row.startswith("cordis.step_once(text,uuid,integer)|")
    assert "cordis.p09.queue.v1" in row
    assert "cordis.p05.mock.v1" in row
    assert "|false|" in row
    assert "|in-db|queue|" in row
    desc = psql(
        server,
        P09_DB,
        "SELECT description FROM cordis.plugin_catalog "
        "WHERE identity = 'kernel.step_once';",
    )
    assert "legacy_unscoped" in desc
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace WHERE n.nspname = 'cordis' "
            "AND p.proname = 'step_once';",
        )
        == "1"
    )


def test_p09_queue_handler_resolver_rejects_wrong_shape(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(
        server,
        P09_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(HOST_NONE) + ");",
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('host.p09.none');",
        "P09_JOB_HANDLER_UNSUPPORTED",
        "0A000",
    )
    _install_tool(
        server,
        "p09_session_echo",
        "p09.session.echo",
        "SELECT p_arguments;",
        extra={"required_grants": []},
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.session.echo');",
        "P09_JOB_HANDLER_UNSUPPORTED",
        "0A000",
    )
    _install_queue(
        server,
        "p09_grant_q",
        "p09.grant.queue",
        "RETURN 'yield';",
        extra={"required_grants": ["run"]},
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.grant.queue');",
        "P09_JOB_HANDLER_UNSUPPORTED",
        "0A000",
    )
    _install_queue(
        server,
        "p09_bad_sig",
        "p09.bad.sig",
        "RETURN 'x';",
        args="p_run_id text",
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.bad.sig');",
        "P09_JOB_HANDLER_ABI_MISMATCH",
        "55000",
    )
    _install_queue(
        server,
        "p09_definer",
        "p09.bad.definer",
        "RETURN 'yield';",
        security="DEFINER",
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.bad.definer');",
        "P09_JOB_HANDLER_ABI_MISMATCH",
        "55000",
    )
    _install_queue(
        server,
        "p09_unpinned",
        "p09.bad.unpinned",
        "RETURN 'yield';",
        set_search_path=False,
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.bad.unpinned');",
        "P09_JOB_HANDLER_ABI_MISMATCH",
        "55000",
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('missing.handler');",
        "P09_UNKNOWN_JOB_HANDLER",
        "22023",
    )
    _install_queue(
        server,
        "p09_setof",
        "p09.bad.setof",
        "RETURN NEXT 'x';\nRETURN;",
        rettype="SETOF text",
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.bad.setof');",
        "P09_JOB_HANDLER_ABI_MISMATCH",
        "55000",
    )
    _install_queue(
        server,
        "p09_stable",
        "p09.bad.stable",
        "RETURN 'yield';",
        volatility="STABLE",
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.bad.stable');",
        "P09_JOB_HANDLER_ABI_MISMATCH",
        "55000",
    )
    _install_queue(
        server,
        "p09_ov",
        "p09.bad.overload",
        "RETURN 'yield';",
    )
    psql(
        server,
        P09_DB,
        "CREATE OR REPLACE FUNCTION cordis.p09_ov("
        "p_run_id text, p_claim_token uuid, p_lease integer, "
        "p_extra text DEFAULT NULL)\n"
        "RETURNS text LANGUAGE plpgsql VOLATILE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog\nAS $h$ BEGIN RETURN 'x'; END; $h$;",
    )
    _expect_error(
        server,
        "SELECT cordis._resolve_in_db_queue_handler('p09.bad.overload');",
        "P09_JOB_HANDLER_ABI_MISMATCH",
        "55000",
    )


def test_p09_enqueue_validates_handler_paradigm_and_payload(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    job_id = _enqueue(server, "p09-enq-ok", PROOF_PAYLOAD)
    assert job_id
    row = psql(
        server,
        P09_DB,
        "SELECT job_type || '|' || (payload->>'paradigm') || '|' || status "
        "FROM cordis.jobs WHERE run_id = 'p09-enq-ok';",
    )
    assert row == "kernel.step_once|codeact|PENDING"
    question = psql(
        server,
        P09_DB,
        "SELECT payload#>>'{input,question}' FROM cordis.jobs "
        "WHERE run_id = 'p09-enq-ok';",
    )
    assert question == "p05 proof"
    before = psql(server, P09_DB, "SELECT count(*) FROM cordis.jobs;")
    _expect_error(
        server,
        "SELECT cordis.enqueue_job('p09-bad-p', 'kernel.step_once', "
        "'codeact', jsonb_build_object('paradigm', 'codeact'), 0);",
        "P09_INVALID_ENQUEUE",
        "22023",
    )
    _expect_error(
        server,
        "SELECT cordis.enqueue_job('p09-bad-h', 'host.p09.none', "
        "'codeact', '{}'::jsonb, 0);",
        "P09_UNKNOWN_JOB_HANDLER",
        "22023",
    )
    _expect_error(
        server,
        "SELECT cordis.enqueue_job('p09-bad-par', 'kernel.step_once', "
        "'nope', '{}'::jsonb, 0);",
        "unknown paradigm",
        "22023",
    )
    after = psql(server, P09_DB, "SELECT count(*) FROM cordis.jobs;")
    assert after == before


def test_p09_enqueue_duplicate_run_propagates_unique_violation(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    first = _enqueue(server, "p09-dup", PROOF_PAYLOAD)
    before = psql(
        server,
        P09_DB,
        "SELECT job_id::text || '|' || job_type FROM cordis.jobs "
        "WHERE run_id = 'p09-dup';",
    )
    msg = _expect_error(
        server,
        "SELECT cordis.enqueue_job('p09-dup', 'kernel.step_once', "
        "'codeact', '{}'::jsonb, 0);",
        "23505",
        "23505",
    )
    assert "jobs_run_id_key" in msg or "duplicate" in msg.lower() or "23505" in msg
    after = psql(
        server,
        P09_DB,
        "SELECT job_id::text || '|' || job_type FROM cordis.jobs "
        "WHERE run_id = 'p09-dup';",
    )
    assert after == before
    assert first in after


def test_p09_worker_step_idle_and_named_run_polling(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    assert _step(server, "w-idle") == "||idle"
    _enqueue(server, "p09-a", PROOF_PAYLOAD, priority=1)
    _enqueue(server, "p09-b", PROOF_PAYLOAD, priority=1)
    named = _step(server, "w-named", "p09-a")
    assert named.endswith("|p09-a|yield")
    other = psql(
        server,
        P09_DB,
        "SELECT status FROM cordis.jobs WHERE run_id = 'p09-b';",
    )
    assert other == "PENDING"


def test_p09_worker_step_claims_at_most_one_ready_job(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _enqueue(server, "p09-lo", PROOF_PAYLOAD, priority=1)
    _enqueue(server, "p09-hi", PROOF_PAYLOAD, priority=10)
    row = _step(server, "w-one")
    assert row.endswith("|p09-hi|yield")
    statuses = psql(
        server,
        P09_DB,
        "SELECT run_id || '=' || status FROM cordis.jobs "
        "WHERE run_id IN ('p09-lo','p09-hi') ORDER BY run_id;",
    )
    assert "p09-hi=PENDING" in statuses
    assert "p09-lo=PENDING" in statuses
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'p09-hi';",
        )
        != "0"
    )
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.agent_steps WHERE run_id = 'p09-lo';",
        )
        == "0"
    )


def test_p09_single_worker_yields_reclaims_and_completes_mock_run(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _enqueue(server, "p09-proof", PROOF_PAYLOAD)
    outcomes = []
    for _ in range(3):
        row = _step(server, "worker-a", "p09-proof")
        outcomes.append(row.rsplit("|", 1)[-1])
    assert outcomes == ["yield", "yield", "complete"]
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.jobs WHERE run_id = 'p09-proof';",
        )
        == "1"
    )
    kinds = psql(
        server,
        P09_DB,
        "SELECT string_agg(kind, ',' ORDER BY seq) FROM cordis.agent_steps "
        "WHERE run_id = 'p09-proof';",
    )
    names = psql(
        server,
        P09_DB,
        "SELECT string_agg(coalesce(step_name, ''), ',' ORDER BY seq) "
        "FROM cordis.agent_steps WHERE run_id = 'p09-proof';",
    )
    assert kinds == "llm,tool,llm,tool,llm,final"
    assert names == "s-1,s-1,s-2,s-2,s-3,s-3"
    state = psql(
        server,
        P09_DB,
        "SELECT status || '|' || steps_used::text || '|' || coalesce(answer, '') "
        "FROM cordis.run_state('p09-proof');",
    )
    assert state == "final|3|ok"
    assert (
        psql(
            server,
            P09_DB,
            "SELECT result->>'answer' FROM cordis.jobs "
            "WHERE run_id = 'p09-proof';",
        )
        == "ok"
    )
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            "WHERE run_id = 'p09-proof' AND kind = 'run/yield';",
        )
        == "0"
    )


def test_p09_worker_revalidates_paradigm_and_handler_after_enqueue(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _enqueue(server, "p09-policy-gone", PROOF_PAYLOAD)
    assert (
        psql(
            server,
            P09_DB,
            "SELECT cordis.unregister_paradigm_policy('codeact');",
        )
        == "t"
    )
    row = _step(server, "w", "p09-policy-gone")
    assert row.endswith("|fail")
    code = psql(
        server,
        P09_DB,
        "SELECT error->>'code' FROM cordis.jobs "
        "WHERE run_id = 'p09-policy-gone';",
    )
    assert code == "P09_PARADIGM_UNAVAILABLE"
    _reset(pgdata)
    server = get_server(pgdata)
    _enqueue(server, "p09-handler-gone", PROOF_PAYLOAD)
    psql(
        server,
        P09_DB,
        "COMMENT ON FUNCTION cordis.step_once(text, uuid, integer) IS NULL;",
    )
    psql(server, P09_DB, "SELECT cordis.refresh_plugins();")
    row = _step(server, "w", "p09-handler-gone")
    assert row.endswith("|fail")
    code = psql(
        server,
        P09_DB,
        "SELECT error->>'code' FROM cordis.jobs "
        "WHERE run_id = 'p09-handler-gone';",
    )
    assert code == "P09_HANDLER_UNAVAILABLE"


def test_p09_worker_maps_p05_failure_to_terminal_job(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _enqueue(server, "p09-p05-fail", {"input": {"question": "no mock"}})
    row = _step(server, "w", "p09-p05-fail")
    assert row.endswith("|fail")
    status = psql(
        server,
        P09_DB,
        "SELECT status FROM cordis.jobs WHERE run_id = 'p09-p05-fail';",
    )
    assert status == "ERROR"
    err = psql(
        server,
        P09_DB,
        "SELECT error->>'code' FROM cordis.jobs WHERE run_id = 'p09-p05-fail';",
    )
    assert err.startswith("P05_")


def test_p09_complete_and_fail_without_log_are_protocol_failures(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_queue(
        server, "p09_bare_complete", "p09.bare.complete", "RETURN 'complete';"
    )
    _install_queue(
        server, "p09_bare_fail", "p09.bare.fail", "RETURN 'fail';"
    )
    _enqueue(server, "p09-c", {}, job_type="p09.bare.complete")
    assert _step(server, "w", "p09-c").endswith("|fail")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT error->>'code' FROM cordis.jobs WHERE run_id = 'p09-c';",
        )
        == "P09_COMPLETE_WITHOUT_FINAL"
    )
    _enqueue(server, "p09-f", {}, job_type="p09.bare.fail")
    assert _step(server, "w", "p09-f").endswith("|fail")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT error->>'code' FROM cordis.jobs WHERE run_id = 'p09-f';",
        )
        == "P09_FAIL_WITHOUT_ERROR"
    )


def test_p09_unknown_and_null_handler_outcomes_fail_durably(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_queue(server, "p09_unknown", "p09.out.unknown", "RETURN 'nope';")
    _install_queue(server, "p09_null", "p09.out.null", "RETURN NULL;")
    _enqueue(server, "p09-u", {}, job_type="p09.out.unknown")
    assert _step(server, "w", "p09-u").endswith("|fail")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT error->>'code' FROM cordis.jobs WHERE run_id = 'p09-u';",
        )
        == "P09_INVALID_STEP_OUTCOME"
    )
    _enqueue(server, "p09-n", {}, job_type="p09.out.null")
    assert _step(server, "w", "p09-n").endswith("|fail")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT error->>'code' FROM cordis.jobs WHERE run_id = 'p09-n';",
        )
        == "P09_INVALID_STEP_OUTCOME"
    )


def test_p09_wait_requires_completed_p03_registration(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_queue(
        server,
        "p09_wait_ok",
        "p09.wait.ok",
        "PERFORM * FROM cordis.await_event("
        "p_claim_token, p_run_id, 'p09-scope', 'done',"
        " pg_catalog.gen_random_uuid());\n"
        "RETURN 'wait';",
    )
    _install_queue(
        server, "p09_wait_bare", "p09.wait.bare", "RETURN 'wait';"
    )
    _enqueue(server, "p09-wait-ok", {}, job_type="p09.wait.ok")
    assert _step(server, "w", "p09-wait-ok").endswith("|wait")
    job = psql(
        server,
        P09_DB,
        "SELECT status || '|' || coalesce(claim_token::text, '') "
        "FROM cordis.jobs WHERE run_id = 'p09-wait-ok';",
    )
    assert job.startswith("WAITING|")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.run_waits "
            "WHERE run_id = 'p09-wait-ok';",
        )
        == "1"
    )
    _enqueue(server, "p09-wait-bare", {}, job_type="p09.wait.bare")
    assert _step(server, "w", "p09-wait-bare").endswith("|fail")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT error->>'code' FROM cordis.jobs "
            "WHERE run_id = 'p09-wait-bare';",
        )
        == "P09_WAIT_NOT_REGISTERED"
    )


def test_p09_handler_exception_propagates_and_rolls_back_claim(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_queue(
        server,
        "p09_boom",
        "p09.boom",
        "RAISE EXCEPTION 'p09-fixture-boom' USING ERRCODE = '23505';",
    )
    _enqueue(server, "p09-boom", {}, job_type="p09.boom")
    _expect_error(
        server,
        "SELECT * FROM cordis.worker_step('w', 'p09-boom', 90);",
        "23505",
        "23505",
    )
    row = psql(
        server,
        P09_DB,
        "SELECT status || '|' || coalesce(claim_token::text, '') "
        "FROM cordis.jobs WHERE run_id = 'p09-boom';",
    )
    assert row.startswith("PENDING|")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            "WHERE run_id = 'p09-boom';",
        )
        == "0"
    )


def test_p09_transition_fence_returns_lost_claim(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_queue(
        server,
        "p09_expire",
        "p09.expire",
        "UPDATE cordis.jobs SET claim_expires_at = "
        "pg_catalog.clock_timestamp() - interval '1 second' "
        "WHERE claim_token = p_claim_token;\n"
        "RETURN 'yield';",
    )
    _enqueue(server, "p09-lost", {}, job_type="p09.expire")
    row = _step(server, "w", "p09-lost")
    assert row.endswith("|lost_claim")
    status = psql(
        server,
        P09_DB,
        "SELECT status FROM cordis.jobs WHERE run_id = 'p09-lost';",
    )
    assert status == "RUNNING"


def test_p09_in_db_tool_authorizes_and_executes_read_only_entrypoint(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_tool(
        server, "p09_echo_tool", "p09.echo.tool", "SELECT p_arguments;"
    )
    _enqueue(server, "p09-tool", PROOF_PAYLOAD)
    token = psql(
        server,
        P09_DB,
        "SELECT claim_token::text FROM cordis.claim_job("
        "'p09-tool', 'w-tool', 90);",
    )
    slice_id = _slice_and_run_grant(server, "p09-tool")
    out = json.loads(
        psql(
            server,
            P09_DB,
            "SELECT cordis.invoke_in_db_tool("
            f"{_sql_str(token)}::uuid, 'p09-tool', "
            f"{_sql_str(slice_id)}::uuid, 'p09.echo.tool', "
            '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        )
    )
    assert out["protocol"] == "cordis.p09.in_db_tool.v1"
    assert out["identity"] == "p09.echo.tool"
    assert out["result"] == {"k": 1}
    assert out["descriptor"]["locus"] == "in-db"


def test_p09_in_db_tool_refuses_host_queue_and_effectful_entries(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(
        server,
        P09_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(HOST_NONE) + ");",
    )
    _install_tool(
        server,
        "p09_tx_tool",
        "p09.tx.tool",
        "SELECT p_arguments;",
        extra={
            "effect_class": "transactional",
            "retry_class": "idempotent",
            "reconciliation": "none",
        },
    )
    _enqueue(server, "p09-ref", PROOF_PAYLOAD)
    token = psql(
        server,
        P09_DB,
        "SELECT claim_token::text FROM cordis.claim_job("
        "'p09-ref', 'w', 90);",
    )
    slice_id = _slice_and_run_grant(server, "p09-ref")
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-ref', "
        f"{_sql_str(slice_id)}::uuid, 'host.p09.none', "
        "'{}'::jsonb, '{}'::jsonb);",
        "P09_IN_DB_TOOL_LOCUS_REQUIRED",
        "42501",
    )
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-ref', "
        f"{_sql_str(slice_id)}::uuid, 'kernel.step_once', "
        "'{}'::jsonb, '{}'::jsonb);",
        "P09_IN_DB_TOOL_INVOCATION_UNSUPPORTED",
        "0A000",
    )
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-ref', "
        f"{_sql_str(slice_id)}::uuid, 'p09.tx.tool', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "P09_IN_DB_TOOL_EFFECT_UNSUPPORTED",
        "0A000",
    )
    _install_tool(
        server,
        "p09_ext_tool",
        "p09.ext.tool",
        "SELECT p_arguments;",
        extra={
            "effect_class": "external",
            "retry_class": "idempotent",
            "reconciliation": "operation_key",
        },
    )
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-ref', "
        f"{_sql_str(slice_id)}::uuid, 'p09.ext.tool', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "P09_IN_DB_TOOL_EFFECT_UNSUPPORTED",
        "0A000",
    )
    _install_tool(
        server, "p09_ov_tool", "p09.ov.tool", "SELECT p_arguments;"
    )
    psql(
        server,
        P09_DB,
        "CREATE OR REPLACE FUNCTION cordis.p09_ov_tool("
        "p_arguments jsonb, p_extra text DEFAULT NULL)\n"
        "RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog\nAS $h$ SELECT p_arguments; $h$;",
    )
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-ref', "
        f"{_sql_str(slice_id)}::uuid, 'p09.ov.tool', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "P09_IN_DB_TOOL_ABI_MISMATCH",
        "55000",
    )
    psql(
        server,
        P09_DB,
        "CREATE OR REPLACE FUNCTION cordis.p09_boom_tool(p_arguments jsonb)\n"
        "RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog\nAS $h$\nBEGIN\n"
        "  RAISE EXCEPTION 'p09-tool-boom' USING ERRCODE = '22023';\n"
        "END;\n$h$;",
    )
    comment = _plugin_comment(
        "p09.boom.tool",
        {
            "invocation": "session_select",
            "effect_class": "read_only",
            "retry_class": "replayable",
            "reconciliation": "none",
            "required_grants": ["run"],
            "config": {},
        },
    )
    psql(
        server,
        P09_DB,
        "COMMENT ON FUNCTION cordis.p09_boom_tool(jsonb) IS "
        f"{_sql_str(comment)};",
    )
    psql(server, P09_DB, "SELECT cordis.refresh_plugins();")
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-ref', "
        f"{_sql_str(slice_id)}::uuid, 'p09.boom.tool', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "p09-tool-boom",
        "22023",
    )


def test_p09_in_db_tool_checks_claim_before_and_after_execution(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_tool(
        server,
        "p09_slow_tool",
        "p09.slow.tool",
        "SELECT p_arguments;",
        sleep_seconds=2,
    )
    _install_tool(
        server, "p09_null_tool", "p09.null.tool", "", returns_null=True
    )
    _enqueue(server, "p09-claim", PROOF_PAYLOAD)
    slice_id = _slice_and_run_grant(server, "p09-claim")
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        "'00000000-0000-0000-0000-000000000001'::uuid, 'p09-claim', "
        f"{_sql_str(slice_id)}::uuid, 'p09.slow.tool', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "P09_TOOL_CLAIM_REQUIRED",
        "42501",
    )
    token = psql(
        server,
        P09_DB,
        "SELECT claim_token::text FROM cordis.claim_job("
        "'p09-claim', 'w', 1);",
    )
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-claim', "
        f"{_sql_str(slice_id)}::uuid, 'p09.slow.tool', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "P09_TOOL_CLAIM_LOST",
        "55000",
    )
    _enqueue(server, "p09-null", PROOF_PAYLOAD)
    token2 = psql(
        server,
        P09_DB,
        "SELECT claim_token::text FROM cordis.claim_job("
        "'p09-null', 'w2', 90);",
    )
    slice2 = _slice_and_run_grant(server, "p09-null")
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token2)}::uuid, 'p09-null', "
        f"{_sql_str(slice2)}::uuid, 'p09.null.tool', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "P09_IN_DB_TOOL_INVALID_RESULT",
        "55000",
    )


def test_p09_in_db_tool_does_not_cache_authorization(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _install_tool(
        server, "p09_echo_tool2", "p09.echo.tool2", "SELECT p_arguments;"
    )
    _enqueue(server, "p09-rev", PROOF_PAYLOAD)
    token = psql(
        server,
        P09_DB,
        "SELECT claim_token::text FROM cordis.claim_job("
        "'p09-rev', 'w', 90);",
    )
    slice_id = _slice_and_run_grant(server, "p09-rev")
    psql(
        server,
        P09_DB,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-rev', "
        f"{_sql_str(slice_id)}::uuid, 'p09.echo.tool2', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
    )
    grant_id = psql(
        server,
        P09_DB,
        "SELECT grant_id::text FROM cordis.grants "
        f"WHERE slice_id = {_sql_str(slice_id)}::uuid AND kind = 'run' "
        "AND status = 'issued' ORDER BY created_at DESC LIMIT 1;",
    )
    psql(
        server,
        P09_DB,
        f"SELECT cordis.revoke_grant({_sql_str(grant_id)}::uuid, 'host');",
    )
    _expect_error(
        server,
        "SELECT cordis.invoke_in_db_tool("
        f"{_sql_str(token)}::uuid, 'p09-rev', "
        f"{_sql_str(slice_id)}::uuid, 'p09.echo.tool2', "
        '\'{"run": true}\'::jsonb, \'{"k": 1}\'::jsonb);',
        "P08_TOOL_GRANT_REQUIRED",
        "42501",
    )


def test_p09_replay_preserves_jobs_logs_runtime_catalog_and_policies(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    _enqueue(server, "p09-replay", PROOF_PAYLOAD)
    _step(server, "w", "p09-replay")
    psql(
        server,
        P09_DB,
        "SELECT cordis.register_host_plugin(" + _jsonb(HOST_NONE) + ");",
    )
    psql(
        server,
        P09_DB,
        "SELECT cordis.register_paradigm_policy("
        + _jsonb(
            {
                "cordis_paradigm": {
                    "identity": "p09.runtime",
                    "version": "0.1.0",
                    "description": "runtime",
                    "action_surface": "structured_tools",
                    "parser_kind": "json_tool_calls",
                    "spawn_mode": "always_enqueue",
                    "env_enabled": False,
                    "env_workspace": "none",
                    "env_inherit": "none",
                    "observation_clip_chars": None,
                    "observation_full_in_env": False,
                    "system_prompt": "runtime prompt",
                    "fold_fn": "cordis.fold_codeact_messages",
                    "parse_fn": "cordis.parse_codeact_decision",
                    "observe_fn": "cordis.observe_codeact",
                }
            }
        )
        + ");",
    )
    psql(
        server,
        P09_DB,
        "COMMENT ON FUNCTION cordis.step_once(text, uuid, integer) IS NULL;",
    )
    psql(server, P09_DB, "SELECT cordis.refresh_plugins();")
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.plugin_catalog "
            "WHERE identity = 'kernel.step_once';",
        )
        == "0"
    )
    before_job = psql(
        server,
        P09_DB,
        "SELECT job_id::text || '|' || status || '|' || "
        "(payload->>'paradigm') FROM cordis.jobs "
        "WHERE run_id = 'p09-replay';",
    )
    before_log = psql(
        server,
        P09_DB,
        "SELECT count(*) FROM cordis.agent_steps "
        "WHERE run_id = 'p09-replay';",
    )
    replay = run_apply("--pgdata", str(pgdata), "--database", P09_DB)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert "mode=in-place" in replay.stdout
    assert psql(server, P09_DB, "SELECT cordis.get_schema_version();") == "p21"
    after_job = psql(
        server,
        P09_DB,
        "SELECT job_id::text || '|' || status || '|' || "
        "(payload->>'paradigm') FROM cordis.jobs "
        "WHERE run_id = 'p09-replay';",
    )
    after_log = psql(
        server,
        P09_DB,
        "SELECT count(*) FROM cordis.agent_steps "
        "WHERE run_id = 'p09-replay';",
    )
    assert after_job == before_job
    assert after_log == before_log
    assert (
        psql(
            server,
            P09_DB,
            "SELECT count(*) FROM cordis.host_plugin_definitions "
            "WHERE identity = 'host.p09.none';",
        )
        == "1"
    )
    assert (
        psql(
            server,
            P09_DB,
            "SELECT identity FROM cordis.plugin_catalog "
            "WHERE identity = 'kernel.step_once';",
        )
        == "kernel.step_once"
    )
    assert (
        psql(
            server,
            P09_DB,
            "SELECT config->>'isolated' FROM cordis.plugin_catalog "
            "WHERE identity = 'kernel.step_once';",
        )
        == "false"
    )
    assert (
        psql(
            server,
            P09_DB,
            "SELECT identity FROM cordis.paradigm_policies "
            "WHERE identity = 'p09.runtime';",
        )
        == "p09.runtime"
    )


def test_p09_source_boundaries() -> None:
    body = (SQL / "0021_p09_in_db_worker.sql").read_text()
    assert "$p09$" in body
    assert "CREATE OR REPLACE FUNCTION cordis.step_once" not in body
    assert re.search(r"UPDATE\s+cordis\.jobs\s+SET\s+status", body, re.I) is None
    assert re.search(r"INSERT\s+INTO\s+cordis\.agent_steps", body, re.I) is None
    assert re.search(r"\bLOOP\b", body) is None
    assert re.search(r"\bTEMP\b", body) is None
    assert "CREATE EXTENSION" not in body
    apply_mod = load_apply_module()
    scanned = apply_mod.sanitize_sql_for_preflight(body)
    assert apply_mod.FORBIDDEN_STMTS[4].search(scanned) is None
    for path in sorted(SQL.glob("*.sql")):
        if path.name == "0021_p09_in_db_worker.sql":
            continue
        text = path.read_text()
        assert "worker_step" not in text or path.name.startswith("000") is False
    older = (SQL / "0005_p05_one_step_driver.sql").read_text()
    assert "COMMENT ON FUNCTION cordis.step_once" not in older
