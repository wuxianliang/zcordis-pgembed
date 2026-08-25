"""P19 paradigm policy tests. Apply stays a subprocess."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pgembed import get_server

from tests.conftest import SQL, next_sql_prefix, psql, run_apply

P19_DB = "cordis_p19"

CODEACT_PROMPT = (
    "You are a CodeAct agent. Each step is one model turn plus its structured "
    "tool calls. Call tools as JSON. Do not execute free-form code. Context is "
    "in the prompt, not in an environment. In-step tools are not child runs."
)
RLM_PROMPT = (
    "You are an RLM prime agent. Context lives in run-scoped environment "
    "variables; address it there. Observations you see are truncated; full "
    "results remain in the environment. Child work uses rlm() and returns only "
    "an admission handle. Do not wait for a child in this step. Do not inline "
    "large context into the model prompt."
)

HOST_PROOF = {
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


def _reset(pgdata: Path, database: str = P19_DB) -> None:
    result = run_apply(
        "--pgdata", str(pgdata), "--database", database, "--reset"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _envelope(**fields: object) -> dict:
    base = {
        "identity": "probe.alias",
        "version": "0.1.0",
        "description": "probe",
        "action_surface": "structured_tools",
        "parser_kind": "json_tool_calls",
        "spawn_mode": "always_enqueue",
        "env_enabled": False,
        "env_workspace": "none",
        "env_inherit": "none",
        "observation_clip_chars": None,
        "observation_full_in_env": False,
        "system_prompt": "probe prompt",
        "fold_fn": "cordis.fold_codeact_messages",
        "parse_fn": "cordis.parse_codeact_decision",
        "observe_fn": "cordis.observe_codeact",
    }
    base.update(fields)
    return {"cordis_paradigm": base}


def _register_sql(definition: dict) -> str:
    payload = json.dumps(definition, separators=(",", ":"))
    return (
        "SELECT cordis.register_paradigm_policy("
        + _sql_str(payload)
        + "::jsonb);"
    )


def _fail(server, sql: str) -> str:
    wrapped = (
        "DO LANGUAGE plpgsql $err$\n"
        "BEGIN\n"
        f"  EXECUTE {_sql_str(sql.rstrip(';'))};\n"
        "EXCEPTION WHEN OTHERS THEN\n"
        "  RAISE EXCEPTION '%: %', SQLSTATE, SQLERRM;\n"
        "END;\n"
        "$err$;"
    )
    try:
        psql(server, P19_DB, wrapped)
    except RuntimeError as exc:
        return str(exc)
    raise AssertionError(f"expected error from {sql!r}")


def test_p19_fresh_apply_seeds_and_version(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    assert psql(server, P19_DB, "SELECT cordis.get_schema_version();") == "p20"
    assert (
        psql(
            server,
            P19_DB,
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname = 'paradigm_policies';",
        )
        == "1"
    )
    assert (
        psql(server, P19_DB, "SELECT count(*) FROM cordis.paradigm_policies;")
        == "2"
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT string_agg(identity, ',' ORDER BY identity) "
            "FROM cordis.paradigm_policies;",
        )
        == "codeact,rlm"
    )
    assert (
        psql(server, P19_DB, "SELECT count(*) FROM cordis.plugin_catalog;")
        == "0"
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'cordis' AND c.relname = 'rlm_vars';",
        )
        == "0"
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'paradigm_policies';",
        )
        == "0"
    )


def test_p19_lookup_codeact_and_rlm(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    codeact = psql(
        server,
        P19_DB,
        "SELECT identity || '|' || version || '|' || action_surface || '|' "
        "|| parser_kind || '|' || spawn_mode || '|' || env_enabled::text || '|' "
        "|| env_workspace || '|' || env_inherit || '|' "
        "|| COALESCE(observation_clip_chars::text, 'null') || '|' "
        "|| observation_full_in_env::text || '|' || fold_fn || '|' "
        "|| parse_fn || '|' || observe_fn || '|' "
        "|| (metadata->'cordis_paradigm'->>'identity') "
        "FROM cordis.paradigm_policy('codeact');",
    )
    assert codeact == (
        "codeact|0.1.0|structured_tools|json_tool_calls|always_enqueue|"
        "false|none|none|null|false|cordis.fold_codeact_messages|"
        "cordis.parse_codeact_decision|cordis.observe_codeact|codeact"
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT system_prompt FROM cordis.paradigm_policy('codeact');",
        )
        == CODEACT_PROMPT
    )
    rlm = psql(
        server,
        P19_DB,
        "SELECT identity || '|' || action_surface || '|' || parser_kind || '|' "
        "|| spawn_mode || '|' || env_enabled::text || '|' || env_workspace "
        "|| '|' || env_inherit || '|' "
        "|| COALESCE(observation_clip_chars::text, 'null') || '|' "
        "|| observation_full_in_env::text || '|' || fold_fn "
        "FROM cordis.paradigm_policy('rlm');",
    )
    assert rlm == (
        "rlm|env_repl|json_env_eval|always_enqueue|true|run_vars|"
        "named_grants_and_question|4000|true|cordis.fold_rlm_messages"
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT system_prompt FROM cordis.paradigm_policy('rlm');",
        )
        == RLM_PROMPT
    )


def test_p19_unknown_and_invalid_identity(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    hybrid = _fail(server, "SELECT * FROM cordis.paradigm_policy('hybrid')")
    assert "22023" in hybrid
    assert "unknown paradigm" in hybrid
    da = _fail(server, "SELECT * FROM cordis.paradigm_policy('data_analysis')")
    assert "22023" in da
    assert "unknown paradigm" in da
    blank = _fail(server, "SELECT * FROM cordis.paradigm_policy('')")
    assert "22023" in blank
    assert "invalid identity" in blank
    nul = _fail(server, "SELECT * FROM cordis.paradigm_policy(NULL)")
    assert "22023" in nul
    assert "invalid identity" in nul
    mixed = _fail(server, "SELECT * FROM cordis.paradigm_policy('CodeAct')")
    assert "22023" in mixed
    assert "invalid identity" in mixed


def test_p19_third_policy_independent_clip(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    ident = psql(
        server,
        P19_DB,
        _register_sql(
            _envelope(
                identity="probe.alias",
                observation_clip_chars=1000,
                system_prompt="alias prompt",
            )
        ),
    )
    assert ident == "probe.alias"
    assert (
        psql(
            server,
            P19_DB,
            "SELECT observation_clip_chars::text "
            "FROM cordis.paradigm_policy('probe.alias');",
        )
        == "1000"
    )
    assert (
        psql(server, P19_DB, "SELECT count(*) FROM cordis.paradigm_policies;")
        == "3"
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT cordis.unregister_paradigm_policy('probe.alias');",
        )
        == "t"
    )
    assert (
        psql(server, P19_DB, "SELECT count(*) FROM cordis.paradigm_policies;")
        == "2"
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT string_agg(identity, ',' ORDER BY identity) "
            "FROM cordis.paradigm_policies;",
        )
        == "codeact,rlm"
    )


def test_p19_register_rejects_illegal_env_sync_and_plugin_envelope(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    before = psql(
        server, P19_DB, "SELECT count(*) FROM cordis.paradigm_policies;"
    )
    env_bad = _envelope(env_enabled=True, env_workspace="none")
    err = _fail(
        server,
        "SELECT * FROM cordis._validate_paradigm_policy("
        + _sql_str(json.dumps(env_bad, separators=(",", ":")))
        + "::jsonb)",
    )
    assert "22023" in err
    assert "invalid env" in err

    sync = _envelope(spawn_mode="sync")
    err = _fail(
        server,
        "SELECT * FROM cordis._validate_paradigm_policy("
        + _sql_str(json.dumps(sync, separators=(",", ":")))
        + "::jsonb)",
    )
    assert "22023" in err

    surface = _envelope(action_surface="free_code")
    err = _fail(
        server,
        "SELECT * FROM cordis._validate_paradigm_policy("
        + _sql_str(json.dumps(surface, separators=(",", ":")))
        + "::jsonb)",
    )
    assert "22023" in err

    plugin = {
        "cordis_plugin": {"identity": "x"},
        "cordis_paradigm": _envelope()["cordis_paradigm"],
    }
    err = _fail(
        server,
        "SELECT * FROM cordis._validate_paradigm_policy("
        + _sql_str(json.dumps(plugin, separators=(",", ":")))
        + "::jsonb)",
    )
    assert "22023" in err
    assert "plugin envelope" in err

    missing = _envelope(fold_fn="cordis.missing_fold")
    err = _fail(
        server,
        "SELECT * FROM cordis._validate_paradigm_policy("
        + _sql_str(json.dumps(missing, separators=(",", ":")))
        + "::jsonb)",
    )
    assert "22023" in err
    assert "invalid fold_fn" in err

    psql(
        server,
        P19_DB,
        "CREATE OR REPLACE FUNCTION cordis.p19_setof_fold(p_run_id text)\n"
        "RETURNS SETOF jsonb LANGUAGE sql STABLE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog AS $fn$ SELECT '{}'::jsonb; $fn$;\n"
        "CREATE OR REPLACE FUNCTION cordis.p19_vol_fold(p_run_id text)\n"
        "RETURNS jsonb LANGUAGE sql VOLATILE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog AS $fn$ SELECT '{}'::jsonb; $fn$;\n"
        "CREATE OR REPLACE FUNCTION cordis.p19_text_fold(p_run_id text)\n"
        "RETURNS text LANGUAGE sql STABLE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog AS $fn$ SELECT 'x'; $fn$;\n"
        "CREATE OR REPLACE FUNCTION cordis.p19_stable_parse(p_llm_text text)\n"
        "RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog AS $fn$ SELECT '{}'::jsonb; $fn$;\n"
        "CREATE OR REPLACE FUNCTION cordis.p19_setof_obs(p_raw jsonb)\n"
        "RETURNS SETOF jsonb LANGUAGE sql IMMUTABLE SECURITY INVOKER\n"
        "SET search_path TO pg_catalog AS $fn$ SELECT '{}'::jsonb; $fn$;",
    )
    for fold_name, fragment in (
        ("cordis.p19_setof_fold", "invalid fold_fn"),
        ("cordis.p19_vol_fold", "invalid fold_fn"),
        ("cordis.p19_text_fold", "invalid fold_fn"),
    ):
        err = _fail(
            server,
            "SELECT * FROM cordis._validate_paradigm_policy("
            + _sql_str(
                json.dumps(_envelope(fold_fn=fold_name), separators=(",", ":"))
            )
            + "::jsonb)",
        )
        assert "22023" in err
        assert fragment in err
    err = _fail(
        server,
        "SELECT * FROM cordis._validate_paradigm_policy("
        + _sql_str(
            json.dumps(
                _envelope(parse_fn="cordis.p19_stable_parse"),
                separators=(",", ":"),
            )
        )
        + "::jsonb)",
    )
    assert "22023" in err
    assert "invalid parse_fn" in err
    err = _fail(
        server,
        "SELECT * FROM cordis._validate_paradigm_policy("
        + _sql_str(
            json.dumps(
                _envelope(observe_fn="cordis.p19_setof_obs"),
                separators=(",", ":"),
            )
        )
        + "::jsonb)",
    )
    assert "22023" in err
    assert "invalid observe_fn" in err
    assert (
        psql(server, P19_DB, "SELECT count(*) FROM cordis.paradigm_policies;")
        == before
    )


def test_p19_clip_overflow_is_22023(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    for value in (1000001, 2147483648, 9999999999999999999):
        err = _fail(
            server,
            "SELECT * FROM cordis._validate_paradigm_policy("
            + _sql_str(
                json.dumps(
                    _envelope(observation_clip_chars=value),
                    separators=(",", ":"),
                )
            )
            + "::jsonb)",
        )
        assert "22023" in err, err
        assert "invalid observation_clip_chars" in err, err
        assert "22003" not in err, err


def test_p19_unregister_and_replay_restores_missing_seed(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    assert (
        psql(
            server,
            P19_DB,
            "SELECT cordis.unregister_paradigm_policy('codeact');",
        )
        == "t"
    )
    gone = _fail(server, "SELECT * FROM cordis.paradigm_policy('codeact')")
    assert "unknown paradigm" in gone
    psql(
        server,
        P19_DB,
        "CREATE TABLE IF NOT EXISTS public.p19_sentinel (id int);",
    )
    result = run_apply("--pgdata", str(pgdata), "--database", P19_DB)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode=in-place" in result.stdout
    assert psql(server, P19_DB, "SELECT cordis.get_schema_version();") == "p20"
    assert (
        psql(
            server,
            P19_DB,
            "SELECT system_prompt FROM cordis.paradigm_policy('codeact');",
        )
        == CODEACT_PROMPT
    )
    assert (
        psql(
            server,
            P19_DB,
            "SELECT COUNT(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'p19_sentinel';",
        )
        == "1"
    )


def test_p19_replay_preserves_runtime_upsert(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    custom = _envelope(
        identity="codeact",
        system_prompt="runtime custom prompt",
        description="CodeAct structured-tool policy for the shared loop kernel.",
    )
    psql(server, P19_DB, _register_sql(custom))
    assert (
        psql(
            server,
            P19_DB,
            "SELECT system_prompt FROM cordis.paradigm_policy('codeact');",
        )
        == "runtime custom prompt"
    )
    result = run_apply("--pgdata", str(pgdata), "--database", P19_DB)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        psql(
            server,
            P19_DB,
            "SELECT system_prompt FROM cordis.paradigm_policy('codeact');",
        )
        == "runtime custom prompt"
    )


def test_p19_upsert_preserves_registered_at(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    psql(server, P19_DB, _register_sql(_envelope(identity="probe.alias")))
    first = psql(
        server,
        P19_DB,
        "SELECT registered_at::text FROM cordis.paradigm_policy('probe.alias');",
    )
    psql(
        server,
        P19_DB,
        _register_sql(
            _envelope(identity="probe.alias", description="updated probe")
        ),
    )
    second = psql(
        server,
        P19_DB,
        "SELECT registered_at::text || '|' || description "
        "FROM cordis.paradigm_policy('probe.alias');",
    )
    assert second.startswith(first + "|")
    assert second.endswith("|updated probe")
    later = psql(
        server,
        P19_DB,
        "SELECT (updated_at >= registered_at)::text "
        "FROM cordis.paradigm_policy('probe.alias');",
    )
    assert later == "true"
    psql(
        server,
        P19_DB,
        "SELECT cordis.unregister_paradigm_policy('probe.alias');",
    )


def test_p19_dispatch_calls_slot_stubs_by_name(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    for ident in ("codeact", "rlm"):
        fold_fn = psql(
            server,
            P19_DB,
            f"SELECT fold_fn FROM cordis.paradigm_policy({_sql_str(ident)});",
        )
        parse_fn = psql(
            server,
            P19_DB,
            f"SELECT parse_fn FROM cordis.paradigm_policy({_sql_str(ident)});",
        )
        observe_fn = psql(
            server,
            P19_DB,
            f"SELECT observe_fn FROM cordis.paradigm_policy({_sql_str(ident)});",
        )
        assert (
            psql(
                server,
                P19_DB,
                f"SELECT to_regprocedure({_sql_str(fold_fn + '(text)')}) "
                "IS NOT NULL;",
            )
            == "t"
        )
        fold = json.loads(
            psql(server, P19_DB, f"SELECT {fold_fn}('run-1');")
        )
        parsed = json.loads(
            psql(server, P19_DB, f"SELECT {parse_fn}('{{}}');")
        )
        obs = json.loads(
            psql(server, P19_DB, f"SELECT {observe_fn}('{{}}'::jsonb);")
        )
        assert fold["p19_stub"] is True
        assert fold["slot"] == "fold"
        assert parsed["p19_stub"] is True
        assert parsed["slot"] == "parse"
        assert obs["p19_stub"] is True
        assert obs["slot"] == "observe"


def test_p19_observation_wrapper_clips_without_identity_branch(
    pgdata: Path,
) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    shown_len = psql(
        server,
        P19_DB,
        "SELECT char_length(cordis.observe_codeact('{}'::jsonb)->>'shown');",
    )
    assert shown_len == "2000"
    clip10 = psql(
        server,
        P19_DB,
        "SELECT char_length("
        "cordis.apply_observation_policy("
        "cordis.observe_codeact('{}'::jsonb), 10, false)->>'shown');",
    )
    assert clip10 == "10"
    noclip = psql(
        server,
        P19_DB,
        "SELECT char_length("
        "cordis.apply_observation_policy("
        "cordis.observe_codeact('{}'::jsonb), NULL, false)->>'shown');",
    )
    assert noclip == "2000"
    full = psql(
        server,
        P19_DB,
        "SELECT char_length("
        "cordis.apply_observation_policy("
        "cordis.observe_codeact('{}'::jsonb), 1000, true)->>'shown') "
        "|| '|' || jsonb_typeof("
        "cordis.apply_observation_policy("
        "cordis.observe_codeact('{}'::jsonb), 1000, true)->'stored');",
    )
    assert full == "1000|object"
    empty = psql(
        server,
        P19_DB,
        "SELECT cordis.apply_observation_policy('{}'::jsonb, 10, false)"
        "->>'shown';",
    )
    assert empty == ""
    nul = _fail(
        server, "SELECT cordis.apply_observation_policy(NULL, 10, false)"
    )
    assert "22023" in nul
    assert "invalid observation" in nul
    arr = _fail(
        server, "SELECT cordis.apply_observation_policy('[]'::jsonb, 10, false)"
    )
    assert "22023" in arr
    assert "invalid observation" in arr


def test_p19_higher_file_replaces_stub_and_survives_replay(
    pgdata: Path, tmp_path: Path
) -> None:
    tree = tmp_path / "sql_sentinel"
    shutil.copytree(SQL, tree)
    prefix = next_sql_prefix(tree)
    (tree / f"{prefix}_sentinel.sql").write_text(
        "CREATE OR REPLACE FUNCTION cordis.fold_codeact_messages(p_run_id text)\n"
        "RETURNS jsonb\n"
        "LANGUAGE sql\n"
        "STABLE\n"
        "SECURITY INVOKER\n"
        "SET search_path TO pg_catalog\n"
        "AS $sentinel$\n"
        "  SELECT pg_catalog.jsonb_build_object('sentinel', true, 'run_id', p_run_id);\n"
        "$sentinel$;\n"
    )
    result = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P19_DB,
        "--sql-root",
        str(tree),
        "--reset",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    server = get_server(pgdata)
    assert psql(server, P19_DB, "SELECT cordis.get_schema_version();") == "p20"
    body = json.loads(
        psql(server, P19_DB, "SELECT cordis.fold_codeact_messages('r');")
    )
    assert body == {"sentinel": True, "run_id": "r"}
    replay = run_apply(
        "--pgdata",
        str(pgdata),
        "--database",
        P19_DB,
        "--sql-root",
        str(tree),
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    body2 = json.loads(
        psql(server, P19_DB, "SELECT cordis.fold_codeact_messages('r');")
    )
    assert body2 == {"sentinel": True, "run_id": "r"}


def test_p19_signatures_and_volatility(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)

    vol = psql(
        server,
        P19_DB,
        "SELECT p.proname || ':' || p.provolatile::text || ':' "
        "|| p.prosecdef::text || ':' || l.lanname "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_language l ON l.oid = p.prolang "
        "WHERE n.nspname = 'cordis' AND p.proname IN ("
        "'_validate_paradigm_policy','register_paradigm_policy',"
        "'unregister_paradigm_policy','paradigm_policy',"
        "'fold_codeact_messages','fold_rlm_messages',"
        "'parse_codeact_decision','parse_rlm_decision',"
        "'observe_codeact','observe_rlm','apply_observation_policy',"
        "'get_schema_version') "
        "ORDER BY 1;",
    ).splitlines()
    wanted = {
        "_validate_paradigm_policy:v:false:plpgsql",
        "apply_observation_policy:i:false:plpgsql",
        "fold_codeact_messages:s:false:sql",
        "fold_rlm_messages:s:false:sql",
        "get_schema_version:i:false:sql",
        "observe_codeact:i:false:sql",
        "observe_rlm:i:false:sql",
        "paradigm_policy:s:false:plpgsql",
        "parse_codeact_decision:i:false:sql",
        "parse_rlm_decision:i:false:sql",
        "register_paradigm_policy:v:false:plpgsql",
        "unregister_paradigm_policy:v:false:plpgsql",
    }
    assert set(vol) == wanted
    version = psql(
        server,
        P19_DB,
        "SELECT pg_get_function_identity_arguments(p.oid) || '|' || "
        "pg_get_function_result(p.oid) || '|' || l.lanname || '|' || "
        "p.provolatile::text || '|' || p.prosecdef::text "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_language l ON l.oid = p.prolang "
        "WHERE n.nspname = 'cordis' AND p.proname = 'get_schema_version' "
        "AND p.pronargs = 0;",
    )
    assert version == "|text|sql|i|false"
    for proname in (
        "_validate_paradigm_policy",
        "register_paradigm_policy",
        "unregister_paradigm_policy",
        "paradigm_policy",
        "fold_codeact_messages",
        "fold_rlm_messages",
        "parse_codeact_decision",
        "parse_rlm_decision",
        "observe_codeact",
        "observe_rlm",
        "apply_observation_policy",
    ):
        assert (
            psql(
                server,
                P19_DB,
                "SELECT count(*) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                f"WHERE n.nspname = 'cordis' AND p.proname = '{proname}';",
            )
            == "1"
        )


def test_p19_does_not_touch_plugin_catalog_invocation(pgdata: Path) -> None:
    _reset(pgdata)
    server = get_server(pgdata)
    cdef = psql(
        server,
        P19_DB,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'plugin_catalog_invocation_check';",
    )
    assert "queue" in cdef
    assert "session_select" in cdef
    assert "host_tool" in cdef
    ident = psql(
        server,
        P19_DB,
        "SELECT cordis.register_host_plugin("
        + _sql_str(json.dumps(HOST_PROOF, separators=(",", ":")))
        + "::jsonb);",
    )
    assert ident == "host.worktree.apply_edits"
    assert (
        psql(
            server,
            P19_DB,
            "SELECT invocation FROM cordis.plugin_catalog "
            "WHERE identity = 'host.worktree.apply_edits';",
        )
        == "host_tool"
    )
