"""
Configuration constants and environment settings for StoryDeck Core.
"""

import os
import ipaddress
import logging
import warnings
from pathlib import Path
from dotenv import load_dotenv
import urllib3
import database

# Suppress spurious InsecureRequestWarning when system truststore/pip-system-certs is active on Windows
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

# Load local environment variables (skipped during isolated unit tests)
if os.getenv("STORYDECK_TESTING", "").lower() not in ("1", "true", "yes"):
    load_dotenv()

# Setup logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

class WerkzeugPollingFilter(logging.Filter):
    """
    Suppresses repetitive high-frequency polling requests from noisy INFO logs
    (e.g., /api/device/config, /health, /api/devices/status, /api/player/status) down to DEBUG level.
    """
    def filter(self, record):
        msg = record.getMessage()
        # Filter high frequency polling endpoints
        if any(p in msg for p in ("/api/device/config", "/health", "/api/devices/status", "/api/player/status", "/api/player/devices")):
            return record.levelno >= logging.WARNING
        return True

# Configure root logging
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("storydeck_core")

# Apply filter to Werkzeug logger to quiet continuous HTTP 200 access pings
logging.getLogger("werkzeug").addFilter(WerkzeugPollingFilter())

# Core Environment Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "storydeck_core_secret_key_session_local_development_hex")
PORT = int(os.getenv("PORT", "5055"))
ABS_BASE_URL = os.getenv("ABS_BASE_URL", "http://audiobookshelf:80").rstrip("/")
ABS_API_KEY = os.getenv("ABS_API_KEY", "")
YOTO_CLIENT_ID = os.getenv("YOTO_CLIENT_ID", "")
YOTO_REFRESH_TOKEN = os.getenv("YOTO_REFRESH_TOKEN", "")
CACHE_DIR = Path(os.getenv("CACHE_DIR", "/app/cache/thumbnails" if database.IS_DOCKER else str(Path(__file__).parent.parent / "cache" / "thumbnails")))
AVATARS_DIR = Path(os.getenv("AVATARS_DIR", "/app/data/avatars" if database.IS_DOCKER else str(Path(__file__).parent.parent / "data" / "avatars")))
CUSTOM_ICONS_DIR = Path(os.getenv("CUSTOM_ICONS_DIR", "/app/data/custom_icons" if database.IS_DOCKER else str(Path(__file__).parent.parent / "data" / "custom_icons")))
FIRMWARE_DIR = Path(os.getenv("FIRMWARE_DIR", "/app/data/firmware" if database.IS_DOCKER else str(Path(__file__).parent.parent / "data" / "firmware")))
THUMBNAIL_SIZE = int(os.getenv("THUMBNAIL_SIZE", "100"))
TRUSTED_PROXIES_RAW = os.getenv("TRUSTED_PROXIES", "127.0.0.1")

# Parse trusted proxy networks
TRUSTED_PROXIES = []
for p in TRUSTED_PROXIES_RAW.split(","):
    p_clean = p.strip()
    if p_clean:
        try:
            TRUSTED_PROXIES.append(ipaddress.ip_network(p_clean, strict=False))
        except Exception:
            try:
                TRUSTED_PROXIES.append(ipaddress.ip_network(f"{p_clean}/32", strict=False))
            except Exception as e:
                logger.warning("Failed parsing TRUSTED_PROXIES entry '%s': %s", p_clean, e)

# Ensure directories exist
CACHE_DIR.mkdir(parents=True, exist_ok=True)
AVATARS_DIR.mkdir(parents=True, exist_ok=True)
CUSTOM_ICONS_DIR.mkdir(parents=True, exist_ok=True)
FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
