# What it does, in detail

This page holds the detail behind the [front page](index.md). It is for the
committee, IT, privacy and records staff, and anyone who wants to check what the
software does and does not do.

!!! warning "Governance metadata only"

    **Governance metadata only.** Never enter patient-identifiable information,
    in any storage mode, the self-hosted server included. A governance review
    has no need for a patient's data, and the tool is not designed, configured
    or reviewed to hold it. It does hold personal data about staff; see
    [Privacy and retention](privacy.md).

## The gap this fills

**The frameworks exist. The record does not.**

Serious frameworks for governing health AI now exist. The Coalition for Health
AI (CHAI), a US non-profit whose members include health systems, technology
vendors, academic centers and patient advocates, publishes a lifecycle with
go/no-go checkpoints. OPTICA, from Clalit Health Services in Israel, is a
77-item checklist for deciding whether to adopt a given solution. In June 2026
the WHO Regional Office for Europe named both among four complementary
approaches. That is a description, not an endorsement.

But a framework is a document. It tells a committee what to ask. It does not
remember the answers, assign the follow-up, notice that a review is overdue, or
show a board which of its tools needs attention this month.

**Approval at purchase is the start of governance, not the end.** Most hospital
technology is approved once and then mostly stays what it was. A clinical AI
model does not. How well it works depends on your patients and your data, not
only on the vendor's study. It can drift as practice and populations change. A
vendor can update it, and staff can use it for something nobody intended. OPTICA
was written because a model that performed well where it was built behaved
differently somewhere else. What a hospital needs is a review that recurs, and
a record that shows it did.

**The field has produced principles faster than practice.** A 2025 scoping
review noted at least 173 published AI ethics frameworks in health care, a
figure it cites from earlier work. It found only 16 studies of any of them being
put into operation. None demonstrated a direct link to patient outcomes, which
were mostly unmeasured or underreported
([the evidence, honestly](frameworks/evidence.md)). That is the state of the
discipline, and this tool does not pretend otherwise. What a hospital can do
now, and will be asked about, is show that it governed: decisions made by named
people, on recorded evidence, and revisited on a schedule.

## What you get

**One portfolio, and an honest status for each tool.** Every AI project appears
on one dashboard with its lifecycle position, a readiness score, its next review
date and a status: *Out of compliance*, *Needs update*, *On track* or *Retired*.
The status is computed from the record by fixed rules, not typed in by whoever
is presenting. A live tool with an action past due, a criterion not met, an
overdue review or an incomplete model card is red, and the reasons are spelled
out beside it. The labels are the software's own and are not a legal finding.
The rules check that a record is complete, current and approved, not that it is
true. See [How statuses are decided](compliance-rules.md).

**Decisions with names on them.** Four checkpoints (approve design, approve a
pilot, approve deployment, review periodically) each record the decision, the
rationale and the conditions. The first three are go or no-go decisions. The
fourth is a periodic review that decides to continue or retire the tool. The
rationale is whatever the reviewer writes. On the shared server a sign-off
carries the name of the person signed in through your hospital's own single
sign-on, not whatever the browser claims.

**A history that is hard to rewrite quietly.** Every change is recorded: who
made it, when, and what the record said afterward. The database itself refuses
to alter the audit log or the revision history, and the shipped stack runs the
service as a database role that cannot switch that protection off. The service
refuses to start as the database owner unless an operator sets
`ALLOW_OWNER_ROLE=true`. A database administrator still can. That is why the
events that matter most (a project created, deleted or purged, record reads, and
refused requests) are also emitted as security events. Your IT team has to
collect those into a log it controls and keeps apart from the database. The
shipped stack does not do that for you (see [Cloud deployment](deploy.md)). Who
*read* a record is recorded too.

The history is not permanent. An owner's purge, or the end of a retention
period, destroys the content of past revisions. Each revision keeps its number,
author, time and hash, and the purge is recorded with who ran it and when.
Deleting a whole project removes its live audit log with it. A permanent record
that the project was deleted, by whom and when, remains, and the revision
history is kept, readable by owners, until it is purged
([Privacy and retention](privacy.md)).

**Reviews that come back.** Each deployed tool has a review cadence, three
months to two years. The date is on the dashboard. Within 30 days of it, the
tool gets an amber flag and shows as *Needs update*. Once the date has passed,
the date turns red and the tool shows as *Out of compliance*. A tool that is not
yet deployed has no review date, and a retired tool raises no flags.

**An applied model card and reports for everyone who asks.** Each tool gets a
model card in the structure of the CHAI Applied Model Card, with key metrics
reported against the populations they were measured on. A report for the board,
an auditor or a regulator exports as PDF, HTML or Markdown, and the data exports
as JSON and CSV. The reports are in the reader's language, except the
storage-mode note, which stays in English until it is reviewed; the JSON and CSV
stay in English so scripts can read them. See [Exports](exports.md).

**Two frameworks, one tool.** The CHAI lifecycle is always on. The OPTICA
adoption checklist can be switched on per project, and a
[crosswalk](crosswalk.md) shows where they overlap and where they do not.

**Your infrastructure, your sign-in, your data.** It runs on your own
servers or cloud account, behind the single sign-on your hospital already uses.
The dashboard and its exports contact no outside service. The data scope is
governance metadata only, and the server has retention, litigation-hold and
subject-access tools for the personal data about *staff* that a governance
record necessarily contains ([Privacy and retention](privacy.md)).

**In your staff's language.** English, Spanish, French, German, Hindi, Russian,
Simplified Chinese and Hebrew, which reads right to left. Most translations are
machine-drafted and unreviewed.

## What it is not

- **It does not find AI tools.** It is the register, not a scanner. Someone has
  to enter each solution. - **It does not test or monitor models.** It records
  that people reviewed a tool, on what evidence, who decided and when the next
  review is due. The metrics are entered by your team, and a Python example
  loads Fairlearn results into the model card. - **It is designed to hold no
  patient data**, in any mode. That is a rule, not a technical block. Nothing
  stops someone typing patient details into a free-text field, which is why an
  offline `make phi-scan` exists to look for them. It finds only the patterns it
  knows, and a clean run does not mean nothing is there. - **It is not a
  certification.** Reports are internal governance records, not legal opinions
  or regulatory determinations. The project is independent of CHAI and not
  endorsed by it ([Notice and license](notice.md)). - **It has not been shown to
  make patients safer.** Nothing in this category has yet. It makes decisions
  legible, attributable and reviewable, and the link from there to clinical
  benefit is assumed, not demonstrated.

## What it takes

The software is free and open source (Apache License 2.0). It has one
maintainer and no vendor: there is no support contract, no response-time promise
and no hosted service. You run it, or your IT team does, as a small container
stack on a server or in your cloud account. The real costs are people's time:
an executive sponsor, a governance committee that will use it, an owner for each
AI tool, and someone in IT who can run it behind your sign-in.

[Adopting it](adopting.md) sets out the decision in full: what it takes, what it
does not do, how to try it without a commitment, and what to ask your own team
first.
