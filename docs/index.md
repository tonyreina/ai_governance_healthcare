# AI Governance for Healthcare

**Know which AI is running in your hospital, who approved it, and whether anyone
is still watching.**

!!! warning "Governance metadata only"

    **Governance metadata only.** Never enter patient-identifiable information,
    in any storage mode, the self-hosted server included. A governance review
    has no need for a patient's data, and the tool is not designed, configured
    or reviewed to hold it. It does hold personal data about staff; see
    [Privacy and retention](privacy.md).

[Try the demonstration :material-arrow-right:](app/index.html){ .md-button .md-button--primary }
[What adopting it takes](adopting.md){ .md-button }

## What is this?

Your hospital already uses AI, and someone approved each tool at some point.
This is free, open source software that keeps one shared record of all of them:
who approved each tool, on what evidence, and when it is due for another look.
It does not test AI tools, and it does not promise safety. It gives your
committee one place to keep the answers and your board one place to read them.

## Why does this matter now?

**AI is already here.** In 2024, 71% of US non-federal acute care hospitals used
predictive AI built into their electronic health record, up from 66% a year
earlier ([federal data brief][astp]).

**Most hospitals check it. Showing the checks is the hard part.** Of the
hospitals using predictive AI, 82% said they evaluated it for accuracy and 74%
for bias. Those answers are self-reported. They do not say whether a check was
written down, repeated, or owned by a named person, and that is what a board,
an insurer or a regulator asks to see.

**Expectations are rising, mostly as guidance.** As of October 2026:

- In September 2025 the Joint Commission, which accredits hospitals, and the
  Coalition for Health AI (CHAI) published [guidance on the responsible use of
  AI][jc-guidance]. CHAI is a coalition of health systems, patient advocacy
  groups, technology companies and others. The guidance is not a legal
  requirement. In 2026 the Joint Commission also launched a [voluntary
  certification][jc-cert] for how a hospital governs AI.
- A federal rule, [45 CFR 92.210][cfr], requires organizations that receive
  federal financial assistance, which includes many hospitals, to make
  reasonable efforts to find the patient care decision tools that use race,
  color, national origin, sex, age or disability as inputs, and to reduce the
  risk of discrimination from them.
- States add their own. Texas, for example, has required health care providers
  to tell patients when AI is used in their care since January 1, 2026
  ([HB 149][tx]).

Laws change, and this is not legal advice. Ask your counsel which apply to you.

## Why is one approval not enough?

Published studies show that an AI tool can disappoint once it is in your
hospital, and can change after you approve it.

- **A tool can work worse for you than the vendor said.** Michigan Medicine
  tested a widely used sepsis alert on its own patients ([Wong, 2021][wong]).
  It missed about two thirds of the patients who developed sepsis and raised an
  alert on 18% of all hospital stays. The authors called this substantially
  worse than the developer reported. It was one hospital, looking back at past
  data.
- **A tool can change under you.** A letter in the New England Journal of
  Medicine reports that Michigan later switched the same alert off because of
  false alarms after a shift in its data ([Finlayson, 2021][finlayson]).
- **A tool can look accurate and still be unfair.** A widely used program for
  choosing patients for extra care favored white patients over sicker Black
  patients, because it predicted cost instead of illness
  ([Obermeyer, 2019][obermeyer]).

None of this means AI should stay out. It means a hospital owes its patients a
process, and needs to be able to show that it ran one.

## What happens when you cannot answer?

Sooner or later a board member, an insurer, a regulator or a lawyer asks:

1. Which AI tools are in use in our hospital today?
2. Who approved each one, when, and on what evidence?
3. Is anyone still checking that it works for our patients?
4. If something went wrong, what can we show?

Without one list, the answers sit in meeting minutes, email and one person's
spreadsheet. They take time to gather, and they are hard to vouch for.

We found no published figure for what that costs, so we will not invent one.
Ask your committee secretary how many hours the last board question took. That
is your baseline.

## What do you get?

- **One list, with an honest status.** Each tool shows as *Out of compliance*,
  *Needs update*, *On track* or *Retired*. Fixed rules set the status, so nobody
  types it in. The labels are this software's own, not a legal finding, and the
  rules check that a record is complete and current, not that it is true.
- **Decisions with names on them.** Four checkpoints (approve the design,
  approve a pilot, approve deployment, and a periodic review) each record who
  decided, when, and the reason the reviewer chose to write. In the
  demonstration copy a name is only typed in, and nobody checks it.
- **Reviews that come back.** Each deployed tool has a review date. In the 30
  days before it, the tool shows as *Needs update*. Once the date has passed it
  shows as *Out of compliance*.
- **Reports your board can read,** and a spreadsheet of the whole list.

[What it does, in detail](what-it-does.md) covers all of this, including what
the record protects and what it does not.

## What does it cost, and what does it not do?

There is no license fee. You pay for hosting, your IT team's time and your
committee's time. You also need a sponsor, a committee with the power to say
stop, and a named owner for each tool. We give no dollar figure.

For scale, one academic medical center reported that a fairness and reliability
review of two prediction models took 115 person-hours over 8 to 10 months
([Stanford, 2022][stanford]). That is one center's experience, not a price list,
and this software does not do that work for you.

What it does not do:

- **It has no support.** There is one maintainer and no support contract, and no
  response times are promised. You hold the source code and the license to carry
  on without us.
- **It does not find or test AI tools.** People enter what they know. "Met" on a
  checklist is a reviewer's statement, not a verified fact. Nothing checks
  whether a model has drifted.
- **It is not a certification.** It does not say that any use of AI follows a
  law.
- **It is not built to hold patient data.** Nothing technical stops someone
  typing it into a free-text box, so your staff need to be told.
- **It has not been shown to make patients safer.** A 2025 review found only 16
  studies of AI ethics frameworks being put into practice in health care, and
  none showed a link to patient outcomes ([the evidence,
  honestly](frameworks/evidence.md)).

## How can you start small?

Open the demonstration. It runs in your browser with sample data and needs no
server. It does not keep a trustworthy history or check who signs, so it is for
looking, not for real records.

Then ask your own team three questions. Who would sponsor this? Which committee
could say "stop" to an AI tool? Which one tool would you start with? In a trial,
measure how long the next board question takes to answer, and how many tools you
did not know about. [Adopting it](adopting.md) has the full list.

## See it in action

<!-- rumdl-disable MD033 -->
<!-- A video element has no Markdown form; the rule is relaxed for this block only. -->
<video controls preload="metadata" width="100%"
       poster="assets/ai-healthcare-governance-demo.jpg"
       aria-label="A 90-second walkthrough of the CHAI governance dashboard">
  <source src="assets/ai-healthcare-governance-demo.mp4" type="video/mp4">
  Your browser cannot play this video.
  <a href="assets/ai-healthcare-governance-demo.mp4">Download the walkthrough
  (MP4, 7.8 MB)</a>.
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

## Where to go next

| If you are... | Start here |
|---|---|
| A CEO, board member or executive sponsor | [Adopting it](adopting.md) |
| Wanting the full list of what it does | [What it does, in detail](what-it-does.md) |
| On the AI governance committee, or the CMIO | [A review, start to finish](guide.md) |
| Evaluating the tool yourself | [Running it](running.md) |
| In IT or security | [Self-hosting](self-hosting.md), [Cloud deployment](deploy.md) and [Security claims](security-claims.md) |
| The privacy officer, DPO or records officer | [Privacy and retention](privacy.md) |
| Comparing the frameworks | [The frameworks](frameworks/index.md) and the [crosswalk](crosswalk.md) |
| A developer, or connecting a chatbot | [Developing it](developing.md), [the agent API](agent-api.md) and [the MCP server](mcp.md) |

## Sources

Checked October 12, 2026. Laws and guidance change.

[astp]: https://www.healthit.gov/sites/default/files/2025-09/hospital-trends-use-evaluation-and-governance-predictive-ai-2023-2024.pdf
[jc-guidance]: https://www.chai.org/news/joint-commission-and-coalition-for-health-ai-chai-release-initial-guidance
[jc-cert]: https://www.jointcommission.org/en-us/certification/responsible-use-of-ai-in-healthcare
[cfr]: https://www.ecfr.gov/current/title-45/section-92.210
[tx]: https://capitol.texas.gov/tlodocs/89R/billtext/html/HB00149F.htm
[wong]: https://jamanetwork.com/journals/jamainternalmedicine/fullarticle/2781307
[finlayson]: https://pmc.ncbi.nlm.nih.gov/articles/PMC8665481/
[obermeyer]: https://pubmed.ncbi.nlm.nih.gov/31649194/
[stanford]: https://www.frontiersin.org/articles/10.3389/fdgth.2022.943768/full
