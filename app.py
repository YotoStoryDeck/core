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

# Serve Wall Tablet Kiosk & Web Client
kiosk_dir = base_dir / "static" / "kiosk"

@app.route("/simulator")
def redirect_simulator():
    from flask import redirect, request
    qs = request.query_string.decode("utf-8")
    target = "/simulator/" + (f"?{qs}" if qs else "")
    return redirect(target, code=301)

@app.route("/kiosk")
@app.route("/kiosk/")
def redirect_kiosk():
    from flask import redirect, request
    qs = request.query_string.decode("utf-8")
    if qs:
        target = f"/simulator/?kiosk=1&{qs}"
    else:
        target = "/simulator/?kiosk=1"
    return redirect(target, code=302)

@app.route("/simulator/")
@app.route("/simulator/<path:filename>")
@app.route("/kiosk/<path:filename>")
def serve_simulator(filename="index.html"):
    from flask import send_from_directory
    return send_from_directory(str(kiosk_dir), filename)




if __name__ == "__main__":
    logger.info("Starting Yoto-ESP32 Middleware Broker on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT)
