"""System Settings, Third-Party API Credentials & Master API Key Management."""
import os
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from .connection import get_db_connection, LEGACY_CONFIG_PATH, DB_PATH, logger

def get_system_settings() -> Dict[str, Any]:
    """Returns global broker settings."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM system_settings;")
        res = {}
        for r in cur.fetchall():
            try:
                res[r["key"]] = json.loads(r["value"])
            except Exception:
                res[r["key"]] = r["value"]
        
        defaults = {
            "thumbnail_size": 100,
            "thumbnail_quality": 80,
            "cache_ttl_hours": 168,
            "abs_default_children_tags": ["Children"],
            "exclude_single_card_series": True,
            "auto_library_refresh_enabled": True,
            "auto_library_refresh_hours": 6,
            "ai_chapter_art": {
                "enabled": False,
                "provider": "openrouter",
                "fallback_to_bridge": True
            }
        }
        for k, v in defaults.items():
            if k not in res:
                res[k] = v
        return res
    finally:
        conn.close()
def set_system_setting(key: str, value: Any) -> bool:
    """Saves or updates a global broker setting into SQLite system_settings table."""
    conn = get_db_connection()
    try:
        val_str = json.dumps(value) if not isinstance(value, str) else value
        conn.execute("""
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP;
        """, (key, val_str))
        conn.commit()
        return True
    except Exception as e:
        logger.error("Failed to set system setting %s: %s", key, e)
        return False
    finally:
        conn.close()
# ============================================================================
# API Credentials & Service Connection DAO
# ============================================================================
def get_api_credentials() -> Dict[str, str]:
    """
    Returns upstream API credentials, prioritizing SQLite system_settings
    and falling back to environment variables.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        keys = [
            "abs_base_url", "abs_api_key",
            "yoto_connection_mode",
            "yoto_client_id", "yoto_client_secret", "yoto_refresh_token",
            "yoto_bridge_url", "yoto_bridge_api_key", "yoto_ui_pin",
            "tinker_api_key",
            "gemini_api_key", "anthropic_api_key", "openrouter_api_key"
        ]
        cur.execute(f"SELECT key, value FROM system_settings WHERE key IN ({','.join(['?']*len(keys))});", keys)
        db_creds = {}
        for r in cur.fetchall():
            try:
                db_creds[r["key"]] = json.loads(r["value"])
            except Exception:
                db_creds[r["key"]] = r["value"]
        # Fallback helper to inspect legacy config.json if unpopulated
        legacy_data = {}
        if LEGACY_CONFIG_PATH.exists():
            try:
                with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                    legacy_data = json.load(f)
            except Exception:
                pass
        legacy_settings = legacy_data.get("settings", {})
        def resolve_val(db_key: str, env_key: str, default_val: str = "") -> str:
            val = db_creds.get(db_key)
            if val:
                return str(val).strip()
            env_val = os.getenv(env_key)
            if env_val:
                return str(env_val).strip()
            legacy_val = legacy_data.get(db_key) or legacy_settings.get(db_key)
            if legacy_val:
                return str(legacy_val).strip()
            return default_val
        # Infer mode if unset: bridge if bridge url present or yoto keys empty
        raw_mode = db_creds.get("yoto_connection_mode")
        if not raw_mode:
            raw_mode = os.getenv("YOTO_CONNECTION_MODE", "bridge")
        return {
            "abs_base_url": resolve_val("abs_base_url", "ABS_BASE_URL", "http://audiobookshelf:80"),
            "abs_api_key": resolve_val("abs_api_key", "ABS_API_KEY", ""),
            "yoto_connection_mode": str(raw_mode).strip(),
            "yoto_client_id": resolve_val("yoto_client_id", "YOTO_CLIENT_ID", ""),
            "yoto_client_secret": resolve_val("yoto_client_secret", "YOTO_CLIENT_SECRET", ""),
            "yoto_refresh_token": resolve_val("yoto_refresh_token", "YOTO_REFRESH_TOKEN", ""),
            "yoto_bridge_url": resolve_val("yoto_bridge_url", "YOTO_BRIDGE_URL", "http://yoto-bridge:8080"),
            "yoto_bridge_api_key": resolve_val("yoto_bridge_api_key", "YOTO_BRIDGE_API_KEY", ""),
            "yoto_ui_pin": resolve_val("yoto_ui_pin", "YOTO_UI_PIN", ""),
            "tinker_api_key": resolve_val("tinker_api_key", "TINKER_API_KEY", ""),
            "gemini_api_key": resolve_val("gemini_api_key", "GEMINI_API_KEY", ""),
            "anthropic_api_key": resolve_val("anthropic_api_key", "ANTHROPIC_API_KEY", ""),
            "openrouter_api_key": resolve_val("openrouter_api_key", "OPENROUTER_API_KEY", "")
        }
    finally:
        conn.close()
def update_api_credentials(creds: Dict[str, str]) -> bool:
    """Updates API credentials in SQLite system_settings."""
    allowed = {
        "abs_base_url", "abs_api_key",
        "yoto_connection_mode",
        "yoto_client_id", "yoto_client_secret", "yoto_refresh_token",
        "yoto_bridge_url", "yoto_bridge_api_key", "yoto_ui_pin",
        "tinker_api_key",
        "gemini_api_key", "anthropic_api_key", "openrouter_api_key"
    }
    conn = get_db_connection()
    try:
        with conn:
            for k, v in creds.items():
                if k in allowed and v is not None:
                    conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?);", (k, json.dumps(str(v).strip())))
        return True
    finally:
        conn.close()
# ============================================================================
# Master API Key DAO
# ============================================================================
def get_master_api_key_details() -> Dict[str, Any]:
    """Returns the Broker's master API key details including created and updated timestamps."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value, updated_at FROM system_settings WHERE key = 'master_api_key';")
        row = cur.fetchone()
        if row and row["value"]:
            try:
                key_val = json.loads(row["value"])
            except Exception:
                key_val = row["value"]
            return {
                "api_key": key_val,
                "updated_at": row["updated_at"] or ""
            }
        
        # If missing, generate new 32-char hex key
        new_key = secrets.token_hex(16)
        conn.execute("INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES ('master_api_key', ?, CURRENT_TIMESTAMP);", (json.dumps(new_key),))
        conn.commit()
        return {
            "api_key": new_key,
            "updated_at": ""
        }
    finally:
        conn.close()
def get_master_api_key() -> str:
    """Returns the raw 32-character hex master API key."""
    return get_master_api_key_details()["api_key"]
def regenerate_master_api_key() -> str:
    """Generates a fresh 32-character hex master API key, invalidating prior tokens."""
    new_key = secrets.token_hex(16)
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('master_api_key', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP;
            """, (json.dumps(new_key),))
        logger.info("Regenerated Broker master API key.")
        return new_key
    finally:
        conn.close()
