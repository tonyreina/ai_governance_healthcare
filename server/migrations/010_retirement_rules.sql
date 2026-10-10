-- 010_retirement_rules.sql -- retirement comes from the build's framework definition
-- (#168 PR C; R-66, D-76).
--
-- 008 decided when a project is RETIRED, and so when its retention clock starts
-- (R-56), from CHAI's own words: checkpoint A, B or C decided "Stop", or D decided
-- "Retire". A build may now use another framework (R-63), whose checkpoints and
-- words differ, so a literal rule here would keep that build's records forever, or
-- worse, read its words with CHAI's meaning.
--
-- So the rule is data: retirement_rule holds every (framework, checkpoint, decision)
-- that ends a project. The migrate job (app/retirement.py) loads it from the build's
-- manifest (docs/app/manifest.json, written by scripts/build_app.py from the same
-- definitions the page embeds): no pair is added or removed unless the operator
-- acknowledges that change (D-76). Every change is a row in
-- retirement_rule_change, which is append-only.
--
-- This file seeds CHAI's four rows, so a database migrated before any manifest is
-- synced retires exactly what 008 retired. A record carries its framework in
-- meta.framework.id; a record with none is CHAI's, because every record written
-- before frameworks were stamped is.

CREATE TABLE IF NOT EXISTS retirement_rule (
    framework_id  text NOT NULL,
    gate_id       text NOT NULL,
    decision      text NOT NULL,
    PRIMARY KEY (framework_id, gate_id, decision),
    -- The definition's id pattern (schema/framework.schema.json), so a rule can
    -- only name what a definition could.
    CONSTRAINT retirement_rule_framework_id CHECK
        (framework_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'),
    CONSTRAINT retirement_rule_gate_id CHECK
        (gate_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'),
    CONSTRAINT retirement_rule_decision CHECK (btrim(decision) <> '')
);

COMMENT ON TABLE retirement_rule IS
    'Which checkpoint decisions end a project, per framework (R-66). A project whose '
    'record holds one is retired and its retention clock starts (R-56). Loaded by '
    'the migrate job from the build manifest; the API may only read it.';

INSERT INTO retirement_rule (framework_id, gate_id, decision) VALUES
    ('chai', 'A', 'Stop'),
    ('chai', 'B', 'Stop'),
    ('chai', 'C', 'Stop'),
    ('chai', 'D', 'Retire')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- The history of the rules. Append-only, like the holds and the disposal runs:
-- "why was this record disposed of, by which rule, set when and by whom" has to
-- have an answer that cannot be edited afterwards.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS retirement_rule_change (
    id               bigserial   PRIMARY KEY,
    at               timestamptz NOT NULL DEFAULT now(),
    changed_by       text        NOT NULL DEFAULT current_user,
    source           text        NOT NULL,
    framework_id     text        NOT NULL,
    old_rules        jsonb       NOT NULL,
    new_rules        jsonb       NOT NULL,
    rule_set_hash    text        NOT NULL,
    definition_hash  text,
    acknowledged     boolean     NOT NULL DEFAULT false,
    CONSTRAINT retirement_rule_change_source_known
        CHECK (source IN ('seed', 'manifest')),
    CONSTRAINT retirement_rule_change_hash
        CHECK (rule_set_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT retirement_rule_change_definition_hash
        CHECK (definition_hash IS NULL OR definition_hash ~ '^[0-9a-f]{64}$')
);

COMMENT ON TABLE retirement_rule_change IS
    'Every change to retirement_rule: who, when, the rules before and after, the '
    'hash of the primary framework''s rule set and of its definition, and whether a '
    'change was acknowledged. Append-only. The latest row''s rule_set_hash is the '
    'active one, which /api/health reports.';

CREATE OR REPLACE FUNCTION retirement_rule_change_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'retirement_rule_change is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$fn$;

DROP TRIGGER IF EXISTS retirement_rule_change_no_change ON retirement_rule_change;
CREATE TRIGGER retirement_rule_change_no_change
    BEFORE UPDATE OR DELETE ON retirement_rule_change
    FOR EACH ROW EXECUTE FUNCTION retirement_rule_change_is_append_only();

-- The seed, recorded like any other change. The hash is of CHAI's rule set as
-- scripts/build_app.py computes it; server/tests/test_retention.py holds the two
-- equal, and equal to the default build's manifest.
INSERT INTO retirement_rule_change
       (source, framework_id, old_rules, new_rules, rule_set_hash)
SELECT 'seed', 'chai', '[]'::jsonb,
       '[["chai", "A", "Stop"], ["chai", "B", "Stop"], ["chai", "C", "Stop"],
         ["chai", "D", "Retire"]]'::jsonb,
       '941520e1fccb882717349cdf052699d4aaaf255dfcdcbf39db7fdcdf2edda501'
 WHERE NOT EXISTS (SELECT 1 FROM retirement_rule_change);

-- ---------------------------------------------------------------------------
-- Whose rules a record follows: its stamp, or CHAI's when it has none.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION record_framework(doc jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(nullif(doc #>> '{meta,framework,id}', ''), 'chai')
$$;

-- ---------------------------------------------------------------------------
-- The live projects a rule set retires, and when each one's clock starts: the
-- LATEST of its ending decisions' dates and its last change, so a later edit, or a
-- retirement dated in the future, only ever makes the record live longer (as 008).
-- The rule set is three parallel arrays, so the migrate job can ask what a rule set
-- it has not applied yet would retire, through the same definition. The checkpoint
-- id is a JSON key read with ->, never a path built from a string.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION retired_under(
    rule_framework text[], rule_gate text[], rule_decision text[])
RETURNS TABLE (project_id text, incarnation uuid, clock_start timestamptz)
LANGUAGE sql STABLE AS $$
    SELECT p.id, p.incarnation,
           greatest(p.updated_at, max(retention_gate_date(p.doc -> 'gates' -> r.g)))
      FROM projects p
      JOIN unnest(rule_framework, rule_gate, rule_decision) AS r(f, g, d)
        ON r.f = record_framework(p.doc)
       AND p.doc -> 'gates' -> r.g ->> 'decision' = r.d
     GROUP BY p.id, p.incarnation, p.updated_at
$$;

-- ---------------------------------------------------------------------------
-- What is due: 008's function with its retired arm reading retirement_rule. Same
-- signature, columns, kinds and clock.
-- ---------------------------------------------------------------------------

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
    rules AS (
        SELECT array_agg(framework_id ORDER BY framework_id, gate_id, decision) AS f,
               array_agg(gate_id ORDER BY framework_id, gate_id, decision) AS g,
               array_agg(decision ORDER BY framework_id, gate_id, decision) AS d
          FROM retirement_rule
    ),
    retired AS (
        -- A live project whose checkpoints say, by its framework's rules, that it
        -- has ended.
        SELECT x.project_id AS id, x.incarnation, 'retired'::text AS kind,
               x.clock_start
          FROM rules, LATERAL retired_under(rules.f, rules.g, rules.d) x
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
