"""P11 dual-worker alternating claim proof. Apply stays a subprocess."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH, get_server

from pg_cordis_host import CordisHostClient, new_host_worker_id
from tests.conftest import psql, run_apply

P11_DB = "cordis_p11"
RUN_ID = "p11-proof"
IN_DB_WORKER_ID = "in-db:p11:worker-a"
HOST_INSTANCE = uuid.UUID(hex="0123456789abcdef0123456789abcdef")
HOST_WORKER_ID = new_host_worker_id("p11proof", HOST_INSTANCE)
HOST_WORKER_RE = re.compile(
    r"^host:([a-z][a-z0-9_-]{0,63}):([0-9a-f]{32})$"
)
P11_PROTOCOL = "cordis.p11.alternating_claim.v1"
P11_PAYLOAD = {
    "input": {"question": "p11 proof"},
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


def _reset(pgdata: Path):
    result = run_apply(
        "--pgdata", str(pgdata), "--database", P11_DB, "--reset"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _client(server) -> CordisHostClient:
    return CordisHostClient(
        server.get_uri(P11_DB),
        HOST_WORKER_ID,
        psql_path=POSTGRES_BIN_PATH / "psql",
    )


def _enqueue(server, run_id: str, payload: object) -> int:
    return int(
        psql(
            server,
            P11_DB,
            "SELECT cordis.enqueue_job("
            f"{_sql_str(run_id)}, 'kernel.step_once', 'codeact', "
            f"{_jsonb(payload)}, 0)::text;",
        )
    )


def _create_slice_and_issue_run_grant(server, run_id: str) -> uuid.UUID:
    slice_id = uuid.UUID(
        psql(
            server,
            P11_DB,
            "SELECT cordis.create_slice("
            f"{_sql_str(run_id)}, 'p11-host', 'host');",
        )
    )
    psql(
        server,
        P11_DB,
        "SELECT cordis.issue_grant("
        f"{_sql_str(run_id)}, {_sql_str(str(slice_id))}::uuid, "
        "'run', '', 'host');",
    )
    return slice_id


def _worker_step(
    server, worker: str, run_id: str, lease: int = 90
) -> dict:
    raw = psql(
        server,
        P11_DB,
        "SELECT pg_catalog.jsonb_build_object("
        "'job_id', job_id, 'run_id', run_id, 'outcome', outcome) "
        "FROM cordis.worker_step("
        f"{_sql_str(worker)}, {_sql_str(run_id)}, {lease});",
    )
    assert raw not in ("", "null"), raw
    return json.loads(raw)


def _raw_claim(
    server, worker: str, run_id: str, lease: int = 90
) -> dict | None:
    raw = psql(
        server,
        P11_DB,
        "SELECT COALESCE("
        "(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object("
        "'job_id', j.job_id, "
        "'run_id', j.run_id, "
        "'attempt', j.attempt, "
        "'token', j.claim_token, "
        "'claimed_by', j.claimed_by, "
        "'status', j.status"
        ")) FROM cordis.claim_job("
        f"{_sql_str(run_id)}, {_sql_str(worker)}, {lease}) AS j), "
        "'[]'::pg_catalog.jsonb);",
    )
    rows = json.loads(raw)
    assert len(rows) <= 1, rows
    if not rows:
        return None
    row = rows[0]
    return {
        "job_id": row["job_id"],
        "run_id": row["run_id"],
        "attempt": row["attempt"],
        "token": uuid.UUID(row["token"]),
        "claimed_by": row["claimed_by"],
        "status": row["status"],
    }


def _raw_yield(server, token: uuid.UUID) -> bool:
    out = psql(
        server,
        P11_DB,
        f"SELECT cordis.yield_claim({_sql_str(str(token))}::uuid);",
    )
    assert out in {"t", "f"}, out
    return out == "t"


def _expire_exact_claim(server, run_id: str, token: uuid.UUID) -> None:
    updated = psql(
        server,
        P11_DB,
        "WITH u AS ("
        "UPDATE cordis.jobs "
        "SET claim_expires_at = clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(run_id)} "
        f"AND claim_token = {_sql_str(str(token))}::uuid "
        "RETURNING job_id"
        ") SELECT count(*)::text FROM u;",
    )
    assert updated == "1", updated


def _job_snapshot(server, run_id: str) -> dict:
    raw = psql(
        server,
        P11_DB,
        "SELECT COALESCE("
        "(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object("
        "'job_id', job_id, "
        "'run_id', run_id, "
        "'job_type', job_type, "
        "'status', status, "
        "'attempt', attempt, "
        "'paradigm', payload->>'paradigm', "
        "'claim_token', claim_token, "
        "'claimed_by', claimed_by, "
        "'claim_expires_at', claim_expires_at, "
        "'result', result, "
        "'error', error, "
        "'completed_at', completed_at"
        f")) FROM cordis.jobs WHERE run_id = {_sql_str(run_id)}), "
        "'[]'::pg_catalog.jsonb);",
    )
    rows = json.loads(raw)
    assert len(rows) == 1, rows
    return rows[0]


def _log_rows(server, run_id: str) -> list[dict]:
    raw = psql(
        server,
        P11_DB,
        "SELECT COALESCE("
        "(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object("
        "'kind', kind, 'step_name', step_name, 'payload', payload) "
        f"ORDER BY seq) FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)}), "
        "'[]'::pg_catalog.jsonb);",
    )
    rows = json.loads(raw)
    assert isinstance(rows, list), rows
    return rows


def _next_step_name(server, run_id: str) -> str:
    return psql(
        server,
        P11_DB,
        f"SELECT cordis.next_step_name({_sql_str(run_id)});",
    )


def _jobs_count(server, run_id: str | None = None) -> int:
    if run_id is None:
        sql = "SELECT count(*) FROM cordis.jobs;"
    else:
        sql = (
            "SELECT count(*) FROM cordis.jobs "
            f"WHERE run_id = {_sql_str(run_id)};"
        )
    return int(psql(server, P11_DB, sql))


def _kind_names(rows: list[dict]) -> list[tuple[str, str | None]]:
    return [(row["kind"], row["step_name"]) for row in rows]


def _remember(seen: set[uuid.UUID], token: uuid.UUID) -> uuid.UUID:
    assert token not in seen, token
    seen.add(token)
    return token


def _assert_pending(job: dict, job_id: int, attempt: int) -> None:
    assert job["job_id"] == job_id
    assert job["run_id"] == RUN_ID
    assert job["status"] == "PENDING"
    assert job["attempt"] == attempt
    assert job["claim_token"] is None
    assert job["claimed_by"] is None
    assert job["claim_expires_at"] is None


def test_p11_in_db_host_in_db_alternation_and_bidirectional_stale_takeover(
    pgdata: Path,
) -> None:
    result = _reset(pgdata)
    assert "0004_p04_sleep_retry.sql" in result.stdout
    assert "0021_p09_in_db_worker.sql" in result.stdout
    server = get_server(pgdata)
    assert psql(server, P11_DB, "SELECT cordis.get_schema_version();") == "p21"

    assert HOST_WORKER_ID == (
        "host:p11proof:0123456789abcdef0123456789abcdef"
    )
    assert HOST_WORKER_RE.fullmatch(HOST_WORKER_ID)
    host_client = _client(server)
    assert host_client.worker_id == HOST_WORKER_ID
    assert HOST_WORKER_RE.fullmatch(host_client.worker_id)

    job_id = _enqueue(server, RUN_ID, P11_PAYLOAD)
    psql(
        server,
        P11_DB,
        "UPDATE cordis.jobs SET retry_backoff_base_seconds = 0, "
        "retry_backoff_max_seconds = 0 "
        f"WHERE run_id = {_sql_str(RUN_ID)};",
    )
    job = _job_snapshot(server, RUN_ID)
    assert job["job_id"] == job_id
    assert job["job_type"] == "kernel.step_once"
    assert job["paradigm"] == "codeact"
    _assert_pending(job, job_id, 1)

    slice_id = _create_slice_and_issue_run_grant(server, RUN_ID)
    assert (
        psql(
            server,
            P11_DB,
            "SELECT cordis.slice_has_grant("
            f"{_sql_str(RUN_ID)}, {_sql_str(str(slice_id))}::uuid, "
            "'run', '');",
        )
        == "t"
    )

    seen_tokens: set[uuid.UUID] = set()

    step1 = _worker_step(server, IN_DB_WORKER_ID, RUN_ID)
    assert step1 == {"job_id": job_id, "run_id": RUN_ID, "outcome": "yield"}, step1
    _assert_pending(_job_snapshot(server, RUN_ID), job_id, 1)
    logs = _log_rows(server, RUN_ID)
    assert _kind_names(logs) == [("llm", "s-1"), ("tool", "s-1")]
    assert _next_step_name(server, RUN_ID) == "s-2"
    assert _jobs_count(server) == 1

    claimed = host_client.claim_job(RUN_ID)
    assert claimed is not None
    host_step_token = _remember(seen_tokens, claimed.claim_token)
    assert claimed.job_id == job_id
    assert claimed.run_id == RUN_ID
    assert claimed.status == "RUNNING"
    assert claimed.attempt == 1
    assert claimed.claimed_by == host_client.worker_id
    assert host_client.next_step_name(RUN_ID) == "s-2"
    assert host_client.llm_checkpoint(RUN_ID, "s-2") is None
    provider_key = host_client.provider_idempotency_key(RUN_ID, "s-2")
    assert re.fullmatch(r"[0-9a-f]{32}", provider_key)
    db_key = psql(
        server,
        P11_DB,
        f"SELECT md5({_sql_str(RUN_ID)} || '/' || 's-2');",
    )
    assert provider_key == db_key

    host_payload = {
        "protocol": P11_PROTOCOL,
        "locus": "host",
        "worker_id": HOST_WORKER_ID,
        "action": "checkpoint_then_yield",
        "logical_step_name": "s-2",
        "provider_key": provider_key,
    }
    assert host_client.emit_step_scoped(
        host_step_token,
        RUN_ID,
        slice_id,
        "run/yield",
        host_payload,
        step_name=None,
        corpus_ids=(),
    )
    logs = _log_rows(server, RUN_ID)
    assert _kind_names(logs) == [
        ("llm", "s-1"),
        ("tool", "s-1"),
        ("run/yield", None),
    ]
    proof = logs[2]
    assert proof["kind"] == "run/yield"
    assert proof["step_name"] is None
    stored = proof["payload"]
    assert stored["protocol"] == P11_PROTOCOL
    assert stored["locus"] == "host"
    assert stored["worker_id"] == HOST_WORKER_ID
    assert stored["action"] == "checkpoint_then_yield"
    assert stored["logical_step_name"] == "s-2"
    assert stored["provider_key"] == provider_key
    assert stored["p08_scope"] == {
        "slice_id": str(slice_id),
        "named_corpora": [],
    }
    assert set(stored) == {
        "protocol",
        "locus",
        "worker_id",
        "action",
        "logical_step_name",
        "provider_key",
        "p08_scope",
    }
    assert host_client.next_step_name(RUN_ID) == "s-2"
    assert host_client.yield_claim(host_step_token) is True
    _assert_pending(_job_snapshot(server, RUN_ID), job_id, 1)

    step2 = _worker_step(server, IN_DB_WORKER_ID, RUN_ID)
    assert step2 == {"job_id": job_id, "run_id": RUN_ID, "outcome": "yield"}, step2
    _assert_pending(_job_snapshot(server, RUN_ID), job_id, 1)
    assert _next_step_name(server, RUN_ID) == "s-3"
    logs = _log_rows(server, RUN_ID)
    expected_log = [
        ("llm", "s-1"),
        ("tool", "s-1"),
        ("run/yield", None),
        ("llm", "s-2"),
        ("tool", "s-2"),
    ]
    assert _kind_names(logs) == expected_log
    assert not any(kind in {"final", "error"} for kind, _ in _kind_names(logs))
    assert _jobs_count(server, RUN_ID) == 1

    host_live = host_client.claim_job(RUN_ID)
    assert host_live is not None
    host_live_token = _remember(seen_tokens, host_live.claim_token)
    assert host_live.job_id == job_id
    assert host_live.attempt == 1
    assert host_live.status == "RUNNING"
    assert host_live.claimed_by == host_client.worker_id
    assert _raw_claim(server, IN_DB_WORKER_ID, RUN_ID) is None
    _expire_exact_claim(server, RUN_ID, host_live_token)
    db_takeover = _raw_claim(server, IN_DB_WORKER_ID, RUN_ID)
    assert db_takeover is not None, db_takeover
    db_takeover_token = _remember(seen_tokens, db_takeover["token"])
    assert db_takeover["job_id"] == job_id
    assert db_takeover["run_id"] == RUN_ID
    assert db_takeover["attempt"] == 2
    assert db_takeover["status"] == "RUNNING"
    assert db_takeover["claimed_by"] == IN_DB_WORKER_ID
    assert host_client.yield_claim(host_live_token) is False
    assert _raw_yield(server, db_takeover_token) is True
    _assert_pending(_job_snapshot(server, RUN_ID), job_id, 2)
    logs = _log_rows(server, RUN_ID)
    first_takeover_log = expected_log + [("run/claim_timeout", None)]
    assert _kind_names(logs) == first_takeover_log
    first_timeout = logs[-1]["payload"]
    assert first_timeout["outcome"] == "retry"
    assert first_timeout["failed_attempt"] == 1
    assert first_timeout["next_attempt"] == 2
    assert first_timeout["delay_seconds"] == 0
    assert _jobs_count(server) == 1

    db_live = _raw_claim(server, IN_DB_WORKER_ID, RUN_ID)
    assert db_live is not None, db_live
    db_live_token = _remember(seen_tokens, db_live["token"])
    assert db_live["job_id"] == job_id
    assert db_live["attempt"] == 2
    assert db_live["status"] == "RUNNING"
    assert db_live["claimed_by"] == IN_DB_WORKER_ID
    assert host_client.claim_job(RUN_ID) is None
    _expire_exact_claim(server, RUN_ID, db_live_token)
    host_takeover = host_client.claim_job(RUN_ID)
    assert host_takeover is not None
    host_takeover_token = _remember(seen_tokens, host_takeover.claim_token)
    assert host_takeover.job_id == job_id
    assert host_takeover.run_id == RUN_ID
    assert host_takeover.attempt == 3
    assert host_takeover.status == "RUNNING"
    assert host_takeover.claimed_by == host_client.worker_id
    assert _raw_yield(server, db_live_token) is False
    assert host_client.yield_claim(host_takeover_token) is True

    final = _job_snapshot(server, RUN_ID)
    _assert_pending(final, job_id, 3)
    assert final["result"] is None
    assert final["error"] is None
    assert final["completed_at"] is None
    assert _jobs_count(server, RUN_ID) == 1
    assert _jobs_count(server) == 1
    logs = _log_rows(server, RUN_ID)
    final_log = first_takeover_log + [("run/claim_timeout", None)]
    assert _kind_names(logs) == final_log
    second_timeout = logs[-1]["payload"]
    assert second_timeout["outcome"] == "retry"
    assert second_timeout["failed_attempt"] == 2
    assert second_timeout["next_attempt"] == 3
    assert second_timeout["delay_seconds"] == 0
    assert not any(
        kind in {"run/sleep", "run/wake", "final", "error"}
        for kind, _ in _kind_names(logs)
    )
    assert _next_step_name(server, RUN_ID) == "s-3"
    assert len(seen_tokens) == 5
