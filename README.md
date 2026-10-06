# CHAI Governance Review

A single-page tool that walks a hospital AI governance team through the
[Coalition for Health AI (CHAI)](https://chai.org) six-stage lifecycle for each
AI solution they evaluate or run, and tracks the whole portfolio on one dashboard.

- **Portfolio dashboard**: every AI project with its lifecycle position, readiness
  score, next periodic review date, and a status of *Out of compliance*,
  *Needs update*, *On track*, or *Retired*, with the reasons spelled out.
- **Lifecycle checklists**: 41 criteria across the six CHAI stages, each
  tagged to one of CHAI's five principles, with status, evidence, owner, and
  due date.
- **Four go/no-go checkpoints** (after stages 1, 4, 5 and 6) with decision,
  rationale, and a sign-off history.
- **Applied model card** following the field structure of the CHAI Applied Model
  Card, with a live preview.
- **Exports**: standalone HTML report, Markdown, JSON (per project) and CSV (portfolio).

**Live site:** <https://tonyreina.github.io/ai_governance_healthcare/> —
documentation, with a **demonstration** copy of the dashboard at
[`/app/`](https://tonyreina.github.io/ai_governance_healthcare/app/). That copy
stores everything in your browser. It is not a system of record.

## Running it

There are three modes and **they are not equivalent**. Only one of them
enforces access control, keeps an audit log on a server, or produces a
checkpoint sign-off that means anything.

| | Docker stack | Claude artifact | Open a file / GitHub Pages |
|---|---|---|---|
| Storage | PostgreSQL | Artifact database | Browser `localStorage` |
| Shared between people | Yes | Yes | **No** |
| Identity | Your hospital SSO | Yes | **None** |
| Access control enforced | **Yes, server-side** | Partly | **No** |
| Audit log | Yes, append-only | Yes | This browser only |
| Version snapshots | **Yes** | No | No |

See [Running it](docs/running.md) for the full comparison.

### Deploy the shared workspace

This is the mode to use for anything you intend to keep. It runs a Caddy front
door, a FastAPI service and PostgreSQL; sign-in is handled by whatever SSO the
hospital already has, and the API reads identity from the proxy and nowhere
else.

```bash
make env                      # creates .env from the template
$EDITOR .env                  # set POSTGRES_PASSWORD and IDENTITY_ID_SOURCE
make up                       # refuses to start on unsafe settings
```

`.env` ships deliberately incomplete: `make up` runs
[`scripts/preflight.py`](scripts/preflight.py) first and will tell you exactly
what is missing and why it matters. The stack binds to loopback by default,
because it speaks plain HTTP and expects TLS to be terminated in front of it.

- **[Deployment guide](docs/deploy.md)** — Google Cloud (IAP), AWS (ALB + OIDC)
  and Azure (Easy Auth), each with a *Close the back door* section. Those
  sections are not hardening; they are the deployment. The API trusts an
  identity header, so it must be unreachable except through the proxy.
- **[Self-hosting](docs/self-hosting.md)** — how the app is built, the store
  contract, and how to back it with something else.

```bash
make dev          # local stack: fixed dev identity, hot reload, exposed ports
make check-isolation   # prove the API is not reachable except through the proxy
make down         # stop. The pgdata volume survives this.
```

### Evaluate it without deploying anything

The dashboard is also a single self-contained file that runs with no server at
all. Everything is stored in that one browser: colleagues cannot see it, there
is no access control, no server-side audit log, and clearing site data deletes
it. The app says so in a standing banner when it is in this mode.

Use it to try the checklists out. **Do not put patient-identifiable
information in it.**

```bash
python3 -m http.server 8000 --directory docs
# then visit http://localhost:8000/app/
```

All persistence goes through one interface (`subscribeAll`, `create`, `update`,
`remove`, `log`, `subscribeLog`), implemented by `ApiStore` (the Docker stack),
`DbStore` (artifact) and `LocalStore` (browser). To back the tool with
something else — Firestore, Supabase, your own service — add a fourth class
with the same methods. The app selects one at boot and **never silently falls
back**: if a server was expected and cannot be reached, it stops and says so.

## Documentation site

The docs are built with [Zensical](https://zensical.org), configured in
`zensical.toml`, with sources in `docs/`. The dashboard lives at
`docs/app/index.html` and is copied into the build verbatim, so the published
site serves the docs at `/` and the app at `/app/`.

The environment is managed with [pixi](https://pixi.sh):

```bash
pixi run docs-serve    # live preview at http://localhost:8000
pixi run docs-build    # writes ./site
```

## Linting and git hooks

Markdown is linted with [rumdl](https://rumdl.dev), configured in `.rumdl.toml`
with the `mkdocs` flavor so Material admonitions and attribute lists are not
reported as errors. Git hooks are managed with [prek](https://prek.j178.dev), a
drop-in replacement for pre-commit.

```bash
pixi run hooks-install   # install the git hook shims, once per clone
pixi run check           # run every hook over all files
pixi run lint            # rumdl only
pixi run lint-fix        # rumdl, fixing what it can in place
```

The same hooks run in CI via `.github/workflows/lint.yml`, so CI cannot drift
from what contributors get locally.

### Publishing the documentation site

`.github/workflows/pages.yml` builds with Zensical and publishes on every push
to `main`. Enable it once under **Settings → Pages → Build and deployment
→ Source: GitHub Actions**.

## Compliance rules

Status is computed in the browser by `flags()`, in
`app/js/10-frameworks/10-chai/10-rules.js`. See
[`docs/compliance-rules.md`](docs/compliance-rules.md) for the full list and how
to change it.

## Working with exports in Python

Each project exports as JSON (schema in [`schema/project.schema.json`](schema/project.schema.json)).

```bash
python examples/load_export.py my-project-chai-review.json
```

`examples/fairlearn_to_metrics.py` takes a Fairlearn `MetricFrame` and appends its
subgroup results to an export's key metrics, so evaluation output flows straight
into the model card. Re-import the file from the dashboard (**Import project JSON**);
an import creates a new project.

## About CHAI content

This project is independent and is not affiliated with or endorsed by CHAI.
See [NOTICE.md](NOTICE.md).

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
