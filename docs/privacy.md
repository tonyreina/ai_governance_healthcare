# Privacy: what is kept, for how long, and what can be erased

This page is the position a privacy officer or data protection officer (DPO) can
point at. It describes what the server-backed deployment stores about **people**
(the staff who use it), what it does not let anyone remove, what it does, and how
to find one person's data. It is a description of the software, not legal advice,
and it does not say that any use of it complies with GDPR, HIPAA or any other law.
Whether it does is for your organization and counsel.

It applies only to the server-backed deployment. The static dashboard keeps
everything in the visitor's browser and sends nothing anywhere.

## What personal data the server holds

The data subjects are the people who sign in: their identifier (the identity the
proxy asserts, usually an email address), their name and email as the proxy sent
them, when they acted, and what they did.

| Where | What identifies a person |
|---|---|
| `projects` | who created and last changed a project; the access list and the sign-off names inside `doc` |
| `project_log` | who wrote each audit entry, and any name in its text |
| `project_version` | who made each revision; a frozen copy of the whole project and its access list as of that revision |
| `project_deletion` | who deleted a project |
| `access_event` | who read what, and the source address |
| `principals` | the name and email the proxy asserted for each identifier |

## How long it is kept

**Nothing here expires, and no retention period has been decided.** The audit log,
the revisions, the deletion record and the read trail are append-only by design,
and nothing deletes a row on a schedule. "Forever, because the table is
append-only" is a fact about the software, not a retention policy, and this page
does not present it as one.

The retention period is an open question for the owner of the deployment (R-47).
It has to reconcile two pulls that point in opposite directions: a documented
retention floor for records that show a medical-device governance decision was
made (45 CFR 164.316(b)(2)(i) sets six years for the documentation the HIPAA
Security Rule requires, where that rule applies), and storage limitation in GDPR
Art. 5(1)(e) (personal data kept no longer than necessary). The software cannot
choose between them and this page does not.

## What can be erased, and what cannot

- **Content can be destroyed.** A revision's content can be purged: its `doc` is
  emptied and the row keeps its number, its author, its time and its original hash.
  An audit entry can be redacted the same way: its text and the value that changed
  are replaced, and the entry keeps who, when and which field. Both record who
  purged and when.
- **The fact of an action cannot.** Who made a revision, who wrote an entry, who
  deleted a project and who read what are rows the database refuses to update or
  delete, and the purge never touches them. That is the point of an audit trail,
  and it is the reason erasure and the trail are in tension.
- **Deleting a project is not erasure.** The history is kept after a delete so
  that the decision can still be reviewed; only a purge destroys content.

A request to erase a person is therefore, in this software, a request to purge
the content that names them and to decide, as a matter of policy, whether the record
of their having acted is kept. GDPR Art. 17(3)(b) allows refusing erasure where
processing is necessary to comply with a legal obligation. Whether a medical-device
governance record qualifies is an argument for your DPO to make with counsel; this
page records only that the software cannot remove the fact of an action without
changing the database by hand, which is a privileged path it exists to avoid.

## Finding one person's data (subject access)

```bash
make subject-access WHO=ceo@hospital.org
```

It reads the running database and reports which tables and columns mention that
identifier, how many rows, and in which projects, plus the person's `principals`
row. It reports locations, not contents: your privacy office decides what is
produced. A match inside a jsonb column is a place to look, not a finding,
since an identifier that is a prefix of another matches both. It changes nothing.

In the dashboard, anyone can do the same for the projects they can open: tick
**Search all text** beside the portfolio search and type a name, an email or a
phrase. Every project whose current text contains it is listed, archived ones
included, with where it was found, and each result opens the project. A
person's name also finds the ids they are stored under (access lists and
sign-offs hold ids). It searches the current version only: earlier revisions
and the audit log are not in the browser, which is what `make subject-access`
is for.

## A restore brings purged content back

A dump taken **before** a purge, restored **afterward**, reinstates every purged
document and redacted entry, because the dump holds their content. So a purge made
for an erasure request can be undone by an ordinary recovery, and nothing flags
it.

After any `make restore`, re-apply every purge made since the dump was taken
(the audit log records each one), and keep dumps no longer than your retention
decision allows. Old backups hold erased content for as long as they exist, which
is a retention matter for the backup copies too. Nothing re-applies purges for you
yet (#116).

## Records of processing (GDPR Art. 30)

This tool is itself the kind of thing a hospital inventories. A starting point for
the entry, to be completed and owned by the controller:

| Field | Draft |
|---|---|
| Controller | *your organization* |
| Purpose | Recording the review and sign-off of AI solutions the organization deploys or evaluates |
| Data subjects | Staff who sign in to the governance server |
| Categories of data | Identifier, name, email, the actions they took and when, what they read, source address |
| Recipients | *those you give access to the project; the operators of the database and its backups* |
| Transfers outside the region | *see "Data residency" in [Cloud deployment](deploy.md); a decision for your DPO* |
| Retention | **Not decided** (R-47). *Fill in once decided.* |
| Security measures | See [Security claims](security-claims.md) and [Self-hosting](self-hosting.md) |
