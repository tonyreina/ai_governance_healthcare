#!/usr/bin/env python3
"""The dashboard and its exports must not contact a third party.

This is a tool whose subject is where regulated data goes, run on networks that
often filter egress. A webfont link meant every page load -- and every open of
an exported report, which is the artifact that gets emailed around a hospital
-- announced itself to Google.

It is also what lets the Content-Security-Policy in proxy/Caddyfile be as
tight as it is.

    pixi run test-no-3p
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from test_boot_storage import serve, wait_until

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def external(urls: list[str]) -> list[str]:
    out = []
    for url in urls:
        scheme = urlsplit(url).scheme
        if scheme in ("http", "https"):
            out.append(url)
    return out


# What loads without a click: a stylesheet, script, image, font, frame or beacon. A
# link the reader chooses to follow (`<a href>`) is not a request the page makes, so it
# is allowed in an export (a report may link to the evidence it cites).
RESOURCE = re.compile(
    r"""(?:\bsrc\s*=|<link\b|@import|\burl\(|\bsrcset\s*=|\bposter\s*=|<object\b|<embed\b)"""
    r"""[^>]*?https?://""",
    re.I,
)


def resource_urls(text: str) -> list[str]:
    """Anything in an export that a viewer would fetch on its own."""
    return [m.group(0)[:80] for m in RESOURCE.finditer(text)]


# ---------------------------------------------------------------------------
# The server-backed page. The walk above runs the browser-only (file://) page. Every
# screen that exists only against a server is walked here: served from a local static
# server with a stand-in API on the same origin, the signed-in person a@b OWNING the
# project (R-75). What the page's own policy refuses (`connect-src` and `img-src` are
# 'self') may never reach a request listener, so a refused attempt is also recorded
# from the page's `securitypolicyviolation` events, from `requestfailed`, and from a
# catch-all route that fails anything not on the local origin.
# ---------------------------------------------------------------------------

ME = "a@b"
JSON_TYPE = "application/json"
PID, PID_READ = "p1", "p2"
AGENT_SECRET = "agt_0123456789abcdef." + "A" * 43
# A listener installed before the page's own script runs, in every frame. The binding
# is exposed on the context, so a violation inside the report frame is reported too.
CSP_LISTENER = """(() => {
  document.addEventListener('securitypolicyviolation', e => {
    try { window.__cspReport(e.violatedDirective + ' ' + e.blockedURI); } catch (_) {}
  }, true);
})()"""


@dataclass
class Observed:
    """What the server-backed walk saw leave, or try to leave, the origin."""

    external: list[str] = field(default_factory=list)  # a request to another host
    violations: list[str] = field(default_factory=list)  # the page's policy refused
    failed: list[str] = field(default_factory=list)  # a failed request to another host
    api: list[str] = field(default_factory=list)  # METHOD path sent to the stand-in
    reached: dict[str, bool] = field(default_factory=dict)  # screen name -> shown


def _is_web(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https", "ws", "wss")


def _project(pid: str, owners: list[str], readers: list[str]) -> dict:
    return {
        "id": pid,
        "meta": {"solution": f"Server project {pid}"},
        "access": {"owners": owners, "writers": [], "readers": readers},
    }


class StandInApi:
    """Enough of the API for every screen: projects, the audit log, a hold, versions,
    agent tokens, principals and the export record. Never reaches a database."""

    def __init__(self, rules: object) -> None:
        self.rules = rules
        self.history: list[dict] = []
        self.tokens: list[dict] = []
        self.agent_on = True
        self.deleted: set[str] = set()
        # An owner on p1 (the signed-in person), a reader on p2: R-75 says a project
        # always has an owner, and a reader's page is the read-only one.
        self.projects = {
            PID: _project(PID, [ME], ["r@b"]),
            PID_READ: _project(PID_READ, ["boss@b"], [ME]),
        }

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "t",
            "database": "up",
            "db_role": "restricted",
            "auth_mode": "proxy-header:proxy",
            "sign_out_url": "/signout",
            "idle_lock_minutes": 30,
            "retirement_rules": self.rules,
        }

    def handle(self, route, seen: list[str]) -> None:
        request = route.request
        path = urlsplit(request.url).path
        method = request.method
        seen.append(f"{method} {path}")

        def ok(body: object, status: int = 200, **extra) -> None:
            route.fulfill(
                status=status, body=json.dumps(body), content_type=JSON_TYPE, **extra
            )

        if path == "/api/events":
            return route.abort()
        if path == "/api/health":
            return ok(self.health())
        if path == "/api/me":
            return ok({"id": ME, "name": "A B", "email": ME, "dev": False})
        if path == "/api/projects":
            return ok([p for k, p in self.projects.items() if k not in self.deleted])
        if path == "/api/principals":
            return ok([{"id": ME, "name": "A B", "email": ME}])
        if path == "/api/exports":
            return ok({}, 201)
        if path.startswith("/api/agent-tokens"):
            return self._agent(route, method, ok)
        for pid in (PID, PID_READ):
            base = f"/api/projects/{pid}"
            if path == f"{base}/log" and method == "GET":
                rows = [
                    {
                        "at": f"2026-01-{1 + i % 28:02d}T09:{i % 60:02d}:00Z",
                        "text": f"Entry {i}",
                        "by": ME,
                        "hash": f"{i:040x}",
                        "change": {"path": f"stage1.item{i}"},
                    }
                    for i in range(60)
                ]
                return ok(rows, headers={"X-Log-Total": "412"})
            if path == f"{base}/hold":
                if method == "POST":
                    body = json.loads(request.post_data or "{}")
                    self.history.insert(
                        0, {"at": "2026-10-08T12:00:00+00:00", "by": ME, **body}
                    )
                held = bool(self.history) and self.history[0]["action"] == "place"
                return ok({"held": held, "history": self.history})
            if path == f"{base}/versions" and method == "DELETE":
                return route.fulfill(status=204, body="")
            if path == base and method == "DELETE":
                self.deleted.add(pid)
                return route.fulfill(status=204, body="")
            if path == base:
                return ok(self.projects[pid])
            if path.startswith(base):
                return ok({})
        return ok([])

    def _agent(self, route, method: str, ok) -> None:
        if not self.agent_on:
            return route.fulfill(status=404, body="{}", content_type=JSON_TYPE)
        if method == "POST":
            self.tokens.insert(0, self.token("0123456789abcdef", "ci agent"))
            return ok(
                {
                    "id": "0123456789abcdef",
                    "token": AGENT_SECRET,
                    "label": "ci agent",
                    "created_at": "2026-01-01T08:00:00Z",
                    "expires_at": "2099-01-01T16:00:00Z",
                },
                201,
                headers={"Cache-Control": "no-store"},
            )
        if method == "DELETE":
            for row in self.tokens:
                row["state"], row["revoked_at"] = "revoked", "2026-01-01T10:00:00Z"
            return route.fulfill(status=204, body="")
        return ok(self.tokens)

    @staticmethod
    def token(tid: str, label: str, state: str = "active") -> dict:
        return {
            "id": tid,
            "label": label,
            "created_at": "2026-01-01T08:00:00Z",
            "expires_at": "2099-01-01T16:00:00Z",
            "revoked_at": None,
            "last_used_at": None,
            "state": state,
        }


def server_walk(browser, url: str, rules: object) -> Observed:
    """Open every screen and dialog that exists only against a server, at `url`, and
    report what left (or tried to leave) the origin. Clicks no external link."""
    out = Observed()
    origin = urlsplit(url).netloc
    api = StandInApi(rules)
    api.tokens = [api.token("00000000000000aa", "old agent", "revoked")]
    ctx = browser.new_context(viewport={"width": 1300, "height": 1000})
    ctx.expose_function("__cspReport", lambda text: out.violations.append(text))
    ctx.add_init_script(CSP_LISTENER)

    def gate(route) -> None:
        # The catch-all: another host fails the walk and is refused here, whether or
        # not the page's own policy would also have stopped it.
        target = route.request.url
        if _is_web(target) and urlsplit(target).netloc != origin:
            out.external.append(target)
            return route.abort()
        if urlsplit(target).path.startswith("/api/"):
            return api.handle(route, out.api)
        return route.continue_()

    def on_request(r) -> None:
        if _is_web(r.url) and urlsplit(r.url).netloc != origin:
            out.external.append(r.url)

    def on_failed(r) -> None:
        if _is_web(r.url) and urlsplit(r.url).netloc != origin:
            out.failed.append(f"{r.url} {r.failure}")

    ctx.route("**/*", gate)
    ctx.on("request", on_request)
    ctx.on("requestfailed", on_failed)
    page = ctx.new_page()
    page.set_default_timeout(8000)
    page.goto(url)
    wait_until(page, "typeof LOADED !== 'undefined' && LOADED", 15)
    wait_until(page, "MODE === Mode.API", 15)
    wait_until(page, "PROJECTS && PROJECTS.size >= 2", 15)

    def reached(name: str, selector: str) -> None:
        out.reached[name] = page.locator(selector).count() > 0

    def view(pid: str, name: str) -> None:
        page.evaluate(f"openProject({pid!r}, {name!r})")
        page.wait_for_timeout(150)

    # The header, the standing server notice, the sign-out link, the rules banner.
    reached("sign-out link", "#signOut")
    reached("server scope notice", "#scopeNotice")
    reached("retirement-rules banner", "#rulesBanner")
    page.evaluate("UI.q = 'server'; UI.qAll = true; updateDashboard()")
    if page.locator('[data-act="dl-csv"]').count():
        page.click('[data-act="dl-csv"]')
    page.evaluate("goHome()")

    # The setup page of a project the person owns: access, hold, disposal, the log.
    view(PID, "setup")
    reached("access settings", "[data-grant-id]")
    page.fill("[data-grant-id]", "new@b")
    page.click('[data-act="grant"]')
    page.wait_for_timeout(200)
    reached("hold section", "#holdHost")
    page.wait_for_selector("[data-hold-action]")
    for action in ("place", "lift"):
        page.click(f'[data-hold-action="{action}"]')
        page.wait_for_selector(".modal")
        out.reached[f"hold {action} dialog"] = True
        if action == "place":
            page.fill("#holdReason", "Smith v. Hospital")
            page.click("[data-hold-go]")
            page.wait_for_timeout(300)
        else:
            page.click("[data-hold-cancel]")
    # The audit log (the version history the page shows) and its older entries.
    page.wait_for_timeout(300)  # the log arrives after the page opens
    page.evaluate("go('changelog')")
    page.wait_for_timeout(150)
    reached("version history (the log)", "ul.history")
    reached("older-entries control", '[data-act="log-older"]')
    if page.locator('[data-act="log-older"]').count():
        page.click('[data-act="log-older"]')
        page.wait_for_timeout(200)

    # Every view of the owned project and of the read-only one, then the exports.
    for pid in (PID, PID_READ):
        view(pid, "setup")
        page.evaluate("setFrameworkEnabled('optica', true)")
        for name in page.evaluate("activeViews().map(v => v.id)"):
            page.evaluate("(v) => go(v)", name)
            page.wait_for_timeout(15)
    out.reached["read-only project"] = bool(page.evaluate("RO"))
    view(PID, "report")
    for act in ("dl-html", "dl-md", "dl-json", "dl-pdf"):
        if page.locator(f'[data-act="{act}"]').count():
            page.click(f'[data-act="{act}"]')
            page.wait_for_timeout(250)
    page.evaluate("exportPDF()")
    page.wait_for_timeout(400)

    # Every language, on the report.
    for locale in page.evaluate("LOCALE_CHOICES"):
        page.evaluate("(l) => { setLocale(l); relocalize(); go('report'); }", locale)
        page.wait_for_timeout(20)
    page.evaluate("setLocale('en'); relocalize();")

    # The rules banner in each state it has.
    for sync in (False, True):
        page.evaluate(
            "(s) => checkRetirementRules({retirement_rules:"
            " {hash: BUILD.ruleSetHash, primary: BUILD.primary, synced: s}})",
            sync,
        )
        page.wait_for_timeout(120)
    page.evaluate("checkRetirementRules({retirement_rules: 'nonsense'})")
    page.wait_for_timeout(120)

    # Agent access: off, then on with a revoked token, a mint, the one-time reveal, a
    # revoke, and the page in every language.
    api.agent_on = False
    page.evaluate("goHome()")
    page.click('[data-act="agent-open"]')
    page.wait_for_selector("#agentPage")
    wait_until(page, "AGENT.load === AgentLoad.OFF", 10)
    reached("agent access (feature off)", "#agentOff:not([hidden])")
    api.agent_on = True
    page.evaluate("goHome()")
    page.click('[data-act="agent-open"]')
    wait_until(page, "AGENT.load === AgentLoad.READY", 10)
    reached("agent access (tokens)", "#agentList li")
    page.fill("#agentLabel", "ci agent")
    page.click("#agentCreate")
    page.wait_for_selector("#agentReveal")
    reached("agent token reveal", "#agentReveal")
    for locale in page.evaluate("LOCALE_CHOICES"):
        page.evaluate("(l) => { setLocale(l); relocalize(); }", locale)
    page.evaluate("setLocale('en'); relocalize();")
    if page.locator("#agentDone").count():
        page.click("#agentDone")
    revoke = page.locator("[data-token-id]")
    if revoke.count():
        revoke.first.click()
        page.wait_for_timeout(200)

    # The idle lock screen.
    page.evaluate("lockNow()")
    reached("idle-lock screen", "#lockScreen")
    page.evaluate(
        "document.getElementById('lockScreen').remove();"
        " document.body.classList.remove('locked')"
    )

    # Disposal: the delete dialog with its choice to destroy the history, to the end.
    view(PID, "setup")
    page.click('[data-act="delete"]')
    page.wait_for_selector(".modal")
    reached("delete dialog", "[data-del-go]")
    reached("purge-history choice", "#delPurge")
    page.keyboard.press("Escape")
    page.click('[data-act="delete"]')
    page.wait_for_selector(".modal")
    page.fill("#delName", f"Server project {PID}")
    page.check("#delPurge")
    page.click("[data-del-go]")
    page.wait_for_timeout(500)
    out.reached["purge and delete sent"] = (
        f"DELETE /api/projects/{PID}/versions" in out.api
        and f"DELETE /api/projects/{PID}" in out.api
    )
    page.wait_for_timeout(500)  # let a late violation report arrive
    ctx.close()
    return out


def mutated_copy(html: str, *, body: str = "", script: str = "") -> str:
    """The built page with something injected. A change to the script changes its
    hash, and a page whose script is refused would be noticed for that reason and not
    for the request, so the policy is re-pointed at the new hash: what the mutation
    does is then what is measured."""
    if body:
        anchor = '<div class="toast" id="toast"'
        html = html.replace(anchor, body + anchor, 1)
    if script:
        start = html.index("<script>") + len("<script>")
        end = html.index("</script>", start)
        old = html[start:end]
        new = script + old
        digest = base64.b64encode(hashlib.sha256(new.encode()).digest()).decode()
        old_digest = base64.b64encode(hashlib.sha256(old.encode()).digest()).decode()
        html = html[:start] + new + html[end:]
        html = html.replace(old_digest, digest, 1)
    return html


SERVER_SCREENS = (
    "sign-out link",
    "server scope notice",
    "retirement-rules banner",
    "access settings",
    "hold section",
    "hold place dialog",
    "hold lift dialog",
    "version history (the log)",
    "older-entries control",
    "read-only project",
    "agent access (feature off)",
    "agent access (tokens)",
    "agent token reveal",
    "idle-lock screen",
    "delete dialog",
    "purge-history choice",
    "purge and delete sent",
)
MISMATCHED_RULES = {"hash": "0" * 64, "primary": "chai", "synced": False}


def server_backed_checks(browser) -> None:
    print("The server-backed page: every screen that exists only against a server")
    with serve(APP.parent.parent) as base:
        seen = server_walk(browser, base + "/app/index.html", MISMATCHED_RULES)
    missing = [n for n in SERVER_SCREENS if not seen.reached.get(n)]
    check("every server-only screen was reached", not missing, ", ".join(missing))
    check(
        "the stand-in answered the screens' own requests",
        any(c.startswith("POST /api/projects/p1/hold") for c in seen.api)
        and any(c.startswith("GET /api/agent-tokens") for c in seen.api),
        str(seen.api[:5]),
    )
    check(
        "the server-backed page requests no other host (catch-all route)",
        not seen.external and not seen.failed,
        ", ".join((seen.external + seen.failed)[:3]),
    )
    check(
        "and its own policy refused nothing (no securitypolicyviolation)",
        not seen.violations,
        ", ".join(seen.violations[:3]),
    )

    print("The server-backed check notices what the policy blocks (mutation)")
    html = APP.read_text(encoding="utf-8")
    mutants = (
        (
            "an <img> to another host",
            "an <img> to another host is noticed although the policy blocks it",
            mutated_copy(html, body='<img src="https://example.invalid/x.png">'),
        ),
        (
            "a fetch() to another host",
            "a fetch() to another host is noticed although the policy blocks it",
            mutated_copy(
                html, script='fetch("https://example.invalid/").catch(() => {});\n'
            ),
        ),
    )
    for label, noticed, text in mutants:
        tmp = Path(tempfile.mkdtemp(prefix="chai-3p-mut-"))
        (tmp / "app").mkdir()
        (tmp / "app" / "index.html").write_text(text, encoding="utf-8")
        with serve(tmp) as base:
            seen = server_walk(browser, base + "/app/index.html", MISMATCHED_RULES)
        # The page's policy refuses both, so the policy's own report is what proves the
        # check can see them; the catch-all route sees one that still got out.
        check(
            noticed,
            bool(seen.violations) or bool(seen.external),
            f"violations={seen.violations[:2]} external={seen.external[:2]}",
        )
        check(
            f"{label}: the report names the blocked host",
            any("example.invalid" in v for v in seen.violations + seen.external),
            str(seen.violations[:3]),
        )
        check(
            f"{label}: the page still ran (the script was not refused instead)",
            seen.reached.get("hold section") is True,
        )


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        requested: list[str] = []
        page.on("request", lambda r: requested.append(r.url))

        page.goto(APP.as_uri())
        page.wait_for_timeout(1200)

        off_origin = external(requested)
        check(
            "loading the dashboard makes no external request",
            not off_origin,
            ", ".join(off_origin[:3]),
        )

        print("Every screen, dialog, language and export")
        walk = browser.new_page()
        seen: list[str] = []
        walk.on("request", lambda r: seen.append(r.url))
        walk.goto(APP.as_uri())
        walk.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        walk.evaluate("loadSamples()")
        walk.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        # A deployed, a piloted and an early project, each with OPTICA on, so every view
        # exists: the setup page, the six stages, the checkpoints, the model card, the
        # report, the change log and the OPTICA chapters.
        views_seen = 0
        for index in (0, 1, 2):
            walk.evaluate(f"openProject([...PROJECTS.keys()][{index}], 'setup')")
            walk.evaluate("setFrameworkEnabled('optica', true)")
            for view in walk.evaluate("activeViews().map(v => v.id)"):
                walk.evaluate("(v) => go(v)", view)
                walk.wait_for_timeout(15)
                views_seen += 1
            walk.evaluate(
                "renderLabel(); document.getElementById('panel').classList.add('open')"
            )
        check("every view was visited", views_seen > 60, str(views_seen))
        walk.evaluate("goHome()")
        walk.evaluate("UI.q = 'sepsis'; UI.qAll = true; updateDashboard()")
        walk.evaluate(
            "openProject([...PROJECTS.keys()][0], 'setup'); openDeleteDialog()"
        )
        walk.keyboard.press("Escape")
        # The picker in the header, and every language it offers.
        for locale in walk.evaluate("LOCALE_CHOICES"):
            walk.evaluate(
                "(l) => { setLocale(l); relocalize(); go('report'); }", locale
            )
            walk.wait_for_timeout(30)
        walk.evaluate("setLocale('en'); relocalize();")
        outputs = walk.evaluate(
            """() => ({
                html: exportHTML(), md: exportMD(), csv: exportCSV(),
                json: JSON.stringify(projectJSON(S)),
            })"""
        )
        # The PDF is the report loaded into a frame of the page: its requests count too.
        walk.evaluate("exportPDF()")
        walk.wait_for_timeout(500)
        # A tool the user can press that talks to nothing: import, search, add, archive.
        walk.evaluate("goHome()")
        walk.wait_for_timeout(200)
        offsite = external(seen)
        check(
            "no screen, dialog, language or export makes a request to another host",
            not offsite,
            ", ".join(offsite[:3]),
        )
        check(
            "and the page made no request at all once loaded, apart from its own file",
            all(urlsplit(u).scheme in ("file", "data", "blob", "about") for u in seen),
            ", ".join(
                u
                for u in seen
                if urlsplit(u).scheme not in ("file", "data", "blob", "about")
            )[:100],
        )

        print("What the exports would fetch when opened")
        for name in ("html", "md", "csv", "json"):
            found = resource_urls(outputs[name])
            check(
                f"the {name} export loads no outside resource",
                not found,
                "; ".join(found[:2]),
            )
        check(
            "the Markdown export has no image (an image is a request when it is read)",
            not re.search(r"(?<!\\)!\[", outputs["md"]),
        )
        reader = browser.new_page()
        opened: list[str] = []
        reader.on("request", lambda r: opened.append(r.url))
        saved = Path(tempfile.mkdtemp(prefix="chai-3p-")) / "report.html"
        saved.write_text(outputs["html"], encoding="utf-8")
        reader.goto(saved.as_uri())
        reader.wait_for_timeout(500)
        check(
            "opening the saved report makes no request to another host",
            not external(opened),
            ", ".join(external(opened)[:3]),
        )

        print("The check notices a request, and a resource (mutation)")
        # The page's own policy refuses these requests (connect-src and img-src are
        # 'self'), which is the point of it. The probe bypasses the policy so that this
        # test shows its own detector can see a request, whatever stopped it.
        probe = browser.new_context(bypass_csp=True).new_page()
        probed: list[str] = []
        probe.on("request", lambda r: probed.append(r.url))
        probe.goto(APP.as_uri())
        probe.evaluate("fetch('https://tracker.example/x').catch(() => {})")
        probe.evaluate("new Image().src = 'https://tracker.example/p.gif'")
        probe.wait_for_timeout(300)
        check(
            "a fetch and an image to another host are both seen",
            len(external(probed)) >= 2,
            str(probed),
        )
        check(
            "a stylesheet link, an image and a CSS url() in an export are noticed",
            len(
                resource_urls(
                    '<link rel=stylesheet href="https://x.example/a.css"><img src="https://x.example/p.png"><style>a{background:url(https://x.example/b.png)}</style>'
                )
            )
            == 3,
        )
        check(
            "a plain hyperlink in a report is not a resource",
            not resource_urls(
                '<a href="https://hospital.example/doc.pdf">the validation report</a>'
            ),
        )

        # The export is generated from the live page, so check its text too.
        page.evaluate(
            """() => {
                S = normalize(blankProject("Sepsis early warning"));
                CUR = "x";
            }"""
        )
        html = page.evaluate("() => exportHTML()")
        check(
            "the HTML export links no external stylesheet",
            "<link" not in html.lower() or "fonts.googleapis" not in html,
            "export still references an external origin",
        )
        check(
            "the HTML export has no http(s) resource URLs at all",
            not resource_urls(html),
            "; ".join(resource_urls(html)[:2]),
        )
        check("the export still carries its inline styles", "<style>" in html)
        check(
            "the export still names the project",
            "Sepsis early warning" in html,
        )

        # Rendering must not have fallen back to a serif default.
        family = page.evaluate("() => getComputedStyle(document.body).fontFamily")
        check(
            "body still resolves a sans-serif stack",
            "sans-serif" in family or "system-ui" in family,
            family,
        )
        server_backed_checks(browser)
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("no third-party contact checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
