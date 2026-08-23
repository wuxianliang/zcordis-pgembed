"""P02 agent_steps log and checkpoint⊂log tests. Apply stays a subprocess."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from pgembed import get_server

from tests.conftest import SQL, load_apply_module, psql, run_apply

P02_DB = "cordis_p02"
P02_ONLY_DB = "cordis_p02_only"
FUNCTION_IDS = (
    "cordis.emit_step(text, text, jsonb, text)",
    "cordis.emit_step_claimed(uuid, text, text, jsonb, text, integer)",
    "cordis.checkpoint(uuid, jsonb, integer)",
    "cordis.next_step_name(text)",
    "cordis.llm_checkpoint(text, text)",
    "cordis.run_state(text)",
)
WRITERS = {
    "cordis.emit_step(text, text, jsonb, text)",
    "cordis.emit_step_claimed(uuid, text, text, jsonb, text, integer)",
    "cordis.checkpoint(uuid, jsonb, integer)",
}
NAMED_CHECKS = (
    "agent_steps_run_id_check",
    "agent_steps_kind_check",
    "agent_steps_step_name_format_check",
    "agent_steps_step_name_presence_check",
)
KINDS = (
    "llm",
    "tool",
    "final",
    "error",
    "run/claim_timeout",
    "run/await",
    "run/sleep",
    "run/wake",
    "run/yield",
    "spawn/start",
    "spawn/end",
    "event/emit",
)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _jsonb(value: str) -> str:
    return _sql_str(value) + "::jsonb"


def _ensure_full(pgdata: Path) -> None:
    result = run_apply("--pgdata", str(pgdata), "--database", P02_DB)
    if result.returncode != 0:
        result = run_apply(
            "--pgdata", str(pgdata), "--database", P02_DB, "--reset"
        )
    assert result.returncode == 0, result.stdout + result.stderr


def _apply_p02_only(pgdata: Path, tmp_path: Path) -> str:
    tree = tmp_path / "sql_p02_only"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir()
    shutil.copy(SQL / "0000_kernel.sql", tree / "0000_kernel.sql")
    shutil.copy(SQL / "0002_p02_log.sql", tree / "0002_p02_log.sql")
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P02_ONLY_DB,
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def _count(server, database: str, run_id: str) -> int:
    return int(
        psql(
            server,
            database,
            "SELECT count(*) FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)};",
        )
    )


def _run_state(server, database: str, run_id: str) -> list[str]:
    return psql(
        server,
        database,
        "SELECT status || ',' || steps_used::text || ',' || "
        "coalesce(answer, '') || ',' || coalesce(error, '') "
        f"FROM cordis.run_state({_sql_str(run_id)});",
    ).split(",", 3)


def test_p02_fresh_apply_catalog_and_version(pgdata: Path, tmp_path: Path) -> None:
    out = _apply_p02_only(pgdata, tmp_path)
    assert "files=0000_kernel.sql,0002_p02_log.sql" in out
    server = get_server(pgdata)
    assert psql(server, P02_ONLY_DB, "SELECT cordis.get_schema_version();") == "p02"
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_namespace WHERE nspname = 'cordis';",
        )
        == "1"
    )
    for rel in ("jobs", "agent_runs", "run_waits", "run_events"):
        assert (
            psql(
                server,
                P02_ONLY_DB,
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                f"WHERE n.nspname = 'cordis' AND c.relname = '{rel}';",
            )
            == "0"
        )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps';",
        )
        == "1"
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'agent_steps';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_extension WHERE extname = 'pg_cordis';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_namespace WHERE nspname = 'absurd';",
        )
        == "0"
    )

    cols = psql(
        server,
        P02_ONLY_DB,
        "SELECT attname || ':' || pg_catalog.format_type(atttypid, atttypmod) "
        "|| ':' || attnotnull::text "
        "FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps' "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY a.attnum;",
    ).splitlines()
    assert cols == [
        "run_id:text:true",
        "seq:bigint:true",
        "kind:text:true",
        "payload:jsonb:true",
        "step_name:text:false",
        "created_at:timestamp with time zone:true",
    ]
    pk = psql(
        server,
        P02_ONLY_DB,
        "SELECT string_agg(a.attname, ',' ORDER BY x.n) "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN unnest(i.indkey) WITH ORDINALITY AS x(attnum, n) ON true "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = x.attnum "
        "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps' AND i.indisprimary;",
    )
    assert pk == "run_id,seq"
    checks = psql(
        server,
        P02_ONLY_DB,
        "SELECT conname FROM pg_constraint con "
        "JOIN pg_class c ON c.oid = con.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps' "
        "AND con.contype = 'c' ORDER BY 1;",
    ).splitlines()
    assert checks == sorted(NAMED_CHECKS)
    idx = psql(
        server,
        P02_ONLY_DB,
        "SELECT indexrelid::regclass::text || ':' || indisunique::text || ':' || "
        "pg_get_indexdef(indexrelid) "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps' "
        "AND NOT i.indisprimary;",
    )
    assert "agent_steps_llm_step_idx" in idx
    assert "UNIQUE" in idx.upper()
    assert "kind" in idx and "llm" in idx
    def_map = {}
    for line in psql(
        server,
        P02_ONLY_DB,
        "SELECT conname || E'\t' || pg_get_constraintdef(con.oid) "
        "FROM pg_constraint con "
        "JOIN pg_class c ON c.oid = con.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps' "
        "AND con.contype = 'c' ORDER BY 1;",
    ).splitlines():
        name, body = line.split("\t", 1)
        def_map[name] = body
    assert set(def_map) == set(NAMED_CHECKS)
    assert "btrim" in def_map["agent_steps_run_id_check"]
    kind_vals = set(re.findall(r"'([^']+)'", def_map["agent_steps_kind_check"]))
    assert kind_vals == set(KINDS)
    assert "s-[1-9][0-9]*" in def_map["agent_steps_step_name_format_check"]
    assert "llm" in def_map["agent_steps_step_name_presence_check"]
    assert "tool" in def_map["agent_steps_step_name_presence_check"]
    seqdef = psql(
        server,
        P02_ONLY_DB,
        "SELECT pg_get_expr(adbin, adrelid) FROM pg_attrdef d "
        "JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps' AND a.attname = 'seq';",
    )
    assert "nextval" in seqdef
    created_def = psql(
        server,
        P02_ONLY_DB,
        "SELECT pg_get_expr(adbin, adrelid) FROM pg_attrdef d "
        "JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
        "JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps' "
        "AND a.attname = 'created_at';",
    )
    assert "clock_timestamp" in created_def
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relkind = 'r' AND c.relname LIKE 'c_%';",
        )
        == "0"
    )
    ids = psql(
        server,
        P02_ONLY_DB,
        "SELECT n.nspname || '.' || p.proname || '(' || "
        "pg_catalog.oidvectortypes(p.proargtypes) || ')' "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cordis' AND p.proname IN "
        "('emit_step','emit_step_claimed','checkpoint',"
        "'next_step_name','llm_checkpoint','run_state') "
        "ORDER BY 1;",
    ).splitlines()
    assert ids == sorted(FUNCTION_IDS)
    vol = dict(
        line.split(":", 1)
        for line in psql(
            server,
            P02_ONLY_DB,
            "SELECT n.nspname || '.' || p.proname || '(' || "
            "pg_catalog.oidvectortypes(p.proargtypes) || '):' || "
            "p.provolatile::text || ':' || p.prosecdef::text "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cordis' AND p.proname IN "
            "('emit_step','emit_step_claimed','checkpoint',"
            "'next_step_name','llm_checkpoint','run_state');",
        ).splitlines()
    )
    for ident in FUNCTION_IDS:
        volatile, security_definer = vol[ident].split(":")
        assert security_definer == "false"
        if ident in WRITERS:
            assert volatile == "v"
        else:
            assert volatile == "s"


def test_p02_emit_step_and_replay(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-run-basic"
    seq = psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', "
        f"{_jsonb('{\"raw\":\"hi\"}')}, 's-1');",
    )
    assert int(seq) >= 1
    row = psql(
        server,
        P02_DB,
        "SELECT run_id || '|' || kind || '|' || step_name || '|' || (payload->>'raw') "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
    )
    assert row == "p02-run-basic|llm|s-1|hi"
    created = psql(
        server,
        P02_DB,
        f"SELECT created_at::text FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
    )
    replay = run_apply("--pgdata", str(pgdata), "--database", P02_DB)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert psql(server, P02_DB, "SELECT cordis.get_schema_version();") == "p02"
    assert (
        psql(
            server,
            P02_DB,
            f"SELECT seq::text || '|' || created_at::text FROM cordis.agent_steps "
            f"WHERE run_id = {_sql_str(run_id)};",
        )
        == f"{seq}|{created}"
    )


def test_p02_three_step_history_and_run_state(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-three"
    empty = _run_state(server, P02_DB, run_id)
    assert empty[0] == "in-progress" and empty[1] == "0"
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-1"
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{\"raw\":\"1\"}')}, 's-1');",
    )
    st = _run_state(server, P02_DB, run_id)
    assert st[0] == "in-progress" and st[1] == "1"
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-1"
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'tool', {_jsonb('{\"obs\":\"o1\"}')}, 's-1');",
    )
    st = _run_state(server, P02_DB, run_id)
    assert st[0] == "in-progress" and st[1] == "1"
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-2"
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{\"raw\":\"2\"}')}, 's-2');",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'tool', {_jsonb('{\"obs\":\"o2\"}')}, 's-2');",
    )
    st = _run_state(server, P02_DB, run_id)
    assert st[0] == "in-progress" and st[1] == "2"
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-3"
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{\"raw\":\"3\"}')}, 's-3');",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'final', {_jsonb('{\"answer\":\"done\"}')}, 's-3');",
    )
    st = _run_state(server, P02_DB, run_id)
    assert st[0] == "final" and st[1] == "3" and st[2] == "done"
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-4"
    )

    err_id = "p02-error"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(err_id)}, 'error', {_jsonb('{\"message\":\"boom\"}')});",
    )
    st = _run_state(server, P02_DB, err_id)
    assert st[0] == "error" and st[3] == "boom"
    both = "p02-final-then-error"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(both)}, 'final', {_jsonb('{\"answer\":\"ok\"}')});",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(both)}, 'error', {_jsonb('{\"message\":\"late\"}')});",
    )
    st = _run_state(server, P02_DB, both)
    assert st[0] == "final" and st[2] == "ok"


def test_p02_crash_shaped_next_step_name(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-crash"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{\"raw\":\"x\"}')}, 's-1');",
    )
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-1"
    )
    assert (
        psql(
            server,
            P02_DB,
            f"SELECT count(*) FROM cordis.llm_checkpoint({_sql_str(run_id)}, 's-1');",
        )
        == "1"
    )
    assert (
        psql(
            server,
            P02_DB,
            f"SELECT count(*) FROM cordis.llm_checkpoint({_sql_str(run_id)}, 's-2');",
        )
        == "0"
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'tool', {_jsonb('{\"obs\":\"o\"}')}, 's-1');",
    )
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-2"
    )


def test_p02_llm_checkpoint_hit_miss_duplicate(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-ckpt"
    assert (
        psql(
            server,
            P02_DB,
            f"SELECT count(*) FROM cordis.llm_checkpoint({_sql_str(run_id)}, 's-1');",
        )
        == "0"
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{\"raw\":\"kept\"}')}, 's-1');",
    )
    assert (
        psql(
            server,
            P02_DB,
            "SELECT payload->>'raw' FROM cordis.llm_checkpoint("
            f"{_sql_str(run_id)}, 's-1');",
        )
        == "kept"
    )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{\"raw\":\"dup\"}')}, 's-1');",
        )
    other = "p02-ckpt-b"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(other)}, 'llm', {_jsonb('{\"raw\":\"b\"}')}, 's-1');",
    )
    assert (
        psql(
            server,
            P02_DB,
            f"SELECT count(*) FROM cordis.llm_checkpoint({_sql_str(other)}, 's-1');",
        )
        == "1"
    )


def test_p02_kind_and_step_name_checks(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-kinds"
    for i, kind in enumerate(KINDS):
        step = "s-1" if kind in ("llm", "tool") else "NULL"
        step_sql = "NULL" if step == "NULL" else _sql_str(step)
        # unique llm step_name: use distinct runs for llm after the first
        rid = f"{run_id}-{i}"
        if kind == "tool":
            psql(
                server,
                P02_DB,
                f"SELECT cordis.emit_step({_sql_str(rid)}, 'llm', {_jsonb('{}')}, 's-1');",
            )
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(rid)}, {_sql_str(kind)}, {_jsonb('null')}, {step_sql});",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{}')}, NULL);",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'tool', {_jsonb('{}')}, NULL);",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{}')}, 's0');",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'nope', {_jsonb('{}')});",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step('  ', 'final', {_jsonb('{}')});",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'final', NULL);",
        )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id + '-nulljson')}, 'final', 'null'::jsonb);",
    )
    for rel in ("run_waits", "run_events"):
        assert (
            psql(
                server,
                P02_DB,
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                f"WHERE n.nspname = 'cordis' AND c.relname = '{rel}';",
            )
            == "0"
        )


def test_p02_claimed_append_without_jobs(pgdata: Path, tmp_path: Path) -> None:
    _apply_p02_only(pgdata, tmp_path)
    server = get_server(pgdata)
    assert (
        psql(server, P02_ONLY_DB, "SELECT pg_catalog.to_regclass('cordis.jobs') IS NULL;")
        == "t"
    )
    token = "00000000-0000-0000-0000-000000000001"
    run_id = "p02-nofence"
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.emit_step_claimed('{token}'::uuid, {_sql_str(run_id)}, "
            f"'llm', {_jsonb('{\"raw\":\"a\"}')}, 's-1');",
        )
        == "t"
    )
    assert _count(server, P02_ONLY_DB, run_id) == 1
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.checkpoint('{token}'::uuid, "
            f"{_jsonb('[{\"run_id\":\"p02-nofence\",\"kind\":\"tool\",\"payload\":{\"o\":1},\"step_name\":\"s-1\"}]')});",
        )
        == "t"
    )
    assert _count(server, P02_ONLY_DB, run_id) == 2
    before = _count(server, P02_ONLY_DB, run_id)
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.emit_step_claimed(NULL, {_sql_str(run_id)}, 'final', {_jsonb('{}')});",
        )
        == "f"
    )
    assert _count(server, P02_ONLY_DB, run_id) == before


def test_p02_claimed_append_with_synthetic_jobs(pgdata: Path, tmp_path: Path) -> None:
    _apply_p02_only(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(
        server,
        P02_ONLY_DB,
        "CREATE TABLE cordis.jobs ("
        "run_id text, claim_token uuid, status text, claim_expires_at timestamptz, "
        "UNIQUE (claim_token));",
    )
    token = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    run_id = "p02-syn"
    psql(
        server,
        P02_ONLY_DB,
        "INSERT INTO cordis.jobs (run_id, claim_token, status, claim_expires_at) VALUES ("
        f"{_sql_str(run_id)}, '{token}'::uuid, 'RUNNING', "
        "pg_catalog.clock_timestamp() + interval '30 seconds');",
    )
    expiry_before = psql(
        server,
        P02_ONLY_DB,
        f"SELECT claim_expires_at::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.emit_step_claimed('{token}'::uuid, {_sql_str(run_id)}, "
            f"'llm', {_jsonb('{}')}, 's-1', 90);",
        )
        == "t"
    )
    assert _count(server, P02_ONLY_DB, run_id) == 1
    expiry_after = psql(
        server,
        P02_ONLY_DB,
        f"SELECT claim_expires_at::text FROM cordis.jobs WHERE run_id = {_sql_str(run_id)};",
    )
    assert expiry_after >= expiry_before
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT cordis.emit_step_claimed('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'::uuid, "
            f"{_sql_str(run_id)}, 'tool', {_jsonb('{}')}, 's-1');",
        )
        == "f"
    )
    assert _count(server, P02_ONLY_DB, run_id) == 1
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.emit_step_claimed('{token}'::uuid, 'other-run', "
            f"'tool', {_jsonb('{}')}, 's-1');",
        )
        == "f"
    )
    assert _count(server, P02_ONLY_DB, run_id) == 1
    psql(
        server,
        P02_ONLY_DB,
        "UPDATE cordis.jobs SET claim_expires_at = pg_catalog.clock_timestamp() "
        f"- interval '1 second' WHERE run_id = {_sql_str(run_id)};",
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.emit_step_claimed('{token}'::uuid, {_sql_str(run_id)}, "
            f"'tool', {_jsonb('{}')}, 's-1');",
        )
        == "f"
    )
    psql(
        server,
        P02_ONLY_DB,
        "UPDATE cordis.jobs SET status = 'PENDING', "
        "claim_expires_at = pg_catalog.clock_timestamp() + interval '1 hour' "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.emit_step_claimed('{token}'::uuid, {_sql_str(run_id)}, "
            f"'tool', {_jsonb('{}')}, 's-1');",
        )
        == "f"
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.emit_step_claimed(NULL, {_sql_str(run_id)}, 'tool', {_jsonb('{}')}, 's-1');",
        )
        == "f"
    )
    assert _count(server, P02_ONLY_DB, run_id) == 1


def test_p02_claimed_append_with_real_jobs(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-real-jobs"
    psql(
        server,
        P02_DB,
        "INSERT INTO cordis.jobs (run_id, job_type) "
        f"VALUES ({_sql_str(run_id)}, 'p02_test');",
    )
    token = psql(
        server,
        P02_DB,
        f"SELECT claim_token::text FROM cordis.claim_job({_sql_str(run_id)}, 'worker-a', 90);",
    )
    assert (
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step_claimed({_sql_str(token)}::uuid, {_sql_str(run_id)}, "
            f"'llm', {_jsonb('{}')}, 's-1');",
        )
        == "t"
    )
    assert _count(server, P02_DB, run_id) == 1
    assert (
        psql(
            server,
            P02_DB,
            "SELECT cordis.emit_step_claimed('cccccccc-cccc-cccc-cccc-cccccccccccc'::uuid, "
            f"{_sql_str(run_id)}, 'tool', {_jsonb('{}')}, 's-1');",
        )
        == "f"
    )
    assert _count(server, P02_DB, run_id) == 1


def test_p02_checkpoint_batch_atomicity(pgdata: Path, tmp_path: Path) -> None:
    _apply_p02_only(pgdata, tmp_path)
    server = get_server(pgdata)
    psql(
        server,
        P02_ONLY_DB,
        "CREATE TABLE cordis.jobs ("
        "run_id text, claim_token uuid, status text, claim_expires_at timestamptz, "
        "UNIQUE (claim_token));",
    )
    token = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    run_id = "p02-batch"
    psql(
        server,
        P02_ONLY_DB,
        "INSERT INTO cordis.jobs (run_id, claim_token, status, claim_expires_at) VALUES ("
        f"{_sql_str(run_id)}, '{token}'::uuid, 'RUNNING', "
        "pg_catalog.clock_timestamp() + interval '10 seconds');",
    )
    events_ok = (
        '[{"run_id":"p02-batch","kind":"llm","payload":{"raw":"a"},"step_name":"s-1"},'
        '{"run_id":"p02-batch","kind":"tool","payload":{"o":1},"step_name":"s-1"}]'
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.checkpoint('{token}'::uuid, {_jsonb(events_ok)});",
        )
        == "t"
    )
    assert _count(server, P02_ONLY_DB, run_id) == 2
    expiry_before = psql(
        server,
        P02_ONLY_DB,
        f"SELECT extract(epoch FROM claim_expires_at)::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    events_bad = (
        '[{"run_id":"p02-batch","kind":"llm","payload":{},"step_name":"s-2"},'
        '{"run_id":"p02-batch","kind":"nope","payload":{},"step_name":"s-2"}]'
    )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.checkpoint('{token}'::uuid, {_jsonb(events_bad)});",
        )
    assert _count(server, P02_ONLY_DB, run_id) == 2
    expiry_after = psql(
        server,
        P02_ONLY_DB,
        f"SELECT extract(epoch FROM claim_expires_at)::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert expiry_after == expiry_before
    events_mismatch = (
        '[{"run_id":"other-run","kind":"final","payload":{}}]'
    )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.checkpoint('{token}'::uuid, {_jsonb(events_mismatch)});",
        )
    assert _count(server, P02_ONLY_DB, run_id) == 2
    expiry_mismatch = psql(
        server,
        P02_ONLY_DB,
        f"SELECT extract(epoch FROM claim_expires_at)::text FROM cordis.jobs "
        f"WHERE run_id = {_sql_str(run_id)};",
    )
    assert expiry_mismatch == expiry_before


def test_p02_no_second_queue_or_public_log(pgdata: Path, tmp_path: Path) -> None:
    _apply_p02_only(pgdata, tmp_path)
    server = get_server(pgdata)
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname = 'agent_steps';",
        )
        == "1"
    )
    for rel in ("jobs", "agent_runs", "run_waits", "run_events"):
        assert (
            psql(
                server,
                P02_ONLY_DB,
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                f"WHERE n.nspname = 'cordis' AND c.relname = '{rel}';",
            )
            == "0"
        )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relkind = 'r' AND c.relname LIKE 'c_%';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname IN ('agent_steps','jobs');",
        )
        == "0"
    )


def test_p02_source_tree_append_monopoly() -> None:
    insert_re = re.compile(r"INSERT\s+INTO\s+cordis\.agent_steps", re.I)
    update_re = re.compile(r"UPDATE\s+cordis\.agent_steps", re.I)
    delete_re = re.compile(r"DELETE\s+FROM\s+cordis\.agent_steps", re.I)
    unqualified = re.compile(r"INSERT\s+INTO\s+agent_steps\b", re.I)
    public = re.compile(r"public\.agent_steps", re.I)
    block_comment = re.compile(r"/\*.*?\*/", re.S)
    inserts = []
    for path in sorted(SQL.glob("*.sql")):
        body = path.read_text()
        scanned = block_comment.sub(" ", body)
        lines = []
        for line in scanned.splitlines():
            if "--" in line:
                line = line.split("--", 1)[0]
            lines.append(line)
        scanned = "\n".join(lines)
        assert update_re.search(scanned) is None, path
        assert delete_re.search(scanned) is None, path
        assert unqualified.search(scanned) is None, path
        assert public.search(scanned) is None, path
        for match in insert_re.finditer(scanned):
            inserts.append((path.name, match.start()))
    assert len(inserts) == 1
    assert inserts[0][0] == "0002_p02_log.sql"
    src = (SQL / "0002_p02_log.sql").read_text()
    header = src.index("CREATE OR REPLACE FUNCTION cordis.emit_step(")
    closer = src.index("$fn$;", header)
    insert_at = src.index("INSERT INTO cordis.agent_steps", header)
    assert header < insert_at < closer


def test_p02_sequence_gap_does_not_change_step_name(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-gap"
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            "BEGIN; "
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{}')}, 's-1'); "
            "SELECT 1/0; "
            "COMMIT;",
        )
    seq = int(
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{}')}, 's-1');",
        )
    )
    assert seq >= 2
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-1"
    )


def test_p02_malformed_event_raises_before_lost_claim(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-malformed"
    before = _count(server, P02_DB, run_id)
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            f"SELECT cordis.emit_step_claimed(NULL, {_sql_str(run_id)}, "
            f"'nope', {_jsonb('{}')}, NULL);",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            "SELECT cordis.checkpoint('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'::uuid, "
            f"{_jsonb('[{\"run_id\":\"p02-malformed\",\"kind\":\"llm\",\"payload\":{}}]')});",
        )
    with pytest.raises(RuntimeError):
        psql(
            server,
            P02_DB,
            "SELECT cordis.checkpoint(NULL, "
            f"{_jsonb('[{\"run_id\":1,\"kind\":\"final\",\"payload\":{}}]')});",
        )
    assert _count(server, P02_DB, run_id) == before


def test_p02_sparse_next_step_name(pgdata: Path) -> None:
    _ensure_full(pgdata)
    server = get_server(pgdata)
    run_id = "p02-sparse"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'llm', {_jsonb('{}')}, 's-5');",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(run_id)}, 'tool', {_jsonb('{}')}, 's-5');",
    )
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(run_id)});")
        == "s-6"
    )
    other = "p02-sparse-gap"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(other)}, 'llm', {_jsonb('{}')}, 's-1');",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(other)}, 'tool', {_jsonb('{}')}, 's-1');",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(other)}, 'llm', {_jsonb('{}')}, 's-3');",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(other)}, 'tool', {_jsonb('{}')}, 's-3');",
    )
    nxt = psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(other)});")
    assert nxt == "s-4"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(other)}, 'llm', {_jsonb('{}')}, {_sql_str(nxt)});",
    )
    big = "p02-sparse-bigint"
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(big)}, 'llm', {_jsonb('{}')}, 's-2147483648');",
    )
    psql(
        server,
        P02_DB,
        f"SELECT cordis.emit_step({_sql_str(big)}, 'tool', {_jsonb('{}')}, 's-2147483648');",
    )
    assert (
        psql(server, P02_DB, f"SELECT cordis.next_step_name({_sql_str(big)});")
        == "s-2147483649"
    )


def test_p02_checkpoint_preserves_array_order(pgdata: Path, tmp_path: Path) -> None:
    _apply_p02_only(pgdata, tmp_path)
    server = get_server(pgdata)
    run_id = "p02-order"
    token = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    events = (
        '[{"run_id":"p02-order","kind":"llm","payload":{"i":1},"step_name":"s-1"},'
        '{"run_id":"p02-order","kind":"tool","payload":{"i":2},"step_name":"s-1"},'
        '{"run_id":"p02-order","kind":"final","payload":{"i":3}}]'
    )
    assert (
        psql(
            server,
            P02_ONLY_DB,
            f"SELECT cordis.checkpoint('{token}'::uuid, {_jsonb(events)});",
        )
        == "t"
    )
    kinds = psql(
        server,
        P02_ONLY_DB,
        "SELECT string_agg(kind, ',' ORDER BY seq) "
        f"FROM cordis.agent_steps WHERE run_id = {_sql_str(run_id)};",
    )
    assert kinds == "llm,tool,final"
