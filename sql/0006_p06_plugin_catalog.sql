-- P06: unified plugin catalog. Replay-safe.
-- No GRANT/REVOKE/role/extension/public objects or transaction control.
-- plpgsql bodies use $p06$ so preflight dollar-quote stripping covers END and grant words.

CREATE TABLE IF NOT EXISTS cordis.plugin_catalog (
    identity text NOT NULL,
    version text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    locus text NOT NULL,
    invocation text NOT NULL,
    required_grants text[] NOT NULL DEFAULT '{}'::text[],
    effect_class text NOT NULL,
    retry_class text NOT NULL,
    reconciliation text NOT NULL,
    inject jsonb NOT NULL DEFAULT '[]'::jsonb,
    provide jsonb NOT NULL DEFAULT '[]'::jsonb,
    intercept jsonb NOT NULL DEFAULT '{}'::jsonb,
    capability jsonb NOT NULL DEFAULT '[]'::jsonb,
    session_scope text NOT NULL DEFAULT 'run',
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL,
    source_kind text NOT NULL,
    entrypoint regprocedure,
    refreshed_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT plugin_catalog_pkey PRIMARY KEY (identity),
    CONSTRAINT plugin_catalog_identity_check CHECK (
        pg_catalog.octet_length(identity) <= 128
        AND identity ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'
    ),
    CONSTRAINT plugin_catalog_version_check CHECK (
        pg_catalog.octet_length(version) BETWEEN 1 AND 64
        AND version ~ '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
    ),
    CONSTRAINT plugin_catalog_locus_check CHECK (locus IN ('in-db', 'host')),
    CONSTRAINT plugin_catalog_invocation_check CHECK (
        invocation IN ('queue', 'session_select', 'host_tool')
    ),
    CONSTRAINT plugin_catalog_locus_invocation_check CHECK (
        (locus = 'in-db' AND invocation IN ('queue', 'session_select'))
        OR (locus = 'host' AND invocation = 'host_tool')
    ),
    CONSTRAINT plugin_catalog_effect_class_check CHECK (
        effect_class IN ('read_only', 'transactional', 'external')
    ),
    CONSTRAINT plugin_catalog_retry_class_check CHECK (
        retry_class IN ('replayable', 'idempotent', 'non_retryable')
    ),
    CONSTRAINT plugin_catalog_reconciliation_check CHECK (
        reconciliation IN ('none', 'operation_key', 'manual')
    ),
    CONSTRAINT plugin_catalog_classification_check CHECK (
        (
            effect_class = 'read_only'
            AND retry_class = 'replayable'
            AND reconciliation = 'none'
        )
        OR (
            effect_class = 'transactional'
            AND reconciliation = 'none'
            AND retry_class IN ('replayable', 'idempotent', 'non_retryable')
        )
        OR (
            effect_class = 'external'
            AND reconciliation = 'operation_key'
            AND retry_class = 'idempotent'
        )
        OR (
            effect_class = 'external'
            AND reconciliation = 'manual'
            AND retry_class = 'non_retryable'
        )
    ),
    CONSTRAINT plugin_catalog_source_kind_check CHECK (
        source_kind IN ('comment', 'host_registration')
    ),
    CONSTRAINT plugin_catalog_source_entrypoint_check CHECK (
        (
            source_kind = 'comment'
            AND locus = 'in-db'
            AND entrypoint IS NOT NULL
        )
        OR (
            source_kind = 'host_registration'
            AND locus = 'host'
            AND invocation = 'host_tool'
            AND entrypoint IS NULL
        )
    ),
    CONSTRAINT plugin_catalog_required_grants_check CHECK (
        required_grants <@ ARRAY['run', 'named_corpus', 'event']::text[]
    )
);

CREATE INDEX IF NOT EXISTS plugin_catalog_locus_invocation_idx
    ON cordis.plugin_catalog (locus, invocation, identity);

CREATE INDEX IF NOT EXISTS plugin_catalog_required_grants_idx
    ON cordis.plugin_catalog USING gin (required_grants);

CREATE TABLE IF NOT EXISTS cordis.host_plugin_definitions (
    identity text NOT NULL,
    metadata jsonb NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT host_plugin_definitions_pkey PRIMARY KEY (identity),
    CONSTRAINT host_plugin_definitions_identity_check CHECK (
        pg_catalog.octet_length(identity) <= 128
        AND identity ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'
    ),
    CONSTRAINT host_plugin_definitions_metadata_object_check CHECK (
        pg_catalog.jsonb_typeof(metadata) = 'object'
    )
);

CREATE OR REPLACE FUNCTION cordis._validate_plugin_definition(
    p_definition jsonb,
    p_source_kind text
)
RETURNS TABLE (
    identity text,
    version text,
    name text,
    description text,
    locus text,
    invocation text,
    required_grants text[],
    effect_class text,
    retry_class text,
    reconciliation text,
    inject jsonb,
    provide jsonb,
    intercept jsonb,
    capability jsonb,
    session_scope text,
    config jsonb,
    metadata jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p06$
DECLARE
    plugin jsonb;
    v_identity text;
    v_version text;
    v_name text;
    v_description text;
    v_locus text;
    v_invocation text;
    v_grants text[];
    v_effect text;
    v_retry text;
    v_recon text;
    v_inject jsonb;
    v_provide jsonb;
    v_intercept jsonb;
    v_capability jsonb;
    v_scope text;
    v_config jsonb;
    v_raw jsonb;
    v_i int;
    v_n int;
    v_elem jsonb;
    v_key text;
    v_val jsonb;
    v_seen text[];
BEGIN
    IF p_source_kind IS NULL OR p_source_kind NOT IN ('comment', 'host_registration') THEN
        RAISE EXCEPTION 'invalid source_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_definition IS NULL OR jsonb_typeof(p_definition) <> 'object' THEN
        RAISE EXCEPTION 'definition must be a JSON object'
            USING ERRCODE = '22023';
    END IF;
    plugin := p_definition -> 'cordis_plugin';
    IF plugin IS NULL OR jsonb_typeof(plugin) <> 'object' THEN
        RAISE EXCEPTION 'cordis_plugin object is required'
            USING ERRCODE = '22023';
    END IF;

    v_identity := plugin ->> 'identity';
    v_version := plugin ->> 'version';
    v_locus := plugin ->> 'locus';
    v_invocation := plugin ->> 'invocation';
    v_effect := plugin ->> 'effect_class';
    v_retry := plugin ->> 'retry_class';
    v_recon := plugin ->> 'reconciliation';

    IF jsonb_typeof(plugin -> 'identity') IS DISTINCT FROM 'string'
       OR v_identity IS NULL OR btrim(v_identity) = '' THEN
        RAISE EXCEPTION 'identity is required'
            USING ERRCODE = '22023';
    END IF;
    v_identity := btrim(v_identity);
    IF octet_length(v_identity) > 128
       OR v_identity !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid identity: %', v_identity
            USING ERRCODE = '22023';
    END IF;

    IF jsonb_typeof(plugin -> 'version') IS DISTINCT FROM 'string'
       OR v_version IS NULL OR btrim(v_version) = '' THEN
        RAISE EXCEPTION 'version is required'
            USING ERRCODE = '22023';
    END IF;
    v_version := btrim(v_version);
    IF octet_length(v_version) NOT BETWEEN 1 AND 64
       OR v_version !~ '^[A-Za-z0-9][A-Za-z0-9._+-]*$' THEN
        RAISE EXCEPTION 'invalid version: %', v_version
            USING ERRCODE = '22023';
    END IF;

    IF jsonb_typeof(plugin -> 'locus') IS DISTINCT FROM 'string'
       OR jsonb_typeof(plugin -> 'invocation') IS DISTINCT FROM 'string'
       OR jsonb_typeof(plugin -> 'effect_class') IS DISTINCT FROM 'string'
       OR jsonb_typeof(plugin -> 'retry_class') IS DISTINCT FROM 'string'
       OR jsonb_typeof(plugin -> 'reconciliation') IS DISTINCT FROM 'string'
       OR v_locus IS NULL OR btrim(v_locus) = ''
       OR v_invocation IS NULL OR btrim(v_invocation) = ''
       OR v_effect IS NULL OR btrim(v_effect) = ''
       OR v_retry IS NULL OR btrim(v_retry) = ''
       OR v_recon IS NULL OR btrim(v_recon) = '' THEN
        RAISE EXCEPTION 'required scalar fields must be non-empty strings'
            USING ERRCODE = '22023';
    END IF;
    v_locus := btrim(v_locus);
    v_invocation := btrim(v_invocation);
    v_effect := btrim(v_effect);
    v_retry := btrim(v_retry);
    v_recon := btrim(v_recon);

    IF plugin ? 'name' THEN
        IF jsonb_typeof(plugin -> 'name') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'name must be a string'
                USING ERRCODE = '22023';
        END IF;
        v_name := plugin ->> 'name';
        IF v_name IS NULL OR btrim(v_name) = '' THEN
            RAISE EXCEPTION 'invalid name'
                USING ERRCODE = '22023';
        END IF;
        v_name := btrim(v_name);
    ELSE
        v_name := v_identity;
    END IF;
    IF octet_length(v_name) NOT BETWEEN 1 AND 128 OR v_name ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid name'
            USING ERRCODE = '22023';
    END IF;

    IF plugin ? 'description' THEN
        IF jsonb_typeof(plugin -> 'description') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'description must be a string'
                USING ERRCODE = '22023';
        END IF;
        v_description := plugin ->> 'description';
        IF v_description IS NULL OR btrim(v_description) = '' THEN
            RAISE EXCEPTION 'invalid description'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        v_description := v_name;
    END IF;
    IF char_length(v_description) NOT BETWEEN 1 AND 500
       OR v_description ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid description'
            USING ERRCODE = '22023';
    END IF;

    IF plugin ? 'session_scope' THEN
        IF jsonb_typeof(plugin -> 'session_scope') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'session_scope must be a string'
                USING ERRCODE = '22023';
        END IF;
        v_scope := btrim(COALESCE(plugin ->> 'session_scope', ''));
        IF v_scope = '' THEN
            RAISE EXCEPTION 'invalid session_scope'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        v_scope := 'run';
    END IF;
    IF octet_length(v_scope) NOT BETWEEN 1 AND 64 OR v_scope ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid session_scope'
            USING ERRCODE = '22023';
    END IF;

    IF v_locus NOT IN ('in-db', 'host')
       OR v_invocation NOT IN ('queue', 'session_select', 'host_tool') THEN
        RAISE EXCEPTION 'invalid locus or invocation'
            USING ERRCODE = '22023';
    END IF;
    IF NOT (
        (v_locus = 'in-db' AND v_invocation IN ('queue', 'session_select'))
        OR (v_locus = 'host' AND v_invocation = 'host_tool')
    ) THEN
        RAISE EXCEPTION 'illegal locus/invocation pair: % / %', v_locus, v_invocation
            USING ERRCODE = '22023';
    END IF;

    IF p_source_kind = 'comment' THEN
        IF v_locus <> 'in-db' THEN
            RAISE EXCEPTION 'comment source requires locus in-db'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        IF v_locus <> 'host' OR v_invocation <> 'host_tool' THEN
            RAISE EXCEPTION 'host_registration requires locus host and invocation host_tool'
                USING ERRCODE = '22023';
        END IF;
    END IF;

    IF plugin ? 'required_grants' THEN
        v_raw := plugin -> 'required_grants';
        IF v_raw IS NULL OR jsonb_typeof(v_raw) <> 'array' THEN
            RAISE EXCEPTION 'required_grants must be a JSON array'
                USING ERRCODE = '22023';
        END IF;
        v_grants := ARRAY[]::text[];
        v_seen := ARRAY[]::text[];
        v_n := jsonb_array_length(v_raw);
        FOR v_i IN 0 .. v_n - 1 LOOP
            v_elem := v_raw -> v_i;
            IF jsonb_typeof(v_elem) <> 'string' THEN
                RAISE EXCEPTION 'required_grants elements must be strings'
                    USING ERRCODE = '22023';
            END IF;
            IF (v_elem #>> '{}') NOT IN ('run', 'named_corpus', 'event') THEN
                RAISE EXCEPTION 'invalid required grant kind: %', v_elem #>> '{}'
                    USING ERRCODE = '22023';
            END IF;
            IF (v_elem #>> '{}') = ANY (v_seen) THEN
                RAISE EXCEPTION 'duplicate required grant kind: %', v_elem #>> '{}'
                    USING ERRCODE = '22023';
            END IF;
            v_seen := array_append(v_seen, v_elem #>> '{}');
            v_grants := array_append(v_grants, v_elem #>> '{}');
        END LOOP;
    ELSE
        v_grants := ARRAY[]::text[];
    END IF;

    IF plugin ? 'inject' THEN
        v_inject := plugin -> 'inject';
        IF v_inject IS NULL THEN
            RAISE EXCEPTION 'inject must not be json null'
                USING ERRCODE = '22023';
        ELSIF jsonb_typeof(v_inject) = 'array' THEN
            v_n := jsonb_array_length(v_inject);
            FOR v_i IN 0 .. v_n - 1 LOOP
                IF jsonb_typeof(v_inject -> v_i) <> 'string' THEN
                    RAISE EXCEPTION 'inject array elements must be strings'
                        USING ERRCODE = '22023';
                END IF;
            END LOOP;
        ELSIF jsonb_typeof(v_inject) = 'object' THEN
            NULL;
        ELSE
            RAISE EXCEPTION 'inject must be a JSON array or object'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        v_inject := '[]'::jsonb;
    END IF;

    IF plugin ? 'provide' THEN
        v_provide := plugin -> 'provide';
        IF v_provide IS NULL THEN
            RAISE EXCEPTION 'provide must not be json null'
                USING ERRCODE = '22023';
        ELSIF jsonb_typeof(v_provide) = 'string' THEN
            NULL;
        ELSIF jsonb_typeof(v_provide) = 'array' THEN
            v_n := jsonb_array_length(v_provide);
            FOR v_i IN 0 .. v_n - 1 LOOP
                IF jsonb_typeof(v_provide -> v_i) <> 'string' THEN
                    RAISE EXCEPTION 'provide array elements must be strings'
                        USING ERRCODE = '22023';
                END IF;
            END LOOP;
        ELSE
            RAISE EXCEPTION 'provide must be a string or array of strings'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        v_provide := '[]'::jsonb;
    END IF;

    IF plugin ? 'intercept' THEN
        v_intercept := plugin -> 'intercept';
        IF v_intercept IS NULL OR jsonb_typeof(v_intercept) <> 'object' THEN
            RAISE EXCEPTION 'intercept must be a JSON object'
                USING ERRCODE = '22023';
        END IF;
        FOR v_key, v_val IN SELECT key, value FROM jsonb_each(v_intercept) LOOP
            IF jsonb_typeof(v_val) <> 'boolean' THEN
                RAISE EXCEPTION 'intercept values must be booleans'
                    USING ERRCODE = '22023';
            END IF;
        END LOOP;
    ELSE
        v_intercept := '{}'::jsonb;
    END IF;

    IF plugin ? 'capability' THEN
        v_capability := plugin -> 'capability';
        IF v_capability IS NULL OR jsonb_typeof(v_capability) = 'null' THEN
            RAISE EXCEPTION 'capability must not be json null'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        v_capability := '[]'::jsonb;
    END IF;

    IF plugin ? 'config' THEN
        v_config := plugin -> 'config';
        IF v_config IS NULL OR jsonb_typeof(v_config) <> 'object' THEN
            RAISE EXCEPTION 'config must be a JSON object'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        v_config := '{}'::jsonb;
    END IF;

    IF v_effect NOT IN ('read_only', 'transactional', 'external')
       OR v_retry NOT IN ('replayable', 'idempotent', 'non_retryable')
       OR v_recon NOT IN ('none', 'operation_key', 'manual') THEN
        RAISE EXCEPTION 'invalid effect/retry/reconciliation class'
            USING ERRCODE = '22023';
    END IF;
    IF NOT (
        (v_effect = 'read_only' AND v_retry = 'replayable' AND v_recon = 'none')
        OR (v_effect = 'transactional' AND v_recon = 'none')
        OR (v_effect = 'external' AND v_recon = 'operation_key' AND v_retry = 'idempotent')
        OR (v_effect = 'external' AND v_recon = 'manual' AND v_retry = 'non_retryable')
    ) THEN
        RAISE EXCEPTION 'illegal effect/retry/reconciliation combination'
            USING ERRCODE = '22023';
    END IF;

    identity := v_identity;
    version := v_version;
    name := v_name;
    description := v_description;
    locus := v_locus;
    invocation := v_invocation;
    required_grants := v_grants;
    effect_class := v_effect;
    retry_class := v_retry;
    reconciliation := v_recon;
    inject := v_inject;
    provide := v_provide;
    intercept := v_intercept;
    capability := v_capability;
    session_scope := v_scope;
    config := v_config;
    metadata := p_definition;
    RETURN NEXT;
END;
$p06$;

CREATE OR REPLACE FUNCTION cordis.refresh_plugins()
RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p06$
DECLARE
    r record;
    nrm record;
    v_cmt text;
    v_trim text;
    v_meta jsonb;
    v_acc jsonb := '[]'::jsonb;
    v_seen text[] := ARRAY[]::text[];
    v_id text;
    v_sig text;
    v_detail text;
    v_ts timestamptz;
    v_n integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('pg_cordis.plugin_refresh'));

    FOR r IN
        SELECT p.oid,
               p.proname,
               p.prokind,
               p.prorettype,
               obj_description(p.oid, 'pg_proc') AS cmt
          FROM pg_proc p
          JOIN pg_namespace ns ON ns.oid = p.pronamespace
         WHERE ns.nspname = 'cordis'
         ORDER BY p.oid, pg_get_function_identity_arguments(p.oid)
    LOOP
        v_cmt := r.cmt;
        IF v_cmt IS NULL THEN
            CONTINUE;
        END IF;
        v_trim := btrim(v_cmt);
        IF v_trim = '' OR left(v_trim, 1) <> '{' THEN
            CONTINUE;
        END IF;
        v_sig := format(
            'cordis.%s(%s)',
            r.proname,
            pg_get_function_identity_arguments(r.oid)
        );
        BEGIN
            v_meta := v_trim::jsonb;
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION 'refresh_plugins: malformed JSON on %', v_sig
                USING ERRCODE = '22023';
        END;
        IF jsonb_typeof(v_meta) <> 'object' THEN
            RAISE EXCEPTION 'refresh_plugins: malformed JSON on %', v_sig
                USING ERRCODE = '22023';
        END IF;

        IF (v_meta ? 'job_handler') AND (v_meta ? 'workbench_plugin') THEN
            RAISE EXCEPTION 'refresh_plugins: mutex on %', v_sig
                USING ERRCODE = '22023';
        END IF;
        IF (v_meta ? 'cordis_plugin')
           AND ((v_meta ? 'job_handler') OR (v_meta ? 'workbench_plugin')) THEN
            RAISE EXCEPTION 'refresh_plugins: mutex on %', v_sig
                USING ERRCODE = '22023';
        END IF;
        IF NOT (v_meta ? 'cordis_plugin') THEN
            CONTINUE;
        END IF;
        IF r.prokind <> 'f' THEN
            RAISE EXCEPTION
                'refresh_plugins: % is not an ordinary function',
                v_sig
                USING ERRCODE = '22023';
        END IF;

        BEGIN
            SELECT * INTO nrm
              FROM cordis._validate_plugin_definition(v_meta, 'comment');
        EXCEPTION WHEN SQLSTATE '22023' THEN
            GET STACKED DIAGNOSTICS v_detail = MESSAGE_TEXT;
            RAISE EXCEPTION
                'refresh_plugins: invalid metadata on %: %',
                v_sig, v_detail
                USING ERRCODE = '22023';
        END;

        IF nrm.invocation = 'session_select' AND r.prorettype <> 'jsonb'::regtype THEN
            RAISE EXCEPTION
                'refresh_plugins: session_select % must return jsonb',
                v_sig
                USING ERRCODE = '22023';
        END IF;

        v_id := nrm.identity;
        IF v_id = ANY (v_seen) THEN
            RAISE EXCEPTION 'refresh_plugins: duplicate identity %', v_id
                USING ERRCODE = '22023';
        END IF;
        v_seen := array_append(v_seen, v_id);
        v_acc := v_acc || jsonb_build_array(jsonb_build_object(
            'identity', nrm.identity,
            'version', nrm.version,
            'name', nrm.name,
            'description', nrm.description,
            'locus', nrm.locus,
            'invocation', nrm.invocation,
            'required_grants', to_jsonb(nrm.required_grants),
            'effect_class', nrm.effect_class,
            'retry_class', nrm.retry_class,
            'reconciliation', nrm.reconciliation,
            'inject', nrm.inject,
            'provide', nrm.provide,
            'intercept', nrm.intercept,
            'capability', nrm.capability,
            'session_scope', nrm.session_scope,
            'config', nrm.config,
            'metadata', nrm.metadata,
            'source_kind', 'comment',
            'entrypoint_oid', r.oid
        ));
    END LOOP;

    FOR r IN
        SELECT d.identity, d.metadata
          FROM cordis.host_plugin_definitions d
         ORDER BY d.identity
    LOOP
        BEGIN
            SELECT * INTO nrm
              FROM cordis._validate_plugin_definition(r.metadata, 'host_registration');
        EXCEPTION WHEN SQLSTATE '22023' THEN
            GET STACKED DIAGNOSTICS v_detail = MESSAGE_TEXT;
            RAISE EXCEPTION
                'refresh_plugins: invalid metadata on host identity %: %',
                r.identity, v_detail
                USING ERRCODE = '22023';
        END;
        IF nrm.identity IS DISTINCT FROM r.identity THEN
            RAISE EXCEPTION
                'refresh_plugins: host source key % does not match metadata identity %',
                r.identity, nrm.identity
                USING ERRCODE = '22023';
        END IF;
        v_id := nrm.identity;
        IF v_id = ANY (v_seen) THEN
            RAISE EXCEPTION 'refresh_plugins: duplicate identity %', v_id
                USING ERRCODE = '22023';
        END IF;
        v_seen := array_append(v_seen, v_id);
        v_acc := v_acc || jsonb_build_array(jsonb_build_object(
            'identity', nrm.identity,
            'version', nrm.version,
            'name', nrm.name,
            'description', nrm.description,
            'locus', nrm.locus,
            'invocation', nrm.invocation,
            'required_grants', to_jsonb(nrm.required_grants),
            'effect_class', nrm.effect_class,
            'retry_class', nrm.retry_class,
            'reconciliation', nrm.reconciliation,
            'inject', nrm.inject,
            'provide', nrm.provide,
            'intercept', nrm.intercept,
            'capability', nrm.capability,
            'session_scope', nrm.session_scope,
            'config', nrm.config,
            'metadata', nrm.metadata,
            'source_kind', 'host_registration',
            'entrypoint_oid', NULL
        ));
    END LOOP;

    v_ts := clock_timestamp();
    DELETE FROM cordis.plugin_catalog;
    INSERT INTO cordis.plugin_catalog (
        identity,
        version,
        name,
        description,
        locus,
        invocation,
        required_grants,
        effect_class,
        retry_class,
        reconciliation,
        inject,
        provide,
        intercept,
        capability,
        session_scope,
        config,
        metadata,
        source_kind,
        entrypoint,
        refreshed_at
    )
    SELECT
        x.identity,
        x.version,
        x.name,
        x.description,
        x.locus,
        x.invocation,
        COALESCE(
            ARRAY(SELECT jsonb_array_elements_text(x.required_grants)),
            ARRAY[]::text[]
        ),
        x.effect_class,
        x.retry_class,
        x.reconciliation,
        x.inject,
        x.provide,
        x.intercept,
        x.capability,
        x.session_scope,
        x.config,
        x.metadata,
        x.source_kind,
        CASE
            WHEN x.entrypoint_oid IS NULL THEN NULL
            ELSE x.entrypoint_oid::oid::regprocedure
        END,
        v_ts
      FROM jsonb_to_recordset(v_acc) AS x(
        identity text,
        version text,
        name text,
        description text,
        locus text,
        invocation text,
        required_grants jsonb,
        effect_class text,
        retry_class text,
        reconciliation text,
        inject jsonb,
        provide jsonb,
        intercept jsonb,
        capability jsonb,
        session_scope text,
        config jsonb,
        metadata jsonb,
        source_kind text,
        entrypoint_oid oid
      );
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n;
END;
$p06$;

CREATE OR REPLACE FUNCTION cordis.register_host_plugin(p_definition jsonb)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p06$
DECLARE
    nrm record;
    t0 timestamptz;
BEGIN
    SELECT * INTO nrm
      FROM cordis._validate_plugin_definition(p_definition, 'host_registration');
    t0 := clock_timestamp();
    INSERT INTO cordis.host_plugin_definitions AS d (
        identity, metadata, registered_at, updated_at
    )
    VALUES (nrm.identity, p_definition, t0, t0)
    ON CONFLICT (identity) DO UPDATE
        SET metadata = EXCLUDED.metadata,
            updated_at = t0;
    PERFORM cordis.refresh_plugins();
    RETURN nrm.identity;
END;
$p06$;

CREATE OR REPLACE FUNCTION cordis.unregister_host_plugin(p_identity text)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p06$
DECLARE
    n integer;
BEGIN
    IF p_identity IS NULL
       OR btrim(p_identity) = ''
       OR octet_length(btrim(p_identity)) > 128
       OR btrim(p_identity) !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid identity: %', p_identity
            USING ERRCODE = '22023';
    END IF;
    DELETE FROM cordis.host_plugin_definitions
     WHERE identity = btrim(p_identity);
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN
        PERFORM cordis.refresh_plugins();
        RETURN true;
    END IF;
    RETURN false;
END;
$p06$;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p06'::text;
$$;

SELECT cordis.refresh_plugins();
