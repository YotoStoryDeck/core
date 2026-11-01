"""
==============================================================================
YOTO & AUDIOBOOKSHELF ESP32 CONTROLLER MIDDLEWARE BROKER
==============================================================================
Provides ultra-lightweight REST endpoints, dynamic tag filtering, on-the-fly
thumbnail resizing, and unified playback dispatch for the ESP32-S3 Touchscreen
controller.
==============================================================================
"""

from pathlib import Path
from flask import Flask
import database
from core.config import SECRET_KEY, PORT, logger
from routes import register_blueprints

# Initialize SQLite database and auto-migrate schema
database.init_db()

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

# Start background library refresh scheduler
from core.scheduler import start_scheduler
start_scheduler()

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

# Serve embedded firmware UI prototype simulator
prototype_dir = base_dir.parent / "firmware" / "ui-prototypes"

@app.route("/simulator")
def redirect_simulator():
    from flask import redirect
    return redirect("/simulator/", code=301)

@app.route("/simulator/")
@app.route("/simulator/<path:filename>")
def serve_simulator(filename="index.html"):
    from flask import send_from_directory
    return send_from_directory(str(prototype_dir), filename)




if __name__ == "__main__":
    logger.info("Starting Yoto-ESP32 Middleware Broker on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT)
