# Working with exports in Python

Each project exports as JSON, validated by
[`schema/project.schema.json`](https://github.com/tonyreina/ai_governance_healthcare/blob/main/schema/project.schema.json).

## Reading an export

```bash
python examples/load_export.py my-project-chai-review.json
```

## Feeding evaluation metrics back in

`examples/fairlearn_to_metrics.py` takes a Fairlearn `MetricFrame` and appends
its subgroup results to an export's key metrics, so evaluation output flows
straight into the model card:

```bash
python examples/fairlearn_to_metrics.py my-project-chai-review.json
```

Re-import the resulting file from the dashboard with **Import project JSON**.

!!! note "Import creates a new project"

    Importing does not merge into the project the file came from — it creates a
    separate one. Retire or delete the original if you meant to replace it.

## PDF

The report screen has a **Download PDF** button. It opens your browser's print
dialog on the standalone report; choose *Save as PDF*.

!!! note "Why the print dialog rather than a one-click download"

    No PDF library is bundled. Every option weighs hundreds of kilobytes, and
    the dashboard has to stay one self-contained file small enough to publish
    as an artifact — a PDF writer would be larger than the whole application.

    Browsers already render HTML to PDF well, with real fonts, selectable text
    and working links. A canvas-based library gives you an image of a document
    instead.

What gets printed is exactly the standalone HTML export, rendered in an
offscreen frame — not the page you are looking at. So the PDF and the HTML
download are the same document, and the app's own navigation never appears in
it.

This is also the one export that keeps working where file downloads are
unavailable, since it goes through the print dialog rather than a download API.

## Croissant

`examples/croissant_export.py` converts a project export into
[Croissant](https://docs.mlcommons.org/croissant/) 1.0 metadata with the
[Responsible AI extension](https://github.com/mlcommons/croissant/blob/main/docs/croissant-rai-spec.md),
so a governance record can be published as machine-readable dataset metadata.

```bash
python examples/croissant_export.py my-project-chai-review.json -o dataset.jsonld
```

The output validates against `mlcroissant`.

### What it describes, and what it refuses to

Croissant describes a **dataset**. A governance record describes a **model** and
an **organizational process**. The exporter keeps that distinction rather than
blurring it:

- `name` and `description` describe the *development and validation data
  extract*.
- The solution itself is carried under `about` as an `sc:SoftwareApplication`.
- The governance record is linked via `isBasedOn`, not transcribed.
- Four governance facts are emitted in this project's own
  [`chai:` namespace](ns/index.md).

The checklist, the checkpoint decisions and the readiness scores are **not**
exported. Croissant has no vocabulary for assurance attestations, and
`sc:creativeWorkStatus` describes the editorial status of a work — not a
governance body's decision to expose patients to a model.

!!! warning "Cohort detail is withheld by default"

    `rai:dataCollection` carries cohort size, dates, sites and demographics by
    design, and Croissant files exist to be published and indexed. A small-cell
    cohort description attributed to a named organization can be re-identifying.

    Pass `--include-cohort-detail` to emit it. Check for small cells first.

### No fabricated structure

The exporter emits no `distribution` and no `recordSet`. A governance record
contains no file hashes, no content URLs and no column names, and synthesizing
them to satisfy a validator would manufacture provenance for clinical data the
tool has never seen. Croissant 1.0 accepts a metadata-only record.

For the same reason it asserts no `license` for the data — only `sdLicense` for
the metadata record. `mlcroissant` warns that `license` is recommended; that
warning is correct, and a human should answer it.

### BioCroissant

[BioCroissant](https://github.com/mlcommons/BioCroissant) is the biomedical
extension of Croissant. As of this writing its repository is a **skeleton** —
its own READMEs state "no schema files yet" and "no implementation yet".

A draft `bio:` vocabulary exists in the prototype its READMEs point to,
[biocroissant-to-omop](https://github.com/renato-umeton/biocroissant-to-omop),
which marks itself `PLACEHOLDER` because the context IRI
`https://mlcommons.org/croissant/bio/0.3/context` does not resolve.

```bash
python examples/croissant_export.py export.json --profile biocroissant-draft
```

This is **off by default and experimental**. Emitting terms under a prefix that
does not resolve is a real defect in published linked data, defensible only as a
labeled opt-in. The output carries a `_contextNote` saying so, and still
validates. `conformsTo` is an array from the start, so adopting BioCroissant
properly later means appending one string.
