-- P00 empty kernel: namespace only.
-- Schema is cordis: PostgreSQL reserves the pg_ prefix, so pg_cordis is illegal.
-- No GRANT, roles, tables, enums, queues, extensions, or public objects.

CREATE SCHEMA IF NOT EXISTS cordis;

CREATE OR REPLACE FUNCTION cordis.get_schema_version()
RETURNS text
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
AS $$
  SELECT 'p00'::text;
$$;
