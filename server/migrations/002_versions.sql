-- Version history: one immutable snapshot per revision.
--
-- The audit log says what someone intended to change. This says what the
-- record actually WAS at each revision, which is the question that matters
-- when a checkpoint decision is challenged a year later and the log is
-- ambiguous. Snapshots cannot disagree with themselves.
--
-- Full documents rather than diffs: a governance record is kilobytes, a
-- committee makes a few edits a week, and reconstructing a point in time by
-- replaying diffs is exactly the operation you do not want to debug while
-- answering a regulator.

CREATE TABLE IF NOT EXISTS project_version (
    project_id   text        NOT NULL,
    rev          integer     NOT NULL,
    doc          jsonb       NOT NULL,
    content_md5  text        NOT NULL,
    changed_by   text,
    changed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, rev),
    CONSTRAINT project_version_doc_is_object CHECK (jsonb_typeof(doc) = 'object')
);

CREATE INDEX IF NOT EXISTS project_version_by_time
    ON project_version (project_id, changed_at DESC);

-- No foreign key to projects, deliberately. Deleting a project must not erase
-- the evidence that it existed and what it said: "the record was deleted on
-- this date, and here is what it contained" is itself an audit finding. The
-- audit log cascades because it belongs to the live project; this does not.

-- Append-only, enforced rather than promised. A history that can be rewritten
-- is not a history.
CREATE OR REPLACE FUNCTION project_version_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'project_version is append-only (attempted % on %)',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS project_version_no_update ON project_version;
CREATE TRIGGER project_version_no_update
    BEFORE UPDATE OR DELETE ON project_version
    FOR EACH ROW EXECUTE FUNCTION project_version_immutable();
