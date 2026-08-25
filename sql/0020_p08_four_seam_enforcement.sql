-- P08: four-seam enforcement. Replay-safe.
-- No GRANT/REVOKE/role/extension/public objects or transaction control.
-- plpgsql bodies use $p08$ so preflight dollar-quote stripping covers END and grant words.
-- File number 0020 is required so P19 fold stubs in 0019 cannot overwrite these bodies.

CREATE TABLE IF NOT EXISTS cordis.isolation_seams (
    seam text NOT NULL,
    gate_fn regprocedure NOT NULL,
    contract_version text NOT NULL,
    installed_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT isolation_seams_pkey PRIMARY KEY (seam),
    CONSTRAINT isolation_seams_gate_fn_key UNIQUE (gate_fn),
    CONSTRAINT isolation_seams_name_check CHECK (
        seam IN ('recall', 'fold', 'env_read', 'tool_dispatch')
    ),
    CONSTRAINT isolation_seams_contract_check CHECK (
        contract_version = 'p08.v1'
    )
);

CREATE TABLE IF NOT EXISTS cordis.isolation_fold_handlers (
    fold_fn regprocedure NOT NULL,
    contract_version text NOT NULL,
    installed_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT isolation_fold_handlers_pkey PRIMARY KEY (fold_fn),
    CONSTRAINT isolation_fold_handlers_contract_check CHECK (
        contract_version = 'p08.v1'
    )
);

CREATE OR REPLACE FUNCTION cordis.isolation_feature_status()
RETURNS TABLE (
    enabled boolean,
    missing_seams text[]
)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
DECLARE
    v_missing text[] := ARRAY[]::text[];
    v_expected regprocedure;
    v_row cordis.isolation_seams%ROWTYPE;
    v_handler regprocedure;
BEGIN
    v_expected := pg_catalog.to_regprocedure(
        'cordis.read_run_env(text,uuid,text,text)'
    );
    SELECT * INTO v_row FROM cordis.isolation_seams WHERE seam = 'env_read';
    IF v_expected IS NULL
       OR NOT FOUND
       OR v_row.contract_version IS DISTINCT FROM 'p08.v1'
       OR v_row.gate_fn IS DISTINCT FROM v_expected THEN
        v_missing := v_missing || ARRAY['env_read'::text];
    END IF;

    v_expected := pg_catalog.to_regprocedure(
        'cordis.fold_slice_messages(text,uuid,text)'
    );
    SELECT * INTO v_row FROM cordis.isolation_seams WHERE seam = 'fold';
    IF v_expected IS NULL
       OR NOT FOUND
       OR v_row.contract_version IS DISTINCT FROM 'p08.v1'
       OR v_row.gate_fn IS DISTINCT FROM v_expected THEN
        v_missing := v_missing || ARRAY['fold'::text];
    ELSE
        v_handler := pg_catalog.to_regprocedure(
            'cordis.fold_codeact_messages(text)'
        );
        IF v_handler IS NULL
           OR NOT EXISTS (
                SELECT 1 FROM cordis.isolation_fold_handlers h
                 WHERE h.fold_fn = v_handler
                   AND h.contract_version = 'p08.v1'
           ) THEN
            v_missing := v_missing || ARRAY['fold'::text];
        ELSE
            v_handler := pg_catalog.to_regprocedure(
                'cordis.fold_rlm_messages(text)'
            );
            IF v_handler IS NULL
               OR NOT EXISTS (
                    SELECT 1 FROM cordis.isolation_fold_handlers h
                     WHERE h.fold_fn = v_handler
                       AND h.contract_version = 'p08.v1'
               ) THEN
                v_missing := v_missing || ARRAY['fold'::text];
            END IF;
        END IF;
    END IF;

    v_expected := pg_catalog.to_regprocedure(
        'cordis.recall_named_corpus(text,uuid,text)'
    );
    SELECT * INTO v_row FROM cordis.isolation_seams WHERE seam = 'recall';
    IF v_expected IS NULL
       OR NOT FOUND
       OR v_row.contract_version IS DISTINCT FROM 'p08.v1'
       OR v_row.gate_fn IS DISTINCT FROM v_expected THEN
        v_missing := v_missing || ARRAY['recall'::text];
    END IF;

    v_expected := pg_catalog.to_regprocedure(
        'cordis.authorize_tool_dispatch(text,uuid,text,jsonb)'
    );
    SELECT * INTO v_row FROM cordis.isolation_seams WHERE seam = 'tool_dispatch';
    IF v_expected IS NULL
       OR NOT FOUND
       OR v_row.contract_version IS DISTINCT FROM 'p08.v1'
       OR v_row.gate_fn IS DISTINCT FROM v_expected THEN
        v_missing := v_missing || ARRAY['tool_dispatch'::text];
    END IF;

    enabled := (v_missing = ARRAY[]::text[]);
    missing_seams := v_missing;
    RETURN NEXT;
END;
$p08$;

CREATE OR REPLACE FUNCTION cordis._require_isolation_feature()
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
DECLARE
    v_enabled boolean;
    v_missing text[];
BEGIN
    SELECT s.enabled, s.missing_seams
      INTO v_enabled, v_missing
      FROM cordis.isolation_feature_status() AS s;
    IF NOT v_enabled THEN
        RAISE EXCEPTION 'P08_ISOLATION_FEATURE_CLOSED'
            USING ERRCODE = '42501',
                  DETAIL = 'missing_seams=' || pg_catalog.array_to_string(
                      COALESCE(v_missing, ARRAY[]::text[]), ','
                  );
    END IF;
END;
$p08$;

CREATE OR REPLACE FUNCTION cordis.emit_step_scoped(
    p_claim_token uuid,
    p_run_id text,
    p_slice_id uuid,
    p_kind text,
    p_payload jsonb,
    p_step_name text DEFAULT NULL,
    p_corpus_ids text[] DEFAULT ARRAY[]::text[],
    p_extend_seconds integer DEFAULT 90
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
DECLARE
    v_normalized text[] := ARRAY[]::text[];
    v_id text;
    v_payload jsonb;
    v_seen text[] := ARRAY[]::text[];
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_payload IS NULL OR pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'invalid payload'
            USING ERRCODE = '22023';
    END IF;
    IF p_extend_seconds IS NULL OR p_extend_seconds <= 0 THEN
        RAISE EXCEPTION 'invalid extend seconds'
            USING ERRCODE = '22023';
    END IF;
    IF p_corpus_ids IS NULL THEN
        RAISE EXCEPTION 'invalid corpus ids'
            USING ERRCODE = '22023';
    END IF;
    FOREACH v_id IN ARRAY p_corpus_ids LOOP
        IF v_id IS NULL OR v_id !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
            RAISE EXCEPTION 'invalid corpus ids'
                USING ERRCODE = '22023';
        END IF;
        IF v_id = ANY (v_seen) THEN
            RAISE EXCEPTION 'invalid corpus ids'
                USING ERRCODE = '22023';
        END IF;
        v_seen := v_seen || v_id;
    END LOOP;
    SELECT COALESCE(pg_catalog.array_agg(x ORDER BY x), ARRAY[]::text[])
      INTO v_normalized
      FROM pg_catalog.unnest(v_seen) AS x;
    IF p_payload ? 'p08_scope' THEN
        RAISE EXCEPTION 'reserved field p08_scope'
            USING ERRCODE = '22023';
    END IF;
    PERFORM cordis._require_isolation_feature();
    PERFORM * FROM cordis.slice_live_grants(p_run_id, p_slice_id);
    IF NOT cordis.slice_has_grant(p_run_id, p_slice_id, 'run', '') THEN
        RAISE EXCEPTION 'P08_SCOPED_APPEND_RUN_GRANT_REQUIRED'
            USING ERRCODE = '42501';
    END IF;
    FOREACH v_id IN ARRAY v_normalized LOOP
        IF NOT cordis.slice_has_grant(
            p_run_id, p_slice_id, 'named_corpus', v_id
        ) THEN
            RAISE EXCEPTION 'P08_SCOPED_APPEND_CORPUS_GRANT_REQUIRED'
                USING ERRCODE = '42501';
        END IF;
    END LOOP;
    v_payload := p_payload || pg_catalog.jsonb_build_object(
        'p08_scope',
        pg_catalog.jsonb_build_object(
            'slice_id', p_slice_id::text,
            'named_corpora', pg_catalog.to_jsonb(v_normalized)
        )
    );
    RETURN cordis.emit_step_claimed(
        p_claim_token,
        p_run_id,
        p_kind,
        v_payload,
        p_step_name,
        p_extend_seconds
    );
END;
$p08$;

CREATE OR REPLACE FUNCTION cordis.recall_named_corpus(
    p_run_id text,
    p_slice_id uuid,
    p_corpus_id text
)
RETURNS TABLE (
    grant_id uuid,
    corpus_id text,
    label text
)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_corpus_id IS NULL OR p_corpus_id !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
        RAISE EXCEPTION 'invalid grant target'
            USING ERRCODE = '22023';
    END IF;
    PERFORM cordis._require_isolation_feature();
    RETURN QUERY
    SELECT g.grant_id, g.target, nc.label
      FROM cordis.slice_live_grants(p_run_id, p_slice_id) AS g
      JOIN cordis.named_corpora AS nc ON nc.corpus_id = g.target
     WHERE g.kind = 'named_corpus'
       AND g.target = p_corpus_id;
END;
$p08$;

CREATE OR REPLACE FUNCTION cordis._fold_scoped_history(
    p_run_id text,
    p_paradigm text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
DECLARE
    v_setting text;
    v_slice uuid;
    v_live text[] := ARRAY[]::text[];
    v_history jsonb := '[]'::jsonb;
    v_as_of bigint := 0;
    v_ordinal integer := 0;
    r record;
    v_scope jsonb;
    v_corpora jsonb;
    v_elem jsonb;
    v_cid text;
    v_ok boolean;
    v_payload jsonb;
    v_idx integer;
    v_n integer;
    v_ids text[];
BEGIN
    v_setting := pg_catalog.current_setting('cordis.p08_calling_slice_id', true);
    IF v_setting IS NULL OR pg_catalog.btrim(v_setting) = '' THEN
        RAISE EXCEPTION 'P08_INVALID_CALLING_SLICE_CONTEXT'
            USING ERRCODE = '42501';
    END IF;
    BEGIN
        v_slice := v_setting::uuid;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'P08_INVALID_CALLING_SLICE_CONTEXT'
            USING ERRCODE = '42501';
    END;
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    PERFORM cordis._require_isolation_feature();
    PERFORM * FROM cordis.slice_live_grants(p_run_id, v_slice);
    IF v_slice::text IS DISTINCT FROM v_setting THEN
        RAISE EXCEPTION 'P08_INVALID_CALLING_SLICE_CONTEXT'
            USING ERRCODE = '42501';
    END IF;
    IF NOT cordis.slice_has_grant(p_run_id, v_slice, 'run', '') THEN
        RAISE EXCEPTION 'P08_FOLD_RUN_GRANT_REQUIRED'
            USING ERRCODE = '42501';
    END IF;
    SELECT COALESCE(pg_catalog.array_agg(g.target ORDER BY g.target), ARRAY[]::text[])
      INTO v_live
      FROM cordis.slice_live_grants(p_run_id, v_slice) AS g
     WHERE g.kind = 'named_corpus';
    FOR r IN
        SELECT s.seq, s.kind, s.step_name, s.payload
          FROM cordis.agent_steps AS s
         WHERE s.run_id = p_run_id
         ORDER BY s.seq ASC
    LOOP
        IF r.payload IS NULL
           OR pg_catalog.jsonb_typeof(r.payload) IS DISTINCT FROM 'object' THEN
            CONTINUE;
        END IF;
        v_scope := r.payload -> 'p08_scope';
        IF v_scope IS NULL
           OR pg_catalog.jsonb_typeof(v_scope) IS DISTINCT FROM 'object' THEN
            CONTINUE;
        END IF;
        IF pg_catalog.jsonb_typeof(v_scope -> 'slice_id') IS DISTINCT FROM 'string'
           OR (v_scope ->> 'slice_id') IS DISTINCT FROM v_slice::text THEN
            CONTINUE;
        END IF;
        v_corpora := v_scope -> 'named_corpora';
        IF v_corpora IS NULL
           OR pg_catalog.jsonb_typeof(v_corpora) IS DISTINCT FROM 'array' THEN
            CONTINUE;
        END IF;
        v_ok := true;
        v_ids := ARRAY[]::text[];
        v_n := pg_catalog.jsonb_array_length(v_corpora);
        FOR v_idx IN 0 .. GREATEST(v_n - 1, -1) LOOP
            EXIT WHEN v_n = 0;
            IF pg_catalog.jsonb_typeof(v_corpora -> v_idx)
               IS DISTINCT FROM 'string' THEN
                v_ok := false;
                EXIT;
            END IF;
            v_cid := v_corpora ->> v_idx;
            IF v_cid IS NULL OR v_cid !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
                v_ok := false;
                EXIT;
            END IF;
            IF v_cid = ANY (v_ids) THEN
                v_ok := false;
                EXIT;
            END IF;
            v_ids := v_ids || v_cid;
            IF v_live IS NULL OR NOT (v_cid = ANY (v_live)) THEN
                v_ok := false;
                EXIT;
            END IF;
        END LOOP;
        IF NOT v_ok THEN
            CONTINUE;
        END IF;
        v_payload := r.payload - 'p08_scope';
        v_ordinal := v_ordinal + 1;
        v_as_of := r.seq;
        v_elem := pg_catalog.jsonb_build_object(
            'ordinal', v_ordinal,
            'seq', r.seq,
            'kind', r.kind,
            'step_name', pg_catalog.to_jsonb(r.step_name),
            'scope', v_scope,
            'payload', v_payload
        );
        v_history := v_history || pg_catalog.jsonb_build_array(v_elem);
    END LOOP;
    RETURN pg_catalog.jsonb_build_object(
        'protocol', 'cordis.p08.fold.v1',
        'paradigm', p_paradigm,
        'run_id', p_run_id,
        'slice_id', v_slice::text,
        'named_corpora', pg_catalog.to_jsonb(v_live),
        'as_of_seq', v_as_of,
        'history', v_history
    );
END;
$p08$;

CREATE OR REPLACE FUNCTION cordis.fold_codeact_messages(p_run_id text)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
    SELECT CASE
        WHEN pg_catalog.btrim(
                 COALESCE(
                     pg_catalog.current_setting(
                         'cordis.p08_calling_slice_id', true
                     ),
                     ''::text
                 )
             ) = ''::text
        THEN pg_catalog.jsonb_build_object(
                 'p19_stub', true, 'slot', 'fold', 'run_id', p_run_id
             )
        ELSE cordis._fold_scoped_history(p_run_id, 'codeact')
    END;
$p08$;

CREATE OR REPLACE FUNCTION cordis.fold_rlm_messages(p_run_id text)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
    SELECT CASE
        WHEN pg_catalog.btrim(
                 COALESCE(
                     pg_catalog.current_setting(
                         'cordis.p08_calling_slice_id', true
                     ),
                     ''::text
                 )
             ) = ''::text
        THEN pg_catalog.jsonb_build_object(
                 'p19_stub', true, 'slot', 'fold', 'run_id', p_run_id
             )
        ELSE cordis._fold_scoped_history(p_run_id, 'rlm')
    END;
$p08$;

CREATE OR REPLACE FUNCTION cordis.fold_slice_messages(
    p_run_id text,
    p_slice_id uuid,
    p_paradigm text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
DECLARE
    v_identity text;
    v_policy record;
    v_reg regprocedure;
    v_call text;
    v_prior text;
    v_slot jsonb;
    v_folded jsonb;
    v_nsp text;
    v_name text;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_paradigm IS NULL
       OR pg_catalog.btrim(p_paradigm) = ''
       OR pg_catalog.octet_length(pg_catalog.btrim(p_paradigm)) > 128
       OR pg_catalog.btrim(p_paradigm)
          !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid identity'
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(p_paradigm);
    PERFORM cordis._require_isolation_feature();
    PERFORM * FROM cordis.slice_live_grants(p_run_id, p_slice_id);
    IF NOT cordis.slice_has_grant(p_run_id, p_slice_id, 'run', '') THEN
        RAISE EXCEPTION 'P08_FOLD_RUN_GRANT_REQUIRED'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_policy FROM cordis.paradigm_policy(v_identity);
    v_reg := pg_catalog.to_regprocedure(v_policy.fold_fn || '(text)');
    IF v_reg IS NULL
       OR NOT EXISTS (
            SELECT 1 FROM cordis.isolation_fold_handlers h
             WHERE h.fold_fn = v_reg
               AND h.contract_version = 'p08.v1'
       ) THEN
        RAISE EXCEPTION 'P08_FOLD_POLICY_NOT_CERTIFIED'
            USING ERRCODE = '42501';
    END IF;
    SELECT n.nspname, p.proname
      INTO v_nsp, v_name
      FROM pg_catalog.pg_proc AS p
      JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
     WHERE p.oid = v_reg;
    v_call := pg_catalog.format('%I.%I', v_nsp, v_name);
    v_prior := pg_catalog.current_setting('cordis.p08_calling_slice_id', true);
    BEGIN
        PERFORM pg_catalog.set_config(
            'cordis.p08_calling_slice_id', p_slice_id::text, true
        );
        EXECUTE 'SELECT ' || v_call || '($1)' INTO v_slot USING p_run_id;
        PERFORM pg_catalog.set_config(
            'cordis.p08_calling_slice_id', COALESCE(v_prior, ''), true
        );
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_catalog.set_config(
            'cordis.p08_calling_slice_id', COALESCE(v_prior, ''), true
        );
        RAISE;
    END;
    IF v_slot IS NULL
       OR pg_catalog.jsonb_typeof(v_slot) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'P08_FOLD_INVALID_RESULT'
            USING ERRCODE = '55000';
    END IF;
    v_folded := COALESCE(v_slot, '{}'::jsonb);
    RETURN v_folded || pg_catalog.jsonb_build_object(
        'protocol', 'cordis.p08.fold.v1',
        'run_id', p_run_id,
        'slice_id', p_slice_id::text,
        'paradigm', v_identity,
        'system_prompt', v_policy.system_prompt,
        'action_surface', v_policy.action_surface,
        'parser_kind', v_policy.parser_kind,
        'named_corpora', COALESCE(v_slot -> 'named_corpora', '[]'::jsonb),
        'as_of_seq', COALESCE(v_slot -> 'as_of_seq', '0'::jsonb),
        'history', COALESCE(v_slot -> 'history', '[]'::jsonb)
    );
END;
$p08$;

CREATE OR REPLACE FUNCTION cordis.read_run_env(
    p_run_id text,
    p_slice_id uuid,
    p_paradigm text,
    p_key text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
DECLARE
    v_identity text;
    v_policy record;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_paradigm IS NULL
       OR pg_catalog.btrim(p_paradigm) = ''
       OR pg_catalog.octet_length(pg_catalog.btrim(p_paradigm)) > 128
       OR pg_catalog.btrim(p_paradigm)
          !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid identity'
            USING ERRCODE = '22023';
    END IF;
    IF p_key IS NULL
       OR pg_catalog.btrim(p_key) = ''
       OR pg_catalog.octet_length(p_key) > 256
       OR p_key ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid env key'
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(p_paradigm);
    PERFORM cordis._require_isolation_feature();
    PERFORM * FROM cordis.slice_live_grants(p_run_id, p_slice_id);
    SELECT * INTO v_policy FROM cordis.paradigm_policy(v_identity);
    IF v_policy.env_enabled IS NOT TRUE
       OR v_policy.env_workspace = 'none' THEN
        RAISE EXCEPTION 'P08_ENV_DISABLED'
            USING ERRCODE = '42501';
    END IF;
    IF v_policy.env_workspace IS DISTINCT FROM 'run_vars' THEN
        RAISE EXCEPTION 'P08_ENV_POLICY_UNSUPPORTED'
            USING ERRCODE = '55000';
    END IF;
    IF NOT cordis.slice_has_grant(p_run_id, p_slice_id, 'run', '') THEN
        RAISE EXCEPTION 'P08_ENV_RUN_GRANT_REQUIRED'
            USING ERRCODE = '42501';
    END IF;
    RAISE EXCEPTION 'P08_ENV_WORKSPACE_UNAVAILABLE'
        USING ERRCODE = '55000';
END;
$p08$;

CREATE OR REPLACE FUNCTION cordis.authorize_tool_dispatch(
    p_run_id text,
    p_slice_id uuid,
    p_identity text,
    p_bindings jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p08$
DECLARE
    v_identity text;
    v_plugin cordis.plugin_catalog%ROWTYPE;
    v_keys text[];
    v_kind text;
    v_target text;
    v_entrypoint_txt text;
    v_denied boolean := false;
    v_denied_oid oid;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_identity IS NULL
       OR pg_catalog.btrim(p_identity) = ''
       OR pg_catalog.octet_length(pg_catalog.btrim(p_identity)) > 128
       OR pg_catalog.btrim(p_identity)
          !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
        RAISE EXCEPTION 'invalid plugin identity'
            USING ERRCODE = '22023';
    END IF;
    v_identity := pg_catalog.btrim(p_identity);
    IF p_bindings IS NULL
       OR pg_catalog.jsonb_typeof(p_bindings) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'invalid requested grants'
            USING ERRCODE = '22023';
    END IF;
    PERFORM cordis._require_isolation_feature();
    PERFORM * FROM cordis.slice_live_grants(p_run_id, p_slice_id);
    SELECT * INTO v_plugin
      FROM cordis.plugin_catalog
     WHERE identity = v_identity;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown plugin'
            USING ERRCODE = '22023';
    END IF;
    IF v_identity IN (
           'register_named_corpus',
           'create_slice',
           'issue_grant',
           'approve_grant',
           'deny_grant',
           'revoke_grant',
           'emit_step',
           'emit_step_claimed',
           'emit_step_scoped',
           'checkpoint'
       )
       OR v_identity IN (
           'cordis.register_named_corpus',
           'cordis.create_slice',
           'cordis.issue_grant',
           'cordis.approve_grant',
           'cordis.deny_grant',
           'cordis.revoke_grant',
           'cordis.emit_step',
           'cordis.emit_step_claimed',
           'cordis.emit_step_scoped',
           'cordis.checkpoint'
       ) THEN
        RAISE EXCEPTION 'P08_CONTROL_PLANE_TOOL_DENIED'
            USING ERRCODE = '42501';
    END IF;
    IF v_plugin.entrypoint IS NOT NULL THEN
        FOREACH v_entrypoint_txt IN ARRAY ARRAY[
            'cordis.register_named_corpus(text,text,text)',
            'cordis.create_slice(text,text,text)',
            'cordis.issue_grant(text,uuid,text,text,text)',
            'cordis.approve_grant(uuid,text)',
            'cordis.deny_grant(uuid,text)',
            'cordis.revoke_grant(uuid,text)',
            'cordis.emit_step(text,text,jsonb,text)',
            'cordis.emit_step_claimed(uuid,text,text,jsonb,text,integer)',
            'cordis.emit_step_scoped(uuid,text,uuid,text,jsonb,text,text[],integer)',
            'cordis.checkpoint(uuid,jsonb,integer)'
        ] LOOP
            v_denied_oid := pg_catalog.to_regprocedure(v_entrypoint_txt);
            IF v_denied_oid IS NOT NULL
               AND v_plugin.entrypoint = v_denied_oid THEN
                v_denied := true;
                EXIT;
            END IF;
        END LOOP;
        IF v_denied THEN
            RAISE EXCEPTION 'P08_CONTROL_PLANE_TOOL_DENIED'
                USING ERRCODE = '42501';
        END IF;
    END IF;
    SELECT COALESCE(pg_catalog.array_agg(k ORDER BY k), ARRAY[]::text[])
      INTO v_keys
      FROM pg_catalog.jsonb_object_keys(p_bindings) AS k;
    IF NOT (
        v_plugin.required_grants <@ v_keys
        AND v_keys <@ v_plugin.required_grants
    ) THEN
        RAISE EXCEPTION 'invalid requested grants'
            USING ERRCODE = '22023';
    END IF;
    FOREACH v_kind IN ARRAY COALESCE(v_plugin.required_grants, ARRAY[]::text[])
    LOOP
        IF v_kind = 'run' THEN
            IF (p_bindings -> 'run') IS DISTINCT FROM 'true'::jsonb THEN
                RAISE EXCEPTION 'invalid requested grants'
                    USING ERRCODE = '22023';
            END IF;
            v_target := '';
        ELSIF v_kind = 'named_corpus' THEN
            IF pg_catalog.jsonb_typeof(p_bindings -> 'named_corpus')
               IS DISTINCT FROM 'string' THEN
                RAISE EXCEPTION 'invalid requested grants'
                    USING ERRCODE = '22023';
            END IF;
            v_target := p_bindings ->> 'named_corpus';
            IF v_target IS NULL
               OR v_target !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
                RAISE EXCEPTION 'invalid requested grants'
                    USING ERRCODE = '22023';
            END IF;
        ELSIF v_kind = 'event' THEN
            IF pg_catalog.jsonb_typeof(p_bindings -> 'event')
               IS DISTINCT FROM 'string' THEN
                RAISE EXCEPTION 'invalid requested grants'
                    USING ERRCODE = '22023';
            END IF;
            v_target := p_bindings ->> 'event';
            IF v_target IS NULL OR pg_catalog.btrim(v_target) = '' THEN
                RAISE EXCEPTION 'invalid requested grants'
                    USING ERRCODE = '22023';
            END IF;
        ELSE
            RAISE EXCEPTION 'invalid requested grants'
                USING ERRCODE = '22023';
        END IF;
        IF NOT cordis.slice_has_grant(
            p_run_id, p_slice_id, v_kind, v_target
        ) THEN
            RAISE EXCEPTION 'P08_TOOL_GRANT_REQUIRED'
                USING ERRCODE = '42501',
                      DETAIL = v_kind;
        END IF;
    END LOOP;
    RETURN pg_catalog.jsonb_build_object(
        'identity', v_plugin.identity,
        'name', v_plugin.name,
        'description', v_plugin.description,
        'version', v_plugin.version,
        'locus', v_plugin.locus,
        'invocation', v_plugin.invocation,
        'required_grants', pg_catalog.to_jsonb(v_plugin.required_grants),
        'bindings', p_bindings,
        'effect_class', v_plugin.effect_class,
        'retry_class', v_plugin.retry_class,
        'reconciliation', v_plugin.reconciliation,
        'entrypoint', CASE
            WHEN v_plugin.entrypoint IS NULL THEN NULL
            ELSE pg_catalog.to_jsonb(v_plugin.entrypoint::text)
        END,
        'session_scope', v_plugin.session_scope,
        'capability', v_plugin.capability,
        'config', v_plugin.config,
        'inject', v_plugin.inject,
        'provide', v_plugin.provide,
        'intercept', v_plugin.intercept
    );
END;
$p08$;

DO $p08latch$
DECLARE
    v_codeact timestamptz;
    v_rlm timestamptz;
    v_recall timestamptz;
    v_fold timestamptz;
    v_env timestamptz;
    v_tool timestamptz;
BEGIN
    SELECT h.installed_at INTO v_codeact
      FROM cordis.isolation_fold_handlers AS h
     WHERE h.fold_fn = 'cordis.fold_codeact_messages(text)'::regprocedure;
    SELECT h.installed_at INTO v_rlm
      FROM cordis.isolation_fold_handlers AS h
     WHERE h.fold_fn = 'cordis.fold_rlm_messages(text)'::regprocedure;
    DELETE FROM cordis.isolation_fold_handlers;
    INSERT INTO cordis.isolation_fold_handlers (
        fold_fn, contract_version, installed_at
    ) VALUES
        (
            'cordis.fold_codeact_messages(text)'::regprocedure,
            'p08.v1',
            COALESCE(v_codeact, pg_catalog.clock_timestamp())
        ),
        (
            'cordis.fold_rlm_messages(text)'::regprocedure,
            'p08.v1',
            COALESCE(v_rlm, pg_catalog.clock_timestamp())
        );

    SELECT s.installed_at INTO v_recall
      FROM cordis.isolation_seams AS s WHERE s.seam = 'recall';
    SELECT s.installed_at INTO v_fold
      FROM cordis.isolation_seams AS s WHERE s.seam = 'fold';
    SELECT s.installed_at INTO v_env
      FROM cordis.isolation_seams AS s WHERE s.seam = 'env_read';
    SELECT s.installed_at INTO v_tool
      FROM cordis.isolation_seams AS s WHERE s.seam = 'tool_dispatch';
    DELETE FROM cordis.isolation_seams;
    INSERT INTO cordis.isolation_seams (
        seam, gate_fn, contract_version, installed_at
    ) VALUES
        (
            'recall',
            'cordis.recall_named_corpus(text,uuid,text)'::regprocedure,
            'p08.v1',
            COALESCE(v_recall, pg_catalog.clock_timestamp())
        ),
        (
            'fold',
            'cordis.fold_slice_messages(text,uuid,text)'::regprocedure,
            'p08.v1',
            COALESCE(v_fold, pg_catalog.clock_timestamp())
        ),
        (
            'env_read',
            'cordis.read_run_env(text,uuid,text,text)'::regprocedure,
            'p08.v1',
            COALESCE(v_env, pg_catalog.clock_timestamp())
        ),
        (
            'tool_dispatch',
            'cordis.authorize_tool_dispatch(text,uuid,text,jsonb)'::regprocedure,
            'p08.v1',
            COALESCE(v_tool, pg_catalog.clock_timestamp())
        );
END;
$p08latch$;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p20'::text;
$$;
