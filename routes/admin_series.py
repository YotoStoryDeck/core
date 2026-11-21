"""
Admin Yoto card manual series and sequence overrides blueprint (DLP-021).
"""
import json
from flask import Blueprint, request, jsonify
import database
from core.auth import require_admin

admin_series_bp = Blueprint("admin_series", __name__)


@admin_series_bp.route("/api/admin/media/<media_id>/series", methods=["POST"])
@require_admin
def admin_set_media_series_override(media_id: str):
    """Assigns or clears a manual series and sequence override for a single Yoto card."""
    data = request.get_json(silent=True) or {}
    series = (data.get("series") or "").strip()
    series_order = data.get("series_order")
    if series_order is None:
        series_order = data.get("sequence", "")
    clean_order = str(series_order if series_order is not None else "").strip()

    try:
        result = database.set_media_series_override(media_id, series, clean_order)
        return jsonify({"ok": True, **result})
    except KeyError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@admin_series_bp.route("/api/admin/media/<media_id>/series", methods=["DELETE"])
@require_admin
def admin_delete_media_series_override(media_id: str):
    """Deletes a manual series override row so the card reverts to upstream automatic detection."""
    item = database.get_media_item_by_id(media_id)
    if not item:
        return jsonify({"ok": False, "error": f"Media item '{media_id}' not found."}), 404

    had_override = database.delete_media_series_override(media_id)
    raw_data = {}
    try:
        raw_data = json.loads(item.get("raw_metadata") or "{}")
    except Exception:
        raw_data = {}

    restored_series = raw_data.get("series") or ""
    restored_order = raw_data.get("series_order") or ""
    if not restored_series and isinstance(raw_data.get("series_list"), list) and raw_data["series_list"]:
        first_s = raw_data["series_list"][0] or {}
        restored_series = first_s.get("name") or ""
        restored_order = first_s.get("order") or ""

    return jsonify({
        "ok": True,
        "media_id": media_id,
        "reverted": True,
        "had_override": had_override,
        "series": restored_series,
        "series_order": restored_order,
        "is_series_overridden": False
    })


@admin_series_bp.route("/api/admin/media/batch-series", methods=["POST"])
@require_admin
def admin_batch_set_media_series_overrides():
    """Atomically assigns a shared series and ordered sequences to multiple selected Yoto cards."""
    data = request.get_json(silent=True) or {}
    series = (data.get("series") or "").strip()
    items = data.get("items")
    if items is None and isinstance(data.get("media_ids"), list):
        items = [
            {"id": mid, "sequence": str(idx)}
            for idx, mid in enumerate(data["media_ids"], start=1)
        ]

    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"ok": False, "error": "A non-empty items list is required."}), 400

    try:
        result = database.batch_set_media_series_overrides(series, items)
        return jsonify({"ok": True, **result})
    except KeyError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
