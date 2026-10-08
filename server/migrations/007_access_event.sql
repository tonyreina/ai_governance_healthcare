-- 007_access_event.sql -- who read what (#33).
--
-- Every read route returned data and wrote nothing, and the exports never touched the
-- server. So "account X was compromised on the 3rd and closed on the 9th; which records
-- did it open, and did it export any?" had no answer anywhere in the stack, and every
-- breach would be scoped to the whole portfolio by default. 45 CFR 164.312(b), audit
-- controls, is a REQUIRED standard.
--
-- This is the record. It is written in the same transaction as the read it describes, so
-- there is no read without a record and no record of a read that did not happen.
--
-- Deliberately:
--   * APPEND-ONLY, like project_log: a trigger refuses UPDATE and DELETE.
--   * NO FOREIGN KEY to projects. "Who read this record" is exactly what an investigator
--     asks about a record that was later deleted, so the trail must outlive it (D-10).
--   * `action` is a closed set, held by a CHECK that a test keeps equal to the Python
--     enum (app/accessaudit.py), so neither can drift.
--   * `detail` carries what the action needs and nothing from the document: the project
--     ids a list returned, or the format of an export. Never content.
--   * `source_ip` is what the proxy reported, for correlation. It is not authentication.
--
-- Not decided here: how long to keep it. That belongs with the retention question (#57).

CREATE TABLE IF NOT EXISTS access_event (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor       text        NOT NULL,
    action      text        NOT NULL,
    project_id  text,
    revision    integer,
    source_ip   text        NOT NULL DEFAULT '',
    detail      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT access_event_action_known CHECK (
        action IN ('list', 'read_versions', 'read_version', 'read_log',
                   'export', 'stream_attach')
    ),
    CONSTRAINT access_event_detail_is_object CHECK (jsonb_typeof(detail) = 'object')
);

-- "Which records did this account open?" and "who opened this record?"
CREATE INDEX IF NOT EXISTS access_event_actor_at_idx
    ON access_event (actor, at DESC);
CREATE INDEX IF NOT EXISTS access_event_project_at_idx
    ON access_event (project_id, at DESC) WHERE project_id IS NOT NULL;

CREATE OR REPLACE FUNCTION access_event_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'access_event is append-only: % is not permitted (id=%)',
        TG_OP, OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS access_event_no_change ON access_event;
CREATE TRIGGER access_event_no_change
    BEFORE UPDATE OR DELETE ON access_event
    FOR EACH ROW EXECUTE FUNCTION access_event_is_append_only();

COMMENT ON TABLE access_event IS
    'Who read what: one row per list, version read, log read, export and stream attach. '
    'Append-only, no foreign key, written in the transaction of the read it records.';
