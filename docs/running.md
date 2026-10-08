# Running it

The dashboard runs in three places, and **they are not equivalent**. Pick by
what you need, not by what is easiest to open.

## Which mode does what

| | GitHub Pages / open a file | Claude artifact | Docker stack |
|---|---|---|---|
| Storage | Browser `localStorage` | Artifact database | PostgreSQL |
| Shared between people | **No** | Yes | Yes |
| Survives clearing site data | **No** | Yes | Yes |
| Signed-in identity | **None** | Yes | Yes, from your SSO |
| Access control enforced | **No** | Partly | **Yes, server-side** |
| Checkpoint sign-off means something | **No, self-asserted** | Yes | Yes |
| Patient-identifiable information | **Never** | **Never** | **Never** |
| Version snapshots | No | No | **Yes** |
| Live updates between people | No | Yes | Yes |
| Both checklists, model card, metrics | Yes | Yes | Yes |
| All exports, including PDF | Yes | Yes | Yes |
| Changelog | Yes, this browser | Yes | Yes |
| Record fingerprint | Yes | Yes | Yes |

!!! danger "The published site is a demonstration, not a system of record"

    <https://tonyreina.github.io/ai_governance_healthcare/app/> stores
    everything in **your browser**. Nobody else can see it, it does not survive
    clearing site data, and there is no signed-in user — so a checkpoint
    sign-off there records a name nobody checked.

    It is the right way to evaluate the tool. It is the wrong way to keep a
    governance record. For that, run the stack below.

## Everything working, locally

`docker compose up` gives you the full system: PostgreSQL, the API with access
control enforced, a proxy supplying identity, and the dashboard served from the
same origin so it finds the API automatically.

```bash
git clone https://github.com/tonyreina/ai_governance_healthcare
cd ai_governance_healthcare

cp .env.example .env
# Set POSTGRES_PASSWORD. Compose refuses to start without it, on purpose.

pixi run build-app          # build the dashboard from app/
docker compose up -d --build

open http://localhost:8080
```

The dashboard should show **Shared workspace** rather than *This browser only*.
If it says the latter, the API is not answering — check `docker compose logs api`.

!!! warning "Changing POSTGRES_PASSWORD later does not change the password"

    PostgreSQL reads `POSTGRES_PASSWORD` **only when it initializes an empty
    data directory**. On an existing `pgdata` volume the variable is ignored,
    so editing `.env` changes what the API *presents* without changing what the
    database *accepts*. Nothing warns, and the symptom points nowhere useful:
    the API retries ten times and exits, `docker compose ps` shows a crash
    loop, and the dashboard says it cannot reach the server.

    `make doctor` names it, and prints the command to fix it. See
    [Rotating the database password](self-hosting.md#rotating-the-database-password)
    — the fix keeps every record, and the destructive option is a last resort,
    not the first one.

### What to try

Things that only work in this mode:

- **Access control.** Open a project, go to *Project setup → Access*. You are
  the owner because you created it. Grant someone else write or read access and
  watch the Manage buttons change for them.
- **Version history.** Make a few edits, then:

    ```bash
    curl -s localhost:8080/api/projects/<id>/versions | python -m json.tool
    ```

    Every revision, with its fingerprint, who made it and when.
- **Live updates.** Open the dashboard in two windows and change something in
  one. The other updates without a refresh.
- **Identity cannot be forged.** The proxy strips any identity header the
  client sends and sets its own:

    ```bash
    curl -H "X-Auth-Request-Email: ceo@hospital.example" localhost:8080/api/me
    # still answers with the proxy's identity, not yours
    ```

### Development mode

Hot reload, and the API published on localhost for inspection. The database is
not published (it is on an internal network by design); reach it with `make psql`:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d
```

Named explicitly rather than `compose.override.yaml`, so a plain
`docker compose up` can never pick it up by accident.

!!! warning "The local proxy mints one fixed identity"

    Locally the proxy sets a single development identity for every request, so
    everything you do is the same person. That is enough to exercise ownership
    and the audit trail, but to see two users with different roles you need a
    real identity provider in front — see
    [Deploying with SSO](deploy.md).

## Stopping and cleaning up

```bash
docker compose down            # stop; the database volume survives
docker compose down -v         # stop and DELETE the database
```

## Running the tests

If something is up but not working, start here:

```bash
make doctor             # asks the running stack what is wrong
```

```bash
pixi run check          # every lint and build hook
pixi run test-app       # the dashboard, in a real browser
pixi run test-access    # roles and the delete confirmation
pixi run test-te        # the CHAI metric picker
pixi run test-pdf       # renders a real PDF and reads it back
pixi run test-proxy     # the proxy against a real Caddy (needs Docker)
pixi run test-stack     # end to end against a running stack
pixi run test-enums     # the enum guardrail
pixi run test-workflows # does CI run every test that exists?
```

The server's own suite needs a PostgreSQL to test against, because what it
tests *is* the database's behavior — a row lock serializing two writers, a
trigger refusing to rewrite history:

```bash
docker run -d --name chai-test-db -p 55432:5432 \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=chai_test postgres:17-alpine
cd server
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/chai_test pytest
```

The stack's own database is not reachable from the host, so the tests run against
a throwaway one.

This one is a URL you write yourself, so percent-encode the password if it
contains `/`, `@`, `:`, `?` or `#`. The stack itself does that for you.

Without `TEST_DATABASE_URL` those tests skip and say why. A skip exits 0, so on
your own machine it looks like a pass. Set `REQUIRE_TESTS=1` to turn every skip
into a failure; CI always does.

### In CI

Every pull request and every push to `main` runs all of the above in GitHub
Actions (`.github/workflows/test.yml`): the server suite against a PostgreSQL 17
service container, the dashboard suites in Chromium, the proxy against a real
Caddy, and the whole Compose stack end to end. One job, **tests passed**, fails
if any of them failed, was canceled, or was skipped.

`main` requires that job: a pull request cannot be merged while it is pending or
red, and there is no administrator bypass.

`pixi run test-workflows` checks the CI configuration itself: it fails if a
`test-*` task is not run by CI, or a test file has no task, so a test cannot be
added and quietly left out.
