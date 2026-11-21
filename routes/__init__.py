"""
Routes package registering all modular Flask Blueprints.
"""

from flask import Flask
from routes.media import media_bp
from routes.admin_auth import admin_auth_bp
from routes.admin_profiles import admin_profiles_bp
from routes.admin_curation import admin_curation_bp
from routes.admin_tracks import admin_tracks_bp
from routes.admin_series import admin_series_bp
from routes.admin_discovery import admin_discovery_bp
from routes.admin_firmware import admin_firmware_bp
from routes.admin_settings import admin_settings_bp
from routes.yoto_oauth import yoto_oauth_bp
from routes.esp32 import esp32_bp
from routes.bridge_stream import bridge_stream_bp
from routes.bridge_cards import bridge_cards_bp
from routes.portal_api import portal_api_bp


def register_blueprints(app: Flask):
    """Registers all application blueprints onto the Flask app."""
    app.register_blueprint(media_bp)
    app.register_blueprint(admin_auth_bp)
    app.register_blueprint(admin_profiles_bp)
    app.register_blueprint(admin_curation_bp)
    app.register_blueprint(admin_tracks_bp)
    app.register_blueprint(admin_series_bp)
    app.register_blueprint(admin_discovery_bp)
    app.register_blueprint(admin_firmware_bp)
    app.register_blueprint(admin_settings_bp)
    app.register_blueprint(yoto_oauth_bp)
    app.register_blueprint(esp32_bp)
    app.register_blueprint(bridge_stream_bp)
    app.register_blueprint(bridge_cards_bp)
    app.register_blueprint(portal_api_bp)
