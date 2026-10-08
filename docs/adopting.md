# Adopting it

This page is for the person deciding whether to adopt the tool: a CEO, CIO,
CMIO or the executive sponsor of an AI governance committee. It says what the
decision involves, what it costs in the ways that matter, what the tool does not
do, and how to find out for yourself before committing to anything.

## The decision in brief

| Topic | In brief |
|---|---|
| **What it is** | A system of record for AI governance: a portfolio of every AI tool, reviews against a published lifecycle, signed go/no-go decisions, and an audit trail. |
| **License fee** | None. It is open source under the Apache License 2.0. |
| **What you pay for** | Hosting, the IT time to run it, and the committee time to use it. |
| **Who supports it** | Nobody under contract. It has one maintainer, and no response or fix times are promised ([the security policy](https://github.com/tonyreina/ai_governance_healthcare/blob/main/SECURITY.md) says so plainly). |
| **Where the data lives** | On your servers or in your cloud account. The dashboard and its exports contact no outside service. |
| **What IT provides** | A container host or service, PostgreSQL, and your single sign-on in front of it. |
| **What you provide** | A sponsor, a committee with the authority to say stop, and a named owner for each AI tool. |
| **Patient data** | None, in any mode. It is a record of governance, not of care. |
| **Getting out** | Every project exports as JSON, every report as PDF, HTML or Markdown, and the portfolio as CSV. |

## Why not a spreadsheet, or the platform we already own

| Approach | Where it helps | Where it falls short for this job |
|---|---|---|
| A shared spreadsheet or document folder | Free and familiar. | No per-project access control, no history anyone can trust, no overdue reviews that announce themselves, and a sign-off that proves nothing about who signed. |
| A general GRC, risk or ticketing platform your hospital already owns | Already approved, and supported by your IT team. | It starts empty. You build the lifecycle, the status rules, the model card and the reports yourself. |
| A commercial AI-governance product | Typically comes with a contract and support. | Not assessed here. This project makes no comparison with any product, and you should evaluate one on its own terms. |
| **This tool** | Shaped to the CHAI lifecycle and the OPTICA checklist from the first day. Self-hosted. The audit trail is enforced by the database, not only by the application. | No support contract. You operate it. It is a small project. |

The honest summary: if your IT organization wants a supported product, this is
not one. If you want a working, inspectable record of AI governance that you
control, and can live with running it yourselves, it fits.

## What it takes

### People

| Role | What they do |
|---|---|
| **Executive sponsor** | Gives the committee authority to approve and to stop, and reads the portfolio. |
| **Committee chair or CMIO** | Owns the decision at each of the four checkpoints. |
| **A clinical sponsor for each AI tool** | Keeps that tool's checklist, evidence, metrics and model card current. |
| **Reviewers** | Data science, nursing informatics, compliance, a patient representative, whoever your committee names. |
| **An IT operator** | Runs the stack, connects it to single sign-on, keeps backups and applies updates. |
| **A privacy or records officer** | Approves the retention schedule and how often disposal runs, and agrees who may place a litigation hold ([Privacy and retention](privacy.md)). |

### Infrastructure

- A host, or a cloud container service, for three containers: a front-door
  proxy, the API and PostgreSQL. Docker Compose runs all three on one machine;
  the [deployment guide](deploy.md) covers Google Cloud, AWS and Azure.
- Your single sign-on in front of it. Sign-in stays with it: the application
  reads identity from the proxy in front of it and nowhere else. There are no
  passwords to manage in the tool.
- TLS at the front door, encrypted backups copied somewhere an attacker with your
  production credentials cannot delete, and a recorded decision about disk
  encryption. `make up` refuses to start on unsafe settings and says why.

### Time

The tool does not make the review shorter; it makes it findable. For scale, the
OPTICA authors report several hours per stakeholder for each solution, with the
overall duration set by how quickly people become available. The CHAI checklist's
41 criteria are filled in as the work happens, and nobody has measured how long
that takes in practice.

## How to find out for yourself

You can learn most of what you need without deploying anything.

1. **Open the [demonstration](app/index.html).** It runs entirely in your
   browser, so nothing leaves your machine, and **Load sample projects** fills
   it with ten example AI tools, one per CHAI use case.
2. **Read [A review, start to finish](guide.md)** and walk one sample tool
   through its checkpoints.
3. **Watch the [90-second video](index.md#see-it-in-action)** of the shared
   workspace, which is what you would actually run.
4. **Have IT stand it up** on a laptop with `make dev`, or in a test
   environment with `make up` ([Running it](running.md)).
5. **Enter one or two of your real tools**, with governance information only,
   and see what the portfolio tells your committee.

## A suggested path to production

This is a suggestion, not a measured plan, and no durations are claimed.

1. Name the sponsor and the committee, and decide who may sign each of the four
   checkpoints.
2. Have IT deploy a test stack behind your sign-in and run `make check-isolation`
   and `make doctor`.
3. Register the AI tools already in use first. Record the decisions you can
   evidence, with their real dates (every decision has a date field), and the
   gaps you cannot, so the portfolio starts honest rather than clean.
4. Agree the retention schedule with your records officer and schedule
   `make dispose`.
5. Put the portfolio in front of the committee on its regular meeting. The red
   and amber rows are the agenda.
6. Use the exported reports for the board and for any external request.

## What to ask your own organization first

- Does the committee have the authority to stop a tool, and will it use it?
- Can IT put this behind our sign-in, and who will apply updates when they are
  published?
- Who is the clinical owner of each AI tool we run, by name?
- Will people enter evidence? The tool records what people say and who said it;
  it cannot make them say it.
- Is our records officer willing to approve a retention schedule and a disposal
  run?
- What does counsel say about holds, and about whether these records could be
  requested in a dispute?

## Risks and limits to weigh

- **One maintainer, and no support.** If the maintainer stops, you have the
  source, the tests and the license to carry on yourselves. Plan for that
  possibility rather than assuming it away.
- **Only the shared server is a system of record.** The browser-only copy is a
  demonstration. Sign-offs there record a name nobody checked, and it says so
  in a standing banner.
- **It records claims; it does not verify evidence.** A checklist item marked
  *Met* is the reviewer's statement, with their name on it. The tool makes that
  statement attributable and reviewable. It does not test the model.
- **No independent security assessment is part of the repository.** What it
  offers instead is [an inventory of every security property it asserts](security-claims.md),
  each with the test that enforces it, and honestly marked where a property is
  only partly enforced.
- **The cloud guides are untested against real managed databases.** Their
  provider settings come from the providers' documentation and are marked as such
  where they appear.
- **Most translations are machine-drafted and unreviewed.** Simplified Chinese
  has been reviewed and approved by a fluent reader. In the others, the
  patient-data notice and the storage-mode banners stay in English until someone
  fluent reviews them.
- **There is no evidence yet that governance frameworks improve patient
  outcomes.** See [the evidence](frameworks/evidence.md). The tool's claim is the
  narrower one: decisions made legible, attributable and reviewable.
- **This is not legal advice.** Where the documentation cites a HIPAA standard it
  names a practice the control follows, not an obligation on a system that holds
  no patient data. What your organization must do is for your counsel.

## How it is built, so you can check

Every requirement the project holds itself to is written down with the reason it
exists and what enforces it ([REQUIREMENTS.md](https://github.com/tonyreina/ai_governance_healthcare/blob/main/REQUIREMENTS.md)
and [DECISIONS.md](https://github.com/tonyreina/ai_governance_healthcare/blob/main/DECISIONS.md)).
A change cannot merge unless the whole test suite passes, including the real
database, a real browser and the whole Docker stack end to end. The dashboard
is a single file you can read. The project is
open about what it does not yet do, because a governance tool that overstates
itself is worse than none.

## Next step

Ask your IT lead to open the demonstration with you, and ask your committee
chair to walk one sample tool through [a review](guide.md). By the end of one
sitting you will know whether this is the kind of record your committee wants to
keep.
