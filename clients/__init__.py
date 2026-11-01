"""
Clients package exporting singletons and factory functions.
"""

import os
from pathlib import Path
import database
from core.config import CACHE_DIR, YOTO_BRIDGE_URL
from ai_service import AIService
from icon_engine import IconEngine
from clients.abs_client import ABSClient
from clients.yoto_client import YotoClient

# Global singletons
abs_client: ABSClient = None
yoto_client: YotoClient = None
ai_service: AIService = None
icon_engine: IconEngine = None


def get_initialized_clients():
    """Initializes and returns ABSClient and YotoClient from database credentials."""
    creds = database.get_api_credentials()
    _abs = ABSClient(creds["abs_base_url"], creds["abs_api_key"])
    _yoto = YotoClient(
        client_id=creds.get("yoto_client_id", ""),
        client_secret=creds.get("yoto_client_secret", ""),
        refresh_token=creds.get("yoto_refresh_token", ""),
        bridge_url=creds.get("yoto_bridge_url", ""),
        bridge_api_key=creds.get("yoto_bridge_api_key", "")
    )
    return _abs, _yoto


def reload_clients():
    """Hot-reloads the global client singletons with latest credentials."""
    global abs_client, yoto_client, ai_service, icon_engine
    abs_client, yoto_client = get_initialized_clients()
    ai_service = AIService(os.getenv("YOTO_BRIDGE_URL", YOTO_BRIDGE_URL), CACHE_DIR)
    icon_engine = IconEngine(yoto_client, abs_client, ai_service, database)
    return abs_client, yoto_client, ai_service, icon_engine


# Initialize on import
reload_clients()
