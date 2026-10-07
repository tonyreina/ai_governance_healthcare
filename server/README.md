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
| `remove(id)` | `DELETE /api/projects/{id}` |
| `log(id, entry)` | `POST /api/projects/{id}/log` |
| `subscribeLog(id, cb)` | `GET /api/projects/{id}/log` + `GET /api/events` |

Plus `GET /api/health` (unauthenticated) and `GET /api/me`.

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
trigger in `migrations/001_init.sql` refuses `UPDATE` on the table. `at` and
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
| `RUN_MIGRATIONS` | `true` | Apply `migrations/*.sql` at boot, under an advisory lock. |
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
and require the `signer` to be your listener's ARN. `IDENTITY_AUDIENCE` catches
a token minted for a different service in the same account; without a signature
check it stops misconfiguration, not a determined forger.

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
