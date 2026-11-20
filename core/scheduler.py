"""
Background Library Refresh Scheduler.
Automatically refreshes upstream Yoto and Audiobookshelf media items periodically.
"""

import time
import threading
from datetime import datetime, timezone
from typing import Any, List, Optional
import requests
import database
import clients
from core.config import logger


# Global reference to scheduler thread
_scheduler_thread = None
_stop_event = threading.Event()
_scheduler_lock = threading.Lock()
_last_refresh_time = 0.0
_last_refresh_status = "Never run"
_last_refresh_count = 0


def _normalize_timestamp_iso(val: Any) -> str:
    """Normalizes numeric epoch (ms or sec) or ISO-8601 strings to UTC ISO-8601."""
    if val is None or val == "":
        return ""
    if isinstance(val, (int, float)):
        ts = float(val)
        if ts <= 0:
            return ""
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, timezone.utc).isoformat()
        except Exception:
            return ""
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return ""
        try:
            num = float(s)
            if num <= 0:
                return ""
            if num > 1e12:
                num /= 1000.0
            return datetime.fromtimestamp(num, timezone.utc).isoformat()
        except ValueError:
            pass
        try:
            clean = s[:-1] + "+00:00" if s.endswith("Z") else s
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return s
    return ""


def sync_abs_user_playback_history() -> int:
    """
    Synchronizes Audiobookshelf user mediaProgress.lastUpdate timestamps into
    media_playback_history for every child profile with a linked abs_username.
    """
    if not clients.abs_client:
        return 0
    profiles = database.get_all_profiles()
    linked = [
        (p_id, p_cfg)
        for p_id, p_cfg in profiles.items()
        if (p_cfg.get("abs_username") or "").strip()
    ]
    if not linked:
        return 0

    users = clients.abs_client.get_all_users()
    uname_to_uid = {
        (u.get("username") or "").strip().lower(): u.get("id")
        for u in users
        if u.get("id")
    }

    synced = 0
    for p_id, p_cfg in linked:
        uname = p_cfg["abs_username"].strip().lower()
        uid = uname_to_uid.get(uname)
        if not uid:
            continue
        existing = database.get_playback_history(p_id)
        for mp in clients.abs_client.get_user_media_progress(uid):
            lid = mp.get("libraryItemId")
            lu = mp.get("lastUpdate")
            iso_ts = _normalize_timestamp_iso(lu)
            if lid and iso_ts and (lid not in existing or iso_ts > existing[lid]):
                database.record_playback(lid, p_id, iso_ts)
                existing[lid] = iso_ts
                synced += 1

    if synced > 0:
        logger.info("Scheduled ABS progress sync updated %d playback history record(s).", synced)
    return synced


def perform_library_refresh() -> int:
    """
    Executes a catalog sync across upstream Yoto and Audiobookshelf sources,
    updating media_items in the SQLite database.
    Returns the count of discovered / upserted items.
    """
    global _last_refresh_time, _last_refresh_status, _last_refresh_count
    logger.info("Starting scheduled background library refresh...")
    discovered_items = []

    # Collect existing known series from database to correlate across sources
    known_series_set = set()
    try:
        cur_items = database.get_catalog_matrix().get("items", [])
        for it in cur_items:
            for s in it.get("series_list", []):
                if s.get("name"):
                    known_series_set.add(s["name"].strip())
    except Exception as e:
        logger.debug("Notice reading known series from database: %s", e)

    # 1. Yoto Cards & Groups
    yoto_playback_events = []
    if clients.yoto_client:
        yoto_card_groups = {}
        try:
            groups = clients.yoto_client.get_groups()
            for g in groups:
                g_title = (g.get("title") or g.get("name") or "").strip()
                if not g_title:
                    continue
                c_ids = g.get("cardIds") or g.get("card_ids") or []
                for cid in c_ids:
                    yoto_card_groups.setdefault(cid, []).append(g_title)
        except Exception as e:
            logger.debug("Background Yoto groups sync notice: %s", e)

        try:
            raw_yoto = clients.yoto_client.get_raw_library()
            for c in raw_yoto:
                cid = c.get("cardId") or c.get("id")
                c_title = c.get("title") or "Yoto Card"
                s_name = c.get("series") or ""
                s_ord = c.get("series_order") or ""

                # Lazy import helper from routes.admin_curation
                from routes.admin_curation import extract_series_list
                series_list = extract_series_list(s_name, s_ord, title=c_title, known_series=list(known_series_set))

                for g_name in yoto_card_groups.get(cid, []):
                    if not any(s["name"].lower() == g_name.lower() for s in series_list):
                        series_list.append({"name": g_name, "order": ""})

                primary_series = series_list[0]["name"] if series_list else ""
                primary_order = series_list[0]["order"] if series_list else ""

                last_played_iso = _normalize_timestamp_iso(
                    c.get("lastPlayedAt")
                    or (c.get("card") or {}).get("lastPlayedAt")
                    or (c.get("metadata") or {}).get("lastPlayedAt")
                    or c.get("last_played_at")
                    or ""
                )
                if cid and last_played_iso:
                    yoto_playback_events.append((cid, last_played_iso))

                discovered_items.append({
                    "id": cid,
                    "type": "yoto_myo" if c.get("isMyo") else "yoto",
                    "title": c.get("title") or "Yoto Card",
                    "author": c.get("author") or "Yoto",
                    "cover_url": c.get("coverImageUrl") or c.get("iconUrl") or "",
                    "raw_metadata": {
                        "series": primary_series,
                        "series_order": primary_order,
                        "series_list": series_list,
                        "lastPlayedAt": last_played_iso
                    }
                })
        except Exception as e:
            logger.warning("Background Yoto sync error: %s", e)

    # 2. Audiobookshelf Books
    if clients.abs_client:
        try:
            libraries = clients.abs_client.get_libraries()
            for lib in libraries:
                lib_id = lib.get("id")
                if lib.get("mediaType", "book") != "book":
                    continue
                try:
                    url = f"{clients.abs_client.base_url}/api/libraries/{lib_id}/items?limit=0"
                    res = requests.get(url, headers=clients.abs_client.get_headers(), timeout=20)
                    if res.status_code == 200:
                        for b in res.json().get("results", []):
                            media = b.get("media", {})
                            meta = media.get("metadata", {})
                            tags = media.get("tags") or []

                            b_title = meta.get("title") or b.get("name") or "Book"
                            raw_series = meta.get("seriesName") or meta.get("series") or ""
                            raw_series_order = meta.get("seriesSequence") or meta.get("sequence") or ""
                            from routes.admin_curation import extract_series_list
                            series_list = extract_series_list(raw_series, raw_series_order, title=b_title, known_series=list(known_series_set))
                            for s in series_list:
                                if s.get("name"):
                                    known_series_set.add(s["name"].strip())

                            primary_series = series_list[0]["name"] if series_list else ""
                            primary_order = series_list[0]["order"] if series_list else ""

                            upd_ts = int((b.get("updatedAt") or 0) // 1000) if b.get("updatedAt") else 0
                            cover_qs = f"&v={upd_ts}" if upd_ts > 0 else ""
                            discovered_items.append({
                                "id": b.get("id"),
                                "type": "abs",
                                "title": meta.get("title") or b.get("name") or "Book",
                                "author": meta.get("authorName") or meta.get("author") or "Unknown",
                                "cover_url": f"/api/thumb?type=abs&id={b.get('id')}{cover_qs}",
                                "raw_metadata": {
                                    "tags": tags,
                                    "library_id": lib_id,
                                    "series": primary_series,
                                    "series_order": primary_order,
                                    "series_list": series_list,
                                    "updated_at_ts": upd_ts
                                }
                            })
                except Exception as e:
                    logger.warning("Background ABS library %s scan error: %s", lib_id, e)
        except Exception as e:
            logger.warning("Background ABS get_libraries error: %s", e)

    count = database.upsert_media_items(discovered_items)

    # Ingest Yoto card lastPlayedAt events and sync ABS user playback history
    for y_cid, lp_iso in yoto_playback_events:
        try:
            database.record_playback(y_cid, "default", lp_iso)
        except Exception as e:
            logger.debug("Yoto lastPlayedAt ingestion notice for %s: %s", y_cid, e)
    try:
        sync_abs_user_playback_history()
    except Exception as e:
        logger.debug("Scheduled ABS user playback sync notice: %s", e)

    # Prune stale records that were deleted upstream in Yoto or Audiobookshelf
    pruned_count = 0
    if discovered_items:
        valid_ids = [it.get("id") for it in discovered_items if it.get("id")]
        pruned_count = database.prune_stale_media_items(valid_ids, ["abs", "yoto", "yoto_myo"])
        if pruned_count > 0:
            logger.info("Background library refresh pruned %d stale media items.", pruned_count)
        try:
            from core.image_resizer import prune_orphan_thumbnails
            orphan_thumbs = prune_orphan_thumbnails(discovered_items)
            if orphan_thumbs > 0:
                logger.info("Pruned %d orphaned thumbnail images from disk cache.", orphan_thumbs)
        except Exception as e:
            logger.debug("Orphan thumbnail sweep notice: %s", e)

    try:
        from routes.admin_profiles import sync_all_bubble_avatars
        sync_all_bubble_avatars()
    except Exception as e:
        logger.debug("Avatar bubble sync notice: %s", e)

    try:
        from core.bridge.offline import prune_evicted_profile_playlists
        lru_res = prune_evicted_profile_playlists()
        if lru_res.get("pruned_count", 0) > 0:
            logger.info("Automated LRU cache pruner evicted %d playlist(s).", lru_res["pruned_count"])
    except Exception as e:
        logger.debug("Scheduled LRU cache pruning notice: %s", e)

    _last_refresh_time = time.time()
    _last_refresh_count = count
    status_suffix = f", {pruned_count} pruned" if pruned_count > 0 else ""
    _last_refresh_status = f"Completed successfully ({count} items refreshed{status_suffix})"
    logger.info("Background library refresh complete: %d items upserted.", count)
    return count


def _check_daily_profile_rotations(now_dt: Optional[datetime] = None) -> List[str]:
    """
    Triggers daily wall-clock catalog rotation re-rolls when the local hour reaches
    each profile's configured catalog_rotation_hour (default 03:00).
    """
    now_dt = now_dt or datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")
    cur_hour = now_dt.hour

    profiles = database.get_all_profiles()
    settings = database.get_system_settings()
    last_dates = dict(settings.get("profile_last_rotation_dates") or {})

    due_profiles: List[str] = []
    for pid, pcfg in profiles.items():
        rot_hour = max(0, min(23, int(pcfg.get("catalog_rotation_hour", 3) if pcfg.get("catalog_rotation_hour") is not None else 3)))
        if cur_hour >= rot_hour and last_dates.get(pid) != today_str:
            due_profiles.append(pid)

    if due_profiles:
        logger.info("Daily wall-clock rotation due for profile(s): %s", ", ".join(due_profiles))
        if time.time() - _last_refresh_time >= 300:
            try:
                perform_library_refresh()
            except Exception as e:
                logger.warning("Pre-rotation library refresh notice: %s", e)
        for pid in due_profiles:
            try:
                database.get_catalog_items_for_profile(pid, "abs")
                database.get_catalog_items_for_profile(pid, "yoto")
            except Exception as e:
                logger.debug("Catalog warm-up notice during rotation for %s: %s", pid, e)
            last_dates[pid] = today_str
        database.set_system_setting("profile_last_rotation_dates", last_dates)

    return due_profiles


def get_refresh_status() -> dict:
    """Returns current scheduler state and last execution metrics."""
    settings = database.get_system_settings()
    enabled = bool(settings.get("auto_library_refresh_enabled", True))
    interval_hours = float(settings.get("auto_library_refresh_hours", 6))

    next_run_seconds = 0
    if enabled and _last_refresh_time > 0:
        interval_secs = interval_hours * 3600
        elapsed = time.time() - _last_refresh_time
        next_run_seconds = max(0, int(interval_secs - elapsed))

    return {
        "enabled": enabled,
        "interval_hours": interval_hours,
        "last_refresh_time": int(_last_refresh_time) if _last_refresh_time else None,
        "last_refresh_status": _last_refresh_status,
        "last_refresh_count": _last_refresh_count,
        "next_run_seconds": next_run_seconds,
        "profile_last_rotation_dates": settings.get("profile_last_rotation_dates", {})
    }


def _scheduler_loop():
    """Background worker daemon thread that sleeps and checks if refresh is due."""
    logger.info("Library refresh background daemon started.")
    # Wait 60 seconds on initial server startup before checking, to allow clients to initialize cleanly
    if _stop_event.wait(60):
        return

    while not _stop_event.is_set():
        try:
            settings = database.get_system_settings()
            enabled = bool(settings.get("auto_library_refresh_enabled", True))
            interval_hours = float(settings.get("auto_library_refresh_hours", 6))
            interval_secs = max(300, interval_hours * 3600)  # Minimum 5 minutes guardrail

            now = time.time()
            if enabled:
                global _last_refresh_time
                if _last_refresh_time == 0 or (now - _last_refresh_time) >= interval_secs:
                    try:
                        perform_library_refresh()
                    except Exception as e:
                        logger.error("Exception during background library refresh: %s", e)

            try:
                _check_daily_profile_rotations()
            except Exception as e:
                logger.error("Exception during daily profile rotation check: %s", e)
        except Exception as e:
            logger.error("Scheduler loop error: %s", e)

        # Sleep in short increments of 10 seconds to allow responsive daemon termination
        for _ in range(6):
            if _stop_event.wait(5):
                break


def start_scheduler():
    """Starts the background library refresh scheduler thread if not already running."""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _stop_event.clear()
            _scheduler_thread = threading.Thread(
                target=_scheduler_loop,
                name="LibraryRefreshScheduler",
                daemon=True
            )
            _scheduler_thread.start()
            logger.info("Library refresh scheduler thread initialized.")


def trigger_immediate_refresh() -> int:
    """Manually triggers an immediate library refresh from API/UI."""
    return perform_library_refresh()

