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
from core.auth import (
    require_device_jwt, create_device_jwt, decode_and_verify_device_jwt, get_current_device
)

# Persistent HTTP session with keep-alive pool for low-latency Bridge/Yoto relay
_http_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
_http_session.mount("http://", _adapter)
_http_session.mount("https://", _adapter)

# Cached player volume ceilings (device_id -> {"max": int, "cached_at": float})
_player_vol_cache = {}

# In-memory presence cache for local home network verification
_player_home_presence = {}  # device_id -> {"is_home": bool, "last_checked": float}
def verify_player_home_presence(device_id: str, online: bool) -> bool:
    """
    Determines if a Yoto player is on the home network or away/traveling.
    If the player is reported offline by Yoto Cloud, returns is_home=False.
    If online, checks cached presence or verifies local presence.
    """
    if not online:
        return False
    now = time.time()
    cached = _player_home_presence.get(device_id)
    if cached and (now - cached.get("last_checked", 0) < 60):
        return cached.get("is_home", True)
    
    # By default in home environment, online players with valid bridge connection are considered home
    # unless flagged as traveling or client IP from bridge/stream indicates external egress
    is_home = True
    _player_home_presence[device_id] = {"is_home": is_home, "last_checked": now}
    return is_home
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
        "version": clients.get_installed_version() if hasattr(clients, "get_installed_version") else __import__("core.version_service", fromlist=["get_installed_version"]).get_installed_version(),
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
# In-memory tracker of last played chapter per (child_id, media_id) or (device_id, media_id) for Yoto cards
_yoto_resume_state = {}


def _resolve_profile_avatar_info(pid: str, pdata: dict) -> tuple[str, bool]:
    """Normalizes profile avatar_url to /api/avatar/<pid>?t=<mtime> when a custom avatar exists."""
    from core.config import AVATARS_DIR
    from routes.admin_profiles import _materialize_avatar_bytes_to_disk
    import base64

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
            except Exception:
                pass
        elif raw_av.startswith("http://") or raw_av.startswith("https://"):
            try:
                res = requests.get(raw_av, timeout=6)
                if res.status_code == 200 and res.content:
                    norm = _materialize_avatar_bytes_to_disk(pid, res.content)
                    if norm:
                        pdata["avatar_url"] = norm
                        database.upsert_profile(pid, pdata)
                        raw_av = norm
            except Exception:
                pass

    if avatar_path.exists():
        mtime = int(avatar_path.stat().st_mtime)
        return f"/api/avatar/{pid}?t={mtime}", True

    bubble_path = AVATARS_DIR / f"{pid}_bubble.jpg"
    if not bubble_path.exists():
        from routes.admin_profiles import sync_all_bubble_avatars
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
    except Exception:
        pass
    return "touch"

@esp32_bp.route("/api/kids/<child_name>/abs", methods=["GET"])
@require_device_jwt
def get_child_abs(child_name: str):
    """
    Returns filtered Audiobookshelf books for the child profile.
    Scoped by child account token, dedicated library ID, and/or tag filter.
    Microcontroller-optimized JSON array served with ultra-low latency from pre-indexed SQLite cache.
    """
    client_type = _resolve_client_type()
    try:
        books = database.get_catalog_items_for_profile(child_name.lower(), "abs", client_type=client_type)
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
    client_type = _resolve_client_type()
    try:
        playlists = database.get_catalog_items_for_profile(child_name.lower(), "yoto", client_type=client_type)
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
    Consumed by bedside controllers and tablet kiosks for track selection & detail views.
    """
    from routes.admin_curation import get_media_tracks_data
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
    If the device is approved, provisions/returns rotating JWT access & refresh tokens.
    If pending approval, returns status: pending_approval (HTTP 202).
    """
    data = request.get_json(silent=True) or {}
    mac = data.get("mac_address") or data.get("mac") or data.get("device_id")
    friendly_name = data.get("friendly_name", "ESP32 Controller")
    # Prioritize explicit client IP from device payload, followed by reverse-proxy headers
    ip_addr = data.get("ip_address") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.headers.get("X-Real-IP") or request.remote_addr or ""
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
            bridge_headers = {"X-Api-Key": creds["yoto_bridge_api_key"]} if creds.get("yoto_bridge_api_key") else {}
            res = requests.get(f"{b_url}/api/status", headers=bridge_headers, timeout=4)
            if res.status_code == 200:
                for d in res.json().get("devices", []):
                    did = d.get("id")
                    if did:
                        v_max = d.get("volume_max", 100)
                        _player_vol_cache[did] = {"max": v_max, "cached_at": time.time()}
                        dev_status = (d.get("status") or "idle").lower()
                        is_playing = (dev_status == "playing")
                        is_active_media = dev_status in ("playing", "paused") or is_playing
                        chapter_title = d.get("chapter_title") or ""
                        author = d.get("author") or ""
                        cover_url = d.get("cover_url") or ""
                        item_id = d.get("item_id") if is_active_media else None
                        now_playing = d.get("now_playing") if is_active_media else None
                        pos = (d.get("position") or 0) if is_active_media else 0

                        # Fast local SQLite media_items enrichment for both Yoto cards and ABS books
                        if item_id:
                            db_item = database.get_media_item_by_id(item_id)
                            if db_item:
                                if not now_playing or now_playing == "Yoto Card":
                                    now_playing = db_item.get("title") or now_playing
                                if not author:
                                    author = db_item.get("author") or ""
                                if not cover_url:
                                    c_db = db_item.get("cover_url") or ""
                                    if c_db:
                                        if db_item.get("type", "").startswith("yoto") and not c_db.startswith("/api/thumb"):
                                            import urllib.parse
                                            cover_url = f"/api/thumb?type=yoto&id={item_id}&url={urllib.parse.quote(c_db)}"
                                        else:
                                            cover_url = c_db

                        if is_active_media and item_id and clients.abs_client:
                            db_item = database.get_media_item_by_id(item_id)
                            if not db_item or db_item.get("type") == "abs":
                                try:
                                    abs_item = clients.abs_client.get_item(item_id)
                                    if abs_item:
                                        meta = abs_item.get("media", {}).get("metadata", {})
                                        author = meta.get("authorName") or meta.get("author") or author
                                        if not author and meta.get("authors"):
                                            author = meta["authors"][0].get("name", "")
                                        if not now_playing:
                                            now_playing = meta.get("title") or now_playing
                                        ch_list = abs_item.get("media", {}).get("chapters", [])
                                        curr = [c for c in ch_list if c.get("start", 0) <= pos < c.get("end", 0)]
                                        if curr:
                                            chapter_title = curr[0].get("title", "")
                                except Exception as ce:
                                    logger.debug("Chapter/Author resolution notice: %s", ce)
                        has_card = bool(is_active_media and (item_id or now_playing))
                        is_online = bool(d.get("online"))
                        is_home = verify_player_home_presence(did, is_online)
                        player_map[did] = {
                            "id": did,
                            "name": d.get("name") or "Yoto Player",
                            "online": is_online,
                            "is_home": is_home,
                            "location": "home" if is_home else "away",
                            "status": dev_status,
                            "is_playing": is_playing,
                            "has_card": has_card,
                            "now_playing": now_playing,
                            "author": author,
                            "chapter_title": chapter_title,
                            "cover_url": cover_url,
                            "item_id": item_id,
                            "position": pos,
                            "duration": d.get("duration") if is_active_media else 0,
                            "volume": d.get("volume") if d.get("volume") is not None else 50,
                            "volume_max": d.get("volume_max", 100) or 100,
                            "day_mode": d.get("day_mode")
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
                        "duration": None,
                        "volume": d.get("volume", 50) if d.get("volume") is not None else 50,
                        "volume_max": d.get("volume_max", 100) or 100
                    }
    except Exception as e:
        logger.debug("Player status resolution notice: %s", e)
    from routes.admin_profiles import compute_household_monograms, PALETTE_COLORS
    monograms = compute_household_monograms()
    profile_summaries = []
    for pid, pdata in all_profs.items():
        avatar, has_custom_av = _resolve_profile_avatar_info(pid, pdata)
        def_id = pdata.get("default_player_id", "")
        # Assemble list of all player objects linked to this profile
        p_ids = list(pdata.get("player_ids", []))
        if def_id and def_id not in p_ids:
            p_ids.insert(0, def_id)
        profile_players = []
        for did in p_ids:
            info = player_map.get(did, {
                "id": did,
                "name": "Yoto Player",
                "online": False,
                "status": "unknown",
                "is_playing": False,
                "volume": 50,
                "volume_max": 100
            })
            profile_players.append(info)
        def_info = player_map.get(def_id)
        def_name = def_info["name"] if def_info else (profile_players[0]["name"] if profile_players else "Yoto Player")

        # Resolve avatar color and smart household monogram for native LVGL fallback
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
            import json as _json
            dev_settings = _json.loads(device["settings_json"]) or {}
        except Exception:
            dev_settings = {}
    can_switch = (len(profile_summaries) > 1) and not bool(assigned_prof)
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
        "profiles": profile_summaries
    })


@esp32_bp.route("/api/device/settings", methods=["PUT", "POST"])
def update_device_settings():
    """
    Persists Grown-Ups settings (Parent PIN, lock_player, locked_player_id,
    sleep timer, bedtime/wake schedules, clock size, blockRemotePlayback) back to
    StoryDeck Core SQLite database so Admin Portal and controller stay 100% synced.
    """
    import json as _json
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
                existing_settings = _json.loads(dev["settings_json"]) or {}
            except Exception:
                existing_settings = {}
        existing_settings.update(data["settings"])
        updates["settings_json"] = _json.dumps(existing_settings)

    if updates:
        database.update_esp32_device(device_id, updates)

    return jsonify({"ok": True, "device_id": device_id, "updated": list(updates.keys())})
@esp32_bp.route("/api/play", methods=["POST"])
@require_device_jwt
def play_media():
    """
    Unified playback execution route for the ESP32.
    Payload:
      {
        "child": "<profile_id>",
        "type": "abs" | "yoto",
        "id": "<media_id>",
        "device_id": "<optional_specific_device_id>",
        "chapter": 1
      }
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
    # Resolve target Yoto player
    allowed_players = child_cfg.get("player_ids") or []
    default_player = child_cfg.get("default_player_id") or ""
    if default_player and default_player not in allowed_players:
        allowed_players.append(default_player)
    if not device_id:
        device_id = default_player or (allowed_players[0] if allowed_players else "")
    if not device_id:
        return jsonify({"ok": False, "error": f"No target player resolved for child '{child}'"}), 400
    logger.info("Executing play: child=%s, type=%s, media=%s, device=%s, explicit_ch=%s", child, media_type, media_id, device_id, explicit_chapter)
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")
    if media_type == "yoto":
        # If no explicit chapter was passed, resume from the profile/player's last played chapter for this Yoto card
        chapter = explicit_chapter or _yoto_resume_state.get((child, media_id)) or _yoto_resume_state.get((device_id, media_id)) or 1
        _yoto_resume_state[(child, media_id)] = chapter
        _yoto_resume_state[(device_id, media_id)] = chapter
        chapter_title = ""
        # 1. Bridge Mode: Route to Bridge /api/play so user needs zero separate Yoto credentials
        if mode == "bridge" and creds.get("yoto_bridge_url"):
            active_bridge_url = creds.get("yoto_bridge_url").rstrip("/")
            bridge_url = f"{active_bridge_url}/api/play"
            raw_ck = str(data.get("chapter_key") or "").strip() if explicit_chapter else ""
            raw_tk = str(data.get("track_key") or "").strip() if explicit_chapter else ""
            chapter_key = None if (raw_ck.isdigit() and len(raw_ck) == 1) else (raw_ck or None)
            track_key = None if (raw_tk.isdigit() and len(raw_tk) == 1) else (raw_tk or None)
            if not track_key or not chapter_key or not chapter_title:
                try:
                    if clients.yoto_client:
                        cdetail = clients.yoto_client.get_card_detail(media_id)
                        if cdetail:
                            c_obj = cdetail.get("content") or cdetail.get("card", {}).get("content") or {}
                            chaps = c_obj.get("chapters", [])
                            if chaps:
                                t_idx = max(0, min(len(chaps) - 1, chapter - 1))
                                chapter = t_idx + 1
                                tgt = chaps[t_idx]
                                chapter_title = tgt.get("title") or ""
                                chapter_key = chapter_key or tgt.get("key")
                                trks = tgt.get("tracks", [])
                                if trks:
                                    track_key = track_key or trks[0].get("key")
                                else:
                                    track_key = track_key or tgt.get("key")
                except Exception as ke:
                    logger.debug("Notice extracting keys for %s: %s", media_id, ke)
            payload = {
                "card_id": media_id,
                "device_id": device_id,
                "chapter": chapter
            }
            if chapter_key:
                payload["chapter_key"] = chapter_key
            if track_key:
                payload["track_key"] = track_key
            bridge_headers = {}
            if creds.get("yoto_bridge_api_key"):
                bridge_headers["X-Api-Key"] = creds["yoto_bridge_api_key"]
            try:
                logger.info("Routing Yoto card playback to Bridge (%s): card=%s, player=%s, ch=%d", bridge_url, media_id, device_id, chapter)
                res = requests.post(bridge_url, json=payload, headers=bridge_headers, timeout=10)
                if res.status_code in (200, 204):
                    logger.info("Bridge accepted Yoto card play: HTTP %d (Status: playing)", res.status_code)
                    database.record_playback(media_id, child)
                    return jsonify({"ok": True, "status": "playing", "type": "yoto", "device_id": device_id, "chapter": chapter, "chapter_title": chapter_title})
                logger.warning("Bridge returned HTTP %d for Yoto card play: %s", res.status_code, res.text)
                return jsonify({"ok": False, "error": f"Bridge rejected Yoto card playback (HTTP {res.status_code})"}), res.status_code
            except Exception as e:
                logger.error("Failed to communicate with Yoto Bridge during card play: %s", e)
                return jsonify({"ok": False, "error": f"Bridge communication error: {str(e)}"}), 502
        # 2. Direct Cloud Fallback
        if not clients.yoto_client:
            logger.error("Yoto direct client not initialized; cannot fallback for card %s", media_id)
            return jsonify({"ok": False, "error": "Yoto client not initialized"}), 502
        logger.info("Routing Yoto card play to direct Yoto Cloud API: card=%s, player=%s", media_id, device_id)
        raw_ck = str(data.get("chapter_key") or "").strip() if explicit_chapter else ""
        raw_tk = str(data.get("track_key") or "").strip() if explicit_chapter else ""
        ck_val = None if (raw_ck.isdigit() and len(raw_ck) == 1) else (raw_ck or None)
        tk_val = None if (raw_tk.isdigit() and len(raw_tk) == 1) else (raw_tk or None)
        success = clients.yoto_client.start_playback(device_id, media_id, chapter, chapter_key=ck_val, track_key=tk_val)
        if success:
            logger.info("Direct Yoto Cloud accepted playback command for %s", device_id)
            database.record_playback(media_id, child)
            return jsonify({"ok": True, "status": "playing", "type": "yoto", "device_id": device_id, "chapter": chapter, "chapter_title": chapter_title})
        logger.error("Direct Yoto Cloud play command failed for player %s", device_id)
        return jsonify({"ok": False, "error": "Yoto player command failed"}), 502
    elif media_type == "abs":
        creds = database.get_api_credentials()
        active_bridge_url = creds.get("yoto_bridge_url", YOTO_BRIDGE_URL).rstrip("/")
        bridge_url = f"{active_bridge_url}/api/play"
        payload = {
            "item_id": media_id,
            "device_id": device_id
        }
        # Only send explicit chapter when user picked a specific chapter; omit when resuming book progress!
        if explicit_chapter is not None:
            payload["chapter"] = explicit_chapter
        bridge_headers = {}
        if creds.get("yoto_bridge_api_key"):
            bridge_headers["X-Api-Key"] = creds["yoto_bridge_api_key"]
        try:
            logger.info("Routing Audiobookshelf playback to Bridge (%s): item=%s, player=%s, explicit_ch=%s", bridge_url, media_id, device_id, explicit_chapter)
            res = requests.post(bridge_url, json=payload, headers=bridge_headers, timeout=10)
            if res.status_code in (200, 204):
                b_data = res.json() if res.content else {}
                resumed_ch = b_data.get("chapter") or explicit_chapter or 1
                resumed_title = b_data.get("chapter_title") or ""
                resumed_pos = b_data.get("position") or 0
                logger.info("Bridge accepted ABS stream dispatch: HTTP %d (ch=%s, pos=%s)", res.status_code, resumed_ch, resumed_pos)
                database.record_playback(media_id, child)
                return jsonify({
                    "ok": True,
                    "status": "playing",
                    "type": "abs",
                    "device_id": device_id,
                    "chapter": resumed_ch,
                    "chapter_title": resumed_title,
                    "position": resumed_pos
                })
            logger.warning("Bridge returned HTTP %d for ABS stream: %s", res.status_code, res.text)
            return jsonify({"ok": False, "error": f"Bridge rejected ABS playback (HTTP {res.status_code})"}), res.status_code
        except Exception as e:
            logger.error("Failed to route ABS stream to Yoto Bridge: %s", e)
            return jsonify({"ok": False, "error": f"Bridge communication error: {str(e)}"}), 502
    return jsonify({"ok": False, "error": f"Unsupported media type '{media_type}'"}), 400
@esp32_bp.route("/api/player/control", methods=["POST"])
@require_device_jwt
def control_player():
    """
    Unified playback control route for Touchscreen and hardware controllers.
    Payload:
      {
        "device_id": "<player_device_id>",
        "action": "pause" | "resume" | "stop" | "next" | "prev" | "volume",
        "volume": 0-100 (for volume action)
      }
    """
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id")
    action = data.get("action")
    volume = data.get("volume")
    if not device_id or not action:
        return jsonify({"ok": False, "error": "device_id and action are required"}), 400
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")
    active_bridge_url = creds.get("yoto_bridge_url", YOTO_BRIDGE_URL).rstrip("/")
    bridge_headers = {}
    if creds.get("yoto_bridge_api_key"):
        bridge_headers["X-Api-Key"] = creds["yoto_bridge_api_key"]
    if creds.get("yoto_ui_pin"):
        bridge_headers["X-Pin"] = str(creds["yoto_ui_pin"]).strip()
    try:
        # 1. Volume Control
        if action == "volume":
            if volume is None:
                return jsonify({"ok": False, "error": "volume (0-100) is required for volume action"}), 400
            vol_val = max(0, min(100, int(volume)))
            # Parent volume ceiling check & clamp using cached volume_max (avoids 300-800ms GET round-trip)
            now_ts = time.time()
            cached_vc = _player_vol_cache.get(device_id)
            if cached_vc and (now_ts - cached_vc.get("cached_at", 0) < 30):
                max_limit = cached_vc.get("max", 100)
            else:
                max_limit = 100
                if mode == "bridge" and active_bridge_url:
                    try:
                        s_res = _http_session.get(f"{active_bridge_url}/api/status", headers=bridge_headers, timeout=1.5)
                        if s_res.status_code == 200:
                            for d in s_res.json().get("devices", []):
                                if d.get("id") == device_id:
                                    max_limit = d.get("volume_max", 100)
                                    _player_vol_cache[device_id] = {"max": max_limit, "cached_at": now_ts}
                                    break
                    except Exception as ve:
                        logger.debug("Could not verify live volume_max from bridge: %s", ve)
            if vol_val > max_limit:
                logger.info("Volume request %d%% for player %s clamped to parent limit %d%%", vol_val, device_id, max_limit)
                vol_val = max_limit
            if mode == "bridge" and active_bridge_url:
                # Try /api/device/volume first, fall back to /api/yoto/volume using keep-alive session
                try:
                    r = _http_session.post(f"{active_bridge_url}/api/device/volume", json={"device_id": device_id, "volume": vol_val}, headers=bridge_headers, timeout=3)
                    if r.status_code == 404:
                        r = _http_session.post(f"{active_bridge_url}/api/yoto/volume", json={"device_id": device_id, "volume": vol_val}, headers=bridge_headers, timeout=3)
                    if r.status_code == 200:
                        logger.info("Player %s volume updated to %d%% via Bridge", device_id, vol_val)
                        return jsonify({"ok": True, "device_id": device_id, "volume": vol_val})
                    logger.warning("Bridge rejected volume command (%d): %s", r.status_code, r.text)
                except Exception as be:
                    logger.warning("Bridge volume connection error (%s), attempting direct cloud fallback", be)
            # Direct Yoto Cloud Fallback for Volume
            if clients.yoto_client:
                logger.info("Routing volume (%d%%) for %s to direct Yoto Cloud API", vol_val, device_id)
                ok = clients.yoto_client.set_volume(device_id, vol_val)
                if ok:
                    return jsonify({"ok": True, "device_id": device_id, "volume": vol_val})
                return jsonify({"ok": False, "error": "Yoto Cloud volume command failed"}), 502
        # 2. Transport: Pause / Resume / Stop
        elif action in ("pause", "resume", "stop"):
            if mode == "bridge" and active_bridge_url:
                try:
                    r = _http_session.post(f"{active_bridge_url}/api/control", json={"device_id": device_id, "action": action}, headers=bridge_headers, timeout=3)
                    if r.status_code == 200:
                        logger.info("Player %s transport action '%s' accepted by Bridge", device_id, action)
                        return jsonify({"ok": True, "device_id": device_id, "action": action})
                    logger.warning("Bridge rejected control action %s (%d): %s", action, r.status_code, r.text)
                except Exception as be:
                    logger.warning("Bridge control connection error (%s), attempting direct cloud fallback", be)
            # Direct Yoto Cloud Fallback for Transport
            if clients.yoto_client:
                logger.info("Routing transport '%s' for %s to direct Yoto Cloud API", action, device_id)
                ok = clients.yoto_client.send_transport_command(device_id, action)
                if ok:
                    return jsonify({"ok": True, "device_id": device_id, "action": action})
                return jsonify({"ok": False, "error": f"Yoto Cloud '{action}' transport command failed"}), 502
        # 3. Chapter Track Skip: Prev / Next
        elif action in ("prev", "next"):
            if mode == "bridge" and active_bridge_url:
                r = _http_session.post(f"{active_bridge_url}/api/seek", json={"device_id": device_id, "action": action}, headers=bridge_headers, timeout=3)
                if r.status_code == 200:
                    logger.info("Player %s seek '%s' accepted by Bridge: %s", device_id, action, r.text)
                    return jsonify({"ok": True, "device_id": device_id, "action": action, "data": r.json()})
                logger.warning("Bridge rejected seek action %s (%d): %s", action, r.status_code, r.text)
                return jsonify({"ok": False, "error": f"Bridge seek error: {r.text}"}), r.status_code
        else:
            return jsonify({"ok": False, "error": f"Unsupported action '{action}'"}), 400
    except Exception as e:
        logger.error("Player control dispatch error on %s (%s): %s", device_id, action, e)
        return jsonify({"ok": False, "error": str(e)}), 502
    return jsonify({"ok": False, "error": "Command not handled"}), 500
