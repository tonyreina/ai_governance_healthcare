-- 001_init.sql -- projects and their append-only audit log.
--
-- The project document is one jsonb column. The API treats it as opaque apart
-- from the deep-merge rule, so there is deliberately no column per field:
-- the browser's schema (schema/project.schema.json) can grow without a
-- migration here.
--
-- Requires PostgreSQL 13 or later (CREATE TRIGGER ... EXECUTE FUNCTION).

CREATE TABLE IF NOT EXISTS projects (
    id          text PRIMARY KEY,
    doc         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    rev         bigint      NOT NULL DEFAULT 1,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text,
    updated_by  text,
    CONSTRAINT projects_doc_is_object CHECK (jsonb_typeof(doc) = 'object')
);

COMMENT ON COLUMN projects.doc IS
    'The project document, exactly as the browser stores it. PATCH deep-merges '
    'into this value; the API never rewrites fields inside it.';
COMMENT ON COLUMN projects.updated_by IS
    'Identity from the reverse-proxy header on the last write. This column, not '
    'anything inside doc, is the trustworthy record of who wrote.';
COMMENT ON COLUMN projects.rev IS
    'Bumped on every successful PATCH. Useful for debugging lost-update reports.';

CREATE INDEX IF NOT EXISTS projects_updated_at_idx ON projects (updated_at DESC);


-- Append-only. There is no API route that updates or deletes a log entry, and
-- the trigger below makes sure a stray UPDATE cannot do it either.
--
-- DELETE is left permitted for exactly one reason: ON DELETE CASCADE has to be
-- able to remove a project's log when the project is deleted. A BEFORE DELETE
-- guard would block the cascade too.
CREATE TABLE IF NOT EXISTS project_log (
    seq         bigserial PRIMARY KEY,
    project_id  text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    at          timestamptz NOT NULL DEFAULT now(),
    by_id       text,
    entry       jsonb       NOT NULL,
    CONSTRAINT project_log_entry_is_object CHECK (jsonb_typeof(entry) = 'object')
);

-- subscribeLog() wants the newest 60 by .at descending. seq breaks ties, so
-- two entries written in the same millisecond still come back in a stable
-- order rather than shuffling between requests.
CREATE INDEX IF NOT EXISTS project_log_project_at_idx
    ON project_log (project_id, at DESC, seq DESC);

CREATE OR REPLACE FUNCTION project_log_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION
        'project_log is append-only: UPDATE is not permitted (seq=%)', OLD.seq
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

DROP TRIGGER IF EXISTS project_log_no_update ON project_log;
CREATE TRIGGER project_log_no_update
    BEFORE UPDATE ON project_log
    FOR EACH ROW EXECUTE FUNCTION project_log_is_append_only();
