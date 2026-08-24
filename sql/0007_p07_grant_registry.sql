-- P07: grant registry. Replay-safe.
-- No GRANT/REVOKE/role/extension/public objects or transaction control.
-- plpgsql bodies use $p07$ so preflight dollar-quote stripping covers END and grant words.

CREATE TABLE IF NOT EXISTS cordis.named_corpora (
    corpus_id text NOT NULL,
    label text NOT NULL,
    created_by_kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT named_corpora_pkey PRIMARY KEY (corpus_id),
    CONSTRAINT named_corpora_id_check CHECK (
        corpus_id ~ '^[a-z][a-z0-9_-]{0,127}$'
    ),
    CONSTRAINT named_corpora_label_check CHECK (
        pg_catalog.btrim(label) <> ''
        AND pg_catalog.octet_length(label) <= 256
        AND label !~ '[[:cntrl:]]'
    ),
    CONSTRAINT named_corpora_created_by_kind_check CHECK (
        created_by_kind IN ('user', 'host')
    )
);

CREATE TABLE IF NOT EXISTS cordis.slices (
    slice_id uuid NOT NULL DEFAULT pg_catalog.gen_random_uuid(),
    run_id text NOT NULL,
    name text NOT NULL,
    created_by_kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT slices_pkey PRIMARY KEY (slice_id),
    CONSTRAINT slices_run_name_key UNIQUE (run_id, name),
    CONSTRAINT slices_run_id_check CHECK (pg_catalog.btrim(run_id) <> ''),
    CONSTRAINT slices_name_check CHECK (name ~ '^[a-z][a-z0-9_-]{0,63}$'),
    CONSTRAINT slices_created_by_kind_check CHECK (
        created_by_kind IN ('user', 'host')
    )
);

CREATE TABLE IF NOT EXISTS cordis.grants (
    grant_id uuid NOT NULL DEFAULT pg_catalog.gen_random_uuid(),
    slice_id uuid NOT NULL,
    kind text NOT NULL,
    target text NOT NULL,
    status text NOT NULL,
    requested_by_kind text NOT NULL,
    decided_by_kind text,
    revoked_by_kind text,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    decided_at timestamptz,
    revoked_at timestamptz,
    CONSTRAINT grants_pkey PRIMARY KEY (grant_id),
    CONSTRAINT grants_slice_kind_target_key UNIQUE (slice_id, kind, target),
    CONSTRAINT grants_slice_fkey FOREIGN KEY (slice_id)
        REFERENCES cordis.slices(slice_id) ON DELETE RESTRICT,
    CONSTRAINT grants_kind_check CHECK (kind IN ('run', 'named_corpus', 'event')),
    CONSTRAINT grants_status_check CHECK (
        status IN ('pending', 'issued', 'denied', 'revoked')
    ),
    CONSTRAINT grants_requested_by_kind_check CHECK (
        requested_by_kind IN ('model', 'user', 'host')
    ),
    CONSTRAINT grants_decided_by_kind_check CHECK (
        decided_by_kind IS NULL OR decided_by_kind IN ('user', 'host')
    ),
    CONSTRAINT grants_revoked_by_kind_check CHECK (
        revoked_by_kind IS NULL OR revoked_by_kind IN ('user', 'host')
    ),
    CONSTRAINT grants_target_by_kind_check CHECK (
        (kind = 'run' AND target = '')
        OR (
            kind = 'named_corpus'
            AND target ~ '^[a-z][a-z0-9_-]{0,127}$'
        )
        OR (kind = 'event' AND pg_catalog.btrim(target) <> '')
    ),
    CONSTRAINT grants_status_times_check CHECK (
        (
            status = 'pending'
            AND decided_by_kind IS NULL
            AND decided_at IS NULL
            AND revoked_by_kind IS NULL
            AND revoked_at IS NULL
        )
        OR (
            status = 'issued'
            AND decided_by_kind IS NOT NULL
            AND decided_at IS NOT NULL
            AND revoked_by_kind IS NULL
            AND revoked_at IS NULL
        )
        OR (
            status = 'denied'
            AND decided_by_kind IS NOT NULL
            AND decided_at IS NOT NULL
            AND revoked_by_kind IS NULL
            AND revoked_at IS NULL
        )
        OR (
            status = 'revoked'
            AND decided_by_kind IS NOT NULL
            AND decided_at IS NOT NULL
            AND revoked_by_kind IS NOT NULL
            AND revoked_at IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS grants_slice_status_idx
    ON cordis.grants (slice_id, status, kind, target);

CREATE OR REPLACE FUNCTION cordis.register_named_corpus(
    p_corpus_id text,
    p_label text,
    p_issuer_kind text
)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_existing text;
BEGIN
    IF p_issuer_kind IS NOT DISTINCT FROM 'model' THEN
        RAISE EXCEPTION 'issuer must not be model'
            USING ERRCODE = '42501';
    END IF;
    IF p_issuer_kind IS NULL OR p_issuer_kind NOT IN ('user', 'host') THEN
        RAISE EXCEPTION 'invalid issuer_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_corpus_id IS NULL OR p_corpus_id !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
        RAISE EXCEPTION 'invalid corpus id'
            USING ERRCODE = '22023';
    END IF;
    IF p_label IS NULL
       OR pg_catalog.btrim(p_label) = ''
       OR pg_catalog.octet_length(p_label) > 256
       OR p_label ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid corpus label'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        INSERT INTO cordis.named_corpora (
            corpus_id, label, created_by_kind
        ) VALUES (
            p_corpus_id, p_label, p_issuer_kind
        );
    EXCEPTION
        WHEN unique_violation THEN
            SELECT nc.label
              INTO v_existing
              FROM cordis.named_corpora AS nc
             WHERE nc.corpus_id = p_corpus_id;
            IF v_existing IS NOT DISTINCT FROM p_label THEN
                RETURN p_corpus_id;
            END IF;
            RAISE EXCEPTION 'corpus already registered'
                USING ERRCODE = '22023';
    END;
    RETURN p_corpus_id;
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.create_slice(
    p_run_id text,
    p_name text,
    p_issuer_kind text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_slice uuid;
BEGIN
    IF p_issuer_kind IS NOT DISTINCT FROM 'model' THEN
        RAISE EXCEPTION 'issuer must not be model'
            USING ERRCODE = '42501';
    END IF;
    IF p_issuer_kind IS NULL OR p_issuer_kind NOT IN ('user', 'host') THEN
        RAISE EXCEPTION 'invalid issuer_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_name IS NULL OR p_name !~ '^[a-z][a-z0-9_-]{0,63}$' THEN
        RAISE EXCEPTION 'invalid slice name'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        INSERT INTO cordis.slices (run_id, name, created_by_kind)
        VALUES (p_run_id, p_name, p_issuer_kind)
        RETURNING slice_id INTO v_slice;
    EXCEPTION
        WHEN unique_violation THEN
            RAISE EXCEPTION 'duplicate slice name'
                USING ERRCODE = '22023';
    END;
    RETURN v_slice;
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.request_grant(
    p_run_id text,
    p_slice_id uuid,
    p_kind text,
    p_target text,
    p_requester_kind text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_kind text;
    v_target text;
    v_run text;
    v_id uuid;
    v_status text;
    v_try integer;
BEGIN
    IF p_requester_kind IS NULL
       OR p_requester_kind NOT IN ('model', 'user', 'host') THEN
        RAISE EXCEPTION 'invalid requester_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_kind IS NULL
       OR pg_catalog.strpos(p_kind, ':') > 0
       OR p_kind NOT IN ('run', 'named_corpus', 'event') THEN
        RAISE EXCEPTION 'unknown grant kind'
            USING ERRCODE = '22023';
    END IF;
    v_kind := p_kind;
    IF v_kind = 'run' THEN
        v_target := COALESCE(p_target, '');
        IF v_target <> '' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
    ELSIF v_kind = 'named_corpus' THEN
        IF p_target IS NULL
           OR p_target !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM cordis.named_corpora AS nc
             WHERE nc.corpus_id = p_target
        ) THEN
            RAISE EXCEPTION 'unknown named corpus'
                USING ERRCODE = '22023';
        END IF;
        v_target := p_target;
    ELSE
        IF p_target IS NULL OR pg_catalog.btrim(p_target) = '' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
        v_target := p_target;
    END IF;
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_slice_id IS NULL THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;

    FOR v_try IN 1..2 LOOP
        v_id := NULL;
        v_status := NULL;
        SELECT s.run_id
          INTO v_run
          FROM cordis.slices AS s
         WHERE s.slice_id = p_slice_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'slice not found'
                USING ERRCODE = '22023';
        END IF;
        IF v_run IS DISTINCT FROM p_run_id THEN
            RAISE EXCEPTION 'slice does not belong to run'
                USING ERRCODE = '22023';
        END IF;

        SELECT g.grant_id, g.status
          INTO v_id, v_status
          FROM cordis.grants AS g
         WHERE g.slice_id = p_slice_id
           AND g.kind = v_kind
           AND g.target = v_target
         FOR UPDATE;

        IF FOUND THEN
            IF v_status IN ('pending', 'issued') THEN
                RETURN v_id;
            END IF;
            UPDATE cordis.grants
               SET status = 'pending',
                   requested_by_kind = p_requester_kind,
                   decided_by_kind = NULL,
                   decided_at = NULL,
                   revoked_by_kind = NULL,
                   revoked_at = NULL
             WHERE grant_id = v_id;
            RETURN v_id;
        END IF;

        BEGIN
            INSERT INTO cordis.grants (
                slice_id, kind, target, status, requested_by_kind
            ) VALUES (
                p_slice_id, v_kind, v_target, 'pending', p_requester_kind
            )
            RETURNING grant_id INTO v_id;
            RETURN v_id;
        EXCEPTION
            WHEN unique_violation THEN
                NULL;
        END;
    END LOOP;
    RAISE EXCEPTION 'grant not found'
        USING ERRCODE = '22023';
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.issue_grant(
    p_run_id text,
    p_slice_id uuid,
    p_kind text,
    p_target text,
    p_issuer_kind text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_kind text;
    v_target text;
    v_run text;
    v_id uuid;
    v_status text;
    v_now timestamptz;
    v_try integer;
BEGIN
    IF p_issuer_kind IS NOT DISTINCT FROM 'model' THEN
        RAISE EXCEPTION 'issuer must not be model'
            USING ERRCODE = '42501';
    END IF;
    IF p_issuer_kind IS NULL OR p_issuer_kind NOT IN ('user', 'host') THEN
        RAISE EXCEPTION 'invalid issuer_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_kind IS NULL
       OR pg_catalog.strpos(p_kind, ':') > 0
       OR p_kind NOT IN ('run', 'named_corpus', 'event') THEN
        RAISE EXCEPTION 'unknown grant kind'
            USING ERRCODE = '22023';
    END IF;
    v_kind := p_kind;
    IF v_kind = 'run' THEN
        v_target := COALESCE(p_target, '');
        IF v_target <> '' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
    ELSIF v_kind = 'named_corpus' THEN
        IF p_target IS NULL
           OR p_target !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM cordis.named_corpora AS nc
             WHERE nc.corpus_id = p_target
        ) THEN
            RAISE EXCEPTION 'unknown named corpus'
                USING ERRCODE = '22023';
        END IF;
        v_target := p_target;
    ELSE
        IF p_target IS NULL OR pg_catalog.btrim(p_target) = '' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
        v_target := p_target;
    END IF;
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_slice_id IS NULL THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;

    FOR v_try IN 1..2 LOOP
        v_id := NULL;
        v_status := NULL;
        SELECT s.run_id
          INTO v_run
          FROM cordis.slices AS s
         WHERE s.slice_id = p_slice_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'slice not found'
                USING ERRCODE = '22023';
        END IF;
        IF v_run IS DISTINCT FROM p_run_id THEN
            RAISE EXCEPTION 'slice does not belong to run'
                USING ERRCODE = '22023';
        END IF;

        SELECT g.grant_id, g.status
          INTO v_id, v_status
          FROM cordis.grants AS g
         WHERE g.slice_id = p_slice_id
           AND g.kind = v_kind
           AND g.target = v_target
         FOR UPDATE;

        v_now := pg_catalog.clock_timestamp();
        IF FOUND THEN
            IF v_status = 'issued' THEN
                RETURN v_id;
            END IF;
            UPDATE cordis.grants
               SET status = 'issued',
                   decided_by_kind = p_issuer_kind,
                   decided_at = v_now,
                   revoked_by_kind = NULL,
                   revoked_at = NULL
             WHERE grant_id = v_id;
            RETURN v_id;
        END IF;

        BEGIN
            INSERT INTO cordis.grants (
                slice_id, kind, target, status,
                requested_by_kind, decided_by_kind,
                created_at, decided_at
            ) VALUES (
                p_slice_id, v_kind, v_target, 'issued',
                p_issuer_kind, p_issuer_kind,
                v_now, v_now
            )
            RETURNING grant_id INTO v_id;
            RETURN v_id;
        EXCEPTION
            WHEN unique_violation THEN
                NULL;
        END;
    END LOOP;
    RAISE EXCEPTION 'grant not found'
        USING ERRCODE = '22023';
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.approve_grant(
    p_grant_id uuid,
    p_issuer_kind text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_slice uuid;
    v_status text;
    v_now timestamptz;
BEGIN
    IF p_issuer_kind IS NOT DISTINCT FROM 'model' THEN
        RAISE EXCEPTION 'issuer must not be model'
            USING ERRCODE = '42501';
    END IF;
    IF p_issuer_kind IS NULL OR p_issuer_kind NOT IN ('user', 'host') THEN
        RAISE EXCEPTION 'invalid issuer_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_grant_id IS NULL THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT g.slice_id
      INTO v_slice
      FROM cordis.grants AS g
     WHERE g.grant_id = p_grant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM cordis.slices AS s WHERE s.slice_id = v_slice FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT g.status
      INTO v_status
      FROM cordis.grants AS g
     WHERE g.grant_id = p_grant_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    IF v_status <> 'pending' THEN
        RAISE EXCEPTION 'grant is not pending'
            USING ERRCODE = '22023';
    END IF;
    v_now := pg_catalog.clock_timestamp();
    UPDATE cordis.grants
       SET status = 'issued',
           decided_by_kind = p_issuer_kind,
           decided_at = v_now,
           revoked_by_kind = NULL,
           revoked_at = NULL
     WHERE grant_id = p_grant_id;
    RETURN p_grant_id;
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.deny_grant(
    p_grant_id uuid,
    p_issuer_kind text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_slice uuid;
    v_status text;
    v_now timestamptz;
BEGIN
    IF p_issuer_kind IS NOT DISTINCT FROM 'model' THEN
        RAISE EXCEPTION 'issuer must not be model'
            USING ERRCODE = '42501';
    END IF;
    IF p_issuer_kind IS NULL OR p_issuer_kind NOT IN ('user', 'host') THEN
        RAISE EXCEPTION 'invalid issuer_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_grant_id IS NULL THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT g.slice_id
      INTO v_slice
      FROM cordis.grants AS g
     WHERE g.grant_id = p_grant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM cordis.slices AS s WHERE s.slice_id = v_slice FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT g.status
      INTO v_status
      FROM cordis.grants AS g
     WHERE g.grant_id = p_grant_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    IF v_status <> 'pending' THEN
        RAISE EXCEPTION 'grant is not pending'
            USING ERRCODE = '22023';
    END IF;
    v_now := pg_catalog.clock_timestamp();
    UPDATE cordis.grants
       SET status = 'denied',
           decided_by_kind = p_issuer_kind,
           decided_at = v_now,
           revoked_by_kind = NULL,
           revoked_at = NULL
     WHERE grant_id = p_grant_id;
    RETURN p_grant_id;
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.revoke_grant(
    p_grant_id uuid,
    p_issuer_kind text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_slice uuid;
    v_status text;
    v_now timestamptz;
BEGIN
    IF p_issuer_kind IS NOT DISTINCT FROM 'model' THEN
        RAISE EXCEPTION 'issuer must not be model'
            USING ERRCODE = '42501';
    END IF;
    IF p_issuer_kind IS NULL OR p_issuer_kind NOT IN ('user', 'host') THEN
        RAISE EXCEPTION 'invalid issuer_kind'
            USING ERRCODE = '22023';
    END IF;
    IF p_grant_id IS NULL THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT g.slice_id
      INTO v_slice
      FROM cordis.grants AS g
     WHERE g.grant_id = p_grant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1 FROM cordis.slices AS s WHERE s.slice_id = v_slice FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT g.status
      INTO v_status
      FROM cordis.grants AS g
     WHERE g.grant_id = p_grant_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'grant not found'
            USING ERRCODE = '22023';
    END IF;
    IF v_status <> 'issued' THEN
        RAISE EXCEPTION 'grant is not issued'
            USING ERRCODE = '22023';
    END IF;
    v_now := pg_catalog.clock_timestamp();
    UPDATE cordis.grants
       SET status = 'revoked',
           revoked_by_kind = p_issuer_kind,
           revoked_at = v_now
     WHERE grant_id = p_grant_id;
    RETURN p_grant_id;
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.slice_live_grants(
    p_run_id text,
    p_slice_id uuid
)
RETURNS TABLE (
    grant_id uuid,
    kind text,
    target text,
    d5_literal text
)
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_run text;
BEGIN
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_slice_id IS NULL THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT s.run_id
      INTO v_run
      FROM cordis.slices AS s
     WHERE s.slice_id = p_slice_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;
    IF v_run IS DISTINCT FROM p_run_id THEN
        RAISE EXCEPTION 'slice does not belong to run'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    SELECT g.grant_id,
           g.kind,
           g.target,
           CASE g.kind
               WHEN 'run' THEN 'run'::text
               WHEN 'named_corpus' THEN 'named_corpus:' || g.target
               ELSE 'event:' || g.target
           END
      FROM cordis.grants AS g
     WHERE g.slice_id = p_slice_id
       AND g.status = 'issued'
     ORDER BY g.kind, g.target, g.grant_id;
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.slice_has_grant(
    p_run_id text,
    p_slice_id uuid,
    p_kind text,
    p_target text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path TO pg_catalog
AS $p07$
DECLARE
    v_kind text;
    v_target text;
    v_run text;
BEGIN
    IF p_kind IS NULL
       OR pg_catalog.strpos(p_kind, ':') > 0
       OR p_kind NOT IN ('run', 'named_corpus', 'event') THEN
        RAISE EXCEPTION 'unknown grant kind'
            USING ERRCODE = '22023';
    END IF;
    v_kind := p_kind;
    IF v_kind = 'run' THEN
        v_target := COALESCE(p_target, '');
        IF v_target <> '' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
    ELSIF v_kind = 'named_corpus' THEN
        IF p_target IS NULL
           OR p_target !~ '^[a-z][a-z0-9_-]{0,127}$' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM cordis.named_corpora AS nc
             WHERE nc.corpus_id = p_target
        ) THEN
            RAISE EXCEPTION 'unknown named corpus'
                USING ERRCODE = '22023';
        END IF;
        v_target := p_target;
    ELSE
        IF p_target IS NULL OR pg_catalog.btrim(p_target) = '' THEN
            RAISE EXCEPTION 'invalid grant target'
                USING ERRCODE = '22023';
        END IF;
        v_target := p_target;
    END IF;
    IF p_run_id IS NULL OR pg_catalog.btrim(p_run_id) = '' THEN
        RAISE EXCEPTION 'invalid run_id'
            USING ERRCODE = '22023';
    END IF;
    IF p_slice_id IS NULL THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;
    SELECT s.run_id
      INTO v_run
      FROM cordis.slices AS s
     WHERE s.slice_id = p_slice_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'slice not found'
            USING ERRCODE = '22023';
    END IF;
    IF v_run IS DISTINCT FROM p_run_id THEN
        RAISE EXCEPTION 'slice does not belong to run'
            USING ERRCODE = '22023';
    END IF;
    RETURN EXISTS (
        SELECT 1
          FROM cordis.grants AS g
         WHERE g.slice_id = p_slice_id
           AND g.kind = v_kind
           AND g.target = v_target
           AND g.status = 'issued'
    );
END;
$p07$;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p07'::text;
$$;
