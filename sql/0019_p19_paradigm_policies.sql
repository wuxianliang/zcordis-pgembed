-- P19: CodeAct / RLM paradigm policy packs. Replay-safe.
-- No GRANT/REVOKE/role/extension/public objects or transaction control.
-- plpgsql bodies use $p19$ so preflight dollar-quote stripping covers END words.

CREATE TABLE IF NOT EXISTS cordis.paradigm_policies (
    identity text NOT NULL,
    version text NOT NULL,
    description text NOT NULL,
    action_surface text NOT NULL,
    parser_kind text NOT NULL,
    spawn_mode text NOT NULL,
    env_enabled boolean NOT NULL,
    env_workspace text NOT NULL,
    env_inherit text NOT NULL,
    observation_clip_chars integer,
    observation_full_in_env boolean NOT NULL,
    system_prompt text NOT NULL,
    fold_fn text NOT NULL,
    parse_fn text NOT NULL,
    observe_fn text NOT NULL,
    metadata jsonb NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT paradigm_policies_pkey PRIMARY KEY (identity),
    CONSTRAINT paradigm_policies_identity_check CHECK (
        pg_catalog.octet_length(identity) <= 128
        AND identity ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'
    ),
    CONSTRAINT paradigm_policies_version_check CHECK (
        pg_catalog.octet_length(version) BETWEEN 1 AND 64
        AND version ~ '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
    ),
    CONSTRAINT paradigm_policies_action_surface_check CHECK (
        action_surface IN ('structured_tools', 'env_repl')
    ),
    CONSTRAINT paradigm_policies_parser_kind_check CHECK (
        parser_kind IN ('json_tool_calls', 'json_env_eval')
    ),
    CONSTRAINT paradigm_policies_spawn_mode_check CHECK (
        spawn_mode = 'always_enqueue'
    ),
    CONSTRAINT paradigm_policies_env_workspace_check CHECK (
        env_workspace IN ('none', 'run_vars')
    ),
    CONSTRAINT paradigm_policies_env_inherit_check CHECK (
        env_inherit IN ('none', 'named_grants_and_question')
    ),
    CONSTRAINT paradigm_policies_clip_check CHECK (
        observation_clip_chars IS NULL OR observation_clip_chars > 0
    ),
    CONSTRAINT paradigm_policies_fn_name_check CHECK (
        fold_fn ~ '^cordis\.[a-z][a-z0-9_]*$'
        AND pg_catalog.octet_length(fold_fn) <= 128
        AND parse_fn ~ '^cordis\.[a-z][a-z0-9_]*$'
        AND pg_catalog.octet_length(parse_fn) <= 128
        AND observe_fn ~ '^cordis\.[a-z][a-z0-9_]*$'
        AND pg_catalog.octet_length(observe_fn) <= 128
    ),
    CONSTRAINT paradigm_policies_prompt_nonblank_check CHECK (
        pg_catalog.btrim(system_prompt) <> ''
    ),
    CONSTRAINT paradigm_policies_metadata_object_check CHECK (
        pg_catalog.jsonb_typeof(metadata) = 'object'
    ),
    CONSTRAINT paradigm_policies_env_check CHECK (
        (
            env_enabled = false
            AND env_workspace = 'none'
            AND env_inherit = 'none'
            AND observation_full_in_env = false
        )
        OR (
            env_enabled = true
            AND env_workspace = 'run_vars'
            AND env_inherit IN ('none', 'named_grants_and_question')
        )
    )
);

CREATE OR REPLACE FUNCTION cordis._validate_paradigm_policy(p_definition jsonb)
RETURNS TABLE (
    identity text,
    version text,
    description text,
    action_surface text,
    parser_kind text,
    spawn_mode text,
    env_enabled boolean,
    env_workspace text,
    env_inherit text,
    observation_clip_chars integer,
    observation_full_in_env boolean,
    system_prompt text,
    fold_fn text,
    parse_fn text,
    observe_fn text,
    metadata jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
DECLARE
    plugin jsonb;
    v_identity text;
    v_version text;
    v_description text;
    v_surface text;
    v_parser text;
    v_spawn text;
    v_env_enabled boolean;
    v_workspace text;
    v_inherit text;
    v_clip integer;
    v_clip_raw jsonb;
    v_clip_num numeric;
    v_full boolean;
    v_prompt text;
    v_fold text;
    v_parse text;
    v_observe text;
    v_oid regprocedure;
    v_kind "char";
    v_retset boolean;
    v_rettype oid;
    v_vol "char";
BEGIN
    IF p_definition IS NULL OR pg_catalog.jsonb_typeof(p_definition) <> 'object' THEN
        RAISE EXCEPTION 'definition must be a JSON object'
            USING ERRCODE = '22023';
    END IF;
    IF (p_definition ? 'cordis_plugin')
       OR (p_definition ? 'job_handler')
       OR (p_definition ? 'workbench_plugin') THEN
        RAISE EXCEPTION 'plugin envelope is not a paradigm policy'
            USING ERRCODE = '22023';
    END IF;
    plugin := p_definition -> 'cordis_paradigm';
    IF plugin IS NULL OR pg_catalog.jsonb_typeof(plugin) <> 'object' THEN
        RAISE EXCEPTION 'cordis_paradigm object is required'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'identity') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: identity'
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(plugin ->> 'identity');
    IF v_identity IS NULL OR v_identity = '' THEN
        RAISE EXCEPTION 'missing field: identity'
            USING ERRCODE = '22023';
    END IF;
    IF pg_catalog.octet_length(v_identity) > 128
       OR v_identity !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid identity: %', v_identity
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'version') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: version'
            USING ERRCODE = '22023';
    END IF;
    v_version := pg_catalog.btrim(plugin ->> 'version');
    IF v_version IS NULL OR v_version = ''
       OR pg_catalog.octet_length(v_version) NOT BETWEEN 1 AND 64
       OR v_version !~ '^[A-Za-z0-9][A-Za-z0-9._+-]*$' THEN
        RAISE EXCEPTION 'invalid version: %', v_version
            USING ERRCODE = '22023';
    END IF;

    IF plugin ? 'description' AND plugin -> 'description' IS NOT NULL
       AND plugin -> 'description' <> 'null'::jsonb THEN
        IF pg_catalog.jsonb_typeof(plugin -> 'description') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'missing field: description'
                USING ERRCODE = '22023';
        END IF;
        v_description := pg_catalog.btrim(plugin ->> 'description');
    ELSE
        v_description := v_identity;
    END IF;
    IF v_description IS NULL OR v_description = ''
       OR pg_catalog.char_length(v_description) > 500
       OR v_description ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid description'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'action_surface') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: action_surface'
            USING ERRCODE = '22023';
    END IF;
    v_surface := pg_catalog.btrim(plugin ->> 'action_surface');
    IF v_surface IS NULL OR v_surface NOT IN ('structured_tools', 'env_repl') THEN
        RAISE EXCEPTION 'invalid action_surface'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'parser_kind') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: parser_kind'
            USING ERRCODE = '22023';
    END IF;
    v_parser := pg_catalog.btrim(plugin ->> 'parser_kind');
    IF v_parser IS NULL OR v_parser NOT IN ('json_tool_calls', 'json_env_eval') THEN
        RAISE EXCEPTION 'invalid parser_kind'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'spawn_mode') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: spawn_mode'
            USING ERRCODE = '22023';
    END IF;
    v_spawn := pg_catalog.btrim(plugin ->> 'spawn_mode');
    IF v_spawn IS DISTINCT FROM 'always_enqueue' THEN
        RAISE EXCEPTION 'invalid spawn_mode'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'env_enabled') IS DISTINCT FROM 'boolean' THEN
        RAISE EXCEPTION 'missing field: env_enabled'
            USING ERRCODE = '22023';
    END IF;
    v_env_enabled := (plugin ->> 'env_enabled')::boolean;

    IF pg_catalog.jsonb_typeof(plugin -> 'env_workspace') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: env_workspace'
            USING ERRCODE = '22023';
    END IF;
    v_workspace := pg_catalog.btrim(plugin ->> 'env_workspace');
    IF v_workspace IS NULL OR v_workspace NOT IN ('none', 'run_vars') THEN
        RAISE EXCEPTION 'invalid env_workspace'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'env_inherit') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: env_inherit'
            USING ERRCODE = '22023';
    END IF;
    v_inherit := pg_catalog.btrim(plugin ->> 'env_inherit');
    IF v_inherit IS NULL
       OR v_inherit NOT IN ('none', 'named_grants_and_question') THEN
        RAISE EXCEPTION 'invalid env_inherit'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'observation_full_in_env') IS DISTINCT FROM 'boolean' THEN
        RAISE EXCEPTION 'missing field: observation_full_in_env'
            USING ERRCODE = '22023';
    END IF;
    v_full := (plugin ->> 'observation_full_in_env')::boolean;

    IF (
        v_env_enabled = false
        AND v_workspace = 'none'
        AND v_inherit = 'none'
        AND v_full = false
    ) OR (
        v_env_enabled = true
        AND v_workspace = 'run_vars'
        AND v_inherit IN ('none', 'named_grants_and_question')
    ) THEN
        NULL;
    ELSE
        RAISE EXCEPTION 'invalid env combination'
            USING ERRCODE = '22023';
    END IF;

    v_clip_raw := plugin -> 'observation_clip_chars';
    IF v_clip_raw IS NULL OR v_clip_raw = 'null'::jsonb THEN
        v_clip := NULL;
    ELSIF pg_catalog.jsonb_typeof(v_clip_raw) = 'number' THEN
        BEGIN
            v_clip_num := (v_clip_raw #>> '{}')::numeric;
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION 'invalid observation_clip_chars'
                USING ERRCODE = '22023';
        END;
        IF v_clip_num IS NULL
           OR v_clip_num <> pg_catalog.trunc(v_clip_num)
           OR v_clip_num < 1
           OR v_clip_num > 1000000 THEN
            RAISE EXCEPTION 'invalid observation_clip_chars'
                USING ERRCODE = '22023';
        END IF;
        v_clip := v_clip_num::integer;
    ELSE
        RAISE EXCEPTION 'invalid observation_clip_chars'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'system_prompt') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: system_prompt'
            USING ERRCODE = '22023';
    END IF;
    v_prompt := plugin ->> 'system_prompt';
    IF v_prompt IS NULL OR pg_catalog.btrim(v_prompt) = ''
       OR pg_catalog.octet_length(v_prompt) > 8000
       OR pg_catalog.replace(pg_catalog.replace(v_prompt, E'\n', ''), E'\t', '') ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid system_prompt'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'fold_fn') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: fold_fn'
            USING ERRCODE = '22023';
    END IF;
    v_fold := pg_catalog.btrim(plugin ->> 'fold_fn');
    IF v_fold IS NULL OR pg_catalog.octet_length(v_fold) > 128
       OR v_fold !~ '^cordis\.[a-z][a-z0-9_]*$' THEN
        RAISE EXCEPTION 'invalid fold_fn'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'parse_fn') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: parse_fn'
            USING ERRCODE = '22023';
    END IF;
    v_parse := pg_catalog.btrim(plugin ->> 'parse_fn');
    IF v_parse IS NULL OR pg_catalog.octet_length(v_parse) > 128
       OR v_parse !~ '^cordis\.[a-z][a-z0-9_]*$' THEN
        RAISE EXCEPTION 'invalid parse_fn'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.jsonb_typeof(plugin -> 'observe_fn') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'missing field: observe_fn'
            USING ERRCODE = '22023';
    END IF;
    v_observe := pg_catalog.btrim(plugin ->> 'observe_fn');
    IF v_observe IS NULL OR pg_catalog.octet_length(v_observe) > 128
       OR v_observe !~ '^cordis\.[a-z][a-z0-9_]*$' THEN
        RAISE EXCEPTION 'invalid observe_fn'
            USING ERRCODE = '22023';
    END IF;

    v_oid := pg_catalog.to_regprocedure(v_fold || '(text)');
    IF v_oid IS NULL THEN
        RAISE EXCEPTION 'invalid fold_fn'
            USING ERRCODE = '22023';
    END IF;
    SELECT p.prokind, p.proretset, p.prorettype, p.provolatile
      INTO v_kind, v_retset, v_rettype, v_vol
      FROM pg_proc p
     WHERE p.oid = v_oid;
    IF v_kind IS DISTINCT FROM 'f'
       OR v_retset
       OR v_rettype IS DISTINCT FROM 'jsonb'::regtype
       OR v_vol IS DISTINCT FROM 's' THEN
        RAISE EXCEPTION 'invalid fold_fn'
            USING ERRCODE = '22023';
    END IF;

    v_oid := pg_catalog.to_regprocedure(v_parse || '(text)');
    IF v_oid IS NULL THEN
        RAISE EXCEPTION 'invalid parse_fn'
            USING ERRCODE = '22023';
    END IF;
    SELECT p.prokind, p.proretset, p.prorettype, p.provolatile
      INTO v_kind, v_retset, v_rettype, v_vol
      FROM pg_proc p
     WHERE p.oid = v_oid;
    IF v_kind IS DISTINCT FROM 'f'
       OR v_retset
       OR v_rettype IS DISTINCT FROM 'jsonb'::regtype
       OR v_vol IS DISTINCT FROM 'i' THEN
        RAISE EXCEPTION 'invalid parse_fn'
            USING ERRCODE = '22023';
    END IF;

    v_oid := pg_catalog.to_regprocedure(v_observe || '(jsonb)');
    IF v_oid IS NULL THEN
        RAISE EXCEPTION 'invalid observe_fn'
            USING ERRCODE = '22023';
    END IF;
    SELECT p.prokind, p.proretset, p.prorettype, p.provolatile
      INTO v_kind, v_retset, v_rettype, v_vol
      FROM pg_proc p
     WHERE p.oid = v_oid;
    IF v_kind IS DISTINCT FROM 'f'
       OR v_retset
       OR v_rettype IS DISTINCT FROM 'jsonb'::regtype
       OR v_vol IS DISTINCT FROM 'i' THEN
        RAISE EXCEPTION 'invalid observe_fn'
            USING ERRCODE = '22023';
    END IF;

    identity := v_identity;
    version := v_version;
    description := v_description;
    action_surface := v_surface;
    parser_kind := v_parser;
    spawn_mode := v_spawn;
    env_enabled := v_env_enabled;
    env_workspace := v_workspace;
    env_inherit := v_inherit;
    observation_clip_chars := v_clip;
    observation_full_in_env := v_full;
    system_prompt := v_prompt;
    fold_fn := v_fold;
    parse_fn := v_parse;
    observe_fn := v_observe;
    metadata := p_definition;
    RETURN NEXT;
END;
$p19$;

CREATE OR REPLACE FUNCTION cordis.register_paradigm_policy(p_definition jsonb)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
DECLARE
    v record;
BEGIN
    SELECT * INTO v FROM cordis._validate_paradigm_policy(p_definition);
    INSERT INTO cordis.paradigm_policies (
        identity, version, description, action_surface, parser_kind, spawn_mode,
        env_enabled, env_workspace, env_inherit, observation_clip_chars,
        observation_full_in_env, system_prompt, fold_fn, parse_fn, observe_fn,
        metadata, registered_at, updated_at
    ) VALUES (
        v.identity, v.version, v.description, v.action_surface, v.parser_kind,
        v.spawn_mode, v.env_enabled, v.env_workspace, v.env_inherit,
        v.observation_clip_chars, v.observation_full_in_env, v.system_prompt,
        v.fold_fn, v.parse_fn, v.observe_fn, v.metadata,
        pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
    )
    ON CONFLICT (identity) DO UPDATE SET
        version = EXCLUDED.version,
        description = EXCLUDED.description,
        action_surface = EXCLUDED.action_surface,
        parser_kind = EXCLUDED.parser_kind,
        spawn_mode = EXCLUDED.spawn_mode,
        env_enabled = EXCLUDED.env_enabled,
        env_workspace = EXCLUDED.env_workspace,
        env_inherit = EXCLUDED.env_inherit,
        observation_clip_chars = EXCLUDED.observation_clip_chars,
        observation_full_in_env = EXCLUDED.observation_full_in_env,
        system_prompt = EXCLUDED.system_prompt,
        fold_fn = EXCLUDED.fold_fn,
        parse_fn = EXCLUDED.parse_fn,
        observe_fn = EXCLUDED.observe_fn,
        metadata = EXCLUDED.metadata,
        updated_at = pg_catalog.clock_timestamp();
    RETURN v.identity;
END;
$p19$;

CREATE OR REPLACE FUNCTION cordis.unregister_paradigm_policy(p_identity text)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
DECLARE
    n integer;
    v_identity text;
BEGIN
    IF p_identity IS NULL
       OR pg_catalog.btrim(p_identity) = ''
       OR pg_catalog.octet_length(pg_catalog.btrim(p_identity)) > 128
       OR pg_catalog.btrim(p_identity) !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid identity: %', p_identity
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(p_identity);
    DELETE FROM cordis.paradigm_policies
     WHERE identity = v_identity;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n > 0;
END;
$p19$;

CREATE OR REPLACE FUNCTION cordis.paradigm_policy(p_identity text)
RETURNS TABLE (
    identity text,
    version text,
    description text,
    action_surface text,
    parser_kind text,
    spawn_mode text,
    env_enabled boolean,
    env_workspace text,
    env_inherit text,
    observation_clip_chars integer,
    observation_full_in_env boolean,
    system_prompt text,
    fold_fn text,
    parse_fn text,
    observe_fn text,
    metadata jsonb,
    registered_at timestamptz,
    updated_at timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
DECLARE
    v_identity text;
BEGIN
    IF p_identity IS NULL
       OR pg_catalog.btrim(p_identity) = ''
       OR pg_catalog.octet_length(pg_catalog.btrim(p_identity)) > 128
       OR pg_catalog.btrim(p_identity) !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid identity: %', p_identity
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(p_identity);
    RETURN QUERY
    SELECT
        p.identity, p.version, p.description, p.action_surface, p.parser_kind,
        p.spawn_mode, p.env_enabled, p.env_workspace, p.env_inherit,
        p.observation_clip_chars, p.observation_full_in_env, p.system_prompt,
        p.fold_fn, p.parse_fn, p.observe_fn, p.metadata,
        p.registered_at, p.updated_at
      FROM cordis.paradigm_policies p
     WHERE p.identity = v_identity;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown paradigm: %', v_identity
            USING ERRCODE = '22023';
    END IF;
END;
$p19$;

CREATE OR REPLACE FUNCTION cordis.fold_codeact_messages(p_run_id text)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
    SELECT pg_catalog.jsonb_build_object(
        'p19_stub', true, 'slot', 'fold', 'run_id', p_run_id
    );
$p19$;

CREATE OR REPLACE FUNCTION cordis.fold_rlm_messages(p_run_id text)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
    SELECT pg_catalog.jsonb_build_object(
        'p19_stub', true, 'slot', 'fold', 'run_id', p_run_id
    );
$p19$;

CREATE OR REPLACE FUNCTION cordis.parse_codeact_decision(p_llm_text text)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
    SELECT pg_catalog.jsonb_build_object(
        'p19_stub', true,
        'slot', 'parse',
        'outcome', 'malformed',
        'action', null,
        'payload', null,
        'final_text', null
    );
$p19$;

CREATE OR REPLACE FUNCTION cordis.parse_rlm_decision(p_llm_text text)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
    SELECT pg_catalog.jsonb_build_object(
        'p19_stub', true,
        'slot', 'parse',
        'outcome', 'malformed',
        'action', null,
        'payload', null,
        'final_text', null
    );
$p19$;

CREATE OR REPLACE FUNCTION cordis.observe_codeact(p_raw jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
    SELECT pg_catalog.jsonb_build_object(
        'p19_stub', true,
        'slot', 'observe',
        'shown', pg_catalog.repeat('x', 2000),
        'stored', p_raw
    );
$p19$;

CREATE OR REPLACE FUNCTION cordis.observe_rlm(p_raw jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
    SELECT pg_catalog.jsonb_build_object(
        'p19_stub', true,
        'slot', 'observe',
        'shown', pg_catalog.repeat('x', 2000),
        'stored', p_raw
    );
$p19$;

CREATE OR REPLACE FUNCTION cordis.apply_observation_policy(
    p_obs jsonb,
    p_clip_chars integer,
    p_full_in_env boolean
)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p19$
DECLARE
    shown0 text;
    shown text;
    stored jsonb;
BEGIN
    IF p_obs IS NULL OR pg_catalog.jsonb_typeof(p_obs) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'invalid observation'
            USING ERRCODE = '22023';
    END IF;
    shown0 := COALESCE(p_obs ->> 'shown', '');
    IF p_clip_chars IS NULL THEN
        shown := shown0;
    ELSE
        shown := pg_catalog.left(shown0, p_clip_chars);
    END IF;
    IF p_full_in_env THEN
        stored := COALESCE(p_obs -> 'stored', 'null'::jsonb);
    ELSE
        stored := pg_catalog.to_jsonb(shown);
    END IF;
    RETURN p_obs || pg_catalog.jsonb_build_object('shown', shown, 'stored', stored);
END;
$p19$;

INSERT INTO cordis.paradigm_policies (
    identity, version, description, action_surface, parser_kind, spawn_mode,
    env_enabled, env_workspace, env_inherit, observation_clip_chars,
    observation_full_in_env, system_prompt, fold_fn, parse_fn, observe_fn,
    metadata, registered_at, updated_at
)
SELECT
    identity, version, description, action_surface, parser_kind, spawn_mode,
    env_enabled, env_workspace, env_inherit, observation_clip_chars,
    observation_full_in_env, system_prompt, fold_fn, parse_fn, observe_fn,
    metadata, pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
FROM cordis._validate_paradigm_policy($p19seed${
  "cordis_paradigm": {
    "identity": "codeact",
    "version": "0.1.0",
    "description": "CodeAct structured-tool policy for the shared loop kernel.",
    "action_surface": "structured_tools",
    "parser_kind": "json_tool_calls",
    "spawn_mode": "always_enqueue",
    "env_enabled": false,
    "env_workspace": "none",
    "env_inherit": "none",
    "observation_clip_chars": null,
    "observation_full_in_env": false,
    "system_prompt": "You are a CodeAct agent. Each step is one model turn plus its structured tool calls. Call tools as JSON. Do not execute free-form code. Context is in the prompt, not in an environment. In-step tools are not child runs.",
    "fold_fn": "cordis.fold_codeact_messages",
    "parse_fn": "cordis.parse_codeact_decision",
    "observe_fn": "cordis.observe_codeact"
  }
}$p19seed$::jsonb)
ON CONFLICT (identity) DO NOTHING;

INSERT INTO cordis.paradigm_policies (
    identity, version, description, action_surface, parser_kind, spawn_mode,
    env_enabled, env_workspace, env_inherit, observation_clip_chars,
    observation_full_in_env, system_prompt, fold_fn, parse_fn, observe_fn,
    metadata, registered_at, updated_at
)
SELECT
    identity, version, description, action_surface, parser_kind, spawn_mode,
    env_enabled, env_workspace, env_inherit, observation_clip_chars,
    observation_full_in_env, system_prompt, fold_fn, parse_fn, observe_fn,
    metadata, pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
FROM cordis._validate_paradigm_policy($p19seed${
  "cordis_paradigm": {
    "identity": "rlm",
    "version": "0.1.0",
    "description": "RLM prime-agent policy: run-scoped env plus always-enqueue children.",
    "action_surface": "env_repl",
    "parser_kind": "json_env_eval",
    "spawn_mode": "always_enqueue",
    "env_enabled": true,
    "env_workspace": "run_vars",
    "env_inherit": "named_grants_and_question",
    "observation_clip_chars": 4000,
    "observation_full_in_env": true,
    "system_prompt": "You are an RLM prime agent. Context lives in run-scoped environment variables; address it there. Observations you see are truncated; full results remain in the environment. Child work uses rlm() and returns only an admission handle. Do not wait for a child in this step. Do not inline large context into the model prompt.",
    "fold_fn": "cordis.fold_rlm_messages",
    "parse_fn": "cordis.parse_rlm_decision",
    "observe_fn": "cordis.observe_rlm"
  }
}$p19seed$::jsonb)
ON CONFLICT (identity) DO NOTHING;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p19'::text;
$$;
