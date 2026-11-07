"""ESP32 Hardware Controller Registry, Quarantine & Token Lifecycle."""
import json
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from .connection import get_db_connection, logger

def register_esp32_device(mac_address: str, friendly_name: str, ip_address: str, firmware_version: str) -> Dict[str, Any]:
    """Registers an ESP32 device upon boot handshake (quarantined by default if new)."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT mac_address, friendly_name, assigned_profile_id, is_approved FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
            existing = cur.fetchone()
            if existing:
                conn.execute("""
                UPDATE esp32_devices 
                SET ip_address = ?, firmware_version = ?, last_seen = CURRENT_TIMESTAMP
                WHERE mac_address = ?;
                """, (ip_address, firmware_version, mac_clean))
                return {
                    "mac_address": mac_clean,
                    "friendly_name": existing["friendly_name"],
                    "assigned_profile_id": existing["assigned_profile_id"],
                    "is_approved": bool(existing["is_approved"]),
                    "status": "updated"
                }
            else:
                conn.execute("""
                INSERT INTO esp32_devices (mac_address, friendly_name, ip_address, firmware_version, is_approved)
                VALUES (?, ?, ?, ?, 0);
                """, (mac_clean, friendly_name or f"ESP32 ({mac_clean[-5:]})", ip_address, firmware_version))
                return {
                    "mac_address": mac_clean,
                    "friendly_name": friendly_name or f"ESP32 ({mac_clean[-5:]})",
                    "assigned_profile_id": None,
                    "is_approved": False,
                    "status": "registered_quarantined"
                }
    finally:
        conn.close()
def get_esp32_device(mac_address: str) -> Optional[Dict[str, Any]]:
    """Retrieves device record by MAC address."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
def list_esp32_devices() -> List[Dict[str, Any]]:
    """Lists all registered devices for Admin Portal Hardware tab."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM esp32_devices ORDER BY last_seen DESC;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
def update_esp32_device(mac_address: str, updates: Dict[str, Any]) -> bool:
    """Updates device friendly name, assigned default profile, or approval state."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT mac_address FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
            if not cur.fetchone():
                return False

            # Merge and serialize settings dictionary into settings_json if provided
            if "settings" in updates and isinstance(updates["settings"], dict):
                existing_settings = {}
                cur.execute("SELECT settings_json FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
                r = cur.fetchone()
                if r and r["settings_json"]:
                    try:
                        import json as _json
                        existing_settings = _json.loads(r["settings_json"]) or {}
                    except Exception:
                        existing_settings = {}
                existing_settings.update(updates["settings"])
                import json as _json
                updates["settings_json"] = _json.dumps(existing_settings)

            fields = []
            values = []
            for k in [
                "friendly_name", "assigned_profile_id", "is_approved",
                "target_firmware_version", "ota_status", "ota_progress", "ota_last_error",
                "jwt_secret", "token_version", "last_token_issued", "parent_pin",
                "lock_player", "locked_player_id", "settings_json"
            ]:
                if k in updates:
                    fields.append(f"{k} = ?")
                    values.append(updates[k])
            if fields:
                values.append(mac_clean)
                query = f"UPDATE esp32_devices SET {', '.join(fields)}, last_seen = CURRENT_TIMESTAMP WHERE mac_address = ?;"
                conn.execute(query, tuple(values))
        return True
    finally:
        conn.close()
def revoke_esp32_device(mac_address: str) -> bool:
    """Instantly revokes device tokens, increments token_version, and places in quarantine."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT mac_address, token_version FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
            row = cur.fetchone()
            if not row:
                return False
            curr_ver = int(row["token_version"] or 1)
            conn.execute("""
                UPDATE esp32_devices
                SET token_version = ?, is_approved = 0, last_seen = CURRENT_TIMESTAMP
                WHERE mac_address = ?;
            """, (curr_ver + 1, mac_clean))
        return True
    finally:
        conn.close()
def delete_esp32_device(mac_address: str) -> bool:
    """Deletes device registration."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DELETE FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
        return True
    finally:
        conn.close()
def prune_stale_devices(hours: int = 48) -> int:
    """Purges unapproved or stale devices not seen in the last `hours`."""
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM esp32_devices
                WHERE is_approved = 0 AND last_seen < datetime('now', '-' || ? || ' hours');
            """, (hours,))
            return cur.rowcount
    finally:
        conn.close()
# ============================================================================
# Media Catalog & Highlights Matrix DAO
# ============================================================================
