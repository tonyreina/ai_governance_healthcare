-- 011_retirement_rule_principals.sql -- the rules' history names a person (#57, R-54).
--
-- retirement_rule_change.changed_by (010) records who changed the retirement rules.
-- R-54 keeps a person's name and email as long as a retained record names them, so
-- principal_referenced (009) must look there too, or disposal could delete the
-- principal of someone that history still names. server/tests/test_retention.py
-- fails if a column that names a person is not read here. 009 is never edited; this
-- is its function with one more clause.

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
     OR EXISTS (SELECT 1 FROM retirement_rule_change rc, w
                 WHERE lower(rc.changed_by) = w.v)
    )
$$;
