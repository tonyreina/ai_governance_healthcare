"""DSN encryption warnings.

asyncpg's default sslmode is "prefer": it tries TLS and silently accepts
cleartext if the server does not offer it. On an internal bridge that is fine;
the same string edited to point at a managed instance is 164.312(e)(1).
"""

from __future__ import annotations

import pytest
from app.db import check_dsn_encryption, normalize_dsn

LOCAL = [
    "postgresql://chai:pw@localhost:5432/chai",
    "postgresql://chai:pw@127.0.0.1:5432/chai",
    "postgresql://chai@/chai?host=/cloudsql/proj:region:inst",
]

REMOTE_WEAK = [
    "postgresql://chai:pw@db.example.org:5432/chai",
    "postgresql://chai:pw@db.example.org:5432/chai?sslmode=prefer",
    "postgresql://chai:pw@db.example.org:5432/chai?sslmode=disable",
    "postgresql://chai:pw@db.example.org:5432/chai?sslmode=allow",
]


@pytest.mark.parametrize("dsn", LOCAL)
def test_a_local_or_socket_dsn_is_not_flagged(dsn: str) -> None:
    assert check_dsn_encryption(dsn) is None


@pytest.mark.parametrize("dsn", REMOTE_WEAK)
def test_a_remote_dsn_without_real_tls_is_flagged(dsn: str) -> None:
    warning = check_dsn_encryption(dsn)
    assert warning and "UNENCRYPTED" in warning


def test_require_is_flagged_as_unverified() -> None:
    warning = check_dsn_encryption(
        "postgresql://chai:pw@db.example.org/chai?sslmode=require"
    )
    assert warning and "verify-full" in warning


@pytest.mark.parametrize("mode", ["verify-full", "verify-ca"])
def test_a_verified_dsn_is_accepted(mode: str) -> None:
    assert (
        check_dsn_encryption(f"postgresql://chai:pw@db.example.org/chai?sslmode={mode}")
        is None
    )


@pytest.mark.parametrize("host", ["db", "postgres", "pg-primary"])
def test_a_container_network_name_is_not_flagged(host: str) -> None:
    """A single-label host resolves only on an internal network.

    Warning about the default compose stack on every boot would train
    operators to ignore the warning, and the warning exists for the moment
    somebody repoints that DSN at a managed instance -- which always has a
    fully qualified name.
    """
    dsn = normalize_dsn(f"postgres://chai:pw@{host}:5432/chai")
    assert check_dsn_encryption(dsn) is None


def test_a_managed_instance_hostname_is_flagged() -> None:
    for host in (
        "mydb.abc123.us-east-1.rds.amazonaws.com",
        "mydb.postgres.database.azure.com",
        "10.20.30.40",
    ):
        warning = check_dsn_encryption(f"postgresql://chai:pw@{host}:5432/chai")
        assert warning and "UNENCRYPTED" in warning, host
