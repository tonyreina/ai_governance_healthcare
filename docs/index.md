# AI Governance for Healthcare

A single-page tool that walks a hospital AI governance team through the
[Coalition for Health AI (CHAI)](https://chai.org) six-stage lifecycle for each
AI solution they evaluate or run, and tracks the whole portfolio on one
dashboard.

[Open the dashboard :material-arrow-right:](app/index.html){ .md-button .md-button--primary }

## See it in action

<!-- rumdl-disable MD033 -->
<!-- A video element has no Markdown form; the rule is relaxed for this block only. -->
<video controls preload="metadata" width="100%"
       poster="assets/ai-healthcare-governance-demo.jpg"
       aria-label="A 90-second walkthrough of the CHAI governance dashboard">
  <source src="assets/ai-healthcare-governance-demo.mp4" type="video/mp4">
  Your browser cannot play this video.
  <a href="assets/ai-healthcare-governance-demo.mp4">Download the walkthrough
  (MP4, 7.5 MB)</a>.
</video>
<!-- rumdl-enable MD033 -->

A 90-second walkthrough, using sample data only. It shows the portfolio
dashboard and its statuses, opening a project and its access settings, the
stage checklists with their evidence and owners, the go/no-go checkpoints, the
applied model card preview, the OPTICA adoption review, and creating a project.

!!! note "This was recorded on the Docker stack, not the demonstration copy"

    The video shows a **shared workspace**: a server, per-project access control
    and an audit log. The demonstration copy at [`/app/`](app/index.html) runs in
    **browser-only mode**. It stores everything in your browser, has no access
    control, and keeps no server-side audit log, so it is not the same thing. See
    [Running it](running.md) for the modes.

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

## Run it

There are three modes and **they are not equivalent**. Only the server-backed
one enforces access control, keeps a server-side audit log, or produces a
checkpoint sign-off that means anything. See [Running it](running.md) for the
full comparison.

### A shared workspace, for records you intend to keep

A Caddy front door, a FastAPI service and PostgreSQL. Sign-in is handled by
whatever single sign-on the hospital already runs, and the API reads identity
from the proxy and nowhere else.

```bash
make env          # creates .env from the template
$EDITOR .env      # set the two passwords + IDENTITY_ID_SOURCE
make up           # refuses to start on unsafe settings
```

The template ships deliberately incomplete, and `make up` will say exactly what
is missing and why it matters. Then read the
[deployment guide](deploy.md) — every platform section there has a *Close the
back door* step, and those steps are not hardening, they are the deployment.

### Try it out without deploying anything

The dashboard is also a single self-contained file that needs no server. In
that mode everything lives in one browser: colleagues cannot see it, there is
no access control, no server-side audit log, and clearing site data deletes it.
The app shows a standing banner saying so. **Do not put patient-identifiable
information in it.**

```bash
python3 -m http.server 8000 --directory docs
# then visit http://localhost:8000/app/
```

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
