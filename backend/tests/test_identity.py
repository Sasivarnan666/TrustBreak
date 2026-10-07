"""v0.9.0 trusted identity model: registry, resolution rules, behaviour preference for the id, and the API."""

import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.services.behaviour import analyze_incident_behaviour
from app.services.identity import get_identity, list_identities, resolve_identity

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


class RegistryTests(unittest.TestCase):
    def test_ceo_identity_fields(self):
        i = get_identity("CEO-001")
        self.assertEqual((i.display_name, i.role, i.department, i.organization),
                         ("Arvind Rao", "Chief Executive Officer", "Executive", "NovaTech Industries"))
        self.assertEqual(i.corporate_email, "arvind.rao@novatech.example")
        self.assertEqual((i.typical_amount_min, i.typical_amount_max), (20_000, 200_000))
        self.assertEqual(i.normal_channels, ("email", "erp"))
        self.assertEqual(i.known_beneficiaries, ("Vendor A", "Vendor B", "Vendor C"))
        self.assertTrue(i.active and i.profile_version == 1)

    def test_ids_are_unique_and_lookup_is_case_insensitive(self):
        ids = [i.identity_id for i in list_identities()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIs(get_identity("ceo-001"), get_identity("CEO-001"))
        self.assertIsNone(get_identity("NOPE-1"))
        self.assertIsNone(get_identity(None))

    def test_resolution_order(self):
        self.assertEqual(resolve_identity("CEO-001", "Someone Else")[1], "explicit")
        self.assertEqual(resolve_identity(None, "  arvind   RAO ")[1], "name_match")
        self.assertEqual(resolve_identity(None, "Jason"), (None, "none"))
        # an unknown id never silently falls back to the display name
        self.assertEqual(resolve_identity("BAD-9", "Arvind Rao"), (None, "unknown_id"))

    def test_to_dict_has_no_real_data_markers(self):
        d = get_identity("CEO-001").to_dict()
        self.assertTrue(d["corporate_email"].endswith(".example"))
        self.assertEqual(d["profile_status"], "Trusted synthetic demo profile")


class BehaviourPrefersIdentityIdTests(unittest.TestCase):
    ARGS = dict(channel="WhatsApp", amount=1_850_000, beneficiary="Vendor X")

    def test_id_wins_over_name(self):
        r = analyze_incident_behaviour("Totally Different Name", sender_identity_id="CEO-001", **self.ARGS)
        self.assertEqual(r["employee_id"], "CEO-001")
        self.assertTrue(r["amount_anomaly"] and r["new_beneficiary"] and r["channel_anomaly"])

    def test_wrong_id_does_not_fall_back_to_name(self):
        r = analyze_incident_behaviour("Arvind Rao", sender_identity_id="BAD-9", **self.ARGS)
        self.assertFalse(r["profile_found"])

    def test_name_fallback_without_id(self):
        r = analyze_incident_behaviour("Arvind Rao", **self.ARGS)
        self.assertEqual(r["employee_id"], "CEO-001")

    def test_other_identity_id_uses_that_profile(self):
        r = analyze_incident_behaviour("Arvind Rao", sender_identity_id="CFO-001", **self.ARGS)
        self.assertEqual(r["employee_id"], "CFO-001")


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("Statement.pdf", "Update.exe"):
            z.writestr(name, "inert placeholder")
    return buf.getvalue()


BASE = {"sender_name": "Arvind Rao", "sender_role": "Chief Executive Officer", "sender_known": True,
        "channel": "Email", "amount": 100000, "beneficiary_name": "Vendor A", "beneficiary_is_new": False,
        "message": "Please pay the monthly invoice as usual."}


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class IdentityApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE")}
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
        os.environ["TRUSTBREAK_AI_MODE"] = "mock"
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def test_list_and_detail(self):
        res = self.client.get("/api/identities").json()
        self.assertEqual({i["identity_id"] for i in res["data"]}, {"CEO-001", "CFO-001"})
        d = self.client.get("/api/identities/CEO-001").json()["data"]
        self.assertEqual(d["identity"]["display_name"], "Arvind Rao")
        self.assertEqual(d["baseline"]["typical_amount_max"], 200000)
        self.assertEqual(d["activity"]["incident_count"], 1)  # the seeded demo incident
        self.assertEqual(d["activity"]["channels_seen"], ["WhatsApp"])
        self.assertEqual(self.client.get("/api/identities/NOPE").status_code, 404)

    def test_identities_are_read_only(self):
        self.assertEqual(self.client.post("/api/identities", json={}).status_code, 405)

    def test_seeded_incident_is_linked_explicitly(self):
        s = self.client.get("/api/incidents/1").json()["data"]["sender"]
        self.assertEqual((s["identity_id"], s["identity_source"]), ("CEO-001", "explicit"))

    def test_create_with_and_without_id(self):
        explicit = self.client.post("/api/incidents", json={**BASE, "sender_identity_id": "ceo-001"}).json()["data"]
        self.assertEqual(explicit["sender"]["identity_id"], "CEO-001")
        by_name = self.client.post("/api/incidents", json=BASE).json()["data"]
        self.assertEqual((by_name["sender"]["identity_id"], by_name["sender"]["identity_source"]), ("CEO-001", "name_match"))
        unknown = self.client.post("/api/incidents", json={**BASE, "sender_name": "Jason"}).json()["data"]
        self.assertEqual((unknown["sender"]["identity_id"], unknown["sender"]["identity_source"]), (None, "none"))

    def test_unknown_identity_id_is_rejected(self):
        res = self.client.post("/api/incidents", json={**BASE, "sender_identity_id": "BAD-9"})
        self.assertEqual(res.status_code, 422)

    def test_id_beats_a_misleading_display_name(self):
        # display name does not match any profile; the explicit id still selects CEO-001's baseline
        body = {**BASE, "sender_name": "A. Rao (new number)", "sender_identity_id": "CEO-001", "channel": "WhatsApp",
                "amount": 1850000, "beneficiary_name": "Vendor X", "beneficiary_is_new": True}
        inc = self.client.post("/api/incidents", json=body).json()["data"]
        beh = self.client.post(f"/api/incidents/{inc['id']}/analyze-behaviour").json()["data"]
        self.assertEqual(beh["employee_id"], "CEO-001")
        self.assertTrue(beh["amount_anomaly"])

    def test_risk_assessment_unchanged_for_demo(self):
        r = self.client.post("/api/incidents/1/analyze-risk",
                             files={"file": ("RBI_Statement.zip", _zip(), "application/zip")}).json()["data"]
        self.assertEqual((r["risk_level"], r["recommended_action"], r["trust_break_detected"]),
                         ("CRITICAL", "HOLD_PAYMENT", True))

    def test_legacy_row_without_identity_columns_still_resolves_by_name(self):
        import sqlite3

        con = sqlite3.connect(os.environ["TRUSTBREAK_DB_PATH"])
        con.execute("UPDATE incidents SET sender_identity_id = NULL, sender_identity_source = NULL WHERE id = 1")
        con.commit(); con.close()
        beh = self.client.post("/api/incidents/1/analyze-behaviour").json()["data"]
        self.assertEqual(beh["employee_id"], "CEO-001")
        g = self.client.get("/api/incidents/1/trust-graph").json()["data"]
        self.assertEqual(g["identity_source"], "name_match")


if __name__ == "__main__":
    unittest.main()
