#!/usr/bin/env python3
"""Convert a project export into Croissant metadata (Croissant 1.0 + RAI 1.0).

    python examples/croissant_export.py my-project-chai-review.json > dataset.jsonld

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT DO
----------------------------------------------------
Croissant describes a **dataset**. A governance record describes a **model** and
an **organizational process**. They are not the same subject, and most of a
governance record has no honest home in Croissant. This exporter therefore:

* Describes the *development/validation data extract* behind the solution.
  ``sc:name`` and ``description`` are about the data. The model itself is carried
  under ``about`` as an ``sc:SoftwareApplication``.
* Links back to the full governance record via ``isBasedOn`` rather than trying
  to encode it.
* Emits **no** ``distribution`` or ``recordSet``. The governance record contains
  no file hashes, no content URLs and no column names, and synthesizing them to
  satisfy a validator would manufacture provenance for clinical data this tool
  has never seen. Croissant 1.0 accepts a metadata-only record.
* Drops the checklist, the checkpoint decisions and the readiness scores
  entirely. Croissant has no vocabulary for assurance attestations, and
  ``sc:creativeWorkStatus`` is not a substitute for a governance body's sign-off.

PHI
---
``rai:dataCollection`` carries cohort size, dates, sites and demographics by
design. A small-cell cohort description attributed to a named organization can be
re-identifying, and Croissant files exist to be published and indexed. Cohort
detail is therefore **withheld by default**; pass ``--include-cohort-detail`` to
emit it, and read the warning that produces.

PEOPLE
------
The review team and clinical sponsor are personal data (GDPR Art. 4(1)), and a
published record that names them links identified individuals to a named
clinical system, a site and a time. That is the detail that supports targeted
social engineering against whoever has authority over a deployment. The default
``maintainer`` is therefore an organizational contact ("AI Governance Committee,
<organization>"), or is omitted when no organization is recorded. Pass
``--include-maintainer-names`` to publish the names, and read the warning that
lists them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

CROISSANT = "http://mlcommons.org/croissant/1.0"
CROISSANT_RAI = "http://mlcommons.org/croissant/RAI/1.0"

# BioCroissant draft profile. github.com/mlcommons/BioCroissant is a skeleton --
# no schema, no context, no implementation -- but its own READMEs point at the
# prototype github.com/renato-umeton/biocroissant-to-omop (MIT), whose
# synthetic_dataset_v0.3.json carries a draft `bio:` vocabulary. That prototype
# marks itself PLACEHOLDER because the context IRI below does not resolve.
#
# So this profile is OFF by default and experimental when on. Emitting terms
# under a prefix that does not resolve is a real defect in published linked
# data; it is only defensible as an explicit, labeled opt-in.
BIOCROISSANT_DRAFT = "http://mlcommons.org/croissant/bio/0.3"
BIOCROISSANT_CONTEXT_IRI = "https://mlcommons.org/croissant/bio/0.3/context"

# Published at https://tonyreina.github.io/ai_governance_healthcare/ns/ so the
# IRI resolves. An unresolvable namespace in published linked data is a defect.
CHAI_NS = "https://tonyreina.github.io/ai_governance_healthcare/ns#"

# The full standard Croissant 1.0 context. Using a trimmed context makes
# mlcroissant warn that the @context is non-standard, so it is reproduced
# in full here, with one project-specific prefix added.
CONTEXT: dict[str, Any] = {
    "@language": "en",
    "@vocab": "https://schema.org/",
    "sc": "https://schema.org/",
    "cr": "http://mlcommons.org/croissant/",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "dct": "http://purl.org/dc/terms/",
    "equivalentProperty": "cr:equivalentProperty",
    "citeAs": "cr:citeAs",
    "column": "cr:column",
    "conformsTo": "dct:conformsTo",
    "data": {"@id": "cr:data", "@type": "@json"},
    "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
    "examples": {"@id": "cr:examples", "@type": "@json"},
    "extract": "cr:extract",
    "field": "cr:field",
    "fileProperty": "cr:fileProperty",
    "fileObject": "cr:fileObject",
    "fileSet": "cr:fileSet",
    "format": "cr:format",
    "includes": "cr:includes",
    "isLiveDataset": "cr:isLiveDataset",
    "jsonPath": "cr:jsonPath",
    "key": "cr:key",
    "md5": "cr:md5",
    "parentField": "cr:parentField",
    "path": "cr:path",
    "recordSet": "cr:recordSet",
    "references": "cr:references",
    "regex": "cr:regex",
    "repeated": "cr:repeated",
    "replace": "cr:replace",
    "samplingRate": "cr:samplingRate",
    "separator": "cr:separator",
    "source": "cr:source",
    "subField": "cr:subField",
    "transform": "cr:transform",
    "chai": CHAI_NS,
}

# The en and em dashes are deliberate, not typos: a date range in a free-text
# field is written "2019-01 to 2023-06", "2019-01 \u2013 2023-06" or with an em
# dash about equally often, and all three have to match.
_YEAR_MONTH = r"(20\d{2}(?:-\d{2})?(?:-\d{2})?)"
_RANGE_SEP = r"(?:to|\u2013|\u2014|-|through|until)"
DATE_RANGE = re.compile(rf"{_YEAR_MONTH}\s*{_RANGE_SEP}\s*{_YEAR_MONTH}", re.I)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "dataset").lower()).strip("-")
    return s or "dataset"


def nonempty(*values: str | None) -> str:
    for v in values:
        if v and v.strip():
            return v.strip()
    return ""


def named_maintainers(meta: dict[str, Any]) -> str:
    """The people the record names as responsible: the review team, else the sponsor."""
    return nonempty(meta.get("reviewers"), meta.get("sponsor"))


def join_parts(*parts: str | None) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def build(
    export: dict[str, Any],
    *,
    include_cohort: bool,
    base_url: str,
    bio_draft: bool = False,
    include_maintainer_names: bool = False,
) -> dict[str, Any]:
    meta = export.get("meta") or {}
    card = export.get("model_card") or {}
    state = export.get("_state") or {}

    solution = nonempty(card.get("name"), meta.get("solution"), "Unnamed AI solution")
    dataset_name = f"{slugify(solution)}-development-extract"

    context = dict(CONTEXT)
    if bio_draft:
        context["bio"] = BIOCROISSANT_DRAFT + "/"

    doc: dict[str, Any] = {
        "@context": context,
        "@type": "sc:Dataset",
        "@id": f"{base_url.rstrip('/')}/{dataset_name}",
        "name": dataset_name,
        # Both profiles from day one. When BioCroissant publishes a context,
        # adding it is appending one string -- no structural change.
        "conformsTo": [CROISSANT, CROISSANT_RAI],
    }
    if bio_draft:
        doc["conformsTo"].append(BIOCROISSANT_DRAFT)
        # The prototype's own self-marking convention, kept verbatim in spirit
        # so a reader of this file is warned the same way.
        doc["_contextNote"] = (
            f"EXPERIMENTAL - the BioCroissant draft context {BIOCROISSANT_CONTEXT_IRI} "
            "does not exist yet. The bio: terms below follow the draft v0.3 vocabulary "
            "from the biocroissant-to-omop prototype and are provisional."
        )

    doc["description"] = join_parts(
        f"Development and validation data extract underlying “{solution}”.",
        card.get("summary"),
        "This record describes the DATA. The AI solution it supports is "
        "described under `about`; the governance review it came from is linked "
        "under `isBasedOn`.",
    )

    # ---- provenance / responsibility -------------------------------------
    if meta.get("developer"):
        creator: dict[str, Any] = {
            "@type": "sc:Organization",
            "name": meta["developer"],
        }
        if meta.get("sourcing"):
            creator["description"] = f"Sourcing: {meta['sourcing']}"
        doc["creator"] = creator
    if meta.get("org"):
        doc["publisher"] = {"@type": "sc:Organization", "name": meta["org"]}
    # Named individuals are gated the way cohort detail is (#60). Without the flag
    # the maintainer is the organization's governance body, never a person, and
    # when no organization is recorded there is nothing honest to name, so it is
    # left out rather than invented.
    if include_maintainer_names:
        maintainer = named_maintainers(meta)
    elif meta.get("org") and meta["org"].strip():
        maintainer = f"AI Governance Committee, {meta['org'].strip()}"
    else:
        maintainer = ""
    if maintainer:
        doc["maintainer"] = {"@type": "sc:Organization", "name": maintainer}

    if card.get("version"):
        doc["version"] = card["version"]
    # `dateCreated`/`dateModified` on a sc:Dataset assert that the DATA was
    # created or changed then. The governance record's timestamps say when the
    # REVIEW was edited, which is a different fact. schema.org has
    # sdDatePublished for exactly this -- the date of the structured
    # description, not of the thing described.
    if state.get("updatedAt"):
        doc["sdDatePublished"] = state["updatedAt"][:10]
    if card.get("releaseDate"):
        doc["datePublished"] = card["releaseDate"]
    if card.get("keywords"):
        doc["keywords"] = [
            k.strip() for k in re.split(r"[,;]", card["keywords"]) if k.strip()
        ]

    # sdLicense covers THIS METADATA RECORD, which this project does license.
    # `license` -- the license of the clinical data itself -- is deliberately
    # left unset: the governance record does not capture one, and guessing a
    # license for a patient-data extract would be worse than omitting it.
    # mlcroissant warns that `license` is recommended; that warning is correct
    # and the honest resolution is for a human to supply it, not for the
    # exporter to invent one.
    doc["sdLicense"] = "https://www.apache.org/licenses/LICENSE-2.0"
    access = join_parts(card.get("security"), card.get("consent"))
    if access:
        doc["conditionsOfAccess"] = access

    citation = join_parts(card.get("evalRefs"), card.get("pubs"))
    if citation:
        doc["citeAs"] = citation

    # ---- Responsible AI extension ----------------------------------------
    dev_data = (card.get("devData") or "").strip()
    if dev_data:
        if include_cohort:
            doc["rai:dataCollection"] = dev_data
        else:
            doc["rai:dataCollection"] = (
                "Withheld. Cohort size, dates, sites and demographics are "
                "recorded in the linked governance record. Re-export with "
                "--include-cohort-detail to publish them."
            )
        match = DATE_RANGE.search(dev_data)
        if match:
            doc["rai:dataCollectionTimeframe"] = f"{match.group(1)}/{match.group(2)}"

    if card.get("inputSource"):
        doc["rai:dataCollectionRawData"] = card["inputSource"]
    if card.get("biases"):
        doc["rai:dataBiases"] = card["biases"]
    if card.get("biasMitigation"):
        doc["rai:dataPreprocessingProtocol"] = card["biasMitigation"]
    if card.get("maintenance"):
        doc["rai:dataReleaseMaintenancePlan"] = card["maintenance"]
    if card.get("consent"):
        doc["rai:personalSensitiveInformation"] = card["consent"]

    # Both the targeted population and the cautioned out-of-scope settings are
    # limitations on reuse of this extract, so they are merged rather than
    # mapped to separate properties that do not exist.
    limitations = join_parts(
        f"Targeted population: {card['population']}"
        if card.get("population")
        else None,
        f"Cautioned out-of-scope settings and uses: {card['outOfScope']}"
        if card.get("outOfScope")
        else None,
        f"Known risks and limitations: {card['risks']}" if card.get("risks") else None,
    )
    if limitations:
        doc["rai:dataLimitations"] = limitations

    if card.get("intendedUse"):
        doc["rai:dataUseCases"] = card["intendedUse"]
    social = join_parts(
        f"Clinical risk level: {card['riskLevel']}" if card.get("riskLevel") else None,
        card.get("biases"),
    )
    if social:
        doc["rai:dataSocialImpact"] = social

    # ---- the model this data supports ------------------------------------
    about: dict[str, Any] = {"@type": "sc:SoftwareApplication", "name": solution}
    if card.get("summary"):
        about["description"] = card["summary"]
    if card.get("version"):
        about["softwareVersion"] = card["version"]
    if card.get("modelType"):
        about["applicationCategory"] = card["modelType"]
    if card.get("developer") or meta.get("developer"):
        about["author"] = {
            "@type": "sc:Organization",
            "name": nonempty(card.get("developer"), meta.get("developer")),
        }
    doc["about"] = about

    # ---- the governance record itself ------------------------------------
    doc["isBasedOn"] = {
        "@type": "sc:CreativeWork",
        "name": f"CHAI governance review: {solution}",
        "conformsTo": export.get("schema", "chai-review/2"),
        "description": (
            "Lifecycle checklist, checkpoint decisions and readiness scores. "
            "These have no Croissant representation and are referenced, not encoded."
        ),
    }

    # Four project-specific terms, in a namespace this project publishes.
    if export.get("phase"):
        doc["chai:lifecyclePhase"] = export["phase"]
    if export.get("status"):
        doc["chai:complianceStatus"] = export["status"]
    if meta.get("riskTier"):
        doc["chai:riskTier"] = meta["riskTier"]
    if export.get("next_review"):
        doc["chai:nextReviewDue"] = export["next_review"]

    if bio_draft:
        # Only terms this record can actually source. Nothing is inferred:
        # bio:clinicalStudyType, bio:deidentificationMethod and
        # bio:authenticatedAccess would all require guessing from free text, and
        # a wrong de-identification claim is a safety problem, not a cosmetic one.
        doc["bio:dataCategory"] = ["clinical"]
        if dev_data and include_cohort:
            doc["bio:cohortDescription"] = dev_data

    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("export", type=Path, help="project JSON export from the dashboard")
    ap.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    ap.add_argument(
        "--include-cohort-detail",
        action="store_true",
        help=(
            "publish the development-data characterization verbatim "
            "(may carry PHI risk)"
        ),
    )
    ap.add_argument(
        "--include-maintainer-names",
        action="store_true",
        help=(
            "publish the review team or clinical sponsor by name as the "
            "maintainer (personal data; the default is an organizational contact)"
        ),
    )
    ap.add_argument(
        "--profile",
        choices=["croissant", "biocroissant-draft"],
        default="croissant",
        help=(
            "croissant (default): Croissant 1.0 + RAI 1.0 only. "
            "biocroissant-draft: additionally emit provisional bio: terms whose "
            "context IRI does not yet resolve -- experimental"
        ),
    )
    ap.add_argument(
        "--base-url",
        default="https://example.org/datasets",
        help="base IRI for the dataset @id",
    )
    args = ap.parse_args(argv)

    try:
        export = json.loads(args.export.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.export}: {exc}", file=sys.stderr)
        return 1

    schema = export.get("schema")
    if schema != "chai-review/2":
        print(
            f"warning: expected schema 'chai-review/2', found {schema!r}; "
            "field names may not line up",
            file=sys.stderr,
        )

    bio_draft = args.profile == "biocroissant-draft"
    doc = build(
        export,
        include_cohort=args.include_cohort_detail,
        base_url=args.base_url,
        bio_draft=bio_draft,
        include_maintainer_names=args.include_maintainer_names,
    )
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)

    if bio_draft:
        print(
            "NOTE: biocroissant-draft profile. The bio: context IRI does not "
            "resolve yet, so these terms are provisional and may change when "
            "MLCommons publishes BioCroissant.",
            file=sys.stderr,
        )
    if args.include_maintainer_names:
        named = named_maintainers(export.get("meta") or {})
        print(
            "WARNING: personal data included: the maintainer names "
            f"{named!r}. A published record that names the people responsible "
            "for a clinical system links identified individuals to that system, "
            "its site and a time. Confirm they agree to be named before "
            "publishing.",
            file=sys.stderr,
        )
    if args.include_cohort_detail:
        print(
            "WARNING: cohort detail included. Check for small cells before "
            "publishing: combined with a named organization, this can be "
            "re-identifying.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
