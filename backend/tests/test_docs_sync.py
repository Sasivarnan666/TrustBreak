"""P0.3 - the documentation must not drift from the code.

Fails when the version or the claimed test count differs between the code, package.json and
the docs, or when an HTTP route is missing from the README API table.
"""

import json
import re
import unittest
from pathlib import Path

from app import __version__

ROOT = Path(__file__).resolve().parents[2]


def read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


class VersionSync(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_frontend_manifest_matches(self):
        self.assertEqual(json.loads(read("frontend", "package.json"))["version"], __version__)
        self.assertEqual(json.loads(read("frontend", "package-lock.json"))["version"], __version__)

    def test_docs_state_the_same_version(self):
        self.assertIn(f"Version {__version__}", read("docs", "PROJECT_STATE.md").split("\n", 3)[2])
        self.assertIn(f"(v{__version__})", read("README.md"))
        self.assertIn(f"Version: {__version__}", read("docs", "ROADMAP.md"))
        self.assertRegex(read("docs", "CHANGELOG.md"), rf"^# Changelog\n\n## {re.escape(__version__)} ", )

    def test_health_and_openapi_report_it(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover
            self.skipTest("fastapi/httpx not installed")
        import os
        import tempfile

        saved = os.environ.get("TRUSTBREAK_DB_PATH")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TRUSTBREAK_DB_PATH"] = str(Path(tmp) / "d.db")
            try:
                from app.main import create_app

                with TestClient(create_app()) as client:
                    self.assertEqual(client.get("/api/health").json()["data"]["version"], __version__)
                    self.assertEqual(client.get("/openapi.json").json()["info"]["version"], __version__)
            finally:
                os.environ.pop("TRUSTBREAK_DB_PATH", None) if saved is None else os.environ.__setitem__("TRUSTBREAK_DB_PATH", saved)


class TestCountSync(unittest.TestCase):
    def test_claimed_test_count_is_current(self):
        backend = ROOT / "backend"
        suite = unittest.defaultTestLoader.discover(str(backend / "tests"), top_level_dir=str(backend))

        def count(s):
            return sum(count(x) if isinstance(x, unittest.TestSuite) else 1 for x in s)

        actual = count(suite)
        claims = re.findall(r"(\d+) tests", read("docs", "PROJECT_STATE.md").split("## What was implemented")[0])
        self.assertTrue(claims, "PROJECT_STATE summary must state the test count")
        self.assertEqual({int(c) for c in claims}, {actual}, "update the test count in docs/PROJECT_STATE.md")


class ApiTableSync(unittest.TestCase):
    def test_every_route_is_in_the_readme(self):
        src = read("backend", "app", "routers", "incidents.py")
        readme = read("README.md")
        routes = re.findall(r'@router\.(?:get|post)\("([^"]*)"', src)
        self.assertGreaterEqual(len(routes), 9)
        for path in routes:
            full = ("/api/incidents" + path).replace("{incident_id}", "{id}")
            self.assertTrue(full in readme, f"{full} missing from the README API table")
        self.assertIn("/api/health", readme)


if __name__ == "__main__":
    unittest.main()
