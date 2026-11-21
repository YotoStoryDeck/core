"""
ESP32 device client communication, health checks, profile catalog feeds, and playback dispatch.
"""
import json
import time
import secrets
import base64
from typing import Optional, Tuple
import requests
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import AVATARS_DIR, logger
from core.auth import (
    require_device_jwt, create_device_jwt, decode_and_verify_device_jwt, get_current_device
)
from core.version_service import get_installed_version

esp32_bp = Blueprint("esp32", __name__)

# In-memory tracker of last played chapter per (child_id, media_id) or (device_id, media_id) for Yoto cards
_yoto_resume_state = {}


@esp32_bp.route("/health", methods=["GET"])
def health_check():
    creds = database.get_api_credentials()
    abs_ok = bool(creds.get("abs_base_url") and creds.get("abs_api_key"))
    yoto_ok = bool(creds.get("yoto_client_id") and creds.get("yoto_refresh_token"))
    ai_enabled = bool(clients.ai_service and clients.ai_service.enabled)
    ai_configured = bool(clients.ai_service and clients.ai_service.is_configured())
    ai_provider = clients.ai_service.provider if clients.ai_service else "auto"
    return jsonify({
        "status": "healthy",
        "version": get_installed_version(),
        "connection_mode": "standalone",
        "features": {
            "abs_enabled": abs_ok,
            "yoto_enabled": yoto_ok,
            "embedded_bridge": True,
            "multi_profile": True,
            "ai_chapter_art": {
                "enabled": ai_enabled,
                "configured": ai_configured,
                "provider": ai_provider
            }
        },
        "abs_configured": abs_ok,
        "yoto_configured": yoto_ok,
        "timestamp": int(time.time())
    })


def _resolve_profile_avatar_info(pid: str, pdata: dict) -> tuple[str, bool]:
    """Normalizes profile avatar_url to /api/avatar/<pid>?t=<mtime> when a custom avatar exists."""
    from routes.admin_profiles import _materialize_avatar_bytes_to_disk, sync_all_bubble_avatars

    avatar_path = AVATARS_DIR / f"{pid}.jpg"
    raw_av = str(pdata.get("avatar_url") or "").strip()

    if not avatar_path.exists() and raw_av:
        if raw_av.startswith("data:image/") and ";base64," in raw_av:
            try:
                raw_bytes = base64.b64decode(raw_av.split(";base64,", 1)[1])
                norm = _materialize_avatar_bytes_to_disk(pid, raw_bytes)
                if norm:
                    pdata["avatar_url"] = norm
                    database.upsert_profile(pid, pdata)
                    raw_av = norm
            except Exception as e:
                logger.warning("Failed materializing base64 avatar for profile %s: %s", pid, e)
        elif raw_av.startswith("http://") or raw_av.startswith("https://"):
            try:
                res = requests.get(raw_av, timeout=6)
                if res.status_code == 200 and res.content:
                    norm = _materialize_avatar_bytes_to_disk(pid, res.content)
                    if norm:
                        pdata["avatar_url"] = norm
                        database.upsert_profile(pid, pdata)
                        raw_av = norm
            except Exception as e:
                logger.warning("Failed downloading avatar for profile %s from %s: %s", pid, raw_av, e)

    if avatar_path.exists():
        mtime = int(avatar_path.stat().st_mtime)
        return f"/api/avatar/{pid}?t={mtime}", True

    bubble_path = AVATARS_DIR / f"{pid}_bubble.jpg"
    if not bubble_path.exists():
        sync_all_bubble_avatars()
    if bubble_path.exists():
        mtime = int(bubble_path.stat().st_mtime)
        return f"/api/avatar/{pid}?t={mtime}", False

    has_custom = bool(raw_av and not raw_av.endswith(f"/api/avatar/{pid}"))
    return (raw_av or f"/api/avatar/{pid}"), has_custom


@esp32_bp.route("/api/profiles", methods=["GET"])
def get_profiles():
    """Returns available child profiles with assigned primary & additional player devices."""
    config = database.get_all_profiles()
    profiles = []
    for pid, pdata in config.items():
        avatar, has_custom = _resolve_profile_avatar_info(pid, pdata)
        profiles.append({
            "id": pid,
            "display_name": pdata.get("display_name", pid.title()),
            "avatar_url": avatar,
            "has_custom_avatar": has_custom,
            "avatar_color": pdata.get("avatar_color", ""),
            "avatar_initial": pdata.get("avatar_initial", ""),
            "default_playback_mode": pdata.get("default_playback_mode", "streaming"),
            "default_player_id": pdata.get("default_player_id", ""),
            "player_ids": pdata.get("player_ids", [])
        })
    return jsonify(profiles)


def _resolve_client_type() -> str:
    """Detects whether client is a Tablet Kiosk / Web Companion or an ESP32 hardware device."""
    client_arg = (request.args.get("client") or request.args.get("device_type") or "").strip().lower()
    if client_arg == "kiosk":
        return "kiosk"
    try:
        dev_info = get_current_device()
        if dev_info and dev_info.get("device"):
            dev = dev_info["device"]
            fw = (dev.get("firmware_version") or "").lower()
            name = (dev.get("friendly_name") or "").lower()
            if "-web" in fw or "kiosk" in name or "browser" in name:
                return "kiosk"
    except Exception as e:
        logger.debug("Client type resolution fallback for device: %s", e)
    return "touch"


@esp32_bp.route("/api/kids/<child_name>/abs", methods=["GET"])
@require_device_jwt
def get_child_abs(child_name: str):
    """
    Returns filtered Audiobookshelf books for the child profile.
    Scoped by child account token, dedicated library ID, and/or tag filter.
    """
    client_type = _resolve_client_type()
    try:
        books = database.get_catalog_items_for_profile(child_name.lower(), "abs", client_type=client_type)
        if books or not clients.abs_client:
            return jsonify(books)
    except Exception as e:
        logger.warning("Error fetching cached ABS catalog for %s: %s; falling back to live query.", child_name, e)
    config = database.get_all_profiles()
    child_cfg = config.get(child_name.lower(), {})
    books = clients.abs_client.get_items_for_profile(child_cfg) if clients.abs_client else []
    return jsonify(books)


@esp32_bp.route("/api/kids/<child_name>/yoto", methods=["GET"])
@require_device_jwt
def get_child_yoto(child_name: str):
    """Returns curated Yoto playlists/cards for the child based on shared and profile rules."""
    client_type = _resolve_client_type()
    try:
        playlists = database.get_catalog_items_for_profile(child_name.lower(), "yoto", client_type=client_type)
        if playlists or not clients.yoto_client:
            return jsonify(playlists)
    except Exception as e:
        logger.warning("Error fetching cached Yoto catalog for %s: %s; falling back to live query.", child_name, e)
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
    """Returns sanitized chapter and track breakdown for a media item."""
    from core.media_utils import get_media_tracks_data
    try:
        data = get_media_tracks_data(media_id)
        if isinstance(data, dict):
            if "title" in data and isinstance(data["title"], str):
                data["title"] = database.sanitize_display_text(data["title"])
            if "tracks" in data and isinstance(data["tracks"], list):
                for trk in data["tracks"]:
                    if isinstance(trk, dict) and "title" in trk and isinstance(trk["title"], str):
                        trk["title"] = database.sanitize_display_text(trk["title"])
        return jsonify(data)
    except Exception as e:
        logger.exception("Error getting device tracks for %s: %s", media_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@esp32_bp.route("/api/devices/register", methods=["POST"])
@esp32_bp.route("/api/device/register", methods=["POST"])
def register_device():
    """
    Self-announcement handshake called by ESP32 devices upon completing Wi-Fi.
    If approved, provisions/returns rotating JWT access & refresh tokens.
    """
    data = request.get_json(silent=True) or {}
    mac = data.get("mac_address") or data.get("mac") or data.get("device_id")
    friendly_name = data.get("friendly_name", "ESP32 Controller")
    ip_addr = data.get("ip_address") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.headers.get("X-Real-IP") or request.remote_addr or ""
    firmware_ver = data.get("firmware_version", "1.0.0")
    boot_state = (data.get("boot_state") or "").strip().lower()
    if not mac:
        return jsonify({"ok": False, "error": "Missing mac_address"}), 400
    mac_clean = mac.lower().strip()
    database.register_esp32_device(mac_clean, friendly_name, ip_addr, firmware_ver, boot_state=boot_state)
    dev_record = database.get_esp32_device(mac_clean)
    is_approved = bool(dev_record.get("is_approved")) if dev_record else False
    if not is_approved:
        return jsonify({
            "status": "pending_approval",
            "is_approved": False,
            "mac_address": mac_clean,
            "message": "Device registered in quarantine. Awaiting administrator approval in Web Portal."
        }), 202
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
    """Exchanges a 30-day refresh token for a fresh 24-hour access token."""
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
    curr_ver = int(dev.get("token_version") or 1)
    if int(claims.get("ver", -1)) != curr_ver:
        return jsonify({"error": "token_revoked", "message": "Device token version has been revoked."}), 403
    assigned_prof = dev.get("assigned_profile_id") or ""
    new_access_token = create_device_jwt(mac, assigned_prof, jwt_secret, curr_ver, "access", expires_in=86400)
    return jsonify({
        "token_type": "Bearer",
        "access_token": new_access_token,
        "expires_in": 86400
    }), 200


@esp32_bp.route("/api/device/config", methods=["GET"])
def get_device_config():
    """Returns device boot configuration, profiles, players, and OTA state."""
    device_id = request.args.get("device_id") or request.args.get("mac")
    device = database.get_esp32_device(device_id) if device_id else None
    is_approved = bool(device["is_approved"]) if device else True
    assigned_prof = device["assigned_profile_id"] if (device and is_approved) else None
    all_profs = database.get_all_profiles()
    from core.player_service import get_live_players_map
    player_map = get_live_players_map()
    from routes.admin_profiles import compute_household_monograms, PALETTE_COLORS
    monograms = compute_household_monograms()
    profile_summaries = []
    for pid, pdata in all_profs.items():
        avatar, has_custom_av = _resolve_profile_avatar_info(pid, pdata)
        def_id = pdata.get("default_player_id", "")
        p_ids = list(pdata.get("player_ids", []))
        if def_id and def_id not in p_ids:
            p_ids.insert(0, def_id)
        profile_players = [
            player_map.get(did, {
                "id": did,
                "name": "Yoto Player",
                "online": False,
                "status": "unknown",
                "is_playing": False,
                "volume": 50,
                "volume_max": 100
            })
            for did in p_ids
        ]
        def_info = player_map.get(def_id)
        def_name = def_info["name"] if def_info else (profile_players[0]["name"] if profile_players else "Yoto Player")

        av_color = pdata.get("avatar_color") or ""
        if not av_color.startswith("#"):
            clean_str = (pdata.get("display_name") or pid).strip().lower()
            h = 0
            for ch in clean_str:
                h = (h * 31 + ord(ch)) & 0xFFFFFFFF
            av_color = PALETTE_COLORS[h % len(PALETTE_COLORS)]
        av_initial = pdata.get("avatar_initial") or monograms.get(pid) or (pdata.get("display_name", pid)[:1].upper() or "C")

        profile_summaries.append({
            "id": pid,
            "display_name": pdata.get("display_name", pid.title()),
            "avatar_url": avatar,
            "has_custom_avatar": has_custom_av,
            "avatar_color": av_color,
            "avatar_initial": av_initial,
            "default_player_id": def_id,
            "default_player_name": def_name,
            "player_ids": pdata.get("player_ids", []),
            "players": profile_players,
            "catalog_rotation_limit": int(pdata.get("catalog_rotation_limit", 80) or 80),
            "catalog_rotation_hour": int(pdata.get("catalog_rotation_hour", 3) or 3),
            "hide_physical": bool(pdata.get("hide_physical", False))
        })
    settings = database.get_system_settings()
    exclude_single = bool(settings.get("exclude_single_card_series", True))
    parent_pin = device.get("parent_pin", "") if device else ""
    lock_player = bool(device.get("lock_player", False)) if device else False
    locked_player_id = (device.get("locked_player_id") or "") if device else ""
    dev_settings = {}
    if device and device.get("settings_json"):
        try:
            dev_settings = json.loads(device["settings_json"]) or {}
        except Exception:
            dev_settings = {}
    can_switch = (len(profile_summaries) > 1) and not bool(assigned_prof)
    latest_rel = database.get_latest_firmware_release()
    return jsonify({
        "device_id": device_id or "unknown",
        "is_approved": is_approved,
        "assigned_profile": assigned_prof or "",
        "parent_pin": parent_pin,
        "lock_player": lock_player,
        "locked_player_id": locked_player_id,
        "settings": dev_settings,
        "allow_profile_switch": can_switch,
        "exclude_single_card_series": exclude_single,
        "ota": {
            "ota_status": (device.get("ota_status") or "idle") if device else "idle",
            "ota_progress": int(device.get("ota_progress") or 0) if device else 0,
            "target_firmware_version": (device.get("target_firmware_version") or "") if device else "",
            "latest_firmware_version": (latest_rel.get("version") or "") if latest_rel else "",
        },
        "profiles": profile_summaries
    })


@esp32_bp.route("/api/device/settings", methods=["PUT", "POST"])
def update_device_settings():
    """
    Persists Grown-Ups settings (Parent PIN, lock_player, locked_player_id,
    sleep timer, bedtime/wake schedules, clock size, blockRemotePlayback) back to SQLite.
    """
    data = request.get_json(force=True, silent=True) or {}
    device_id = (data.get("device_id") or data.get("mac") or request.args.get("device_id") or "").lower().strip()
    if not device_id:
        return jsonify({"ok": False, "error": "Missing device_id"}), 400

    dev = database.get_esp32_device(device_id)
    if not dev:
        ip_addr = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or ""
        database.register_esp32_device(device_id, data.get("friendly_name", "StoryDeck Kiosk"), ip_addr, "kiosk-web")
        dev = database.get_esp32_device(device_id)

    updates = {}
    if "parent_pin" in data:
        pin_val = str(data["parent_pin"] or "").strip()
        if len(pin_val) == 4 and pin_val.isdigit():
            updates["parent_pin"] = pin_val
    if "lock_player" in data:
        updates["lock_player"] = 1 if bool(data["lock_player"]) else 0
    if "locked_player_id" in data:
        updates["locked_player_id"] = str(data["locked_player_id"] or "").strip()
    if "assigned_profile" in data or "assigned_profile_id" in data:
        updates["assigned_profile_id"] = str(data.get("assigned_profile") or data.get("assigned_profile_id") or "").strip()
    if "friendly_name" in data and data["friendly_name"]:
        updates["friendly_name"] = str(data["friendly_name"]).strip()

    if "settings" in data and isinstance(data["settings"], dict):
        existing_settings = {}
        if dev and dev.get("settings_json"):
            try:
                existing_settings = json.loads(dev["settings_json"]) or {}
            except Exception:
                existing_settings = {}
        existing_settings.update(data["settings"])
        updates["settings_json"] = json.dumps(existing_settings)

    if updates:
        database.update_esp32_device(device_id, updates)

    return jsonify({"ok": True, "device_id": device_id, "updated": list(updates.keys())})


def _dispatch_card_start(device_id: str, card_id: str, chapter: int,
                         chapter_key: str = None, track_key: str = None) -> Tuple[bool, Optional[str], int]:
    """Starts playback via embedded MQTT first, falling back to Yoto Cloud REST."""
    from core.bridge.mqtt_client import get_mqtt_bridge
    from core.bridge.playback import get_playback_manager

    get_playback_manager().expect(device_id, card_id)
    mqtt = get_mqtt_bridge()
    if mqtt.is_connected and mqtt.play(device_id, card_id, track=chapter):
        return True, None, 200

    if not clients.yoto_client:
        return False, "Yoto client not configured", 503

    if clients.yoto_client.start_playback(device_id, card_id, chapter=chapter, chapter_key=chapter_key, track_key=track_key):
        return True, None, 200
    return False, "Yoto player command failed", 502


@esp32_bp.route("/api/play", methods=["POST"])
@require_device_jwt
def play_media():
    """
    Unified native playback execution route for Touch controllers and Kiosks.
    Supports both official/MYO Yoto cards ('type': 'yoto') and native
    Audiobookshelf streaming/offline cards ('type': 'abs').
    """
    data = request.get_json(force=True, silent=True) or {}
    child = str(data.get("child") or data.get("profile_id") or "default").lower()
    media_type = data.get("type", "abs")
    media_id = data.get("id")
    device_id = data.get("device_id")
    raw_ch = data.get("chapter")
    explicit_chapter = int(raw_ch) if (raw_ch is not None and str(raw_ch).strip() != "" and int(raw_ch) > 0) else None
    if not media_id:
        return jsonify({"ok": False, "error": "Missing media id"}), 400

    config = database.get_all_profiles()
    child_cfg = config.get(child, {})
    allowed_players = list(child_cfg.get("player_ids") or [])
    default_player = child_cfg.get("default_player_id") or ""
    if default_player and default_player not in allowed_players:
        allowed_players.append(default_player)
    if not device_id:
        device_id = default_player or (allowed_players[0] if allowed_players else "")
    if not device_id:
        return jsonify({"ok": False, "error": f"No target player resolved for child '{child}'"}), 400

    logger.info("Executing play: child=%s, type=%s, media=%s, device=%s, explicit_ch=%s", child, media_type, media_id, device_id, explicit_chapter)

    if media_type == "yoto":
        chapter = explicit_chapter or _yoto_resume_state.get((child, media_id)) or _yoto_resume_state.get((device_id, media_id)) or 1
        _yoto_resume_state[(child, media_id)] = chapter
        _yoto_resume_state[(device_id, media_id)] = chapter
        chapter_title = ""

        raw_ck = str(data.get("chapter_key") or "").strip() if explicit_chapter else ""
        raw_tk = str(data.get("track_key") or "").strip() if explicit_chapter else ""
        ck_val = None if (raw_ck.isdigit() and len(raw_ck) == 1) else (raw_ck or None)
        tk_val = None if (raw_tk.isdigit() and len(raw_tk) == 1) else (raw_tk or None)

        if clients.yoto_client and (not tk_val or not ck_val or not chapter_title):
            try:
                cdetail = clients.yoto_client.get_card_detail(media_id)
                if cdetail:
                    c_obj = cdetail.get("content") or cdetail.get("card", {}).get("content") or {}
                    chaps = c_obj.get("chapters", [])
                    if chaps:
                        t_idx = max(0, min(len(chaps) - 1, chapter - 1))
                        chapter = t_idx + 1
                        tgt = chaps[t_idx]
                        chapter_title = tgt.get("title") or ""
                        ck_val = ck_val or tgt.get("key")
                        trks = tgt.get("tracks", [])
                        tk_val = tk_val or (trks[0].get("key") if trks else tgt.get("key"))
            except Exception as ke:
                logger.debug("Notice extracting keys for %s: %s", media_id, ke)

        ok, err_msg, code = _dispatch_card_start(device_id, media_id, chapter, chapter_key=ck_val, track_key=tk_val)
        if not ok:
            return jsonify({"ok": False, "error": err_msg}), code

        database.record_playback(media_id, child)
        return jsonify({
            "ok": True,
            "status": "playing",
            "type": "yoto",
            "device_id": device_id,
            "chapter": chapter,
            "chapter_title": chapter_title
        })

    elif media_type == "abs":
        from core.bridge.manager import get_bridge_manager
        from core.bridge.offline import get_offline_manager

        base_url = request.host_url.rstrip("/")
        mgr = get_bridge_manager()
        if child in config:
            slot = mgr.update_profile_primary_card(profile_id=child, abs_item_id=media_id, mode_override="default", base_url=base_url)
        else:
            slot = mgr.assign_to_fleet_card(slot_id=f"profile_{child}", abs_item_id=media_id, base_url=base_url)

        slot_key = slot.get("slot_id") or f"profile_{child}"
        slot_mode = slot.get("mode", "streaming")
        yoto_cid = slot.get("yoto_card_id") or slot_key

        if slot_mode == "offline":
            get_offline_manager().queue_transcode(slot_key, base_url=base_url)
        elif clients.yoto_client:
            try:
                saved_id = clients.yoto_client.save_stream_playlist(
                    title=slot.get("title", "Audiobook"),
                    tracks=slot.get("tracks", []),
                    card_id=yoto_cid,
                    cover_url=f"{base_url}/api/cover/{media_id}",
                    description=f"Streams {slot.get('title', '')} from Audiobookshelf"
                )
                if saved_id:
                    yoto_cid = saved_id
                    if saved_id != slot.get("yoto_card_id"):
                        conn = database.get_db_connection()
                        try:
                            with conn:
                                conn.execute("UPDATE bridge_slots SET yoto_card_id = ? WHERE slot_id = ?;", (saved_id, slot_key))
                        finally:
                            conn.close()
            except Exception as e:
                logger.warning("Failed to save stream playlist for %s: %s", media_id, e)

        target_ch = explicit_chapter or 1
        tracks = slot.get("tracks") or []
        chapter_title = ""
        if 1 <= target_ch <= len(tracks):
            chapter_title = tracks[target_ch - 1].get("title") or ""

        ok, err_msg, code = _dispatch_card_start(device_id, yoto_cid, target_ch)
        if not ok:
            return jsonify({"ok": False, "error": err_msg}), code

        database.record_playback(media_id, child)
        return jsonify({
            "ok": True,
            "status": "playing",
            "type": "abs",
            "device_id": device_id,
            "card_id": yoto_cid,
            "slot_id": slot_key,
            "chapter": target_ch,
            "chapter_title": chapter_title,
            "position": 0
        })

    return jsonify({"ok": False, "error": f"Unsupported media type '{media_type}'"}), 400


@esp32_bp.route("/api/player/control", methods=["POST"])
@require_device_jwt
def control_player():
    """Unified playback control route for Touchscreen and hardware controllers."""
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id")
    action = data.get("action")
    volume = data.get("volume")
    if not device_id or not action:
        return jsonify({"ok": False, "error": "device_id and action are required"}), 400
    from core.player_service import dispatch_player_control
    ok, resp_data, status_code = dispatch_player_control(device_id, action, volume=volume)
    return jsonify(resp_data), status_code
