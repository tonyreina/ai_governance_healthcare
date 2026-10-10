-- 012_retirement_ack_nonce.sql -- an acknowledgment belongs to one database
-- (#168 PR C; R-66, D-76).
--
-- A change of the retirement rules is made only when RETIREMENT_RULES_ACK is the
-- acknowledgment of exactly that change (app/retirement.py, transition_ack). It named
-- the history row it follows by id, a bigserial, so another database at the same
-- point in the same history (staging and production, or two fresh databases built
-- the same way) accepted the same value. So each database gets a random nonce here,
-- once, and the acknowledgment binds it too, with the time of the change it follows.
--
-- A dump carries this row, so a database restored from a dump has the nonce, and
-- the history, of the database it was taken from: a value printed against the state
-- in that dump is accepted again by the restored database. The acknowledgment
-- cannot tell a restore from the original, and does not claim to.

CREATE TABLE IF NOT EXISTS retirement_ack_nonce (
    only_row    boolean     PRIMARY KEY DEFAULT true,
    nonce       uuid        NOT NULL DEFAULT gen_random_uuid(),
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT retirement_ack_nonce_one_row CHECK (only_row)
);

COMMENT ON TABLE retirement_ack_nonce IS
    'One random value per database, which every acknowledgment of a retirement rule '
    'change binds (D-76), so a value printed for one database is refused by another '
    'with the same history. Restored with a dump, like the history. The API has no '
    'access to it.';

INSERT INTO retirement_ack_nonce DEFAULT VALUES ON CONFLICT DO NOTHING;
