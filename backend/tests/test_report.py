"""Printable incident report: complete, escaped, honest, read-only."""

import re
import unittest

from tests.test_risk_persistence_api import NORMAL, PersistedRiskApiTests, demo_zip
from tests.test_verification import CONFIRM, START

SECTIONS = ["1. Executive summary", "2. Trusted identity", "3. Observed request", "4. Behaviour baseline", "5. Social-engineering indicators",
            "6. Attachment findings", "7. Risk assessment", "8. Evidence and provenance", "9. Counterfactual analysis",
            "10. Verification history", "11. Forensic timeline", "12. Assessment history", "13. Analyst decision", "14. Limitations / methodology"]


class ReportTests(PersistedRiskApiTests):
    def rep(self, iid=1):
        return self.client.get(f"/api/incidents/{iid}/report")

    def test_unknown_incident_404(self):
        self.assertEqual(self.rep(999).status_code, 404)

    def test_full_demo_report(self):
        self.run_risk(files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")})
        self.client.post("/api/incidents/1/verification", json=START)
        self.client.post("/api/incidents/1/verification", json=CONFIRM)
        res = self.rep()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers["content-type"].startswith("text/html"))
        h = res.text
        self.assertIn("TRUSTBREAK INCIDENT REPORT", h)
        for s in SECTIONS:
            self.assertIn(s, h)
        for needed in ("TB-0001", "SYNTHETIC / DEMO DATA", "TRUST BREAK DETECTED", "Arvind Rao / CEO-001", "100", "CRITICAL",
                       "Statement.pdf", "Update.exe", "helper.dll", "Static structural analysis only",
                       "TrustBreak provides deterministic prototype decision support. Risk scores are heuristic and are not probabilities of fraud.",
                       "Attachment analysis is static structural analysis and does not establish malware presence.",
                       "Counterfactuals are deterministic simulations using the same Risk Engine",
                       "Known corporate phone", "Verification confirmed", "No analyst decision has been recorded"):
            self.assertIn(needed, h)
        self.assertNotIn("<script", h.lower().replace("onclick='window.print()'", ""))
        self.assertNotRegex(h, r"(?i)api[_ ]?key|GEMINI_|AIza")
        self.assertNotIn("is malware", h.lower())
        self.assertNotIn("fraud probability", h.lower())

    def test_message_is_escaped(self):
        evil = dict(NORMAL, message="<script>alert(1)</script> pay now & keep secret", sender_name="Arvind Rao")
        iid = self.client.post("/api/incidents", json=evil).json()["data"]["id"]
        self.run_risk(iid)
        h = self.rep(iid).text
        self.assertNotIn("<script>alert(1)</script>", h)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", h)

    def test_unassessed_report_is_honest(self):
        h = self.rep().text
        self.assertIn("No risk assessment has been run", h)
        self.assertIn("Unavailable", h)
        for s in SECTIONS:
            self.assertIn(s, h)

    def test_non_synthetic_incident_is_not_labelled_as_a_scenario(self):
        iid = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        self.run_risk(iid)
        h = self.rep(iid).text
        self.assertNotIn("SYNTHETIC / DEMO DATA", h)
        self.assertIn("synthetic", h.lower())  # baseline note

    def test_report_is_read_only(self):
        self.run_risk()
        before = (self.get(), self.client.get("/api/incidents/1/assessments").json())
        self.rep()
        self.assertEqual((self.get(), self.client.get("/api/incidents/1/assessments").json()), before)


if __name__ == "__main__":
    unittest.main()
