-- 012_retirement_ack_database.sql -- an acknowledgment belongs to one database
-- (#168 PR C; R-66, D-76).
--
-- A change of the retirement rules is made only when RETIREMENT_RULES_ACK is the
-- acknowledgment of exactly that change (app/retirement.py, transition_ack). It named
-- the history row it follows by id, a bigserial, so another database at the same
-- point in the same history (staging and production, or two fresh databases built
-- the same way) accepted the same value. A random value stored in the database would
-- not fix that for a copy: a dump carries every row, so staging restored from a
-- production dump would hold production's value, and a value printed on one would be
-- accepted by the other.
--
-- So the acknowledgment binds what a dump does not copy, read here:
--
-- * cluster: the cluster's system identifier (pg_control_system()), set by initdb.
--   Every cluster has its own; a restore into another cluster has another.
-- * database: this database's OID. A restore into another database, in this cluster
--   or any other, has another, and so does a database dropped and created again.
-- * history: the OID of retirement_rule_change. A restore over this database in place
--   (`make restore`: pg_dump --clean drops and recreates every table) recreates the
--   table, which gets a new OID.
--
-- What keeps all three is a copy of the files rather than a dump: a base backup,
-- point-in-time recovery, a volume or disk snapshot, or a promoted replica. To the
-- acknowledgment such a copy is the database it was copied from, and the original
-- accepts a value printed on the copy. A restore of the data alone into the tables
-- already there (--data-only, or TRUNCATE and reload) keeps all three too (D-76
-- says so).

CREATE OR REPLACE FUNCTION retirement_ack_database()
RETURNS TABLE (cluster text, database bigint, history bigint)
LANGUAGE sql STABLE AS $$
    SELECT (SELECT system_identifier::text FROM pg_control_system()),
           (SELECT oid::bigint FROM pg_database WHERE datname = current_database()),
           'retirement_rule_change'::regclass::oid::bigint
$$;

COMMENT ON FUNCTION retirement_ack_database() IS
    'What makes an acknowledgment of a retirement rule change this database''s '
    '(D-76): the cluster''s system identifier, the database''s OID and the OID of '
    'retirement_rule_change. A dump copies none of them.';
