"""Child Profiles, Device Bindings & Shared Household Curation Rules."""
import json
import sqlite3
from typing import Dict, Any, List, Optional

from .connection import get_db_connection, logger

def get_all_profiles() -> Dict[str, Any]:
    """Returns all profiles formatted for broker ingestion and ESP32 responses."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM profiles ORDER BY created_at ASC;")
        rows = cur.fetchall()
        result = {}
        for r in rows:
            prof_id = r["id"]
            # Fetch allowed/excluded cards
            cur.execute("SELECT media_id, permission FROM profile_media_permissions WHERE profile_id = ?;", (prof_id,))
            perms = cur.fetchall()
            allowed = [p["media_id"] for p in perms if p["permission"] == "allowed"]
            excluded = [p["media_id"] for p in perms if p["permission"] == "excluded"]
            # Fetch profile regexes
            cur.execute("SELECT pattern FROM shared_regex_patterns WHERE target_scope = ?;", (prof_id,))
            match_titles = [row["pattern"] for row in cur.fetchall()]
            player_ids = []
            try:
                player_ids = json.loads(r["player_ids"]) if r["player_ids"] else []
            except Exception:
                player_ids = []
            result[prof_id] = {
                "id": prof_id,
                "display_name": r["display_name"],
                "abs_username": r["abs_username"] if "abs_username" in r.keys() else "",
                "abs_api_key": r["abs_api_key"],
                "abs_library_id": r["abs_library_id"],
                "abs_tag": r["abs_tag"],
                "default_player_id": r["default_player_id"],
                "player_ids": player_ids,
                "avatar_url": r["avatar_url"],
                "avatar_color": r["avatar_color"] if "avatar_color" in r.keys() else "",
                "avatar_initial": r["avatar_initial"] if "avatar_initial" in r.keys() else "",
                "hide_physical": bool(r["hide_physical"]) if "hide_physical" in r.keys() else False,
                "catalog_rotation_limit": int(r["catalog_rotation_limit"]) if "catalog_rotation_limit" in r.keys() and r["catalog_rotation_limit"] is not None else 80,
                "catalog_rotation_hour": int(r["catalog_rotation_hour"]) if "catalog_rotation_hour" in r.keys() and r["catalog_rotation_hour"] is not None else 3,
                "yoto": {
                    "inherit_shared": bool(r["inherit_shared"]),
                    "allowed_card_ids": allowed,
                    "excluded_card_ids": excluded,
                    "match_titles": match_titles
                }
            }
        return result
    finally:
        conn.close()
def get_profile_by_id(profile_id: str) -> Optional[Dict[str, Any]]:
    """Returns single profile config."""
    profiles = get_all_profiles()
    return profiles.get(profile_id)
def upsert_profile(prof_id: str, data: Dict[str, Any]) -> bool:
    """Inserts or updates a child profile and its permission rules."""
    conn = get_db_connection()
    try:
        with conn:
            display_name = data.get("display_name", prof_id.capitalize())
            abs_username = data.get("abs_username", "")
            abs_api_key = data.get("abs_api_key", "")
            abs_library_id = data.get("abs_library_id", "")
            abs_tag = data.get("abs_tag", "")
            default_player_id = data.get("default_player_id", "")
            player_ids = json.dumps(data.get("player_ids", []))
            avatar_url = data.get("avatar_url", "")
            avatar_color = data.get("avatar_color", "")
            avatar_initial = data.get("avatar_initial", "")
            hide_phys = 1 if data.get("hide_physical", False) else 0
            rot_lim = int(data.get("catalog_rotation_limit", 80) or 80)
            rot_hr = int(data.get("catalog_rotation_hour", 3) if data.get("catalog_rotation_hour") is not None else 3)
            yoto = data.get("yoto", {})
            inherit = 1 if yoto.get("inherit_shared", True) else 0
            conn.execute("""
            INSERT INTO profiles (id, display_name, abs_username, abs_api_key, abs_library_id, abs_tag, default_player_id, player_ids, avatar_url, avatar_color, avatar_initial, inherit_shared, hide_physical, catalog_rotation_limit, catalog_rotation_hour, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                display_name = excluded.display_name,
                abs_username = excluded.abs_username,
                abs_api_key = excluded.abs_api_key,
                abs_library_id = excluded.abs_library_id,
                abs_tag = excluded.abs_tag,
                default_player_id = excluded.default_player_id,
                player_ids = excluded.player_ids,
                avatar_url = excluded.avatar_url,
                avatar_color = excluded.avatar_color,
                avatar_initial = excluded.avatar_initial,
                inherit_shared = excluded.inherit_shared,
                hide_physical = excluded.hide_physical,
                catalog_rotation_limit = excluded.catalog_rotation_limit,
                catalog_rotation_hour = excluded.catalog_rotation_hour,
                updated_at = CURRENT_TIMESTAMP;
            """, (prof_id, display_name, abs_username, abs_api_key, abs_library_id, abs_tag, default_player_id, player_ids, avatar_url, avatar_color, avatar_initial, inherit, hide_phys, rot_lim, rot_hr))
            # Reset & rebuild permissions
            conn.execute("DELETE FROM profile_media_permissions WHERE profile_id = ?;", (prof_id,))
            for card_id in yoto.get("allowed_card_ids", []):
                conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'yoto', ?);", (card_id, f"Card {card_id}"))
                conn.execute("INSERT INTO profile_media_permissions (profile_id, media_id, permission) VALUES (?, ?, 'allowed');", (prof_id, card_id))
            for card_id in yoto.get("excluded_card_ids", []):
                conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'yoto', ?);", (card_id, f"Card {card_id}"))
                conn.execute("INSERT INTO profile_media_permissions (profile_id, media_id, permission) VALUES (?, ?, 'excluded');", (prof_id, card_id))
            # Rebuild regexes
            conn.execute("DELETE FROM shared_regex_patterns WHERE target_scope = ?;", (prof_id,))
            for pat in yoto.get("match_titles", []):
                conn.execute("INSERT INTO shared_regex_patterns (target_scope, pattern) VALUES (?, ?);", (prof_id, pat))
        return True
    finally:
        conn.close()
def delete_profile(prof_id: str) -> bool:
    """Deletes a child profile and cascades permissions."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DELETE FROM profiles WHERE id = ?;", (prof_id,))
            conn.execute("DELETE FROM shared_regex_patterns WHERE target_scope = ?;", (prof_id,))
        return True
    finally:
        conn.close()
# ============================================================================
# Shared Household Curation Rules
# ============================================================================
def get_shared_rules() -> Dict[str, Any]:
    """Returns shared household Yoto curation rules."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM shared_rules;")
        rules = {r["key"]: json.loads(r["value"]) for r in cur.fetchall()}
        # Allowed media items (include both 'yoto' and 'yoto_myo'; per-profile exclusions are evaluated per profile in get_catalog_matrix)
        cur.execute("SELECT id FROM media_items WHERE type IN ('yoto', 'yoto_myo');")
        allowed = [r["id"] for r in cur.fetchall()]
        # Regexes
        cur.execute("SELECT pattern FROM shared_regex_patterns WHERE target_scope = 'shared';")
        match_titles = [r["pattern"] for r in cur.fetchall()]
        return {
            "include_all": rules.get("include_all", False),
            "include_myo_by_default": rules.get("include_myo_by_default", True),
            "allowed_card_ids": allowed,
            "match_titles": match_titles
        }
    finally:
        conn.close()
def set_shared_rule(key: str, value: Any):
    """Sets a shared rule key-value pair."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO shared_rules (key, value) VALUES (?, ?);", (key, json.dumps(value)))
    finally:
        conn.close()
# ============================================================================
# Registered ESP32 Hardware & Quarantine Management
# ============================================================================
