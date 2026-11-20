"""
Shared test isolation bootstrap for StoryDeck Core unit tests.
Redirects DB_PATH, CONFIG_PATH, CACHE_DIR, AVATARS_DIR, and CUSTOM_ICONS_DIR
to an ephemeral temporary directory so tests NEVER read, mutate, rotate, or
destroy the user's live data/broker.db or Yoto OAuth credentials.
"""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_ISOLATION_DIR = None


def ensure_isolated_test_env() -> Path:
    global _ISOLATION_DIR
    if _ISOLATION_DIR is not None:
        return _ISOLATION_DIR

    if os.getenv("STORYDECK_USE_LIVE_DB", "").lower() in ("1", "true", "yes"):
        return Path(os.getenv("DB_PATH", "data/broker.db")).parent

    tmp = Path(tempfile.mkdtemp(prefix="storydeck_test_"))
    _ISOLATION_DIR = tmp

    os.environ["STORYDECK_TESTING"] = "1"
    os.environ["STORYDECK_DISABLE_SCHEDULER"] = "1"
    os.environ["DB_PATH"] = str(tmp / "test_broker.db")
    os.environ["CONFIG_PATH"] = str(tmp / "no_legacy_config.json")
    os.environ["CACHE_DIR"] = str(tmp / "cache")
    os.environ["AVATARS_DIR"] = str(tmp / "avatars")
    os.environ["CUSTOM_ICONS_DIR"] = str(tmp / "custom_icons")
    os.environ["FIRMWARE_DIR"] = str(tmp / "firmware")

    # Prevent accidental fallback to live environment credentials during unit tests
    for env_key in (
        "ABS_BASE_URL", "ABS_API_KEY",
        "YOTO_CLIENT_ID", "YOTO_CLIENT_SECRET", "YOTO_REFRESH_TOKEN",
        "YOTO_BRIDGE_URL", "YOTO_BRIDGE_API_KEY", "YOTO_UI_PIN",
        "TINKER_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"
    ):
        os.environ[env_key] = ""

    atexit.register(lambda p=tmp: shutil.rmtree(p, ignore_errors=True))
    return tmp


ensure_isolated_test_env()
