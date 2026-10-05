# Compliance rules

Each project gets a status from the flags raised by `flags(p)` in `docs/app/index.html`.
Any red flag makes the project **Out of compliance**; otherwise any amber flag
makes it **Needs update**; otherwise it is **On track**. Projects stopped at a
checkpoint or retired at Checkpoint D are **Retired** and raise no flags.

## Lifecycle phase

| Phase | Condition |
|---|---|
| Intake & planning | Checkpoint A not yet approved |
| Design, build & assess | Checkpoint A approved |
| Pilot | Checkpoint B approved |
| Deployed | Checkpoint C approved |
| Stopped / Retired | "Stop" at A, B or C, or "Retire" at D |

"Approved" means a decision starting with *Proceed* or *Continue*.

## Red: out of compliance

| Rule | Applies to |
|---|---|
| Action items past their due date (not met, partial, or unanswered) | Pilot, Deployed |
| Any checklist criterion marked *Not met* | Deployed |
| No deployment date recorded at Checkpoint C | Deployed |
| Periodic review overdue | Deployed |
| Model card missing one or more core fields | Deployed |

## Amber: needs update

| Rule | Applies to |
|---|---|
| Action items past their due date | Intake, Design/build |
| Periodic review due within 30 days | Deployed |
| Last periodic review asked for retraining or revision | Deployed |
| Model card missing core fields | Pilot |
| Model card not edited since the most recent approved checkpoint | Pilot, Deployed |
| No key metrics recorded | Pilot, Deployed |
| Conditional approval with no conditions recorded | Any |
| Checkpoint approved over open criteria with no rationale | Any |
| No activity in 90 days | Not deployed |

## Periodic review date

`next review = (Checkpoint D date, else Checkpoint C date) + cadence`.
Cadence is set per project (3, 6, 12 or 24 months) and defaults to 6 months for
high-risk projects and 12 months otherwise. **Record a new periodic review today**
on Checkpoint D resets the date.

## Core model card fields

Intended use and workflow, primary intended users, targeted patient population,
cautioned out-of-scope settings, known risks and limitations, clinical risk level,
outcomes and outputs, input data source, ongoing maintenance.

Edit `CORE_CARD` in `index.html` to change the list.
