-- 009_principal_disposal.sql -- staff names and emails past their period (#57).
--
-- R-54: a person's name and email (principals) are kept while they are active, then
-- as long as a retained record refers to them. 008 applied every other period and
-- left this one. A principal is due when they have not signed in for the read-trail
-- period AND nothing retained names them, by id or by email, in any column that
-- records who did something or inside any document, log entry, read detail or hold
-- reason (principal_referenced). The match is a case-insensitive substring, so an
-- id that is a prefix of another keeps both: it errs toward keeping.
--
-- A purge keeps a revision's author (R-12), so anyone who ever changed a retained
-- record stays listed for as long as that record is kept, which is the rule.
-- server/tests/test_retention.py fails if a table gains a column that names a
-- person and this function does not look at it.

CREATE OR REPLACE FUNCTION principal_referenced(who text) RETURNS boolean
LANGUAGE sql STABLE AS $$
    WITH w AS (SELECT lower(who) AS v)
    SELECT coalesce(btrim(who), '') <> '' AND (
        EXISTS (SELECT 1 FROM projects p, w
                 WHERE lower(p.created_by) = w.v OR lower(p.updated_by) = w.v
                    OR strpos(lower(p.doc::text), w.v) > 0)
     OR EXISTS (SELECT 1 FROM project_log l, w
                 WHERE lower(l.by_id) = w.v OR lower(l.purged_by) = w.v
                    OR strpos(lower(l.entry::text), w.v) > 0)
     OR EXISTS (SELECT 1 FROM project_version pv, w
                 WHERE lower(pv.changed_by) = w.v OR lower(pv.purged_by) = w.v
                    OR strpos(lower(pv.doc::text), w.v) > 0
                    OR strpos(lower(pv.access::text), w.v) > 0)
     OR EXISTS (SELECT 1 FROM project_deletion d, w WHERE lower(d.deleted_by) = w.v)
     OR EXISTS (SELECT 1 FROM access_event e, w
                 WHERE lower(e.actor) = w.v OR strpos(lower(e.detail::text), w.v) > 0)
     OR EXISTS (SELECT 1 FROM retention_hold h, w
                 WHERE lower(h.by_id) = w.v OR strpos(lower(h.reason), w.v) > 0)
     OR EXISTS (SELECT 1 FROM disposal_run r, w WHERE lower(r.run_by) = w.v)
     OR EXISTS (SELECT 1 FROM retention_policy rp, w WHERE lower(rp.changed_by) = w.v)
    )
$$;

CREATE OR REPLACE FUNCTION principals_due()
RETURNS TABLE (id text, last_seen timestamptz)
LANGUAGE sql STABLE AS $$
    SELECT pr.id, pr.last_seen
      FROM principals pr, retention_policy pol
     WHERE pr.last_seen < now() - make_interval(years => pol.read_trail_years)
       AND NOT principal_referenced(pr.id)
       AND NOT principal_referenced(pr.email)
     ORDER BY pr.last_seen
$$;

ALTER TABLE disposal_run ADD COLUMN IF NOT EXISTS principals integer NOT NULL DEFAULT 0;

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
    n_people    integer;
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

    -- Last, so a person known only from reads just deleted goes in the same run.
    DELETE FROM principals
     WHERE principals.id IN (SELECT d.id FROM principals_due() d);
    GET DIAGNOSTICS n_people = ROW_COUNT;

    INSERT INTO disposal_run (at, run_by, record_years, read_trail_years, projects,
                              revisions, read_events, read_trail_before, disposed,
                              principals)
    VALUES (t, run_by, pol.record_years, pol.read_trail_years, n_projects, n_revisions,
            n_events, cut, done, n_people)
    RETURNING * INTO result;
    RETURN result;
END;
$fn$;

REVOKE ALL ON FUNCTION dispose_due(text) FROM PUBLIC;
