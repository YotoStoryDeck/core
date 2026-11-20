"""
Offline Transcoding Engine & Ephemeral Cache Pruner.
Handles background transcoding of Audiobookshelf audio into CBR MP3s,
uploads them to Yoto Cloud transcoding pipeline, saves offline playlists,
and executes LRU pruning of evicted profile caches while respecting pins and physical cards.
"""
from __future__ import annotations
import io
import time
import logging
import threading
from typing import Dict, Any, List, Optional
import database
import clients
from .manager import get_bridge_manager
from .streamer import AudioStreamer, AudioTrackSource

logger = logging.getLogger("storydeck.bridge.offline")


class OfflineTranscodeManager:
    """Manages background transcoding and upload jobs for offline Yoto cards."""

    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get_job_status(self, slot_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(slot_id)
            if not job:
                return None
            return dict(job)

    def is_busy(self, slot_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(slot_id)
            return bool(job and job.get("status") in ("queued", "encoding", "uploading", "processing"))

    def queue_transcode(self, slot_id: str, base_url: str = "") -> Dict[str, Any]:
        """Queues a card slot for offline transcoding and Yoto upload."""
        with self._lock:
            existing = self._jobs.get(slot_id)
            if existing and existing.get("status") in ("queued", "encoding", "uploading", "processing"):
                return existing

            job = {
                "slot_id": slot_id,
                "status": "queued",
                "progress": 0.0,
                "done": 0,
                "total": 0,
                "error": None,
                "started_at": time.time(),
                "updated_at": time.time()
            }
            self._jobs[slot_id] = job

        thread = threading.Thread(target=self._run_job, args=(slot_id, base_url), daemon=True)
        thread.start()
        return job

    def _run_job(self, slot_id: str, base_url: str):
        mgr = get_bridge_manager()
        slot = mgr.get_slot(slot_id)
        if not slot:
            self._update_job(slot_id, status="failed", error="Slot not found")
            return

        tracks = slot.get("tracks", [])
        if not tracks:
            self._update_job(slot_id, status="failed", error="Slot has no tracks")
            return

        total_tracks = len(tracks)
        self._update_job(slot_id, status="encoding", total=total_tracks, done=0, progress=0.0)

        # 1. Fetch ABS Item media sources
        abs_item_id = slot.get("abs_item_id")
        if not abs_item_id or not clients.abs_client:
            self._update_job(slot_id, status="failed", error="No ABS client or item configured")
            return

        try:
            item_data = clients.abs_client.get_item(abs_item_id)
        except Exception as e:
            logger.error("Failed to fetch ABS item %s for slot %s: %s", abs_item_id, slot_id, e)
            self._update_job(slot_id, status="failed", error=f"ABS item error: {e}")
            return

        media = (item_data or {}).get("media", {})
        audio_files = media.get("audioFiles", [])
        if not audio_files:
            self._update_job(slot_id, status="failed", error="ABS item has no audio files")
            return

        # Build AudioTrackSources
        sources: List[AudioTrackSource] = []
        c_offset = 0.0
        abs_token = clients.abs_client.token if hasattr(clients.abs_client, "token") else ""
        abs_base = clients.abs_client.base_url if hasattr(clients.abs_client, "base_url") else ""
        auth_hdr = f"Bearer {abs_token}" if abs_token else ""

        for af in audio_files:
            ino = af.get("ino") or af.get("id") or ""
            f_dur = float(af.get("duration") or 0.0)
            url = f"{abs_base}/api/items/{abs_item_id}/file/{ino}"
            sources.append(AudioTrackSource(url=url, start=c_offset, duration=f_dur))
            c_offset += f_dur

        streamer = AudioStreamer(bitrate_kbps=64, channels=1, sample_rate=44100)
        uploaded_tracks: List[Dict[str, Any]] = []

        conn = database.get_db_connection()
        try:
            for idx, trk in enumerate(tracks):
                track_idx = trk["track_idx"]
                start_sec = float(trk["start_time"])
                end_sec = float(trk["end_time"])
                trk_title = trk.get("title") or f"Track {track_idx}"
                sha = trk.get("yoto_sha256")

                # If already uploaded to Yoto, reuse sha
                if sha:
                    uploaded_tracks.append({
                        "track_idx": track_idx,
                        "title": trk_title,
                        "sha": sha,
                        "duration": end_sec - start_sec
                    })
                    self._update_job(slot_id, done=idx + 1, progress=(idx + 1) / total_tracks)
                    continue

                # Encode segment
                self._update_job(slot_id, status="encoding", done=idx, progress=idx / total_tracks)
                audio_buffer = bytearray()
                for chunk in streamer.stream_segment(sources, start_sec, end_sec, auth_header=auth_hdr):
                    audio_buffer.extend(chunk)

                # Upload to Yoto Cloud
                if not clients.yoto_client:
                    raise RuntimeError("Yoto client is not configured")

                self._update_job(slot_id, status="uploading")
                up_info = clients.yoto_client.upload_audio(
                    bytes(audio_buffer),
                    title=f"{slot.get('title', 'Book')} - {trk_title}",
                    on_phase=lambda ph: self._update_job(slot_id, status=ph)
                )

                sha = up_info.get("sha")
                if not sha:
                    raise RuntimeError(f"Yoto upload failed to return sha for track {track_idx}")

                # Save sha in database
                with conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE bridge_tracks SET yoto_sha256 = ? WHERE slot_id = ? AND track_idx = ?;",
                                (sha, slot_id, track_idx))

                uploaded_tracks.append({
                    "track_idx": track_idx,
                    "title": trk_title,
                    "sha": sha,
                    "duration": up_info.get("duration") or (end_sec - start_sec),
                    "fileSize": up_info.get("fileSize") or len(audio_buffer)
                })

                self._update_job(slot_id, done=idx + 1, progress=(idx + 1) / total_tracks)

            # 2. Save full offline playlist to Yoto Cloud
            cover_url = f"{base_url}/api/cover/{abs_item_id}" if base_url else ""
            yoto_card_id = slot.get("yoto_card_id") or slot_id
            saved_cid = clients.yoto_client.save_track_playlist(
                title=slot.get("title", "Audiobook"),
                tracks=uploaded_tracks,
                card_id=yoto_card_id,
                cover_url=cover_url,
                description=f"Offline audiobook: {slot.get('title', '')} by {slot.get('author', '')}"
            )

            # Update slot status
            with conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE bridge_slots
                    SET mode = 'offline', yoto_card_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE slot_id = ?;
                """, (saved_cid or yoto_card_id, slot_id))

            self._update_job(slot_id, status="ready", progress=1.0, done=total_tracks)
            logger.info("Successfully finished offline transcode and upload for slot %s (cardId: %s)", slot_id, saved_cid)

        except Exception as e:
            logger.error("Error during offline transcode/upload for slot %s: %s", slot_id, e)
            self._update_job(slot_id, status="failed", error=str(e))
        finally:
            conn.close()

    def _update_job(self, slot_id: str, **kwargs):
        with self._lock:
            if slot_id in self._jobs:
                self._jobs[slot_id].update(kwargs)
                self._jobs[slot_id]["updated_at"] = time.time()


_offline_manager: Optional[OfflineTranscodeManager] = None

def get_offline_manager() -> OfflineTranscodeManager:
    global _offline_manager
    if _offline_manager is None:
        _offline_manager = OfflineTranscodeManager()
    return _offline_manager


def prune_evicted_profile_playlists() -> Dict[str, Any]:
    """
    Automated LRU Cache Pruner for ephemeral profile playlists.
    Follows profile offline_retention_limit and recent_tier curation rules.
    Strictly preserves:
    - Pinned playlists (is_pinned = 1 or is_protected = 1)
    - Permanent MYO / fleet cards (kind = 'permanent_myo')
    - Custom user-uploaded playlists
    """
    pruned_count = 0
    pruned_items = []

    profiles = database.get_all_profiles()
    conn = database.get_db_connection()
    try:
        cur = conn.cursor()
        for p_id, p_cfg in profiles.items():
            retention_limit = int(p_cfg.get("offline_retention_limit", 8) or 8)
            playback_history = database.get_playback_history(p_id)

            # Sort recent items descending by last played time
            sorted_recent = sorted(playback_history.items(), key=lambda kv: kv[1], reverse=True)
            active_recent_ids = {book_id for book_id, _ in sorted_recent[:retention_limit]}

            # Query ephemeral slots belonging to this profile
            cur.execute("""
                SELECT slot_id, abs_item_id, title, is_pinned, is_protected, kind, yoto_card_id
                FROM bridge_slots
                WHERE owner_profile_id = ? AND kind = 'ephemeral_offline';
            """, (p_id,))
            candidate_slots = cur.fetchall()

            for s in candidate_slots:
                slot_id = s["slot_id"]
                book_id = s["abs_item_id"]
                yoto_cid = s["yoto_card_id"] or slot_id

                # Never prune pinned or protected playlists
                if s["is_pinned"] or s["is_protected"]:
                    continue

                # Evict if book is no longer in active recent list
                if book_id not in active_recent_ids:
                    logger.info("Pruning evicted offline playlist: %s (slot: %s, profile: %s)", s["title"], slot_id, p_id)
                    # Delete from Yoto Cloud
                    if clients.yoto_client:
                        try:
                            clients.yoto_client.delete_playlist(yoto_cid)
                        except Exception as e:
                            logger.warning("Failed to delete Yoto Cloud playlist %s: %s", yoto_cid, e)

                    # Delete slot and tracks from DB
                    with conn:
                        sub_cur = conn.cursor()
                        sub_cur.execute("DELETE FROM bridge_slots WHERE slot_id = ?;", (slot_id,))
                        sub_cur.execute("DELETE FROM bridge_tracks WHERE slot_id = ?;", (slot_id,))

                    pruned_count += 1
                    pruned_items.append({"slot_id": slot_id, "title": s["title"], "profile_id": p_id})

    finally:
        conn.close()

    return {
        "pruned_count": pruned_count,
        "pruned_items": pruned_items,
        "timestamp": time.time()
    }
