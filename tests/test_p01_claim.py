"""P01 claim protocol tests. Apply execution stays a subprocess."""

from __future__ import annotations

from pathlib import Path

from pgembed import get_server

from tests.conftest import psql, psql_session, run_apply

P01_DB = "cordis_p01"
NAMED_CONSTRAINTS = (
    "jobs_pkey",
    "jobs_run_id_key",
    "jobs_claim_token_key",
    "jobs_status_check",
    "jobs_attempt_check",
    "jobs_claim_fields_check",
    "jobs_claimed_by_nonblank_check",
    "jobs_terminal_time_check",
)
FUNCTION_IDS = (
    "cordis.claim_job(text,text,integer)",
    "cordis.renew_claim(uuid,integer)",
    "cordis.yield_claim(uuid)",
    "cordis.complete_claim(uuid,jsonb)",
    "cordis.fail_claim(uuid,jsonb)",
    "cordis.release_stale(text,integer)",
)


def _ensure_p01(pgdata: Path) -> None:
    result = run_apply("--pgdata", str(pgdata), "--database", P01_DB)
    if result.returncode != 0:
        result = run_apply(
            "--pgdata", str(pgdata), "--database", P01_DB, "--reset"
        )
    assert result.returncode == 0, result.stdout + result.stderr


def _insert_pending(server, run_id: str, job_type: str = "p01_test") -> None:
    psql(
        server,
        P01_DB,
        "INSERT INTO cordis.jobs (run_id, job_type) "
        f"VALUES ({_sql_str(run_id)}, {_sql_str(job_type)});",
    )


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _jsonb(value: str) -> str:
    return _sql_str(value) + "::jsonb"


def test_catalog_contract(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    cols = psql(
        server,
        P01_DB,
        "SELECT attname || ':' || pg_catalog.format_type(atttypid, atttypmod) "
        "FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs' "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY a.attnum;",
    ).splitlines()
    assert "job_id:bigint" in cols
    assert "run_id:text" in cols
    assert "job_type:text" in cols
    assert "payload:jsonb" in cols
    assert "status:text" in cols
    assert "priority:integer" in cols
    assert "attempt:integer" in cols
    assert "available_at:timestamp with time zone" in cols
    assert "claim_token:uuid" in cols
    assert "claimed_by:text" in cols
    assert "claim_expires_at:timestamp with time zone" in cols
    assert "result:jsonb" in cols
    assert "error:jsonb" in cols
    assert "created_at:timestamp with time zone" in cols
    assert "completed_at:timestamp with time zone" in cols

    names = psql(
        server,
        P01_DB,
        "SELECT conname FROM pg_constraint x "
        "JOIN pg_class c ON c.oid = x.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs' "
        "ORDER BY 1;",
    ).splitlines()
    for constraint in NAMED_CONSTRAINTS:
        assert constraint in names, names

    indexes = psql(
        server,
        P01_DB,
        "SELECT indexrelid::regclass::text FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs' "
        "ORDER BY 1;",
    )
    assert "jobs_ready_idx" in indexes
    assert "jobs_stale_claim_idx" in indexes

    for identity in FUNCTION_IDS:
        found = psql(
            server,
            P01_DB,
            f"SELECT to_regprocedure({_sql_str(identity)}) IS NOT NULL;",
        )
        assert found == "t", identity

    version = psql(
        server,
        P01_DB,
        "SELECT pg_get_function_identity_arguments(p.oid) || '|' || "
        "pg_get_function_result(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname = 'get_schema_version' "
        "AND p.pronargs = 0;",
    )
    assert version == "|text"
    assert psql(server, P01_DB, "SELECT cordis.get_schema_version();") == "p06"


def test_mutual_exclusion_and_yield_reclaim(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    run_id = "p01-mutex"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};")
    _insert_pending(server, run_id)

    with psql_session(server, P01_DB) as session_a:
        session_a.execute("BEGIN")
        claimed = session_a.execute(
            f"SELECT job_id::text, run_id, claimed_by, claim_token::text, status "
            f"FROM cordis.claim_job({_sql_str(run_id)}, 'worker-a', 90)"
        )
        assert len(claimed) == 1, claimed
        job_id, _, _, token_a, status = claimed[0].split("|")
        assert status == "RUNNING"
        assert token_a

        empty = psql(
            server,
            P01_DB,
            "SET statement_timeout = '2s'; "
            f"SELECT count(*) FROM cordis.claim_job({_sql_str(run_id)}, 'worker-b', 90);",
        )
        assert empty == "0"

        session_a.commit()

        still_running = psql(
            server,
            P01_DB,
            f"SELECT count(*) FROM cordis.claim_job({_sql_str(run_id)}, 'worker-b', 90);",
        )
        assert still_running == "0"

        yielded = psql(
            server,
            P01_DB,
            f"SELECT cordis.yield_claim({_sql_str(token_a)}::uuid);",
        )
        assert yielded == "t"

    reclaimed = psql(
        server,
        P01_DB,
        f"SELECT job_id::text, run_id, claimed_by, claim_token::text, status "
        f"FROM cordis.claim_job({_sql_str(run_id)}, 'worker-b', 90);",
    ).splitlines()
    assert len(reclaimed) == 1, reclaimed
    job_id_b, run_id_b, claimed_by, token_b, status_b = reclaimed[0].split("|")
    assert job_id_b == job_id
    assert run_id_b == run_id
    assert claimed_by == "worker-b"
    assert token_b != token_a
    assert status_b == "RUNNING"


def test_renew_and_transition_fencing(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    run_id = "p01-fence"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};")
    _insert_pending(server, run_id)
    row = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text, claim_expires_at::text "
        f"FROM cordis.claim_job({_sql_str(run_id)}, 'worker-a', 90);",
    )
    token, expiry_before = row.split("|")
    renewed = psql(
        server,
        P01_DB,
        f"SELECT cordis.renew_claim({_sql_str(token)}::uuid, 90);",
    )
    assert renewed == "t"
    moved = psql(
        server,
        P01_DB,
        "SELECT claim_expires_at > "
        f"{_sql_str(expiry_before)}::timestamptz "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert moved == "t"

    missing = psql(
        server,
        P01_DB,
        "SELECT cordis.renew_claim('00000000-0000-0000-0000-000000000000'::uuid, 90);",
    )
    assert missing == "f"

    yielded = psql(
        server,
        P01_DB,
        f"SELECT cordis.yield_claim({_sql_str(token)}::uuid);",
    )
    assert yielded == "t"
    fields = psql(
        server,
        P01_DB,
        "SELECT status, claim_token IS NULL, claimed_by IS NULL, "
        "claim_expires_at IS NULL, attempt::text "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    status, token_null, by_null, exp_null, attempt = fields.split("|")
    assert status == "PENDING"
    assert token_null == "t"
    assert by_null == "t"
    assert exp_null == "t"
    assert attempt == "1"

    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.complete_claim({_sql_str(token)}::uuid, {_jsonb('{}')});",
        )
        == "f"
    )
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.fail_claim({_sql_str(token)}::uuid, {_jsonb('{\"e\":\"x\"}')});",
        )
        == "f"
    )

    complete_id = "p01-complete"
    psql(
        server,
        P01_DB,
        f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(complete_id)};",
    )
    _insert_pending(server, complete_id)
    complete_token = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(complete_id)}, 'w', 90);",
    )
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.complete_claim({_sql_str(complete_token)}::uuid, {_jsonb('{\"ok\":true}')});",
        )
        == "t"
    )
    done = psql(
        server,
        P01_DB,
        "SELECT status, result->>'ok', completed_at IS NOT NULL, claim_token IS NULL "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(complete_id)};",
    )
    assert done.split("|") == ["DONE", "true", "t", "t"]
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT count(*) FROM cordis.claim_job({_sql_str(complete_id)}, 'w2', 90);",
        )
        == "0"
    )

    fail_id = "p01-fail"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(fail_id)};")
    _insert_pending(server, fail_id)
    fail_token = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(fail_id)}, 'w', 90);",
    )
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.fail_claim({_sql_str(fail_token)}::uuid, {_jsonb('{\"reason\":\"boom\"}')});",
        )
        == "t"
    )
    failed = psql(
        server,
        P01_DB,
        "SELECT status, error->>'reason', completed_at IS NOT NULL "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(fail_id)};",
    )
    assert failed.split("|") == ["ERROR", "boom", "t"]


def test_stale_reap_and_auto_claim(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    run_id = "p01-stale"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};")
    _insert_pending(server, run_id)
    old_token = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'worker-old', 90);",
    )
    psql(
        server,
        P01_DB,
        "UPDATE cordis.jobs "
        "SET claim_expires_at = clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    reaped = psql(
        server,
        P01_DB,
        f"SELECT cordis.release_stale({_sql_str(run_id)}, 100);",
    )
    assert reaped == "1"
    row = psql(
        server,
        P01_DB,
        "SELECT status, attempt::text, claim_token IS NULL, claimed_by IS NULL, "
        "claim_expires_at IS NULL, available_at <= clock_timestamp() "
        f"FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert row.split("|") == ["PENDING", "2", "t", "t", "t", "t"]
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.renew_claim({_sql_str(old_token)}::uuid, 90);",
        )
        == "f"
    )
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.yield_claim({_sql_str(old_token)}::uuid);",
        )
        == "f"
    )
    new_token = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'worker-new', 90);",
    )
    assert new_token != old_token
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.release_stale({_sql_str(run_id)}, 100);",
        )
        == "0"
    )

    auto_id = "p01-stale-auto"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(auto_id)};")
    _insert_pending(server, auto_id)
    auto_old = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(auto_id)}, 'old', 90);",
    )
    psql(
        server,
        P01_DB,
        "UPDATE cordis.jobs "
        "SET claim_expires_at = clock_timestamp() - interval '1 second' "
        f"WHERE run_id = {_sql_str(auto_id)};",
    )
    auto_new = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text, attempt::text, claimed_by "
        f"FROM cordis.claim_job({_sql_str(auto_id)}, 'new', 90);",
    )
    token, attempt, claimed_by = auto_new.split("|")
    assert token != auto_old
    assert attempt == "2"
    assert claimed_by == "new"


def test_reserved_waiting_sleeping_not_claimed(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    for status, run_id in (("WAITING", "p01-waiting"), ("SLEEPING", "p01-sleeping")):
        psql(
            server,
            P01_DB,
            f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        psql(
            server,
            P01_DB,
            "INSERT INTO cordis.jobs (run_id, job_type, status, available_at) VALUES ("
            f"{_sql_str(run_id)}, 'p01_test', {_sql_str(status)}, '-infinity'::timestamptz);",
        )
        count = psql(
            server,
            P01_DB,
            f"SELECT count(*) FROM cordis.claim_job({_sql_str(run_id)}, 'worker', 90);",
        )
        assert count == "0"
        stayed = psql(
            server,
            P01_DB,
            f"SELECT status FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        assert stayed == status


def test_run_id_unique_including_terminal(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    run_id = "p01-unique"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};")
    _insert_pending(server, run_id)
    try:
        psql(
            server,
            P01_DB,
            "INSERT INTO cordis.jobs (run_id, job_type) "
            f"VALUES ({_sql_str(run_id)}, 'p01_test');",
        )
        raise AssertionError("duplicate run_id should fail")
    except RuntimeError as exc:
        assert "jobs_run_id_key" in str(exc)

    token = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'w', 90);",
    )
    psql(
        server,
        P01_DB,
        f"SELECT cordis.complete_claim({_sql_str(token)}::uuid, NULL);",
    )
    try:
        psql(
            server,
            P01_DB,
            "INSERT INTO cordis.jobs (run_id, job_type) "
            f"VALUES ({_sql_str(run_id)}, 'p01_test');",
        )
        raise AssertionError("terminal run_id should still occupy the unique slot")
    except RuntimeError as exc:
        assert "jobs_run_id_key" in str(exc)


def test_replay_preserves_jobs_row(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    run_id = "p01-replay"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};")
    _insert_pending(server, run_id)
    before = psql(
        server,
        P01_DB,
        f"SELECT job_id::text, run_id, payload::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    result = run_apply("--pgdata", str(pgdata), "--database", P01_DB)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode=in-place" in result.stdout
    assert psql(server, P01_DB, "SELECT cordis.get_schema_version();") == "p06"
    after = psql(
        server,
        P01_DB,
        f"SELECT job_id::text, run_id, payload::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert after == before


def _expect_param_error(server, sql: str) -> None:
    try:
        psql(server, P01_DB, sql)
    except RuntimeError as exc:
        assert "must " in str(exc), exc
        return
    raise AssertionError(f"expected parameter error for: {sql}")


def test_parameter_exceptions(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    _expect_param_error(server, "SELECT * FROM cordis.claim_job(NULL, NULL, 90);")
    _expect_param_error(
        server, "SELECT * FROM cordis.claim_job(NULL, '   ', 90);"
    )
    _expect_param_error(
        server, "SELECT * FROM cordis.claim_job('   ', 'worker', 90);"
    )
    _expect_param_error(
        server, "SELECT * FROM cordis.claim_job(NULL, 'worker', 0);"
    )
    _expect_param_error(server, "SELECT cordis.renew_claim(NULL, 0);")
    _expect_param_error(server, "SELECT cordis.release_stale(NULL, 0);")
    _expect_param_error(
        server,
        "SELECT cordis.fail_claim("
        "'00000000-0000-0000-0000-000000000000'::uuid, NULL);",
    )


def test_null_token_verbs_return_false(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    assert psql(server, P01_DB, "SELECT cordis.renew_claim(NULL, 90);") == "f"
    assert psql(server, P01_DB, "SELECT cordis.yield_claim(NULL);") == "f"
    assert (
        psql(server, P01_DB, "SELECT cordis.complete_claim(NULL, NULL);") == "f"
    )
    assert (
        psql(
            server,
            P01_DB,
            f"SELECT cordis.fail_claim(NULL, {_jsonb('{}')});",
        )
        == "f"
    )


def test_stale_reap_respects_limit(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    psql(
        server,
        P01_DB,
        "DELETE FROM cordis.jobs WHERE run_id LIKE 'p01-limit-%';",
    )
    for i in range(3):
        run_id = f"p01-limit-{i}"
        _insert_pending(server, run_id)
        psql(
            server,
            P01_DB,
            f"SELECT cordis.claim_job({_sql_str(run_id)}, 'w', 90);",
        )
    psql(
        server,
        P01_DB,
        "UPDATE cordis.jobs "
        "SET claim_expires_at = clock_timestamp() - interval '1 second' "
        "WHERE run_id LIKE 'p01-limit-%';",
    )
    first = psql(server, P01_DB, "SELECT cordis.release_stale(NULL, 1);")
    assert first == "1"
    remaining = psql(
        server,
        P01_DB,
        "SELECT count(*) FROM cordis.jobs "
        "WHERE run_id LIKE 'p01-limit-%' AND status = 'RUNNING';",
    )
    assert remaining == "2"
    second = psql(server, P01_DB, "SELECT cordis.release_stale(NULL, 1);")
    assert second == "1"


def test_unknown_status_rejected_and_six_statuses_accepted(
    pgdata: Path,
) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    try:
        psql(
            server,
            P01_DB,
            "INSERT INTO cordis.jobs (run_id, job_type, status) "
            "VALUES ('p01-bad-status', 'p01_test', 'CANCELLED');",
        )
        raise AssertionError("unknown status should fail")
    except RuntimeError as exc:
        assert "jobs_status_check" in str(exc)
    for status, run_id in (
        ("PENDING", "p01-st-pending"),
        ("WAITING", "p01-st-waiting"),
        ("SLEEPING", "p01-st-sleeping"),
        ("DONE", "p01-st-done"),
        ("ERROR", "p01-st-error"),
    ):
        psql(
            server,
            P01_DB,
            f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
        )
        completed = (
            "clock_timestamp()"
            if status in ("DONE", "ERROR")
            else "NULL"
        )
        psql(
            server,
            P01_DB,
            "INSERT INTO cordis.jobs (run_id, job_type, status, completed_at) "
            f"VALUES ({_sql_str(run_id)}, 'p01_test', {_sql_str(status)}, {completed});",
        )


def test_catalog_defaults_identity_and_index_predicates(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    identity = psql(
        server,
        P01_DB,
        "SELECT a.attidentity FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs' "
        "AND a.attname = 'job_id';",
    )
    assert identity == "d"
    ready = psql(
        server,
        P01_DB,
        "SELECT pg_get_indexdef(c.oid) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs_ready_idx';",
    )
    assert "status = 'PENDING'" in ready
    assert "priority DESC" in ready
    stale = psql(
        server,
        P01_DB,
        "SELECT pg_get_indexdef(c.oid) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs_stale_claim_idx';",
    )
    assert "status = 'RUNNING'" in stale
    assert "claim_expires_at" in stale
    payload_default = psql(
        server,
        P01_DB,
        "SELECT pg_get_expr(ad.adbin, ad.adrelid) FROM pg_attrdef ad "
        "JOIN pg_attribute a ON a.attrelid = ad.adrelid AND a.attnum = ad.adnum "
        "JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'jobs' AND a.attname = 'payload';",
    )
    assert "'{}'" in payload_default or "jsonb" in payload_default


def test_fenced_against_search_path_clock_shadow(pgdata: Path) -> None:
    _ensure_p01(pgdata)
    server = get_server(pgdata)
    run_id = "p01-shadow-clock"
    psql(server, P01_DB, f"DELETE FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};")
    _insert_pending(server, run_id)
    token = psql(
        server,
        P01_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'w', 90);",
    )
    psql(
        server,
        P01_DB,
        "CREATE SCHEMA IF NOT EXISTS p01_shadow; "
        "CREATE OR REPLACE FUNCTION p01_shadow.clock_timestamp() "
        "RETURNS timestamptz LANGUAGE sql IMMUTABLE AS "
        "$$ SELECT TIMESTAMPTZ '2999-01-01 00:00:00+00' $$;",
    )
    yielded = psql(
        server,
        P01_DB,
        "SET search_path TO p01_shadow, pg_catalog; "
        f"SELECT cordis.yield_claim({_sql_str(token)}::uuid);",
    )
    assert yielded == "t"
