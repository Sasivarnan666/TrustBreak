"""Runtime configuration.

Deliberately tiny: every setting has a sensible default and can be overridden
with an environment variable. Values are read on each call (not at import time)
so tests can point the app at a temporary database.
"""

import os
from pathlib import Path

# backend/app/config.py -> parents[2] is the repository root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "trustbreak.db"


def get_db_path() -> Path:
    return Path(os.environ.get("TRUSTBREAK_DB_PATH", str(DEFAULT_DB_PATH)))


def get_cors_origins() -> list[str]:
    raw = os.environ.get(
        "TRUSTBREAK_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def seed_enabled() -> bool:
    """Insert the synthetic demo incident on first start (set to 0 to disable)."""
    return os.environ.get("TRUSTBREAK_SEED_DEMO", "1") != "0"


# ---- AI message analysis ----------------------------------------------------- #
def get_ai_mode() -> str:
    """auto (default): use AI when a key exists, else demo mock. ai: AI only. mock: demo only."""
    mode = os.environ.get("TRUSTBREAK_AI_MODE", "auto").strip().lower()
    return mode if mode in ("auto", "ai", "mock") else "auto"


def get_ai_api_key():
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


def get_ai_model() -> str:
    return os.environ.get("TRUSTBREAK_AI_MODEL", "").strip() or "claude-sonnet-5-5"


def get_ai_timeout() -> float:
    try:
        value = float(os.environ.get("TRUSTBREAK_AI_TIMEOUT_SECONDS", "20"))
    except ValueError:
        return 20.0
    return value if 1 <= value <= 120 else 20.0
