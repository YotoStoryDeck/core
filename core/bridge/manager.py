"""
StoryDeck Core Bridge Manager.
Orchestrates bridge slots, tracks, Audiobookshelf metadata parsing,
and synchronized Yoto Cloud playlist updates.
"""
from __future__ import annotations
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
import database
import clients
from .chapters import chapter_spans, DEFAULT_PART_SECONDS
from .quiet import get_quiet_spots
from .streamer import AudioTrackSource

logger = logging.getLogger("storydeck.bridge")


class BridgeManager:
    def __init__(self):
        self.quiet_spots = get_quiet_spots()

    def get_slot(self, slot_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a bridge card slot by slot_id."""
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bridge_slots WHERE slot_id = ?;", (slot_id,))
            row = cur.fetchone()
            if not row:
                return None
            slot = dict(row)
            slot["tracks"] = self.get_slot_tracks(slot_id)
            return slot
        finally:
            conn.close()

    def list_slots(self) -> List[Dict[str, Any]]:
        """Lists all registered bridge slots (profile cards, fleet cards, and virtual slots)."""
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bridge_slots ORDER BY updated_at DESC;")
            rows = cur.fetchall()
            results = []
            for r in rows:
                s = dict(r)
                s["tracks"] = self.get_slot_tracks(s["slot_id"])
                results.append(s)
            return results
        finally:
            conn.close()

    def get_slot_tracks(self, slot_id: str) -> List[Dict[str, Any]]:
        """Retrieves track layout for a slot ordered by track_idx."""
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, slot_id, track_idx, title, start_time, end_time, duration, icon_hash, yoto_sha256, stream_url
                FROM bridge_tracks
                WHERE slot_id = ?
                ORDER BY track_idx ASC;
            """, (slot_id,))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_track(self, slot_id: str, track_idx: int) -> Optional[Dict[str, Any]]:
        """Retrieves a specific track for a slot."""
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, slot_id, track_idx, title, start_time, end_time, duration, icon_hash, yoto_sha256, stream_url
                FROM bridge_tracks
                WHERE slot_id = ? AND track_idx = ?;
            """, (slot_id, track_idx))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_slot_speed(self, slot_id: str, speed: float) -> bool:
        """Sets playback speed for a card slot (1.0 = normal)."""
        clamped_speed = max(0.5, min(2.0, float(speed or 1.0)))
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("UPDATE bridge_slots SET speed = ?, updated_at = CURRENT_TIMESTAMP WHERE slot_id = ?;", (clamped_speed, slot_id))
                return cur.rowcount > 0
        finally:
            conn.close()

    def set_slot_own_place(self, slot_id: str, own_place: bool) -> bool:
        """Toggles independent listening place for a card slot."""
        val = 1 if own_place else 0
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("UPDATE bridge_slots SET own_place = ?, updated_at = CURRENT_TIMESTAMP WHERE slot_id = ?;", (val, slot_id))
                return cur.rowcount > 0
        finally:
            conn.close()

    def set_slot_pin(self, slot_id: str, is_pinned: bool) -> bool:
        """Pins or unpins a slot to protect it from automated LRU cleaner."""
        val = 1 if is_pinned else 0
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("UPDATE bridge_slots SET is_pinned = ?, is_protected = ?, updated_at = CURRENT_TIMESTAMP WHERE slot_id = ?;", (val, val, slot_id))
                return cur.rowcount > 0
        finally:
            conn.close()

    def delete_slot(self, slot_id: str) -> bool:
        """Removes a card slot and cascades its tracks."""
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM bridge_slots WHERE slot_id = ?;", (slot_id,))
                return cur.rowcount > 0
        finally:
            conn.close()

    def _build_abs_audio_sources(self, abs_item_id: str, item_data: Optional[Dict[str, Any]]) -> Tuple[List[AudioTrackSource], str]:
        """Builds AudioTrackSource spans and auth header for an Audiobookshelf item."""
        audio_files = (item_data or {}).get("media", {}).get("audioFiles") or []
        abs_token = ""
        abs_base = ""
        if clients.abs_client:
            abs_token = getattr(clients.abs_client, "token", "") or getattr(clients.abs_client, "api_key", "") or ""
            abs_base = (getattr(clients.abs_client, "base_url", "") or "").rstrip("/")

        sources: List[AudioTrackSource] = []
        c_offset = 0.0
        for af in audio_files:
            f_dur = float(af.get("duration") or 0.0)
            local_path = af.get("local_path") or ""
            ino = af.get("ino") or af.get("id") or ""
            url = local_path if local_path else (f"{abs_base}/api/items/{abs_item_id}/file/{ino}" if (abs_base and ino) else "")
            if url and f_dur > 0:
                sources.append(AudioTrackSource(url=url, start=c_offset, duration=f_dur))
            c_offset += f_dur

        auth_hdr = f"Bearer {abs_token}" if abs_token else ""
        return sources, auth_hdr

    def assign_abs_book_to_slot(self, slot_id: str, abs_item_id: str, title: str = "",
                                author: str = "", series_id: str = "", series_name: str = "",
                                group_kind: str = "book", owner_profile_id: str = "",
                                kind: str = "permanent_myo", mode: str = "streaming",
                                base_url: str = "", scan_quiet_sync: bool = False) -> Dict[str, Any]:
        """
        Assigns an Audiobookshelf book to a card slot, generates chapter tracks,
        and saves layout in SQLite.
        """
        # 1. Fetch item from ABS client if available
        item_data = None
        if clients.abs_client:
            try:
                item_data = clients.abs_client.get_item(abs_item_id)
            except Exception as e:
                logger.warning("Failed to fetch ABS item %s metadata: %s", abs_item_id, e)

        item_media = (item_data or {}).get("media", {})
        item_meta = item_media.get("metadata", {})
        book_title = title or item_meta.get("title") or (item_data or {}).get("name") or "Audiobook"
        book_author = author or item_meta.get("authorName") or item_meta.get("author") or ""
        total_duration = float(item_media.get("duration") or 0.0)
        raw_chapters = item_media.get("chapters") or []

        resolved_series_name = (series_name or "").strip()
        if not resolved_series_name:
            raw_ser = item_meta.get("seriesName") or item_meta.get("series") or ""
            if isinstance(raw_ser, list) and raw_ser:
                first = raw_ser[0]
                raw_ser = first.get("name", "") if isinstance(first, dict) else str(first)
            elif isinstance(raw_ser, dict):
                raw_ser = raw_ser.get("name", "")
            resolved_series_name = str(raw_ser or "").split(",")[0].split("#")[0].strip()
        if not resolved_series_name:
            db_item = database.get_media_item_by_id(abs_item_id)
            if db_item and db_item.get("raw_metadata"):
                try:
                    raw_meta = json.loads(db_item["raw_metadata"])
                    resolved_series_name = (raw_meta.get("series") or "").strip()
                except Exception:
                    pass

        # 2. Build chapter spans (with pause-snapped internal cuts)
        planned_cuts: List[float] = []
        if total_duration > 0:
            chapter_spans(
                raw_chapters,
                total_duration,
                part_seconds=DEFAULT_PART_SECONDS,
                snap=lambda t: (planned_cuts.append(t), t)[1]
            )

        missing_cuts = self.quiet_spots.missing(abs_item_id, planned_cuts) if planned_cuts else []
        sources, auth_hdr = self._build_abs_audio_sources(abs_item_id, item_data) if missing_cuts else ([], "")
        if scan_quiet_sync and missing_cuts and sources:
            self.quiet_spots.scan_windows(abs_item_id, planned_cuts, sources, auth_header=auth_hdr, budget=20.0)

        snap = self.quiet_spots.snapper(abs_item_id)
        spans = chapter_spans(raw_chapters, total_duration, part_seconds=DEFAULT_PART_SECONDS, snap=snap)

        owner_val = owner_profile_id.strip() if owner_profile_id and owner_profile_id.strip() else None
        is_protected_val = 0 if kind in ("profile_cache", "ephemeral_offline") else 1

        # 3. Upsert slot record
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO bridge_slots (
                        slot_id, abs_item_id, owner_profile_id, title, author,
                        series_id, series_name, group_kind, kind, source, is_protected,
                        total_duration, mode, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'storydeck', ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(slot_id) DO UPDATE SET
                        abs_item_id = excluded.abs_item_id,
                        owner_profile_id = CASE WHEN excluded.owner_profile_id IS NOT NULL THEN excluded.owner_profile_id ELSE bridge_slots.owner_profile_id END,
                        title = excluded.title,
                        author = excluded.author,
                        series_id = excluded.series_id,
                        series_name = excluded.series_name,
                        group_kind = excluded.group_kind,
                        kind = excluded.kind,
                        is_protected = CASE WHEN excluded.kind != bridge_slots.kind THEN excluded.is_protected ELSE bridge_slots.is_protected END,
                        total_duration = excluded.total_duration,
                        mode = excluded.mode,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    slot_id, abs_item_id, owner_val, book_title, book_author,
                    series_id, resolved_series_name, group_kind, kind, is_protected_val, total_duration, mode
                ))

                # Rebuild tracks
                cur.execute("DELETE FROM bridge_tracks WHERE slot_id = ?;", (slot_id,))
                server_url = base_url.rstrip("/") if base_url else ""
                for idx, (start_t, end_t, track_title) in enumerate(spans, 1):
                    stream_url = f"{server_url}/s/audio/{slot_id}/{idx}" if server_url else f"/s/audio/{slot_id}/{idx}"
                    cur.execute("""
                        INSERT INTO bridge_tracks (slot_id, track_idx, title, start_time, end_time, duration, stream_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (slot_id, idx, track_title, start_t, end_t, end_t - start_t, stream_url))

            if not scan_quiet_sync and missing_cuts and sources:
                def _refresh_snapped_tracks():
                    cur_slot = self.get_slot(slot_id)
                    if not cur_slot or cur_slot.get("abs_item_id") != abs_item_id:
                        return
                    if any(t.get("yoto_sha256") for t in cur_slot.get("tracks", [])):
                        return
                    new_snap = self.quiet_spots.snapper(abs_item_id)
                    if not new_snap:
                        return
                    new_spans = chapter_spans(raw_chapters, total_duration, part_seconds=DEFAULT_PART_SECONDS, snap=new_snap)
                    rconn = database.get_db_connection()
                    try:
                        with rconn:
                            rcur = rconn.cursor()
                            rcur.execute("DELETE FROM bridge_tracks WHERE slot_id = ?;", (slot_id,))
                            for ridx, (rstart, rend, rtitle) in enumerate(new_spans, 1):
                                rstream = f"{server_url}/s/audio/{slot_id}/{ridx}" if server_url else f"/s/audio/{slot_id}/{ridx}"
                                rcur.execute("""
                                    INSERT INTO bridge_tracks (slot_id, track_idx, title, start_time, end_time, duration, stream_url)
                                    VALUES (?, ?, ?, ?, ?, ?, ?);
                                """, (slot_id, ridx, rtitle, rstart, rend, rend - rstart, rstream))
                    finally:
                        rconn.close()

                self.quiet_spots.schedule_background_scan(
                    abs_item_id, planned_cuts, sources, auth_header=auth_hdr, on_complete=_refresh_snapped_tracks
                )

            return self.get_slot(slot_id) or {}
        finally:
            conn.close()

    def update_profile_primary_card(self, profile_id: str, abs_item_id: str,
                                   mode_override: Optional[str] = None,
                                   base_url: str = "") -> Dict[str, Any]:
        """
        Dynamically repoints a child profile's primary ABS card to the selected book.
        Follows profile default playback mode unless mode_override is specified.
        When switching away from an offline book, archives it into an ephemeral
        'profile_cache' slot managed by the automated LRU cache pruner.
        """
        profile = database.get_profile_by_id(profile_id)
        if not profile:
            raise ValueError(f"Profile '{profile_id}' not found.")

        mode = mode_override
        if not mode or mode == "default":
            mode = profile.get("default_playback_mode", "streaming")

        slot_id = f"profile_{profile_id}"
        existing = self.get_slot(slot_id)
        primary_card_id = (profile.get("primary_card_id") or "").strip()

        if existing and existing.get("abs_item_id") and existing.get("abs_item_id") != abs_item_id and existing.get("mode") == "offline":
            old_item_id = existing["abs_item_id"]
            cache_slot_id = f"cache_{profile_id}_{old_item_id}"
            old_pinned = int(existing.get("is_pinned") or 0)
            old_protected = 1 if old_pinned else 0
            old_yoto_cid = existing.get("yoto_card_id") or cache_slot_id

            conn = database.get_db_connection()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO bridge_slots (
                            slot_id, abs_item_id, yoto_card_id, owner_profile_id, title, author,
                            series_id, series_name, group_kind, kind, source, is_protected, is_pinned,
                            total_duration, speed, own_place, mode, offline_status, offline_progress,
                            icon_hash, last_played_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'profile_cache', ?, ?, ?, ?, ?, ?, 'offline', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(slot_id) DO UPDATE SET
                            abs_item_id = excluded.abs_item_id,
                            yoto_card_id = excluded.yoto_card_id,
                            owner_profile_id = excluded.owner_profile_id,
                            title = excluded.title,
                            author = excluded.author,
                            series_id = excluded.series_id,
                            series_name = excluded.series_name,
                            group_kind = excluded.group_kind,
                            kind = 'profile_cache',
                            is_pinned = MAX(bridge_slots.is_pinned, excluded.is_pinned),
                            is_protected = MAX(bridge_slots.is_protected, excluded.is_protected),
                            total_duration = excluded.total_duration,
                            speed = excluded.speed,
                            own_place = excluded.own_place,
                            mode = 'offline',
                            offline_status = excluded.offline_status,
                            offline_progress = excluded.offline_progress,
                            icon_hash = excluded.icon_hash,
                            last_played_at = excluded.last_played_at,
                            updated_at = CURRENT_TIMESTAMP;
                    """, (
                        cache_slot_id,
                        old_item_id,
                        old_yoto_cid,
                        profile_id,
                        existing.get("title") or "Audiobook",
                        existing.get("author") or "",
                        existing.get("series_id") or "",
                        existing.get("series_name") or "",
                        existing.get("group_kind") or "book",
                        existing.get("source") or "storydeck",
                        old_protected,
                        old_pinned,
                        float(existing.get("total_duration") or 0.0),
                        float(existing.get("speed") or 1.0),
                        int(existing.get("own_place") or 0),
                        existing.get("offline_status") or "ready",
                        float(existing.get("offline_progress") or 1.0),
                        existing.get("icon_hash") or "",
                        existing.get("last_played_at") or "",
                    ))

                    cur.execute("DELETE FROM bridge_tracks WHERE slot_id = ?;", (cache_slot_id,))
                    for trk in existing.get("tracks", []):
                        cur.execute("""
                            INSERT INTO bridge_tracks (
                                slot_id, track_idx, title, start_time, end_time,
                                duration, icon_hash, yoto_sha256, stream_url
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            cache_slot_id,
                            trk["track_idx"],
                            trk["title"],
                            trk["start_time"],
                            trk["end_time"],
                            trk["duration"],
                            trk.get("icon_hash") or "",
                            trk.get("yoto_sha256") or "",
                            trk.get("stream_url") or "",
                        ))

                    if existing.get("yoto_card_id") and existing.get("yoto_card_id") != primary_card_id:
                        cur.execute("UPDATE bridge_slots SET yoto_card_id = NULL WHERE slot_id = ?;", (slot_id,))
            finally:
                conn.close()

        warm_slot = self.get_slot(f"cache_{profile_id}_{abs_item_id}")

        slot = self.assign_abs_book_to_slot(
            slot_id=slot_id,
            abs_item_id=abs_item_id,
            owner_profile_id=profile_id,
            kind="profile_primary",
            mode=mode,
            base_url=base_url
        )

        if mode == "offline" and warm_slot and warm_slot.get("mode") == "offline":
            warm_sha_map = {
                trk["track_idx"]: trk.get("yoto_sha256")
                for trk in warm_slot.get("tracks", [])
                if trk.get("yoto_sha256")
            }
            if warm_sha_map:
                wconn = database.get_db_connection()
                try:
                    with wconn:
                        wcur = wconn.cursor()
                        for t_idx, sha in warm_sha_map.items():
                            wcur.execute(
                                "UPDATE bridge_tracks SET yoto_sha256 = ? WHERE slot_id = ? AND track_idx = ?;",
                                (sha, slot_id, t_idx)
                            )
                finally:
                    wconn.close()
                slot = self.get_slot(slot_id) or slot

        # Record in media_playback_history for recent tier curation
        database.record_playback(abs_item_id, profile_id)
        return slot

    def assign_to_fleet_card(self, slot_id: str, abs_item_id: str = "",
                             mode_override: Optional[str] = None,
                             base_url: str = "", yoto_card_id: str = "",
                             title: str = "", author: str = "") -> Dict[str, Any]:
        """Assigns an ABS book or an Official Yoto card to a named fleet card slot."""
        if yoto_card_id and not abs_item_id:
            db_item = database.get_media_item_by_id(yoto_card_id) or {}
            card_title = title or db_item.get("title") or f"Yoto Card {yoto_card_id}"
            card_author = author or db_item.get("author") or "Yoto"
            conn = database.get_db_connection()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO bridge_slots (
                            slot_id, abs_item_id, yoto_card_id, title, author,
                            group_kind, kind, source, is_protected, mode, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'yoto_official', 'permanent_myo', 'storydeck', 1, 'retail', CURRENT_TIMESTAMP)
                        ON CONFLICT(slot_id) DO UPDATE SET
                            abs_item_id = excluded.abs_item_id,
                            yoto_card_id = excluded.yoto_card_id,
                            title = excluded.title,
                            author = excluded.author,
                            group_kind = 'yoto_official',
                            mode = 'retail',
                            updated_at = CURRENT_TIMESTAMP;
                    """, (slot_id, yoto_card_id, yoto_card_id, card_title, card_author))
                    cur.execute("DELETE FROM bridge_tracks WHERE slot_id = ?;", (slot_id,))
                return self.get_slot(slot_id) or {}
            finally:
                conn.close()

        mode = mode_override if mode_override and mode_override != "default" else "streaming"
        return self.assign_abs_book_to_slot(
            slot_id=slot_id,
            abs_item_id=abs_item_id,
            title=title,
            author=author,
            kind="permanent_myo",
            mode=mode,
            base_url=base_url
        )


_bridge_manager: Optional[BridgeManager] = None

def get_bridge_manager() -> BridgeManager:
    global _bridge_manager
    if _bridge_manager is None:
        _bridge_manager = BridgeManager()
    return _bridge_manager
