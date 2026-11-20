"""
StoryDeck Core Bridge Manager.
Orchestrates bridge slots, tracks, Audiobookshelf metadata parsing,
and synchronized Yoto Cloud playlist updates.
"""
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional, Tuple
import database
import clients
from .chapters import chapter_spans, DEFAULT_PART_SECONDS

logger = logging.getLogger("storydeck.bridge")


class BridgeManager:
    def __init__(self):
        pass

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

    def assign_abs_book_to_slot(self, slot_id: str, abs_item_id: str, title: str = "",
                                author: str = "", series_id: str = "", series_name: str = "",
                                group_kind: str = "book", owner_profile_id: str = "",
                                kind: str = "permanent_myo", mode: str = "streaming",
                                base_url: str = "") -> Dict[str, Any]:
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

        # 2. Build chapter spans
        spans = chapter_spans(raw_chapters, total_duration, part_seconds=DEFAULT_PART_SECONDS)

        owner_val = owner_profile_id.strip() if owner_profile_id and owner_profile_id.strip() else None

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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'storydeck', 1, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(slot_id) DO UPDATE SET
                        abs_item_id = excluded.abs_item_id,
                        owner_profile_id = CASE WHEN excluded.owner_profile_id IS NOT NULL THEN excluded.owner_profile_id ELSE bridge_slots.owner_profile_id END,
                        title = excluded.title,
                        author = excluded.author,
                        series_id = excluded.series_id,
                        series_name = excluded.series_name,
                        group_kind = excluded.group_kind,
                        total_duration = excluded.total_duration,
                        mode = excluded.mode,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    slot_id, abs_item_id, owner_val, book_title, book_author,
                    series_id, series_name, group_kind, kind, total_duration, mode
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

            return self.get_slot(slot_id) or {}
        finally:
            conn.close()

    def update_profile_primary_card(self, profile_id: str, abs_item_id: str,
                                   mode_override: Optional[str] = None,
                                   base_url: str = "") -> Dict[str, Any]:
        """
        Dynamically repoints a child profile's primary ABS card to the selected book.
        Follows profile default playback mode unless mode_override is specified.
        """
        profile = database.get_profile_by_id(profile_id)
        if not profile:
            raise ValueError(f"Profile '{profile_id}' not found.")

        mode = mode_override
        if not mode or mode == "default":
            mode = profile.get("default_playback_mode", "streaming")

        slot_id = f"profile_{profile_id}"
        slot = self.assign_abs_book_to_slot(
            slot_id=slot_id,
            abs_item_id=abs_item_id,
            owner_profile_id=profile_id,
            kind="profile_primary",
            mode=mode,
            base_url=base_url
        )

        # Record in media_playback_history for recent tier curation
        database.record_playback(abs_item_id, profile_id)
        return slot

    def assign_to_fleet_card(self, slot_id: str, abs_item_id: str,
                             mode_override: Optional[str] = None,
                             base_url: str = "") -> Dict[str, Any]:
        """Assigns an ABS book to a named fleet card slot."""
        mode = mode_override if mode_override and mode_override != "default" else "streaming"
        return self.assign_abs_book_to_slot(
            slot_id=slot_id,
            abs_item_id=abs_item_id,
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
