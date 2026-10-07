"""Who signed a checkpoint, and when, is decided by the server.

``gates.<key>.signedBy`` and ``signedAt`` used to arrive from the browser and go
into the stored document untouched. Any writer could record a decision as the
CMO, on any date (#31), while the deployment guide told reviewers that "the
identity attached to it was asserted by the organization's IdP, not chosen by
whoever was at the keyboard".

The same rule is already applied to the audit log: ``append_log`` overwrites
``at`` and ``by`` with the server clock and the proxy identity, because an audit
log whose author and timestamp come from the client is not an audit log. A
sign-off is an attestation, so it gets the same treatment.

What the rule is, per gate in a patch:

* **A decision is set or changed.** The server writes ``signedBy`` and
  ``signedAt`` from the caller and the clock, whatever the client sent. This is
  what makes attribution correct when somebody changes a decision without sending
  any attribution at all.
* **A decision is cleared.** Attribution is cleared with it. An empty decision
  cannot carry a signature.
* **The decision is unchanged.** Whatever attribution the client sent is dropped,
  so the stored attribution stands. Crucially this is a no-op, not an error: the
  browser may re-send a whole gate, and a 403 here would be read by the app as
  "your access changed" and put the user into read-only mode.
* **No decision key, attribution present** (recording a periodic review). If a
  decision stands and the values differ from what is stored, the reviewer is the
  caller; otherwise the attribution is dropped. So attribution cannot be
  blanked, forged, or planted where there is nothing to attribute.

Only ``signedBy`` and ``signedAt`` are the server's. ``by`` (the name of the
body that decided), ``date`` and ``rationale`` are the committee's own words and
stay as sent.

With identity disabled (``REQUIRE_IDENTITY=false``) there is nobody to attribute
to, so nothing is rewritten and the value stays self-asserted, which
``/api/health`` reports rather than hides. This is the same carve-out
``access.py`` makes.

Pure: no I/O, no clock. The caller passes the time in, so the rule is testable
without a database or a patched ``datetime``.
"""

from __future__ import annotations

import copy
from typing import Any

GATES = "gates"
DECISION = "decision"
SIGNED_BY = "signedBy"
SIGNED_AT = "signedAt"
ATTRIBUTION = (SIGNED_BY, SIGNED_AT)


def _attributed(gate: dict[str, Any], actor: str, now: str) -> None:
    gate[SIGNED_BY] = actor
    gate[SIGNED_AT] = now


def _unattributed(gate: dict[str, Any]) -> None:
    gate[SIGNED_BY] = None
    gate[SIGNED_AT] = None


def _dropped(gate: dict[str, Any]) -> None:
    for field in ATTRIBUTION:
        gate.pop(field, None)


def _one_gate(
    gate: dict[str, Any], stored: dict[str, Any], actor: str, now: str
) -> None:
    stored_decision = stored.get(DECISION)

    if DECISION in gate:
        decision = gate[DECISION]
        if not decision:
            _unattributed(gate)
        elif decision != stored_decision:
            _attributed(gate, actor, now)
        else:
            _dropped(gate)
        return

    claimed = {f: gate[f] for f in ATTRIBUTION if f in gate}
    if not claimed:
        return
    changed = any(v is not None and v != stored.get(f) for f, v in claimed.items())
    if changed and stored_decision:
        _attributed(gate, actor, now)
    else:
        _dropped(gate)


def attribute_signoffs(
    patch: dict[str, Any],
    before: dict[str, Any] | None,
    actor: str,
    now: str,
    *,
    enforced: bool,
) -> dict[str, Any]:
    """Return ``patch`` with every gate's attribution written by the server.

    ``before`` is the stored document, or ``None`` when a project is being
    created. ``actor`` is the authenticated identity and ``now`` an ISO-8601
    timestamp. The input is not modified.
    """
    gates = patch.get(GATES)
    if not enforced or not isinstance(gates, dict):
        return patch

    out = copy.deepcopy(patch)
    stored_gates = (before or {}).get(GATES)
    stored_gates = stored_gates if isinstance(stored_gates, dict) else {}
    for key, gate in out[GATES].items():
        if not isinstance(gate, dict):
            continue
        stored = stored_gates.get(key)
        _one_gate(gate, stored if isinstance(stored, dict) else {}, actor, now)
    return out
