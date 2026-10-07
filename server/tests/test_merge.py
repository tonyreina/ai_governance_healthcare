"""Deep-merge semantics.

The requirement is not "a deep merge" but "the same deep merge the browser
does". So the last test in this file runs the *actual* JavaScript from
``app/js/00-core/00-util.js`` under node and compares, case for case. If the
two ever disagree, a PATCH silently throws away work a user has done.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from app.merge import MAX_DEPTH, TooDeep, deep_merge, is_obj, merged

REPO_ROOT = Path(__file__).resolve().parents[2]
UTIL_JS = REPO_ROOT / "app" / "js" / "00-core" / "00-util.js"


# --- the three rules that are easy to get wrong -----------------------------


def test_nested_partial_preserves_siblings_at_every_level() -> None:
    """The shape the app actually sends."""
    document = {
        "meta": {"solution": "Sepsis alert", "org": "St Elsewhere"},
        "items": {
            "s4-1": {"status": "met", "evidence": "validation report"},
            "s4-2": {"status": "partial", "owner": "A. Reviewer", "due": "2026-03-01"},
        },
        "archived": False,
    }
    result = merged(document, {"items": {"s4-2": {"status": "met"}}})

    # The edited key changed...
    assert result["items"]["s4-2"]["status"] == "met"
    # ...its siblings inside that object survived...
    assert result["items"]["s4-2"]["owner"] == "A. Reviewer"
    assert result["items"]["s4-2"]["due"] == "2026-03-01"
    # ...its sibling one level up survived...
    assert result["items"]["s4-1"] == {
        "status": "met",
        "evidence": "validation report",
    }
    # ...and so did everything at the top level.
    assert result["meta"] == {"solution": "Sepsis alert", "org": "St Elsewhere"}
    assert result["archived"] is False


def test_arrays_replace_they_do_not_merge() -> None:
    """``Array.isArray`` excludes arrays from ``isObj``, so they overwrite.

    The app depends on this: editing one metric sends the whole ``metrics``
    array, and a merge that concatenated or index-merged would duplicate rows
    or resurrect deleted ones.
    """
    document = {"metrics": [{"name": "AUROC", "value": "0.81"}, {"name": "TPR gap"}]}
    result = merged(document, {"metrics": [{"name": "AUROC", "value": "0.88"}]})
    assert result["metrics"] == [{"name": "AUROC", "value": "0.88"}]
    assert len(result["metrics"]) == 1


def test_array_replaces_an_object_and_an_object_replaces_an_array() -> None:
    assert merged({"a": {"x": 1}}, {"a": [1, 2]}) == {"a": [1, 2]}
    assert merged({"a": [1, 2]}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_null_replaces_rather_than_recursing() -> None:
    """``isObj(null)`` is falsy in JS because of the leading ``v &&``."""
    assert merged({"gates": {"A": {"signedBy": "u1"}}}, {"gates": {"A": None}}) == {
        "gates": {"A": None}
    }


def test_scalar_and_object_type_changes_replace() -> None:
    assert merged({"a": 1}, {"a": {"b": 2}}) == {"a": {"b": 2}}
    assert merged({"a": {"b": 2}}, {"a": 1}) == {"a": 1}
    assert merged({"a": "text"}, {"a": False}) == {"a": False}


def test_a_patch_cannot_delete_a_key_only_null_it() -> None:
    """Keys absent from the patch are never touched."""
    assert merged({"a": 1, "b": 2}, {"a": 9}) == {"a": 9, "b": 2}


def test_empty_patch_is_a_no_op() -> None:
    assert merged({"a": {"b": 1}}, {}) == {"a": {"b": 1}}


def test_new_keys_are_added_at_any_depth() -> None:
    assert merged({"items": {}}, {"items": {"s1-1": {"status": "met"}}}) == {
        "items": {"s1-1": {"status": "met"}}
    }


def test_result_does_not_alias_the_patch() -> None:
    """A later mutation of the patch must not reach into the stored document.

    ``clone()`` in the JS does this with JSON round-tripping; here it is
    ``copy.deepcopy``. Without it, the document and the request body would
    share a nested dict and a second request could mutate the first's result.
    """
    patch = {"items": {"s1-1": {"status": "met"}}}
    result = merged({}, patch)
    patch["items"]["s1-1"]["status"] = "notmet"
    assert result["items"]["s1-1"]["status"] == "met"


def test_deep_merge_mutates_and_returns_the_target() -> None:
    target = {"a": {"b": 1}}
    returned = deep_merge(target, {"a": {"c": 2}})
    assert returned is target
    assert target == {"a": {"b": 1, "c": 2}}


@pytest.mark.parametrize(
    "value,expected",
    [
        ({}, True),
        ({"a": 1}, True),
        ([], False),
        ([1], False),
        (None, False),
        ("", False),
        ("text", False),
        (0, False),
        (1, False),
        (True, False),
        (1.5, False),
    ],
)
def test_is_obj_matches_the_js_predicate(value: object, expected: bool) -> None:
    assert is_obj(value) is expected


# --- parity with the real JavaScript ----------------------------------------

PARITY_CASES: list[tuple[dict, dict]] = [
    (
        {"items": {"s4-1": {"status": "met"}, "s4-2": {"owner": "A"}}},
        {"items": {"s4-2": {"status": "met"}}},
    ),
    ({"metrics": [1, 2, 3]}, {"metrics": [4]}),
    ({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"c": 9}}}),
    ({"a": {"b": 1}}, {"a": None}),
    ({"a": None}, {"a": {"b": 1}}),
    ({"a": [1, 2]}, {"a": {"b": 1}}),
    ({"a": {"b": 1}}, {"a": [1, 2]}),
    ({"a": 1}, {"a": {"b": 2}}),
    ({"a": {"b": 2}}, {"a": 1}),
    ({"a": True}, {"a": False}),
    ({}, {"a": {"b": {"c": {"d": 1}}}}),
    ({"a": {"b": {"c": {"d": 1}}}}, {}),
    ({"a": {"b": 1}, "z": "keep"}, {"a": {"c": 2}}),
    (
        {"gates": {"A": {"decision": "go", "by": "u1"}}},
        {"gates": {"A": {"decision": "no-go"}, "B": {"decision": "go"}}},
    ),
    ({"a": ""}, {"a": 0}),
    ({"a": {"b": []}}, {"a": {"b": [{"x": 1}]}}),
]

JS_RUNNER = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
// new Function, not eval: `const` declared inside eval is scoped to the eval
// and would not be visible afterwards. A Function body keeps the bindings and
// the closure, so deepMerge still sees clone() and isObj().
const deepMerge = new Function(src + "\nreturn deepMerge;")();
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
process.stdout.write(JSON.stringify(cases.map(([t, s]) => deepMerge(t, s))));
"""


@pytest.mark.skipif(
    shutil.which("node") is None and not os.getenv("REQUIRE_TESTS"),
    reason="node is not installed",
)
@pytest.mark.skipif(not UTIL_JS.exists(), reason=f"{UTIL_JS} not found")
def test_parity_with_the_browsers_deepmerge(tmp_path: Path) -> None:
    """Run the app's own ``deepMerge`` and demand identical output.

    This is the test that makes "mirror it exactly" checkable rather than
    aspirational. If someone edits the JavaScript, this fails.
    """
    runner = tmp_path / "runner.js"
    runner.write_text(JS_RUNNER, encoding="utf-8")
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(PARITY_CASES), encoding="utf-8")

    completed = subprocess.run(
        ["node", str(runner), str(UTIL_JS), str(cases_file)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    from_js = json.loads(completed.stdout)
    from_py = [merged(target, patch) for target, patch in PARITY_CASES]

    assert len(from_js) == len(PARITY_CASES)
    for index, (js_result, py_result) in enumerate(zip(from_js, from_py, strict=True)):
        assert py_result == js_result, (
            f"case {index} diverged\n"
            f"  target: {PARITY_CASES[index][0]}\n"
            f"  patch:  {PARITY_CASES[index][1]}\n"
            f"  python: {py_result}\n"
            f"  js:     {js_result}"
        )


class TestDepthBound:
    """A bound, so a pathological patch is a 400 rather than a 500.

    Python's JSON parser rejects most deeply-nested payloads first, so this is
    a backstop. It matters because a RecursionError surfaces as an unhandled
    500 on a write that looked ordinary, and because _canonical() runs AFTER
    the caller has been told the write was accepted.
    """

    def test_a_reasonable_depth_is_fine(self) -> None:
        patch: dict = {}
        node = patch
        for _ in range(MAX_DEPTH - 2):
            node["n"] = {}
            node = node["n"]
        node["leaf"] = 1
        assert merged({}, patch)

    def test_past_the_bound_raises_rather_than_recursing(self) -> None:
        patch: dict = {}
        node = patch
        for _ in range(MAX_DEPTH + 10):
            node["n"] = {}
            node = node["n"]
        base = json.loads(json.dumps(patch))  # both sides objects, so it recurses
        with pytest.raises(TooDeep):
            merged(base, patch)

    def test_the_error_names_the_limit(self) -> None:
        patch: dict = {}
        node = patch
        for _ in range(MAX_DEPTH + 10):
            node["n"] = {}
            node = node["n"]
        base = json.loads(json.dumps(patch))
        with pytest.raises(TooDeep, match=str(MAX_DEPTH)):
            merged(base, patch)
