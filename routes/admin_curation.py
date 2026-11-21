"""
Admin media catalog, curation rules, highlights, permissions, and ABS tagging blueprint.
"""
import json
from typing import Optional
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import logger
from core.auth import require_admin
# Re-exported for backwards compatibility with existing imports/tests
from core.media_utils import (  # noqa: F401
    parse_single_series,
    extract_series_list,
    get_media_tracks_data,
    parse_track_names,
    TINY_DIGITS,
    extract_chapter_number,
    render_16x16_icon_with_overlay,
)

admin_curation_bp = Blueprint("admin_curation", __name__)


@admin_curation_bp.route("/api/admin/catalog/matrix", methods=["GET"])
@require_admin
def admin_get_catalog_matrix():
    """Returns complete media catalog with highlight flags and per-profile permissions."""
    return jsonify(database.get_catalog_matrix())


@admin_curation_bp.route("/api/admin/catalog/highlight/<media_id>", methods=["POST"])
@require_admin
def admin_toggle_highlight(media_id: str):
    """Toggles seasonal/pinned highlight status for an item."""
    data = request.get_json(silent=True) or {}
    is_hi = bool(data.get("is_highlight", False))
    database.set_item_highlight(media_id, is_hi)
    return jsonify({"ok": True, "is_highlight": is_hi})


@admin_curation_bp.route("/api/admin/catalog/physical/<media_id>", methods=["POST"])
@require_admin
def admin_toggle_physical(media_id: str):
    """Toggles physical plastic card ownership flag for an item."""
    data = request.get_json(silent=True) or {}
    has_phys = bool(data.get("has_physical", False))
    database.set_item_physical(media_id, has_phys)
    return jsonify({"ok": True, "has_physical": has_phys})


@admin_curation_bp.route("/api/admin/catalog/refresh", methods=["POST"])
@admin_curation_bp.route("/api/admin/catalog/refresh/<profile_id>", methods=["POST"])
@require_admin
def admin_force_refresh_catalog(profile_id: Optional[str] = None):
    """Forces an immediate library sync and catalog rotation re-roll."""
    from core.scheduler import perform_library_refresh
    count = perform_library_refresh()
    return jsonify({"ok": True, "count": count, "profile_id": profile_id})


@admin_curation_bp.route("/api/admin/curation/shared-rule", methods=["POST"])
@require_admin
def admin_update_shared_rule():
    """Updates a shared household rule (e.g. include_all, include_myo_by_default)."""
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    value = data.get("value")
    if key:
        database.set_shared_rule(key, value)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Missing key"}), 400


@admin_curation_bp.route("/api/admin/curation/permission", methods=["POST"])
@require_admin
def admin_update_permission():
    """Toggles a single profile's permission on a card."""
    data = request.get_json(silent=True) or {}
    prof_id = data.get("profile_id")
    media_id = data.get("media_id")
    allowed = bool(data.get("allowed", False))

    prof = database.get_profile_by_id(prof_id)
    if not prof:
        return jsonify({"ok": False, "error": "Profile not found"}), 404

    yoto_cfg = prof.get("yoto", {})
    allowed_list = set(yoto_cfg.get("allowed_card_ids", []))
    excluded_list = set(yoto_cfg.get("excluded_card_ids", []))

    if allowed:
        allowed_list.add(media_id)
        excluded_list.discard(media_id)
    else:
        allowed_list.discard(media_id)
        excluded_list.add(media_id)

    yoto_cfg["allowed_card_ids"] = list(allowed_list)
    yoto_cfg["excluded_card_ids"] = list(excluded_list)
    prof["yoto"] = yoto_cfg

    database.upsert_profile(prof_id, prof)
    return jsonify({"ok": True})


@admin_curation_bp.route("/api/admin/curation/batch-permissions", methods=["POST"])
@require_admin
def admin_batch_permissions():
    """Atomically updates permissions across multiple media items and profiles."""
    try:
        data = request.get_json(silent=True) or {}
        media_ids = data.get("media_ids", [])
        profile_actions = data.get("profile_actions", {})
        is_highlight = data.get("is_highlight")

        if not isinstance(media_ids, list) or not media_ids:
            return jsonify({"ok": False, "error": "media_ids must be a non-empty list"}), 400

        if not isinstance(profile_actions, dict) and is_highlight is None:
            return jsonify({"ok": False, "error": "profile_actions or is_highlight must be provided"}), 400

        logger.info("Batch permissions update requested: %d cards, actions: %s", len(media_ids), profile_actions)
        has_physical = data.get("has_physical")
        result = database.batch_update_profile_media_permissions(
            media_ids=media_ids,
            profile_actions=profile_actions or {},
            is_highlight=is_highlight,
            has_physical=has_physical
        )
        logger.info("Batch permissions update succeeded: %s", result)
        return jsonify({"ok": True, **result})
    except Exception as e:
        logger.exception("Error during batch permissions update: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_curation_bp.route("/api/admin/curation/batch-highlight", methods=["POST"])
@require_admin
def admin_batch_highlight():
    """Atomically updates seasonal/pinned highlight status for multiple media items."""
    try:
        data = request.get_json(silent=True) or {}
        media_ids = data.get("media_ids", [])
        is_highlight = bool(data.get("is_highlight", False))

        if not isinstance(media_ids, list) or not media_ids:
            return jsonify({"ok": False, "error": "media_ids must be a non-empty list"}), 400

        count = database.batch_update_media_highlight(media_ids, is_highlight)
        return jsonify({"ok": True, "updated_count": count, "is_highlight": is_highlight})
    except Exception as e:
        logger.exception("Error during batch highlight update: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_curation_bp.route("/api/admin/curation/batch-physical", methods=["POST"])
@require_admin
def admin_batch_physical():
    """Atomically sets has_physical flag for multiple media items."""
    try:
        data = request.get_json(silent=True) or {}
        media_ids = data.get("media_ids", [])
        has_phys = bool(data.get("has_physical", False))
        if not isinstance(media_ids, list) or not media_ids:
            return jsonify({"ok": False, "error": "media_ids must be a non-empty list"}), 400
        count = database.batch_update_media_physical(media_ids, has_phys)
        return jsonify({"ok": True, "updated_count": count, "has_physical": has_phys})
    except Exception as e:
        logger.exception("Error during batch physical update: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_curation_bp.route("/api/admin/catalog/sync", methods=["POST"])
@require_admin
def admin_sync_upstream_catalogs():
    """Queries upstream Yoto and Audiobookshelf servers to refresh media_items cache."""
    from core.scheduler import perform_library_refresh
    count = perform_library_refresh()
    return jsonify({"ok": True, "count": count})


@admin_curation_bp.route("/api/admin/abs/item-tags", methods=["POST"])
@require_admin
def admin_update_abs_item_tags():
    """Updates the tags on an Audiobookshelf book and refreshes the local database cache."""
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    tags = data.get("tags", [])

    if not item_id or not isinstance(tags, list):
        return jsonify({"ok": False, "error": "Invalid item_id or tags list"}), 400

    if not clients.abs_client:
        return jsonify({"ok": False, "error": "Audiobookshelf client not configured"}), 503

    success = clients.abs_client.update_item_tags(item_id, tags)
    if not success:
        return jsonify({"ok": False, "error": "Failed to update tags in Audiobookshelf"}), 502

    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT raw_metadata FROM media_items WHERE id = ?;", (item_id,))
        row = cur.fetchone()
        raw_meta = {}
        if row and row["raw_metadata"]:
            try:
                raw_meta = json.loads(row["raw_metadata"])
            except Exception as e:
                logger.error("Corrupted raw_metadata for media item %s: %s", item_id, e)
                return jsonify({"ok": False, "error": f"Corrupted metadata in database for {item_id}"}), 500
        raw_meta["tags"] = tags
        with conn:
            conn.execute("UPDATE media_items SET raw_metadata = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (json.dumps(raw_meta), item_id))
    finally:
        conn.close()

    return jsonify({"ok": True, "tags": tags})
