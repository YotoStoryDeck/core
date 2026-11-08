"""Catalog Rotation Algorithm, Atomic Series Clustering & Display Sanitization."""
import hashlib
import json
import re
import unicodedata
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from .connection import get_db_connection, logger
from .profiles import get_all_profiles
from .media import get_catalog_matrix, get_playback_history, record_playback

def sanitize_display_text(text: str) -> str:
    """
    Normalizes accented characters and smart typography into standard ASCII
    for glitch-free rendering on microcontroller LCD fonts (e.g. Pokémon -> Pokemon, Peppa’s -> Peppa's).
    """
    if not text or not isinstance(text, str):
        return text or ""
    replacements = {
        "\u2019": "'", "\u2018": "'", "\u201a": "'", "\u201b": "'", "\u00b4": "'", "`": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
        "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2026": "...",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    import unicodedata
    decomposed = unicodedata.normalize('NFKD', text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))

def get_catalog_items_for_profile(profile_key: str, media_type: str = "abs", client_type: str = "touch") -> List[Dict[str, Any]]:
    """
    Retrieves filtered media catalog items for a child profile directly from SQLite cache.
    Implements multi-tiered rotation curation:
    1. 'Last Played' Tier: Sorted directly to the top for instant one-touch resumption.
    2. 'Sticky Favorites' Tier: Parent-pinned highlights (is_highlight = 1).
    3. 'Discovery Rotation Pool': Deterministically rotated daily mix with Book #1 series prioritization
       and physical card down-weighting, capped at the configurable profile rotation limit (default 60 on Touch, 0/unlimited on Kiosk).
    Returns microcontroller-optimized array matching the client response schema.
    """
    from datetime import datetime, timezone
    import hashlib

    matrix = get_catalog_matrix()
    items = matrix.get("items", [])
    profiles = get_all_profiles()
    pcfg = profiles.get(profile_key.lower(), {})
    hide_physical = bool(pcfg.get("hide_physical", False))
    if client_type == "kiosk":
        # 0 denotes unlimited; positive integer caps at that limit
        rotation_limit = int(pcfg.get("kiosk_catalog_limit", 0) if pcfg.get("kiosk_catalog_limit") is not None else 0)
    else:
        # Bedside Touch controller: default 60 (for low PSRAM pressure and fast boot)
        rotation_limit = int(pcfg.get("catalog_rotation_limit", 60) or 60)
        if rotation_limit <= 0:
            rotation_limit = 60

    # Sync live playback history
    playback_history = get_playback_history(profile_key)
    try:
        import clients
        import requests
        if clients.abs_client and pcfg.get("abs_username"):
            try:
                abs_c = clients.abs_client
                users_res = requests.get(f"{abs_c.base_url}/api/users", headers=abs_c.get_headers(), timeout=4)
                if users_res.status_code == 200:
                    target_uname = pcfg["abs_username"].strip().lower()
                    uid = next((u.get("id") for u in users_res.json().get("users", []) if (u.get("username") or "").lower() == target_uname), None)
                    if uid:
                        prog_res = requests.get(f"{abs_c.base_url}/api/users/{uid}", headers=abs_c.get_headers(), timeout=4)
                        if prog_res.status_code == 200:
                            for mp in prog_res.json().get("mediaProgress", []):
                                lid = mp.get("libraryItemId")
                                lu = mp.get("lastUpdate")
                                if lid and lu:
                                    iso_ts = datetime.fromtimestamp(lu / 1000.0, timezone.utc).isoformat()
                                    if lid not in playback_history or iso_ts > playback_history[lid]:
                                        playback_history[lid] = iso_ts
                                        record_playback(lid, profile_key, iso_ts)
            except Exception as pe:
                logger.debug("Notice updating live ABS progress for %s: %s", profile_key, pe)
    except Exception as ie:
        logger.debug("Notice initializing clients in catalog: %s", ie)
    if client_type != "kiosk" and rotation_limit <= 0:
        rotation_limit = 60

    def _parse_seq(val, title):
        seq = None
        seq_disp = str(val).strip() if (val is not None and str(val).strip() != "") else None
        if seq_disp:
            m_lead = re.search(r"(\d+(?:\.\d+)?)", seq_disp)
            if m_lead:
                try:
                    seq = float(m_lead.group(1))
                except (ValueError, TypeError):
                    pass
        if seq is None and title:
            m_range = re.search(r"#\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)", title, re.IGNORECASE)
            if m_range:
                seq_disp = re.sub(r"\s+", "", m_range.group(1) or m_range.group(2))
                m_lead = re.search(r"(\d+(?:\.\d+)?)", seq_disp)
                if m_lead:
                    try:
                        seq = float(m_lead.group(1))
                    except (ValueError, TypeError):
                        pass
            else:
                m_num = re.search(r"#\s*(\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)", title, re.IGNORECASE)
                if m_num:
                    v = m_num.group(1) or m_num.group(2)
                    seq_disp = str(v).strip()
                    try:
                        seq = float(v)
                    except (ValueError, TypeError):
                        pass
        return seq, seq_disp

    allowed_entries = []
    for it in items:
        m_type = it.get("type")
        if media_type == "abs" and m_type != "abs":
            continue
        if media_type == "yoto" and not m_type.startswith("yoto"):
            continue
        if not it.get("profiles", {}).get(profile_key, {}).get("allowed"):
            continue

        has_phys = bool(it.get("has_physical", False))
        if hide_physical and has_phys:
            continue

        title = sanitize_display_text(it.get("title") or "")
        primary_series = sanitize_display_text(it.get("series") or "")
        raw_order = it.get("series_order") or ""
        raw_list = it.get("series_list") or []
        s_seq, s_seq_disp = _parse_seq(raw_order, title)
        series_list = []
        for s in raw_list:
            s_name = sanitize_display_text(s.get("name") or "")
            s_ord = s.get("order") or s.get("sequence_display") or s.get("sequence") or raw_order
            sub_seq, sub_seq_disp = _parse_seq(s_ord, title)
            if s_name:
                series_list.append({
                    "name": s_name,
                    "sequence": sub_seq,
                    "sequence_display": sub_seq_disp
                })

        cover_url = it.get("cover_url") or ""
        cover_v = hashlib.sha256(cover_url.encode("utf-8")).hexdigest()[:8] if cover_url else "1"
        if media_type == "yoto":
            if cover_url and not cover_url.startswith("/api/thumb"):
                import urllib.parse
                thumb = f"/api/thumb?type=yoto&id={it.get('id', '')}&url={urllib.parse.quote(cover_url)}&v={cover_v}"
            elif not cover_url:
                thumb = f"/api/thumb?type=yoto&id={it.get('id', '')}&v={cover_v}"
            else:
                thumb = cover_url if "v=" in cover_url else f"{cover_url}{'&' if '?' in cover_url else '?'}v={cover_v}"
        else:
            base_t = cover_url or f"/api/thumb?type=abs&id={it.get('id', '')}"
            thumb = base_t if "v=" in base_t else f"{base_t}{'&' if '?' in base_t else '?'}v={cover_v}"

        entry = {
            "id": it.get("id"),
            "type": "abs" if m_type == "abs" else "yoto",
            "title": title,
            "author": sanitize_display_text(it.get("author") or ("Unknown" if m_type == "abs" else "Yoto")),
            "thumb": thumb,
            "is_highlight": bool(it.get("is_highlight")),
            "has_physical": has_phys,
            "series": primary_series,
            "sequence": s_seq,
            "sequence_display": s_seq_disp,
            "series_list": series_list,
            "last_played_at": playback_history.get(it.get("id")) or it.get("last_played_at") or "",
            "_last_played_at": playback_history.get(it.get("id")) or it.get("last_played_at") or ""
        }
        if media_type == "yoto":
            entry["is_myo"] = (m_type == "yoto_myo")
            entry["groups"] = [s.get("name") for s in raw_list if s.get("name")]
        allowed_entries.append(entry)

    # Partition into tiers
    recent_items = []
    highlight_items = []
    pool_items = []

    for e in allowed_entries:
        lp = e.get("_last_played_at")
        if lp and str(lp).strip():
            recent_items.append(e)
        elif e.get("is_highlight"):
            highlight_items.append(e)
        else:
            pool_items.append(e)

    # Sort recent tier newest first (lexical sort on ISO timestamp descending)
    recent_items.sort(key=lambda x: str(x.get("_last_played_at") or ""), reverse=True)
    recent_tier = recent_items[:8]
    # Any overflow recent items move to pool
    pool_items.extend(recent_items[8:])

    # Sort highlight tier alphabetically ignoring articles
    def _clean_title(t):
        return re.sub(r"^(the|a|an)\s+", "", (t or "").strip(), flags=re.IGNORECASE).lower()

    highlight_items.sort(key=lambda x: _clean_title(x.get("title", "")))

    # --------------------------------------------------------------------------
    # Atomic Whole-Series Rotation & Complete Series Preservation:
    # Build complete mapping of ALL allowed books by series name.
    # --------------------------------------------------------------------------
    series_all_books = {}
    for it in allowed_entries:
        s_name = (it.get("series") or "").strip()
        if s_name:
            series_all_books.setdefault(s_name.lower(), []).append(it)
        for extra in (it.get("series_list") or []):
            ex_name = (extra.get("name") or "").strip()
            if ex_name:
                series_all_books.setdefault(ex_name.lower(), []).append(it)

    def _book_seq_key(b):
        sq = b.get("sequence")
        if sq is not None and sq >= 0.0:
            return (0, sq)
        disp = b.get("sequence_display") or ""
        return (1, disp.lower() if disp else "zzzz")

    for s_low, blist in series_all_books.items():
        seen_b = set()
        dedup_b = []
        for b in blist:
            if b["id"] not in seen_b:
                seen_b.add(b["id"])
                dedup_b.append(b)
        series_all_books[s_low] = sorted(dedup_b, key=_book_seq_key)

    pulled_ids = set()
    final_results = []

    def _pull_item_and_whole_series(item):
        if item["id"] in pulled_ids:
            return
        pulled_ids.add(item["id"])
        final_results.append(item)
        # Pull all sister books in all series/groups this item belongs to
        sn_list = []
        p_ser = (item.get("series") or "").strip()
        if p_ser:
            sn_list.append(p_ser.lower())
        for ex in (item.get("series_list") or []):
            exn = (ex.get("name") or "").strip()
            if exn and exn.lower() not in sn_list:
                sn_list.append(exn.lower())
        for sn in sn_list:
            for sister in series_all_books.get(sn, []):
                if sister["id"] not in pulled_ids:
                    pulled_ids.add(sister["id"])
                    final_results.append(sister)

    # 1. Pull Recent Tier and any series they belong to as whole
    for r in recent_tier:
        _pull_item_and_whole_series(r)

    # 2. Pull Highlight Tier and any series they belong to as whole
    for h in highlight_items:
        _pull_item_and_whole_series(h)

    # 3. Group remaining unpulled items into atomic clusters (standalone card or whole series)
    cluster_map = {}
    for it in pool_items:
        if it["id"] in pulled_ids:
            continue
        p_ser = (it.get("series") or "").strip()
        if p_ser:
            c_key = f"series:{p_ser.lower()}"
        else:
            c_key = f"card:{it['id']}"
        cluster_map.setdefault(c_key, []).append(it)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seed_base = f"{profile_key.lower()}:{today_str}"

    cluster_list = []
    for c_key, c_books in cluster_map.items():
        c_books.sort(key=_book_seq_key)
        rep_id = c_books[0]["id"]
        h = int(hashlib.sha256(f"{seed_base}:{rep_id}".encode()).hexdigest()[:8], 16)
        all_phys = all(b.get("has_physical") for b in c_books)
        weight_mult = 3 if all_phys else 1
        rank = h * weight_mult
        cluster_list.append((rank, c_key, c_books))

    cluster_list.sort(key=lambda x: x[0])

    for rank, c_key, c_books in cluster_list:
        if rotation_limit > 0 and len(final_results) >= rotation_limit:
            break
        for b in c_books:
            _pull_item_and_whole_series(b)

    # Predetermine series representative cover and ID on every card
    for r in final_results:
        s_name = (r.get("series") or "").strip()
        if s_name and s_name.lower() in series_all_books:
            lead = series_all_books[s_name.lower()][0]
            r["series_cover"] = lead.get("cover") or lead.get("thumb") or ""
            r["series_cover_id"] = lead.get("id") or ""
        else:
            r["series_cover"] = ""
            r["series_cover_id"] = ""
        for extra in (r.get("series_list") or []):
            ex_name = (extra.get("name") or "").strip()
            if ex_name and ex_name.lower() in series_all_books:
                ex_lead = series_all_books[ex_name.lower()][0]
                extra["cover"] = ex_lead.get("cover") or ex_lead.get("thumb") or ""
                extra["cover_id"] = ex_lead.get("id") or ""

    # Clean up internal metadata keys
    for r in final_results:
        r.pop("_last_played_at", None)
        r.pop("_rank", None)

    return final_results

def set_item_highlight(media_id: str, is_highlight: bool) -> bool:
    """Toggles the seasonal/pinned highlight status of a media item."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE media_items SET is_highlight = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (1 if is_highlight else 0, media_id))
        return True
    finally:
        conn.close()
def batch_update_media_highlight(media_ids: List[str], is_highlight: bool) -> int:
    """Atomically sets is_highlight for multiple media items."""
    if not media_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ",".join("?" for _ in media_ids)
        val = 1 if is_highlight else 0
        with conn:
            cur = conn.execute(
                f"UPDATE media_items SET is_highlight = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                [val] + list(media_ids)
            )
            return cur.rowcount
    finally:
        conn.close()

def set_item_physical(media_id: str, has_physical: bool) -> bool:
    """Sets the physical plastic card ownership flag of a media item."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE media_items SET has_physical = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (1 if has_physical else 0, media_id))
        return True
    finally:
        conn.close()

def batch_update_media_physical(media_ids: List[str], has_physical: bool) -> int:
    """Atomically sets has_physical for multiple media items."""
    if not media_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ",".join("?" for _ in media_ids)
        val = 1 if has_physical else 0
        with conn:
            cur = conn.execute(
                f"UPDATE media_items SET has_physical = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                [val] + list(media_ids)
            )
            return cur.rowcount
    finally:
        conn.close()
def batch_update_profile_media_permissions(media_ids: List[str], profile_actions: Dict[str, str], is_highlight: Optional[bool] = None, has_physical: Optional[bool] = None) -> Dict[str, Any]:
    """
    Atomically updates media permissions for multiple items across one or more profiles.
    profile_actions: { profile_id: "allow" | "exclude" | "reset" }
    is_highlight: optional boolean to update highlight status simultaneously
    has_physical: optional boolean to update physical ownership flag simultaneously
    """
    if not media_ids:
        return {"updated_cards": 0, "affected_profiles": 0}
    conn = get_db_connection()
    try:
        with conn:
            # 1. Optional bulk highlight update
            placeholders = ",".join("?" for _ in media_ids)
            if is_highlight is not None:
                val = 1 if is_highlight else 0
                conn.execute(
                    f"UPDATE media_items SET is_highlight = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                    [val] + list(media_ids)
                )
            if has_physical is not None:
                val_phy = 1 if has_physical else 0
                conn.execute(
                    f"UPDATE media_items SET has_physical = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                    [val_phy] + list(media_ids)
                )
            # 2. Bulk profile permission changes
            affected_profiles = 0
            for prof_id, action in profile_actions.items():
                action = str(action).lower().strip()
                if action not in ("allow", "exclude", "reset"):
                    continue
                affected_profiles += 1
                placeholders = ",".join("?" for _ in media_ids)
                # First, remove existing records for these media items for this profile
                conn.execute(
                    f"DELETE FROM profile_media_permissions WHERE profile_id = ? AND media_id IN ({placeholders});",
                    [prof_id] + list(media_ids)
                )
                if action in ("allow", "exclude"):
                    perm_val = "allowed" if action == "allow" else "excluded"
                    for mid in media_ids:
                        # Ensure media item exists in media_items table to satisfy FOREIGN KEY constraint
                        conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'abs', ?);", (mid, f"Item {mid}"))
                        conn.execute(
                            "INSERT OR REPLACE INTO profile_media_permissions (profile_id, media_id, permission) VALUES (?, ?, ?);",
                            (prof_id, mid, perm_val)
                        )
                # If action == "reset", we deleted the rows so they fall back to household default rules
            return {
                "updated_cards": len(media_ids),
                "affected_profiles": affected_profiles
            }
    finally:
        conn.close()
# ============================================================================
# System Settings DAO
# ============================================================================
