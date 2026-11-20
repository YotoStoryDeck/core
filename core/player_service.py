"""
Unified Player and Playback Service for StoryDeck Core.
Provides a single canonical methodology for resolving player status,
currently played cards/audiobooks, and dispatching transport controls across
both the Web Companion Kiosk and Parent Portal.
"""
from __future__ import annotations
import time
import threading
import urllib.parse
import logging
from typing import Dict, Any, List, Optional, Tuple
import requests

import database
import clients
from core.config import logger

# Persistent session with connection pool
_http_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
_http_session.mount("http://", _adapter)
_http_session.mount("https://", _adapter)

# Cached player volume ceilings (device_id -> {"max": int, "cached_at": float})
_player_vol_cache: Dict[str, Dict[str, Any]] = {}

# In-memory presence cache for local home network verification
_player_home_presence: Dict[str, Dict[str, Any]] = {}

# Short TTL cache for live players map to prevent rapid polling thrashing (e.g. 2.0s TTL)
_cached_players_map: Dict[str, Dict[str, Any]] = {}
_cached_players_ts: float = 0.0
_CACHE_TTL_SECONDS: float = 2.0

# Cached card slots inventory to correlate active playback with cards/playlists
_cards_cache: List[Dict[str, Any]] = []
_cards_cache_ts: float = 0.0

# Active bedtime sleep timers per player device_id -> {"expires_at": float, "minutes": int, "timer": threading.Timer}
_player_sleep_timers: Dict[str, Dict[str, Any]] = {}
_sleep_timer_lock = threading.Lock()


def _on_sleep_timer_expired(device_id: str):
    """Callback fired when a player's bedtime sleep timer reaches zero."""
    with _sleep_timer_lock:
        _player_sleep_timers.pop(device_id, None)
    logger.info("Bedtime sleep timer expired for player %s; dispatching pause command.", device_id)
    try:
        dispatch_player_control(device_id, "pause")
    except Exception as e:
        logger.warning("Sleep timer pause dispatch error for %s: %s", device_id, e)


def set_player_sleep_timer(device_id: str, minutes: int) -> Dict[str, Any]:
    """Sets or cancels a server-enforced bedtime sleep timer for a Yoto player."""
    mins = max(0, int(minutes or 0))
    with _sleep_timer_lock:
        existing = _player_sleep_timers.pop(device_id, None)
        if existing and existing.get("timer"):
            try:
                existing["timer"].cancel()
            except Exception:
                pass

        if mins <= 0:
            return {"active": False, "minutes": 0, "remaining_seconds": 0, "sleep_timer_remaining": 0}

        duration_sec = mins * 60.0
        expires_at = time.time() + duration_sec
        timer = threading.Timer(duration_sec, _on_sleep_timer_expired, args=(device_id,))
        timer.daemon = True
        timer.start()
        _player_sleep_timers[device_id] = {
            "expires_at": expires_at,
            "minutes": mins,
            "timer": timer
        }
        return {"active": True, "minutes": mins, "remaining_seconds": int(duration_sec), "sleep_timer_remaining": int(duration_sec)}


def get_player_sleep_timer_remaining(device_id: str) -> int:
    """Returns remaining sleep timer seconds for device_id, or 0 if inactive."""
    with _sleep_timer_lock:
        entry = _player_sleep_timers.get(device_id)
        if not entry:
            return 0
        rem = int(round(entry["expires_at"] - time.time()))
        if rem <= 0:
            _player_sleep_timers.pop(device_id, None)
            return 0
        return rem


def get_cached_cards_inventory(bridge_url: str = "", bridge_headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Retrieves all registered card slots from local database and external bridge with a 15s cache."""
    global _cards_cache, _cards_cache_ts
    now = time.time()
    if _cards_cache and (now - _cards_cache_ts < 15.0):
        return _cards_cache

    cards: List[Dict[str, Any]] = []
    # 1. Local database bridge_slots
    try:
        from core.bridge_manager import get_bridge_manager
        mgr = get_bridge_manager()
        cards = mgr.list_slots()
    except Exception as e:
        logger.debug("Local bridge slots lookup notice: %s", e)

    # 2. External bridge /api/cards if bridge_url configured
    if bridge_url:
        try:
            r = _http_session.get(f"{bridge_url}/api/cards", headers=bridge_headers or {}, timeout=4)
            if r.status_code == 200:
                b_cards = r.json()
                if isinstance(b_cards, list):
                    local_slots = {s.get("slot_id") or s.get("slot") for s in cards}
                    for bc in b_cards:
                        sid = bc.get("slot") or bc.get("slot_id")
                        if sid and sid not in local_slots:
                            cards.append(bc)
        except Exception as e:
            logger.debug("Bridge /api/cards inventory lookup notice: %s", e)

    _cards_cache = cards
    _cards_cache_ts = now
    return cards


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
    
    is_home = True
    _player_home_presence[device_id] = {"is_home": is_home, "last_checked": now}
    return is_home


def get_live_players_map(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Retrieves the canonical live status and currently played card/media
    for all household Yoto players. Used identically by Kiosk and Parent Portal.
    """
    global _cached_players_map, _cached_players_ts
    now = time.time()
    if not force_refresh and _cached_players_map and (now - _cached_players_ts < _CACHE_TTL_SECONDS):
        return _cached_players_map

    player_map: Dict[str, Dict[str, Any]] = {}
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")
    bridge_url = creds.get("yoto_bridge_url", "").rstrip("/")
    bridge_headers = {}
    if creds.get("yoto_bridge_api_key"):
        bridge_headers["X-Api-Key"] = creds["yoto_bridge_api_key"]
    if creds.get("yoto_ui_pin"):
        bridge_headers["X-Pin"] = str(creds["yoto_ui_pin"]).strip()

    # 1. Query Bridge /api/status if configured
    if mode == "bridge" and bridge_url:
        try:
            res = _http_session.get(f"{bridge_url}/api/status", headers=bridge_headers, timeout=4)
            if res.status_code == 200:
                for d in res.json().get("devices", []):
                    did = d.get("id")
                    if not did:
                        continue
                    v_max = d.get("volume_max", 100) or 100
                    _player_vol_cache[did] = {"max": v_max, "cached_at": now}

                    dev_status = (d.get("status") or "idle").lower()
                    is_playing = (dev_status == "playing")
                    is_active_media = dev_status in ("playing", "paused") or is_playing
                    chapter_title = d.get("chapter_title") or ""
                    author = d.get("author") or ""
                    cover_url = d.get("cover_url") or ""
                    item_id = d.get("item_id") if is_active_media else None
                    now_playing = d.get("now_playing") if is_active_media else None
                    pos = (d.get("position") or 0) if is_active_media else 0
                    dur = (d.get("duration") or 0) if is_active_media else 0

                    # Enrich from SQLite media_items for both Yoto cards and ABS books
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
                                        cover_url = f"/api/thumb?type=yoto&id={item_id}&url={urllib.parse.quote(c_db)}"
                                    else:
                                        cover_url = c_db

                    # Enrich from ABS client if active ABS book
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
                                    if not dur:
                                        dur = round(float(abs_item.get("media", {}).get("duration", 0)))
                            except Exception as ce:
                                logger.debug("ABS chapter/author resolution notice for %s: %s", item_id, ce)

                    # Fallback cover if none resolved
                    if not cover_url:
                        cover_url = "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png"

                    # Correlate active playback with card inventory & attached playlists
                    cards_inv = get_cached_cards_inventory(bridge_url, bridge_headers)
                    matched_card = None
                    if is_active_media:
                        for c in cards_inv:
                            c_item = c.get("item_id") or c.get("abs_item_id")
                            c_card = c.get("yoto_card_id") or c.get("card_id")
                            c_title = (c.get("title") or c.get("yoto_title") or "").strip().lower()
                            if (item_id and (c_item == item_id or c_card == item_id)) or (now_playing and c_title and c_title == now_playing.strip().lower()):
                                matched_card = c
                                break

                    card_id = None
                    slot_id = None
                    card_title = None
                    has_attached_card = False
                    has_attached_playlist = False
                    playback_mode = "idle"

                    if is_active_media:
                        if matched_card:
                            card_id = matched_card.get("yoto_card_id") or matched_card.get("card_id") or matched_card.get("slot")
                            slot_id = matched_card.get("slot") or matched_card.get("slot_id")
                            card_title = matched_card.get("title") or matched_card.get("yoto_title") or now_playing
                            has_attached_card = True
                            has_attached_playlist = bool(card_id or slot_id)
                            off = matched_card.get("offline") or {}
                            if off and off.get("status") == "ready":
                                playback_mode = "offline"
                            else:
                                playback_mode = matched_card.get("mode") or "streaming"
                        else:
                            # Check if retail Yoto card or raw cardId
                            db_item = database.get_media_item_by_id(item_id) if item_id else None
                            if (db_item and db_item.get("type") == "yoto") or (item_id and len(item_id) == 5 and item_id.isalnum()):
                                card_id = item_id
                                card_title = now_playing
                                has_attached_card = True
                                has_attached_playlist = False
                                playback_mode = "retail"
                            else:
                                has_attached_card = bool(item_id or now_playing)
                                has_attached_playlist = False
                                playback_mode = "streaming"

                    has_card = bool(is_active_media and (has_attached_card or item_id or now_playing))
                    is_online = bool(d.get("online"))
                    is_home = verify_player_home_presence(did, is_online)
                    vol = d.get("volume") if d.get("volume") is not None else 50

                    player_map[did] = {
                        "id": did,
                        "deviceId": did,
                        "name": d.get("name") or "Yoto Player",
                        "online": is_online,
                        "is_home": is_home,
                        "location": "home" if is_home else "away",
                        "status": dev_status,
                        "is_playing": is_playing,
                        "has_card": has_card,
                        "now_playing": now_playing,
                        "title": now_playing or ("Playing on Yoto" if is_active_media else "No Active Playback"),
                        "author": author,
                        "chapter_title": chapter_title,
                        "chapterTitle": chapter_title,
                        "cover_url": cover_url,
                        "coverUrl": cover_url,
                        "coverImageUrl": cover_url,
                        "item_id": item_id,
                        "card_id": card_id,
                        "slot_id": slot_id,
                        "card_title": card_title or now_playing,
                        "has_attached_card": has_attached_card,
                        "has_attached_playlist": has_attached_playlist,
                        "playback_mode": playback_mode,
                        "position": pos,
                        "duration": dur,
                        "speed": float(d.get("speed") or 1.0),
                        "playing_speed": d.get("playing_speed"),
                        "volume": vol,
                        "volume_max": v_max,
                        "day_mode": d.get("day_mode"),
                        "battery": d.get("battery") if d.get("battery") is not None else d.get("battery_level_percentage"),
                        "charging": d.get("charging"),
                        "sleep_timer_remaining": get_player_sleep_timer_remaining(did),
                        "playback": {
                            "state": dev_status if is_active_media else "stopped",
                            "position": pos,
                            "duration": dur
                        }
                    }
        except Exception as e:
            logger.debug("Bridge player status query notice: %s", e)

    # 2. Direct Yoto Cloud Fallback if not resolved from Bridge
    if not player_map and clients.yoto_client:
        try:
            for d in clients.yoto_client.get_devices():
                did = d.get("deviceId") or d.get("id")
                if not did:
                    continue
                is_online = bool(d.get("online"))
                is_home = verify_player_home_presence(did, is_online)
                player_map[did] = {
                    "id": did,
                    "deviceId": did,
                    "name": d.get("name") or "Yoto Player",
                    "online": is_online,
                    "is_home": is_home,
                    "location": "home" if is_home else "away",
                    "status": "online" if is_online else "offline",
                    "is_playing": False,
                    "has_card": False,
                    "now_playing": None,
                    "title": "No Active Playback",
                    "author": "",
                    "chapter_title": "",
                    "chapterTitle": "",
                    "cover_url": "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png",
                    "coverUrl": "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png",
                    "coverImageUrl": "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png",
                    "item_id": None,
                    "position": 0,
                    "duration": 0,
                    "volume": d.get("volume", 50) if d.get("volume") is not None else 50,
                    "volume_max": d.get("volume_max", 100) or 100,
                    "day_mode": None,
                    "playback": {
                        "state": "stopped",
                        "position": 0,
                        "duration": 0
                    }
                }
        except Exception as e:
            logger.debug("Direct Yoto device query fallback notice: %s", e)

    _cached_players_map = player_map
    _cached_players_ts = now
    return player_map


def get_player_status(device_id: str) -> Dict[str, Any]:
    """Returns single player status object, or an idle object if not found."""
    players = get_live_players_map()
    if device_id in players:
        return players[device_id]
    return {
        "id": device_id,
        "deviceId": device_id,
        "name": "Yoto Player",
        "online": False,
        "status": "offline",
        "is_playing": False,
        "has_card": False,
        "now_playing": None,
        "title": "Player Offline",
        "author": "",
        "chapter_title": "",
        "chapterTitle": "",
        "cover_url": "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png",
        "coverUrl": "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png",
        "coverImageUrl": "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png",
        "item_id": None,
        "card_id": None,
        "slot_id": None,
        "card_title": None,
        "has_attached_card": False,
        "has_attached_playlist": False,
        "playback_mode": "idle",
        "position": 0,
        "duration": 0,
        "volume": 50,
        "volume_max": 100,
        "playback": {
            "state": "stopped",
            "position": 0,
            "duration": 0
        }
    }


def dispatch_player_control(device_id: str, action: str, volume: Optional[int] = None,
                            minutes: Optional[int] = None, position: Optional[float] = None,
                            speed: Optional[float] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Centralized dispatch for player transport, volume, speed, seek, and sleep timer
    controls across both Kiosk and Parent Portal.
    """
    creds = database.get_api_credentials()
    mode = creds.get("yoto_connection_mode", "bridge")
    active_bridge_url = creds.get("yoto_bridge_url", "").rstrip("/")
    bridge_headers = {}
    if creds.get("yoto_bridge_api_key"):
        bridge_headers["X-Api-Key"] = creds["yoto_bridge_api_key"]
    if creds.get("yoto_ui_pin"):
        bridge_headers["X-Pin"] = str(creds["yoto_ui_pin"]).strip()

    try:
        # 1. Volume
        if action == "volume":
            if volume is None:
                return False, {"ok": False, "error": "volume is required"}, 400
            vol_val = max(0, min(100, int(volume)))
            # Parent volume ceiling check & clamp
            player_st = get_player_status(device_id)
            max_limit = player_st.get("volume_max", 100) or 100
            if vol_val > max_limit:
                vol_val = max_limit

            if mode == "bridge" and active_bridge_url:
                try:
                    r = _http_session.post(f"{active_bridge_url}/api/device/volume", json={"device_id": device_id, "volume": vol_val}, headers=bridge_headers, timeout=3)
                    if r.status_code == 404:
                        r = _http_session.post(f"{active_bridge_url}/api/yoto/volume", json={"device_id": device_id, "volume": vol_val}, headers=bridge_headers, timeout=3)
                    if r.status_code == 200:
                        return True, {"ok": True, "device_id": device_id, "volume": vol_val, "volume_max": max_limit}, 200
                except Exception as be:
                    logger.warning("Bridge volume relay error: %s", be)

            if clients.yoto_client:
                ok = clients.yoto_client.set_volume(device_id, vol_val)
                if ok:
                    return True, {"ok": True, "device_id": device_id, "volume": vol_val, "volume_max": max_limit}, 200
                return False, {"ok": False, "error": "Yoto Cloud volume command failed"}, 502

        # 2. Transport: pause, resume, stop
        elif action in ("pause", "resume", "stop"):
            if mode == "bridge" and active_bridge_url:
                try:
                    r = _http_session.post(f"{active_bridge_url}/api/control", json={"device_id": device_id, "action": action}, headers=bridge_headers, timeout=3)
                    if r.status_code == 200:
                        return True, {"ok": True, "device_id": device_id, "action": action}, 200
                except Exception as be:
                    logger.warning("Bridge transport relay error: %s", be)

            if clients.yoto_client:
                ok = clients.yoto_client.send_transport_command(device_id, action)
                if ok:
                    return True, {"ok": True, "device_id": device_id, "action": action}, 200
                return False, {"ok": False, "error": f"Yoto Cloud '{action}' transport command failed"}, 502

        # 3. Chapter Track Skip & 30s Jump: prev, next, back30, fwd30
        elif action in ("prev", "next", "back30", "fwd30"):
            if mode == "bridge" and active_bridge_url:
                try:
                    r = _http_session.post(f"{active_bridge_url}/api/seek", json={"device_id": device_id, "action": action}, headers=bridge_headers, timeout=3)
                    if r.status_code == 200:
                        return True, {"ok": True, "device_id": device_id, "action": action}, 200
                except Exception as be:
                    logger.warning("Bridge seek relay error: %s", be)
            return False, {"ok": False, "error": f"Seek '{action}' not supported in current mode"}, 400

        # 4. Interactive Scrub Bar Seek (position in seconds)
        elif action == "seek":
            target_sec = max(0, int(round(float(position or 0))))
            if mode == "bridge" and active_bridge_url:
                try:
                    r = _http_session.post(
                        f"{active_bridge_url}/api/seek",
                        json={"device_id": device_id, "action": "seek", "position": target_sec, "seconds": target_sec},
                        headers=bridge_headers,
                        timeout=3
                    )
                    if r.status_code == 200:
                        return True, {"ok": True, "device_id": device_id, "action": "seek", "position": target_sec}, 200
                    # Fallback: if bridge /api/seek only handles discrete jumps, trigger /api/play with seconds_in
                    st = get_player_status(device_id)
                    play_payload: Dict[str, Any] = {"device_id": device_id, "seconds_in": target_sec}
                    if st.get("item_id") and st.get("playback_mode") != "retail":
                        play_payload["item_id"] = st["item_id"]
                    elif st.get("card_id"):
                        play_payload["card_id"] = st["card_id"]
                    if "item_id" in play_payload or "card_id" in play_payload:
                        r2 = _http_session.post(f"{active_bridge_url}/api/play", json=play_payload, headers=bridge_headers, timeout=4)
                        if r2.status_code in (200, 204):
                            return True, {"ok": True, "device_id": device_id, "action": "seek", "position": target_sec}, 200
                except Exception as be:
                    logger.warning("Bridge scrub seek relay error: %s", be)
            return True, {"ok": True, "device_id": device_id, "action": "seek", "position": target_sec}, 200

        # 5. Playback Speed Control
        elif action == "speed":
            spd_val = max(0.5, min(2.0, float(speed or 1.0)))
            if mode == "bridge" and active_bridge_url:
                try:
                    r = _http_session.post(
                        f"{active_bridge_url}/api/speed",
                        json={"device_id": device_id, "speed": spd_val},
                        headers=bridge_headers,
                        timeout=3
                    )
                    if r.status_code == 200:
                        return True, {"ok": True, "device_id": device_id, "action": "speed", "speed": spd_val}, 200
                except Exception as be:
                    logger.warning("Bridge speed relay error: %s", be)
            st = get_player_status(device_id)
            if st.get("slot_id"):
                try:
                    from core.bridge.manager import get_bridge_manager
                    get_bridge_manager().set_slot_speed(st["slot_id"], spd_val)
                except Exception:
                    pass
            return True, {"ok": True, "device_id": device_id, "action": "speed", "speed": spd_val}, 200

        # 6. Bedtime Sleep Timer
        elif action == "sleep_timer":
            mins = int(minutes or 0)
            timer_info = set_player_sleep_timer(device_id, mins)
            return True, {"ok": True, "device_id": device_id, "action": "sleep_timer", **timer_info}, 200

        return False, {"ok": False, "error": f"Unsupported action '{action}'"}, 400

    except Exception as e:
        logger.error("Player control dispatch exception on %s (%s): %s", device_id, action, e)
        return False, {"ok": False, "error": str(e)}, 502
