"""Retention: litigation holds and disposal at the end of the period (#57).

The rules live in SQL (``migrations/008_retention.sql``), because the database
enforces them whoever is connected: ``retention_due()`` says what is past its
period, ``dispose_due()`` disposes of it, and the read trail's trigger refuses to
lose a row that is not. This module names the values Python shares with that file.
"""

from __future__ import annotations

from enum import StrEnum


class HoldAction(StrEnum):
    """A row in ``retention_hold``. The CHECK constraint lists the same values, and
    ``tests/test_retention.py`` fails if the two drift."""

    PLACE = "place"
    LIFT = "lift"


# Who a disposal names as having purged and deleted a record: not a person, the
# schedule. The person who ran it is in disposal_run.run_by.
SYSTEM_ACTOR = "system:retention"
