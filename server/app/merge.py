"""Deep merge, mirroring ``deepMerge()`` in ``app/js/00-core/00-util.js``.

The browser sends nested partials and expects sibling keys preserved at every
level::

    {"items": {"s4-2": {"status": "met"}}}

must leave ``items["s4-1"]`` and ``items["s4-2"]["evidence"]`` alone.

The JavaScript original is::

    const isObj = v => v && typeof v==="object" && !Array.isArray(v);
    function deepMerge(t, src){
      for (const k in src){
        if (isObj(src[k]) && isObj(t[k])) deepMerge(t[k], src[k]);
        else t[k] = clone(src[k]);
      }
      return t;
    }

Three consequences of that definition are easy to get wrong, so they are
spelled out here and pinned by ``tests/test_merge.py``:

1. **Arrays replace, they do not merge.** ``Array.isArray`` excludes arrays
   from ``isObj``, so an array in the patch overwrites whatever is at that key.
   The app relies on this: editing one metric sends the whole ``metrics``
   array.
2. **``null`` replaces.** ``isObj(null)`` is falsy in JavaScript because of the
   leading ``v &&``, so a null in the patch clears the key rather than
   recursing into it.
3. **A type change replaces.** Merging only happens when *both* sides are
   objects. Object-over-array, object-over-scalar and scalar-over-object all
   overwrite.

Keys absent from the patch are never touched, so a patch can never delete a
key -- it can only set it to null.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = ["deep_merge", "is_obj", "merged"]


def is_obj(value: Any) -> bool:
    """Mirror of ``isObj()``: a JSON object, never an array, never ``null``.

    ``isinstance(value, dict)`` is the exact Python counterpart: JSON arrays
    decode to ``list``, JSON ``null`` decodes to ``None``, and neither is a
    ``dict``.
    """
    return isinstance(value, dict)


def deep_merge(target: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Merge ``src`` into ``target`` in place and return ``target``.

    Recurses only where both sides are objects; everything else is replaced
    with a deep copy, so the result never aliases ``src``.
    """
    for key, value in src.items():
        if is_obj(value) and is_obj(target.get(key)):
            deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def merged(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Non-mutating :func:`deep_merge`: returns a new document."""
    return deep_merge(copy.deepcopy(base), patch)
