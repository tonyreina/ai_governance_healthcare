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
| `remove(id)` | Delete a project and its log |
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
# local development: a literal string
IDENTITY_ID_SOURCE=dev@localhost

# behind a cloud SSO front door: the header it sets
# IDENTITY_ID_SOURCE={http.request.header.X-Goog-Authenticated-User-Id}
# IDENTITY_ID_SOURCE={http.request.header.X-Amzn-Oidc-Identity}
# IDENTITY_ID_SOURCE={http.request.header.X-Ms-Client-Principal-Id}
```

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
    deploy.

    `compose.dev.yaml` deliberately breaks this by publishing the API on
    `127.0.0.1:8000`. That is why it is a named override rather than
    `compose.override.yaml`, which `docker compose up` would pick up silently.

### The data survives `docker compose down`

Postgres writes to the named volume `pgdata`.

```bash
docker compose down        # containers and networks go; pgdata stays
docker compose down -v     # pgdata is destroyed, with no undo
make backup                # pg_dump through the running server -> backups/
```

Back up with `make backup`, not by copying the volume's files: a live cluster
copied file-by-file gives a torn snapshot that may not restore.

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
