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
- Known issue, fixed: `PROXY_SHARED_SECRET` was documented but no shipped config
  sent it, so enabling it made every request 403 (#61). See D-30.

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
- The header is the same shape: `MODE_LABEL`, keyed by `Mode`, with a text and a
  CSS class per mode, and a test that every mode has one and no two share a
  text. The artifact mode was labeled "Shared workspace", as the server was
  (#64), and now says "Claude artifact", saves to "this Claude artifact", and
  shows a standing notice. The notice states where the data lives and what the
  comparison in `docs/running.md` says it lacks, and says not to enter
  patient-identifiable information, as the browser-only banner does. That is
  about the artifact mode only: it says nothing about the server mode, whose
  classification is still open (R-21).
- Source: closed issue #55; R-04.

### D-20 Pre-commit is the only CI gate

- Status: **Superseded by D-23**
- `lint.yml` ran `prek` and nothing else, so no test ran on a pull request (#32).
  Kept for the history: until D-23, a property could not honestly be called
  "tested" on the strength of a test file CI never executed.

### D-23 CI runs every test, in four jobs, and a skip fails

- Status: Accepted
- `.github/workflows/test.yml` runs on every pull request and on main:
  **workflows** (unit: `test-workflows`, `test-enums`, and `actionlint`),
  **server** (the API against a PostgreSQL 17 service container), **browser**
  (the dashboard suites in Chromium) and **stack** (the proxy, then the Compose
  stack end to end). A fifth job, **tests passed**, depends on all of them and
  treats a skipped job as a failure, so one check name can gate a merge and a new
  job cannot be forgotten.
- Why three environments: what the server tests exercise IS the database (a row
  lock, a trigger), the dashboard needs a browser, and the identity handoff needs
  a real Caddy. A fake would test the fake.
- Why `REQUIRE_TESTS`: a skip exits 0. On a runner with no database 106 of 201
  server tests skip and the run is green. See R-24.
- Why the CI configuration has unit tests: the gap opened because a test could be
  added and left out of CI. `test_workflows.py` fails if any `pixi run test-*`
  task is not run by CI, if a test file has no task, if Postgres drifts from the
  version `compose.yaml` pins, or if a job loses its timeout. Each rule has a
  mutation test.
- Found by running it: `test_stack.py`'s browser section had been broken since the
  Content-Security-Policy shipped, because `wait_for_function` evaluates a string
  and the policy forbids `unsafe-eval`. It is fixed with a polling helper, which
  keeps the app under the policy it ships with rather than bypassing it.
- Branch protection is on. The owner enabled the `protect-main` ruleset, which
  requires a pull request and the `tests passed` check (pinned to the GitHub
  Actions app, so nothing else can satisfy it by posting a status of the same
  name) and blocks force-pushes and deletion. It has **no bypass actors**, so it
  applies to administrators too. Verified by trying to merge a throwaway PR
  twice, once with the check pending and once with it red; both were refused.
  The first attempt found that the ruleset had been saved with an EMPTY
  required-checks list, which enforced nothing, so verify it rather than
  trusting that it is on.
- It is a repository setting, not a file, so nothing in the repo can detect it
  being switched off (C-48). To check it: `gh api
  repos/OWNER/REPO/rules/branches/main`.
- Actions are pinned by tag, matching the existing workflows; pinning by commit
  SHA is #37.
- Source: #32; R-23, R-24.

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

### D-26 The walkthrough video is hosted on the docs site, under a bounded cap

- Status: Accepted
- The source recording was 160 MB (2392x1462, 14.5 Mbps), over GitHub's 100 MB
  push limit and the repo's own 512 KB guard. A screen recording compresses
  extremely well: re-encoded to 1920 px wide, H.264, CRF 26, it is **7.5 MB** at
  the same 91 seconds, which also fits GitHub's 10 MB free-plan limit for inline
  video attachments.
- Hosted on the docs site (`docs/assets/`) and played with a plain `<video>`.
  Rejected: YouTube or Vimeo (a third-party iframe, against the spirit of R-05);
  a README drag-and-drop upload (a manual browser step, hosted by GitHub outside
  the repo and not versioned with it); a Release asset (works, but is not shown
  on the project's own page).
- Cost, accepted: about 7.6 MB added to git history, permanently. The repo was
  about 6 MB. Rewriting a public repo's history to remove it later would be worse
  than the cost, so this is the decision to revisit *before* adding a second
  video, not after.
- The repo-wide 512 KB limit is unchanged. Media under `docs/assets/` gets its own
  hook with a 10 MB cap, and `tests/test_docs_media.py` fails if that number and
  the page's assumption ever differ. An exception with a cap is a different thing
  from no limit.
- The poster is the portfolio overview, chosen because it is the most legible
  single frame. The video shows the browser's own chrome (a profile chip and an
  extension button), which is public now.
- Source: R-26.

### D-27 Claims are rows with a quoted sentence and evidence CI runs

- Status: Accepted
- `docs/security-claims.md` has one section per claim: the claim, one or more
  `Asserted in` entries (a file and the sentence **quoted**), a status, the
  evidence, and for anything not fully enforced the gap and its issue.
  `scripts/check_claims.py` verifies it.
- The quote is the key design choice. A claim list that only names tests rots
  silently when the doc is edited. Quoting the sentence means editing the doc
  fails the check until the row is reviewed, which is when "is this still true?"
  gets asked.
- Evidence must be something **CI runs**: a `server/tests` test, a `tests/` suite
  with a pixi task in `test.yml`, or a pre-commit hook. A test nobody runs is
  what #32 was.
- Four statuses, one of them `violated`. A claim the code does not back may stay
  in the inventory, with its issue, so the repository can say "this sentence is
  not true yet" in the open. The alternative, deleting the row or the sentence to
  pass, hides the finding.
- Rejected: scanning the docs for assertive words and requiring a row for each.
  It is noisy, and it would fail on ordinary prose. Finding a claim nobody wrote
  down is a judgment, which is what the CLAUDE.md rule asks of the author.
- The first run found a gap that became a test: the isolation the security model
  rests on had only a manual `make` target. `tests/test_compose_isolation.py` now
  asserts it against the real `compose.yaml` in CI. It also found that
  `preflight.py` has no tests (#77).
- Source: #68; R-19.

### D-28 Preflight reads `.env` exactly as compose does

- Status: Accepted
- `scripts/preflight.py` decides from `.env` alone, so the way for it to be wrong
  is to read `.env` differently from compose, and both mistakes failed open:
  an empty `SITE_ADDRESS=` (compose: the default, plain `http://:80`) was read as
  "not plain HTTP" and passed a bind to the whole network, and
  `POSTGRES_PASSWORD=abc # a long note` was counted at the length of the note while
  compose used `abc`.
- So it follows compose's rules: an empty value is the default (`${VAR:-d}`), an
  unquoted `#` after whitespace starts a comment, a quoted value keeps its `#`,
  and `export` is accepted. Its two defaults are constants, and a test fails if
  they drift from `compose.yaml`.
- Found by writing the tests (#77), not by reading the code: the gate had never
  been tested, and a gate nobody tests is a claim.
- Rejected: shelling out to `docker compose config` to read the resolved values.
  It would be exact, but it needs Docker and the variables set, and preflight must
  run first, before anything is up, on a machine that may have neither.
- Source: #77; R-08.

### D-30 One variable turns on the shared secret at both ends

- Status: Accepted
- `compose.yaml` hands `PROXY_SHARED_SECRET` to both the `api` and the `proxy`
  service, and `proxy/Caddyfile` sends it as `X-Proxy-Secret` with `header_up`.
  Setting it once in `.env` therefore turns the control on at both ends; unset,
  the API does not check and the proxy sends an empty value.
- Why: the API half existed (`_check_shared_secret`) and nothing sent the header,
  so the documented way to enable the control made every request 403 (#61). Two
  settings that must agree are one setting too many.
- `header_up` sets the header, which replaces a value the client sent under the
  same name. Do not add `header_up -X-Proxy-Secret` beside it: Caddy applies
  deletes after sets and the secret would vanish.
- It authenticates the proxy to the API. It is not a way for a caller to
  authenticate to the proxy, which the deployment guide used to suggest.
- The header name is fixed at the API's default, `X-Proxy-Secret`. Compose does
  not pass `PROXY_SECRET_HEADER`, so the two cannot disagree.
- Rejected: documenting it as an operator exercise (set it on the API, add a
  `header_up` to a Caddyfile you edit). That is the configuration nobody tested.
- Source: #61; R-07, D-04.

### D-31 `check-isolation` is a script with an exit code, not shell that prints

- Status: Accepted
- `make check-isolation` runs `scripts/check_isolation.py`. It asserts three things
  and exits non-zero on any failure: no host port on `api` or `db`, a refused
  direct connection to the API, and a forged `X-Auth-Request-*` that does not
  come back as the identity. The third tests for the forged value's absence,
  because the legitimate identity varies by deployment. Not running the stack
  is a failure, not a pass.
- Why: the shell version printed what it found and ended step 3 with `|| true`,
  so it exited 0 whatever it saw (#56). The docs told operators to put it in
  post-deploy automation, where the exit code is the only thing read.
- Why a script: so each decision is a function a test can break
  (`tests/test_check_isolation.py`), and so CI can run it against the real
  stack (`tests/test_stack.py`). A Makefile target is not evidence CI counts
  (R-19).
- Rejected: fixing the shell in place. It would be correct once and untestable
  after.
- Source: #56; R-07, R-19.

### D-32 The root `.dockerignore` is an allowlist

- Status: Accepted
- It excludes everything (`*`) and admits `proxy/Caddyfile` and `docs/app/`,
  the only paths `proxy/Dockerfile` COPYs.
- Why an allowlist: the context is the whole repository, which holds a
  password file, encrypted and plaintext backups, the git history and a
  licensed PDF. A blocklist guards against the secrets somebody thought of; an
  allowlist guards against the next file nobody did.
- Rejected: narrowing the context so the Dockerfile does not need the root
  (build the dashboard into `proxy/` first). It changes the documented build
  command to save a two-line file.
- Rejected: a CI check that a built image contains no `.env`. The image was
  never the problem; the context is, and that is what is tested.
- Source: #63; R-29.

### D-33 The backup passphrase goes through the environment and a mode-600 file

- Status: Accepted
- `scripts/backup_crypto.sh` takes `BACKUP_PASSPHRASE` from the environment,
  writes it with the shell builtin `printf` to a `mktemp` file created under
  `umask 077`, passes gpg `--passphrase-file`, and removes the file in a trap.
- Why: argv is world-readable on Linux, so `gpg --passphrase "$PW"` showed every
  local account the key to every record for as long as the dump ran (#41). Make
  made it worse: `$(VAR)` is pasted into the recipe text, which is the argv of
  `sh -c`, so even a line that never mentions gpg leaked it.
- Rejected: `--passphrase-fd 0` (stdin is already the dump stream in both
  directions); `--passphrase-fd 3` with a here-string (bash only, and the
  Makefile's recipes should not need to be); a gpg-agent or keyring (right for
  interactive use, awkward for a scripted restore).
- The Makefile runs under bash with `pipefail`, and `backup` chains with `&&`.
  Found while testing this: a failed `pg_dump` left an empty "encrypted" file and
  exited 0, and a restore with the wrong passphrase exited 0 having restored
  nothing, because a pipeline's status is its last command's.
- `scripts/doctor.py` gives docker `-e PGPASSWORD` (the name) and passes the value
  in the environment, for the same reason.
- Source: #41; R-13.

### D-34 The identity prefix is stripped once, and the template cannot undo it

- Status: Accepted
- `_normalized()` in `server/app/auth.py` strips `IDENTITY_STRIP_PREFIX` from the
  id, name and email after the plain and JWT parsers, so they cannot diverge.
  Preflight refuses an identity source that reads `X-Goog-Authenticated-User-*`
  unless the prefix is exactly `accounts.google.com:`. The template's bottom
  `IDENTITY_STRIP_PREFIX=` line is commented out, because compose takes the last
  value in a file and the active line re-emptied what the Google block set.
- Why both: the API fix makes the two paths agree, but only if the prefix is
  configured, and compose passes it through empty. The preflight rule stops the
  misconfiguration before any data is written (#35).
- Rejected: defaulting the prefix to Google's in `compose.yaml`. It would strip
  for every other front door too, silently rewriting ids that merely begin with
  that text.
- Rejected, for now: a `make doctor` check that finds stored ids not matching the
  running configuration. The documented count and repair SQL cover deployments
  that already did this; the check is a follow-up.
- Source: #35; R-30.

### D-35 The proxy runs as uid 65532, with a one-shot job to own its volumes

- Status: Accepted
- `user: 65532:65532`, `cap_drop: ALL` plus `NET_BIND_SERVICE`, `read_only`, a
  tmpfs `/tmp`, and a `proxy-perms` service that `chown -R`s `/data` and `/config`
  before the proxy starts.
- Found by running it, not by reading: the stock `caddy` binary has a file
  capability, so under `cap_drop: ALL` the kernel refuses to exec it ("operation
  not permitted") until `NET_BIND_SERVICE` is back in the bounding set, even
  though Docker lets any user bind port 80. Named volumes are root-owned, so a
  non-root Caddy logged `permission denied` on its autosave, instance id and
  locks, and an automatic-HTTPS deployment would have re-issued certificates on
  every restart.
- The upgrade case is the reason the fixer is recursive and has
  `DAC_READ_SEARCH`: volumes an earlier root-run proxy populated hold `0700`
  directories and `0600` keys. Tested with Caddy's local CA: the non-root proxy
  took over such a volume, served HTTPS, logged no permission error and reused
  the certificate.
- Rejected: leaving the proxy root with fewer capabilities. It works, and is
  the smaller change, but a container escape from the one internet-facing
  process would start as root, which is the finding.
- Rejected: `tmpfs` for `/data`. It runs, and loses the certificates.
- Rejected: baking a `chown` into a compose-built image. Compose bind-mounts the
  Caddyfile and dashboard so an edit needs no rebuild (D-15), and only the cloud
  image is built; there the `chown` is in `proxy/Dockerfile`.
- Limits are defaults, overridable through `.env`, sized for kilobytes of
  documents.
- Source: #50; R-32.

### D-36 Paging by header cursor, over the existing index, with a fixed cap

- Status: Accepted
- The response stays a bare JSON array, so the browser's `ApiStore` and any
  existing caller keep working. The total and the next cursor travel in headers
  (`X-Log-Total`, `X-Log-Next`).
- The cursor is `(at, seq)` as `<microseconds>.<seq>`. `project_log_project_at_idx
  (project_id, at DESC, seq DESC)` already serves `(at, seq) < ($2, $3)` exactly,
  and `seq` breaks ties so nothing repeats or vanishes.
- It is not an ISO timestamp. That first version carried `+` and `:`, a query
  string turns `+` into a space, and a client that forgot to encode it failed in
  a way that looked like corruption. Found by the test.
- `limit` is capped at 500 so no request makes the server build an unbounded
  list. The dashboard's *Show older entries* deepens one request (`?limit=120`,
  `180`, ...) rather than holding a cursor, because every change event refetches
  the newest page and would otherwise discard older pages already loaded.
- Rejected: changing the body to `{entries, total, next}`. Cleaner, and breaks
  every caller for no gain over headers.
- Rejected: `OFFSET`. It re-reads and discards all earlier rows on every page, and
  entries written between pages shift it.
- Source: #40; R-34.

### D-37 Two roles, with the owner's credential in a one-shot job

- Status: Accepted
- `python -m app.migrate` (compose's `migrate` service) holds the owner's
  credential, applies migrations and creates the restricted role; the API gets only
  the restricted role's. `APP_POSTGRES_PASSWORD` is required by `make up` and must
  differ from the owner's.
- Why a separate job and not "migrate at boot, then switch roles": a process that
  starts with the owner's credential still has it in its environment and memory.
  The compromise being defended against is exactly an attacker in the API
  process.
- Why not derive the restricted password from the owner's (an HMAC), which would
  need no new setting: the API would have to be given the owner's password to
  compute it, which is the thing being removed.
- Why `GRANTS` is explicit and nothing is inherited: a new table must name what
  the API may do to it. A test fails if one does not. `project_log` gets UPDATE
  (the purge redacts in place; its trigger permits only that) and no DELETE,
  because a project's log is removed by `ON DELETE CASCADE`, which runs with the
  table owner's rights.
- Found by running the whole suite as the restricted role: four tests exercised
  the triggers by issuing statements the restricted role is now refused earlier,
  by a privilege check. They connect as the owner, since the triggers bind the
  owner too; `test_roles.py` covers the role being refused.
- Rejected: row-level security or moving the merge into the database (the
  issue's own non-goals).
- Rejected: leaving it to the operator to grant by hand. That is the configuration
  nobody tests.
- Source: #48; R-35.

### D-38 A principals table, resolved only for people you can already see

- Status: Accepted
- The proxy asserts name and email on every request and the API discarded them.
  `principals` keeps them keyed by id, upserted as people sign in, throttled in
  memory (new, changed, or at most hourly) so a read is not a write. This is the
  issue's option 1.
- The lookup is not open. A signed-in user could otherwise walk a directory of
  every member of staff who ever signed in, so it answers for the caller and for
  people on a project the caller can read, and omits the rest. Omitted, not 403:
  an absent id carries no information about whether the person exists.
- The server-backed mode shows the id when it cannot name someone (the issue's
  option 4, as the fallback): it is what a reviewer can match against a
  directory, where "someone" tells them nothing. The artifact and browser-only
  modes keep "someone".
- Rejected: resolving against the IdP (Graph, Google Directory). More correct and
  a new outbound dependency and credential for a hospital to approve.
- Rejected: a display name typed when granting access. It drifts, and does not help
  ids that predate it.
- Cost, stated: a staff directory exists as a side effect. It is documented as
  personal data in `docs/deploy.md`, and erasing one person from it is not yet a
  supported operation (#57).
- Source: #39; R-36.

### D-39 Break-glass is an identity flag, with an unmissable record of each use

- Status: Accepted
- `Identity.emergency` is set from configuration and the proxy's asserted id
  alone. `access.require()` returns True when a request was allowed only because
  of it, and the route then records the use. The access lists are unchanged: the
  break-glass identity does not appear in them and cannot be removed from a
  project by one.
- Why record in the project's own log, as a system entry: the people who need to
  know are the project's owners, and the log is where they look; a system entry
  (`is_system`) is never redacted by a purge, so the evidence survives the very
  operation an emergency user might run. A separately-named event
  (`access.breakglass`) and a dedicated logger make it alertable.
- Why reads are throttled and writes are not: a dashboard refetches the log and
  versions on every change event, so an unthrottled read entry would write hundreds
  of rows per hour for one open tab. One per person per project per ten minutes
  still says it happened and who. Every use, throttled or not, is an
  `access.breakglass` security event. Revisit if a stricter reading of "every
  use" is wanted.
- Known limit: a delete's log entry goes with the project (by design, D-10/R-11).
  The warning and the tombstone remain. SSE streams are not widened: a break-glass
  identity is not in a project's audience, so it fetches rather than being pushed.
- Rejected: a role hierarchy or organization admin (the issue's own non-goal).
- Rejected: an `UPDATE` run by hand against the database. That is the privileged
  path the role model exists to avoid, and it leaves no record in the application.
- Source: #42; R-37.

### D-40 Bound the stream's life; do not build a session layer

- Status: Accepted
- The API stays free of sessions (D-03): identity comes from the proxy. The one
  place a revoked identity kept working was the event stream, which
  authenticates at attach. The API cannot re-ask the identity provider, so the
  fix is to **end the stream** on a timer and let the browser's reconnect do the
  re-authentication, which is exactly what the front door is for. This is the
  issue's option 2, adapted: it said to re-check the identity on the keepalive
  tick, and there is nothing in the API to check it against.
- The idle lock is a screen lock, off by default. It reloads rather than
  re-authenticating in place, because only the front door can authenticate. It
  flushes pending edits first.
- `SIGN_OUT_URL` is an allowlist (https, or a single-slash path), applied by the
  server at startup and again in the browser, because the server's answer is
  data and the value becomes a link. `javascript:`, `data:`, plain `http:` and
  `//host` are refused.
- Found while writing it: `ApiStore` set `es.onerror = () => {}`, so a stream
  that was closed for good (what a refused reconnect looks like) was swallowed
  and the page went on looking live. It now reports `stream_closed`.
- Rejected: building sign-in or a session in the API (the issue's own non-goal).
- Rejected, for now: closing the stream when the identity's *access* to a
  project changes. Events are already filtered by the audience at publish time.
- Source: #49; R-38.

### D-41 One security-event stream, JSON, tagged, and not the application log

- Status: Accepted
- `emit(SecurityEvent.X, message, **fields)` writes through a dedicated
  `chai.security` logger. The JSON formatter tags every line with its `stream`
  (`security` or `app`) so a sink can route and retain them separately (the
  issue's option 4) and an alert is a field match (option 1). The human-readable
  message is kept, so `LOG_FORMAT=text` and existing tests still read naturally.
- The security logger is held at INFO regardless of `LOG_LEVEL`, because an
  event that disappears when someone turns the application log down is not an
  audit.
- Values are `json.dumps`ed, so an identity with a quote or newline stays in its
  own string. Tokens and secrets are never fields: a token that cannot be
  decoded logs only the exception's class.
- The rate-limit event is once per client per window, or a flood of refused
  requests would become a flood of log lines, which is the denial of service
  again.
- It replaced the per-module loggers `chai.access` and `chai.emergency`, which
  could not be filtered together and whose names were in the docs as the thing
  to alert on. Those references now point at the events.
- Found while testing: `configure_logging` took a string and compared it to the
  enum by identity, so passing `"json"` silently selected the text format. It
  now coerces at its boundary (`LogFormat(fmt)`), which also rejects an unknown
  value.
- Rejected: a log shipper in the stack. A hospital has its own collector, and
  one more container that holds the security stream is one more thing to harden.
- Rejected: an audit table for these (option 3 of #33 is the read trail, which
  is a different thing). A database admin can alter a table; a sink outside the
  database is the tamper-evident copy. Both are in #33.
- Source: #38; R-39.

### D-29 Redaction is defined once, in SQL, and the trigger verifies the result

- Status: Accepted
- `project_log_redacted(entry)` is the single definition of what a redacted
  entry is: a **whitelist** of `at`, `by`, `hash`, the changed field's `path`,
  and a fixed marker for the text. The trigger on `project_log` permits an
  UPDATE only if the new entry **equals that function applied to the old one**,
  so it checks what was done, not what the caller says it did. A partial
  redaction, one that keeps `change.to`, a change to when or who, and un-purging
  are all refused.
- Why a whitelist: the log stores arbitrary fields the client sends, and the
  client writes the values into the prose (`text`) as well as `change.from/to`.
  The issue named only `from` and `to`; a blacklist of known fields would have
  left the identifier readable in the prose.
- "Already purged" and "written by the system" are **columns**, set only by the
  server. Were they keys inside the entry, a client could send `{"purged":
  true}` and make an entry carrying the value survive every purge.
- Deletion writes `project_deletion` (append-only, no content, no foreign key,
  so it outlives the row) inside the delete transaction. A refused or failed
  delete writes nothing.
- **Deleting is still not erasure,** by design (D-10): the history is kept so
  the record can be audited. The dialog says so, and offers the destroy step as
  a separate choice, run first so a failure does not delete the project.
- Rejected: redacting only `change.from/to` (leaves the prose); blacklisting
  known sensitive fields; making the purge delete the rows (a vanished row looks
  like a snapshot never taken, D-11); letting deletion cascade-delete the
  history (an audit trail that vanishes with its subject is not one).
- Not done: removing the identifiers of the people who made changes
  (`created_by`, `changed_by`, `by_id`), and reaching backups. Both are
  documented, and the first is #57.
- Source: #36; R-12, R-27.

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
