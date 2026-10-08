-- 008_retention.sql -- disposal at the end of the retention period, and litigation
-- holds (#57; R-54, R-56, D-62).
--
-- R-54 set the periods: a project's record for the life of the AI solution plus six
-- years after it is retired, and the read trail for six years (or the organization's
-- shorter audit-log policy). Nothing applied them, because applying them removes rows
-- from append-only tables (R-10). The owner granted that exception on #57, on three
-- terms, and this file is those terms:
--
--   * Disposal is a PURGE, not a vanishing. A project past its period has its
--     revisions purged and its live record deleted, through the same transitions the
--     triggers already permit, so a tombstone of who, when and what it hashed to
--     stays (R-12). The read trail is the one table whose rows are deleted.
--   * Disposal is run by an operator, as the owner role: `make dispose` reports what
--     is due, and `make dispose APPLY=1` disposes of it. The API cannot: its role has
--     no DELETE on the read trail and no EXECUTE on dispose_due().
--   * A litigation hold on a project stops its disposal, and its read trail's, until
--     the hold is lifted. Holds are append-only, with who, when and why.
--
-- The rule for when a project's clock starts, in one place (retention_due below):
-- the project is RETIRED when checkpoint A, B or C decided "Stop" or checkpoint D
-- decided "Retire" (phase() in app/js/10-frameworks/10-chai/10-rules.js, which
-- server/tests/test_retention.py keeps in step with this file). The clock starts at
-- the LATEST of those decisions' dates and the record's last change, so a later edit,
-- or a retirement dated in the future, only ever makes the record live longer. A
-- deleted project's clock starts when it was deleted.

-- ---------------------------------------------------------------------------
-- The periods. One row. The organization's schedule takes precedence (R-54), so
-- an operator may change them, as the owner role; the change is stamped.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS retention_policy (
    singleton         boolean     PRIMARY KEY DEFAULT true CHECK (singleton),
    record_years      integer     NOT NULL DEFAULT 6 CHECK (record_years >= 1),
    read_trail_years  integer     NOT NULL DEFAULT 6 CHECK (read_trail_years >= 1),
    changed_at        timestamptz NOT NULL DEFAULT now(),
    changed_by        text        NOT NULL DEFAULT current_user
);

INSERT INTO retention_policy DEFAULT VALUES ON CONFLICT DO NOTHING;

COMMENT ON TABLE retention_policy IS
    'How long a retired project''s record and the read trail are kept (R-54). One '
    'row; changing it is stamped with who and when. The organization''s own '
    'schedule takes precedence over the defaults.';

CREATE OR REPLACE FUNCTION retention_policy_stamp() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'retention_policy cannot be deleted; change its values'
            USING ERRCODE = 'restrict_violation';
    END IF;
    NEW.changed_at := now();
    NEW.changed_by := current_user;
    RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS retention_policy_stamped ON retention_policy;
CREATE TRIGGER retention_policy_stamped
    BEFORE UPDATE OR DELETE ON retention_policy
    FOR EACH ROW EXECUTE FUNCTION retention_policy_stamp();

-- ---------------------------------------------------------------------------
-- Litigation holds. Append-only: placing and lifting are both rows, so the hold's
-- history is itself evidence. Keyed by project id, not incarnation, so a hold
-- covers every record that has used the id.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS retention_hold (
    id          bigserial   PRIMARY KEY,
    project_id  text        NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    by_id       text        NOT NULL,
    action      text        NOT NULL,
    reason      text        NOT NULL,
    CONSTRAINT retention_hold_action_known CHECK (action IN ('place', 'lift')),
    CONSTRAINT retention_hold_has_reason CHECK (btrim(reason) <> '')
);

CREATE INDEX IF NOT EXISTS retention_hold_project_idx
    ON retention_hold (project_id, id DESC);

COMMENT ON TABLE retention_hold IS
    'Litigation holds: who placed or lifted one on a project, when and why. '
    'Append-only. A project whose latest row is a place is not disposed of.';

CREATE OR REPLACE FUNCTION retention_hold_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'retention_hold is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

DROP TRIGGER IF EXISTS retention_hold_no_change ON retention_hold;
CREATE TRIGGER retention_hold_no_change
    BEFORE UPDATE OR DELETE ON retention_hold
    FOR EACH ROW EXECUTE FUNCTION retention_hold_is_append_only();

CREATE OR REPLACE FUNCTION retention_held(pid text) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        (SELECT action = 'place' FROM retention_hold
          WHERE project_id = pid ORDER BY id DESC LIMIT 1),
        false)
$$;

-- ---------------------------------------------------------------------------
-- What a disposal run did. Append-only: "this was disposed of under the policy,
-- by whom and when" is the answer to "why is this gone?" (R-12).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS disposal_run (
    id                 bigserial   PRIMARY KEY,
    at                 timestamptz NOT NULL DEFAULT now(),
    run_by             text        NOT NULL,
    record_years       integer     NOT NULL,
    read_trail_years   integer     NOT NULL,
    projects           integer     NOT NULL,
    revisions          integer     NOT NULL,
    read_events        bigint      NOT NULL,
    read_trail_before  timestamptz NOT NULL,
    disposed           jsonb       NOT NULL DEFAULT '[]'::jsonb
);

COMMENT ON TABLE disposal_run IS
    'One row per applied disposal: who ran it, under which periods, and which '
    'project incarnations and how many read-trail rows it disposed of. Append-only.';

CREATE OR REPLACE FUNCTION disposal_run_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'disposal_run is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

DROP TRIGGER IF EXISTS disposal_run_no_change ON disposal_run;
CREATE TRIGGER disposal_run_no_change
    BEFORE UPDATE OR DELETE ON disposal_run
    FOR EACH ROW EXECUTE FUNCTION disposal_run_is_append_only();

-- ---------------------------------------------------------------------------
-- The read trail may now lose rows, but only rows past the policy's period and
-- not under a hold. Still no UPDATE, ever. The API's role has no DELETE grant at
-- all (app/roles.py), so this is the condition an operator's DELETE must meet.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION access_event_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND OLD.at < now() - make_interval(
               years => (SELECT read_trail_years FROM retention_policy))
       AND (OLD.project_id IS NULL OR NOT retention_held(OLD.project_id))
    THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'access_event is append-only: % is not permitted (id=%)',
        TG_OP, OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$;

-- ---------------------------------------------------------------------------
-- What is due. A date a person typed is used only if it is a real date.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION retention_gate_date(gate jsonb) RETURNS timestamptz
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
    IF gate ->> 'date' ~ '^\d{4}-\d{2}-\d{2}$' THEN
        RETURN ((gate ->> 'date')::date + 1)::timestamp AT TIME ZONE 'UTC';
    END IF;
    RETURN NULL;
EXCEPTION WHEN others THEN
    RETURN NULL;  -- 2024-02-30 and the like
END;
$fn$;

CREATE OR REPLACE FUNCTION retention_due()
RETURNS TABLE (
    project_id   text,
    incarnation  uuid,
    kind         text,
    clock_start  timestamptz,
    due          timestamptz,
    held         boolean
)
LANGUAGE sql STABLE AS $$
    WITH policy AS (
        SELECT make_interval(years => record_years) AS keep FROM retention_policy
    ),
    retired AS (
        -- A live project whose checkpoints say it is retired.
        SELECT p.id, p.incarnation, 'retired'::text AS kind,
               greatest(
                   p.updated_at,
                   CASE WHEN g.a ->> 'decision' = 'Stop' THEN retention_gate_date(g.a) END,
                   CASE WHEN g.b ->> 'decision' = 'Stop' THEN retention_gate_date(g.b) END,
                   CASE WHEN g.c ->> 'decision' = 'Stop' THEN retention_gate_date(g.c) END,
                   CASE WHEN g.d ->> 'decision' = 'Retire' THEN retention_gate_date(g.d) END
               ) AS clock_start
          FROM projects p,
               LATERAL (SELECT p.doc #> '{gates,A}' AS a, p.doc #> '{gates,B}' AS b,
                               p.doc #> '{gates,C}' AS c, p.doc #> '{gates,D}' AS d) g
         WHERE g.a ->> 'decision' = 'Stop'
            OR g.b ->> 'decision' = 'Stop'
            OR g.c ->> 'decision' = 'Stop'
            OR g.d ->> 'decision' = 'Retire'
    ),
    gone AS (
        -- A history whose live record is gone and that still holds content: from
        -- its tombstone, or, for one deleted before tombstones existed (005), from
        -- its last revision.
        SELECT v.project_id AS id, v.incarnation, 'deleted'::text AS kind,
               coalesce(max(d.deleted_at), max(v.changed_at)) AS clock_start
          FROM project_version v
          LEFT JOIN project_deletion d
                 ON d.project_id = v.project_id AND d.incarnation = v.incarnation
         WHERE v.purged_at IS NULL
           AND NOT EXISTS (SELECT 1 FROM projects p
                            WHERE p.id = v.project_id
                              AND p.incarnation = v.incarnation)
         GROUP BY v.project_id, v.incarnation
    )
    SELECT c.id, c.incarnation, c.kind, c.clock_start, c.clock_start + policy.keep,
           retention_held(c.id)
      FROM (SELECT * FROM retired UNION ALL SELECT * FROM gone) c, policy
     WHERE c.clock_start + policy.keep <= now()
     ORDER BY c.clock_start, c.id
$$;

CREATE OR REPLACE FUNCTION read_trail_due()
RETURNS TABLE (cutoff timestamptz, events bigint, held bigint)
LANGUAGE sql STABLE AS $$
    WITH cut AS (
        SELECT now() - make_interval(years => read_trail_years) AS before
          FROM retention_policy
    )
    -- count(e.id), not count(*): with no row past the cutoff, the LEFT JOIN still
    -- yields one empty row, and it is not a read.
    SELECT cut.before AS cutoff,
           count(e.id) FILTER (WHERE e.project_id IS NULL
                                  OR NOT retention_held(e.project_id)),
           count(e.id) FILTER (WHERE e.project_id IS NOT NULL
                                  AND retention_held(e.project_id))
      FROM cut LEFT JOIN access_event e ON e.at < cut.before
     GROUP BY cut.before
$$;

-- ---------------------------------------------------------------------------
-- Disposal. One transaction: everything due and not held, or nothing.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION dispose_due(run_by text) RETURNS disposal_run
LANGUAGE plpgsql AS $fn$
DECLARE
    actor     constant text := 'system:retention';
    t         constant timestamptz := now();
    pol       retention_policy;
    r         record;
    n_rev     integer;
    n_projects  integer := 0;
    n_revisions integer := 0;
    n_events    bigint;
    cut       timestamptz;
    done      jsonb := '[]'::jsonb;
    result    disposal_run;
BEGIN
    IF run_by IS NULL OR btrim(run_by) = '' THEN
        RAISE EXCEPTION 'dispose_due needs the name of whoever is running it';
    END IF;
    SELECT * INTO pol FROM retention_policy;
    cut := t - make_interval(years => pol.read_trail_years);

    FOR r IN SELECT * FROM retention_due() d WHERE NOT d.held LOOP
        -- The live record first, from its row lock, the way DELETE /api/projects
        -- does it: the tombstone, then the row (its log goes by ON DELETE CASCADE).
        IF r.kind = 'retired' THEN
            INSERT INTO project_deletion
                   (project_id, incarnation, deleted_at, deleted_by, last_rev, last_md5)
            SELECT p.id, p.incarnation, t, actor, p.rev, v.content_md5
              FROM projects p
              LEFT JOIN project_version v
                     ON v.project_id = p.id
                    AND v.incarnation = p.incarnation
                    AND v.rev = p.rev
             WHERE p.id = r.project_id AND p.incarnation = r.incarnation;
            DELETE FROM projects
             WHERE id = r.project_id AND incarnation = r.incarnation;
        END IF;
        -- Then the history: the purge transition the trigger permits (R-12).
        UPDATE project_version
           SET doc = '{}'::jsonb, purged_at = t, purged_by = actor
         WHERE project_version.project_id = r.project_id
           AND project_version.incarnation = r.incarnation
           AND purged_at IS NULL;
        GET DIAGNOSTICS n_rev = ROW_COUNT;
        n_projects := n_projects + 1;
        n_revisions := n_revisions + n_rev;
        done := done || jsonb_build_object(
            'project', r.project_id, 'incarnation', r.incarnation,
            'kind', r.kind, 'clock_start', r.clock_start, 'revisions', n_rev);
    END LOOP;

    DELETE FROM access_event
     WHERE at < cut
       AND (access_event.project_id IS NULL
            OR NOT retention_held(access_event.project_id));
    GET DIAGNOSTICS n_events = ROW_COUNT;

    INSERT INTO disposal_run (at, run_by, record_years, read_trail_years, projects,
                              revisions, read_events, read_trail_before, disposed)
    VALUES (t, run_by, pol.record_years, pol.read_trail_years, n_projects, n_revisions,
            n_events, cut, done)
    RETURNING * INTO result;
    RETURN result;
END;
$fn$;

COMMENT ON FUNCTION dispose_due(text) IS
    'Dispose of everything past its retention period and not under a hold, in one '
    'transaction, and record the run. Run by an operator as the owner role '
    '(make dispose APPLY=1); the API''s role cannot execute it.';

REVOKE ALL ON FUNCTION dispose_due(text) FROM PUBLIC;
