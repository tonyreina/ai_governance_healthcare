# CHAI Governance Review

A single-page tool that walks a hospital AI governance team through the
[Coalition for Health AI (CHAI)](https://chai.org) six-stage lifecycle for each
AI solution they evaluate or run, and tracks the whole portfolio on one dashboard.

- **Portfolio dashboard**: every AI project with its lifecycle position, readiness
  score, next periodic review date, and a status of *Out of compliance*,
  *Needs update*, *On track*, or *Retired*, with the reasons spelled out.
- **Lifecycle checklists**: 41 criteria across the six CHAI stages, each tagged to one
  of CHAI's five principles, with status, evidence, owner, and due date.
- **Four go/no-go checkpoints** (after stages 1, 4, 5 and 6) with decision,
  rationale, and a sign-off history.
- **Applied model card** following the field structure of the CHAI Applied Model
  Card, with a live preview.
- **Exports**: standalone HTML report, Markdown, JSON (per project) and CSV (portfolio).

No build step, no dependencies: everything is in `docs/app/index.html`.

**Live site:** <https://tonyreina.github.io/ai_governance_healthcare/> —
documentation, with the dashboard itself at
[`/app/`](https://tonyreina.github.io/ai_governance_healthcare/app/).

## Run it

Open `docs/app/index.html` in a browser, or serve the folder:

```bash
python3 -m http.server 8000 --directory docs
# then visit http://localhost:8000/app/
```

### Storage modes

| Where it runs | Storage | Shared between people? |
|---|---|---|
| Published as a Claude artifact | Artifact database (`claude.use("db")`) | Yes, live, with per-user sign-off |
| Opened directly / GitHub Pages | Browser `localStorage` | No, one browser only |

All persistence goes through two small classes in `docs/app/index.html`, `DbStore` and
`LocalStore`, which share one interface (`subscribeAll`, `create`, `update`,
`remove`, `log`, `subscribeLog`). To back the tool with your own server
(Firestore, Supabase, a FastAPI service, etc.), add a third class with the same
methods and select it at boot.

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

### Deploy

`.github/workflows/pages.yml` builds with Zensical and publishes on every push
to `main`. Enable it once under **Settings → Pages → Build and deployment
→ Source: GitHub Actions**.

## Compliance rules

Status is computed in the browser by `flags()` in `docs/app/index.html`. See
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
