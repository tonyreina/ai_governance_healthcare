# CHAI checklist

The 41 criteria this tool tracks, in the order the dashboard presents
them. Each is tagged with the CHAI principle it serves.

!!! info "Generated file"

    This page is generated from `app/frameworks/chai/framework.json` by
    `scripts/gen_framework_docs.py` (`pixi run gen-docs`), so it cannot drift
    from the checklist the tool actually enforces. Edit the criteria in
    `app/frameworks/chai/framework.json`, not here.

    These criteria are original summaries written for this project. They
    are not the text of CHAI's Responsible AI Checklist — see
    [Notice & license](../notice.md).

## Principles

| Tag | Principle |
|---|---|
| **U** | Usefulness, usability & efficacy |
| **F** | Fairness |
| **S** | Safety & reliability |
| **T** | Transparency & accountability |
| **P** | Security & privacy |

## Stage 1: Define the problem & plan

Agree on the clinical or operational problem, confirm AI is the right tool,
and name who is accountable before anything is built or bought.

*7 criteria.*

| | Criterion | Principle |
|---|---|---|
| 1.1 | Problem statement and target outcome agreed with clinical and operational stakeholders | **U** |
| 1.2 | Current-state or root-cause analysis shows AI is an appropriate intervention, not just a possible one | **U** |
| 1.3 | Success measures and a baseline to compare against are defined | **U** |
| 1.4 | Affected patient populations identified, including groups at risk of being underserved or harmed | **F** |
| 1.5 | Potential harms and failure modes listed, with severity and likelihood | **S** |
| 1.6 | Accountable owner, governance body, and decision rights named | **T** |
| 1.7 | Data needs, privacy, consent, and regulatory constraints scoped | **P** |

## Stage 2: Design the AI system

Specify how the system fits into care: who uses it, where in the workflow,
what it outputs, and what happens when it is wrong.

*7 criteria.*

| | Criterion | Principle |
|---|---|---|
| 2.1 | End users took part in workflow and interface design | **U** |
| 2.2 | Intended use, users, and care setting documented, with out-of-scope uses listed | **U** |
| 2.3 | Subgroups and fairness criteria for evaluation pre-specified | **F** |
| 2.4 | Decision thresholds defined and clinically justified | **S** |
| 2.5 | Human oversight and override path designed into the workflow | **S** |
| 2.6 | Pathway for reporting safety issues and harms drafted, naming who reports to whom | **T** |
| 2.7 | Threat model, access controls, and data flows designed | **P** |

## Stage 3: Engineer the AI solution

Build or configure the model with traceable data and documented choices, so
the assessment stage has something it can verify.

*7 criteria.*

| | Criterion | Principle |
|---|---|---|
| 3.1 | Data provenance and known data limitations documented | **T** |
| 3.2 | Demographic and socio-demographic make-up of development data characterized | **F** |
| 3.3 | Bias mitigation approach chosen and documented | **F** |
| 3.4 | Data quality checks and handling of missing data documented | **S** |
| 3.5 | Version control in place for datasets, code, and model artifacts | **T** |
| 3.6 | De-identification or other privacy-enhancing techniques applied where appropriate | **P** |
| 3.7 | People responsible for monitoring data and model behavior designated | **S** |

## Stage 4: Assess

Validate the solution locally before patients are exposed to it. Record key
metrics below; they flow into the model card.

*8 criteria.*

| | Criterion | Principle |
|---|---|---|
| 4.1 | Performance validated on local data representative of the deployment population | **U** |
| 4.2 | Performance compared across demographic subgroups, with gaps explained | **F** |
| 4.3 | Calibration checked, not only discrimination | **S** |
| 4.4 | Silent (shadow) evaluation run in the live environment | **S** |
| 4.5 | Installation qualification completed, where applicable | **S** |
| 4.6 | Explanations of outputs are suited to the intended users | **T** |
| 4.7 | Security review or vendor security assessment completed | **P** |
| 4.8 | Safety reporting pathway updated with what assessment revealed | **T** |

## Stage 5: Pilot

Run a small, time-boxed pilot to learn whether the solution helps in real
care, for whom, and at what cost to staff.

*6 criteria.*

| | Criterion | Principle |
|---|---|---|
| 5.1 | Pilot scope, sites, duration, and stop rules defined | **U** |
| 5.2 | Usability and workflow fit assessed with frontline users | **U** |
| 5.3 | Real-world effect on outcomes or process measured against baseline | **U** |
| 5.4 | Pilot results checked for differences across patient groups | **F** |
| 5.5 | Adverse events and near misses tracked and reviewed | **S** |
| 5.6 | Users trained, and the approach to patient disclosure decided | **T** |

## Stage 6: Deploy & monitor

Scale up with monitoring, change control, and a plan for when to retrain or
retire.

*6 criteria.*

| | Criterion | Principle |
|---|---|---|
| 6.1 | Performance and drift monitoring live, with alert thresholds and an owner | **S** |
| 6.2 | Subgroup performance monitored on an ongoing basis | **F** |
| 6.3 | Audit schedule and change control set, with a revised model card for each version | **T** |
| 6.4 | Incident response, rollback, and retirement criteria documented | **S** |
| 6.5 | Access reviews and security patching scheduled | **P** |
| 6.6 | Value to patients and staff re-evaluated periodically | **U** |

---

**41 criteria in total.**
