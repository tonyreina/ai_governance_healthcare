# Self-hosting

## How the app is built

`docs/app/index.html` is **generated**. Do not edit it.

The dashboard has to ship as one self-contained file: it runs as a Claude
artifact, it is opened straight off disk with no server, and it is published to
GitHub Pages. But a single 1,400-line file holding the CSS, two governance
frameworks and all the rendering is not maintainable. So the source is split
under `app/` and concatenated by `scripts/build_app.py`:

```text
app/
  index.html                   shell, with CSS and JS insertion markers
  css/app.css
  js/
    00-core/                   framework-agnostic: util, model, stores,
                               state, writes, DOM helpers
    10-frameworks/
      00-registry.js           the framework contract
      05-project/              project setup (not owned by any framework)
      10-chai/                 definition, rules, views, registration
      20-optica/               the same four files, independently
    20-app/                    shell, dashboard, exports, events, boot
```

```bash
pixi run build-app     # app/ -> docs/app/index.html
pixi run check-app     # syntax + duplicate-declaration checks
pixi run test-app      # end-to-end browser tests
```

A prek hook rebuilds on any change under `app/`, so the generated file can never
go stale.

## Adding a framework

A framework is a directory under `app/js/10-frameworks/` whose last file calls
`registerFramework()` with:

| Field | Purpose |
|---|---|
| `id`, `label` | identity, used in data keys and the UI |
| `enabled(p)` | is it switched on for this project? |
| `views(p)` | rail entries, in order |
| `render(view, p)` | markup for one view |
| `blank()` | extra keys for a new project |
| `normalize(p)` | repair shape on load; must be idempotent |

Nothing else in the app names a framework. The rail, the router and the pager
read only the registry.

!!! warning "One framework owns the status"

    CHAI is always enabled and owns the compliance status, the readiness scores
    and the dashboard. That is deliberate: the dashboard needs **one** status,
    and averaging two frameworks' judgements would produce a number that means
    nothing.

    Optional frameworks never propagate status in either direction. An OPTICA
    answer cannot move a CHAI score, and vice versa. The frameworks ask
    different parties for different evidence at different moments, and no OPTICA
    item fully discharges a CHAI criterion — see the [crosswalk](crosswalk.md).
    Evidence can be cited in both; a judgment in one is never a judgment in
    the other.

## Storage

All persistence goes through two small classes in `app/js/00-core/20-stores.js`,
`DbStore` and `LocalStore`, which implement one interface:

| Method | Purpose |
|---|---|
| `subscribeAll(cb)` | Stream the project list; returns an unsubscribe function |
| `create(id, data)` | Create a project |
| `update(id, patch)` | Deep-merge a patch into a project |
| `remove(id)` | Delete a project and its live audit log. The server keeps its version history |
| `log(id, entry)` | Append an audit-log entry |
| `subscribeLog(id, cb)` | Stream the most recent log entries for a project |

Three implementations ship: `DbStore` (Claude artifact database), `LocalStore`
(browser `localStorage`), and `ApiStore` (a self-hosted FastAPI + PostgreSQL
backend). `ApiStore` is selected automatically when `/api/health` answers, so
one build serves both the GitHub Pages copy and the Docker stack.

To back the tool with something else — Firestore, Supabase, your own service —
add a fourth class implementing those six methods and select it at boot. See
[Deploying with Docker and SSO](deploy.md).

!!! warning "Sign-off needs real identity"

    `LocalStore` has no concept of a user, so checkpoint sign-offs it records
    are self-asserted. If sign-offs need to carry weight for audit, your backend
    must supply an authenticated identity, as the artifact database does.

## The Docker Compose stack

`compose.yaml` in the repository root runs the whole thing on one host: the
proxy, the API that implements the six methods above, and Postgres.

```bash
cp .env.example .env     # or: make env
pixi run build-app       # regenerates docs/app/index.html from app/
docker compose up -d     # or: make up
```

Then open `http://localhost:8080/`.

| File | What it is |
|---|---|
| `compose.yaml` | The stack. Production-shaped: no port on the API, none on the database. |
| `compose.dev.yaml` | Opt-in override: fixed dev identity, hot reload, ports on `127.0.0.1`. |
| `proxy/Caddyfile` | Serves the dashboard, proxies `/api`, owns the identity header. |
| `proxy/Dockerfile` | Bakes the Caddyfile and the built dashboard into an image for the clouds. |
| `.env.example` | Every variable, commented. Copy to `.env`; it is git-ignored. |
| `Makefile` | `make dev`, `make backup`, `make check-isolation`. |

### Identity comes from the proxy

The API does not authenticate anybody. The proxy deletes any
`X-Auth-Request-User`, `-Name` or `-Email` the browser sent, then sets them
from a source you configure in `.env`:

```bash
# behind an SSO front door: the header it sets. Pick one.
IDENTITY_ID_SOURCE={http.request.header.X-Goog-Authenticated-User-Id}
IDENTITY_STRIP_PREFIX=accounts.google.com:   # Google IAP only; see below
# IDENTITY_ID_SOURCE={http.request.header.X-Amzn-Oidc-Identity}
# IDENTITY_ID_SOURCE={http.request.header.X-Ms-Client-Principal-Id}
```

Google IAP sends its identity as `accounts.google.com:person@hospital.org`.
`IDENTITY_STRIP_PREFIX` removes that prefix before anything is stored, so an
access list holds `person@hospital.org` however the person arrives. Set it
**before anyone signs in**: `make up` refuses a Google source without it,
because access lists built from prefixed ids stop matching later and every
project then disappears from its owner, with no error anywhere. Every other front
door sends an unprefixed value and needs no prefix.

#### If access lists were already stored with the prefix

If people signed in before the prefix was set, their access lists hold
`accounts.google.com:person@hospital.org`, and once the prefix is set those
entries match nobody: every such project disappears from its owner, and a direct
request answers 404. Count the affected entries, then rewrite them. This edits the
database directly, so the application does not record it: note it in your change
record. History is not touched, because a live project's versions are read against
its current access list, so repairing the project repairs who can read them.

```sql
-- how many access entries still carry the prefix
SELECT count(*) AS prefixed_entries
  FROM projects p,
       LATERAL jsonb_each(COALESCE(p.doc -> 'access', '{}')) AS a(role, list),
       LATERAL jsonb_array_elements_text(
         CASE WHEN jsonb_typeof(a.list) = 'array' THEN a.list ELSE '[]' END
       ) AS e(entry)
 WHERE e.entry LIKE 'accounts.google.com:%';

-- remove it from owners, writers and readers
UPDATE projects p
   SET doc = jsonb_set(p.doc, '{access}', (p.doc -> 'access') || (
         SELECT jsonb_object_agg(r.role, COALESCE((
                  SELECT jsonb_agg(
                           regexp_replace(x, '^accounts\.google\.com:', ''))
                    FROM jsonb_array_elements_text(
                           COALESCE(p.doc -> 'access' -> r.role, '[]')) AS x
                ), '[]'))
           FROM unnest(ARRAY['owners', 'writers', 'readers']) AS r(role)))
 WHERE jsonb_typeof(p.doc -> 'access') = 'object'
   AND (p.doc -> 'access' ->> 'owners'  LIKE '%accounts.google.com:%'
     OR p.doc -> 'access' ->> 'writers' LIKE '%accounts.google.com:%'
     OR p.doc -> 'access' ->> 'readers' LIKE '%accounts.google.com:%');
```

Never put a literal such as `dev@localhost` here. It makes every visitor the
same person, so `make up` refuses to start on it. For local development, run
`make dev`: it supplies a fixed developer identity through `compose.dev.yaml`,
the one place a literal belongs.

Headers the proxy does not own pass through untouched, so an API that prefers
to verify a signed assertion itself — the IAP JWT, `x-amzn-oidc-data`,
`X-MS-CLIENT-PRINCIPAL` — still receives it. See
[Deploying with SSO](deploy.md) for running this on Google Cloud, AWS or Azure.

!!! danger "The API must be unreachable except through the proxy"

    This is not hardening, it is the security model. Anyone who can open a TCP
    connection to the API sets the identity header themselves and becomes
    whoever they like, including signing off a checkpoint in a colleague's
    name.

    `compose.yaml` enforces it with networking rather than with a convention:
    the API publishes no host port, the only network it shares with anything
    internet-facing has the proxy as its sole other member, and Postgres sits
    on an `internal: true` network with no route off the host at all.

    `make check-isolation` asserts all of this against a running stack. Run it
    after any change to the networking, and keep it in whatever runs after a
    deploy. It exits non-zero on a published port on `api` or `db`, on a direct
    connection to the API that succeeds, or on a forged identity header that
    comes back as the identity.

    `compose.dev.yaml` deliberately breaks this by publishing the API on
    `127.0.0.1:8000`. That is why it is a named override rather than
    `compose.override.yaml`, which `docker compose up` would pick up silently.

### How the containers are locked down

The proxy is the only service reachable from outside, so it gets the strictest
treatment: it runs as an unprivileged user (uid 65532), drops every Linux
capability except the one the Caddy binary asks for, and has a read-only root
filesystem. The API drops all capabilities and is read-only too, on top of the
unprivileged user its image already uses. All three services set
`no-new-privileges` and have memory, CPU and process limits (see the resource
limits in `.env.example`).

A small one-shot service, `proxy-perms`, hands the proxy's two named volumes to
that user before it starts, because Docker creates them root-owned and a
non-root Caddy could not otherwise write its certificates. It has no network
and only the two capabilities `chown` needs, and it also covers an upgrade: the
volumes an earlier, root-run proxy populated are fixed on the next `up`.

`docker compose ps` hides it once it has exited; `docker compose ps -a` shows
it with exit code 0. The cloud image (`proxy/Dockerfile`) is unprivileged the
same way. In a cloud, set memory and CPU limits and drop capabilities in the
task or service definition, which is where the platform applies them.

### The data survives `docker compose down`

Postgres writes to the named volume `pgdata`.

```bash
docker compose down        # containers and networks go; pgdata stays
docker compose down -v     # pgdata is destroyed, with no undo
make backup                # pg_dump through the running server -> backups/
```

Back up with `make backup`, not by copying the volume's files: a live cluster
copied file-by-file gives a torn snapshot that may not restore.

`make backup` and `make restore` read the passphrase from the `BACKUP_PASSPHRASE`
environment variable, so `export` it (or have your secret store set it). Do not
write `make backup BACKUP_PASSPHRASE=...`: that puts it in `make`'s own command
line, where any local account can read it. The dump is encrypted with GnuPG
through a temporary file that only you can read, and a failed dump, or a
restore with the wrong passphrase, exits non-zero.

### Backups: `make backup` is a tool, not a backup strategy

`make backup` writes an encrypted dump of a running database. On its own it is not
a backup plan (45 CFR 164.308(a)(7) makes a data backup plan *required*), for
three reasons, each of which is a decision you make.

**1. Nothing schedules it.** Run it from the host's scheduler, for example daily
at 02:30. `BACKUP_PASSPHRASE` must be in that job's environment, from a secret
store, never typed on a command line:

```cron
30 2 * * *  /srv/chai/nightly-backup.sh
```

```sh
#!/bin/sh
# /srv/chai/nightly-backup.sh
cd /srv/chai
export BACKUP_PASSPHRASE="$(cat /etc/chai/backup.pass)"
make backup BACKUP_RETAIN=30
make verify-backup
```

**2. It writes to `backups/` on the same disk as the database.** A copy on the
host it protects does not survive losing the host. Copy each file to storage in
**another account or site**, and keep the passphrase somewhere else again. A
backup in the same account as the thing it protects does not survive that account
being compromised.

**3. Nothing restores from it unless you do.** A backup that has never been
restored is a hypothesis. `make verify-backup` restores the newest dump (or
`FILE=...`) into a throwaway PostgreSQL of the same major version as production,
with no network, and checks that the tables, the rows and the **append-only
triggers** came back. A dump that restores without them has quietly lost the
guarantee the history rests on. It exits non-zero otherwise, so run it after the
backup, from the same scheduler. How long it takes is your real restore time,
which is the number to write down.

`make restore` overwrites the live database with a dump, so it asks you to type
`YES` first (`CONFIRM=YES` skips the question for automation). Practice the
restore somewhere that is not production before you need it.

### Encryption at rest

The database lives in the Docker volume `pgdata`, which is an ordinary directory
on the host's disk. **Nothing in this stack encrypts it.** If the disk is not
encrypted, whoever holds the disk (stolen, returned to a vendor, improperly
disposed of) can read every record.

45 CFR 164.312(a)(2)(iv), encryption at rest, is *addressable*: implement it, or
document why an equivalent is reasonable. Either way it has to be a decision on
the record, and there is a practical reason to make it. If this stack holds
protected health information, whether a lost disk is a reportable breach can
turn on whether the data was encrypted to the standard HHS describes (45 CFR
164.402); ask your privacy officer. Whether this system is approved for
protected health information at all is a separate question this repository has
not answered.

To encrypt it, put **Docker's data root** (`/var/lib/docker` by default, which
holds `pgdata`) on an encrypted volume:

- **A host you manage:** LUKS/dm-crypt on the device that holds the data root,
  or an encrypted filesystem, and `data-root` in `/etc/docker/daemon.json` if
  you moved it. Keep the key somewhere other than that host.
- **A cloud VM:** the provider's encrypted disks (encrypted EBS volumes,
  encrypted Persistent Disks, encrypted managed disks), enabled when the disk is
  created. Check the setting on the disk that backs the data root, not on the
  boot disk.

Then set `STORAGE_ENCRYPTION_CONFIRMED=1` in `.env`. **That is you telling the
stack it is done: nothing inside a container can check.** `make up` refuses a
stack that is reachable beyond this machine (a non-loopback `HTTP_BIND`) that
uses its own database volume until you do, so the decision is made by someone,
once, on the record. `make doctor` reports what the host shows under the volume
(a dm-crypt layer, or none, or that it cannot tell); treat "none" as "ask",
because a cloud provider may encrypt below what the host can see.

`make backup` already encrypts every dump with a passphrase of its own (see
above); that is separate from, and does not replace, an encrypted volume.

Not covered: application-level or column-level encryption of the project
documents. It would break the `jsonb` merge, version history and every query,
for a threat the disk-level control already addresses.

### Deleting and destroying data

There are three different things, and they reach different amounts. **Deleting a
project does not erase its history.** That is deliberate: an audit trail that
vanishes with its subject is not one. But it means that deleting is not erasure,
and nothing here should be described to anyone as if it were.

| | Live document | Audit log | Version history |
|---|---|---|---|
| **Edit** a field | corrected | an entry is added | the old revision is kept |
| **Delete** the project | removed | removed with it | **kept**, readable by owners |
| **Destroy history** (a purge) | untouched | content destroyed | content destroyed |

**Delete** (`DELETE /api/projects/{id}`) removes the project and its live audit
log. It writes a permanent tombstone to `project_deletion`: who deleted it, when,
and what its last revision hashed to. The tombstone holds no content.

**Destroy history** (`DELETE /api/projects/{id}/versions`, owners only; in the
app, a choice in the delete dialog) is the separate step that answers "this should
never have been recorded", for example a patient identifier pasted into an
evidence field. A purge destroys the content of every revision **and of every
audit-log entry**, including the prose, which carries the values too. What stays
is who changed what, when, which field, and the fingerprint, so the history shows
that something was written and later destroyed, not a gap. The server records the
purge in the log. It is irreversible.

To remove a value that was entered by mistake: correct the live document, then
destroy the history. To remove a whole record: destroy the history, then delete
the project (the dialog does them in that order, so a failure does not leave you
believing the data is gone). Then check:

```sql
select project_id, deleted_by, deleted_at, last_rev from project_deletion;
select count(*) from project_version where doc::text like '%the-value%';
select count(*) from project_log where entry::text like '%the-value%';
```

**What none of this reaches.** Backups made earlier still hold the data, and
`make restore` puts it back, so a restore after a purge must be followed by
another purge. The identifiers of the people who made changes (`created_by`,
`updated_by`, `changed_by`, `by_id`) are not removed either; that is a separate
question from erasing content, and it has a real tension with keeping an audit
trail.

### Two database roles

The audit log and the version history are append-only because of database
triggers, and a table's owner can switch a trigger off with one statement. The
Postgres user `.env` calls `POSTGRES_USER` owns every table (and, in this
image, is a superuser), so an API that connected as it would only be bound by the
triggers as long as the API behaved.

So the API does not. Two roles:

| Role | Password | Held by | Can |
|---|---|---|---|
| owner (`POSTGRES_USER`) | `POSTGRES_PASSWORD` | the one-shot `migrate` service only | everything: create tables, disable triggers |
| restricted (`APP_POSTGRES_USER`, default `chai_app`) | `APP_POSTGRES_PASSWORD` | the `api` service | read and write the project tables; it **cannot** disable or drop a trigger, truncate, alter a table or create one |

`migrate` runs before the API on every `up`: it applies migrations and creates the
restricted role with exactly the grants in `server/app/roles.py`
(`docker compose run --rm migrate python -m app.migrate --print-grants` lists
them). The `api` container is given the restricted role's password and none of the
owner's. Set `APP_POSTGRES_PASSWORD` to a **different** `openssl rand -base64 32`
than `POSTGRES_PASSWORD`; `make up` refuses to start if it is empty, short, a
placeholder or the same.

Rotating `APP_POSTGRES_PASSWORD` is a restart, because `migrate` re-applies it:

```bash
docker compose up -d --force-recreate migrate api
```

`make doctor` checks that the restricted role accepts its password and that the
API reports serving as it. A Postgres superuser still bypasses all of this, which
is why the owner's password is the one to guard, and why it lives only in a job.

### Rotating the database password

`POSTGRES_PASSWORD` is read by PostgreSQL **once**, when it initializes an
empty data directory. On an existing `pgdata` volume it is ignored. Editing it
in `.env` therefore changes what the API presents and not what the database
accepts, and the API can no longer reach its own database:

```text
database not ready: password authentication failed for user "chai"
```

Nothing warns about this, and `make up` cannot: `preflight.py` reads `.env` and
has no running database to ask. It is also the check that sends people here,
because it insists the password be strong and not a placeholder — which is
exactly what makes somebody change it.

So ask the running stack instead:

```bash
make doctor
```

It connects as the API does and tells you whether the password in `.env` is the
one the database accepts. The fix keeps every record:

```bash
docker compose exec db \
  psql -U chai -d chai \
  -c "ALTER ROLE chai WITH PASSWORD 'the value now in .env';"

docker compose up -d --force-recreate api
```

That `psql` has no `-h`, so it goes over the container's Unix socket, which
`pg_hba.conf` trusts — it needs no password, which is what makes the rotation
possible when you have locked yourself out.

!!! note "Why `make doctor` connects to `-h db` and not to localhost"

    `initdb` writes a `pg_hba.conf` that trusts the Unix socket *and*
    loopback; the postgres image appends one `host all all all scram-sha-256`
    line, and only that line asks for a password. A check run as
    `psql -h 127.0.0.1` inside the container matches the loopback **trust**
    rule and succeeds with any password at all. The API connects from another
    container over the bridge, so `-h db` is the only path that tests
    anything.

The other option destroys the database, so reach for it only on a stack with
nothing in it worth keeping:

```bash
make backup      # if there is
make prune       # deletes the volume: records, audit log, every version
```

Managed PostgreSQL has none of this problem, because there is no volume and no
`db` service — rotate with the provider and update `DATABASE_URL`. See
[Deploying with SSO](deploy.md).

## Deploying this site

The GitHub Actions workflow at `.github/workflows/pages.yml` builds the
documentation with [Zensical](https://zensical.org) and publishes it on every
push to `main`. The built site includes the dashboard at `/app/`.

Enable it once under **Settings → Pages → Build and deployment → Source: GitHub
Actions**.

To build locally:

```bash
pixi run docs-serve    # live preview at http://localhost:8000
pixi run docs-build    # writes ./site
```

## Staying in step with CHAI

This project paraphrases CHAI's lifecycle, mirrors the Applied Model Card's
field names, and crosswalks both against OPTICA. None of that updates itself.

`.github/workflows/chai-updates.yml` runs weekly, compares
[CHAI's content repository](https://github.com/coalition-for-health-ai/responsible-ai-content)
against the snapshot in `data/chai-upstream.json`, and on any difference opens
a single issue — updated in place, not reopened weekly — assigned to the
repository owner, listing what moved and which files here derive from it.

```bash
pixi run check-chai         # compare now; exits 1 if upstream moved
pixi run check-chai-write   # accept the current upstream as the baseline
```

!!! warning "Two CHAI documents are not watched"

    The Assurance Standards Guide and the Applied Model Card template are PDFs
    with no machine-readable version feed. The check cannot see them, and says
    so in the issue it opens rather than implying full coverage. Check those by
    hand when the alert fires.

## Linting and git hooks

Markdown is linted with [rumdl](https://rumdl.dev), configured in `.rumdl.toml`.
The `mkdocs` flavor is set there deliberately: Zensical shares Material for
MkDocs' Markdown dialect, and under the `standard` flavor an admonition block is
misread as an indented code block and reported as `MD046`.

Git hooks are managed with [prek](https://prek.j178.dev), a drop-in replacement
for pre-commit:

```bash
pixi run hooks-install   # install the git hook shims, once per clone
pixi run check           # run every hook over all files
pixi run lint-fix        # rumdl, fixing what it can in place
```

!!! note "`--strict` does not validate the nav"

    The `zensical build --strict` hook fails on broken internal links, but a
    `nav` entry in `zensical.toml` pointing at a page that does not exist still
    builds cleanly. After changing the nav, check the rendered site.
