"""Household Media Item Index, Matrix Curation Permissions & Playback History."""
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from .connection import get_db_connection, logger
from .profiles import get_all_profiles, get_shared_rules
from .settings import get_system_settings

def upsert_media_items(items: List[Dict[str, Any]]) -> int:
    """Caches discovered Yoto cards or ABS books into media_items table, invalidating cached thumbnails whenever an item's cover changes."""
    conn = get_db_connection()
    count = 0
    changed_covers = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, type, cover_url FROM media_items;")
        existing_covers = {r["id"]: (r["type"], r["cover_url"] or "") for r in cur.fetchall()}
        with conn:
            for it in items:
                m_id = it.get("id")
                m_type = it.get("type", "yoto")
                title = it.get("title", "")
                author = it.get("author", "")
                cover = it.get("cover_url", it.get("thumb", "")) or ""
                is_hi = 1 if it.get("is_highlight", False) else 0
                raw = json.dumps(it.get("raw_metadata") or it)
                if m_id in existing_covers:
                    old_type, old_cover = existing_covers[m_id]
                    if old_cover and old_cover != cover:
                        changed_covers.append((m_id, old_type, old_cover))
                conn.execute("""
                INSERT INTO media_items (id, type, title, author, cover_url, is_highlight, raw_metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    title = excluded.title,
                    author = excluded.author,
                    cover_url = excluded.cover_url,
                    raw_metadata = excluded.raw_metadata,
                    updated_at = CURRENT_TIMESTAMP;
                """, (m_id, m_type, title, author, cover, is_hi, raw))
                count += 1
        if changed_covers:
            try:
                from core.image_resizer import invalidate_thumbnail
                for cid, ctype, old_c in changed_covers:
                    invalidate_thumbnail(f"abs_{cid}")
                    if old_c:
                        invalidate_thumbnail(f"yoto_{old_c}")
                logger.info("Invalidated cached thumbnails for %d updated media covers.", len(changed_covers))
            except Exception as e:
                logger.warning("Failed invalidating changed cover thumbnails: %s", e)
        return count
    finally:
        conn.close()

def get_media_item_by_id(media_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single cached media item from SQLite by ID."""
    if not media_id:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, type, title, author, cover_url, is_highlight, raw_metadata FROM media_items WHERE id = ?;", (media_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_catalog_matrix() -> Dict[str, Any]:
    """Returns complete media catalog with highlight flags and per-profile permissions."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM media_items;")
        media_rows = cur.fetchall()
        # Sort with same methodology as Controller: highlight first, then title ignoring leading articles (A, An, The)
        def _matrix_sort_key(r):
            t = (r["title"] or "").strip()
            clean_t = re.sub(r"^(the|a|an)\s+", "", t, flags=re.IGNORECASE).lower()
            return (not bool(r["is_highlight"]), clean_t)
        media_rows = sorted(media_rows, key=_matrix_sort_key)
        profiles = get_all_profiles()
        shared_rules = get_shared_rules()
        settings = get_system_settings()
        default_child_tags = [t.lower() for t in settings.get("abs_default_children_tags", ["Children"])]
        items = []
        for mr in media_rows:
            m_id = mr["id"]
            m_type = mr["type"]
            is_hi = bool(mr["is_highlight"])
            
            raw_data = {}
            try:
                raw_data = json.loads(mr["raw_metadata"]) if mr["raw_metadata"] else {}
            except Exception:
                raw_data = {}
            tags = raw_data.get("tags") or []
            library_id = raw_data.get("library_id") or ""
            series = raw_data.get("series") or ""
            series_order = raw_data.get("series_order") or ""
            series_list = raw_data.get("series_list") or []
            if not series_list and series:
                series_list = [{"name": series, "order": series_order}]
            profile_states = {}
            for pid, pcfg in profiles.items():
                yoto_rules = pcfg.get("yoto", {})
                allowed_ids = yoto_rules.get("allowed_card_ids", [])
                excluded_ids = yoto_rules.get("excluded_card_ids", [])
                if m_id in excluded_ids:
                    allowed = False
                    reason = "explicit_excluded"
                elif m_id in allowed_ids:
                    allowed = True
                    reason = "explicit_allowed"
                elif m_type == "abs":
                    # Check ABS user scoping
                    child_tag = (pcfg.get("abs_tag") or "").strip().lower()
                    abs_uname = (pcfg.get("abs_username") or "").strip().lower()
                    
                    item_tags_lower = [t.lower() for t in tags]
                    
                    if child_tag and child_tag in item_tags_lower:
                        allowed = True
                        reason = "abs_tag_match"
                    elif any(dt in item_tags_lower for dt in default_child_tags):
                        allowed = True
                        reason = "abs_account_permitted"
                    elif abs_uname and any(dt in item_tags_lower for dt in default_child_tags):
                        allowed = True
                        reason = "abs_account_permitted"
                    else:
                        allowed = False
                        reason = "abs_restricted"
                elif yoto_rules.get("inherit_shared", True) and shared_rules.get("include_all", False):
                    allowed = True
                    reason = "inherited_shared_all"
                elif yoto_rules.get("inherit_shared", True) and (m_id in shared_rules.get("allowed_card_ids", [])):
                    allowed = True
                    reason = "inherited_shared"
                elif yoto_rules.get("inherit_shared", True) and shared_rules.get("include_myo_by_default", True) and m_type == "yoto_myo":
                    allowed = True
                    reason = "inherited_myo_default"
                else:
                    allowed = False
                    reason = "default_not_shared"
                profile_states[pid] = {"allowed": allowed, "reason": reason}
            last_played_at = raw_data.get("lastPlayedAt") or raw_data.get("last_played") or ""
            items.append({
                "id": m_id,
                "type": m_type,
                "title": mr["title"],
                "author": mr["author"],
                "cover_url": mr["cover_url"],
                "is_highlight": is_hi,
                "has_physical": bool(mr["has_physical"]) if "has_physical" in mr.keys() else False,
                "last_played_at": last_played_at,
                "tags": tags,
                "library_id": library_id,
                "series": series,
                "series_order": series_order,
                "series_list": series_list,
                "profiles": profile_states
            })
        return {
            "items": items,
            "profiles": list(profiles.keys()),
            "shared_rules": shared_rules,
            "exclude_single_card_series": bool(settings.get("exclude_single_card_series", True))
        }
    finally:
        conn.close()
def prune_stale_media_items(valid_ids: List[str], media_types: List[str] = None) -> int:
    """Removes cached media_items of given types that are no longer present in upstream libraries, and deletes their cached cover/chapter images from disk."""
    if not valid_ids:
        return 0
    if media_types is None:
        media_types = ["abs", "yoto", "yoto_myo"]
    conn = get_db_connection()
    stale_rows = []
    removed_count = 0
    try:
        placeholders_types = ",".join("?" for _ in media_types)
        placeholders_ids = ",".join("?" for _ in valid_ids)
        params = list(media_types) + list(valid_ids)
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, type, cover_url FROM media_items WHERE type IN ({placeholders_types}) AND id NOT IN ({placeholders_ids});",
            params
        )
        stale_rows = [dict(r) for r in cur.fetchall()]
        if stale_rows:
            with conn:
                del_cur = conn.execute(
                    f"DELETE FROM media_items WHERE type IN ({placeholders_types}) AND id NOT IN ({placeholders_ids});",
                    params
                )
                removed_count = del_cur.rowcount
                conn.execute(
                    f"DELETE FROM profile_media_permissions WHERE media_id NOT IN (SELECT id FROM media_items);"
                )
    finally:
        conn.close()

    if stale_rows:
        try:
            from core.image_resizer import invalidate_thumbnail
            from core.config import CUSTOM_ICONS_DIR
            for sr in stale_rows:
                sid = sr.get("id") or ""
                scover = sr.get("cover_url") or ""
                if sid:
                    invalidate_thumbnail(f"abs_{sid}")
                    for ch_idx in range(150):
                        invalidate_thumbnail(f"abs_ch_{sid}_{ch_idx}")
                    for icon_file in CUSTOM_ICONS_DIR.glob(f"{sid}_*.png"):
                        try:
                            icon_file.unlink()
                        except Exception:
                            pass
                if scover:
                    invalidate_thumbnail(f"yoto_{scover}")
        except Exception as e:
            logger.warning("Error cleaning up cached images for pruned media items: %s", e)

    return removed_count

def record_playback(media_id: str, profile_id: str = "default", timestamp: str = None):
    """Records or updates the last_played_at timestamp for a media item and profile."""
    if not media_id:
        return
    from datetime import datetime, timezone
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
            INSERT INTO media_playback_history (media_id, profile_id, last_played_at)
            VALUES (?, ?, ?)
            ON CONFLICT(media_id, profile_id) DO UPDATE SET last_played_at = excluded.last_played_at;
            """, (media_id, (profile_id or "default").lower(), ts))
    except Exception as e:
        logger.warning("Error recording playback history for %s: %s", media_id, e)
    finally:
        conn.close()


def get_playback_history(profile_id: str) -> Dict[str, str]:
    """Returns dictionary of media_id -> ISO timestamp for the given profile and default."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT media_id, last_played_at FROM media_playback_history WHERE profile_id IN (?, 'default');",
            ((profile_id or "default").lower(),)
        )
        res = {}
        for r in cur.fetchall():
            mid = r["media_id"]
            ts = str(r["last_played_at"] or "")
            if mid not in res or ts > res[mid]:
                res[mid] = ts
        return res
    except Exception as e:
        logger.warning("Error reading playback history for %s: %s", profile_id, e)
        return {}
    finally:
        conn.close()

