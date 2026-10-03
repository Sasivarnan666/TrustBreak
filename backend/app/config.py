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
# Provider names understood by TRUSTBREAK_AI_PROVIDER.
AI_PROVIDERS = ("gemini", "anthropic", "mock")

# Environment variable holding each provider's API key (never hard-coded).
AI_KEY_ENV_VARS = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

# The ONLY place default model names live. Override with TRUSTBREAK_AI_MODEL.
DEFAULT_AI_MODELS = {"gemini": "gemini-3.8-flash", "anthropic": "claude-sonnet-5-5"}


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def get_ai_mode() -> str:
    """Failure policy (legacy name kept for compatibility).

    auto (default): use the provider when a key exists, else fall back to the labelled demo.
    ai:             provider only - return an error instead of falling back.
    mock:           force the offline demo extractor (wins over TRUSTBREAK_AI_PROVIDER).
    """
    mode = _env("TRUSTBREAK_AI_MODE").lower() or "auto"
    return mode if mode in ("auto", "ai", "mock") else "auto"


def get_ai_provider() -> str:
    """Resolve which provider handles message extraction.

    Precedence (first match wins):
      1. TRUSTBREAK_AI_MODE=mock                      -> mock (offline is always honoured)
      2. TRUSTBREAK_AI_PROVIDER = gemini|anthropic|mock
      3. (provider unset/invalid) GEMINI_API_KEY set   -> gemini
      4. (provider unset/invalid) only ANTHROPIC_API_KEY set -> anthropic (legacy setups)
      5. otherwise                                     -> gemini (primary; with no key the
         service falls back to the labelled demo extractor)
    """
    if get_ai_mode() == "mock":
        return "mock"
    explicit = _env("TRUSTBREAK_AI_PROVIDER").lower()
    if explicit in AI_PROVIDERS:
        return explicit
    if _env(AI_KEY_ENV_VARS["gemini"]):
        return "gemini"
    if _env(AI_KEY_ENV_VARS["anthropic"]):
        return "anthropic"
    return "gemini"


def get_ai_api_key(provider=None):
    """API key for `provider` (default: the resolved provider), or None."""
    provider = provider or get_ai_provider()
    env_name = AI_KEY_ENV_VARS.get(provider)
    return (_env(env_name) or None) if env_name else None


def get_ai_model(provider=None) -> str:
    """TRUSTBREAK_AI_MODEL if set, otherwise the provider's default model."""
    provider = provider or get_ai_provider()
    return _env("TRUSTBREAK_AI_MODEL") or DEFAULT_AI_MODELS.get(provider, DEFAULT_AI_MODELS["gemini"])


def get_ai_timeout() -> float:
    try:
        value = float(os.environ.get("TRUSTBREAK_AI_TIMEOUT_SECONDS", "20"))
    except ValueError:
        return 20.0
    return value if 1 <= value <= 120 else 20.0
