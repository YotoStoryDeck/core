"""
Unit and integration tests for Phase 2 deliverables (DLP-023 & DLP-019):
- Ephemeral profile_cache archiving on offline primary card switches & warm cache reuse
- Automated LRU cache pruner across profile_cache / ephemeral_offline slots with atomic whole-series retention
- ffmpeg silencedetect + QuietSpots pause snapping on non-chapter track boundaries
- Yoto lastPlayedAt & ABS user mediaProgress.lastUpdate ingestion + scheduled LRU pruning
- Daily wall-clock catalog rotation trigger based on profile catalog_rotation_hour
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import app  # noqa: F401 - ensures full app/blueprint wiring initializes cleanly
import clients
import database
import core.scheduler as scheduler
from core.bridge.chapters import chapter_spans
from core.bridge.manager import BridgeManager
from core.bridge.offline import prune_evicted_profile_playlists
from core.bridge.quiet import QuietSpots
from core.bridge.streamer import AudioStreamer, AudioTrackSource


class TestPhase2PrunerQuietScheduler(unittest.TestCase):
    def setUp(self):
        self._orig_settings = database.get_system_settings()
        self._orig_rot_dates = self._orig_settings.get("profile_last_rotation_dates")
        self._cleanup_test_rows()

    def tearDown(self):
        self._cleanup_test_rows()
        if self._orig_rot_dates is not None:
            database.set_system_setting("profile_last_rotation_dates", self._orig_rot_dates)
        else:
            conn = database.get_db_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM system_settings WHERE key = 'profile_last_rotation_dates';")
            finally:
                conn.close()

    def _cleanup_test_rows(self):
        database.delete_profile("phase2_kid")
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM bridge_tracks WHERE slot_id LIKE '%phase2%';")
                conn.execute(
                    "DELETE FROM bridge_slots WHERE slot_id LIKE '%phase2%' "
                    "OR abs_item_id LIKE 'phase2_%' OR owner_profile_id = 'phase2_kid';"
                )
                conn.execute("DELETE FROM media_playback_history WHERE profile_id = 'phase2_kid' OR media_id LIKE 'phase2_%';")
                conn.execute("DELETE FROM media_items WHERE id LIKE 'phase2_%';")
        finally:
            conn.close()

    def test_profile_primary_offline_switch_archives_profile_cache(self):
        """Switching a profile primary offline book archives the previous book as profile_cache and preserves SHAs."""
        database.upsert_profile("phase2_kid", {
            "display_name": "Phase2 Kid",
            "default_playback_mode": "offline",
            "offline_retention_limit": 2,
            "yoto": {"inherit_shared": False}
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = BridgeManager()
            mgr.quiet_spots = QuietSpots(tmpdir)

            fake_item_1 = {
                "id": "phase2_book_1",
                "media": {
                    "duration": 600.0,
                    "chapters": [
                        {"start": 0.0, "end": 300.0, "title": "Ch 1"},
                        {"start": 300.0, "end": 600.0, "title": "Ch 2"},
                    ],
                    "metadata": {"title": "Book One", "authorName": "Author A", "seriesName": "Phase2 Series"}
                }
            }
            fake_item_2 = {
                "id": "phase2_book_2",
                "media": {
                    "duration": 400.0,
                    "chapters": [{"start": 0.0, "end": 400.0, "title": "Part 1"}],
                    "metadata": {"title": "Book Two", "authorName": "Author B"}
                }
            }

            with patch.object(clients.abs_client, "get_item", side_effect=lambda bid: fake_item_1 if bid == "phase2_book_1" else fake_item_2):
                slot1 = mgr.update_profile_primary_card("phase2_kid", "phase2_book_1", mode_override="offline")
                self.assertEqual(slot1["slot_id"], "profile_phase2_kid")
                self.assertEqual(slot1["kind"], "profile_primary")
                self.assertEqual(slot1["mode"], "offline")

                # Simulate completed offline upload metadata on primary slot
                conn = database.get_db_connection()
                try:
                    with conn:
                        conn.execute(
                            "UPDATE bridge_slots SET yoto_card_id = 'yoto_card_b1', offline_status = 'ready' "
                            "WHERE slot_id = 'profile_phase2_kid';"
                        )
                        conn.execute(
                            "UPDATE bridge_tracks SET yoto_sha256 = 'sha_track_1' "
                            "WHERE slot_id = 'profile_phase2_kid' AND track_idx = 1;"
                        )
                finally:
                    conn.close()

                # Switch primary card to book 2
                slot2 = mgr.update_profile_primary_card("phase2_kid", "phase2_book_2", mode_override="offline")
                self.assertEqual(slot2["abs_item_id"], "phase2_book_2")
                self.assertNotEqual(slot2.get("yoto_card_id"), "yoto_card_b1")

                # Verify old book was archived into profile_cache with SHAs and unpinned state
                archived = mgr.get_slot("cache_phase2_kid_phase2_book_1")
                self.assertIsNotNone(archived)
                self.assertEqual(archived["kind"], "profile_cache")
                self.assertEqual(archived["is_protected"], 0)
                self.assertEqual(archived["is_pinned"], 0)
                self.assertEqual(archived["yoto_card_id"], "yoto_card_b1")
                self.assertEqual(archived["tracks"][0]["yoto_sha256"], "sha_track_1")

                # Switching back to book 1 warms SHAs from archive
                slot_back = mgr.update_profile_primary_card("phase2_kid", "phase2_book_1", mode_override="offline")
                self.assertEqual(slot_back["tracks"][0]["yoto_sha256"], "sha_track_1")

    def test_lru_pruner_handles_profile_cache_and_atomic_whole_series_retention(self):
        """LRU pruner queries profile_cache slots and preserves sister books of series in the recent tier."""
        database.upsert_profile("phase2_kid", {
            "display_name": "Phase2 Kid",
            "default_playback_mode": "offline",
            "offline_retention_limit": 1,
            "yoto": {"inherit_shared": False}
        })

        database.upsert_media_items([
            {
                "id": "phase2_ser_1",
                "type": "abs",
                "title": "Wizards #1",
                "raw_metadata": {"series": "Phase2 Wizards", "series_list": [{"name": "Phase2 Wizards", "order": "1"}]}
            },
            {
                "id": "phase2_ser_2",
                "type": "abs",
                "title": "Wizards #2",
                "raw_metadata": {"series": "Phase2 Wizards", "series_list": [{"name": "Phase2 Wizards", "order": "2"}]}
            },
            {
                "id": "phase2_old_standalone",
                "type": "abs",
                "title": "Standalone Old Book",
                "raw_metadata": {}
            }
        ])

        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO bridge_slots (
                        slot_id, abs_item_id, yoto_card_id, owner_profile_id, title,
                        series_name, kind, mode, is_pinned, is_protected
                    ) VALUES (
                        'cache_phase2_kid_ser2', 'phase2_ser_2', 'yoto_ser2', 'phase2_kid',
                        'Wizards #2', 'Phase2 Wizards', 'profile_cache', 'offline', 0, 0
                    );
                """)
                conn.execute("""
                    INSERT INTO bridge_slots (
                        slot_id, abs_item_id, yoto_card_id, owner_profile_id, title,
                        series_name, kind, mode, is_pinned, is_protected
                    ) VALUES (
                        'cache_phase2_kid_old', 'phase2_old_standalone', 'yoto_old_1', 'phase2_kid',
                        'Standalone Old Book', '', 'profile_cache', 'offline', 0, 0
                    );
                """)
        finally:
            conn.close()

        # Newer timestamp for Wizards #1 (within retention_limit=1), older for others
        database.record_playback("phase2_ser_1", "phase2_kid", "2026-11-20T12:00:00+00:00")
        database.record_playback("phase2_ser_2", "phase2_kid", "2026-11-18T12:00:00+00:00")
        database.record_playback("phase2_old_standalone", "phase2_kid", "2026-11-15T12:00:00+00:00")

        with patch.object(clients.yoto_client, "delete_playlist", return_value=True) as mock_del:
            res = prune_evicted_profile_playlists()
            evicted_slots = {p["slot_id"] for p in res["pruned_items"]}
            self.assertIn("cache_phase2_kid_old", evicted_slots)
            self.assertNotIn("cache_phase2_kid_ser2", evicted_slots)
            mock_del.assert_any_call("yoto_old_1")

        mgr = BridgeManager()
        self.assertIsNone(mgr.get_slot("cache_phase2_kid_old"))
        self.assertIsNotNone(mgr.get_slot("cache_phase2_kid_ser2"))

    def test_ffmpeg_silencedetect_and_quiet_spots_snapping(self):
        """Real ffmpeg silencedetect populates QuietSpots and snaps non-chapter track cuts."""
        ffmpeg_bin = shutil.which("ffmpeg")
        self.assertIsNotNone(ffmpeg_bin, "ffmpeg binary must be available for silence detection tests")

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = str(Path(tmpdir) / "tone_pause_tone.wav")
            cmd = [
                ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2.0",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1.0",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2.0",
                "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
                "-map", "[out]", wav_path
            ]
            subprocess.run(cmd, check=True)

            src = AudioTrackSource(url=wav_path, start=0.0, duration=5.0)
            streamer = AudioStreamer(ffmpeg_bin=ffmpeg_bin)
            spots = streamer.detect_quiet_spots([src], 0.0, 5.0)
            self.assertTrue(any(s <= 2.2 and e >= 2.8 for s, e in spots), f"Expected ~2.0-3.0s pause, got {spots}")

            qs = QuietSpots(tmpdir)
            scanned = qs.scan_windows("phase2_audio_book", [2.2], [src], streamer=streamer)
            self.assertEqual(scanned, 1)

            qs_reloaded = QuietSpots(tmpdir)
            snap = qs_reloaded.snapper("phase2_audio_book")
            self.assertIsNotNone(snap)
            snapped_cut = snap(2.2)
            self.assertGreaterEqual(snapped_cut, 2.3)
            self.assertLessEqual(snapped_cut, 2.7)

            # Verify BridgeManager passes snapper into chapter_spans during assign_abs_book_to_slot
            mgr = BridgeManager()
            mgr.quiet_spots = QuietSpots(tmpdir)
            long_book = {
                "id": "phase2_snap_book",
                "media": {
                    "duration": 5400.0,
                    "chapters": [],
                    "audioFiles": [{"ino": "1", "duration": 5400.0, "local_path": wav_path}],
                    "metadata": {"title": "Long Unchaptered Book", "authorName": "Author"}
                }
            }

            def _fake_detect(sources, start_sec, end_sec, **kwargs):
                mid = (start_sec + end_sec) / 2.0
                if abs(mid - 1800.0) < 25.0:
                    return [(1804.0, 1806.0)]
                if abs(mid - 3600.0) < 25.0:
                    return [(3593.0, 3595.0)]
                return []

            with patch.object(clients.abs_client, "get_item", return_value=long_book), \
                 patch.object(AudioStreamer, "detect_quiet_spots", side_effect=_fake_detect):
                slot = mgr.assign_abs_book_to_slot(
                    slot_id="phase2_snap_slot",
                    abs_item_id="phase2_snap_book",
                    scan_quiet_sync=True
                )
                self.assertEqual(slot["tracks"][0]["end_time"], 1805.0)
                self.assertEqual(slot["tracks"][1]["start_time"], 1805.0)
                self.assertEqual(slot["tracks"][1]["end_time"], 3594.0)

    def test_yoto_last_played_at_and_abs_progress_scheduled_sync(self):
        """perform_library_refresh() ingests Yoto lastPlayedAt, syncs ABS mediaProgress, and invokes LRU pruner."""
        database.upsert_profile("phase2_kid", {
            "display_name": "Phase2 Kid",
            "abs_username": "phase2_abs_user",
            "yoto": {"inherit_shared": False}
        })

        mock_yoto_raw = [{
            "cardId": "phase2_yoto_card",
            "id": "phase2_yoto_card",
            "title": "Phase2 Story Card",
            "author": "Yoto",
            "lastPlayedAt": "2026-11-19T12:00:00Z"
        }]
        # 1795000000000 ms -> 2026-11-18T... UTC
        expected_abs_iso = datetime.fromtimestamp(1795000000.0, timezone.utc).isoformat()

        with patch.object(clients.yoto_client, "get_groups", return_value=[]), \
             patch.object(clients.yoto_client, "get_raw_library", return_value=mock_yoto_raw), \
             patch.object(clients.abs_client, "get_libraries", return_value=[]), \
             patch.object(clients.abs_client, "get_all_users", return_value=[{"id": "u_p2", "username": "phase2_abs_user"}]), \
             patch.object(clients.abs_client, "get_user_media_progress", return_value=[{"libraryItemId": "phase2_abs_book", "lastUpdate": 1795000000000}]), \
             patch("database.prune_stale_media_items", return_value=0), \
             patch("core.image_resizer.prune_orphan_thumbnails", return_value=0), \
             patch("core.bridge.offline.prune_evicted_profile_playlists", return_value={"pruned_count": 0, "pruned_items": []}) as mock_prune:

            count = scheduler.perform_library_refresh()
            self.assertEqual(count, 1)
            mock_prune.assert_called_once()

        hist = database.get_playback_history("phase2_kid")
        self.assertEqual(hist.get("phase2_yoto_card"), "2026-11-19T12:00:00+00:00")
        self.assertEqual(hist.get("phase2_abs_book"), expected_abs_iso)

    def test_daily_wall_clock_rotation_trigger(self):
        """Daily wall-clock rotation triggers once per day once local hour reaches catalog_rotation_hour."""
        database.upsert_profile("phase2_kid", {
            "display_name": "Phase2 Kid",
            "catalog_rotation_hour": 4,
            "yoto": {"inherit_shared": False}
        })

        last_dates = dict(database.get_system_settings().get("profile_last_rotation_dates") or {})
        last_dates.pop("phase2_kid", None)
        database.set_system_setting("profile_last_rotation_dates", last_dates)

        with patch.object(scheduler, "perform_library_refresh", return_value=0):
            # Before 04:00 -> not due
            due_early = scheduler._check_daily_profile_rotations(datetime(2026, 11, 20, 3, 59))
            self.assertNotIn("phase2_kid", due_early)

            # At 04:00 -> due once
            due_now = scheduler._check_daily_profile_rotations(datetime(2026, 11, 20, 4, 0))
            self.assertIn("phase2_kid", due_now)

            # Later same day -> already ran today (idempotent)
            due_later = scheduler._check_daily_profile_rotations(datetime(2026, 11, 20, 5, 0))
            self.assertNotIn("phase2_kid", due_later)


if __name__ == "__main__":
    unittest.main()
