"""
Admin hardware displays and discovery blueprint (Yoto players, ABS users, household match).
"""

import re
from typing import Dict, Any, List
import requests
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import logger
from core.auth import require_admin

admin_discovery_bp = Blueprint("admin_discovery", __name__)


# ============================================================================
# Registered ESP32 Hardware Displays Management
# ============================================================================

@admin_discovery_bp.route("/api/admin/devices", methods=["GET"])
@require_admin
def admin_list_devices():
    """Lists registered hardware displays."""
    return jsonify(database.list_esp32_devices())


@admin_discovery_bp.route("/api/admin/devices/<mac_address>", methods=["PUT"])
@require_admin
def admin_update_device(mac_address: str):
    """Updates device approval state, friendly name, or default profile assignment."""
    data = request.get_json(silent=True) or {}
    success = database.update_esp32_device(mac_address, data)
    if success:
        return jsonify({"ok": True, "message": "Device updated."})
    return jsonify({"ok": False, "error": "Device not found."}), 404


@admin_discovery_bp.route("/api/admin/devices/<mac_address>", methods=["DELETE"])
@require_admin
def admin_delete_device(mac_address: str):
    """Deletes device registration."""
    success = database.delete_esp32_device(mac_address)
    return jsonify({"ok": success})


@admin_discovery_bp.route("/api/admin/devices/prune", methods=["POST"])
@require_admin
def admin_prune_devices():
    """Purges unapproved devices that have not pinged or connected within 48 hours."""
    data = request.get_json(silent=True) or {}
    hours = int(data.get("hours", 48))
    count = database.prune_stale_devices(hours=hours)
    return jsonify({"ok": True, "pruned": count, "message": f"Pruned {count} stale device(s)."})


@admin_discovery_bp.route("/api/admin/devices/<mac_address>/ping", methods=["GET"])
@require_admin
def admin_ping_device(mac_address: str):
    """Actively probes device IP to test live reachability and update last_seen timestamp."""
    dev = database.get_esp32_device(mac_address)
    if not dev:
        return jsonify({"ok": False, "error": "Device not found."}), 404
    ip = dev.get("ip_address")
    if not ip or ip.startswith("172.") or ip.startswith("127."):
        return jsonify({"ok": False, "online": False, "error": f"Invalid or non-LAN IP: {ip}"}), 200
    try:
        # Probe touch web server /heap endpoint
        res = requests.get(f"http://{ip}/heap", timeout=1.5)
        if res.status_code == 200:
            database.update_esp32_device(mac_address, {})  # updates last_seen = CURRENT_TIMESTAMP
            return jsonify({"ok": True, "online": True, "ip": ip, "data": res.json()})
    except Exception as e:
        logger.debug("Ping device %s (%s) error: %s", mac_address, ip, e)
    return jsonify({"ok": True, "online": False, "ip": ip, "error": "Host unreachable on port 80"}), 200


@admin_discovery_bp.route("/api/admin/devices/<mac_address>/revoke", methods=["POST"])
@require_admin
def admin_revoke_device(mac_address: str):
    """
    Instantly invalidates all active tokens for this ESP32 controller
    by incrementing token_version and placing the device in quarantine.
    """
    success = database.revoke_esp32_device(mac_address)
    if success:
        return jsonify({
            "ok": True,
            "status": "revoked",
            "mac": mac_address,
            "message": "Device tokens invalidated. Controller placed in quarantine."
        })
    return jsonify({"ok": False, "error": "Device not found."}), 404


@admin_discovery_bp.route("/api/admin/devices/<mac_address>/reset-pin", methods=["POST"])
@require_admin
def admin_reset_device_pin(mac_address: str):
    """
    Pushes an OTA PIN reset to the ESP32 controller.
    Validates that the provided PIN is exactly 4 numeric digits.
    Defaults to '1234' if none provided or left empty.
    """
    data = request.get_json(silent=True) or {}
    new_pin = str(data.get("pin") or "1234").strip()
    if not (len(new_pin) == 4 and new_pin.isdigit()):
        return jsonify({"ok": False, "error": "Parent PIN must be exactly 4 numeric digits (e.g. 1234)."}), 400

    dev = database.get_esp32_device(mac_address)
    if not dev:
        return jsonify({"ok": False, "error": "Device not found."}), 404

    success = database.update_esp32_device(mac_address, {"parent_pin": new_pin})
    if success:
        logger.info("OTA Parent PIN reset for device %s to %s", mac_address, new_pin)
        return jsonify({
            "ok": True,
            "mac": mac_address,
            "parent_pin": new_pin,
            "message": f"Parent PIN successfully reset to {new_pin}."
        })
    return jsonify({"ok": False, "error": "Failed to update device PIN."}), 500



# ============================================================================
# Discovery & Household Matching Endpoints
# ============================================================================

@admin_discovery_bp.route("/api/admin/discovery/players", methods=["GET"])
@require_admin
def admin_discovery_players():
    """Lists registered Yoto players from Bridge or direct Yoto cloud."""
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")

    # If in bridge mode, probe bridge status
    if mode == "bridge" and creds.get("yoto_bridge_url"):
        try:
            b_url = creds["yoto_bridge_url"].rstrip("/")
            res = requests.get(f"{b_url}/api/status", timeout=5)
            if res.status_code == 200:
                data = res.json()
                players = []
                for d in data.get("devices", []):
                    players.append({
                        "id": d.get("id"),
                        "name": d.get("name", "Yoto Player"),
                        "online": d.get("online", False),
                        "status": d.get("status", "idle")
                    })
                return jsonify(players)
        except Exception as e:
            logger.debug("Bridge player query notice: %s", e)

    # Fallback to direct cloud devices
    direct_players = clients.yoto_client.get_devices() if clients.yoto_client else []
    players = []
    for d in direct_players:
        did = d.get("deviceId") or d.get("id")
        players.append({
            "id": did,
            "name": d.get("name", "Yoto Player"),
            "online": d.get("online", False),
            "status": "online" if d.get("online") else "offline"
        })
    return jsonify(players)


@admin_discovery_bp.route("/api/admin/discovery/abs-users", methods=["GET"])
@require_admin
def admin_discovery_abs_users():
    """Fetches list of registered Audiobookshelf users for profile dropdown binding."""
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")
    if mode != "bridge" or not clients.abs_client or not clients.abs_client.base_url:
        return jsonify([])

    try:
        res = requests.get(f"{clients.abs_client.base_url}/api/users", headers=clients.abs_client.get_headers(), timeout=6)
        if res.status_code == 200:
            users_raw = res.json().get("users", [])
            users = []
            for u in users_raw:
                users.append({
                    "id": u.get("id"),
                    "username": u.get("username", ""),
                    "type": u.get("type", "user"),
                    "is_admin": u.get("type") in ("root", "admin")
                })
            return jsonify(users)
    except Exception as e:
        logger.debug("ABS users discovery query notice: %s", e)

    return jsonify([])


@admin_discovery_bp.route("/api/admin/discovery/household-match", methods=["GET"])
@require_admin
def admin_discovery_household_match():
    """
    Simultaneously probes Yoto players and ABS users, performing fuzzy string matching
    to suggest automated child profile bindings with 1 click.
    """
    creds = database.get_api_credentials()
    # 1. Fetch Yoto Players
    players = []
    if creds.get("yoto_connection_mode") == "bridge" and creds.get("yoto_bridge_url"):
        try:
            b_url = creds["yoto_bridge_url"].rstrip("/")
            res = requests.get(f"{b_url}/api/status", timeout=5)
            if res.status_code == 200:
                players = res.json().get("devices", [])
        except Exception:
            pass
    if not players and clients.yoto_client:
        players = clients.yoto_client.get_devices()

    # 2. Fetch ABS Users
    abs_users = []
    if clients.abs_client and clients.abs_client.base_url:
        try:
            res = requests.get(f"{clients.abs_client.base_url}/api/users", headers=clients.abs_client.get_headers(), timeout=6)
            if res.status_code == 200:
                abs_users = res.json().get("users", [])
        except Exception as e:
            logger.debug("ABS user query notice: %s", e)

    existing_profiles = database.get_all_profiles()

    matches = []
    matched_user_ids = set()

    for p in players:
        pid = p.get("id") or p.get("deviceId")
        pname = p.get("name", "")
        clean_pname = re.sub(r"[^a-zA-Z0-9\s]", "", pname.lower())
        p_words = set(clean_pname.split())

        matched_user = None
        for u in abs_users:
            uname = (u.get("username") or "").lower()
            if uname in ("root", "admin", "administrator"):
                continue
            if uname in p_words or uname in clean_pname:
                matched_user = u
                matched_user_ids.add(u.get("id"))
                break

        suggested_id = (matched_user.get("username") if matched_user else re.sub(r"[^a-zA-Z0-9_]", "_", clean_pname)).strip("_")
        display = matched_user.get("username").title() if matched_user else pname

        matches.append({
            "suggested_profile_id": suggested_id,
            "display_name": display,
            "matched_abs_user": {
                "id": matched_user.get("id"),
                "username": matched_user.get("username")
            } if matched_user else None,
            "matched_yoto_player": {
                "id": pid,
                "name": pname,
                "online": p.get("online", False)
            },
            "confidence": 0.95 if matched_user else 0.50,
            "already_exists": suggested_id.lower() in existing_profiles
        })

    unmatched_users = [
        {"id": u.get("id"), "username": u.get("username")}
        for u in abs_users
        if u.get("id") not in matched_user_ids and u.get("username", "").lower() not in ("root", "admin")
    ]

    return jsonify({
        "matches": matches,
        "unmatched_abs_users": unmatched_users
    })


@admin_discovery_bp.route("/api/admin/discovery/auto-import", methods=["POST"])
@require_admin
def admin_discovery_auto_import():
    """Provisions an array of approved child profiles into SQLite."""
    data = request.get_json(silent=True) or {}
    profiles = data.get("profiles", [])
    if not profiles:
        return jsonify({"ok": False, "error": "No profiles provided to import."}), 400

    imported_count = 0
    for p in profiles:
        pid = (p.get("id") or "").lower().strip()
        if not pid:
            continue
        default_player = p.get("default_player_id") or ""
        player_list = p.get("player_ids") or ([default_player] if default_player else [])
        payload = {
            "display_name": p.get("display_name") or pid.title(),
            "abs_username": p.get("abs_username") or "",
            "abs_api_key": p.get("abs_api_key") or "",
            "abs_tag": p.get("abs_tag") or "",
            "abs_library_id": p.get("abs_library_id") or "",
            "default_player_id": default_player,
            "player_ids": player_list,
            "yoto": {
                "inherit_shared": True,
                "allowed_card_ids": [],
                "excluded_card_ids": [],
                "match_titles": []
            }
        }
        if database.upsert_profile(pid, payload):
            imported_count += 1

    return jsonify({"ok": True, "imported_count": imported_count})
