# AI Governance for Healthcare

A single-page tool that walks a hospital AI governance team through the
[Coalition for Health AI (CHAI)](https://chai.org) six-stage lifecycle for each
AI solution they evaluate or run, and tracks the whole portfolio on one
dashboard.

[Open the dashboard :material-arrow-right:](app/index.html){ .md-button .md-button--primary }

## What it does

- **Portfolio dashboard** — every AI project with its lifecycle position,
  readiness score, next periodic review date, and a status of *Out of
  compliance*, *Needs update*, *On track*, or *Retired*, with the reasons
  spelled out.
- **Lifecycle checklists** — 41 criteria across the six CHAI stages, each tagged
  to one of CHAI's five principles, with status, evidence, owner, and due date.
- **Four go/no-go checkpoints** after stages 1, 4, 5 and 6, with decision,
  rationale, and a sign-off history.
- **Applied model card** following the field structure of the CHAI Applied Model
  Card, with a live preview.
- **Exports** — standalone HTML report, Markdown, JSON per project, and CSV for
  the portfolio.

The app has no build step and no dependencies: everything is in a single
`index.html`.

## Run it locally

The dashboard is a self-contained file. Open it straight from the repository:

```bash
# any browser, no server required
xdg-open docs/app/index.html
```

Or serve the folder, which is closer to how it behaves when published:

```bash
python3 -m http.server 8000 --directory docs
# then visit http://localhost:8000/app/
```

## Where it runs

The tool picks its storage backend from where it is running, and the modes are
**not equivalent**: access control, version history and shared editing need a
backend. See [Running it](running.md) for the full comparison and how to run
everything locally.

| Where it runs | Storage | Shared? | Access control enforced? |
|---|---|---|---|
| Docker stack | PostgreSQL | Yes | **Yes** |
| Published as a Claude artifact | Artifact database | Yes | Partly |
| GitHub Pages / opened directly | Browser `localStorage` | No | No |

!!! warning "Published here, your data stays in your browser"

    The copy of the dashboard on this site uses `localStorage`. Nothing is sent
    to a server, and nothing is shared with colleagues. Use the JSON export to
    move a project between people or machines, or see
    [Self-hosting](self-hosting.md) to put it behind a real database.

## Two frameworks, reconciled

This tool tracks the CHAI lifecycle. It also carries a full crosswalk to
**OPTICA**, the Clalit adoption checklist that the WHO Regional Office for
Europe named alongside CHAI as one of four complementary approaches in 2026.

- [The frameworks](frameworks/index.md) — what each is for, and how they differ.
- [CHAI checklist](frameworks/chai-checklist.md) — all 41 criteria.
- [OPTICA checklist](frameworks/optica-checklist.md) — all 77 items, paraphrased.
- [Crosswalk](crosswalk.md) — item-by-item, including the honest finding that
  **no OPTICA item fully discharges a CHAI criterion**.
- [Does any of this work?](frameworks/evidence.md) — the evidence base, and the
  gap in it.

## Where to go next

- [Compliance rules](compliance-rules.md) — how each status is computed, and how
  to change the thresholds.
- [Python exports](exports.md) — read an export in Python, and push Fairlearn
  metrics back into the model card.
- [Self-hosting](self-hosting.md) — back the tool with your own database.
- [Notice & license](notice.md) — the relationship to CHAI's published material.
