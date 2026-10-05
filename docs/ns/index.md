# `chai:` namespace

Namespace IRI: `https://tonyreina.github.io/ai_governance_healthcare/ns#`

The [Croissant exporter](../exports.md#croissant) emits four terms that have no
equivalent in Croissant or in its Responsible AI extension. They are defined
here so the namespace IRI resolves — an unresolvable namespace in published
linked data is a defect, not a cosmetic issue.

These terms describe **governance state**, not data. They are deliberately few:
the checklist, the checkpoint decisions and the readiness scores are *not*
exported, because Croissant has no vocabulary for assurance attestations and
inventing one here would be worse than linking out to the record itself.

## Terms

### `chai:lifecyclePhase`

Where the solution sits in the CHAI lifecycle at export time.

Range: one of `Intake & planning`, `Design, build & assess`, `Pilot`,
`Deployed`, `Retired`, `Stopped`.

### `chai:complianceStatus`

The governance status computed from the solution's outstanding criteria and
review dates. See [compliance rules](../compliance-rules.md).

Range: one of `Out of compliance`, `Needs update`, `On track`, `Retired`,
`Stopped`.

### `chai:riskTier`

The clinical risk tier assigned by the reviewing organization.

Range: one of `Low`, `Moderate`, `High`.

### `chai:nextReviewDue`

The date the next periodic review falls due, set by the most recent Checkpoint D
decision.

Range: `xsd:date`.

## Stability

These terms are specific to this project. They are **not** a standard, and
nothing outside this repository should depend on them. If CHAI or MLCommons
publishes equivalent vocabulary, the exporter should move to it.
