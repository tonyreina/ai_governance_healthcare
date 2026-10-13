"""Is an ``Origin`` header this server's own? (D-102)

The cross-site check (``reject_cross_site_writes`` in ``main.py``) trusts
``Sec-Fetch-Site`` when a browser sends it. When it is absent, a state-changing
request must show an ``Origin`` that is the site the request was addressed to.

"Addressed to" is the ``Host`` header, which every proxy this project documents
passes through unchanged (Caddy's ``reverse_proxy``, Cloud Run, an ALB, Easy
Auth). ``X-Forwarded-Host`` is deliberately NOT read: a client sets it, and this
repository trusts no forwarded header for a security decision. (``X-Forwarded-Proto``
is read for HSTS only, which fails safe.) A deployment whose proxy rewrites
``Host`` lists the browser origin in ``CORS_ORIGINS``, which also counts.

The scheme is not compared. TLS ends at the proxy, so the scheme the API sees is
not the browser's, and a page on another scheme but the same host and port is not
a different site in the sense that matters here (a cross-site page differs in
host). The port is compared, with the scheme's default filled in on both sides.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_parts(origin: str) -> tuple[str, str, int] | None:
    """``(scheme, host, port)`` of a serialized origin, or None if it is not one.

    An origin is ``scheme://host[:port]`` and nothing else: ``null``, an empty
    string, userinfo, a path, a query or a fragment all make it None."""
    try:
        parts = urlsplit(origin.strip())
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORTS:
        return None
    if parts.path or parts.query or parts.fragment or "@" in parts.netloc:
        return None
    if not host:
        return None
    return parts.scheme, host.lower(), port or _DEFAULT_PORTS[parts.scheme]


def origin_is_own(origin: str, host_header: str, allowed: list[str]) -> bool:
    """Whether ``origin`` is the site ``host_header`` names, or one of ``allowed``."""
    mine = _origin_parts(origin)
    if mine is None:
        return False
    scheme, host, port = mine
    if any(_origin_parts(candidate) == mine for candidate in allowed):
        return True
    # The Host header has no scheme: parse it as if it had the origin's.
    if not host_header or "@" in host_header or "/" in host_header:
        return False
    own = _origin_parts(f"{scheme}://{host_header.strip()}")
    return own is not None and own[1:] == (host, port)
