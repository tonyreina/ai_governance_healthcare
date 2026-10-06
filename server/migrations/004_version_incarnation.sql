-- 004_version_incarnation.sql -- stop two different projects sharing one history.
--
-- project_version rows survive their project's deletion on purpose, and
-- create_project always snapshots at rev 1. Project ids are caller-chosen.
-- Put those together:
--
--   1. project "p1" is created and edited to revision 50
--   2. its owner deletes it; the projects row goes, 50 version rows stay
--   3. anyone creates a NEW project with id "p1"
--   4. its rev 1 collides with the old rev 1 and ON CONFLICT DO NOTHING
--      drops it on the floor, silently
--   5. GET /api/projects/p1/versions now returns the old project's 1..50
--      interleaved with the new project's 2.. as one continuous history
--
-- The history is the thing this system offers when a checkpoint decision is
-- challenged a year later. Two records presented as one, with the new record's
-- first revision missing and nothing anywhere saying so, is worse than having
-- no history: it is a confident wrong answer.
--
-- The fix is an incarnation id: a value minted when a project is created and
-- copied onto every snapshot. Reusing an id starts a new incarnation, and the
-- two histories stay separate because their keys differ.

-- The 003 trigger refuses every UPDATE that is not a purge, including the
-- backfills below. Drop it first and reinstall it at the bottom, in the same
-- transaction, so the table is never left unprotected.
DROP TRIGGER IF EXISTS project_version_no_update ON project_version;

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS incarnation uuid NOT NULL DEFAULT gen_random_uuid();

ALTER TABLE project_version
    ADD COLUMN IF NOT EXISTS incarnation uuid;

COMMENT ON COLUMN projects.incarnation IS
    'Minted per creation. Distinguishes this project from an earlier, deleted '
    'one that happened to use the same id.';
COMMENT ON COLUMN project_version.incarnation IS
    'The incarnation this snapshot belongs to. NULL on rows written before '
    '004, which are all treated as one legacy incarnation per project id.';

-- Existing rows belong to the live project where there is one.
UPDATE project_version v
   SET incarnation = p.incarnation
  FROM projects p
 WHERE p.id = v.project_id
   AND v.incarnation IS NULL;

-- Rows whose project was already deleted have no live incarnation to inherit.
-- Give them one derived from the project id, so every row from before this
-- migration that shares an id shares an incarnation -- which is the grouping
-- they already had. Deterministic rather than gen_random_uuid() so the
-- migration is idempotent and so two replicas applying it cannot disagree.
UPDATE project_version
   SET incarnation = md5('legacy:' || project_id)::uuid
 WHERE incarnation IS NULL;

ALTER TABLE project_version ALTER COLUMN incarnation SET NOT NULL;

-- The primary key has to admit two revision 1s for the same id now: one per
-- incarnation. Keyed on the incarnation, a reused id starts a separate
-- history instead of colliding with the old one.
--
-- A plain NOT NULL column and an ordinary unique constraint, rather than
-- NULLS NOT DISTINCT, because that syntax needs PostgreSQL 15 and 001_init.sql
-- sets the floor at 13. Backfilling the legacy rows above is what makes it
-- unnecessary.
ALTER TABLE project_version DROP CONSTRAINT IF EXISTS project_version_pkey;
ALTER TABLE project_version
    ADD CONSTRAINT project_version_pkey
    PRIMARY KEY (project_id, incarnation, rev);

CREATE INDEX IF NOT EXISTS project_version_by_incarnation
    ON project_version (project_id, incarnation, changed_at DESC);


-- Reinstall the append-only trigger, with `incarnation` added to the set of
-- columns a purge must leave alone. Without it the one permitted UPDATE could
-- move a snapshot from one incarnation to another, which is precisely the
-- confusion this migration exists to prevent.
CREATE OR REPLACE FUNCTION project_version_immutable()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'project_version is append-only (attempted DELETE on %)', TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF OLD.purged_at IS NULL
       AND NEW.purged_at IS NOT NULL
       AND NEW.doc = '{}'::jsonb
       AND NEW.project_id  =  OLD.project_id
       AND NEW.incarnation =  OLD.incarnation
       AND NEW.rev         =  OLD.rev
       AND NEW.content_md5 =  OLD.content_md5
       AND NEW.changed_at  =  OLD.changed_at
       AND NEW.changed_by  IS NOT DISTINCT FROM OLD.changed_by
       AND NEW.access      IS NOT DISTINCT FROM OLD.access
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION
        'project_version is append-only: the only permitted UPDATE is a purge '
        '(set purged_at, empty doc, change nothing else)'
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER project_version_no_update
    BEFORE UPDATE OR DELETE ON project_version
    FOR EACH ROW EXECUTE FUNCTION project_version_immutable();
