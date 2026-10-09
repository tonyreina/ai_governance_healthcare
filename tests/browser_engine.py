"""Which browser engine a Playwright suite drives (#160).

Chromium by default. `TEST_BROWSER=firefox` or `webkit` runs the same suite in
that engine. Escaping is the same everywhere, but the page's own policy (a meta
Content-Security-Policy naming the script by hash) is enforced by each engine's
own implementation, and a hospital's workstations are not all Chromium.

An unknown name is an error, not a fallback to Chromium: a typo in a CI matrix
would otherwise run the Chromium suite twice and call it cross-browser.
"""

from __future__ import annotations

import os

ENGINES = ("chromium", "firefox", "webkit")


def engine_name() -> str:
    name = os.environ.get("TEST_BROWSER", "chromium").strip().lower()
    if name not in ENGINES:
        raise SystemExit(f"TEST_BROWSER={name!r}: expected one of {ENGINES}")
    return name


def launch(pw):
    """Launch the chosen engine, and say which one, so a log shows what ran."""
    name = engine_name()
    print(f"[browser: {name}]")
    return getattr(pw, name).launch()
