"""Checkpoint sign-offs are attributed by the server, never by the client (#31).

`gates.*.signedBy` and `gates.*.signedAt` used to be sent by the browser and
merged into the stored document untouched, so any writer could record a decision
as the CMO, on any date. The deployment guide sells the server mode on the
opposite claim: "the identity attached to it was asserted by the organization's
IdP, not chosen by whoever was at the keyboard." These tests hold it to that.

The same reasoning is already applied to the audit log (`append_log` overwrites
`at` and `by`): an attestation whose author and timestamp come from the client
is not an attestation.

Two layers. The rules are pure and tested without a database. The exploit itself
is then reproduced against the real API, because a rule nobody wired in is not a
control.
"""

from __future__ import annotations

import copy

from app.signoff import attribute_signoffs
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, requires_db

ALICE = TEST_EMAIL
BOB = "bob.intern@hospital.example"
CMO = "cmo@hospital.example"
READER = "reader@hospital.example"
NOW = "2026-10-07T12:00:00.000Z"
FORGED_AT = "2026-01-15T09:00:00.000Z"


def gate(**fields) -> dict:
    return {"gates": {"A": fields}}


def stored(**fields) -> dict:
    return {"gates": {"A": fields}}


def result(
    patch: dict, before: dict | None, actor: str = BOB, *, enforced=True
) -> dict:
    return attribute_signoffs(patch, before, actor, NOW, enforced=enforced)["gates"][
        "A"
    ]


# --- the rules, without a database -----------------------------------------


class TestWhoSignedAndWhen:
    def test_a_new_decision_is_attributed_to_the_caller_not_the_claim(self):
        out = result(
            gate(decision="Proceed", signedBy=CMO, signedAt=FORGED_AT), stored()
        )
        assert out["signedBy"] == BOB
        assert out["signedAt"] == NOW

    def test_a_decision_with_no_attribution_sent_still_gets_one(self):
        out = result(gate(decision="Proceed"), stored())
        assert (out["signedBy"], out["signedAt"]) == (BOB, NOW)

    def test_changing_a_decision_moves_the_attribution_to_whoever_changed_it(self):
        """Bob changes Alice's decision without sending any attribution. Left
        alone, the record would still say Alice decided "Stop"."""
        before = stored(decision="Proceed", signedBy=ALICE, signedAt=FORGED_AT)
        out = result(gate(decision="Stop"), before)
        assert (out["signedBy"], out["signedAt"]) == (BOB, NOW)

    def test_an_unchanged_decision_cannot_have_its_attribution_rewritten(self):
        before = stored(decision="Proceed", signedBy=ALICE, signedAt=FORGED_AT)
        out = result(
            gate(decision="Proceed", signedBy=CMO, signedAt="2030-01-01T00:00:00.000Z"),
            before,
        )
        assert "signedBy" not in out and "signedAt" not in out, "must be a no-op"

    def test_resending_the_stored_block_is_a_no_op_not_an_error(self):
        """The browser may re-send a whole gate; that must not 403 or re-attribute."""
        before = stored(
            decision="Proceed", signedBy=ALICE, signedAt=FORGED_AT, rationale="ok"
        )
        out = result(gate(**before["gates"]["A"]), before)
        assert "signedBy" not in out and out["rationale"] == "ok"

    def test_clearing_a_decision_clears_the_attribution_with_it(self):
        before = stored(decision="Proceed", signedBy=ALICE, signedAt=FORGED_AT)
        out = result(gate(decision=None, signedBy=CMO, signedAt=FORGED_AT), before)
        assert out["signedBy"] is None and out["signedAt"] is None

    def test_an_empty_decision_cannot_carry_a_signature(self):
        out = result(gate(decision="", signedBy=CMO, signedAt=FORGED_AT), stored())
        assert out["signedBy"] is None and out["signedAt"] is None

    def test_blanking_the_attribution_while_the_decision_stands_is_refused(self):
        """Otherwise a writer could erase who signed without touching the decision."""
        before = stored(decision="Proceed", signedBy=ALICE, signedAt=FORGED_AT)
        out = result(gate(signedBy=None, signedAt=None), before)
        assert "signedBy" not in out and "signedAt" not in out

    def test_other_gate_fields_are_left_alone(self):
        out = result(
            gate(
                decision="Proceed",
                by="AI Governance Committee",
                date="2026-01-15",
                rationale="Approved.",
            ),
            stored(),
        )
        assert out["by"] == "AI Governance Committee"
        assert out["date"] == "2026-01-15" and out["rationale"] == "Approved."


class TestPeriodicReview:
    """Recording a periodic review sets signedBy/signedAt with no decision key."""

    def test_a_review_of_an_existing_decision_is_attributed_to_the_reviewer(self):
        before = stored(decision="Proceed", signedBy=ALICE, signedAt=FORGED_AT)
        out = result(gate(date="2026-10-07", signedBy=CMO, signedAt=FORGED_AT), before)
        assert out["signedBy"] == BOB, "not the CMO the client claimed"
        assert out["signedAt"] == NOW

    def test_attribution_with_nothing_to_review_is_dropped(self):
        out = result(gate(signedBy=CMO, signedAt=FORGED_AT), stored())
        assert "signedBy" not in out and "signedAt" not in out

    def test_the_stored_values_sent_back_are_a_no_op(self):
        before = stored(decision="Proceed", signedBy=ALICE, signedAt=FORGED_AT)
        out = result(gate(signedBy=ALICE, signedAt=FORGED_AT), before)
        assert "signedBy" not in out and "signedAt" not in out


class TestEverythingElse:
    def test_creating_a_project_with_a_pre_signed_gate_attributes_the_creator(self):
        out = result(gate(decision="Proceed", signedBy=CMO, signedAt=FORGED_AT), None)
        assert (out["signedBy"], out["signedAt"]) == (BOB, NOW)

    def test_every_gate_is_handled_independently(self):
        patch = {
            "gates": {
                "A": {"decision": "Proceed", "signedBy": CMO},
                "B": {"decision": "Stop", "signedBy": CMO},
            }
        }
        out = attribute_signoffs(patch, None, BOB, NOW, enforced=True)["gates"]
        assert out["A"]["signedBy"] == out["B"]["signedBy"] == BOB

    def test_a_patch_with_no_gates_is_returned_unchanged(self):
        patch = {"meta": {"solution": "x"}}
        assert attribute_signoffs(patch, None, BOB, NOW, enforced=True) == patch

    def test_a_null_or_non_object_gate_is_left_alone(self):
        for patch in ({"gates": None}, {"gates": {"A": None}}, {"gates": {"A": "x"}}):
            assert attribute_signoffs(patch, None, BOB, NOW, enforced=True) == patch

    def test_the_input_is_not_mutated(self):
        patch = gate(decision="Proceed", signedBy=CMO)
        snapshot = copy.deepcopy(patch)
        attribute_signoffs(patch, None, BOB, NOW, enforced=True)
        assert patch == snapshot

    def test_without_identity_nothing_is_attributed_and_the_docs_say_so(self):
        """REQUIRE_IDENTITY=false: there is nobody to attribute to, so the value
        stays self-asserted, which /api/health reports rather than hides."""
        patch = gate(decision="Proceed", signedBy=CMO, signedAt=FORGED_AT)
        assert result(patch, stored(), enforced=False) == patch["gates"]["A"]


# --- the exploit from the issue, against the real API ----------------------


def headers_for(email: str) -> dict[str, str]:
    return {"X-Forwarded-Email": email, "X-Forwarded-User": email.split("@")[0]}


def acting_as(client: AsyncClient, email: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers=headers_for(email),
    )


async def make_project(client: AsyncClient, pid: str, **extra) -> None:
    r = await client.post(
        f"/api/projects/{pid}",
        json={
            "meta": {"solution": "Sepsis early warning"},
            "access": {
                "owners": [ALICE],
                "writers": [BOB],
                "readers": [READER],
            },
            **extra,
        },
    )
    assert r.status_code == 201, r.text


async def read_gate(client: AsyncClient, pid: str, key: str = "A") -> dict:
    projects = (await client.get("/api/projects")).json()
    return next(p for p in projects if p["id"] == pid)["gates"][key]


@requires_db
class TestTheForgeryFromTheIssue:
    async def test_a_writer_cannot_sign_off_as_the_cmo(self, client: AsyncClient):
        await make_project(client, "forge")
        async with acting_as(client, BOB) as bob:
            r = await bob.patch(
                "/api/projects/forge",
                json={
                    "gates": {
                        "A": {
                            "decision": "Proceed",
                            "by": "AI Governance Committee",
                            "signedBy": CMO,
                            "signedAt": FORGED_AT,
                            "rationale": "Approved for clinical deployment.",
                        }
                    }
                },
            )
        assert r.status_code == 200, r.text
        stored_gate = await read_gate(client, "forge")
        assert stored_gate["signedBy"] == BOB, "the CMO never touched this system"
        assert stored_gate["signedAt"] != FORGED_AT, "the date was bob's to choose"
        assert stored_gate["signedAt"].startswith("20"), stored_gate["signedAt"]

    async def test_the_response_shows_the_server_value_too(self, client: AsyncClient):
        await make_project(client, "forge2")
        async with acting_as(client, BOB) as bob:
            r = await bob.patch(
                "/api/projects/forge2",
                json=gate(decision="Proceed", signedBy=CMO, signedAt=FORGED_AT),
            )
        assert r.json()["gates"]["A"]["signedBy"] == BOB

    async def test_attribution_agrees_with_the_version_history(
        self, client: AsyncClient
    ):
        """changed_by is server-authored already; the sign-off now matches it."""
        await make_project(client, "agree")
        async with acting_as(client, BOB) as bob:
            await bob.patch(
                "/api/projects/agree", json=gate(decision="Proceed", signedBy=CMO)
            )
        versions = (await client.get("/api/projects/agree/versions")).json()
        latest = max(versions, key=lambda v: v["rev"])
        assert latest["by"] == (await read_gate(client, "agree"))["signedBy"] == BOB

    async def test_a_forged_attribution_on_an_unchanged_decision_is_ignored(
        self, client: AsyncClient
    ):
        await make_project(client, "keep")
        await client.patch("/api/projects/keep", json=gate(decision="Proceed"))
        assert (await read_gate(client, "keep"))["signedBy"] == ALICE
        async with acting_as(client, BOB) as bob:
            r = await bob.patch(
                "/api/projects/keep",
                json=gate(decision="Proceed", signedBy=CMO, signedAt=FORGED_AT),
            )
        assert r.status_code == 200, "an unchanged resend must not become an error"
        assert (await read_gate(client, "keep"))["signedBy"] == ALICE

    async def test_resending_a_whole_gate_block_succeeds_and_changes_nothing(
        self, client: AsyncClient
    ):
        await make_project(client, "resend")
        await client.patch(
            "/api/projects/resend", json=gate(decision="Proceed", rationale="ok")
        )
        before = await read_gate(client, "resend")
        async with acting_as(client, BOB) as bob:
            r = await bob.patch("/api/projects/resend", json={"gates": {"A": before}})
        assert r.status_code == 200
        assert await read_gate(client, "resend") == before

    async def test_changing_a_decision_re_attributes_it_to_the_changer(
        self, client: AsyncClient
    ):
        await make_project(client, "change")
        await client.patch("/api/projects/change", json=gate(decision="Proceed"))
        async with acting_as(client, BOB) as bob:
            await bob.patch("/api/projects/change", json=gate(decision="Stop"))
        out = await read_gate(client, "change")
        assert (out["decision"], out["signedBy"]) == ("Stop", BOB)

    async def test_clearing_a_decision_clears_its_attribution(
        self, client: AsyncClient
    ):
        await make_project(client, "clear")
        await client.patch("/api/projects/clear", json=gate(decision="Proceed"))
        await client.patch(
            "/api/projects/clear", json=gate(decision=None, signedBy=CMO)
        )
        out = await read_gate(client, "clear")
        assert out.get("signedBy") is None and out.get("signedAt") is None

    async def test_a_pre_signed_gate_on_create_is_attributed_to_the_creator(
        self, client: AsyncClient
    ):
        r = await client.post(
            "/api/projects/presigned",
            json={
                "meta": {"solution": "Imported"},
                **gate(decision="Proceed", signedBy=CMO, signedAt=FORGED_AT),
            },
        )
        assert r.status_code == 201
        assert (await read_gate(client, "presigned"))["signedBy"] == ALICE

    async def test_a_reader_still_cannot_sign_anything(self, client: AsyncClient):
        await make_project(client, "reader")
        async with acting_as(client, READER) as reader:
            r = await reader.patch(
                "/api/projects/reader", json=gate(decision="Proceed")
            )
        assert r.status_code == 403, "access control is checked first"
