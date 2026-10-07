"""v0.9.0 evidence / trust graph: pure builder tests and the HTTP endpoint."""

import ast
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.services.evidence_graph import build_comparison, build_trust_graph
from app.services.identity import get_identity

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

CEO = get_identity("CEO-001")
BEH_BAD = {"checks": {"amount": {"status": "above_baseline"}, "beneficiary": {"status": "new"}, "channel": {"status": "unusual"}}}
BEH_OK = {"checks": {"amount": {"status": "within_baseline"}, "beneficiary": {"status": "known"}, "channel": {"status": "normal"}}}


def sig(code, source, details=None, title=None):
    return {"code": code, "source": source, "title": title or code, "message": "m", "details": details or []}


def graph(behaviour=BEH_BAD, assessment=None, identity=CEO, attachment="RBI_Statement.zip", amount=1_850_000):
    return build_trust_graph(incident_id=1, identity=identity, identity_source="explicit" if identity else "none",
                             behaviour=behaviour, assessment=assessment, channel="WhatsApp", amount=amount,
                             beneficiary="Vendor X", attachment_name=attachment)


def ids(g):
    return {n["id"] for n in g["nodes"]}


class ComparisonTests(unittest.TestCase):
    def test_expected_vs_observed(self):
        rows = {r["aspect"]: r for r in build_comparison(CEO, BEH_BAD, "WhatsApp", 1_850_000, "Vendor X")}
        self.assertEqual(rows["channel"]["expected"], "Email / ERP")
        self.assertEqual(rows["beneficiary"]["expected"], "Vendor A, Vendor B, Vendor C")
        self.assertEqual(rows["amount"]["expected"], "≤ ₹2,00,000")
        self.assertEqual(rows["amount"]["observed"], "₹18,50,000")
        self.assertEqual(rows["amount"]["detail"], "9.25× the typical maximum")
        self.assertTrue(all(r["status"] == "anomalous" for r in rows.values()))

    def test_benign_is_normal(self):
        rows = build_comparison(CEO, BEH_OK, "Email", 100000, "Vendor A")
        self.assertTrue(all(r["status"] == "normal" for r in rows))
        self.assertIsNone(rows[2]["detail"])

    def test_no_identity_is_not_evaluated(self):
        rows = build_comparison(None, None, "Email", 1000, "Vendor A")
        self.assertTrue(all(r["status"] == "not_evaluated" for r in rows))


class GraphTests(unittest.TestCase):
    CRIT = {"assessment_id": 5, "version_number": 2, "risk_level": "CRITICAL", "trust_break_detected": True,
            "recommended_action_label": "Hold payment", "inputs": {"attachment": {"status": "used"}},
            "signals": [sig("HIGH_URGENCY", "message"), sig("EXECUTABLE_ATTACHMENT", "attachment", ["Update.exe", "helper.dll"])]}

    def test_full_trust_break_graph(self):
        g = graph(assessment=self.CRIT)
        self.assertTrue({"identity", "exp_channel", "obs_channel", "obs_amount", "obs_beneficiary", "request", "attachment",
                         "file_0", "file_1", "exec_content", "verdict", "sig_HIGH_URGENCY"} <= ids(g))
        verdict = next(n for n in g["nodes"] if n["id"] == "verdict")
        self.assertEqual((verdict["label"], verdict["status"]), ("TRUST BREAK", "verdict"))
        self.assertEqual((g["assessment_id"], g["version_number"]), (5, 2))
        self.assertFalse(g["is_final_decision"])

    def test_every_edge_references_existing_nodes(self):
        for a in (None, self.CRIT):
            g = graph(assessment=a)
            for e in g["edges"]:
                self.assertIn(e["source"], ids(g)); self.assertIn(e["target"], ids(g))

    def test_deterministic(self):
        self.assertEqual(graph(assessment=self.CRIT), graph(assessment=self.CRIT))

    def test_not_assessed_has_no_verdict_claim(self):
        g = graph(assessment=None)
        v = next(n for n in g["nodes"] if n["id"] == "verdict")
        self.assertEqual((v["label"], v["status"]), ("Not assessed", "unknown"))
        self.assertIsNone(g["trust_break_detected"])
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "attachment")["status"], "unknown")

    def test_benign_graph_has_no_anomaly_and_no_trust_break(self):
        a = {"assessment_id": 1, "version_number": 1, "risk_level": "LOW", "trust_break_detected": False,
             "recommended_action": "PROCEED", "signals": [sig("FINANCIAL_TRANSFER_INTENT", "message")], "inputs": {}}
        g = build_trust_graph(incident_id=2, identity=CEO, identity_source="explicit", behaviour=BEH_OK, assessment=a,
                              channel="Email", amount=100000, beneficiary="Vendor A", attachment_name=None)
        self.assertNotIn("anomalous", {n["status"] for n in g["nodes"] if n["kind"].startswith("observed")})
        self.assertNotIn("attachment", ids(g))
        v = next(n for n in g["nodes"] if n["id"] == "verdict")
        self.assertEqual((v["label"], v["status"]), ("No trust break detected", "normal"))

    def test_no_identity_degrades_without_inventing_a_baseline(self):
        g = graph(identity=None, behaviour={"checks": {}})
        self.assertNotIn("exp_channel", ids(g))
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "identity")["status"], "unknown")

    def test_graph_never_changes_the_verdict(self):
        # high-risk signals but the stored assessment says no trust break: the graph repeats the stored fact
        a = {**self.CRIT, "trust_break_detected": False, "risk_level": "HIGH"}
        v = next(n for n in graph(assessment=a)["nodes"] if n["id"] == "verdict")
        self.assertEqual(v["status"], "normal")

    def test_module_is_pure(self):
        path = Path(__file__).resolve().parents[1] / "app" / "services" / "evidence_graph.py"
        imported = {n.module if isinstance(n, ast.ImportFrom) else a.name
                    for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, (ast.Import, ast.ImportFrom))
                    for a in getattr(n, "names", [None])}
        self.assertFalse({m for m in imported if m and any(x in m for x in ("sqlite3", "fastapi", "urllib", "subprocess", "message_analysis", "risk_correlation"))})


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("Statement.pdf", "Update.exe", "helper.dll"):
            z.writestr(name, "inert placeholder")
    return buf.getvalue()


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class TrustGraphApiTests(unittest.TestCase):
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

    def test_before_assessment(self):
        g = self.client.get("/api/incidents/1/trust-graph").json()["data"]
        self.assertIsNone(g["assessment_id"])
        self.assertEqual(g["identity"]["identity_id"], "CEO-001")
        self.assertTrue(all(r["status"] == "anomalous" for r in g["comparison"]))

    def test_after_assessment_with_zip(self):
        self.client.post("/api/incidents/1/analyze-risk", files={"file": ("RBI_Statement.zip", _zip(), "application/zip")})
        g = self.client.get("/api/incidents/1/trust-graph").json()["data"]
        self.assertTrue(g["trust_break_detected"])
        self.assertEqual(g["risk_level"], "CRITICAL")
        labels = {n["label"] for n in g["nodes"]}
        self.assertTrue({"Update.exe", "helper.dll", "TRUST BREAK", "RBI_Statement.zip", "₹18,50,000"} <= labels)

    def test_read_only_and_errors(self):
        before = self.client.get("/api/incidents/1").json()
        self.client.get("/api/incidents/1/trust-graph")
        self.assertEqual(before, self.client.get("/api/incidents/1").json())
        self.assertEqual(self.client.get("/api/incidents/999/trust-graph").status_code, 404)
        self.assertEqual(self.client.post("/api/incidents/1/trust-graph").status_code, 405)


if __name__ == "__main__":
    unittest.main()
