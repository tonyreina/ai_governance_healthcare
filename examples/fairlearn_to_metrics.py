"""Append Fairlearn subgroup results to a project export's key metrics.

The updated file can be re-imported from the dashboard ("Import project JSON"),
which creates a new project carrying the metrics into its model card.

Example:
    from fairlearn.metrics import MetricFrame
    from sklearn.metrics import recall_score, roc_auc_score

    mf = MetricFrame(
        metrics={"Sensitivity": recall_score},
        y_true=y_test, y_pred=y_pred,
        sensitive_features=X_test[["age_band", "sex"]],
    )
    export = load("deterioration-index-chai-review.json")
    add_metrics(export, metricframe_to_rows(mf))
    save(export, "deterioration-index-with-fairness.json")

Requires: fairlearn, pandas.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

FAIRNESS = "Fairness & equity"
CATEGORIES = {"Usefulness, usability & efficacy", FAIRNESS, "Safety & reliability"}


def _group_label(group) -> str:
    if isinstance(group, tuple):
        return ", ".join(str(g) for g in group)
    return str(group)


def metricframe_to_rows(mf, category: str = FAIRNESS, digits: int = 3,
                        include_overall: bool = True) -> list[dict]:
    """Turn a fairlearn MetricFrame into metric rows for the tool."""
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {sorted(CATEGORIES)}")
    by_group = mf.by_group
    overall = mf.overall
    rows: list[dict] = []
    if hasattr(by_group, "columns"):  # several metrics -> DataFrame
        for metric in by_group.columns:
            if include_overall:
                rows.append(_row(category, metric, overall[metric], "Overall", digits))
            for group, value in by_group[metric].items():
                rows.append(_row(category, metric, value, _group_label(group), digits))
    else:  # one metric -> Series
        name = by_group.name or "Metric"
        if include_overall:
            rows.append(_row(category, name, overall, "Overall", digits))
        for group, value in by_group.items():
            rows.append(_row(category, name, value, _group_label(group), digits))
    return rows


def _row(cat: str, name, value, pop: str, digits: int) -> dict:
    try:
        text = f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        text = str(value)
    return {"cat": cat, "name": str(name), "value": text, "ci": "", "pop": pop}


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def add_metrics(export: dict, rows: Iterable[dict], replace_category: str | None = None) -> dict:
    """Append rows to the export. Optionally drop existing rows of one category first."""
    state = export["_state"]
    metrics = state.setdefault("metrics", [])
    if replace_category:
        metrics[:] = [m for m in metrics if m.get("cat") != replace_category]
    metrics.extend(rows)
    export["metrics"] = metrics
    return export


def save(export: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(export, indent=2), encoding="utf-8")
