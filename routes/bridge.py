"""
StoryDeck Core Bridge Blueprint.
Consolidated audio streaming, card slot inventory, and Yoto Cloud playlist manager.
"""
from __future__ import annotations
import io
import re
import logging
from typing import Dict, Any, List, Optional
from flask import Blueprint, request, Response, jsonify, send_file
import database
import clients
from core.auth import require_auth, require_admin
from core.bridge.manager import get_bridge_manager
from core.bridge.streamer import AudioStreamer, AudioTrackSource
from core.bridge.offline import get_offline_manager, prune_evicted_profile_playlists

logger = logging.getLogger("storydeck.routes.bridge")
bridge_bp = Blueprint("bridge", __name__)


# -----------------------------------------------------------------------------
# 1. Audio Streaming & Icon Endpoints (Yoto Devices & Players)
# -----------------------------------------------------------------------------

@bridge_bp.route("/s/health", methods=["GET"])
def health_check():
    """Health check endpoint for reverse proxy, deploy scripts, and Uptime Kuma."""
    return jsonify({
        "status": "healthy",
        "service": "storydeck-core-bridge",
        "version": "v1.1.0"
    }), 200


@bridge_bp.route("/s/audio/<slot_id>/<int:track_idx>", methods=["GET"])
def stream_track_audio(slot_id: str, track_idx: int):
    """
    Streams a constant-bitrate MP3 chapter track with HTTP 206 Range request support.
    Compatible with Yoto Player dynamic stream chapters and standard media players.
    """
    mgr = get_bridge_manager()
    slot = mgr.get_slot(slot_id)
    if not slot:
        return Response("Slot not found", status=404)

    track = mgr.get_track(slot_id, track_idx)
    if not track:
        return Response("Track not found", status=404)

    start_sec = float(track["start_time"])
    end_sec = float(track["end_time"])
    duration = max(0.1, end_sec - start_sec)
    speed = float(slot.get("speed") or 1.0)

    streamer = AudioStreamer(bitrate_kbps=64, channels=1, sample_rate=44100)
    total_bytes = streamer.seconds_to_bytes(duration, speed)

    # 1. Fetch ABS Item Sources
    abs_item_id = slot.get("abs_item_id")
    if not abs_item_id or not clients.abs_client:
        return Response("Audiobookshelf item not available", status=503)

    try:
        item_data = clients.abs_client.get_item(abs_item_id)
    except Exception as e:
        logger.error("Failed to fetch ABS item for stream %s/%d: %s", slot_id, track_idx, e)
        return Response("Audio source unavailable", status=502)

    media = (item_data or {}).get("media", {})
    audio_files = media.get("audioFiles", [])
    if not audio_files:
        return Response("No audio files in book", status=404)

    sources: List[AudioTrackSource] = []
    c_offset = 0.0
    abs_token = clients.abs_client.token if hasattr(clients.abs_client, "token") else ""
    abs_base = clients.abs_client.base_url if hasattr(clients.abs_client, "base_url") else ""
    auth_hdr = f"Bearer {abs_token}" if abs_token else ""

    for af in audio_files:
        ino = af.get("ino") or af.get("id") or ""
        f_dur = float(af.get("duration") or 0.0)
        url = f"{abs_base}/api/items/{abs_item_id}/file/{ino}"
        sources.append(AudioTrackSource(url=url, start=c_offset, duration=f_dur))
        c_offset += f_dur

    # 2. Parse Range Header
    range_header = request.headers.get("Range")
    byte_start = 0
    byte_end = total_bytes - 1

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            byte_start = int(m.group(1))
            if m.group(2):
                byte_end = min(total_bytes - 1, int(m.group(2)))

    if byte_start >= total_bytes:
        return Response(
            status=416,
            headers={"Content-Range": f"bytes */{total_bytes}"}
        )

    content_length = byte_end - byte_start + 1
    seek_sec = streamer.bytes_to_seconds(byte_start, speed)
    req_start_sec = start_sec + seek_sec
    req_end_sec = min(end_sec, start_sec + streamer.bytes_to_seconds(byte_end + 1, speed))

    def generate_chunks():
        bytes_sent = 0
        for chunk in streamer.stream_segment(sources, req_start_sec, req_end_sec, auth_header=auth_hdr, speed=speed):
            remaining = content_length - bytes_sent
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                yield chunk[:remaining]
                bytes_sent += remaining
                break
            yield chunk
            bytes_sent += len(chunk)

    status_code = 206 if range_header else 200
    headers = {
        "Content-Type": "audio/mpeg",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Cache-Control": "no-cache",
    }
    if range_header:
        headers["Content-Range"] = f"bytes {byte_start}-{byte_end}/{total_bytes}"

    return Response(generate_chunks(), status=status_code, headers=headers)


@bridge_bp.route("/s/stream/<slot_id>", methods=["GET"])
def stream_slot_legacy(slot_id: str):
    """Legacy whole-book stream endpoint, forwarding to track 1."""
    return stream_track_audio(slot_id, 1)


@bridge_bp.route("/s/icon/<slot_id>.png", methods=["GET"])
@bridge_bp.route("/s/icon/<slot_id>/<int:track_idx>.png", methods=["GET"])
def serve_track_icon(slot_id: str, track_idx: int = 1):
    """Serves a 16x16 pixel art PNG icon for display on Yoto Player display."""
    mgr = get_bridge_manager()
    slot = mgr.get_slot(slot_id)
    abs_item_id = slot.get("abs_item_id") if slot else None

    # Check if a custom icon exists in DB or item cache
    if abs_item_id and clients.yoto_client:
        icon_bytes = clients.yoto_client.get_item_chapter_icon(abs_item_id, track_idx)
        if icon_bytes:
            return Response(icon_bytes, mimetype="image/png")

    # Fallback default 16x16 icon (orange Yoto-style disc)
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([1, 1, 14, 14], fill=(229, 83, 30, 255))
    draw.ellipse([6, 6, 9, 9], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


# -----------------------------------------------------------------------------
# 2. Card Slot Inventory Management (/api/cards)
# -----------------------------------------------------------------------------

@bridge_bp.route("/api/cards", methods=["GET"])
@require_auth
def list_cards():
    """Lists all registered card slots with active transcode and offline status."""
    mgr = get_bridge_manager()
    slots = mgr.list_slots()
    off_mgr = get_offline_manager()

    for s in slots:
        s_id = s["slot_id"]
        job = off_mgr.get_job_status(s_id)
        if job:
            s["transcode"] = job

    return jsonify(slots)


@bridge_bp.route("/api/cards", methods=["POST"])
@require_auth
def create_card():
    """Registers a new card slot."""
    data = request.get_json() or {}
    slot_id = data.get("slot_id") or data.get("id")
    if not slot_id:
        return jsonify({"error": "slot_id is required"}), 400

    mgr = get_bridge_manager()
    slot = mgr.assign_abs_book_to_slot(
        slot_id=slot_id,
        abs_item_id=data.get("abs_item_id", ""),
        title=data.get("title", ""),
        author=data.get("author", ""),
        owner_profile_id=data.get("owner_profile_id", ""),
        kind=data.get("kind", "permanent_myo"),
        mode=data.get("mode", "streaming")
    )
    return jsonify(slot), 201


@bridge_bp.route("/api/cards/<slot_id>", methods=["GET"])
@require_auth
def get_card(slot_id: str):
    """Retrieves slot details and track layout."""
    mgr = get_bridge_manager()
    slot = mgr.get_slot(slot_id)
    if not slot:
        return jsonify({"error": "Slot not found"}), 404

    job = get_offline_manager().get_job_status(slot_id)
    if job:
        slot["transcode"] = job
    return jsonify(slot)


@bridge_bp.route("/api/cards/<slot_id>", methods=["PUT"])
@require_auth
def update_card(slot_id: str):
    """Updates slot settings."""
    data = request.get_json() or {}
    mgr = get_bridge_manager()
    slot = mgr.get_slot(slot_id)
    if not slot:
        return jsonify({"error": "Slot not found"}), 404

    if "speed" in data:
        mgr.set_slot_speed(slot_id, float(data["speed"]))
    if "own_place" in data:
        mgr.set_slot_own_place(slot_id, bool(data["own_place"]))
    if "is_pinned" in data:
        mgr.set_slot_pin(slot_id, bool(data["is_pinned"]))

    return jsonify(mgr.get_slot(slot_id))


@bridge_bp.route("/api/cards/<slot_id>", methods=["DELETE"])
@require_auth
def delete_card(slot_id: str):
    """Deletes a card slot."""
    mgr = get_bridge_manager()
    if mgr.delete_slot(slot_id):
        return jsonify({"success": True})
    return jsonify({"error": "Slot not found"}), 404


@bridge_bp.route("/api/cards/<slot_id>/speed", methods=["POST"])
@require_auth
def set_card_speed(slot_id: str):
    data = request.get_json() or {}
    speed = float(data.get("speed", 1.0))
    if get_bridge_manager().set_slot_speed(slot_id, speed):
        return jsonify({"success": True, "speed": speed})
    return jsonify({"error": "Slot not found"}), 404


@bridge_bp.route("/api/cards/<slot_id>/own-place", methods=["POST"])
@require_auth
def set_card_own_place(slot_id: str):
    data = request.get_json() or {}
    own_place = bool(data.get("own_place", False))
    if get_bridge_manager().set_slot_own_place(slot_id, own_place):
        return jsonify({"success": True, "own_place": own_place})
    return jsonify({"error": "Slot not found"}), 404


@bridge_bp.route("/api/cards/<slot_id>/pin", methods=["POST"])
@require_auth
def toggle_card_pin(slot_id: str):
    data = request.get_json() or {}
    is_pinned = bool(data.get("is_pinned", True))
    if get_bridge_manager().set_slot_pin(slot_id, is_pinned):
        return jsonify({"success": True, "is_pinned": is_pinned})
    return jsonify({"error": "Slot not found"}), 404


@bridge_bp.route("/api/cards/assign", methods=["POST"])
@require_auth
def assign_card_content():
    """
    Assigns an ABS audiobook to a card slot with configurable delivery mode:
    - profile_id: updates child profile's primary card
    - slot_id: updates specified fleet card slot
    - mode: 'default', 'streaming', or 'offline'
    """
    data = request.get_json() or {}
    abs_item_id = data.get("abs_item_id")
    if not abs_item_id:
        return jsonify({"error": "abs_item_id is required"}), 400

    profile_id = data.get("profile_id")
    slot_id = data.get("slot_id")
    mode_override = data.get("mode", "default")
    base_url = request.host_url.rstrip("/")

    mgr = get_bridge_manager()

    if profile_id:
        try:
            slot = mgr.update_profile_primary_card(
                profile_id=profile_id,
                abs_item_id=abs_item_id,
                mode_override=mode_override,
                base_url=base_url
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    elif slot_id:
        slot = mgr.assign_to_fleet_card(
            slot_id=slot_id,
            abs_item_id=abs_item_id,
            mode_override=mode_override,
            base_url=base_url
        )
    else:
        return jsonify({"error": "Either profile_id or slot_id must be provided"}), 400

    slot_mode = slot.get("mode", "streaming")
    slot_key = slot.get("slot_id")

    # If offline delivery mode selected, trigger background transcode & upload
    if slot_mode == "offline":
        job = get_offline_manager().queue_transcode(slot_key, base_url=base_url)
        slot["transcode"] = job
    elif slot_mode == "streaming" and clients.yoto_client:
        # Update or create stream playlist in Yoto Cloud
        try:
            yoto_cid = slot.get("yoto_card_id") or slot_key
            cover_url = f"{base_url}/api/cover/{abs_item_id}"
            saved_id = clients.yoto_client.save_stream_playlist(
                title=slot.get("title", "Audiobook"),
                tracks=slot.get("tracks", []),
                card_id=yoto_cid,
                cover_url=cover_url,
                description=f"Streams {slot.get('title', '')} from Audiobookshelf"
            )
            if saved_id:
                slot["yoto_card_id"] = saved_id
        except Exception as e:
            logger.warning("Failed to push stream playlist to Yoto Cloud: %s", e)

    return jsonify(slot)


# -----------------------------------------------------------------------------
# 3. Yoto Cloud Playlists Manager (/api/yoto/playlists)
# -----------------------------------------------------------------------------

@bridge_bp.route("/api/yoto/playlists", methods=["GET"])
@require_auth
def list_yoto_playlists():
    """
    Returns all Yoto Cloud user playlists with classification:
    - source: 'broker' (created by StoryDeck / Bridge) vs 'custom' (user/external)
    - is_pinned: protected from automated pruning
    - is_physical: bound to physical NFC card
    - mode: 'streaming' vs 'offline'
    """
    if not clients.yoto_client:
        return jsonify([])

    raw_playlists = clients.yoto_client.get_all_cloud_playlists()
    mgr = get_bridge_manager()
    registered_slots = {s["slot_id"]: s for s in mgr.list_slots()}

    # Also lookup slots by yoto_card_id
    yoto_map = {}
    for s in registered_slots.values():
        y_cid = s.get("yoto_card_id")
        if y_cid:
            yoto_map[y_cid] = s

    enriched = []
    for p in raw_playlists:
        cid = p.get("cardId") or p.get("id") or ""
        title = p.get("title") or "Yoto Playlist"
        meta = p.get("metadata") or {}
        content = p.get("content") or {}
        desc = (meta.get("description") or "").lower()
        gen = (meta.get("generator") or "").lower()

        # Check if matched in registered slots
        slot = registered_slots.get(cid) or yoto_map.get(cid)
        is_broker = bool(slot) or "storydeck" in desc or "streams from audiobookshelf" in desc or gen == "storydeck-core"

        is_pinned = bool(slot.get("is_pinned", 0)) if slot else False
        is_protected = bool(slot.get("is_protected", 0)) if slot else False
        mode = slot.get("mode", "streaming") if slot else "custom"
        owner_profile_id = slot.get("owner_profile_id") if slot else ""

        # Check physical MYO binding
        is_physical = bool(p.get("shareType") == "myo" or str(p.get("reason", "")).startswith("myo"))

        cover_url = meta.get("cover", {}).get("imageL") or content.get("cover", {}).get("imageL") or ""

        enriched.append({
            "card_id": cid,
            "title": title,
            "author": meta.get("author") or "Yoto",
            "source": "broker" if is_broker else "custom",
            "is_broker": is_broker,
            "is_pinned": is_pinned or is_protected,
            "is_physical": is_physical,
            "mode": mode,
            "owner_profile_id": owner_profile_id,
            "slot_id": slot.get("slot_id") if slot else None,
            "cover_url": cover_url,
            "chapters_count": len(content.get("chapters", []))
        })

    enriched.sort(key=lambda x: (not x["is_broker"], x["title"].lower()))
    return jsonify(enriched)


@bridge_bp.route("/api/yoto/playlists/<card_id>", methods=["DELETE"])
@require_auth
def delete_yoto_playlist(card_id: str):
    """
    Manually deletes a playlist from Yoto Cloud (outside automated pruning).
    Also cascades and cleans up any linked bridge slot.
    """
    if not clients.yoto_client:
        return jsonify({"error": "Yoto client not configured"}), 503

    success = clients.yoto_client.delete_playlist(card_id)
    if not success:
        return jsonify({"error": "Failed to delete playlist from Yoto Cloud"}), 500

    # Cleanup local slot if present
    mgr = get_bridge_manager()
    slot = mgr.get_slot(card_id)
    if slot:
        mgr.delete_slot(card_id)
    else:
        # Check by yoto_card_id
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM bridge_slots WHERE yoto_card_id = ?;", (card_id,))
        finally:
            conn.close()

    return jsonify({"success": True, "card_id": card_id})


@bridge_bp.route("/api/yoto/playlists/<card_id>/pin", methods=["POST"])
@require_auth
def toggle_playlist_pin(card_id: str):
    """Toggles pin / protection status for a playlist."""
    data = request.get_json() or {}
    is_pinned = bool(data.get("is_pinned", True))

    mgr = get_bridge_manager()
    slot = mgr.get_slot(card_id)
    if slot:
        mgr.set_slot_pin(card_id, is_pinned)
        return jsonify({"success": True, "card_id": card_id, "is_pinned": is_pinned})

    # If slot doesn't exist yet, insert a placeholder record to remember pin status
    conn = database.get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            val = 1 if is_pinned else 0
            cur.execute("""
                INSERT INTO bridge_slots (slot_id, yoto_card_id, kind, is_pinned, is_protected, updated_at)
                VALUES (?, ?, 'custom_playlist', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(slot_id) DO UPDATE SET is_pinned = excluded.is_pinned, is_protected = excluded.is_protected;
            """, (card_id, card_id, val, val))
        return jsonify({"success": True, "card_id": card_id, "is_pinned": is_pinned})
    finally:
        conn.close()


@bridge_bp.route("/api/yoto/playlists/prune", methods=["POST"])
@require_auth
def trigger_lru_prune():
    """
    Manually triggers LRU pruning of evicted ephemeral profile playlists.
    Strictly preserves pinned, protected, and physical cards.
    """
    result = prune_evicted_profile_playlists()
    return jsonify(result)


# -----------------------------------------------------------------------------
# 4. Mobile Front Portal Player & Catalog Endpoints
# -----------------------------------------------------------------------------

@bridge_bp.route("/api/player/devices", methods=["GET"])
@require_auth
def get_player_devices():
    """Returns available Yoto player hardware devices."""
    if not clients.yoto_client:
        return jsonify([])
    try:
        devices = clients.yoto_client.get_devices()
        return jsonify(devices)
    except Exception as e:
        logger.error("Failed to query player devices: %s", e)
        return jsonify([])


@bridge_bp.route("/api/player/status/<device_id>", methods=["GET"])
@require_auth
def get_device_status_endpoint(device_id: str):
    """Returns device playback status (volume, online, playing)."""
    if not clients.yoto_client:
        return jsonify({})
    try:
        status = clients.yoto_client.get_card_detail(device_id) or {}
        return jsonify(status)
    except Exception as e:
        logger.debug("Device status query notice for %s: %s", device_id, e)
        return jsonify({})


@bridge_bp.route("/api/player/transport", methods=["POST"])
@require_auth
def send_player_transport():
    """
    Sends transport and volume commands from the Parent Web Portal.
    Payload: { "device_id": str, "action": "play"|"pause"|"resume"|"stop"|"next"|"prev"|"volume", "volume": int }
    """
    data = request.get_json() or {}
    device_id = data.get("device_id")
    action = data.get("action")
    if not device_id or not action:
        return jsonify({"error": "device_id and action are required"}), 400

    if not clients.yoto_client:
        return jsonify({"error": "Yoto client not configured"}), 503

    if action == "volume":
        vol = max(0, min(100, int(data.get("volume", 50))))
        ok = clients.yoto_client.set_volume(device_id, vol)
        return jsonify({"ok": ok, "volume": vol})
    else:
        # map 'play' action to 'resume'
        act = "resume" if action == "play" else action
        ok = clients.yoto_client.send_transport_command(device_id, act)
        return jsonify({"ok": ok, "action": action})


@bridge_bp.route("/api/player/play", methods=["POST"])
@require_auth
def start_player_card():
    """
    Commands a Yoto player to begin playback of a specific card/playlist.
    Payload: { "device_id": str, "card_id": str, "chapter": int }
    """
    data = request.get_json() or {}
    device_id = data.get("device_id")
    card_id = data.get("card_id")
    chapter = int(data.get("chapter", 1))

    if not device_id or not card_id:
        return jsonify({"error": "device_id and card_id are required"}), 400

    if not clients.yoto_client:
        return jsonify({"error": "Yoto client not configured"}), 503

    ok = clients.yoto_client.start_playback(device_id, card_id, chapter=chapter)
    return jsonify({"ok": ok, "device_id": device_id, "card_id": card_id, "chapter": chapter})


@bridge_bp.route("/api/library/profile/<profile_id>", methods=["GET"])
@require_auth
def get_profile_library_catalog(profile_id: str):
    """Returns curated ABS audiobooks and series permitted for the specified child profile."""
    from database.curation import get_catalog_items_for_profile
    try:
        items = get_catalog_items_for_profile(profile_id, media_type="abs", client_type="kiosk")
        return jsonify(items)
    except Exception as e:
        logger.error("Failed to query catalog for profile %s: %s", profile_id, e)
        return jsonify([])
