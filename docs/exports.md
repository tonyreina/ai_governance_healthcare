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
