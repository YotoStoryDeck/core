"""
Admin media catalog, curation rules, highlights, and permissions blueprint.
"""

from typing import Dict, Any, List, Optional, Tuple
import re
import json
import time
import requests
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import logger
from core.auth import require_admin

admin_curation_bp = Blueprint("admin_curation", __name__)


def load_full_config() -> Dict[str, Any]:
    """Loads full config representation from SQLite database."""
    return {
        "shared_yoto": database.get_shared_rules(),
        "profiles": database.get_all_profiles(),
        "settings": database.get_system_settings()
    }


def save_full_config(config_data: Dict[str, Any]) -> bool:
    """Saves updated config_data back into SQLite tables."""
    try:
        if "shared_yoto" in config_data:
            sh = config_data["shared_yoto"]
            database.set_shared_rule("include_all", sh.get("include_all", False))
            database.set_shared_rule("include_myo_by_default", sh.get("include_myo_by_default", True))
        if "profiles" in config_data:
            for pid, pcfg in config_data["profiles"].items():
                database.upsert_profile(pid, pcfg)
        if "settings" in config_data:
            for sk, sv in config_data["settings"].items():
                database.set_system_setting(sk, sv)
        return True
    except Exception as e:
        logger.error("Failed to save full config to SQLite: %s", e)
        return False


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
    """
    Atomically updates permissions across multiple media items and profiles.
    Body: {
      "media_ids": ["id1", "id2"],
      "profile_actions": { "jackson": "allow", "wesley": "exclude" },
      "is_highlight": null | true | false
    }
    """
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
        result = database.batch_update_profile_media_permissions(
            media_ids=media_ids,
            profile_actions=profile_actions or {},
            is_highlight=is_highlight
        )
        logger.info("Batch permissions update succeeded: %s", result)
        return jsonify({"ok": True, **result})
    except Exception as e:
        logger.exception("Error during batch permissions update: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_curation_bp.route("/api/admin/curation/batch-highlight", methods=["POST"])
@require_admin
def admin_batch_highlight():
    """
    Atomically updates seasonal/pinned highlight status for multiple media items.
    Body: { "media_ids": ["id1", "id2"], "is_highlight": true | false }
    """
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


def parse_single_series(name_str: str, default_order: str = ""):
    """Extracts series title and sequence/order (handling #12, #13-15, Book 1-4)."""
    import re
    name_str = (name_str or "").strip()
    order_str = str(default_order or "").strip()
    if not name_str:
        return None

    # Check for trailing #sequence (e.g. #55, #13-15)
    m_seq = re.search(r'\s*#\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', name_str)
    if m_seq:
        if not order_str:
            order_str = m_seq.group(1).replace(" ", "")
        name_str = name_str[:m_seq.start()].strip()
    else:
        # Check for trailing Book/Volume sequence
        m_book = re.search(r'[,:\s]+(?:Books?|Volumes?|Vol\.?|Parts?)\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', name_str, re.IGNORECASE)
        if m_book:
            if not order_str:
                order_str = m_book.group(1).replace(" ", "")
            name_str = name_str[:m_book.start()].strip()

    return {"name": name_str, "order": order_str} if name_str else None


def extract_series_list(raw_series: Any, raw_series_order: str = "", title: str = "", known_series: list = None) -> list:
    """Normalizes raw series into a list of {name, order} dicts, with title and known series fallback deduction."""
    import re
    series_list = []
    if isinstance(raw_series, list):
        for s_entry in raw_series:
            if isinstance(s_entry, dict):
                parsed = parse_single_series(s_entry.get("name"), s_entry.get("sequence") or raw_series_order)
            else:
                parsed = parse_single_series(str(s_entry), raw_series_order)
            if parsed:
                series_list.append(parsed)
    elif isinstance(raw_series, dict):
        parsed = parse_single_series(raw_series.get("name"), raw_series.get("sequence") or raw_series_order)
        if parsed:
            series_list.append(parsed)
    elif isinstance(raw_series, str) and raw_series.strip():
        # Handle comma-delimited series list with or without numbers
        raw_parts = [p.strip() for p in raw_series.split(",") if p.strip()]
        if len(raw_parts) > 1:
            for p in raw_parts:
                parsed = parse_single_series(p, raw_series_order if len(raw_parts) == 1 else "")
                if parsed:
                    series_list.append(parsed)
        else:
            parsed = parse_single_series(raw_series, raw_series_order)
            if parsed:
                series_list.append(parsed)

    # Sequence / order detection from title if missing
    clean_title = (title or "").strip()
    detected_order = str(raw_series_order or "").strip()
    if not detected_order and clean_title:
        m_range = re.search(r"#\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)", clean_title, re.IGNORECASE)
        if m_range:
            detected_order = re.sub(r"\s+", "", m_range.group(1) or m_range.group(2))
        else:
            m_num = re.search(r"#\s*(\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)", clean_title, re.IGNORECASE)
            if m_num:
                val = m_num.group(1) or m_num.group(2)
                detected_order = str(val).strip()

    # 1. Match against known cross-platform series (e.g. 'The Boxcar Children')
    if known_series and clean_title:
        for ks in known_series:
            ks_str = (ks or "").strip()
            if not ks_str:
                continue
            pat = r"^" + re.escape(ks_str) + r"(?:\s*Collection)?(?:[\s,:–—\-]|$)"
            if re.search(pat, clean_title, re.IGNORECASE):
                if not any(s["name"].lower() == ks_str.lower() for s in series_list):
                    series_list.append({"name": ks_str, "order": detected_order})

    # 2. Sub-title prefix deduction (e.g. 'The Boxcar Children: Mystery Ranch' -> 'The Boxcar Children')
    if not series_list and clean_title:
        for sep in [" - ", ": "]:
            if sep in clean_title:
                cand = clean_title.split(sep)[0].strip()
                if cand and len(cand) >= 3:
                    parsed_cand = parse_single_series(cand, detected_order)
                    if parsed_cand:
                        series_list.append(parsed_cand)
                break

    return series_list


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

    # Refresh raw_metadata in local database
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT raw_metadata FROM media_items WHERE id = ?;", (item_id,))
        row = cur.fetchone()
        raw_meta = {}
        if row and row["raw_metadata"]:
            try:
                raw_meta = json.loads(row["raw_metadata"])
            except Exception:
                pass
        raw_meta["tags"] = tags
        with conn:
            conn.execute("UPDATE media_items SET raw_metadata = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (json.dumps(raw_meta), item_id))
    finally:
        conn.close()

    return jsonify({"ok": True, "tags": tags})


@admin_curation_bp.route("/api/admin/yoto/cards", methods=["GET", "PUT"])
def admin_yoto_cards():
    """Legacy backward-compatible endpoint for curation."""
    full_cfg = load_full_config()
    profiles = full_cfg.get("profiles", {})
    shared_cfg = full_cfg.get("shared_yoto", {})

    if request.method == "GET":
        raw_cards = clients.yoto_client.get_raw_library() if clients.yoto_client else []
        card_list = []
        for c in raw_cards:
            cid = c.get("cardId") or c.get("id")
            title = c.get("title") or "Yoto Playlist"
            is_myo = c.get("isMyo", False)

            card_info = {
                "id": cid,
                "title": title,
                "author": c.get("author") or "Yoto",
                "is_myo": is_myo,
                "cover_url": c.get("coverImageUrl") or c.get("iconUrl") or "",
                "in_shared": cid in shared_cfg.get("allowed_card_ids", []),
                "profiles": {}
            }

            for p_key, p_val in profiles.items():
                p_yoto = p_val.get("yoto", {})
                card_info["profiles"][p_key] = {
                    "allowed": cid in p_yoto.get("allowed_card_ids", []),
                    "excluded": cid in p_yoto.get("excluded_card_ids", [])
                }
            card_list.append(card_info)

        return jsonify({
            "cards": card_list,
            "shared_yoto": shared_cfg,
            "profiles": list(profiles.keys())
        })

    elif request.method == "PUT":
        data = request.get_json(silent=True) or {}
        if "shared_yoto" in data:
            full_cfg["shared_yoto"] = data["shared_yoto"]

        if "profiles" in data and isinstance(data["profiles"], dict):
            for p_key, p_updates in data["profiles"].items():
                if p_key in full_cfg.get("profiles", {}):
                    if "yoto" in p_updates:
                        full_cfg["profiles"][p_key]["yoto"] = p_updates["yoto"]

        if save_full_config(full_cfg):
            return jsonify({"status": "ok", "message": "Curation configuration saved."})
        return jsonify({"status": "error", "message": "Failed to save config."}), 500


# ============================================================================
# Tracklist Browser & Chapter Artwork Studio (Feature 012)
# ============================================================================

def get_media_tracks_data(media_id: str) -> dict:
    """
    Returns chapter/track breakdown dict for any media item (ABS, Yoto Retail, or MYO).
    For ABS: returns chapters from Audiobookshelf with icon URLs.
    For Yoto Retail: returns read-only official tracklist and official Yoto 16x16 icons.
    For MYO: returns tracklist with editable icon status.
    """
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, type, title, author, cover_url, raw_metadata FROM media_items WHERE id = ?;", (media_id,))
    item_row = cur.fetchone()
    conn.close()

    media_type = item_row["type"] if item_row else "abs"
    title = item_row["title"] if item_row else "Unknown"
    author = item_row["author"] if item_row else ""
    cover_url = item_row["cover_url"] if item_row else ""

    tracks = []
    can_edit = False

    if media_type == "abs":
        can_edit = True
        if clients.abs_client:
            abs_data = clients.abs_client.get_item(media_id)
            if abs_data:
                media_obj = abs_data.get("media", {})
                chapters = media_obj.get("chapters", [])
                title = abs_data.get("media", {}).get("metadata", {}).get("title") or title
                author = abs_data.get("media", {}).get("metadata", {}).get("authorName") or author

                from core.config import CUSTOM_ICONS_DIR
                for idx, ch in enumerate(chapters):
                    ch_start = float(ch.get("start", 0))
                    ch_end = float(ch.get("end", 0))
                    dur = max(0, int(ch_end - ch_start))
                    dur_str = f"{dur // 60}:{dur % 60:02d}" if dur > 0 else ""

                    custom_file = CUSTOM_ICONS_DIR / f"{media_id}_{idx}.png"
                    if custom_file.exists():
                        v_param = f"&v={int(custom_file.stat().st_mtime)}"
                        has_custom = True
                    else:
                        v_param = ""
                        has_custom = False

                    tracks.append({
                        "index": idx,
                        "track_number": idx + 1,
                        "title": ch.get("title") or f"Chapter {idx + 1}",
                        "duration_seconds": dur,
                        "duration_formatted": dur_str,
                        "icon_url": f"/api/thumb?type=abs_chapter&id={media_id}&chapter={idx}&size=100{v_param}",
                        "has_custom_icon": has_custom
                    })

    elif media_type in ("yoto", "yoto_myo"):
        can_edit = (media_type == "yoto_myo")
        card_detail = None
        if clients.yoto_client:
            card_detail = clients.yoto_client.get_card_detail(media_id)

        if card_detail:
            c = card_detail.get("card") or card_detail
            meta = c.get("metadata") or {}
            content = c.get("content") or {}
            raw_chaps = content.get("chapters") or c.get("chapters") or []
            title = c.get("title") or title
            author = meta.get("author") or author

            from core.config import CUSTOM_ICONS_DIR
            for idx, ch in enumerate(raw_chaps):
                dur = int(ch.get("duration", 0))
                dur_str = f"{dur // 60}:{dur % 60:02d}" if dur > 0 else ""
                disp = ch.get("display") or {}
                ch_icon = disp.get("icon16x16") or ch.get("iconUrl") or ch.get("icon") or ""
                
                custom_file = CUSTOM_ICONS_DIR / f"{media_id}_{idx}.png"
                if custom_file.exists():
                    icon_display_url = f"/api/thumb?type=abs_chapter&id={media_id}&chapter={idx}&size=100&v={int(custom_file.stat().st_mtime)}"
                    has_custom = True
                elif ch_icon.startswith("yoto:#"):
                    icon_display_url = f"/api/thumb?type=yoto_icon&ref={ch_icon.replace('yoto:#', '')}&fallback_id={media_id}"
                    has_custom = True
                else:
                    icon_display_url = ch_icon or cover_url
                    has_custom = bool(ch_icon)

                ch_key = ch.get("key") or f"{idx + 1:02d}"
                ch_trks = ch.get("tracks") or []
                trk_key = (ch_trks[0].get("key") if ch_trks and isinstance(ch_trks[0], dict) else None) or ch_key
                tracks.append({
                    "index": idx,
                    "track_number": idx + 1,
                    "key": ch_key,
                    "track_key": trk_key,
                    "title": ch.get("title") or f"Track {idx + 1}",
                    "duration_seconds": dur,
                    "duration_formatted": dur_str,
                    "icon_url": icon_display_url,
                    "has_custom_icon": has_custom
                })

    # Fallback if no tracks were extracted
    if not tracks:
        tracks.append({
            "index": 0,
            "track_number": 1,
            "title": title,
            "duration_seconds": 0,
            "duration_formatted": "--:--",
            "icon_url": cover_url,
            "has_custom_icon": bool(cover_url)
        })

    return {
        "ok": True,
        "id": media_id,
        "type": media_type,
        "title": title,
        "author": author,
        "cover_url": cover_url,
        "can_edit": can_edit,
        "tracks": tracks
    }


@admin_curation_bp.route("/api/admin/media/<media_id>/tracks", methods=["GET"])
@require_admin
def admin_get_media_tracks(media_id: str):
    """
    Returns chapter/track breakdown for any media item (ABS, Yoto Retail, or MYO).
    """
    try:
        data = get_media_tracks_data(media_id)
        return jsonify(data)
    except Exception as e:
        logger.exception("Error getting tracks for %s: %s", media_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500



@admin_curation_bp.route("/api/admin/icons/search", methods=["GET"])
@require_admin
def admin_search_icons():
    """
    Multi-tier community icon search across YotoIcons and Tinker.
    Query params:
      - q: search keyword (e.g. 'dragon', 'train', 'magic')
      - limit: max results (default: 24)
    """
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


@admin_curation_bp.route("/api/admin/media/<media_id>/auto-match-icons", methods=["POST"])
@require_admin
def admin_auto_match_icons(media_id: str):
    """
    1-Click Auto-Match Engine for ABS audiobooks and MYO playlists.
    Evaluates each chapter's title against community icons and assigns best match.
    """
    try:
        from icon_engine import IconEngine
        engine = IconEngine(clients.yoto_client, clients.abs_client, clients.ai_service, database)

        # 1. Fetch tracks for the media item
        tracks_res = admin_get_media_tracks(media_id)
        tracks_data = tracks_res.get_json() or {}
        tracks = tracks_data.get("tracks", [])

        if not tracks:
            return jsonify({"ok": False, "error": "No tracks found to match"}), 404

        matched_count = 0
        assigned_tracks = []

        for tr in tracks:
            tr_title = tr.get("title", "")
            # Clean title (e.g. "Chapter 1: The Boy Who Lived" -> "boy lived")
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


def parse_track_names(raw_input: str) -> List[str]:
    """
    Parses flexible track name inputs:
    - Bullet list:
      • Chapter 1: To the Castle!
      - Chapter 2: The Dragon Stone
      * Chapter 3: More Dragons!
    - Newline-delimited lines (with optional numbers/bullets)
    - Comma-delimited list: "Chapter 1: To the Castle!, Chapter 2: The Dragon Stone"
    Strips leading bullet characters (•, -, *, •, ·) while preserving chapter titles.
    """
    if not raw_input or not isinstance(raw_input, str):
        return []

    lines = [ln.strip() for ln in raw_input.strip().splitlines() if ln.strip()]

    # If it's a single line and contains commas, parse as comma-delimited
    if len(lines) == 1 and "," in lines[0] and not lines[0].startswith(("•", "-", "*")):
        raw_items = [item.strip() for item in lines[0].split(",") if item.strip()]
    else:
        raw_items = lines

    cleaned: List[str] = []
    for item in raw_items:
        # Strip leading bullet points or markers (e.g. •, -, *, ·)
        t = re.sub(r"^[\s•\-*·]+\s*", "", item).strip()
        if t:
            cleaned.append(t)
    return cleaned


@admin_curation_bp.route("/api/admin/media/<media_id>/tracks", methods=["PUT"])
@require_admin
def admin_update_media_tracks(media_id: str):
    """
    Batch updates track / chapter names on Audiobookshelf audiobooks.
    Accepts:
      {
        "track_names": ["Chapter 1: ...", "Chapter 2: ..."]  // OR
        "raw_text": "• Chapter 1: ...\n• Chapter 2: ..."
      }
    """
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
                    # Also update any inner track title
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
        else:
            return jsonify({"ok": False, "error": "Failed to update playlist on Yoto Cloud/Bridge."}), 500

    if not clients.abs_client:
        return jsonify({"ok": False, "error": "Audiobookshelf client not configured."}), 503

    item = clients.abs_client.get_item(media_id)
    if not item:
        return jsonify({"ok": False, "error": f"Item '{media_id}' not found in Audiobookshelf."}), 404

    media = item.get("media", {})
    existing_chapters = media.get("chapters", [])
    if not existing_chapters:
        return jsonify({"ok": False, "error": "Item has no existing chapter timestamps in Audiobookshelf to rename."}), 400

    # Build updated chapters preserving exact start, end, and id timestamps
    updated_chapters = []
    for idx, ch in enumerate(existing_chapters):
        ch_copy = dict(ch)
        if idx < len(track_names):
            new_title = track_names[idx].strip()
            if new_title:
                ch_copy["title"] = new_title
        updated_chapters.append(ch_copy)

    # Persist to Audiobookshelf
    success = clients.abs_client.update_item_chapters(media_id, updated_chapters)
    if success:
        return jsonify({
            "ok": True,
            "message": f"Successfully updated {min(len(track_names), len(existing_chapters))} chapter title(s) in Audiobookshelf.",
            "total_chapters": len(updated_chapters),
            "updated_count": min(len(track_names), len(existing_chapters)),
            "chapters": updated_chapters
        })
    else:
        return jsonify({"ok": False, "error": "Failed to update chapters in Audiobookshelf. Check server permissions."}), 500


# 3x4 pixel digits for corner numbers (matches Yoto pixel displays)
TINY_DIGITS = {
    "0": ["###", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#."],
    "2": ["##.", "..#", ".#.", "###"],
    "3": ["###", ".##", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#"],
    "5": ["###", "##.", "..#", "##."],
    "6": ["#..", "###", "#.#", "###"],
    "7": ["###", "..#", ".#.", ".#."],
    "8": ["###", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#"],
}

def extract_chapter_number(title: str, fallback_num: int = 1) -> int:
    """
    Extracts chapter number from title looking for 'Chapter 1', 'Ch. 2', 'Chap 3', 'Part 4',
    or leading digits ('01. Intro'). If no number is detected, defaults to fallback_num.
    """
    if not title:
        return fallback_num
    # 1. Explicit Chapter abbreviations
    m = re.search(r'\b(?:chapter|chap|ch|c)\.?\s*#?\s*(\d+)\b', title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 2. Part / Section / Track
    m = re.search(r'\b(?:part|pt|section|sec|track)\.?\s*#?\s*(\d+)\b', title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 3. Leading numbers like '01 - ' or '1. '
    m = re.search(r'^\s*#?\s*(\d+)\s*[:.\-]', title)
    if m:
        return int(m.group(1))
    return fallback_num


def render_16x16_icon_with_overlay(raw_bytes: bytes, number: Optional[int] = None, corner: str = "top-right") -> bytes:
    """
    Center-crops raw image bytes to a square, resizes to 16x16, and optionally overlays
    a 3x4 pixel chapter/track number in the specified corner.
    """
    import io
    from PIL import Image

    img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    w, h = img.size
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = (h - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))
    img = img.resize((16, 16), Image.Resampling.LANCZOS)

    if number is not None:
        text = str(max(0, number))[-3:]
        w_text = len(text) * 4 - 1
        x0 = (16 - w_text) if "right" in corner else 0
        y0 = (16 - 4) if "bottom" in corner else 0

        # Contrast check against background pixels
        total_luma = 0.0
        count = 0
        for y in range(y0, min(16, y0 + 4)):
            for x in range(x0, min(16, x0 + w_text)):
                r, g, b, a = img.getpixel((x, y))
                total_luma += 0.299 * r + 0.587 * g + 0.114 * b
                count += 1
        avg_luma = total_luma / max(1, count)
        ink = (35, 35, 40, 255) if avg_luma > 140 else (240, 240, 245, 255)

        for n, ch in enumerate(text):
            if ch not in TINY_DIGITS:
                continue
            for cy, row in enumerate(TINY_DIGITS[ch]):
                for cx, c in enumerate(row):
                    if c == "#":
                        px_x = x0 + n * 4 + cx
                        px_y = y0 + cy
                        if 0 <= px_x < 16 and 0 <= px_y < 16:
                            curr = img.getpixel((px_x, px_y))
                            tinted = (
                                int(curr[0] * 0.25 + ink[0] * 0.75),
                                int(curr[1] * 0.25 + ink[1] * 0.75),
                                int(curr[2] * 0.25 + ink[2] * 0.75),
                                255
                            )
                            img.putpixel((px_x, px_y), tinted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@admin_curation_bp.route("/api/admin/media/<media_id>/tracks/<int:track_idx>/icon", methods=["POST"])
@admin_curation_bp.route("/api/admin/media/<media_id>/tracks/batch-icon", methods=["POST"])
@require_admin
def admin_update_track_icon(media_id: str, track_idx: int = -1):
    """
    Assigns artwork (custom uploaded file, URL, or community icon) to one or multiple tracks.
    Optionally applies a track/chapter number corner overlay.
    Accepts JSON or multipart/form-data:
      - type: 'yoto_myo' | 'abs'
      - track_indices: [0, 1, 2] (or single track_idx from URL)
      - icon_url: URL to icon image (optional if file uploaded or b64 provided)
      - image_b64: base64-encoded image (optional)
      - file: uploaded image file (optional multipart)
      - apply_overlay: bool (if true, burns chapter number into corner)
      - overlay_corner: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left'
    """
    import base64
    from core.config import CUSTOM_ICONS_DIR

    # 1. Parse incoming parameters
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

    # Determine targeted track indices
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

    # 2. Acquire source image bytes
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

    # 3. Handle Yoto MYO Cards
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

        # Upload icon(s) to Yoto Cloud and update chapters
        updated_chapters = []
        uploaded_icon_cache: Dict[str, str] = {}  # key -> icon_ref

        for idx, ch in enumerate(chapters):
            ch_copy = dict(ch)
            if idx in track_indices:
                title = ch_copy.get("title", f"Track {idx + 1}")
                ch_num = extract_chapter_number(title, idx + 1) if apply_overlay else None
                cache_key = f"num_{ch_num}" if apply_overlay else "base"

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

                # Also save the rendered PNG locally for instant admin UI preview & fallback
                if rendered_png:
                    icon_path = CUSTOM_ICONS_DIR / f"{media_id}_{idx}.png"
                    icon_path.write_bytes(rendered_png)
                    from core.image_resizer import invalidate_thumbnail
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
        else:
            return jsonify({"ok": False, "error": "Failed to update MYO playlist on Yoto Cloud/Bridge."}), 500

    # 4. Handle Audiobookshelf Items
    # For ABS, save 16x16 icon to CUSTOM_ICONS_DIR and sync to bridge item cache
    item_data = clients.abs_client.get_item(media_id) if clients.abs_client else {}
    abs_chapters = (item_data.get("media", {}).get("chapters") or []) if item_data else []

    import base64
    updated_urls = {}
    batch_bridge_tracks = {}

    for t_idx in track_indices:
        title = abs_chapters[t_idx].get("title", f"Chapter {t_idx + 1}") if t_idx < len(abs_chapters) else f"Chapter {t_idx + 1}"
        ch_num = extract_chapter_number(title, t_idx + 1) if apply_overlay else None
        rendered_png = render_16x16_icon_with_overlay(raw_image_bytes, ch_num, overlay_corner)

        # Save to persistent storage locally in broker
        icon_path = CUSTOM_ICONS_DIR / f"{media_id}_{t_idx}.png"
        icon_path.write_bytes(rendered_png)

        # Collect for Bridge item-level cache push (1-indexed track number)
        batch_bridge_tracks[str(t_idx + 1)] = base64.b64encode(rendered_png).decode("ascii")

        # Evict any existing cached thumbnail for this chapter
        from core.image_resizer import invalidate_thumbnail
        invalidate_thumbnail(f"abs_ch_{media_id}_{t_idx}")

        v_tok = int(icon_path.stat().st_mtime) if icon_path.exists() else int(time.time())
        updated_urls[t_idx] = f"/api/thumb?type=abs_chapter&id={media_id}&chapter={t_idx}&size=100&v={v_tok}"

    # Push to Bridge item cache so physical Yoto player and Bridge phone UI inherit it immediately
    if clients.yoto_client and batch_bridge_tracks:
        try:
            clients.yoto_client.push_item_chapter_icons_batch(media_id, batch_bridge_tracks)
        except Exception as e:
            logger.warning("Failed to sync item chapter icons batch to Bridge: %s", e)

    return jsonify({
        "ok": True,
        "message": f"Successfully updated artwork for {len(track_indices)} ABS chapter(s).",
        "updated_tracks": track_indices,
        "updated_urls": updated_urls,
        "apply_overlay": apply_overlay
    })


@admin_curation_bp.route("/api/admin/media/<media_id>/sync-bridge-icons", methods=["POST"])
@require_admin
def admin_sync_bridge_icons(media_id: str):
    """
    Scans local custom icons in CUSTOM_ICONS_DIR for media_id and batch-pushes
    them to the Yoto Bridge item-level cache.
    """
    from core.config import CUSTOM_ICONS_DIR
    import base64

    if not clients.yoto_client:
        return jsonify({"ok": False, "error": "Yoto client not initialized."}), 503

    # Find all local icon files matching {media_id}_<index>.png
    batch_bridge_tracks = {}
    pattern = re.compile(rf"^{re.escape(media_id)}_(\d+)\.png$")

    for f in CUSTOM_ICONS_DIR.iterdir():
        if f.is_file():
            m = pattern.match(f.name)
            if m:
                t_idx = int(m.group(1))
                # Bridge uses 1-indexed track/chapter numbers
                ch_num = str(t_idx + 1)
                try:
                    png_bytes = f.read_bytes()
                    batch_bridge_tracks[ch_num] = base64.b64encode(png_bytes).decode("ascii")
                except Exception as e:
                    logger.warning("Failed reading custom icon %s: %s", f.name, e)

    if not batch_bridge_tracks:
        return jsonify({
            "ok": False,
            "error": f"No custom icons found locally in {CUSTOM_ICONS_DIR} for media_id '{media_id}'."
        }), 404

    success = clients.yoto_client.push_item_chapter_icons_batch(media_id, batch_bridge_tracks)
    if success:
        return jsonify({
            "ok": True,
            "message": f"Successfully synced {len(batch_bridge_tracks)} custom icon(s) to Yoto Bridge item cache.",
            "media_id": media_id,
            "synced_tracks": sorted([int(k) for k in batch_bridge_tracks.keys()])
        })
    else:
        return jsonify({
            "ok": False,
            "error": "Failed to push icons to Bridge. Check Bridge connectivity and API key."
        }), 502






