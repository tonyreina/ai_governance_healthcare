-- 003_version_access.sql -- make version history keep its access rules, and
-- make it purgeable.
--
-- Two problems with 002, both found by review:
--
-- 1. READS WERE CHECKED AGAINST THE LIVE PROJECT. When a project is deleted
--    there is no live row, so the check was skipped and every retained
--    snapshot became readable by anyone who could reach the API. Deleting a
--    restricted record widened access to it. The fix is to record the access
--    list ON each snapshot, so history stays as restricted as the record was.
--
-- 2. THERE WAS NO WAY TO REMOVE ANYTHING, EVER. The trigger refused UPDATE and
--    DELETE, which is right for ordinary edits and wrong as an absolute: data
--    entered in error -- a patient identifier pasted into an evidence field --
--    could not be removed through the application at all, and not in SQL
--    without disabling the trigger. A system holding regulated data needs a
--    disposal path.
--
-- The purge below is deliberately NOT a delete. The row survives, carrying its
-- revision, its author, its timestamp and its ORIGINAL content_md5; only `doc`
-- is emptied. So "revision 7 existed, was written by this person on this date,
-- hashed to this value, and its contents were purged by that person on that
-- date" remains answerable. A deletion would leave a hole that looks identical
-- to a snapshot that was never taken.

-- Drop the 002 trigger FIRST. It refuses every UPDATE, including the backfill
-- below, and a migration that cannot run is not a migration. The replacement
-- is installed at the bottom of this file, inside the same transaction, so
-- there is no window in which the table is unprotected.
DROP TRIGGER IF EXISTS project_version_no_update ON project_version;

ALTER TABLE project_version
    ADD COLUMN IF NOT EXISTS access     jsonb,
    ADD COLUMN IF NOT EXISTS purged_at  timestamptz,
    ADD COLUMN IF NOT EXISTS purged_by  text;

COMMENT ON COLUMN project_version.access IS
    'The project''s access list as of this revision. Version reads are checked '
    'against this when the live project is gone, so deleting a project does not '
    'widen access to its history. NULL on rows written before this migration.';
COMMENT ON COLUMN project_version.purged_at IS
    'Set when the content was deliberately destroyed. The row, its rev, its '
    'author and its original content_md5 survive; doc is emptied.';

-- Backfill from the live project where there still is one. Rows whose project
-- has already been deleted cannot be recovered this way and stay NULL; the API
-- treats a NULL access snapshot as unrestricted, which is exactly the state
-- those rows were already in. Nothing becomes more open than it was.
UPDATE project_version v
   SET access = COALESCE(p.doc -> 'access', '{}'::jsonb)
  FROM projects p
 WHERE p.id = v.project_id
   AND v.access IS NULL;


-- Append-only, with one permitted transition: redaction.
--
-- DELETE is still refused outright. UPDATE is refused unless it is exactly a
-- purge: purged_at going from NULL to a value, doc emptied, and every other
-- column -- including content_md5, which is what makes the tombstone evidence
-- rather than a gap -- left alone.
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

DROP TRIGGER IF EXISTS project_version_no_update ON project_version;
CREATE TRIGGER project_version_no_update
    BEFORE UPDATE OR DELETE ON project_version
    FOR EACH ROW EXECUTE FUNCTION project_version_immutable();
