"""P0.2 - assessment correctness: the score is backend-authoritative, never double counted,
never stale, and identical wherever it is shown (detail, list, summary, after restart).

Synthetic data only; no network.
"""

import copy
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import risk_repository
from app.services.risk_correlation import rules
from app.services.risk_correlation.engine import correlate_risk
from app.services.risk_correlation.service import assess_incident_risk

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

ENV = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TRUSTBREAK_AI_PROVIDER")


def make_zip(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, b"x")
    return buf.getvalue()


def assert_internally_consistent(test, r):
    """The invariants every assessment must satisfy, whatever produced it."""
    pts = [s["points"] for s in r["signals"]]
    cats = [s["category"] for s in r["signals"]]
    groups = [s["group"] for s in r["signals"]]
    test.assertEqual(len(groups), len(set(groups)), "one signal per consolidation group (no double counting)")
    test.assertEqual(r["raw_points"], sum(pts))
    test.assertEqual(r["risk_score"], min(rules.MAX_SCORE, sum(pts)))
    per_category = {}
    for c, p in zip(cats, pts):
        per_category[c] = per_category.get(c, 0) + p
    test.assertEqual(r["category_points"], per_category)
    for category, cap in rules.CATEGORY_CAPS.items():
        test.assertLessEqual(r["category_points"].get(category, 0), cap)
    test.assertEqual(sum(r["category_points"].values()), r["raw_points"])
    expected = next(lvl for lo, lvl in rules.LEVEL_THRESHOLDS if r["risk_score"] >= lo)
    test.assertEqual(r["risk_level"], expected)
    test.assertEqual(r["recommended_action"], rules.ACTION_FOR_LEVEL[expected])
    test.assertFalse(r["payment_blocked"])
    codes = [s["code"] for s in r["signals"]]
    test.assertEqual(len(codes), len(set(codes)), "no duplicated signal")
    for s in r["signals"]:  # no evidence detail repeated inside one signal
        test.assertEqual(len(s["details"]), len(set(s["details"])))


def ceo_incident(channel="WhatsApp", amount=1850000, beneficiary="New Vendor X", message=None):
    return SimpleNamespace(
        message=message or "Urgent. Transfer Rs 18,50,000 today. Keep this confidential.",
        channel=channel,
        sender=SimpleNamespace(name="Arvind Rao", role="CEO"),
        payment=SimpleNamespace(amount=amount, beneficiary_name=beneficiary),
    )


class EngineInvariants(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV}
        os.environ["TRUSTBREAK_AI_MODE"] = "mock"

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def run_case(self, incident, file=None):
        return assess_incident_risk(incident, file).to_dict()

    def test_invariants_hold_across_scenarios(self):
        cases = {
            "critical": (ceo_incident(), ("RBI_Statement.zip", make_zip("Statement.pdf", "Update.exe", "helper.dll"), "application/zip")),
            "no_file": (ceo_incident(), None),
            "benign": (ceo_incident("Email", 100000, "Vendor A", "Please pay the monthly invoice as usual."), None),
            "unknown_sender": (SimpleNamespace(message="Urgent. Pay Rs 5,00,000 now. Keep this secret.", channel="Email",
                                               sender=SimpleNamespace(name="Nobody Known", role="Clerk"),
                                               payment=SimpleNamespace(amount=500000, beneficiary_name="X")), None),
            "double_ext": (ceo_incident(), ("Invoice.pdf.exe", b"MZ\x90\x00", "application/octet-stream")),
        }
        for name, (inc, f) in cases.items():
            with self.subTest(name):
                assert_internally_consistent(self, self.run_case(inc, f))

    def test_archive_with_two_executables_counts_executable_content_once(self):
        r = self.run_case(ceo_incident(), ("a.zip", make_zip("Statement.pdf", "Update.exe", "helper.dll"), "application/zip"))
        executables = [s for s in r["signals"] if s["code"] == "EXECUTABLE_ATTACHMENT"]
        self.assertEqual(len(executables), 1)
        self.assertEqual(executables[0]["points"], 25)
        self.assertEqual(sorted(executables[0]["details"]), ["Update.exe", "helper.dll"])

    def test_same_attachment_findings_listed_twice_do_not_add_points(self):
        att = {"archive": True, "contains_executable": True, "executable_files": ["Update.exe", "Update.exe"],
               "findings": [{"type": "executable_inside_archive", "severity": "high", "entry": "Update.exe"}] * 3
               + [{"type": "path_traversal", "severity": "high", "entry": "../a"}] * 2}
        once = correlate_risk(None, None, att).to_dict()
        att2 = copy.deepcopy(att)
        att2["findings"] = att["findings"][:1] + att["findings"][3:4]
        self.assertEqual(once["raw_points"], correlate_risk(None, None, att2).raw_points)
        self.assertEqual(once["signals"][0]["details"].count("Update.exe"), 1)

    def test_overlapping_attachment_categories_are_characterized(self):
        # RESOLVED IN RISK ENGINE 2.0: one deceptive "Invoice.pdf.exe" used to score three overlapping attachment
        # categories (25 + 20 + 15 = 60). It is now executable content (25) plus ONE disguise contribution (12); the
        # double-extension / risky-extension findings are recorded as related signals, not added again.
        r = self.run_case(ceo_incident("Email", 100000, "Vendor A", "Please pay the invoice."),
                          ("Invoice.pdf.exe", b"MZ\x90\x00", "application/octet-stream"))
        by = {s["code"]: s["points"] for s in r["signals"] if s["analyzer"] == "attachment"}
        self.assertEqual(by.get("EXECUTABLE_ATTACHMENT"), 25)
        self.assertEqual(sum(by.values()), 25 + 12)
        self.assertEqual(len([c for c in by if c in ("DOUBLE_EXTENSION", "DOCUMENT_WITH_EXECUTABLE")]), 1)
        assert_internally_consistent(self, r)

    def test_missing_evidence_never_adds_points(self):
        base = correlate_risk(None, None, None)
        self.assertEqual((base.raw_points, base.risk_score, base.risk_level), (0, 0, "LOW"))

    def test_deterministic_for_identical_input(self):
        a = self.run_case(ceo_incident())
        b = self.run_case(ceo_incident())
        for k in ("risk_score", "raw_points", "signals", "category_points", "risk_level"):
            self.assertEqual(a[k], b[k])

    def test_extraction_cannot_smuggle_a_score(self):
        # An extraction/message dict carrying verdict-like fields has no effect on the score.
        msg = {"mode": "ai", "extraction": {"urgency_level": "none", "secrecy_indicator": False, "financial_intent": "none",
                                            "risk_score": 100, "risk_level": "CRITICAL", "claimed_authority": None, "deadline": None}}
        r = correlate_risk(msg, None, None).to_dict()
        self.assertEqual((r["risk_score"], r["risk_level"], r["signals"]), (0, "LOW", []))


class ConsistencyGuard(unittest.TestCase):
    def good(self):
        r = assess_incident_risk(ceo_incident(), None).to_dict()
        return r

    def setUp(self):
        self._m = os.environ.get("TRUSTBREAK_AI_MODE")
        os.environ["TRUSTBREAK_AI_MODE"] = "mock"

    def tearDown(self):
        os.environ.pop("TRUSTBREAK_AI_MODE", None) if self._m is None else os.environ.__setitem__("TRUSTBREAK_AI_MODE", self._m)

    def test_real_engine_output_passes(self):
        self.assertIsNone(risk_repository.check_result_consistent(self.good()))

    def test_contradictions_are_refused(self):
        tamper = {
            "inflated score": lambda r: r.update(risk_score=100, raw_points=100),
            "score not capped": lambda r: r.update(risk_score=r["raw_points"] + 5),
            "wrong level": lambda r: r.update(risk_level="LOW"),
            "wrong action": lambda r: r.update(recommended_action="PROCEED"),
            "category mismatch": lambda r: r["category_points"].update(urgency=99),
            "duplicate category": lambda r: r["signals"].append(copy.deepcopy(r["signals"][0])),
            "bad points": lambda r: r["signals"][0].update(points="lots"),
        }
        for name, fn in tamper.items():
            with self.subTest(name):
                r = self.good()
                fn(r)
                with self.assertRaises(ValueError):
                    risk_repository.check_result_consistent(r)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class PersistedConsistency(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in ENV}
        os.environ.update(TRUSTBREAK_DB_PATH=str(Path(self._tmp.name) / "i.db"), TRUSTBREAK_SEED_DEMO="1", TRUSTBREAK_AI_MODE="mock")
        for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TRUSTBREAK_AI_PROVIDER"):
            os.environ.pop(k, None)
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.c = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def files(self):
        return {"file": ("RBI_Statement.zip", make_zip("Statement.pdf", "Update.exe", "helper.dll"), "application/zip")}

    def test_stored_equals_returned_equals_listed_and_summarised(self):
        run = self.c.post("/api/incidents/1/analyze-risk", files=self.files()).json()["data"]
        assert_internally_consistent(self, run)
        detail = self.c.get("/api/incidents/1").json()["data"]
        stored = detail["risk_assessment"]
        for k in ("risk_score", "raw_points", "risk_level", "recommended_action", "category_points", "signals", "assessed_at"):
            self.assertEqual(stored[k], run[k], k)
        assert_internally_consistent(self, stored)
        row = next(i for i in self.c.get("/api/incidents").json()["data"] if i["id"] == 1)
        self.assertEqual((row["risk_score"], row["risk_level"], row["recommended_action"]), (run["risk_score"], run["risk_level"], run["recommended_action"]))
        self.assertEqual(detail["incident_status"], row["incident_status"])
        summary = self.c.get("/api/incidents/risk-summary").json()["data"]
        self.assertEqual(summary[run["risk_level"].lower()], 1)
        self.assertEqual(summary["assessed"], 1)

    def test_client_cannot_supply_a_score(self):
        res = self.c.post("/api/incidents/1/analyze-risk?risk_score=0&risk_level=LOW", data={"risk_score": "0", "risk_level": "LOW"})
        d = res.json()["data"]
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(d["risk_score"], 70)
        self.assertEqual(d["risk_level"], "CRITICAL")

    def test_repeated_runs_are_idempotent_not_cumulative(self):
        a = self.c.post("/api/incidents/1/analyze-risk", files=self.files()).json()["data"]
        b = self.c.post("/api/incidents/1/analyze-risk", files=self.files()).json()["data"]
        c = self.c.post("/api/incidents/1/analyze-risk", files=self.files()).json()["data"]
        for k in ("risk_score", "raw_points", "signals", "category_points"):
            self.assertEqual((a[k], b[k]), (b[k], c[k]), k)

    def test_rerun_without_file_drops_attachment_evidence_and_says_so(self):
        # Characterization of the known 0.6.0 limitation (superseded by assessment history in P1):
        # the latest snapshot never silently keeps stale attachment evidence.
        with_file = self.c.post("/api/incidents/1/analyze-risk", files=self.files()).json()["data"]
        without = self.c.post("/api/incidents/1/analyze-risk").json()["data"]
        self.assertGreater(with_file["risk_score"], without["risk_score"])
        self.assertEqual(without["inputs"]["attachment"]["status"], "not_provided")
        self.assertFalse(any(s["source"] == "attachment" for s in without["signals"]))
        stored = self.c.get("/api/incidents/1").json()["data"]["risk_assessment"]
        self.assertEqual(stored["signals"], without["signals"])
        assert_internally_consistent(self, stored)

    def test_engine_fault_is_refused_not_persisted(self):
        bad = assess_incident_risk(ceo_incident(), None).to_dict()
        bad["risk_score"] = 3
        with mock.patch("app.routers.incidents.assess_incident_risk") as m:
            m.return_value = SimpleNamespace(to_dict=lambda: bad)
            with self.assertRaises(ValueError):
                self.c.post("/api/incidents/1/analyze-risk")
        self.assertIsNone(self.c.get("/api/incidents/1").json()["data"]["risk_assessment"])


class FrontendDoesNotScore(unittest.TestCase):
    # The only arithmetic on risk_score in the UI is the progress-bar width clamp (display only).
    def test_no_frontend_file_sums_or_derives_points(self):
        import re

        src = Path(__file__).resolve().parents[2] / "frontend" / "src"
        for f in src.rglob("*.js*"):
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(reduce\([^)]*points|\.points\s*[+*]|\+=\s*[^;]*points)", text), f.name)


if __name__ == "__main__":
    unittest.main()
