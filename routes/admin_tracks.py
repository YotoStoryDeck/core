"""
Admin tracklist browser, batch renamer, and 16x16 chapter artwork studio blueprint.
"""
import re
import json
import time
import base64
from typing import Dict
import requests
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import CUSTOM_ICONS_DIR, logger
from core.auth import require_admin
from core.media_utils import (
    get_media_tracks_data,
    parse_track_names,
    extract_chapter_number,
    render_16x16_icon_with_overlay,
)

admin_tracks_bp = Blueprint("admin_tracks", __name__)


@admin_tracks_bp.route("/api/admin/media/<media_id>/tracks", methods=["GET"])
@require_admin
def admin_get_media_tracks(media_id: str):
    """Returns chapter/track breakdown for any media item (ABS, Yoto Retail, or MYO)."""
    try:
        data = get_media_tracks_data(media_id)
        return jsonify(data)
    except Exception as e:
        logger.exception("Error getting tracks for %s: %s", media_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_tracks_bp.route("/api/admin/icons/search", methods=["GET"])
@require_admin
def admin_search_icons():
    """Multi-tier community icon search across YotoIcons and Tinker."""
    query = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 24))
    if not query:
        return jsonify({"ok": True, "results": []})

    try:
        from icon_engine import IconEngine
        engine = IconEngine(clients.yoto_client, clients.abs_client, clients.ai_service, database)
        results = engine.search_all_sources(query, limit_per_source=limit)
        return jsonify({"ok": True, "query": query, "results": results})
    except Exception as e:
        logger.exception("Icon search error for '%s': %s", query, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_tracks_bp.route("/api/admin/media/<media_id>/auto-match-icons", methods=["POST"])
@require_admin
def admin_auto_match_icons(media_id: str):
    """1-Click Auto-Match Engine for ABS audiobooks and MYO playlists."""
    try:
        from icon_engine import IconEngine
        engine = IconEngine(clients.yoto_client, clients.abs_client, clients.ai_service, database)

        tracks_data = get_media_tracks_data(media_id)
        tracks = tracks_data.get("tracks", [])
        if not tracks:
            return jsonify({"ok": False, "error": "No tracks found to match"}), 404

        matched_count = 0
        assigned_tracks = []

        for tr in tracks:
            tr_title = tr.get("title", "")
            clean_q = re.sub(r"^(?:Chapter|Track|Part|Book)\s*\d+[:.\s-]*", "", tr_title, flags=re.IGNORECASE).strip()
            if not clean_q:
                clean_q = tr_title.strip()

            icons = engine.search_all_sources(clean_q, limit_per_source=3)
            if not icons and tr_title != clean_q:
                icons = engine.search_all_sources(tr_title, limit_per_source=3)

            if icons:
                best_icon = icons[0]
                matched_count += 1
                assigned_tracks.append({
                    "track_index": tr["index"],
                    "title": tr_title,
                    "icon_url": best_icon.get("url"),
                    "icon_name": best_icon.get("name")
                })

        return jsonify({
            "ok": True,
            "media_id": media_id,
            "total_tracks": len(tracks),
            "matched_count": matched_count,
            "assigned_tracks": assigned_tracks
        })
    except Exception as e:
        logger.exception("Auto-match icons error for %s: %s", media_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_tracks_bp.route("/api/admin/media/<media_id>/tracks", methods=["PUT"])
@require_admin
def admin_update_media_tracks(media_id: str):
    """Batch updates track / chapter names on Audiobookshelf audiobooks or Yoto MYO playlists."""
    data = request.get_json(silent=True) or {}
    raw_text = data.get("raw_text")
    track_names = data.get("track_names")

    if raw_text and not track_names:
        track_names = parse_track_names(raw_text)

    if not track_names or not isinstance(track_names, list):
        return jsonify({"ok": False, "error": "No track names provided. Supply track_names array or raw_text."}), 400

    media_type = data.get("type", "abs")
    if media_type == "yoto":
        return jsonify({"ok": False, "error": "Official Yoto retail card tracklists are fixed upstream and cannot be edited."}), 400

    if media_type == "yoto_myo":
        if not clients.yoto_client:
            return jsonify({"ok": False, "error": "Yoto client not configured."}), 503

        card = clients.yoto_client.get_card_detail(media_id)
        if not card:
            return jsonify({"ok": False, "error": f"MYO card '{media_id}' not found."}), 404

        content = card.get("content") or {}
        existing_chapters = content.get("chapters") or card.get("chapters") or []
        if not existing_chapters:
            return jsonify({"ok": False, "error": "MYO card has no existing chapters to rename."}), 400

        updated_chapters = []
        for idx, ch in enumerate(existing_chapters):
            ch_copy = dict(ch)
            if idx < len(track_names):
                new_title = track_names[idx].strip()
                if new_title:
                    ch_copy["title"] = new_title
                    inner_tracks = ch_copy.get("tracks")
                    if isinstance(inner_tracks, list) and inner_tracks:
                        t_copy = dict(inner_tracks[0])
                        t_copy["title"] = new_title
                        ch_copy["tracks"] = [t_copy] + inner_tracks[1:]
            updated_chapters.append(ch_copy)

        success = clients.yoto_client.update_card_playlist(media_id, chapters=updated_chapters)
        if success:
            return jsonify({
                "ok": True,
                "message": f"Successfully updated {min(len(track_names), len(existing_chapters))} track title(s) on Yoto MYO card.",
                "total_chapters": len(updated_chapters),
                "updated_count": min(len(track_names), len(existing_chapters)),
                "chapters": updated_chapters
            })
        return jsonify({"ok": False, "error": "Failed to update playlist on Yoto Cloud."}), 500

    if not clients.abs_client:
        return jsonify({"ok": False, "error": "Audiobookshelf client not configured."}), 503

    item = clients.abs_client.get_item(media_id)
    if not item:
        return jsonify({"ok": False, "error": f"Item '{media_id}' not found in Audiobookshelf."}), 404

    media = item.get("media", {})
    existing_chapters = media.get("chapters", [])
    if not existing_chapters:
        return jsonify({"ok": False, "error": "Item has no existing chapter timestamps in Audiobookshelf to rename."}), 400

    updated_chapters = []
    for idx, ch in enumerate(existing_chapters):
        ch_copy = dict(ch)
        if idx < len(track_names):
            new_title = track_names[idx].strip()
            if new_title:
                ch_copy["title"] = new_title
        updated_chapters.append(ch_copy)

    success = clients.abs_client.update_item_chapters(media_id, updated_chapters)
    if success:
        return jsonify({
            "ok": True,
            "message": f"Successfully updated {min(len(track_names), len(existing_chapters))} chapter title(s) in Audiobookshelf.",
            "total_chapters": len(updated_chapters),
            "updated_count": min(len(track_names), len(existing_chapters)),
            "chapters": updated_chapters
        })
    return jsonify({"ok": False, "error": "Failed to update chapters in Audiobookshelf. Check server permissions."}), 500


@admin_tracks_bp.route("/api/admin/media/<media_id>/tracks/<int:track_idx>/icon", methods=["POST"])
@admin_tracks_bp.route("/api/admin/media/<media_id>/tracks/batch-icon", methods=["POST"])
@require_admin
def admin_update_track_icon(media_id: str, track_idx: int = -1):
    """Assigns artwork (uploaded file, base64, or URL) to one or multiple tracks with optional chapter number overlay."""
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        data = request.form.to_dict()
        file = request.files.get("file")
        raw_image_bytes = file.read() if file else None
    else:
        data = request.get_json(silent=True) or {}
        raw_image_bytes = None

    media_type = data.get("type", "abs")
    if media_type == "yoto":
        return jsonify({"ok": False, "error": "Cannot change artwork on retail Yoto cards."}), 400

    track_indices = data.get("track_indices")
    if isinstance(track_indices, str):
        try:
            track_indices = json.loads(track_indices)
        except Exception:
            track_indices = [int(i.strip()) for i in track_indices.split(",") if i.strip().isdigit()]
    if not track_indices:
        if track_idx >= 0:
            track_indices = [track_idx]
        else:
            return jsonify({"ok": False, "error": "No track indices provided."}), 400

    apply_overlay = str(data.get("apply_overlay", "false")).lower() in ("true", "1", "yes")
    overlay_corner = data.get("overlay_corner", "top-right")

    if not raw_image_bytes:
        img_b64 = data.get("image_b64") or data.get("png_b64")
        if img_b64:
            raw_image_bytes = base64.b64decode(img_b64.split(",")[-1])
        else:
            icon_url = data.get("icon_url", "").strip()
            if icon_url:
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
                    }
                    res = requests.get(icon_url, headers=headers, timeout=12)
                    if res.status_code == 200:
                        raw_image_bytes = res.content
                    else:
                        return jsonify({"ok": False, "error": f"Failed to download icon from {icon_url} ({res.status_code})"}), 400
                except Exception as e:
                    logger.error("Download icon failed: %s", e)
                    return jsonify({"ok": False, "error": f"Failed to fetch image: {e}"}), 400

    if not raw_image_bytes:
        return jsonify({"ok": False, "error": "No valid image provided (file, image_b64, or icon_url)."}), 400

    from core.image_resizer import invalidate_thumbnail

    if media_type == "yoto_myo":
        if not clients.yoto_client:
            return jsonify({"ok": False, "error": "Yoto client not configured."}), 503

        card = clients.yoto_client.get_card_detail(media_id)
        if not card:
            return jsonify({"ok": False, "error": f"MYO card '{media_id}' not found."}), 404

        content = card.get("content") or {}
        chapters = content.get("chapters") or card.get("chapters") or []
        if not chapters:
            return jsonify({"ok": False, "error": "MYO card has no chapters."}), 400

        updated_chapters = []
        uploaded_icon_cache: Dict[str, str] = {}

        for idx, ch in enumerate(chapters):
            ch_copy = dict(ch)
            if idx in track_indices:
                title = ch_copy.get("title", f"Track {idx + 1}")
                ch_num = extract_chapter_number(title, idx + 1) if apply_overlay else None
                cache_key = f"num_{ch_num}" if apply_overlay else "base"

                rendered_png = None
                if cache_key in uploaded_icon_cache:
                    icon_ref = uploaded_icon_cache[cache_key]
                else:
                    rendered_png = render_16x16_icon_with_overlay(raw_image_bytes, ch_num, overlay_corner)
                    icon_ref = clients.yoto_client.upload_display_icon(rendered_png, filename=f"track_{idx+1}.png")
                    if icon_ref:
                        uploaded_icon_cache[cache_key] = icon_ref

                if icon_ref:
                    ch_copy["display"] = {"icon16x16": icon_ref}
                    inner_tracks = ch_copy.get("tracks")
                    if isinstance(inner_tracks, list) and inner_tracks:
                        t_copy = dict(inner_tracks[0])
                        t_copy["display"] = {"icon16x16": icon_ref}
                        ch_copy["tracks"] = [t_copy] + inner_tracks[1:]

                if rendered_png:
                    icon_path = CUSTOM_ICONS_DIR / f"{media_id}_{idx}.png"
                    icon_path.write_bytes(rendered_png)
                    invalidate_thumbnail(f"abs_ch_{media_id}_{idx}")

            updated_chapters.append(ch_copy)

        success = clients.yoto_client.update_card_playlist(media_id, chapters=updated_chapters)
        if success:
            updated_urls = {}
            for t_idx in track_indices:
                p = CUSTOM_ICONS_DIR / f"{media_id}_{t_idx}.png"
                v_tok = int(p.stat().st_mtime) if p.exists() else int(time.time())
                updated_urls[t_idx] = f"/api/thumb?type=abs_chapter&id={media_id}&chapter={t_idx}&size=100&v={v_tok}"
            return jsonify({
                "ok": True,
                "message": f"Successfully updated artwork for {len(track_indices)} track(s) on Yoto MYO card.",
                "updated_tracks": track_indices,
                "updated_urls": updated_urls,
                "apply_overlay": apply_overlay
            })
        return jsonify({"ok": False, "error": "Failed to update MYO playlist on Yoto Cloud."}), 500

    # Audiobookshelf items: persist rendered 16x16 PNGs locally in CUSTOM_ICONS_DIR
    item_data = clients.abs_client.get_item(media_id) if clients.abs_client else {}
    abs_chapters = (item_data.get("media", {}).get("chapters") or []) if item_data else []

    updated_urls = {}
    for t_idx in track_indices:
        title = abs_chapters[t_idx].get("title", f"Chapter {t_idx + 1}") if t_idx < len(abs_chapters) else f"Chapter {t_idx + 1}"
        ch_num = extract_chapter_number(title, t_idx + 1) if apply_overlay else None
        rendered_png = render_16x16_icon_with_overlay(raw_image_bytes, ch_num, overlay_corner)

        icon_path = CUSTOM_ICONS_DIR / f"{media_id}_{t_idx}.png"
        icon_path.write_bytes(rendered_png)
        invalidate_thumbnail(f"abs_ch_{media_id}_{t_idx}")

        v_tok = int(icon_path.stat().st_mtime) if icon_path.exists() else int(time.time())
        updated_urls[t_idx] = f"/api/thumb?type=abs_chapter&id={media_id}&chapter={t_idx}&size=100&v={v_tok}"

    return jsonify({
        "ok": True,
        "message": f"Successfully updated artwork for {len(track_indices)} ABS chapter(s).",
        "updated_tracks": track_indices,
        "updated_urls": updated_urls,
        "apply_overlay": apply_overlay
    })
