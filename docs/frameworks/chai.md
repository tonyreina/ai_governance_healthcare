# CHAI

The **Coalition for Health AI (CHAI)** is a US non-profit whose members include
health systems, technology vendors, academic centers, and patient advocates. Its
published material is the basis of the lifecycle this tool tracks.

!!! info "What is CHAI's, and what is ours"

    The six-stage lifecycle, the four checkpoints, and the five principles follow
    the structure of CHAI's **Assurance Standards Guide**. The 41 checklist
    criteria in this tool are **original summaries written for this project** —
    they are not the text of CHAI's Responsible AI Checklist.

    CHAI's [responsible-ai-content](https://github.com/coalition-for-health-ai/responsible-ai-content)
    repository is published under **CC BY 4.0** and may be quoted with
    attribution. See [Notice & license](../notice.md).

## Purpose

CHAI's framing is that assurance is a lifecycle property, not a gate you pass
once. A model that was validated at purchase can drift, meet a different patient
mix than it was built for, or be used for something nobody intended. So the
material is organized around stages of a solution's life, and the same five
principles are asked at every stage.

Where [OPTICA](optica.md) asks *should this organization adopt this solution*,
CHAI asks *is this solution being developed, deployed, and operated responsibly,
continuously*.

## The five principles

Every criterion in this tool is tagged with one:

| Tag | Principle |
|---|---|
| **U** | Usefulness, usability & efficacy |
| **F** | Fairness |
| **S** | Safety & reliability |
| **T** | Transparency & accountability |
| **P** | Security & privacy |

The tool scores each principle separately, so a solution that is performing well
but has no monitoring owner shows a weak **S** score rather than a vaguely
diminished overall one.

## The six stages

| Stage | Name | What it establishes |
|---|---|---|
| 1 | Define the problem & plan | A real problem, the right tool for it, and a named accountable owner |
| 2 | Design the AI system | Where it sits in the workflow, who uses it, what happens when it is wrong |
| 3 | Engineer the AI solution | Traceable data and documented choices the assessment stage can verify |
| 4 | Assess | Local validation before any patient is exposed |
| 5 | Pilot | A small, time-boxed trial with stop rules |
| 6 | Deploy & monitor | Scale-up with drift monitoring, change control, and retirement criteria |

## The four checkpoints

Stages are separated by explicit go/no-go decisions, each recorded with a
rationale and a sign-off.

| Checkpoint | After stage | Question |
|---|---|---|
| **A** | 1 | Approve moving to design? |
| **B** | 4 | Approve a pilot? |
| **C** | 5 | Approve deployment at scale? |
| **D** | 6 | Periodic review — continue, change, retrain, or retire? |

Checkpoint D is the one that recurs. Each review sets the next review date, which
is what drives the *Needs update* and *Out of compliance* states on the
dashboard.

## Applied Model Card

CHAI publishes an **Applied Model Card** template — a structured description
of a solution covering basic information, uses and directions, warnings, "trust
ingredients", and resources. This tool reproduces its *section and field names*
and fills them from checklist evidence.

!!! warning "The model card template has a different license"

    CHAI distributes the Applied Model Card template under **CC BY-ND 4.0**
    (Attribution, No Derivatives) — not the CC BY 4.0 that covers the content
    repository.

    That license explicitly permits redistribution "for any purpose, even
    commercially", so commercial use is *not* the constraint. **No Derivatives**
    is: you may not distribute a modified version of CHAI's material. This tool
    uses the template's section and field names to structure its own output; it
    does not redistribute CHAI's document. If you plan to publish something
    closer to the template itself, read
    [the license](https://creativecommons.org/licenses/by-nd/4.0/) first.

## Testing & Evaluation Frameworks

Separately from the lifecycle, CHAI publishes consensus **Testing and Evaluation
(T&E) Frameworks** per use case. These are not questions — they are recommended
methods and metrics, each with an intended use, a rationale, a reference, and
fields for monitoring cadence and responsible party.

Ten use cases are published on CHAI's content hub,
[rai-content.chai.org](https://rai-content.chai.org/):

| Use case | T&E framework |
|---|---|
| Ambient AI | [framework](https://rai-content.chai.org/en/latest/Ambient-AI/t&e-framework.html) |
| Agentic AI | [framework](https://rai-content.chai.org/en/latest/agentic/t&e-framework.html) |
| Clinical decision support | [framework](https://rai-content.chai.org/en/latest/clinical-decision-support/t&e-framework.html) |
| Clinical trials | [framework](https://rai-content.chai.org/en/latest/clinical-trials/t&e-framework.html) |
| EHR information retrieval | [framework](https://rai-content.chai.org/en/latest/electronic-health-record-information-retrieval/t&e-framework.html) |
| General health advice chatbot | [framework](https://rai-content.chai.org/en/latest/general-health-advice-chatbot/t&e-framework.html) |
| Mental health | [framework](https://rai-content.chai.org/en/latest/mental-health/t&e-framework.html) |
| Patient discharge summarization | [framework](https://rai-content.chai.org/en/latest/patient-discharge-summarization/te.html) |
| Prior authorization criteria matching | [framework](https://rai-content.chai.org/en/latest/prior-authorization-ai-supported-criteria-matching/t&e-framework.html) |
| Sepsis risk prediction | [framework](https://rai-content.chai.org/en/latest/sepsis-risk-prediction/te.html) |

Each is split **pre-deployment** and **post-deployment**, and within each, by the
five principles.

!!! tip "Use these to fill the metrics table, not the checklist"

    A T&E framework is guidance for *completing the Applied Model Card*, not a
    third set of questions. Each entry names a method or metric with an intended
    use, a rationale, a reference, and fields for monitoring cadence and
    responsible party — which is exactly the shape of the key metrics this tool
    records at stage 4. See the [crosswalk](../crosswalk.md).

## Source

- [CHAI](https://chai.org)
- [responsible-ai-content](https://github.com/coalition-for-health-ai/responsible-ai-content)
  — CC BY 4.0, © 2025 Coalition for Health AI, Inc.
