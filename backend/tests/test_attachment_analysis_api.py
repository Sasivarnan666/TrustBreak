"""HTTP tests for POST /api/incidents/{id}/analyze-attachment (skipped without FastAPI/httpx)."""

import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

_ENV_KEYS = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_MAX_UPLOAD_BYTES")
URL = "/api/incidents/{}/analyze-attachment"

NO_ATTACHMENT = {
    "sender_name": "Arvind Rao",
    "sender_role": "Chief Executive Officer",
    "sender_known": True,
    "channel": "Email",
    "amount": 100000,
    "beneficiary_name": "Vendor A",
    "beneficiary_is_new": False,
    "message": "Please pay the monthly invoice as usual.",
}


def make_zip(names) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, b"synthetic placeholder text")
    return buf.getvalue()


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class AnalyzeAttachmentApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
        os.environ.pop("TRUSTBREAK_MAX_UPLOAD_BYTES", None)
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def post(self, incident_id, name, data, content_type="application/octet-stream"):
        return self.client.post(URL.format(incident_id), files={"file": (name, data, content_type)})

    def test_rbi_statement_scenario(self):
        blob = make_zip(["Statement.pdf", "Update.exe", "helper.dll"])
        res = self.post(1, "RBI_Statement.zip", blob, "application/zip")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertEqual((data["file_name"], data["file_type"], data["archive"], data["file_count"]),
                         ("RBI_Statement.zip", "zip", True, 3))
        self.assertTrue(data["contains_executable"] and data["suspicious"])
        self.assertFalse(data["is_final_decision"])
        found = {(f["type"], f.get("entry")) for f in data["findings"]}
        self.assertIn(("executable_inside_archive", "Update.exe"), found)
        self.assertIn(("executable_inside_archive", "helper.dll"), found)
        self.assertIn(("document_with_executable_content", None), found)

    def test_normal_pdf_and_zip(self):
        res = self.post(1, "RBI_Statement.zip", make_zip(["a.pdf", "b.pdf"]), "application/zip")
        self.assertFalse(res.json()["data"]["suspicious"])
        res = self.post(1, "RBI_Statement.zip", b"%PDF-1.4\n%%EOF\n", "application/pdf")
        self.assertEqual(res.json()["data"]["file_type"], "pdf")

    def test_name_differs_from_recorded_attachment(self):
        res = self.post(1, "Other.pdf", b"%PDF-1.4\n%%EOF\n")
        self.assertIn("differs", res.json()["data"]["notes"][0])

    def test_corrupted_zip_fails_safely(self):
        res = self.post(1, "RBI_Statement.zip", b"PK\x03\x04garbage")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertFalse(data["inspected"])
        self.assertIn("invalid_archive", [f["type"] for f in data["findings"]])

    def test_missing_file_part(self):
        res = self.client.post(URL.format(1))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "attachment_missing")

    def test_incident_without_attachment(self):
        created = self.client.post("/api/incidents", json=NO_ATTACHMENT).json()["data"]
        res = self.post(created["id"], "x.pdf", b"%PDF-1.4")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "attachment_missing")

    def test_unknown_incident_and_bad_id(self):
        self.assertEqual(self.post(999, "x.pdf", b"%PDF-1.4").status_code, 404)
        self.assertEqual(self.post(0, "x.pdf", b"%PDF-1.4").status_code, 422)

    def test_empty_file_too_large_and_long_name(self):
        self.assertEqual(self.post(1, "x.pdf", b"").json()["error"]["code"], "empty_file")
        os.environ["TRUSTBREAK_MAX_UPLOAD_BYTES"] = "100"
        res = self.post(1, "x.pdf", b"%PDF-" + b"0" * 500)
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (413, "file_too_large"))
        os.environ.pop("TRUSTBREAK_MAX_UPLOAD_BYTES")
        res = self.post(1, "a" * 300 + ".pdf", b"%PDF-1.4")
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (400, "filename_too_long"))

    def test_unsupported_type_and_path_traversal(self):
        res = self.post(1, "notes.xyz", b"plain text")
        self.assertEqual(res.json()["data"]["file_type"], "unknown")
        res = self.post(1, "RBI_Statement.zip", make_zip(["../../evil.txt"]))
        self.assertIn("path_traversal", [f["type"] for f in res.json()["data"]["findings"]])

    def test_other_analyses_unaffected(self):
        self.assertEqual(self.client.post("/api/incidents/1/analyze-behaviour").status_code, 200)
        self.assertEqual(self.client.post("/api/incidents/1/analyze-message").status_code, 200)
        self.assertEqual(self.client.get("/api/incidents/1").status_code, 200)


if __name__ == "__main__":
    unittest.main()
