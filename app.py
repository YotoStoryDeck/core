"""
==============================================================================
STORYDECK CORE HUB - CONTROLLER MIDDLEWARE ENGINE
==============================================================================
Provides ultra-lightweight REST endpoints, dynamic tag filtering, on-the-fly
thumbnail resizing, and unified playback dispatch for the ESP32-S3 Touchscreen
controller.
==============================================================================
"""

import os
from pathlib import Path
from flask import Flask, jsonify
import database
from core.config import SECRET_KEY, PORT, logger

# Initialize SQLite database and auto-migrate schema before importing routes/clients
database.init_db()

from routes import register_blueprints

# Create Flask application
base_dir = Path(__file__).parent
app = Flask(
    __name__,
    template_folder=str(base_dir / "templates"),
    static_folder=str(base_dir / "static")
)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Register modular blueprints
register_blueprints(app)

# Log version startup banner
from core.version_service import get_installed_version
_version = get_installed_version()
logger.info("============================================================")
logger.info(" 📻 StoryDeck Core Engine - Version: %s", _version)
logger.info("============================================================")

# Start background library refresh scheduler (disabled in isolated test runs)
if os.getenv("STORYDECK_TESTING", "").lower() not in ("1", "true", "yes") and \
   os.getenv("STORYDECK_DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
    from core.scheduler import start_scheduler
    start_scheduler()
    from core.bridge import start_bridge_services
    start_bridge_services()

# Version Endpoint
@app.route("/version", methods=["GET"])
def version_probe():
    from core.version_service import get_installed_version
    return jsonify({"version": get_installed_version()})

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

# Serve Tablet Kiosk & Web Client
kiosk_dir = base_dir / "static" / "kiosk"

@app.route("/kiosk")
@app.route("/kiosk/")
def serve_kiosk_root():
    from flask import send_from_directory
    return send_from_directory(str(kiosk_dir), "index.html")

@app.route("/kiosk/<path:filename>")
def serve_kiosk_file(filename):
    from flask import send_from_directory
    return send_from_directory(str(kiosk_dir), filename)




if __name__ == "__main__":
    logger.info("StoryDeck Core listening on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT)
