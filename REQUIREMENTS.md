# Requirements

Things that must stay true of this project. New code adheres to these unless
the user says otherwise, and the user's instruction is then recorded here.

How this file is used is set out in [CLAUDE.md](CLAUDE.md). The reasoning
behind how each requirement is met lives in [DECISIONS.md](DECISIONS.md).

Each entry has a stable ID. Never renumber or reuse an ID: other files and
issues cite them. A requirement that no longer applies is marked **Retired**
with the reason and the date, not deleted.

**Status** is one of:

- **Active**: in force. New code must satisfy it.
- **Open**: a question the project has not answered. Do not assume an answer.
- **Retired**: superseded or dropped. Kept so the history makes sense.

**Enforced by** says what fails if the requirement is broken. "Nothing" is an
honest answer and is a gap worth closing; see R-19.

## Product

### R-01 The dashboard is one self-contained file

- Status: Active
- The built dashboard (`docs/app/index.html`) is a single HTML document. It must
  run as a Claude artifact, open straight off disk with no server, and publish
  to GitHub Pages. Native ES modules and anything that needs a second file are
  out, because `file://` blocks module loading.
- Source is split under `app/` and concatenated by `scripts/build_app.py`.
  The built file is generated and is never edited by hand.
- Source: `scripts/build_app.py` module docstring.
- Enforced by: `pixi run check-app`, and the `build-app` pre-commit hook, which
  fails if the built file differs from its sources.

### R-02 Storage goes through one interface

- Status: Active
- All persistence uses the six-method store interface (`subscribeAll`,
  `create`, `update`, `remove`, `log`, `subscribeLog`). `ApiStore` (Docker
  stack), `DbStore` (Claude artifact) and `LocalStore` (browser) implement it.
  A new backend adds a class; it does not add a branch in the app.
- Source: README, "Evaluate it without deploying anything".
- Enforced by: Nothing.

### R-03 Never silently fall back

- Status: Active
- If a server was expected and cannot be reached, the app stops and says so. It
  must not degrade to browser-only storage, because that hands a user a working
  private workspace that looks like the shared one.
- Source: README; `app/js/20-app/80-boot.js` ("access control failing open
  into a usable app").
- Enforced by: `tests/test_boot_storage.py`.

### R-04 The mode the user is in is never ambiguous

- Status: Active
- Storage mode is the most consequential fact about a deployment and the least
  visible. Each mode must label itself truthfully, and the label for one mode
  must not be reused for another.
- History: #55 (the server mode reported "Saved in this browser") and #64 (the
  Claude artifact mode was labeled "Shared workspace", as the server mode is)
  are both fixed. Each mode now has its own header label, saved label and, for
  the artifact and browser-only modes, a standing notice in the layout.
- Source: `app/js/20-app/40-readonly.js`, `showStorageWarning` comment.
- Enforced by: `tests/test_boot_storage.py`: the saved label and the header
  label for every mode (each present, no two alike), and the artifact notice.

### R-05 The dashboard and its exports contact no third party

- Status: Active
- No webfont, CDN, analytics or other third-party request, on page load or when
  an exported report is opened. This is also what lets the Content-Security-
  Policy be as tight as it is.
- Source: `tests/test_no_third_party.py` docstring; closed issue #17.
- Enforced by: `pixi run test-no-3p`.

## Identity and access

### R-06 Identity comes from the proxy and nowhere else

- Status: Active
- The API reads exactly the identity headers the proxy sets. Never from a body,
  a query parameter, a cookie or a token. The API has no user table, no password
  hash, no login form and no token endpoint.
- Source: `server/app/auth.py` module docstring; DECISIONS D-03.
- Enforced by: `server/tests/test_auth.py`; `tests/test_proxy_identity.py`.

### R-07 The API is reachable only through the proxy

- Status: Active
- The API publishes no host port. This is the security boundary: the whole
  identity model is "trust a header", which is only safe if nothing else can
  reach the API. Adding a service to the `edge` network widens the boundary.
- Source: `compose.yaml` header; `server/app/auth.py`.
- Enforced by: `tests/test_compose_isolation.py` (the compose file), and
  `scripts/check_isolation.py`, which `make check-isolation` runs against a live
  stack: `tests/test_check_isolation.py` breaks each of its three steps and
  demands it notice, and `tests/test_stack.py` runs it against the real stack.
  (Step 3 used to assert nothing, #56.)

### R-08 Fail closed on identity

- Status: Active
- An unset or empty identity source rejects every request (401). It never falls
  back to a usable default. The stack refuses to start on a literal identity
  source, a placeholder or short database password, or a non-loopback bind over
  plain HTTP.
- Source: `proxy/Caddyfile` ("NO DEFAULT VALUE"); `scripts/preflight.py`.
- Enforced by: `tests/test_proxy_identity.py`; `tests/test_preflight.py` for
  the preflight gate. It reads `.env` the way compose does (an empty value is
  the default, an unquoted `#` after whitespace starts a comment), because
  reading it differently fails open.

### R-09 Sign-offs are attributed to the authenticated user

- Status: Active
- A checkpoint sign-off records the identity the proxy asserted and the server
  clock, not a name or date the client supplied. The server writes `signedBy`
  and `signedAt` whenever a decision is set or changed, clears them when it is
  cleared, ignores them on an unchanged decision, and refuses to let them be
  blanked while a decision stands. With identity disabled nothing is attributed.
- History: this was violated (#31). A writer could record a decision as the CMO,
  on any date, while the deployment guide claimed the opposite.
- Source: `docs/deploy.md`, "A checkpoint sign-off means something."; DECISIONS
  D-24.
- Enforced by: `server/tests/test_signoff.py` (the rules, and the exploit against
  the real API); `tests/test_stack.py` (the same exploit through a real Caddy).

### R-30 One person has one identity id, whichever way they arrive

- Status: Active
- The id is the key every access list is matched against, so the plain-header
  and JWT paths, and any front door, must give the same person the same id. The
  front door's scheme prefix (Google IAP's `accounts.google.com:`) is stripped in
  one place, after both parsers, and `make up` refuses a Google identity source
  whose `IDENTITY_STRIP_PREFIX` is not Google's, because ids stored with the
  prefix stop matching later and every project vanishes from its owner.
- History: the strip applied to plain headers only, compose passed the prefix
  through empty, and `.env.example` re-emptied it with a later line (#35).
- Source: #35; DECISIONS D-34.
- Enforced by: `server/tests/test_auth.py` (both paths agree),
  `tests/test_preflight.py` (the refusal, and the template's own Google block
  passing), and `server/tests/test_identity_repair.py` (the documented repair,
  run against PostgreSQL).

### R-31 A published export names no individual unless asked

- Status: Active
- The Croissant exporter's default `maintainer` is an organizational contact, not
  the review team or clinical sponsor, and is omitted when no organization is
  recorded. `--include-maintainer-names` publishes the names and prints a
  warning that lists them, as `--include-cohort-detail` does for cohorts.
- Why: a published record that names the people responsible for a clinical
  system links identified individuals to it, its site and a time. That is
  personal data under GDPR Art. 4(1).
- History: names were emitted unconditionally while cohort detail was gated
  (#60).
- Source: #60.
- Enforced by: `tests/test_croissant_export.py`, which also checks the output
  still validates against `mlcroissant`.

### R-32 The containers run with the least privilege they work with

- Status: Active
- The proxy (the only service reachable from outside) runs as a non-root user,
  drops every capability but `NET_BIND_SERVICE`, and has a read-only root
  filesystem. The API drops every capability and is read-only. Every service
  sets `no-new-privileges` and a memory, CPU and process limit. The ownership
  fixer `proxy-perms` has no network and only `CHOWN` and `DAC_READ_SEARCH`. The
  cloud image `proxy/Dockerfile` is unprivileged to match.
- `db` cannot drop all capabilities: the Postgres entrypoint starts as root and
  drops to the postgres user.
- A change that adds a service, a capability, a network or a root user to this
  set needs a decision, not a drive-by edit.
- History: the proxy ran as root with default capabilities, and no service had
  a limit (#50).
- Source: #50; DECISIONS D-35.
- Enforced by: `tests/test_compose_isolation.py` (the rule, with a mutation test
  for each part, and the cloud Dockerfile) and `tests/test_stack.py`, which
  `docker inspect`s the running containers.

### R-33 A denial is logged, and the log never carries the document

- Status: Active
- Every authorization refusal on an existing project (the 404 that hides it
  from a non-reader, and the 403s for a missing write or owner right) logs one
  `access.denied` warning on `chai.access`: actor, project id, what was needed,
  what the user held, and the status returned. It never logs document contents.
  A project that does not exist is not a denial.
- Why: a compromised staff account probing other people's records left no trace
  (#53). Denied access is the highest-signal, lowest-volume security event.
- Source: #53; 45 CFR 164.308(a)(1)(ii)(D).
- Enforced by: `server/tests/test_denial_log.py`, against a real PostgreSQL.

### R-28 A project's creator is always one of its owners

- Status: Active
- Creating a project lists the caller first among its owners, whatever the body
  says, and keeps any other owner the body names (so "create and share" works).
  The client's `owners` list can neither attribute a record to someone who did
  not make it nor leave it with no reachable owner.
- Applies when identity is enforced (`REQUIRE_IDENTITY`); with it off nothing
  is attributed.
- History: the client's `owners` was kept verbatim (#44).
- Source: #44.
- Enforced by: `server/tests/test_access.py`
  (`test_creator_stays_an_owner_when_naming_someone_else` and the tests beside
  it), against a real PostgreSQL.

### R-29 A Docker build context holds only what its Dockerfile copies

- Status: Active
- `proxy/Dockerfile` builds with the repository root as its context, so the root
  `.dockerignore` is an allowlist (`*`, then the two paths the Dockerfile COPYs).
  `.env`, `backups/`, `.git/` and the licensed source PDF must never be sent to
  the daemon, whatever a Dockerfile happens to copy. `server/.dockerignore` keeps
  `.env*` and the tests out of the API image's context.
- A new `COPY` of another path needs that path allowed in the same change.
- History: no root `.dockerignore` existed, so every build uploaded the whole
  tree (#63). The image never held the secrets; the exposure was the context
  itself, on a remote or shared builder, one `COPY . .` from a published secret.
- Source: #63; DECISIONS D-32.
- Enforced by: `tests/test_dockerignore.py`, against the real contexts and a
  real build, with decoys; it also shows the decoys leak without the file.

## Audit and data

### R-10 The audit log and version history are append-only

- Status: Active
- `project_log` refuses UPDATE. `project_version` refuses DELETE and refuses any
  UPDATE except a purge. `at` and `by` on a log entry are overwritten
  server-side.
- Source: `server/migrations/001_init.sql`, `003_version_access.sql`.
- Enforced by: database triggers; `server/tests/test_versions.py`. The triggers
  do not bind the application's own role (#48).

### R-11 History outlives the record it describes

- Status: Active
- Deleting a project does not delete its version history, and history keeps the
  access rules the record had when it was written, so deletion never widens
  access.
- Source: `002_versions.sql`, `003_version_access.sql`, `004_version_incarnation.sql`.
- Enforced by: `server/tests/test_versions.py`.
- Note: this is in tension with erasure, which is why deleting a project is NOT
  erasure and a separate, explicit purge exists (R-12, D-29).

### R-12 Disposal leaves a tombstone, not a gap

- Status: Active
- Purging a version empties its content and keeps its revision, author,
  timestamp and original `content_md5`, so "this existed and was purged by whom
  and when" stays answerable.
- A purge also redacts the project's audit log in the same transaction, by
  whitelist, because the client writes the values into the entry's prose and may
  add any field it likes (#36). The database permits that one transition and
  refuses any other UPDATE.
- Source: `003_version_access.sql`.
- Enforced by: `server/tests/test_versions.py`.

### R-27 Deletion is auditable, and erasure is a separate explicit step

- Status: Active
- Deleting a project writes a permanent, append-only tombstone (who, when, what
  it last hashed to) and keeps the version history. Destroying the content of the
  history and the audit log is a separate, owner-only, irreversible step, offered
  in the delete dialog only where there is a history to destroy, and ordered so
  that a failure never leaves the user believing data is gone.
- The documentation says that deleting is not erasure, and what no step reaches:
  earlier backups, and the identifiers of the people who made changes.
- Source: #36; DECISIONS D-29.
- Enforced by: `server/tests/test_disposal.py`, `tests/test_disposal_ui.py`, and
  `tests/test_stack.py` through a real proxy.

### R-13 Backups are encrypted

- Status: Active
- `make backup` refuses to run without a passphrase and writes only encrypted
  dumps. A plaintext dump requires an explicit `PLAINTEXT=1` and is for
  throwaway databases.
- The passphrase is never in a process's argv: it comes from the environment and
  reaches gpg through a mode-600 file (`scripts/backup_crypto.sh`), and the
  Makefile never expands it as `$(BACKUP_PASSPHRASE)` (make pastes that into the
  `sh -c` text). A failed dump or decrypt fails the command and keeps no file.
- History: the passphrase was on gpg's command line (#41), and a failed
  `pg_dump` or a wrong passphrase on restore exited 0.
- Still open: `make backup BACKUP_PASSPHRASE=...` puts it in make's own argv, so
  the docs say to export it. Where the passphrase is kept long term is the
  operator's key-management question.
- Source: `Makefile`, `backup` target comment; #41; DECISIONS D-33.
- Enforced by: `tests/test_backup_crypto.py` (the guards, the recipe text, the
  process table while gpg runs, the exit status of a restore and of a failed
  backup).

## Security posture

### R-14 Cross-site writes are refused

- Status: Active
- State-changing requests carrying `Sec-Fetch-Site` outside the trusted set are
  rejected. CORS is off unless explicitly configured, and never `*`.
- Source: `server/app/main.py` docstring.
- Enforced by: `server/tests/test_csrf.py`.

### R-15 Request size and rate are bounded

- Status: Active
- The edge refuses an `/api` body over 2,000,000 bytes (Caddy `max_size 2MB`
  is SI, not 2 MiB). The API refuses over 1,048,576 bytes
  (`REQUEST_BODY_LIMIT_BYTES`) and rate-limits per replica at 240 requests per
  60 seconds.
- Source: `proxy/Caddyfile`; `server/app/config.py`.
- Enforced by: `tests/test_proxy_identity.py`;
  `server/tests/test_api_hardening.py`.

### R-16 Security headers on every response

- Status: Active
- The Content-Security-Policy, HSTS, `nosniff`, Referrer-Policy and frame
  denial apply to `/api/*` responses and the dashboard alike, and `Server` is
  removed.
- Source: `proxy/Caddyfile`; closed issues #14, #27.
- Enforced by: `tests/test_proxy_identity.py`.

### R-25 The documented first-run path works with any password

- Status: Active
- A password generated the way `preflight.py` and `.env.example` tell the
  operator to generate it (`openssl rand -base64 32`), or chosen by a password
  manager, must work. Nothing may build a URL by interpolating the password.
- History: this was violated. Compose pasted `${POSTGRES_PASSWORD}` into the
  connection URL, and a `/` in the password made the API crash on startup, reading
  the start of the password as a port number. About half of all generated
  passwords did this. Found by an operator running `make dev`, not by a test.
- Source: the user's bug report; DECISIONS D-25.
- Enforced by: `server/tests/test_database_url.py`, including a real PostgreSQL
  role whose password contains every awkward character, and a guard that fails if
  compose ever interpolates the password into a URL again.

### R-26 Showcase media is first-party, bounded and honest about the mode

- Status: Active
- The walkthrough video lives on the docs site (`docs/assets/`), not on a
  third-party host, so the project's no-third-party rule (R-05) holds for its own
  front page. Each file is capped at 10 MB, starts playing before it finishes
  downloading, has controls and a poster, and never autoplays.
- The page must say the video was recorded on the Docker stack and that the
  demonstration copy at `/app/` is browser-only, because a viewer will otherwise
  assume the demo behaves like the video (R-04).
- **Known gap:** the narration has no captions or transcript (#75).
- Source: the user's instruction to publish the walkthrough; DECISIONS D-26.
- Enforced by: `tests/test_docs_media.py`, and a pre-commit hook that applies the
  10 MB cap to `docs/assets/` media while the repo-wide limit stays at 512 KB.

## Engineering rules

### R-17 American English only

- Status: Active
- American spelling in prose, code, comments, docstrings, commit messages and
  UI copy. Quoted material and third-party field names keep their original
  spelling.
- Enforced by: `pixi run check-spelling` (pre-commit).

### R-18 A closed set of values has an enumerated type

- Status: Active
- Code never branches on a bare string for a closed set. Python uses
  `StrEnum`; JavaScript uses a frozen constant object. Existing uses are
  baselined and only shrink.
- Source: [CLAUDE.md](CLAUDE.md); DECISIONS D-19.
- Enforced by: `pixi run check-enums`; the Claude Code hook in
  `.claude/settings.json` (Write, Edit, MultiEdit and Bash); `pixi run
  test-enums`.
- Not enforced: a hoisted constant, a dispatch dict, a literal on the left of
  `in`, a lowercase JavaScript state variable. See CLAUDE.md. These rest on
  review.

### R-19 A security claim names the test that enforces it

- Status: Active
- A claim in documentation or the UI ("sign-off means something", "check-
  isolation asserts all of this") is true or it is removed. Each one is listed in
  `docs/security-claims.md` with the sentence quoted and a test CI runs, or is
  listed honestly as `partial`, `unenforced` or `violated` with a reason and an
  issue.
- History: this was the root cause of #31, #55, #56, #61 and #62.
- Source: the claim-versus-reality findings of the hospital security review; #68;
  DECISIONS D-27.
- Enforced by: `pixi run check-claims` (every commit, and CI through the
  pre-commit hooks) and `tests/test_check_claims.py`. What it cannot do is
  find a claim nobody wrote down: a new assertive sentence still needs a human
  to add its row, which is what CLAUDE.md requires.

### R-23 Code ships with unit and integration tests

- Status: Active
- Whenever code is added or changed, unit and integration tests are added or
  updated in the same change. A bug fix starts with a regression test shown to
  fail. A guardrail is shown to fail (mutation tests). Integration tests use the
  real thing at a boundary (PostgreSQL, a browser, Caddy, Compose), never a fake
  for what is under test.
- Source: the user's instruction; [CLAUDE.md](CLAUDE.md); #32.
- Enforced by: review and CLAUDE.md for "tests accompany the change". CI
  enforces the weaker half: every test that exists runs on every pull request
  (`tests/test_workflows.py`).

### R-24 In CI, a test that cannot run fails

- Status: Active
- `REQUIRE_TESTS=1` turns a skip into a failure for every suite: no database, no
  Docker, no `node`, no stack, no Playwright. A skip exits 0 and reads as a pass.
- Source: #32.
- Enforced by: `.github/workflows/test.yml` sets it at workflow level, and
  `tests/test_workflows.py` fails if that is removed.

### R-20 Decisions and requirements are tracked

- Status: Active
- This file and `DECISIONS.md` are kept current as part of the change that
  alters them. See CLAUDE.md.
- Enforced by: review, and the instruction in CLAUDE.md.

## Open questions

### R-21 What data classification does the server-backed mode carry?

- Status: **Open** (#34)
- "Do not put patient-identifiable information in it" is stated only for the
  browser-only mode. The server mode, which a hospital deploys, states nothing,
  and its own migration comments anticipate a patient identifier pasted into an
  evidence field. Until the owner decides, do not write documentation or UI
  copy that implies the server mode is, or is not, approved for PHI.
- GDPR applies regardless: the data subjects include hospital staff.

### R-22 Is PHI detection in scope, and where does it run?

- Status: **Open** (#65, #66)
- Proposed, not decided: an opt-in sidecar behind `POST /api/phi-check`, plus an
  offline `make phi-scan`. The model cannot live in the browser (R-01).
  Whatever is built must not say "no PHI detected"; it states what was scanned
  and that a clean result is not a guarantee.
