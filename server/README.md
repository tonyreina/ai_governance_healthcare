# CHAI governance API

The shared-storage backend for the dashboard. It implements the six-method
store contract the browser uses, over REST plus Server-Sent Events, on
PostgreSQL.

For running this behind Google Cloud IAP, an AWS ALB or Azure Easy Auth, see
[`docs/deploy.md`](../docs/deploy.md).

## The contract

| Store method | HTTP |
|---|---|
| `subscribeAll(cb, err)` | `GET /api/projects` + `GET /api/events` |
| `create(id, data)` | `POST /api/projects/{id}` — 409 if it exists |
| `update(id, patch)` | `PATCH /api/projects/{id}` — deep merge |
| `remove(id)` | `DELETE /api/projects/{id}`: removes the project and its live log, keeps the version history, writes a tombstone |
| `purgeVersions(id)` | `DELETE /api/projects/{id}/versions`: destroys the content of every revision **and** of the audit log. Owners only; irreversible. Server store only |
| `log(id, entry)` | `POST /api/projects/{id}/log` |
| `subscribeLog(id, cb)` | `GET /api/projects/{id}/log` + `GET /api/events` |

Plus `GET /api/health` (unauthenticated), `GET /api/me`, and
`GET /api/principals?ids=a,b,c`, which turns identity ids into names and emails
(see below).

The two `subscribe*` methods are a fetch plus a stream: fetch once, hold
`/api/events` open, refetch what an event says changed. Events carry an id and
never a document, because `NOTIFY` caps its payload at 8000 bytes and a project
can exceed that.

## Three decisions worth knowing

**The deep merge runs in Python, inside a transaction, behind
`SELECT ... FOR UPDATE`.** The row lock is what makes two concurrent PATCHes to
different fields safe: the second blocks at the `SELECT` until the first
commits, then merges onto the committed document. A recursive `jsonb` merge in
PL/pgSQL would be equally atomic and was rejected for a different reason — it
would be a second implementation of a merge rule the browser already defines in
`app/js/00-core/00-util.js`, and two implementations drift. `tests/test_merge.py`
runs the real JavaScript under node and demands identical output.

PostgreSQL's `||` operator is not an option at all: it merges only the top
level, so `{"items": {"s4-2": {...}}}` would discard every other key under
`items`.

**The audit log is append-only.** No route updates or deletes an entry, and a
trigger refuses `UPDATE` on the table (`migrations/001_init.sql`), with exactly
one exception: the redaction a purge performs (`migrations/005_disposal.sql`),
which the trigger verifies by comparing the result with `project_log_redacted()`.
Deleting a project removes its live log by cascade. `at` and
`by` are overwritten on write with the server clock and the proxy identity,
even though the browser sends both — a log whose author is a field the client
sets is not a log.

**Identity comes from a proxy header and nothing else.** No cookie, no bearer
token, no query parameter. Which header is configurable, because each cloud
sends a different one.

## The one hard requirement

**This service must be unreachable except through the proxy.** It trusts a
request header, and a header is trivially forged:

```bash
curl -H 'X-Forwarded-Email: cmo@hospital.org' https://api.example.org/api/me
```

If that can reach the container from anywhere but the proxy, anyone can be
anyone — including signing off a checkpoint in a colleague's name. Network
isolation is the security boundary; `docs/deploy.md` has the per-cloud steps
and a `make check-isolation` that asserts them.

Two optional second locks, both off by default and neither a substitute:
`TRUSTED_PROXY_CIDR` rejects a request whose TCP peer is outside the given
ranges, and `PROXY_SHARED_SECRET` rejects one that does not carry a secret only
the proxy knows.

This is why the container does **not** run uvicorn with `--proxy-headers`: that
would rewrite the peer address from `X-Forwarded-For`, which the client
controls, and the CIDR check would be checking the attacker's own claim.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | `postgresql://…`; `postgres://` and `postgresql+asyncpg://` are accepted too. Wins over the `POSTGRES_*` variables. **Percent-encode the password** (`/ @ : ? #` end the URL early); a broken one fails at startup and says so. |
| `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | —, `chai`, `localhost`, `5432`, `chai` | Used when `DATABASE_URL` is unset. The API builds the URL and encodes the password, so **any password works**. `compose.yaml` uses these. One of the two is required. |
| `PORT` / `API_PORT` | `8000` | Port to bind. Cloud Run sets `PORT`; `compose.yaml` sets `API_PORT`. |
| `IDENTITY_MODE` | `proxy` | Preset: `proxy`, `iap`, `alb`, `easyauth`. |
| `IDENTITY_HEADER` | `X-Forwarded-Email` | The header carrying identity. Overrides the preset. Alias: `AUTH_HEADER_EMAIL`. |
| `IDENTITY_NAME_HEADER` | `X-Forwarded-User` | Display name. Alias: `AUTH_HEADER_NAME`. |
| `IDENTITY_ID_HEADER` | — | Stable user id, if the proxy sends one. Alias: `AUTH_HEADER_ID`. |
| `IDENTITY_STRIP_PREFIX` | — | Removed from the value. `iap` sets `accounts.google.com:`. |
| `IDENTITY_HEADER_FORMAT` | per preset | `plain`, or `jwt` to read claims out of a signed assertion. |
| `IDENTITY_AUDIENCE` | — | In `jwt` mode, require this `aud` claim or `signer` header field. |
| `REQUIRE_IDENTITY` | `true` | Leave it on. `false` serves unidentified requests as `anonymous`. |
| `TRUSTED_PROXY_CIDR` | — | Comma-separated CIDRs the TCP peer must fall inside. |
| `PROXY_SHARED_SECRET` | — | Require `X-Proxy-Secret` to match. |
| `DEV_INSECURE_AUTH` | `false` | **Dev only.** See below. |
| `CORS_ORIGINS` | — | Off. Explicit list only; the app is same-origin with the API. |
| `RUN_MIGRATIONS` | `true` | Apply `migrations/*.sql` at boot, under an advisory lock. **Must be `false`** when the API serves as the restricted role (it cannot create tables); `python -m app.migrate` migrates instead. |
| `APP_DATABASE_URL` | — | The restricted role's connection string. Wins over the pieces below. |
| `APP_POSTGRES_USER` | `chai_app` | The restricted role's name. |
| `APP_POSTGRES_PASSWORD` | — | Its password. With this set the API serves as that role, and `DATABASE_URL`/`POSTGRES_PASSWORD` (the owner's) belong to `python -m app.migrate` only. See `app/roles.py` for exactly what the role may do. |
| `EVENTS_CHANNEL` | `chai_events` | `LISTEN`/`NOTIFY` channel. |
| `LOG_LEVEL` | `info` | |

### Per cloud

| | `IDENTITY_MODE` | Header it reads |
|---|---|---|
| Google Cloud IAP | `iap` | `X-Goog-Authenticated-User-Email` (prefix stripped) |
| AWS ALB (`authenticate-oidc`) | `alb` | `x-amzn-oidc-data`, claims read out of the JWT |
| Azure Easy Auth | `easyauth` | `X-MS-CLIENT-PRINCIPAL-NAME` |
| oauth2-proxy, nginx, Caddy | `proxy` | `X-Forwarded-Email` |

In `jwt` mode the signature is **not** verified. That is safe for exactly the
same reason plain-header mode is safe and no other: nothing but the proxy can
reach the port. Verifying it properly is the upgrade path — check
`x-amzn-oidc-data` against `https://public-keys.auth.elb.<region>.amazonaws.com/<kid>`
and require the `signer` to be your load balancer's ARN. `IDENTITY_AUDIENCE` catches
a token minted for a different service in the same account; without a signature
check it stops misconfiguration, not a determined forger.

## Who an id is

Access lists, sign-offs and log entries hold identity ids, which mean nothing to
a reviewer (an IAP numeric subject id, an ALB `sub`). The API records the name
and email the proxy asserts as people sign in (`principals`, throttled to one
write an hour per person unless the name changes) and `GET /api/principals?ids=`
returns them.

It answers **only for people the caller can already see**: themself, and anyone
named on a project the caller can read (its access lists, sign-offs, last editors
and log authors). Any other id is omitted, not refused, so the table cannot be
walked. At most 100 ids per request. Recording never fails a request.

## Reading the whole audit history

`GET /api/projects/{id}/log` returns the newest page (60 by default, newest
first). It used to be the only page. Now:

- `?limit=N` asks for up to 500 entries.
- `X-Log-Total` is how many entries the project has in all, so a caller can say
  "newest 60 of 412" instead of presenting a window as the history.
- `X-Log-Next` is present only when there is more. Pass it as `?before=` to get
  the next page. It is opaque and safe in a URL; do not build one yourself.

```bash
# every entry, oldest last, for a regulator
url=/api/projects/sepsis-2026/log
while [ -n "$url" ]; do
  curl -si "https://host$url" -H "$AUTH" | tee page.txt | sed -n '/^\r$/,$p'
  next=$(sed -n 's/^[Xx]-[Ll]og-[Nn]ext: \(.*\)\r$/\1/p' page.txt)
  url=${next:+/api/projects/sepsis-2026/log?before=$next}
done
```

The dashboard's changelog shows the window it has and says so ("Showing the
newest 60 of 412 entries"), with a *Show older entries* button on the server
store that goes up to 500; every export carries the same sentence. Paging is
access-controlled exactly like the first page.

## Emergency access

`EMERGENCY_ACCESS_IDS` (comma-separated identity ids) names identities that
hold owner rights on every project, for a record whose only owner has left. Every
use is recorded in that project's own audit log as a system entry (`event:
access.breakglass`, never redacted by a purge) and as a warning on the
`chai.emergency` logger; reads of the same project by the same person are one entry
per ten minutes, writes are never throttled. Off by default. See
`docs/deploy.md`, "Offboarding, and emergency access".

## Denied access is logged

A request from an authenticated user that is refused on a project they have no
right to produces one warning on the `chai.access` logger, with a stable name
so an alert can match it without parsing prose:

```text
(one line; wrapped here)
access.denied actor='ann@hospital.org' project='sepsis-2026'
    need=write held=reader status=403
```

`need` is what the route required (`read`, `write` or `own`), `held` is the role
the user actually has (`none` if they have none), and `status` is what the caller
was told: **404** when they could not even read the project (so its existence is
not confirmed to them) and **403** when they could read it but not do this. The
line carries the project id and never the document. A request for a project that
does not exist is not a denial and is not logged. A burst of these from one actor
is worth an alert; the per-cloud alert policy is where that lives.

## Dev mode

`DEV_INSECURE_AUTH=1` authenticates every request as one fixed fake user and
ignores the identity header entirely, so the stack runs on a laptop with no
proxy. It announces itself three ways: a banner in the startup log, an
`X-Chai-Auth-Mode: DEV-INSECURE` header on every response, and `auth_mode` in
`GET /api/health`.

Never set it anywhere a real person's name could end up in an audit log.

## Running the tests

The pure tests — merge semantics, identity parsing — need nothing. The rest
need a real PostgreSQL, because what they test *is* the database's behavior: a
row lock serializing concurrent PATCHes, a unique constraint producing one 409,
a trigger refusing an `UPDATE`. A fake would test the fake.

```bash
docker run -d --name chai-test-db -p 55432:5432 \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=chai_test postgres:16-alpine

pip install -e '.[dev]'
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/chai_test pytest -q
```

Without `TEST_DATABASE_URL` the database tests skip and say why.

## Layout

```text
app/
  main.py      app factory, lifespan, CORS off, error handler
  config.py    environment -> Settings, with the per-cloud presets
  auth.py      identity from the proxy header; the peer and secret checks
  db.py        asyncpg pool, DSN normalizing, migrations under a lock
  merge.py     the deep merge, mirroring the browser's
  models.py    pydantic models for the envelope, not for the document
  routes.py    every endpoint in the contract
  events.py    LISTEN/NOTIFY -> SSE fan-out
migrations/
  001_init.sql projects + project_log, with the append-only trigger
tests/
```

Nothing in the image refers to this directory by name, so it can be built from
`./server` or `./api` without edits.
