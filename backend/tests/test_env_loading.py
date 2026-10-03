"""Configuration tests: backend/.env loading. No real key is used; values are never printed."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app import config

BACKEND_DIR = Path(__file__).resolve().parents[1]
FAKE_KEY = "fake-test-key-not-a-secret"  # placeholder, not a real credential
_KEYS = ("GEMINI_API_KEY", "TRUSTBREAK_LOAD_DOTENV")


class EnvFileLoadingTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _KEYS}
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ["TRUSTBREAK_LOAD_DOTENV"] = "1"  # the suite disables it globally
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = Path(self._tmp.name) / ".env"

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _write(self, text):
        self.env_path.write_text(text, encoding="utf-8")

    def test_env_file_is_anchored_to_backend_dir(self):
        self.assertEqual(config.ENV_FILE, BACKEND_DIR / ".env")

    def test_loads_key_from_file_without_exposing_value(self):
        self._write(f"GEMINI_API_KEY={FAKE_KEY}\n")
        self.assertTrue(config.load_env_file(self.env_path))
        self.assertTrue(bool(os.environ.get("GEMINI_API_KEY")))
        self.assertEqual(bool(config.get_ai_api_key("gemini")), True)

    def test_real_environment_wins_over_file(self):
        os.environ["GEMINI_API_KEY"] = "from-environment"
        self._write(f"GEMINI_API_KEY={FAKE_KEY}\n")
        config.load_env_file(self.env_path)
        self.assertEqual(os.environ["GEMINI_API_KEY"], "from-environment")

    def test_blank_environment_value_is_filled_from_file(self):
        os.environ["GEMINI_API_KEY"] = ""
        self._write(f"GEMINI_API_KEY={FAKE_KEY}\n")
        config.load_env_file(self.env_path)
        self.assertTrue(bool(os.environ["GEMINI_API_KEY"]))

    def test_empty_value_in_file_does_not_count_as_configured(self):
        self._write("GEMINI_API_KEY=\n")
        config.load_env_file(self.env_path)
        self.assertIsNone(config.get_ai_api_key("gemini"))

    def test_missing_file_is_not_an_error(self):
        self.assertFalse(config.load_env_file(Path(self._tmp.name) / "absent.env"))
        self.assertNotIn("GEMINI_API_KEY", os.environ)

    def test_loading_can_be_disabled(self):
        os.environ["TRUSTBREAK_LOAD_DOTENV"] = "0"
        self._write(f"GEMINI_API_KEY={FAKE_KEY}\n")
        self.assertFalse(config.load_env_file(self.env_path))
        self.assertNotIn("GEMINI_API_KEY", os.environ)

    def test_app_import_loads_backend_env_from_any_working_directory(self):
        """Subprocess: a temporary backend-like tree is not needed; we point at a temp .env via
        the loader's default by running from a different cwd and checking only a boolean."""
        code = (
            "import os, sys; sys.path.insert(0, sys.argv[1]);"
            "from app import config; config.ENV_FILE = __import__('pathlib').Path(sys.argv[2]);"
            "config.load_env_file(); print(bool(os.environ.get('GEMINI_API_KEY')))"
        )
        self._write(f"GEMINI_API_KEY={FAKE_KEY}\n")
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        env["TRUSTBREAK_LOAD_DOTENV"] = "1"
        for cwd in (BACKEND_DIR, BACKEND_DIR.parent, self._tmp.name):
            out = subprocess.run(
                [sys.executable, "-c", code, str(BACKEND_DIR), str(self.env_path)],
                cwd=cwd, env=env, capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(out, "True", f"cwd={cwd}")

    def test_dotenv_is_gitignored_and_example_has_no_key(self):
        root = BACKEND_DIR.parent
        patterns = (root / ".gitignore").read_text().splitlines()
        self.assertIn(".env", patterns)  # unanchored: matches backend/.env at any depth
        for example in (root / ".env.example", BACKEND_DIR / ".env.example"):
            if example.is_file():
                for line in example.read_text().splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        self.assertEqual(line.split("=", 1)[1].strip(), "")


if __name__ == "__main__":
    unittest.main()
