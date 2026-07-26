-- Extensions the schema depends on. Created here rather than in a migration so
-- that a fresh database is usable before Alembic has ever run.
--
--   pg_trgm     fuzzy matching on subject and institution names: a student
--               typing "matan" or "prijimacky" must still find them
--   unaccent    strips Czech diacritics so "prijimacky" matches "přijímačky"
--   btree_gist  lets the availability exclusion constraint combine an equality
--               test on helper_id with an overlap test on a time range
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- pgvector is present in the image but deliberately NOT enabled yet. Semantic
-- search is planned, not built; enabling an extension we do not query would
-- only make the schema look like it does something it does not.
-- When the time comes:  CREATE EXTENSION vector;  and see docs/data-model.md.

-- unaccent() is STABLE, which bars it from expression indexes. This wrapper is
-- the standard workaround: same behaviour, marked IMMUTABLE, and the dictionary
-- is pinned so the promise actually holds.
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;
