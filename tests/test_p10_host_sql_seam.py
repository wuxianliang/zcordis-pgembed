"""P10 host SQL seam tests. Apply stays a subprocess."""

from __future__ import annotations

import json
import math
import os
import stat
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pgembed import POSTGRES_BIN_PATH, get_server

import pg_cordis_host
from pg_cordis_host import (
    AgentStep,
    AuthorizedHostTool,
    AwaitEventResult,
    CheckpointEvent,
    ClaimedJob,
    CordisCommandTimeout,
    CordisFeatureUnavailable,
    CordisHostClient,
    CordisHostError,
    CordisInputError,
    CordisProtocolError,
    CordisSqlError,
    JobSnapshot,
    NamedCorpusRef,
    PluginCatalogEntry,
    RunState,
    new_host_worker_id,
)
from tests.conftest import REPO, SQL, psql, run_apply

P10_DB = "cordis_p10"
PUBLIC_API = {
    "AgentStep",
    "AuthorizedHostTool",
    "AwaitEventResult",
    "CheckpointEvent",
    "ClaimedJob",
    "CordisCommandTimeout",
    "CordisFeatureUnavailable",
    "CordisHostClient",
    "CordisHostError",
    "CordisInputError",
    "CordisProtocolError",
    "CordisSqlError",
    "JobSnapshot",
    "NamedCorpusRef",
    "PluginCatalogEntry",
    "RunState",
    "new_host_worker_id",
}
READONLY_HOST = {
    "cordis_plugin": {
        "identity": "host.p10.lookup",
        "version": "0.1.0",
        "name": "lookup",
        "description": "P10 read-only host tool",
        "locus": "host",
        "invocation": "host_tool",
        "required_grants": ["named_corpus"],
        "effect_class": "read_only",
        "retry_class": "replayable",
        "reconciliation": "none",
    }
}
EXTERNAL_HOST = {
    "cordis_plugin": {
        "identity": "host.p10.mutate",
        "version": "0.1.0",
        "locus": "host",
        "invocation": "host_tool",
        "required_grants": [],
        "effect_class": "external",
        "retry_class": "idempotent",
        "reconciliation": "operation_key",
    }
}
FORBIDDEN_SOURCE = (
    "worker_step",
    "enqueue_job",
    "invoke_in_db_tool",
    "_resolve_in_db_queue_handler",
    "invoke_llm",
    "emit_event",
    "issue_grant",
    "execute_host_tool",
    "step_once",
    "pgembed",
    "psycopg",
    "asyncpg",
    "yield_walkthrough",
    ".p19-backup",
)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _reset(pgdata: Path) -> None:
    result = run_apply(
        "--pgdata", str(pgdata), "--database", P10_DB, "--reset"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _client(server, worker: str | None = None) -> CordisHostClient:
    if worker is None:
        worker = new_host_worker_id("p10proof")
    return CordisHostClient(
        server.get_uri(P10_DB),
        worker,
        psql_path=POSTGRES_BIN_PATH / "psql",
    )


def _insert_job(server, run_id: str, job_type: str = "p10") -> None:
    psql(
        server,
        P10_DB,
        "INSERT INTO cordis.jobs (run_id, job_type) VALUES ("
        f"{_sql_str(run_id)}, {_sql_str(job_type)});",
    )


def _slice(server, run_id: str, name: str) -> uuid.UUID:
    raw = psql(
        server,
        P10_DB,
        "SELECT cordis.create_slice("
        f"{_sql_str(run_id)}, {_sql_str(name)}, 'host');",
    )
    return uuid.UUID(raw)


def _issue(
    server, run_id: str, slice_id: uuid.UUID, kind: str, target: str
) -> uuid.UUID:
    raw = psql(
        server,
        P10_DB,
        "SELECT cordis.issue_grant("
        f"{_sql_str(run_id)}, {_sql_str(str(slice_id))}::uuid, "
        f"{_sql_str(kind)}, {_sql_str(target)}, 'host');",
    )
    return uuid.UUID(raw)


def _register_corpus(server, corpus_id: str, label: str) -> None:
    psql(
        server,
        P10_DB,
        "SELECT cordis.register_named_corpus("
        f"{_sql_str(corpus_id)}, {_sql_str(label)}, 'host');",
    )


def _write_stub(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_p10_worker_id_format_and_client_validation() -> None:
    fixed = uuid.UUID("12345678123456781234567812345678")
    assert (
        new_host_worker_id("p10proof", fixed)
        == "host:p10proof:12345678123456781234567812345678"
    )
    with pytest.raises(CordisInputError):
        new_host_worker_id("P10")
    with pytest.raises(CordisInputError):
        CordisHostClient("", "host:p10proof:" + "a" * 32)
    with pytest.raises(CordisInputError):
        CordisHostClient("postgres://localhost/db", "not-a-host-id")
    with pytest.raises(CordisInputError):
        CordisHostClient("postgres://localhost/db", new_host_worker_id("svc"), psql_path="")
    with pytest.raises(CordisInputError):
        CordisHostClient(
            "postgres://localhost/db",
            new_host_worker_id("svc"),
            command_timeout_seconds=0,
        )
    with pytest.raises(CordisInputError):
        CordisHostClient(
            "postgres://localhost/db",
            new_host_worker_id("svc"),
            command_timeout_seconds=math.nan,
        )
    client = CordisHostClient(
        "postgres://user:secret@localhost/db", new_host_worker_id("svc")
    )
    dumped = repr(client)
    assert "secret" not in dumped
    assert "postgres://" not in dumped
    with pytest.raises(CordisInputError):
        client.claim_job("run", lease_seconds=0)
    with pytest.raises(CordisInputError):
        client.fail_claim(uuid.uuid4(), {"x": "a\x00b"})



def test_p10_psql_transport_errors_and_output_validation(
    tmp_path: Path,
) -> None:
    worker = new_host_worker_id("p10proof")
    missing = CordisHostClient(
        "postgres://user:supersecret@127.0.0.1/db",
        worker,
        psql_path=tmp_path / "no-such-psql",
    )
    with pytest.raises(CordisHostError) as missing_exc:
        missing.next_step_name("run-x")
    assert "supersecret" not in str(missing_exc.value)
    assert not hasattr(missing_exc.value, "dsn")

    sleeper = _write_stub(tmp_path / "sleep-psql", "sleep 30\n")
    slow = CordisHostClient(
        "postgres://user:supersecret@127.0.0.1/db",
        worker,
        psql_path=sleeper,
        command_timeout_seconds=0.2,
    )
    with pytest.raises(CordisCommandTimeout) as timed:
        slow.next_step_name("run-x")
    assert timed.value.__cause__ is None
    formatted = "".join(traceback.format_exception(timed.value))
    assert "supersecret" not in formatted
    assert "supersecret" not in repr(timed.value.args)
    empty = _write_stub(tmp_path / "empty-psql", "exit 0\n")
    blank = CordisHostClient("postgres://localhost/db", worker, psql_path=empty)
    with pytest.raises(CordisProtocolError):
        blank.next_step_name("run-x")

    failing = _write_stub(
        tmp_path / "fail-psql",
        'echo "ERROR:  42501: boom" >&2\nexit 3\n',
    )
    bad = CordisHostClient("postgres://localhost/db", worker, psql_path=failing)
    with pytest.raises(CordisSqlError) as sql_exc:
        bad.next_step_name("run-x")
    assert sql_exc.value.returncode == 3
    assert sql_exc.value.sqlstate == "42501"
    assert not hasattr(sql_exc.value, "dsn")
    assert "supersecret" not in str(sql_exc.value)

    malformed = _write_stub(tmp_path / "bad-json", "echo not-json\n")
    ugly = CordisHostClient("postgres://localhost/db", worker, psql_path=malformed)
    with pytest.raises(CordisProtocolError):
        ugly.next_step_name("run-x")

    multi = _write_stub(tmp_path / "multi-json", "printf '{}\n{}\n'\n")
    many = CordisHostClient("postgres://localhost/db", worker, psql_path=multi)
    with pytest.raises(CordisProtocolError):
        many.next_step_name("run-x")


def test_p10_public_api_inventory_and_no_new_sql_marker(pgdata: Path) -> None:
    assert set(pg_cordis_host.__all__) == PUBLIC_API
    assert not hasattr(CordisHostClient, "execute")
    assert not hasattr(CordisHostClient, "query")
    assert not list(SQL.glob("0022*"))
    _reset(pgdata)
    server = get_server(pgdata)
    assert psql(server, P10_DB, "SELECT cordis.get_schema_version();") == "p21"
    assert (
        psql(
            server,
            P10_DB,
            "SELECT COUNT(*) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cordis' AND p.proname = 'provider_idempotency_key';",
        )
        == "0"
    )


def test_p10_special_character_arguments_are_data_not_sql(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-special"
    _insert_job(server, run_id)
    slice_id = _slice(server, run_id, "fn-1")
    _issue(server, run_id, slice_id, "run", "")
    client = _client(server)
    claimed = client.claim_job(run_id)
    assert claimed is not None
    nasty = {
        "quote": "it's a trap",
        "slash": "a\\b",
        "unicode": "雪花 $tag$ SELECT 1; --",
        "newline": "line1\nDROP TABLE cordis.jobs;\nline2",
        "dollar": "$e0123$payload$e0123$",
    }
    assert client.emit_step_scoped(
        claimed.claim_token,
        run_id,
        slice_id,
        "llm",
        nasty,
        step_name="s-1",
    )
    step = client.llm_checkpoint(run_id, "s-1")
    assert step is not None
    for key, value in nasty.items():
        assert step.payload[key] == value
    assert psql(server, P10_DB, "SELECT count(*) FROM cordis.jobs;") == "1"


def test_p10_provider_key_matches_postgres_and_p05_guard(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run/密钥"
    _insert_job(server, run_id)
    a = _client(server, new_host_worker_id("alpha"))
    b = _client(server, new_host_worker_id("beta"))
    key = a.provider_idempotency_key(run_id, "s-1")
    assert key == b.provider_idempotency_key(run_id, "s-1")
    db_key = psql(
        server,
        P10_DB,
        "SELECT md5(" + _sql_str(run_id) + " || '/' || 's-1');",
    )
    assert key == db_key
    claimed = a.claim_job(run_id)
    assert claimed is not None
    psql(
        server,
        P10_DB,
        "UPDATE cordis.jobs SET attempt = 2 WHERE run_id = "
        f"{_sql_str(run_id)};",
    )
    key_after = a.provider_idempotency_key(run_id, "s-1")
    assert key_after == key
    psql(
        server,
        P10_DB,
        "CREATE SCHEMA shadow; "
        "CREATE FUNCTION shadow.md5(text) RETURNS text LANGUAGE sql IMMUTABLE "
        "AS $$ SELECT repeat('f', 32) $$; "
        "ALTER DATABASE cordis_p10 SET search_path = shadow, pg_catalog;",
    )
    shadowed = a.provider_idempotency_key(run_id, "s-1")
    assert shadowed == key
    assert shadowed != "f" * 32
    with pytest.raises(RuntimeError) as wrong:
        psql(
            server,
            P10_DB,
            "SELECT cordis.invoke_llm("
            f"{_sql_str(run_id)}, 's-1', '{{\"x\":1}}'::jsonb, "
            f"{_sql_str('0' * 32)});",
        )
    assert "p_provider_key must equal" in str(wrong.value)
    with pytest.raises(RuntimeError) as right:
        psql(
            server,
            P10_DB,
            "SELECT cordis.invoke_llm("
            f"{_sql_str(run_id)}, 's-1', '{{\"x\":1}}'::jsonb, "
            f"{_sql_str(key)});",
        )
    assert "p_provider_key must equal" not in str(right.value)


def test_p10_two_clients_share_p01_claim_fencing(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-fence"
    _insert_job(server, run_id)
    a = _client(server, new_host_worker_id("alpha"))
    b = _client(server, new_host_worker_id("beta"))
    first = a.claim_job(run_id)
    assert first is not None
    assert b.claim_job(run_id) is None
    assert a.yield_claim(first.claim_token) is True
    second = b.claim_job(run_id)
    assert second is not None
    assert second.job_id == first.job_id
    assert second.claim_token != first.claim_token
    assert second.claimed_by == b.worker_id


def test_p10_claim_transitions_preserve_boolean_fencing(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-bool"
    _insert_job(server, run_id)
    client = _client(server)
    claimed = client.claim_job(run_id)
    assert claimed is not None
    token = claimed.claim_token
    assert client.yield_claim(token) is True
    dead = uuid.uuid4()
    assert client.renew_claim(token) is False
    assert client.yield_claim(token) is False
    assert client.complete_claim(token, {"answer": "no"}) is False
    assert client.fail_claim(token, {"reason": "no"}) is False
    assert client.renew_claim(dead) is False
    snap = client.get_job(run_id)
    assert snap is not None
    assert snap.status == "PENDING"
    assert snap.claim_present is False


def test_p10_checkpoint_and_scoped_append_are_claim_fenced(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-log"
    _insert_job(server, run_id)
    slice_id = _slice(server, run_id, "fn-1")
    _issue(server, run_id, slice_id, "run", "")
    client = _client(server)
    claimed = client.claim_job(run_id)
    assert claimed is not None
    token = claimed.claim_token
    assert client.checkpoint(token, []) is True
    events = [
        CheckpointEvent(run_id, "run/yield", {"n": 1}),
        CheckpointEvent(run_id, "run/yield", {"n": 2}),
    ]
    assert client.checkpoint(token, events) is True
    kinds = psql(
        server,
        P10_DB,
        "SELECT string_agg(payload->>'n', ',' ORDER BY seq) "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)} "
        "AND kind = 'run/yield';",
    )
    assert kinds == "1,2"
    with pytest.raises(CordisInputError):
        client.emit_step_scoped(
            token,
            run_id,
            slice_id,
            "llm",
            {"p08_scope": {"slice_id": "x"}},
            step_name="s-1",
        )
    assert client.emit_step_scoped(
        token, run_id, slice_id, "llm", {"raw": {"ok": True}}, step_name="s-1"
    )
    scoped = psql(
        server,
        P10_DB,
        "SELECT payload ? 'p08_scope' FROM cordis.agent_steps "
        f"WHERE run_id = {_sql_str(run_id)} AND kind = 'llm';",
    )
    assert scoped == "t"
    assert client.yield_claim(token) is True
    assert client.checkpoint(token, events) is False
    assert (
        client.emit_step_scoped(
            token, run_id, slice_id, "llm", {"raw": {"x": 1}}, step_name="s-2"
        )
        is False
    )
    assert (
        psql(
            server,
            P10_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)} AND step_name = 's-2';",
        )
        == "0"
    )


def test_p10_next_step_and_llm_checkpoint_support_skip_if_present(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-resume"
    _insert_job(server, run_id)
    slice_id = _slice(server, run_id, "fn-1")
    _issue(server, run_id, slice_id, "run", "")
    client = _client(server)
    assert client.next_step_name(run_id) == "s-1"
    assert client.llm_checkpoint(run_id, "s-1") is None
    claimed = client.claim_job(run_id)
    assert claimed is not None
    assert client.emit_step_scoped(
        claimed.claim_token,
        run_id,
        slice_id,
        "llm",
        {"raw": {"a": 1}},
        step_name="s-1",
    )
    found = client.llm_checkpoint(run_id, "s-1")
    assert isinstance(found, AgentStep)
    assert found.step_name == "s-1"
    assert client.next_step_name(run_id) == "s-1"
    with pytest.raises(CordisSqlError) as dup:
        client.emit_step_scoped(
            claimed.claim_token,
            run_id,
            slice_id,
            "llm",
            {"raw": {"a": 2}},
            step_name="s-1",
        )
    assert dup.value.sqlstate in {"23505", None} or "23505" in str(dup.value)
    assert client.emit_step_scoped(
        claimed.claim_token,
        run_id,
        slice_id,
        "tool",
        {"raw": {"a": 1}},
        step_name="s-1",
    )
    assert client.next_step_name(run_id) == "s-2"


def test_p10_host_process_claims_and_appends_one_scoped_step(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-proof"
    _insert_job(server, run_id)
    s1 = _slice(server, run_id, "fn-1")
    s2 = _slice(server, run_id, "fn-2")
    _issue(server, run_id, s1, "run", "")
    a = _client(server, new_host_worker_id("p10proof"))
    b = _client(server, new_host_worker_id("p10proof"))
    claimed = a.claim_job(run_id)
    assert claimed is not None
    assert a.next_step_name(run_id) == "s-1"
    assert a.llm_checkpoint(run_id, "s-1") is None
    key = a.provider_idempotency_key(run_id, "s-1")
    payload = {
        "protocol": "cordis.p10.host.proof.v1",
        "provider_key": key,
        "model": "host-mock",
        "raw": {"action": "final", "answer": "ok"},
    }
    assert a.emit_step_scoped(
        claimed.claim_token, run_id, s1, "llm", payload, step_name="s-1"
    )
    folded = a.fold_slice_messages(run_id, s1, "codeact")
    hist = json.dumps(folded.get("history"))
    assert "cordis.p10.host.proof.v1" in hist
    with pytest.raises(CordisSqlError) as denied:
        a.fold_slice_messages(run_id, s2, "codeact")
    assert denied.value.sqlstate == "42501" or "P08_FOLD_RUN_GRANT_REQUIRED" in str(
        denied.value
    )
    assert a.yield_claim(claimed.claim_token) is True
    second = b.claim_job(run_id)
    assert second is not None
    assert second.job_id == claimed.job_id
    assert second.claim_token != claimed.claim_token
    assert second.claimed_by == b.worker_id
    assert b.yield_claim(second.claim_token) is True


def test_p10_await_event_immediate_and_suspend_paths(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-wait"
    _insert_job(server, run_id)
    client = _client(server)
    claimed = client.claim_job(run_id)
    assert claimed is not None
    scope = str(uuid.uuid4())
    psql(
        server,
        P10_DB,
        "SELECT * FROM cordis.emit_event("
        f"{_sql_str(scope)}, 'ready', '{{\"v\":1}}'::jsonb);",
    )
    immediate = client.await_event(
        claimed.claim_token,
        run_id,
        scope,
        "ready",
        uuid.uuid4(),
        deadline=datetime.now(timezone.utc),
        ui_metadata={"prompt": "ok"},
    )
    assert isinstance(immediate, AwaitEventResult)
    assert immediate.accepted is True
    assert immediate.should_suspend is False
    assert immediate.payload == {"v": 1}
    snap = client.get_job(run_id)
    assert snap is not None
    assert snap.status == "RUNNING"

    run_b = "run-wait-2"
    _insert_job(server, run_b)
    other = _client(server)
    live = other.claim_job(run_b)
    assert live is not None
    missing_scope = str(uuid.uuid4())
    suspended = other.await_event(
        live.claim_token,
        run_b,
        missing_scope,
        "ready",
        uuid.uuid4(),
    )
    assert suspended.accepted is True
    assert suspended.should_suspend is True
    after = other.get_job(run_b)
    assert after is not None
    assert after.status == "WAITING"
    assert after.claim_present is False
    lost = other.await_event(
        live.claim_token,
        run_b,
        missing_scope,
        "ready",
        uuid.uuid4(),
    )
    assert lost.accepted is False


def test_p10_sleep_is_typed_but_unavailable_without_p04(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-sleep"
    _insert_job(server, run_id)
    client = _client(server)
    claimed = client.claim_job(run_id)
    assert claimed is not None
    until = datetime.now(timezone.utc)
    with pytest.raises(CordisFeatureUnavailable) as exc:
        client.sleep_claim(claimed.claim_token, run_id, until)
    assert exc.value.code == "P10_SLEEP_UNAVAILABLE"
    snap = client.get_job(run_id)
    assert snap is not None
    assert snap.status == "RUNNING"
    psql(
        server,
        P10_DB,
        "CREATE FUNCTION cordis.sleep_claim("
        "p_claim_token uuid, p_run_id text, p_until timestamptz, p_extend integer) "
        "RETURNS boolean LANGUAGE sql AS $$ SELECT true $$;",
    )
    assert client.sleep_claim(claimed.claim_token, run_id, until) is True
    assert (
        psql(
            server,
            P10_DB,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)};",
        )
        == "0"
    )
    src = (REPO / "pg_cordis_host" / "client.py").read_text(encoding="utf-8")
    assert ".p19-backup" not in src
    assert "0004_p04" not in src


def test_p10_catalog_registration_lookup_and_unregister(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    client = _client(server)
    identity = client.register_host_plugin(READONLY_HOST)
    assert identity == "host.p10.lookup"
    row = client.get_plugin(identity)
    assert isinstance(row, PluginCatalogEntry)
    assert row.locus == "host"
    assert row.invocation == "host_tool"
    assert row.entrypoint is None
    assert row.source_kind == "host_registration"
    assert row.effect_class == "read_only"
    assert client.unregister_host_plugin(identity) is True
    assert client.get_plugin(identity) is None
    assert client.unregister_host_plugin(identity) is False


def test_p10_authorize_host_tool_is_read_only_and_non_executing(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-auth"
    _insert_job(server, run_id)
    _register_corpus(server, "project-1", "Project 1")
    slice_id = _slice(server, run_id, "fn-1")
    _issue(server, run_id, slice_id, "run", "")
    _issue(server, run_id, slice_id, "named_corpus", "project-1")
    client = _client(server)
    client.register_host_plugin(READONLY_HOST)
    client.register_host_plugin(EXTERNAL_HOST)
    psql(
        server,
        P10_DB,
        "CREATE FUNCTION cordis.p10_session_lookup(p jsonb) RETURNS jsonb "
        "LANGUAGE sql STABLE SET search_path TO pg_catalog AS $$ SELECT p $$; "
        "COMMENT ON FUNCTION cordis.p10_session_lookup(jsonb) IS $cmt$"
        '{"cordis_plugin":{"identity":"cordis.p10.session","version":"0.1.0",'
        '"locus":"in-db","invocation":"session_select","effect_class":"read_only",'
        '"retry_class":"replayable","reconciliation":"none","required_grants":[]}}'
        "$cmt$; SELECT cordis.refresh_plugins();",
    )
    authorized = client.authorize_host_tool(
        run_id, slice_id, "host.p10.lookup", {"named_corpus": "project-1"}
    )
    assert isinstance(authorized, AuthorizedHostTool)
    assert authorized.entrypoint is None
    assert authorized.locus == "host"
    assert not hasattr(authorized, "callable")
    assert not hasattr(client, "execute_host_tool")
    with pytest.raises(CordisProtocolError):
        client.authorize_host_tool(run_id, slice_id, "kernel.step_once", {})
    with pytest.raises(CordisProtocolError):
        client.authorize_host_tool(run_id, slice_id, "cordis.p10.session", {})
    with pytest.raises(CordisProtocolError):
        client.authorize_host_tool(run_id, slice_id, "host.p10.mutate", {})


def test_p10_four_seam_calls_are_slice_bound_and_not_cached(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-seams"
    _insert_job(server, run_id)
    _register_corpus(server, "project-1", "Project 1")
    _register_corpus(server, "project-2", "Project 2")
    s1 = _slice(server, run_id, "fn-1")
    s2 = _slice(server, run_id, "fn-2")
    _issue(server, run_id, s1, "run", "")
    corpus_grant = _issue(server, run_id, s1, "named_corpus", "project-1")
    _issue(server, run_id, s2, "named_corpus", "project-2")
    client = _client(server)
    client.register_host_plugin(READONLY_HOST)
    claimed = client.claim_job(run_id)
    assert claimed is not None
    assert client.emit_step_scoped(
        claimed.claim_token,
        run_id,
        s1,
        "llm",
        {"secret": "only-one"},
        step_name="s-1",
    )
    one = client.recall_named_corpus(run_id, s1, "project-1")
    assert isinstance(one, NamedCorpusRef)
    assert one.corpus_id == "project-1"
    assert client.recall_named_corpus(run_id, s1, "project-2") is None
    fold1 = client.fold_slice_messages(run_id, s1, "codeact")
    assert "only-one" in json.dumps(fold1.get("history"))
    with pytest.raises(CordisSqlError) as fold2:
        client.fold_slice_messages(run_id, s2, "codeact")
    assert "P08_FOLD_RUN_GRANT_REQUIRED" in str(fold2.value)
    with pytest.raises(CordisSqlError) as env:
        client.read_run_env(run_id, s1, "rlm", "question")
    assert env.value.sqlstate == "55000" or "P08_ENV_WORKSPACE_UNAVAILABLE" in str(
        env.value
    )
    first = client.authorize_host_tool(
        run_id, s1, "host.p10.lookup", {"named_corpus": "project-1"}
    )
    assert first.identity == "host.p10.lookup"
    psql(
        server,
        P10_DB,
        "SELECT cordis.revoke_grant("
        f"{_sql_str(str(corpus_grant))}::uuid, 'host');",
    )
    with pytest.raises(CordisSqlError):
        client.authorize_host_tool(
            run_id, s1, "host.p10.lookup", {"named_corpus": "project-1"}
        )


def test_p10_get_job_and_run_state_support_lost_response_reconciliation(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    run_id = "run-state"
    _insert_job(server, run_id)
    slice_id = _slice(server, run_id, "fn-1")
    _issue(server, run_id, slice_id, "run", "")
    client = _client(server)
    claimed = client.claim_job(run_id)
    assert claimed is not None
    snap = client.get_job(run_id)
    assert isinstance(snap, JobSnapshot)
    assert snap.claim_present is True
    assert not hasattr(snap, "claim_token")
    assert "claim_token" not in snap.__dict__
    state = client.run_state(run_id)
    assert isinstance(state, RunState)
    assert state.status == "in-progress"
    assert client.emit_step_scoped(
        claimed.claim_token,
        run_id,
        slice_id,
        "final",
        {"answer": "done"},
        step_name="s-1",
    )
    assert client.complete_claim(claimed.claim_token, {"answer": "done"}) is True
    done = client.get_job(run_id)
    assert done is not None
    assert done.status == "DONE"
    assert done.claim_present is False
    terminal = client.run_state(run_id)
    assert terminal.status == "final"
    assert terminal.answer == "done"
    assert client.get_job("missing-run") is None


def test_p10_has_no_p09_worker_or_control_plane_model_dispatch() -> None:
    text = ""
    for path in (REPO / "pg_cordis_host").glob("*.py"):
        text += path.read_text(encoding="utf-8")
    for needle in FORBIDDEN_SOURCE:
        assert needle not in text, needle


def test_p10_source_and_dependency_boundaries() -> None:
    assert not list(SQL.glob("0022*"))
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "package = false" in pyproject
    assert "psycopg" not in pyproject
    assert "asyncpg" not in pyproject
    client_src = (REPO / "pg_cordis_host" / "client.py").read_text(encoding="utf-8")
    init_src = (REPO / "pg_cordis_host" / "__init__.py").read_text(encoding="utf-8")
    combined = client_src + init_src
    assert "import pgembed" not in combined
    assert "from pgembed" not in combined
    assert "tests.conftest" not in combined
    assert "apply_pg_cordis" not in combined
    assert "scratch" not in combined
