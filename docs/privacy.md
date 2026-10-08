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

The project owner decided these periods (R-54). They are a starting point for
your organization's records retention schedule, which should hold them alongside
its other committee and compliance records, and which takes precedence.

| Record | Kept for |
|---|---|
| A project, its revisions and its audit log | The life of the AI solution, plus 6 years after it is retired |
| The read trail (who opened what) | 6 years, or your audit-log policy if shorter |
| The security event log, in your log system | Your security-log policy (often 1 year readily searchable) |
| Staff names and emails (`principals`) | While the person is active, then as long as a retained record refers to them |
| Backups | 35 days rolling, plus any archive your backup policy keeps |

Why: the record exists to show who reviewed a clinical AI tool and on what
evidence, for as long as anyone could ask, so the clock starts at retirement,
not at creation. Six years follows the practice hospitals already use for
compliance documentation (the HIPAA Security Rule's documentation period, 45 CFR
164.316(b)(2)(i)), and covers most malpractice limitation periods. A litigation
hold suspends any period. If a tool was used on children, ask counsel whether
the limitation periods for minors in your state call for longer. Backups bound
how long an erasure takes to be complete, because a purged value survives in
every older backup until it expires.

**Nothing deletes on this schedule yet.** The audit log, the revisions, the
deletion record and the read trail are append-only, and no job ages them out.
Disposing of a retired project at the end of its period is a manual purge and
delete today; an automatic disposal step needs a deliberate exception to the
append-only rule (R-10) and has not been built.

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
for an erasure request could be undone by an ordinary recovery.

`make restore` puts the purges back. Before it overwrites the database it reads
every purge the live database holds into a ledger file in `backups/` (who purged
which project, when, and how far; no content), and after the restore it applies
them again, with their original time and person. Each project's audit log gets a
system entry saying so. Run twice, it changes nothing the second time.

If the live database cannot be read (it is the thing you are recovering from),
`make restore` says that purges will **not** be re-applied, and carries on. The
security log still has every purge (`versions.purged` carries what a re-apply
needs), so rebuild the ledger from it and apply that:

```bash
python3 scripts/purge_ledger.py from-log security.jsonl --out ledger.json
make reapply-purges LEDGER=ledger.json
```

Purge events written before this existed lack those fields; the script counts
them and they have to be re-applied by hand. And old backups still hold erased
content for as long as they exist, which is a retention matter for the backup
copies too.

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
| Retention | See "How long it is kept" above (R-54); confirm against your records retention schedule |
| Security measures | See [Security claims](security-claims.md) and [Self-hosting](self-hosting.md) |
