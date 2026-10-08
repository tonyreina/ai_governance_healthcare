-- 005_disposal.sql -- deletion that leaves a record, and a purge that reaches the
-- audit log. (#36)
--
-- Two things were wrong, and they compound.
--
-- 1. PURGE LEFT THE SAME VALUES IN THE AUDIT LOG. A purge emptied
--    project_version.doc and stopped. But the client writes each log entry's PROSE
--    with the values in it ("Changed evidence of ...: “old” -> “new”") as well as
--    change.from and change.to, and the entry may carry any other field the client
--    chose to send. A patient identifier pasted into an evidence field was still
--    readable in project_log after a purge reported success.
--
-- 2. DELETION LEFT NO DURABLE RECORD. DELETE removes the live project and, by
--    ON DELETE CASCADE, its log. The only trace that the record ever existed was a
--    line on container stdout, and the orphaned project_version rows, which carry
--    no "deleted" state. "Deleted by X on this date" is itself an audit finding.

-- ---------------------------------------------------------------------------
-- Part 1: redacting the log.
--
-- "Already purged" and "written by the system" are COLUMNS, not keys inside the
-- entry. The entry is client-supplied jsonb: if the exemption were a key in it,
-- a client could send {"purged": true} and make an entry carrying the value
-- survive every purge.
-- ---------------------------------------------------------------------------

ALTER TABLE project_log
    ADD COLUMN IF NOT EXISTS purged_at timestamptz,
    ADD COLUMN IF NOT EXISTS purged_by text,
    ADD COLUMN IF NOT EXISTS is_system boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN project_log.purged_at IS
    'Set when the entry''s content was destroyed. The row, its sequence number, '
    'time and author survive; see project_log_redacted() for what is kept.';
COMMENT ON COLUMN project_log.is_system IS
    'True for entries the SERVER wrote (the record of a purge). Never set from a '
    'client request, and never redacted: it is the evidence that a purge happened.';

-- What a redacted entry IS, in one place. A WHITELIST: the log accepts arbitrary
-- extra fields from the client, any of which could hold the value, so a list of
-- known-sensitive fields would miss the one that matters. Kept: when, who, which
-- field changed, and the fingerprint. Everything else, including the prose, the
-- old and new values, and anything the client added, is gone.
--
-- IMMUTABLE and deterministic, because the trigger below compares against it.
CREATE OR REPLACE FUNCTION project_log_redacted(entry jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'text',   '[content purged]',
        'at',     entry -> 'at',
        'by',     entry -> 'by',
        'hash',   entry -> 'hash',
        'change', CASE WHEN entry ? 'change'
                       THEN jsonb_build_object('path', entry #> '{change,path}')
                  END
    ))
$$;

-- The trigger from 001 refused every UPDATE. It now permits exactly one
-- transition, a redaction, and verifies the RESULT rather than trusting the
-- caller: the new entry must equal project_log_redacted(old entry). A partial
-- redaction, a redaction that keeps change.to, an edit that merely claims to be
-- one, a change to when or who, and un-purging are all refused.
CREATE OR REPLACE FUNCTION project_log_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.seq        =  OLD.seq
       AND NEW.project_id =  OLD.project_id
       AND NEW.at         =  OLD.at
       AND NEW.by_id      IS NOT DISTINCT FROM OLD.by_id
       AND NEW.is_system  =  OLD.is_system
       AND NOT OLD.is_system
       AND OLD.purged_at  IS NULL
       AND NEW.purged_at  IS NOT NULL
       AND NEW.entry      =  project_log_redacted(OLD.entry)
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION
        'project_log is append-only: the only permitted UPDATE is a purge '
        'redaction (seq=%)', OLD.seq
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

-- ---------------------------------------------------------------------------
-- Part 2: a tombstone for deletion.
--
-- One row per deleted incarnation. No foreign key to projects, for the same
-- reason project_version has none: it must outlive the row it describes. It is
-- append-only and is NOT touched by a purge, because "the record existed, was
-- deleted by X at T, and last hashed to H" is exactly what an erasure leaves
-- behind. It holds no content, only who, when and a fingerprint.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS project_deletion (
    project_id   text        NOT NULL,
    incarnation  uuid        NOT NULL,
    deleted_at   timestamptz NOT NULL DEFAULT now(),
    deleted_by   text,
    last_rev     integer,
    last_md5     text,
    PRIMARY KEY (project_id, incarnation)
);

COMMENT ON TABLE project_deletion IS
    'Append-only record that a project was deleted, by whom and when, and what its '
    'last revision hashed to. Holds no content. Survives a purge.';

CREATE OR REPLACE FUNCTION project_deletion_immutable() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'project_deletion is append-only (attempted % on %)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

DROP TRIGGER IF EXISTS project_deletion_no_change ON project_deletion;
CREATE TRIGGER project_deletion_no_change
    BEFORE UPDATE OR DELETE ON project_deletion
    FOR EACH ROW EXECUTE FUNCTION project_deletion_immutable();
