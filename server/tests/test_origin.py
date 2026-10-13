"""Unit tests for the same-site Origin comparison (D-102). No I/O."""

from __future__ import annotations

import pytest
from app.origin import origin_is_own


@pytest.mark.parametrize(
    ("origin", "host", "allowed"),
    [
        ("https://gov.example", "gov.example", []),
        ("http://gov.example", "gov.example", []),  # the scheme is not compared
        ("HTTPS://GOV.EXAMPLE", "gov.example", []),
        ("https://gov.example:443", "gov.example", []),
        ("http://localhost:8080", "localhost:8080", []),
        ("https://[::1]:8443", "[::1]:8443", []),
        ("https://app.example", "api.internal", ["https://app.example"]),
        ("https://app.example", "api.internal", ["https://APP.example:443"]),
    ],
)
def test_an_origin_that_is_ours(origin: str, host: str, allowed: list[str]) -> None:
    assert origin_is_own(origin, host, allowed)


@pytest.mark.parametrize(
    ("origin", "host", "allowed"),
    [
        ("https://evil.example", "gov.example", []),
        ("https://gov.example.evil.example", "gov.example", []),
        ("https://evil.example", "gov.example", ["https://app.example"]),
        ("http://localhost:9999", "localhost:8080", []),
        ("https://gov.example:8443", "gov.example", []),
        ("null", "gov.example", []),
        ("", "gov.example", []),
        ("gov.example", "gov.example", []),  # no scheme
        ("ftp://gov.example", "gov.example", []),
        ("https://gov.example/", "gov.example", []),  # an origin has no path
        ("https://gov.example/x", "gov.example", []),
        ("https://gov.example?x=1", "gov.example", []),
        ("https://user@gov.example", "gov.example", []),
        ("https://gov.example", "", []),  # no Host to compare with
        ("https://gov.example", "gov.example/x", []),
        ("https://gov.example", "user@gov.example", []),
        ("https://gov.example:notaport", "gov.example", []),
    ],
)
def test_an_origin_that_is_not(origin: str, host: str, allowed: list[str]) -> None:
    assert not origin_is_own(origin, host, allowed)
