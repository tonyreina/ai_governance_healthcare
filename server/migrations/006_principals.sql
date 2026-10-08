-- 006_principals.sql -- who an id is (#39).
--
-- Every access list, sign-off and log entry names a person by the identity id the
-- proxy asserted: an IAP numeric subject id, an ALB `sub`, an Entra object id.
-- Nothing could turn one into a person, so every identity but the viewer's own
-- rendered as the word "someone", and an owner doing an access review saw a list of
-- opaque ids that match nothing in any staff directory.
--
-- The proxy already asserts the name and email on every request, and the API
-- discarded them. This keeps what it was told, keyed by the id, as people sign in.
-- It is a directory built from observed sign-ins: it covers exactly the people who
-- can appear in an access list, and it needs no outbound call or credential for a
-- hospital to approve. It is also personal data about staff (name, email, when
-- first and last seen), so it is a record of processing; see docs/deploy.md.
--
-- Not an audit table: a name can change, so a row is updated in place. What a
-- sign-off recorded is in project_log, which is append-only.

CREATE TABLE IF NOT EXISTS principals (
    id          text PRIMARY KEY,
    name        text        NOT NULL DEFAULT '',
    email       text        NOT NULL DEFAULT '',
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE principals IS
    'Name and email the proxy asserted for each identity id, recorded as people '
    'sign in, so an access list or a sign-off can show a person instead of an id. '
    'Personal data about staff; resolved only for people the caller can already '
    'see on a project they can read.';
