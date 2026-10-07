# Design decisions

Why the project is built the way it is, so the reasoning is not rediscovered
the hard way. Requirements say what must stay true; this file says why a given
approach was chosen and what was rejected. See [REQUIREMENTS.md](REQUIREMENTS.md).

How this file is used is set out in [CLAUDE.md](CLAUDE.md). In short: new code
follows an **Accepted** decision unless the user says otherwise, and a change
of mind adds a new entry that supersedes the old one. Never edit history.

Each entry has a stable ID. Never renumber or reuse one. A decision that no
longer holds is marked **Superseded by D-nn** and left in place.

**Status** is one of:

- **Accepted**: in force, and reflected in the code.
- **Proposed**: argued for and filed, not yet built or confirmed by the owner.
  Do not treat it as settled.
- **Superseded**: replaced. Kept for the history.

Entry shape: the decision, why, what was rejected, and where it comes from.

## Identity and the network

### D-01 Caddy, not nginx, as the identity boundary

- Status: Accepted
- Header deletion is a first-class verb in Caddy (`request_header -X`), where
  nginx can only send an empty header and silently does nothing if another
  `proxy_set_header` appears in a more specific block. SSE works by default.
  The whole config is one file.
- Rejected: nginx. Three ways to get the identity strip or SSE streaming subtly
  wrong, each with a failure that looks like an application bug.
- Source: `proxy/Caddyfile` header comment.

### D-02 The identity strip and set run in a fixed order

- Status: Accepted
- Strip the canonical headers, set them from the configured source, then strip
  the provider headers, reject if empty, forward. The provider strip must come
  after the set, because the set reads a provider header through a placeholder.
- Why it is written down: the strip once came first, which made every documented
  cloud deployment resolve to an empty identity and answer 401, invisibly, for
  months (#23).
- Source: `proxy/Caddyfile`; `tests/test_proxy_identity.py`.

### D-03 No password login

- Status: Accepted
- There is no user table, hash, registration form or token endpoint. Sign-in is
  the hospital's identity provider; the application learns who you are from one
  header.
- Why: offboarding works because disabling a user in the directory ends access
  everywhere at once; MFA is whatever the hospital already requires; password
  policy is the security office's job; and every credential feature is a thing
  to get wrong in a tool whose authentication surface is one header.
- Rejected: local accounts (the FastAPI `OAuth2PasswordRequestForm` pattern).
- Source: `docs/deploy.md`, "Why there is no password login"; closed issue #28.

### D-04 Network isolation, not code, is the boundary

- Status: Accepted
- The API publishes no host port. The only network `api` shares with anything
  internet-facing is `edge`, and the only other member is `proxy`. The database
  sits on an `internal: true` network with no gateway.
- Why: a header is trivially forged, and no code in the API can compensate for a
  reachable port. `TRUSTED_PROXY_CIDR` and `PROXY_SHARED_SECRET` are defense in
  depth, not substitutes.
- Source: `compose.yaml` header; `server/app/auth.py`.
- Known issue: `PROXY_SHARED_SECRET` is documented but no shipped config sends it
  (#61).

### D-05 No `--proxy-headers`

- Status: Accepted
- uvicorn is not run with proxy-header handling, because that rewrites the peer
  address from `X-Forwarded-For`, which the client controls, and
  `TRUSTED_PROXY_CIDR` would then be checking the attacker's own claim.
- Source: `server/app/main.py` docstring.

### D-06 CSRF defense is `Sec-Fetch-Site`, and CORS is off

- Status: Accepted
- The proxy authenticates on its own session, which a browser attaches to
  cross-site requests too. CORS governs reading a response, not whether a delete
  happened. `Sec-Fetch-Site` is set by the browser and cannot be altered by
  script. A request without it is a non-browser client and is allowed.
- Source: `server/app/main.py`, `reject_cross_site_writes`; closed issue #9.

## Data

### D-07 The project document is opaque `jsonb`

- Status: Accepted
- One `jsonb` column rather than a column per field, so the browser's schema can
  grow without a migration. The API treats the document as opaque apart from the
  merge rule (objects merge key by key, arrays replace).
- Source: `server/migrations/001_init.sql`.

### D-08 The merge runs in Python under a row lock

- Status: Accepted
- A read-modify-write inside a transaction holding `SELECT ... FOR UPDATE`.
- Rejected: a recursive `jsonb` merge in PL/pgSQL. It would be atomic too, but it
  is a second implementation of a rule the browser already defines in
  `app/js/00-core/00-util.js`, and two implementations drift. PostgreSQL's `||`
  is not an option at all: it merges only the top level.
- Source: `server/app/routes.py`, `patch_project` docstring.

### D-09 Version history stores full documents, not diffs

- Status: Accepted
- A governance record is kilobytes and a committee edits it a few times a week.
  Reconstructing a point in time by replaying diffs is the operation you least
  want to debug while answering a regulator.
- Cost: unbounded growth with no retention policy (#54).
- Source: `server/migrations/002_versions.sql`.

### D-10 History survives deletion, with no foreign key

- Status: Accepted
- `project_version` deliberately has no foreign key to `projects`. "The record
  was deleted on this date, and here is what it contained" is itself an audit
  finding. The audit log cascades because it belongs to the live project.
- Consequence: DELETE does not erase content, which collides with erasure (#36).
- Source: `002_versions.sql`.

### D-11 Disposal is a tombstone

- Status: Accepted
- Purge empties `doc` and keeps the row, with `purged_at` and `purged_by`, rather
  than deleting. A vanished row is indistinguishable from a snapshot never taken.
  The trigger permits exactly that transition and nothing else.
- Source: `server/migrations/003_version_access.sql`.

### D-12 Each snapshot carries the access list it was written under

- Status: Accepted
- Otherwise deleting a project removed its live row, the access check was
  skipped, and every retained snapshot became readable by anyone. Deleting a
  restricted record widened access to it.
- Source: `003_version_access.sql`.

### D-13 An incarnation separates reused project ids

- Status: Accepted
- Project ids are caller-chosen and snapshots outlive their project, so a new
  project reusing an id collided with the old history. An incarnation column
  keeps the histories apart.
- Source: `server/migrations/004_version_incarnation.sql`; closed issue #10.

### D-14 Postgres is pinned to a major version

- Status: Accepted
- Postgres does not migrate its on-disk format. Moving 17 to 18 under a live
  volume makes the cluster unreadable and needs `pg_upgrade` or a dump and
  restore. A floating tag would do that on an unrelated `docker compose pull`.
- Source: `compose.yaml`.

## Operations

### D-15 The dashboard is built on the host, not in Docker

- Status: Accepted
- `pixi run build-app` generates `docs/app/index.html`, which the proxy mounts
  read-only. For the cloud, `proxy/Dockerfile` copies it in.
- Source: `compose.yaml`; `proxy/Dockerfile`.

### D-16 The rate limiter is in-process and per replica

- Status: Accepted
- With N replicas the effective ceiling is N times the limit. A shared counter
  would mean Redis or a database round trip per request, for a limiter whose job
  is to blunt a runaway client, not to meter an API. The hard protections are the
  body cap, the SSE stream cap and network isolation.
- Source: `server/app/main.py`, `SlidingWindowRateLimiter` docstring.

### D-17 Backups are `pg_dump` through the running server, encrypted

- Status: Accepted
- Never a copy of the volume's files, which gives a torn snapshot of a live
  cluster. `gpg --symmetric` because it is on far more machines than `age`.
- Source: `Makefile`, `backup` target.

### D-18 `make doctor` checks the password over the API's own path

- Status: Accepted
- `initdb` trusts the Unix socket and loopback, and only the appended
  `host all all all scram-sha-256` line asks for a password. A check using
  `-h 127.0.0.1` passes against a database it is locked out of. `-h db` is the
  only path that tests anything.
- Source: `scripts/doctor.py`; closed issue #26.

## Engineering

### D-19 Enumerated types, enforced by a ratcheting checker

- Status: Accepted
- A closed set of values gets a `StrEnum` (Python) or a frozen object
  (JavaScript). The existing bare-string uses are baselined and may only shrink.
- Why a custom checker and not ruff's `PLR2004`: it produced about 190 hits,
  mostly protocol constants and punctuation, and a noisy guardrail gets switched
  off. The ratchet means legacy code does not block work and new code cannot add
  to the problem.
- Why tests are exempt: a test may pin a wire value on purpose, and that is the
  test that proves a field was not silently renamed.
- Hardened after an adversarial review: 28 evasions were reproduced, 20 closed
  (inline `frozenset` and dict membership, `is`, hyphenated values, `Literal`
  aliases, `Field(pattern=...)`, JS `.includes`, backticks, comparisons wrapped
  across lines, and a pragma hidden in a string). The scanner reads real
  comments, so a pragma only counts in one.
- Hook scope: the first version fired only on Write and Edit, which skips most of
  what an agent working through Bash writes. It now also runs after Bash and
  checks every file git reports changed.
- Left uncaught on purpose: aliased constants, hoisted tuples, dispatch dicts,
  reverse `in`, `operator.eq` and lowercase JS state. Each would flag ordinary
  code in bulk. They are documented as blind spots rather than hidden.
- A file the checker cannot parse is reported as a violation, not skipped.
- Source: `scripts/check_enums.py`; [CLAUDE.md](CLAUDE.md).

### D-22 The storage mode is an enum, and each mode owns its labels

- Status: Accepted
- `Mode` (`app/js/00-core/30-state.js`) is a frozen object with `CONNECTING`,
  `LOCAL`, `API` and `ARTIFACT`. What a save tells the user is looked up in
  `SAVED_LABEL`, keyed by `Mode`, rather than chosen by a comparison.
- Why: `MODE` was assigned `"api"` in one file and compared with `"shared"` in
  another, so the server-backed mode reported "Saved in this browser" after every
  save (#55), contradicting the header beside it.
- An unknown mode falls back to a label that claims nothing ("Saved") rather than
  to one that claims the wrong place. Only `LOCAL` may mention the browser, and
  the test asserts it.
- The artifact mode's value changed from `"shared"` to `"artifact"`. Nothing
  outside the app read it.
- Source: closed issue #55; R-04.

### D-20 Pre-commit is the only CI gate today

- Status: Accepted, **known gap** (#32)
- `lint.yml` runs `prek` and nothing else, so no test runs on a pull request.
  This is a description of the present, not an endorsement. Do not claim a
  property is "tested" on the strength of a test file that CI never executes.

### D-24 The server decides who signed a checkpoint, and when

- Status: Accepted
- `server/app/signoff.py` rewrites `gates.*.signedBy` and `signedAt` from the
  caller and the clock on create and on patch, mirroring what `append_log`
  already does for the audit log's `at` and `by`.
- Attribution follows the *decision*, not the claim. Changing a decision without
  sending any attribution would otherwise leave the record saying the previous
  person made the new decision. Setting or changing one attributes it to the
  caller; clearing one clears it; recording a periodic review attributes the
  reviewer.
- An unchanged decision is a **no-op, not an error**. The browser may re-send a
  whole gate, and a 403 would be read by the app as "your access changed" and put
  the user into read-only mode. Forgery is prevented by ignoring the claim, not
  by punishing it.
- Rejected: failing the request when a client sends a wrong `signedBy`. It turns
  an ordinary resend into a visible failure and teaches nothing the caller can
  act on.
- Only `signedBy` and `signedAt` are the server's. `by`, `date` and `rationale`
  are the committee's own words and stay as sent.
- A project created with pre-signed gates (an import) is attributed to whoever
  creates it. They are the one asserting it in this deployment; the original
  signer is not authenticated here and cannot be.
- With identity disabled (`REQUIRE_IDENTITY=false`) nothing is attributed, the
  same carve-out `access.py` makes, and `/api/health` reports it.
- Known limit: nothing signs the attestation cryptographically. The proxy
  identity is the trust anchor for everything here; making the sign-off match it
  is the fix, not raising it above it.
- Source: closed issue #31; R-09.

### D-25 The API assembles the database URL; compose passes the pieces

- Status: Accepted
- `compose.yaml` hands the API `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`,
  `POSTGRES_DB` and `POSTGRES_PASSWORD`. `build_database_url` in `config.py`
  assembles the URL and percent-encodes every part, so the choice of password is
  irrelevant. An explicit `DATABASE_URL` still wins, for managed instances whose
  URL carries `sslmode` or a Cloud SQL socket the pieces cannot express.
- Why: compose cannot percent-encode. `postgresql://u:${POSTGRES_PASSWORD}@db/..`
  broke on a `/` in the password, which the documented generator produces about
  half the time (measured: 47% of 20,000).
- A hand-written `DATABASE_URL` that cannot be parsed fails at startup with a
  message that names the likely cause and the way out, and **never echoes the
  password**. urllib's own message embeds the offending text, which here is the
  start of the password, and an error that quotes a credential ends up in a log
  aggregator.
- Rejected: telling operators to use `openssl rand -hex`. It shifts the burden to
  every operator and to every password manager, fixes nothing for a password
  chosen by a person, and leaves a first-run path that works only if you happened
  to read the right sentence.
- Rejected: rejecting such passwords in `preflight.py`. Correct passwords would
  be refused to protect a code path that should simply be correct.
- Source: R-25.

## Proposed, not yet decided

### D-21 PHI detection runs in an opt-in sidecar, advisory only

- Status: **Proposed** (#65, #66, #67)
- The detector (OpenMed) cannot be bundled into a single-file dashboard (R-01),
  and adding it to the API image would add gigabytes and a large CVE surface. A
  separate container, absent by default, behind `POST /api/phi-check`.
- Advisory, never blocking: a governance record says "patient" constantly. The
  acknowledgment is itself recorded.
- Must not claim "no PHI detected". OpenMed publishes no aggregate F1, precision
  or recall, and says a clean result is not a compliance claim.
- Waits on R-21: the data classification is the owner's decision first.
