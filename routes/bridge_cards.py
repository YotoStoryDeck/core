"""
StoryDeck Core Card Slot Inventory & Yoto Cloud Playlist Manager Blueprint (/api/cards*, /api/yoto/playlists*).
"""
from __future__ import annotations
import logging
from flask import Blueprint, request, jsonify
import database
import clients
from core.auth import require_auth
from core.bridge.manager import get_bridge_manager
from core.bridge.offline import get_offline_manager, prune_evicted_profile_playlists

logger = logging.getLogger("storydeck.routes.bridge_cards")
bridge_cards_bp = Blueprint("bridge_cards", __name__)


@bridge_cards_bp.route("/api/cards", methods=["GET"])
@require_auth
def list_cards():
    """Lists all registered card slots with active transcode and offline status."""
    mgr = get_bridge_manager()
    slots = mgr.list_slots()
    off_mgr = get_offline_manager()

    for s in slots:
        job = off_mgr.get_job_status(s["slot_id"])
        if job:
            s["transcode"] = job

    return jsonify(slots)


@bridge_cards_bp.route("/api/cards", methods=["POST"])
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


@bridge_cards_bp.route("/api/cards/<slot_id>", methods=["GET"])
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


@bridge_cards_bp.route("/api/cards/<slot_id>", methods=["PUT"])
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


@bridge_cards_bp.route("/api/cards/<slot_id>", methods=["DELETE"])
@require_auth
def delete_card(slot_id: str):
    """Deletes a card slot."""
    if get_bridge_manager().delete_slot(slot_id):
        return jsonify({"success": True})
    return jsonify({"error": "Slot not found"}), 404


@bridge_cards_bp.route("/api/cards/<slot_id>/speed", methods=["POST"])
@require_auth
def set_card_speed(slot_id: str):
    """Updates playback speed multiplier for a card slot."""
    data = request.get_json() or {}
    speed = float(data.get("speed", 1.0))
    if get_bridge_manager().set_slot_speed(slot_id, speed):
        return jsonify({"success": True, "speed": speed})
    return jsonify({"error": "Slot not found"}), 404


@bridge_cards_bp.route("/api/cards/<slot_id>/own-place", methods=["POST"])
@require_auth
def set_card_own_place(slot_id: str):
    """Toggles independent listening place for a card slot."""
    data = request.get_json() or {}
    own_place = bool(data.get("own_place", False))
    if get_bridge_manager().set_slot_own_place(slot_id, own_place):
        return jsonify({"success": True, "own_place": own_place})
    return jsonify({"error": "Slot not found"}), 404


@bridge_cards_bp.route("/api/cards/<slot_id>/mode", methods=["POST"])
@require_auth
def set_card_delivery_mode(slot_id: str):
    """Switches an existing card slot between 'streaming' and 'offline' delivery modes."""
    data = request.get_json() or {}
    target_mode = (data.get("mode") or "streaming").strip().lower()
    if target_mode not in ("streaming", "offline"):
        return jsonify({"error": "mode must be 'streaming' or 'offline'"}), 400

    base_url = request.host_url.rstrip("/")
    mgr = get_bridge_manager()
    slot = mgr.get_slot(slot_id)
    if not slot:
        return jsonify({"error": "Slot not found"}), 404

    conn = database.get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE bridge_slots SET mode = ?, updated_at = CURRENT_TIMESTAMP WHERE slot_id = ?;", (target_mode, slot_id))
    finally:
        conn.close()

    slot = mgr.get_slot(slot_id) or slot
    if target_mode == "offline":
        job = get_offline_manager().queue_transcode(slot_id, base_url=base_url)
        slot["transcode"] = job
    elif target_mode == "streaming" and clients.yoto_client and slot.get("abs_item_id"):
        try:
            yoto_cid = slot.get("yoto_card_id") or slot_id
            cover_url = f"{base_url}/api/cover/{slot['abs_item_id']}"
            clients.yoto_client.save_stream_playlist(
                title=slot.get("title", "Audiobook"),
                tracks=slot.get("tracks", []),
                card_id=yoto_cid,
                cover_url=cover_url,
                description=f"Streams {slot.get('title', '')} from Audiobookshelf"
            )
        except Exception as e:
            logger.warning("Failed to switch slot %s to streaming playlist: %s", slot_id, e)

    return jsonify({"success": True, "slot_id": slot_id, "mode": target_mode, "slot": slot})


@bridge_cards_bp.route("/api/cards/<slot_id>/pin", methods=["POST"])
@require_auth
def toggle_card_pin(slot_id: str):
    """Toggles pin / cache eviction protection on a card slot."""
    data = request.get_json() or {}
    is_pinned = bool(data.get("is_pinned", True))
    if get_bridge_manager().set_slot_pin(slot_id, is_pinned):
        return jsonify({"success": True, "is_pinned": is_pinned})
    return jsonify({"error": "Slot not found"}), 404


@bridge_cards_bp.route("/api/cards/assign", methods=["POST"])
@require_auth
def assign_card_content():
    """Assigns an ABS audiobook or Official Yoto Card to a profile primary or fleet card slot."""
    data = request.get_json() or {}
    abs_item_id = (data.get("abs_item_id") or "").strip()
    yoto_card_id = (data.get("yoto_card_id") or "").strip()
    if not abs_item_id and not yoto_card_id:
        return jsonify({"error": "abs_item_id or yoto_card_id is required"}), 400

    profile_id = data.get("profile_id")
    slot_id = data.get("slot_id")
    mode_override = data.get("mode", "default")
    base_url = request.host_url.rstrip("/")

    mgr = get_bridge_manager()

    if profile_id:
        if not abs_item_id:
            return jsonify({"error": "abs_item_id is required for profile primary card assignment"}), 400
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
            yoto_card_id=yoto_card_id,
            title=data.get("title", ""),
            author=data.get("author", ""),
            mode_override=mode_override,
            base_url=base_url
        )
    else:
        return jsonify({"error": "Either profile_id or slot_id must be provided"}), 400

    slot_mode = slot.get("mode", "streaming")
    slot_key = slot.get("slot_id")

    if slot_mode == "offline":
        job = get_offline_manager().queue_transcode(slot_key, base_url=base_url)
        slot["transcode"] = job
    elif slot_mode == "streaming" and clients.yoto_client:
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


@bridge_cards_bp.route("/api/yoto/playlists", methods=["GET"])
@require_auth
def list_yoto_playlists():
    """Returns all Yoto Cloud user playlists classified by StoryDeck vs custom source and pin state."""
    if not clients.yoto_client:
        return jsonify([])

    raw_playlists = clients.yoto_client.get_all_cloud_playlists()
    mgr = get_bridge_manager()
    registered_slots = {s["slot_id"]: s for s in mgr.list_slots()}

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

        slot = registered_slots.get(cid) or yoto_map.get(cid)
        is_broker = bool(slot) or "storydeck" in desc or "streams from audiobookshelf" in desc or gen == "storydeck-core"

        is_pinned = bool(slot.get("is_pinned", 0)) if slot else False
        is_protected = bool(slot.get("is_protected", 0)) if slot else False
        mode = slot.get("mode", "streaming") if slot else "custom"
        owner_profile_id = slot.get("owner_profile_id") if slot else ""
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


@bridge_cards_bp.route("/api/yoto/playlists/<card_id>", methods=["DELETE"])
@require_auth
def delete_yoto_playlist(card_id: str):
    """Manually deletes a playlist from Yoto Cloud and cascades removal of any linked local slot."""
    if not clients.yoto_client:
        return jsonify({"error": "Yoto client not configured"}), 503

    if not clients.yoto_client.delete_playlist(card_id):
        return jsonify({"error": "Failed to delete playlist from Yoto Cloud"}), 500

    mgr = get_bridge_manager()
    if mgr.get_slot(card_id):
        mgr.delete_slot(card_id)
    else:
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM bridge_slots WHERE yoto_card_id = ?;", (card_id,))
        finally:
            conn.close()

    return jsonify({"success": True, "card_id": card_id})


@bridge_cards_bp.route("/api/yoto/playlists/<card_id>/pin", methods=["POST"])
@require_auth
def toggle_playlist_pin(card_id: str):
    """Toggles pin / protection status for a playlist."""
    data = request.get_json() or {}
    is_pinned = bool(data.get("is_pinned", True))

    mgr = get_bridge_manager()
    if mgr.get_slot(card_id):
        mgr.set_slot_pin(card_id, is_pinned)
        return jsonify({"success": True, "card_id": card_id, "is_pinned": is_pinned})

    conn = database.get_db_connection()
    try:
        with conn:
            val = 1 if is_pinned else 0
            conn.execute("""
                INSERT INTO bridge_slots (slot_id, yoto_card_id, kind, is_pinned, is_protected, updated_at)
                VALUES (?, ?, 'custom_playlist', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(slot_id) DO UPDATE SET is_pinned = excluded.is_pinned, is_protected = excluded.is_protected;
            """, (card_id, card_id, val, val))
        return jsonify({"success": True, "card_id": card_id, "is_pinned": is_pinned})
    finally:
        conn.close()


@bridge_cards_bp.route("/api/yoto/playlists/prune", methods=["POST"])
@require_auth
def trigger_lru_prune():
    """Manually triggers LRU pruning of evicted ephemeral profile playlists."""
    return jsonify(prune_evicted_profile_playlists())
