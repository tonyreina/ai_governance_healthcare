"""CHAI governance review API.

A small FastAPI service that implements the six-method store contract the
browser app uses (``subscribeAll``, ``create``, ``update``, ``remove``,
``log``, ``subscribeLog``) over REST plus Server-Sent Events, backed by
PostgreSQL.

Identity comes from a reverse proxy in front of the service. See
``app/auth.py`` and ``docs/deploying.md`` in the repository root.
"""

__version__ = "0.1.0"
