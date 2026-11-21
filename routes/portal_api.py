"""
Mobile Parent Portal Player Controls, MQTT Status, and Profile Library Blueprint.
"""
from __future__ import annotations
import time
import logging
from typing import Dict, Any, List
from flask import Blueprint, request, jsonify
import database
import clients
from core.auth import require_auth
from core.bridge.mqtt_client import get_mqtt_bridge
from core.bridge.playback import get_playback_manager
from core.media_utils import get_media_tracks_data

logger = logging.getLogger("storydeck.routes.portal_api")
portal_api_bp = Blueprint("portal_api", __name__)


@portal_api_bp.route("/api/yoto/auth-status", methods=["GET"])
@require_auth
def get_yoto_auth_status():
    """Reports live Yoto API OAuth token health for Parent Portal status indicator & feature lockout."""
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    if not clients.yoto_client:
        return jsonify({
            "ok": False,
            "connected": False,
            "token_valid": False,
            "configured": False,
            "mode": "direct",
            "reason": "not_configured",
            "error": "Yoto API client is not initialized. Open Admin Settings to connect Yoto.",
            "checked_at": time.time()
        })
    return jsonify(clients.yoto_client.get_auth_status(verify=True, force=force))


@portal_api_bp.route("/api/player/devices", methods=["GET"])
@require_auth
def get_player_devices():
    """Returns available Yoto player hardware devices with live status."""
    from core.player_service import get_live_players_map
    try:
        return jsonify(list(get_live_players_map().values()))
    except Exception as e:
        logger.error("Failed to query player devices: %s", e)
        return jsonify([])


@portal_api_bp.route("/api/player/status/<device_id>", methods=["GET"])
@require_auth
def get_device_status_endpoint(device_id: str):
    """Returns single device playback status."""
    from core.player_service import get_player_status
    try:
        return jsonify(get_player_status(device_id))
    except Exception as e:
        logger.debug("Device status query notice for %s: %s", device_id, e)
        return jsonify({})


@portal_api_bp.route("/api/player/transport", methods=["POST"])
@require_auth
def send_player_transport():
    """Sends transport, volume, speed, seek, and sleep timer commands from the Parent Portal."""
    from core.player_service import dispatch_player_control
    data = request.get_json() or {}
    device_id = data.get("device_id")
    action = data.get("action")
    if not device_id or not action:
        return jsonify({"ok": False, "error": "device_id and action are required"}), 400

    act = "resume" if action == "play" else action
    _, resp_data, status_code = dispatch_player_control(
        device_id,
        act,
        volume=data.get("volume"),
        minutes=data.get("minutes"),
        position=data.get("position"),
        speed=data.get("speed")
    )
    return jsonify(resp_data), status_code


@portal_api_bp.route("/api/player/play", methods=["POST"])
@require_auth
def start_player_card():
    """Commands a Yoto player to begin playback of a specific card/playlist."""
    data = request.get_json() or {}
    device_id = data.get("device_id")
    card_id = data.get("card_id")
    chapter = int(data.get("chapter", 1))

    if not device_id or not card_id:
        return jsonify({"error": "device_id and card_id are required"}), 400

    get_playback_manager().expect(device_id, card_id)

    mqtt = get_mqtt_bridge()
    if mqtt.is_connected and mqtt.play(device_id, card_id, track=chapter):
        return jsonify({"ok": True, "device_id": device_id, "card_id": card_id, "chapter": chapter, "via": "mqtt"})

    if not clients.yoto_client:
        return jsonify({"error": "Yoto client not configured"}), 503

    ok = clients.yoto_client.start_playback(device_id, card_id, chapter=chapter)
    return jsonify({"ok": ok, "device_id": device_id, "card_id": card_id, "chapter": chapter})


@portal_api_bp.route("/api/bridge/mqtt/status", methods=["GET"])
@require_auth
def get_bridge_mqtt_status():
    """Returns embedded Yoto MQTT connection telemetry and active ABS stream playback sessions."""
    return jsonify({
        "ok": True,
        "mqtt": get_mqtt_bridge().get_status_summary(),
        "active_sessions": get_playback_manager().get_active_sessions_summary()
    })


def _query_profile_library_catalog(profile_id: str) -> List[Dict[str, Any]]:
    """Builds the curated ABS catalog list for a child profile or '__all__' household view."""
    from database.curation import get_catalog_items_for_profile, sanitize_display_text
    if profile_id == "__all__":
        matrix = database.get_catalog_matrix()
        return [
            {
                "id": it.get("id"),
                "type": "abs",
                "title": sanitize_display_text(it.get("title") or ""),
                "author": sanitize_display_text(it.get("author") or "Unknown"),
                "thumb": it.get("cover_url") or f"/api/thumb?type=abs&id={it.get('id', '')}",
                "is_highlight": bool(it.get("is_highlight")),
                "series": sanitize_display_text(it.get("series") or ""),
                "sequence_display": it.get("series_order") or "",
                "series_list": it.get("series_list") or [],
                "last_played_at": it.get("last_played_at") or ""
            }
            for it in matrix.get("items", [])
            if it.get("type") == "abs"
        ]
    return get_catalog_items_for_profile(profile_id, media_type="abs", client_type="kiosk")


@portal_api_bp.route("/api/library/profile/<profile_id>", methods=["GET"])
@require_auth
def get_profile_library_catalog(profile_id: str):
    """Returns curated ABS audiobooks and series permitted for the specified child profile."""
    try:
        return jsonify(_query_profile_library_catalog(profile_id))
    except Exception as e:
        logger.error("Failed to query catalog for profile %s: %s", profile_id, e)
        return jsonify([])


@portal_api_bp.route("/api/library/recent/<profile_id>", methods=["GET"])
@require_auth
def get_profile_recent_books(profile_id: str):
    """Returns recently played / in-progress books for the 'Continue Listening' shelf."""
    try:
        items = _query_profile_library_catalog(profile_id)
        recent = [it for it in (items or []) if it.get("last_played_at")]
        recent.sort(key=lambda x: str(x.get("last_played_at") or ""), reverse=True)
        return jsonify(recent[:8])
    except Exception as e:
        logger.debug("Recent books lookup notice for %s: %s", profile_id, e)
        return jsonify([])


@portal_api_bp.route("/api/library/yoto", methods=["GET"])
@require_auth
def get_household_yoto_cards():
    """Returns household Yoto retail and MYO cards for assigning official Yoto content to Fleet cards."""
    try:
        matrix = database.get_catalog_matrix()
        cards = [
            {
                "id": it.get("id"),
                "title": it.get("title") or "Yoto Card",
                "author": it.get("author") or "Yoto",
                "type": it.get("type"),
                "cover_url": it.get("cover_url") or ""
            }
            for it in matrix.get("items", [])
            if str(it.get("type") or "").startswith("yoto")
        ]
        cards.sort(key=lambda c: c["title"].lower())
        return jsonify(cards)
    except Exception as e:
        logger.debug("Household Yoto cards lookup notice: %s", e)
        return jsonify([])


@portal_api_bp.route("/api/library/book/<item_id>/details", methods=["GET"])
@require_auth
def get_portal_book_details(item_id: str):
    """Returns book synopsis/description and full chapter breakdown for the Parent Portal Book Modal."""
    description = ""
    total_duration = 0.0
    tracks = []
    title = ""
    author = ""
    try:
        tdata = get_media_tracks_data(item_id)
        if isinstance(tdata, dict):
            title = tdata.get("title") or ""
            author = tdata.get("author") or ""
            tracks = tdata.get("tracks") or []
            total_duration = float(tdata.get("total_duration") or 0.0)
    except Exception as e:
        logger.debug("Portal tracks lookup notice for %s: %s", item_id, e)

    if clients.abs_client:
        try:
            abs_item = clients.abs_client.get_item(item_id)
            if abs_item:
                media = abs_item.get("media", {})
                meta = media.get("metadata", {})
                description = meta.get("description") or meta.get("subtitle") or ""
                if not total_duration:
                    total_duration = float(media.get("duration") or 0.0)
                if not tracks:
                    for idx, ch in enumerate(media.get("chapters", []), 1):
                        st = float(ch.get("start", 0.0))
                        et = float(ch.get("end", st))
                        tracks.append({
                            "number": idx,
                            "title": ch.get("title") or f"Chapter {idx}",
                            "start": st,
                            "end": et,
                            "duration": max(0.0, et - st)
                        })
        except Exception as e:
            logger.debug("Portal ABS item synopsis lookup notice for %s: %s", item_id, e)

    return jsonify({
        "id": item_id,
        "title": title,
        "author": author,
        "description": description,
        "total_duration": total_duration,
        "tracks": tracks
    })
