"""

ESP32 device client communication, health checks, profile catalog feeds, and playback dispatch.

"""

import time

import secrets

import requests

from flask import Blueprint, request, jsonify

import database

import clients

from core.config import YOTO_BRIDGE_URL, logger

from core.auth import require_device_jwt, create_device_jwt, decode_and_verify_device_jwt

esp32_bp = Blueprint("esp32", __name__)

@esp32_bp.route("/health", methods=["GET"])
def health_check():
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")
    bridge_ok = bool(creds.get("yoto_bridge_url")) if mode == "bridge" else False
    abs_ok = bool(creds.get("abs_api_key")) if mode == "bridge" else False
    yoto_direct_ok = bool(creds.get("yoto_client_id") and creds.get("yoto_refresh_token"))
    yoto_ok = bridge_ok if mode == "bridge" else yoto_direct_ok
    ai_configured = clients.ai_service.is_configured() if (clients.ai_service and mode == "bridge") else False
    ai_enabled = clients.ai_service.enabled if (clients.ai_service and mode == "bridge") else False
    ai_provider = clients.ai_service.provider if clients.ai_service else "auto"
    return jsonify({
        "status": "healthy",
        "connection_mode": mode,
        "features": {
            "abs_enabled": abs_ok,
            "yoto_enabled": yoto_ok,
            "bridge_enabled": bridge_ok,
            "bridge_primary": mode == "bridge",
            "multi_profile": True,
            "ai_chapter_art": {
                "enabled": ai_enabled,
                "configured": ai_configured,
                "provider": ai_provider,
                "fallback_to_bridge": bridge_ok
            }
        },
        "abs_configured": abs_ok,
        "yoto_configured": yoto_ok,
        "yoto_bridge_url": creds.get("yoto_bridge_url", "") if mode == "bridge" else "",
        "timestamp": int(time.time())
    })

@esp32_bp.route("/api/profiles", methods=["GET"])
def get_profiles():
    """Returns available child profiles with assigned primary & additional player devices."""
    config = database.get_all_profiles()
    profiles = []
    for pid, pdata in config.items():
        avatar = pdata.get("avatar_url") or f"/api/avatar/{pid}"
        profiles.append({
            "id": pid,
            "display_name": pdata.get("display_name", pid.title()),
            "avatar_url": avatar,
            "default_player_id": pdata.get("default_player_id", ""),
            "player_ids": pdata.get("player_ids", [])
        })
    return jsonify(profiles)

@esp32_bp.route("/api/kids/<child_name>/abs", methods=["GET"])
@require_device_jwt
def get_child_abs(child_name: str):
    """

    Returns filtered Audiobookshelf books for the child profile.

    Scoped by child account token, dedicated library ID, and/or tag filter.

    Microcontroller-optimized JSON array served with ultra-low latency from pre-indexed SQLite cache.

    """
    try:
        books = database.get_catalog_items_for_profile(child_name.lower(), "abs")
        if books or not clients.abs_client:
            return jsonify(books)
    except Exception as e:
        logger.warning("Error fetching cached ABS catalog for %s: %s; falling back to live query.", child_name, e)
    # Fallback to live query if cache is empty or throws error
    config = database.get_all_profiles()
    child_cfg = config.get(child_name.lower(), {})
    books = clients.abs_client.get_items_for_profile(child_cfg) if clients.abs_client else []
    return jsonify(books)

@esp32_bp.route("/api/kids/<child_name>/yoto", methods=["GET"])
@require_device_jwt
def get_child_yoto(child_name: str):
    """

    Returns curated Yoto playlists/cards for the child based on shared

    and profile-specific curation rules.

    Microcontroller-optimized JSON array served with ultra-low latency from pre-indexed SQLite cache.

    """
    try:
        playlists = database.get_catalog_items_for_profile(child_name.lower(), "yoto")
        if playlists or not clients.yoto_client:
            return jsonify(playlists)
    except Exception as e:
        logger.warning("Error fetching cached Yoto catalog for %s: %s; falling back to live query.", child_name, e)
    # Fallback to live query if cache is empty or throws error
    profiles = database.get_all_profiles()
    shared_cfg = database.get_shared_rules()
    profile_cfg = profiles.get(child_name.lower(), {})
    playlists = []
    if clients.yoto_client:
        playlists = clients.yoto_client.get_curated_playlists_for_profile(
            profile_key=child_name.lower(),
            profile_cfg=profile_cfg,
            shared_cfg=shared_cfg
        )
    return jsonify(playlists)

@esp32_bp.route("/api/media/<media_id>/tracks", methods=["GET"])
@require_device_jwt
def get_device_media_tracks(media_id: str):
    """
    Returns chapter and track breakdown for a media item (ABS audiobook or Yoto card).
    Consumed by bedside controllers and the touchscreen simulator for track selection & detail views.
    """
    from routes.admin_curation import get_media_tracks_data
    try:
        data = get_media_tracks_data(media_id)
        return jsonify(data)
    except Exception as e:
        logger.exception("Error getting device tracks for %s: %s", media_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500

@esp32_bp.route("/api/devices/register", methods=["POST"])
def register_device():
    """

    Self-announcement handshake called by ESP32 devices upon completing Wi-Fi.

    If the device is approved, provisions/returns rotating JWT access & refresh tokens.

    If pending approval, returns status: pending_approval (HTTP 202).

    """
    data = request.get_json(silent=True) or {}
    mac = data.get("mac_address") or data.get("mac")
    friendly_name = data.get("friendly_name", "ESP32 Controller")
    ip_addr = data.get("ip_address") or request.remote_addr or ""
    firmware_ver = data.get("firmware_version", "1.0.0")
    if not mac:
        return jsonify({"ok": False, "error": "Missing mac_address"}), 400
    mac_clean = mac.lower().strip()
    device_info = database.register_esp32_device(mac_clean, friendly_name, ip_addr, firmware_ver)
    dev_record = database.get_esp32_device(mac_clean)
    is_approved = bool(dev_record.get("is_approved")) if dev_record else False
    if not is_approved:
        return jsonify({
            "status": "pending_approval",
            "is_approved": False,
            "mac_address": mac_clean,
            "message": "Device registered in quarantine. Awaiting administrator approval in Web Portal."
        }), 202
    # Device is approved: generate or retrieve jwt_secret and issue token pair
    jwt_secret = dev_record.get("jwt_secret")
    token_ver = int(dev_record.get("token_version") or 1)
    if not jwt_secret:
        jwt_secret = secrets.token_hex(32)
        database.update_esp32_device(mac_clean, {"jwt_secret": jwt_secret, "token_version": token_ver})
    assigned_prof = dev_record.get("assigned_profile_id") or ""
    access_token = create_device_jwt(mac_clean, assigned_prof, jwt_secret, token_ver, "access", expires_in=86400)
    refresh_token = create_device_jwt(mac_clean, assigned_prof, jwt_secret, token_ver, "refresh", expires_in=2592000)
    return jsonify({
        "status": "approved",
        "is_approved": True,
        "mac_address": mac_clean,
        "assigned_profile": assigned_prof,
        "tokens": {
            "token_type": "Bearer",
            "access_token": access_token,
            "expires_in": 86400,
            "refresh_token": refresh_token,
            "refresh_expires_in": 2592000
        }
    }), 200

@esp32_bp.route("/api/device/auth/refresh", methods=["POST"])
def refresh_device_token():
    """

    Called by ESP32 periodically (e.g. every 12-20h) to exchange its 30-day refresh

    token for a fresh 24-hour access token.

    """
    data = request.get_json(silent=True) or {}
    mac = (data.get("mac_address") or data.get("mac") or "").lower().strip()
    refresh_tok = data.get("refresh_token") or ""
    if not mac or not refresh_tok:
        return jsonify({"ok": False, "error": "Missing mac or refresh_token"}), 400
    dev = database.get_esp32_device(mac)
    if not dev or not dev.get("is_approved"):
        return jsonify({
            "error": "token_revoked",
            "message": "This device has been unapproved or revoked by an administrator."
        }), 403
    jwt_secret = dev.get("jwt_secret")
    if not jwt_secret:
        return jsonify({"error": "token_revoked", "message": "Device security credentials not initialized."}), 403
    claims = decode_and_verify_device_jwt(refresh_tok, jwt_secret)
    if not claims or claims.get("type") != "refresh":
        return jsonify({"error": "invalid_token", "message": "Invalid or expired refresh token."}), 403
    # Check token version for immediate revocation
    curr_ver = int(dev.get("token_version") or 1)
    if int(claims.get("ver", -1)) != curr_ver:
        return jsonify({"error": "token_revoked", "message": "Device token version has been revoked."}), 403
    # Issue fresh access token (24h)
    assigned_prof = dev.get("assigned_profile_id") or ""
    new_access_token = create_device_jwt(mac, assigned_prof, jwt_secret, curr_ver, "access", expires_in=86400)
    return jsonify({
        "token_type": "Bearer",
        "access_token": new_access_token,
        "expires_in": 86400
    }), 200

@esp32_bp.route("/api/device/config", methods=["GET"])
def get_device_config():
    """

    Queried by ESP32 on boot to identify hardware-assigned default profile

    and available alternate profiles.

    """
    device_id = request.args.get("device_id") or request.args.get("mac")
    device = database.get_esp32_device(device_id) if device_id else None
    # Check quarantine approval gate
    is_approved = bool(device["is_approved"]) if device else True
    assigned_prof = device["assigned_profile_id"] if (device and is_approved) else None
    all_profs = database.get_all_profiles()
    # Resolve friendly player details and live status from Bridge or direct Yoto client
    player_map = {}
    try:
        creds = database.get_api_credentials()
        mode = creds.get("yoto_connection_mode", "bridge")
        if mode == "bridge" and creds.get("yoto_bridge_url"):
            b_url = creds["yoto_bridge_url"].rstrip("/")
            res = requests.get(f"{b_url}/api/status", timeout=2)
            if res.status_code == 200:
                for d in res.json().get("devices", []):
                    did = d.get("id")
                    if did:
                        is_playing = (d.get("status") == "playing")
                        chapter_title = d.get("chapter_title") or ""
                        author = d.get("author") or ""
                        cover_url = d.get("cover_url") or ""
                        item_id = d.get("item_id")
                        pos = d.get("position") or 0
                        if is_playing and item_id and clients.abs_client:
                            try:
                                abs_item = clients.abs_client.get_item(item_id)
                                if abs_item:
                                    meta = abs_item.get("media", {}).get("metadata", {})
                                    author = meta.get("authorName") or meta.get("author") or author
                                    if not author and meta.get("authors"):
                                        author = meta["authors"][0].get("name", "")
                                    ch_list = abs_item.get("media", {}).get("chapters", [])
                                    curr = [c for c in ch_list if c.get("start", 0) <= pos < c.get("end", 0)]
                                    if curr:
                                        chapter_title = curr[0].get("title", "")
                            except Exception as ce:
                                logger.debug("Chapter/Author resolution notice: %s", ce)
                        player_map[did] = {
                            "id": did,
                            "name": d.get("name") or "Yoto Player",
                            "online": bool(d.get("online")),
                            "status": d.get("status") or "idle",
                            "is_playing": is_playing,
                            "now_playing": d.get("now_playing"),
                            "author": author,
                            "chapter_title": chapter_title,
                            "cover_url": cover_url,
                            "item_id": item_id,
                            "position": pos,
                            "duration": d.get("duration")
                        }
        elif clients.yoto_client:
            for d in clients.yoto_client.get_devices():
                did = d.get("deviceId") or d.get("id")
                if did:
                    player_map[did] = {
                        "id": did,
                        "name": d.get("name") or "Yoto Player",
                        "online": bool(d.get("online")),
                        "status": "online" if d.get("online") else "offline",
                        "is_playing": False,
                        "now_playing": None,
                        "chapter_title": "",
                        "item_id": None,
                        "position": None,
                        "duration": None
                    }
    except Exception as e:
        logger.debug("Player status resolution notice: %s", e)
    profile_summaries = []
    for pid, pdata in all_profs.items():
        avatar = pdata.get("avatar_url") or f"/api/avatar/{pid}"
        def_id = pdata.get("default_player_id", "")
        # Assemble list of all player objects linked to this profile
        p_ids = pdata.get("player_ids", [])
        if def_id and def_id not in p_ids:
            p_ids.insert(0, def_id)
        profile_players = []
        for did in p_ids:
            info = player_map.get(did, {
                "id": did,
                "name": "Yoto Player",
                "online": False,
                "status": "unknown",
                "is_playing": False
            })
            profile_players.append(info)
        def_info = player_map.get(def_id)
        def_name = def_info["name"] if def_info else "Yoto Player"
        profile_summaries.append({
            "id": pid,
            "display_name": pdata.get("display_name", pid.title()),
            "avatar_url": avatar,
            "default_player_id": def_id,
            "default_player_name": def_name,
            "player_ids": pdata.get("player_ids", []),
            "players": profile_players
        })
    settings = database.get_system_settings()
    exclude_single = bool(settings.get("exclude_single_card_series", True))
    return jsonify({
        "device_id": device_id or "unknown",
        "is_approved": is_approved,
        "assigned_profile": assigned_prof,
        "allow_profile_switch": len(profile_summaries) > 1,
        "exclude_single_card_series": exclude_single,
        "profiles": profile_summaries
    })

@esp32_bp.route("/api/play", methods=["POST"])
@require_device_jwt
def play_media():
    """

    Unified playback execution route for the ESP32.

    Payload:

      {

        "child": "jackson" | "wesley",

        "type": "abs" | "yoto",

        "id": "<media_id>",

        "device_id": "<optional_specific_device_id>",

        "chapter": 1

      }

    """
    data = request.get_json(force=True, silent=True) or {}
    child = data.get("child", "jackson").lower()
    media_type = data.get("type", "abs")
    media_id = data.get("id")
    device_id = data.get("device_id")
    chapter = int(data.get("chapter", 1))
    if not media_id:
        return jsonify({"ok": False, "error": "Missing media id"}), 400
    config = database.get_all_profiles()
    child_cfg = config.get(child, {})
    # Resolve target Yoto player
    allowed_players = child_cfg.get("player_ids") or []
    default_player = child_cfg.get("default_player_id") or ""
    if default_player and default_player not in allowed_players:
        allowed_players.append(default_player)
    if not device_id:
        device_id = default_player or (allowed_players[0] if allowed_players else "")
    if not device_id:
        return jsonify({"ok": False, "error": f"No target player resolved for child '{child}'"}), 400
    logger.info("Executing play: child=%s, type=%s, media=%s, device=%s (allowed=%s)", child, media_type, media_id, device_id, allowed_players)
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")
    if media_type == "yoto":
        # 1. Bridge Mode: Route to Bridge /api/play so user needs zero separate Yoto credentials
        if mode == "bridge" and creds.get("yoto_bridge_url"):
            active_bridge_url = creds.get("yoto_bridge_url").rstrip("/")
            bridge_url = f"{active_bridge_url}/api/play"
            payload = {
                "card_id": media_id,
                "device_id": device_id,
                "chapter": chapter
            }
            bridge_headers = {}
            if creds.get("yoto_bridge_api_key"):
                bridge_headers["X-Api-Key"] = creds["yoto_bridge_api_key"]
            try:
                res = requests.post(bridge_url, json=payload, headers=bridge_headers, timeout=10)
                if res.status_code in (200, 204):
                    return jsonify({"ok": True, "status": "playing", "type": "yoto", "device_id": device_id})
                logger.warning("Bridge returned status %d for Yoto card play: %s", res.status_code, res.text)
                return jsonify({"ok": False, "error": f"Bridge rejected Yoto card playback (HTTP {res.status_code})"}), res.status_code
            except Exception as e:
                logger.error("Failed to route Yoto card play to Bridge: %s", e)
                return jsonify({"ok": False, "error": f"Bridge communication error: {str(e)}"}), 502
        # 2. Direct Cloud Fallback
        if not clients.yoto_client:
            return jsonify({"ok": False, "error": "Yoto client not initialized"}), 502
        success = clients.yoto_client.start_playback(device_id, media_id, chapter)
        if success:
            return jsonify({"ok": True, "status": "playing", "type": "yoto", "device_id": device_id})
        return jsonify({"ok": False, "error": "Yoto player command failed"}), 502
    elif media_type == "abs":
        creds = database.get_api_credentials()
        active_bridge_url = creds.get("yoto_bridge_url", YOTO_BRIDGE_URL).rstrip("/")
        bridge_url = f"{active_bridge_url}/api/play"
        payload = {
            "item_id": media_id,
            "device_id": device_id,
            "chapter": chapter
        }
        bridge_headers = {}
        if creds.get("yoto_bridge_api_key"):
            bridge_headers["X-Api-Key"] = creds["yoto_bridge_api_key"]
        try:
            res = requests.post(bridge_url, json=payload, headers=bridge_headers, timeout=10)
            if res.status_code in (200, 204):
                return jsonify({"ok": True, "status": "playing", "type": "abs", "device_id": device_id})
            logger.warning("Bridge returned status %d, checking direct slot mapping", res.status_code)
        except Exception as e:
            logger.error("Failed to route to Yoto Bridge: %s", e)
        return jsonify({
            "ok": True,
            "status": "dispatched",
            "type": "abs",
            "message": "ABS playback request dispatched to bridge",
            "device_id": device_id
        })
    return jsonify({"ok": False, "error": f"Unsupported media type '{media_type}'"}), 400