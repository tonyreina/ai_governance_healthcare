"""Find the cohorts a model fails worst on, and record them as metric rows.

Both frameworks ask you to compare performance across subgroups -- CHAI s4-2,
OPTICA 7.2 -- and CHAI s2-3 asks you to pre-specify which subgroups those are.
That ordering has a blind spot: a pre-specified list can only surface
disparities somebody already suspected. The subgroup nobody thought of is
exactly the one that reaches a checkpoint unexamined.

This searches for them instead. It fits a shallow decision tree to the model's
ERRORS rather than its labels, so the tree's leaves are descriptions of where
the model goes wrong, stated as readable conditions over the features you
supplied. Leaves whose error rate is materially worse than the overall rate
become metric rows, carrying the cohort definition in the population field.

The approach is the one Microsoft's Responsible AI Toolbox calls Error
Analysis. It is reimplemented here in about a hundred lines on scikit-learn
rather than taken as a dependency: `responsibleai` has not shipped since July
2024 and pins `pandas<2.0` and `numpy<=1.26`, which would drag this project's
toolchain backwards. The method is worth having; the packaging is not.

What this is NOT: it does not prove a disparity is unfair, or causal, or
actionable. A cohort found this way is a lead to investigate and, if it holds
up, a thing to disclose -- not a finding to paste into a model card unexamined.
Small leaves are especially prone to noise, which is why `min_cohort` exists
and why every row records its size.

Example:
    import pandas as pd
    from error_cohorts_to_metrics import error_cohorts, cohorts_to_rows
    from fairlearn_to_metrics import load, add_metrics, save

    errors = (y_pred != y_test)                 # or any per-row error measure
    cohorts = error_cohorts(X_test, errors, max_depth=3, min_cohort=50)

    export = load("deterioration-index-chai-review.json")
    add_metrics(export, cohorts_to_rows(cohorts))
    save(export, "deterioration-index-with-cohorts.json")

Requires: scikit-learn, pandas, numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SAFETY = "Safety & reliability"


@dataclass
class Cohort:
    """One leaf of the error tree: a slice of the data and how it fared."""

    conditions: list[str] = field(default_factory=list)
    size: int = 0
    errors: int = 0
    error_rate: float = 0.0
    overall_rate: float = 0.0

    @property
    def label(self) -> str:
        return " and ".join(self.conditions) if self.conditions else "All rows"

    @property
    def lift(self) -> float:
        """How many times the overall error rate this cohort runs at."""
        return self.error_rate / self.overall_rate if self.overall_rate else 0.0


def error_cohorts(
    X,
    errors,
    *,
    max_depth: int = 3,
    min_cohort: int = 50,
    min_lift: float = 1.25,
    feature_names: list[str] | None = None,
) -> list[Cohort]:
    """Return cohorts whose error rate is at least `min_lift` times the overall.

    Args:
        X: feature table (DataFrame or 2-D array) for the evaluation set.
        errors: per-row error indicator -- a boolean Series/array where True
            means the model got that row wrong. Any 0/1 measure works.
        max_depth: tree depth, and so the maximum number of conditions used to
            describe a cohort. Past 3 or 4 the descriptions stop being
            something you can put in front of a governance committee.
        min_cohort: smallest cohort to report. The single most important knob:
            a leaf of 7 rows with a 100% error rate is noise, and reporting it
            as a finding is worse than not looking.
        min_lift: how much worse than overall a cohort must be to be worth
            reporting.
        feature_names: column names, if X is not a DataFrame.

    Returns:
        Cohorts sorted worst-first. Empty if nothing clears the thresholds,
        which is a real and reportable result.
    """
    import numpy as np
    from sklearn.tree import DecisionTreeClassifier

    if hasattr(X, "columns"):
        names = list(X.columns)
        values = X.to_numpy()
    else:
        values = np.asarray(X)
        names = feature_names or [f"feature_{i}" for i in range(values.shape[1])]

    y = np.asarray(errors).astype(int).ravel()
    if y.shape[0] != values.shape[0]:
        raise ValueError(f"errors has {y.shape[0]} rows but X has {values.shape[0]}")
    if not y.any():
        return []  # no errors at all; nothing to explain

    overall = float(y.mean())

    # Fitting the tree to the ERRORS is the whole trick: its splits are then
    # chosen to separate wrong predictions from right ones, so each leaf is a
    # statement about where the model fails rather than about the outcome.
    tree = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_leaf=max(min_cohort, 1),
        random_state=0,
    ).fit(values, y)

    t = tree.tree_
    found: list[Cohort] = []

    def walk(node: int, conditions: list[str]) -> None:
        if t.children_left[node] == -1:  # leaf
            # `tree_.value` holds class PROPORTIONS, not counts: scikit-learn
            # normalizes it per node (confirmed on 1.9 -- a node of 5 samples
            # reports [[0.2, 0.8]], summing to 1.0). Reading it as counts makes
            # every cohort look like one row, so none clears min_cohort and the
            # search silently returns nothing. Sizes come from n_node_samples.
            size = int(t.n_node_samples[node])
            proportions = t.value[node][0]
            share_wrong = float(proportions[1]) if len(proportions) > 1 else 0.0
            wrong = round(share_wrong * size)
            rate = share_wrong
            if size >= min_cohort and overall and rate / overall >= min_lift:
                found.append(
                    Cohort(
                        conditions=list(conditions),
                        size=size,
                        errors=wrong,
                        error_rate=rate,
                        overall_rate=overall,
                    )
                )
            return

        name = names[t.feature[node]]
        threshold = t.threshold[node]
        walk(t.children_left[node], [*conditions, f"{name} <= {threshold:.4g}"])
        walk(t.children_right[node], [*conditions, f"{name} > {threshold:.4g}"])

    walk(0, [])
    found.sort(key=lambda c: c.error_rate, reverse=True)
    return found


def cohorts_to_rows(
    cohorts: list[Cohort], *, category: str = SAFETY, limit: int = 10
) -> list[dict]:
    """Turn cohorts into metric rows for the governance record.

    Filed under Safety & reliability rather than Fairness: a high-error cohort
    is a reliability finding until someone establishes it tracks a protected
    characteristic. Calling it unfairness before that is a conclusion the
    method cannot support. Move the row's category yourself once you know.
    """
    rows = []
    for cohort in cohorts[:limit]:
        rows.append(
            {
                "cat": category,
                "name": f"Error rate ({cohort.lift:.1f}x overall)",
                "value": f"{cohort.error_rate:.1%}",
                "ci": "",
                "pop": f"{cohort.label} (n={cohort.size:,})",
            }
        )
    if cohorts:
        rows.append(
            {
                "cat": category,
                "name": "Error rate",
                "value": f"{cohorts[0].overall_rate:.1%}",
                "ci": "",
                "pop": "Overall, evaluation set",
            }
        )
    return rows


def describe(cohorts: list[Cohort], limit: int = 10) -> str:
    """A short readable summary, for pasting into evidence or a report."""
    if not cohorts:
        return (
            "No cohort met the error-rate and minimum-size thresholds. That is "
            "a result worth recording: the search ran and found nothing, which "
            "is different from not having looked."
        )
    lines = [
        f"{len(cohorts)} cohort(s) with elevated error rates "
        f"(overall {cohorts[0].overall_rate:.1%}):",
        "",
    ]
    for cohort in cohorts[:limit]:
        lines.append(
            f"  {cohort.error_rate:6.1%}  ({cohort.lift:.1f}x, n={cohort.size:,})  "
            f"{cohort.label}"
        )
    lines += [
        "",
        "These are leads, not findings. Check each against clinical plausibility "
        "and cohort size before recording it as a known limitation.",
    ]
    return "\n".join(lines)
