# How statuses are decided

Every project on the dashboard has a **status**, and the status comes from rules
applied to what the record says. Nobody types it in. This page lists every rule,
so a committee can see why a tool is red and what to do about it.

The rules live in one function, `flags()`, in
[`app/js/10-frameworks/10-chai/10-rules.js`](https://github.com/tonyreina/ai_governance_healthcare/blob/main/app/js/10-frameworks/10-chai/10-rules.js),
beside `phase()`, `nextReview()` and `statusOf()`. They run in the browser, on
the project as the browser holds it, with today's date.

## From flags to status

Each rule that fires adds a **flag**, red or amber, to the project. Then:

1. A project that has been **stopped or retired** is *Retired* and raises no flags.
2. Otherwise, if any flag is red, the status is **Out of compliance**.
3. Otherwise, if any flag is amber, it is **Needs update**.
4. Otherwise it is **On track**.

The dashboard shows the flags under the status, worst first, and the report
lists them all.

## Lifecycle phase

The phase follows the checkpoint decisions, and the rules below depend on it.

| Phase | Condition |
|---|---|
| Intake and planning | Checkpoint A not yet approved |
| Design, build and assess | Checkpoint A approved |
| Pilot | Checkpoint B approved |
| Deployed | Checkpoint C approved |
| Stopped or Retired | "Stop" at A, B or C, or "Retire" at D |

A checkpoint is **approved** when its decision starts with *Proceed* or
*Continue*. The furthest approved checkpoint sets the phase, and a "Stop" or
"Retire" anywhere ends it.

## Red: out of compliance

| Rule | Applies to |
|---|---|
| Action items past their due date. These are criteria with a due date before today that are not Met or N/A, so Partial, Not met and unanswered all count | Pilot, Deployed |
| Any criterion marked *Not met* | Deployed |
| No deployment date recorded at Checkpoint C (so no review date can be worked out) | Deployed |
| Periodic review overdue | Deployed |
| Model card missing one or more core fields | Deployed |

## Amber: needs update

| Rule | Applies to |
|---|---|
| Action items past their due date | Intake, Design and build |
| Periodic review due within 30 days | Deployed |
| The last periodic review (Checkpoint D) asked for retraining or revision | Deployed |
| Model card missing one or more core fields | Pilot |
| Model card not edited since the most recent approved checkpoint | Pilot, Deployed |
| No key metrics recorded (no metric row has a name or a value) | Pilot, Deployed |
| Conditional approval ("with conditions" or "with changes") with nothing recorded in the rationale | Any |
| Checkpoint approved while criteria in the stages before it are unanswered or Not met, with no rationale | Any |
| No activity in 90 days | Not deployed |

## The periodic review date

```text
next review = (Checkpoint D date, else Checkpoint C date) + cadence
```

It exists only for a Deployed tool. The cadence is set per project (3, 6, 12 or
24 months) and defaults to 6 months for High risk and 12 months otherwise.
**Record a new periodic review today**, on the Checkpoint D page, sets the D date
to today and moves the next review forward.

## Core model card fields

A piloted or deployed tool is expected to have these filled in:

- Intended use and workflow
- Primary intended users
- Targeted patient population
- Cautioned out-of-scope settings and use cases
- Known risks and limitations
- Clinical risk level
- Outcome(s) and output(s)
- Input data source
- Ongoing maintenance

## Readiness is not status

The **readiness** percentage on the dashboard is the share of applicable
criteria that are Met, with Partial counting as half and an unanswered criterion
as zero. It shows progress. No rule above reads it, so a tool at 96% can be red
and a tool at 40% can be on track if it is still early in its lifecycle.

## What the rules do not do

- **They do not read the evidence.** A criterion marked *Met* is met as far as the
  rules can tell. The rules check that the record is complete, current and
  approved, not that it is true.
- **OPTICA never changes the status.** The adoption checklist is separate. Its
  answers cannot move a CHAI flag, and the reverse.
- **They do not look at the outside world.** Nothing checks whether a model's
  performance has drifted; a person has to enter that, and the periodic review is
  where it is asked.

## Changing the rules

The rules are your organization's to change, since you run the software.

1. Edit `flags()` for a rule, or `CORE_CARD` in
   `app/js/10-frameworks/10-chai/00-definition.js` for the core model card
   fields.
2. If you add a flag, add its message to `app/i18n/en.json` and to every other
   catalog (`pixi run check-i18n` tells you what is missing).
3. Rebuild the dashboard with `pixi run build-app`, and run the suites in
   [Developing it](developing.md).
4. Update this page.
