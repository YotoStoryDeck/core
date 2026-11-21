"""
Unit and integration tests for Phase 3 deliverables (DLP-023 Standalone Parity):
- Embedded YotoMqttBridge (EventPatch, StatusPatch, PresenceEvent ingestion & control commands)
- core/player_service.py standalone/direct mode merging MQTT + PlaybackSession telemetry
- PlaybackManager byte/time/MQTT/speed position calculation, per-child ABS tokens, own_place bypass, 404 fallback
- /s/audio/<slot_id>/<track_idx> streaming endpoint recording bytes & syncing ABS progress on close
- GET /api/bridge/mqtt/status telemetry endpoint
"""
import tests.test_isolation  # noqa: F401 - must precede app/database/clients imports
import enum
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from app import app
import clients
import database
import core.player_service as player_service
from core.bridge.manager import get_bridge_manager
from core.bridge.mqtt_client import YotoMqttBridge
from core.bridge.playback import PlaybackManager, get_playback_manager
from core.bridge.streamer import AudioStreamer


class _FakePlaybackStatus(enum.Enum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"


class PresenceEvent:
    def __init__(self, player_id: str, is_online: bool):
        self.player_id = player_id
        self.is_online = is_online


class EventPatch:
    def __init__(self, player_id: str, **fields):
        self.player_id = player_id
        self.fields = fields


class StatusPatch:
    def __init__(self, player_id: str, **fields):
        self.player_id = player_id
        self.fields = fields


class TestPhase3MqttPlayback(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self._orig_creds = database.get_api_credentials()
        self._cleanup()
        player_service._cards_cache = []
        player_service._cards_cache_ts = 0.0
        player_service._cached_players_map = {}
        player_service._cached_players_ts = 0.0
        get_playback_manager()._sessions.clear()

    def tearDown(self):
        database.update_api_credentials(self._orig_creds)
        clients.reload_clients()
        get_playback_manager()._sessions.clear()
        self._cleanup()

    def _cleanup(self):
        database.delete_profile("p3_kid")
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM bridge_tracks WHERE slot_id LIKE '%p3%';")
                conn.execute("DELETE FROM bridge_slots WHERE slot_id LIKE '%p3%' OR abs_item_id LIKE 'abs_p3_%';")
                conn.execute("DELETE FROM media_items WHERE id LIKE 'abs_p3_%' OR id LIKE 'card_p3%';")
                conn.execute("DELETE FROM media_playback_history WHERE profile_id = 'p3_kid' OR media_id LIKE 'abs_p3_%';")
        finally:
            conn.close()

    def test_mqtt_event_status_presence_and_card_removal(self):
        """YotoMqttBridge parses PresenceEvent, EventPatch, StatusPatch, and card removal cleanly."""
        bridge = YotoMqttBridge()
        events_seen = []
        presence_seen = []
        bridge.add_event_listener(lambda did, ev: events_seen.append((did, ev)))
        bridge.add_presence_listener(lambda did, online: presence_seen.append((did, online)))

        bridge.handle_message(PresenceEvent("dev_1", True))
        self.assertEqual(presence_seen[-1], ("dev_1", True))
        self.assertTrue(bridge.get_device_state("dev_1")["online"])

        bridge.handle_message(EventPatch(
            "dev_1",
            card_id="card_abc",
            position=42,
            track_length=300,
            playback_status=_FakePlaybackStatus.PLAYING,
            chapter_key="02",
            track_key="02",
            chapter_title="Into the Woods",
            volume=45,
            volume_max=65,
        ))
        bridge.handle_message(StatusPatch(
            "dev_1",
            user_volume_percentage=50,
            day_mode=0,
            battery_level_percentage=88,
            charging=True,
        ))

        st = bridge.get_device_state("dev_1")
        self.assertEqual(st["cardId"], "card_abc")
        self.assertEqual(st["playbackStatus"], "playing")
        self.assertEqual(st["chapterTitle"], "Into the Woods")
        self.assertEqual(st["volume"], 50)
        self.assertEqual(st["volume_max"], 65)
        self.assertEqual(st["day_mode"], 0)
        self.assertEqual(st["battery_level_percentage"], 88)
        self.assertTrue(st["charging"])
        self.assertGreaterEqual(len(events_seen), 2)

        # Card removed -> clears active card fields and sets stopped
        bridge.handle_message(EventPatch("dev_1", card_id="none", playback_status="stopped"))
        st_after = bridge.get_device_state("dev_1")
        self.assertNotIn("cardId", st_after)
        self.assertEqual(st_after["playbackStatus"], "stopped")

        bridge.handle_message(PresenceEvent("dev_1", False))
        self.assertFalse(bridge.get_device_state("dev_1")["online"])

    def test_player_service_direct_mode_merges_mqtt_and_dispatches_controls(self):
        """player_service merges live MQTT telemetry in direct mode and routes transport commands."""
        database.upsert_media_items([{
            "id": "abs_p3_item",
            "type": "abs",
            "title": "Phase 3 Book",
            "author": "Author P3",
            "cover_url": "/api/thumb?type=abs&id=abs_p3_item",
            "raw_metadata": {}
        }])

        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO bridge_slots (slot_id, abs_item_id, yoto_card_id, title, author, kind, mode, total_duration)
                    VALUES ('slot_p3_1', 'abs_p3_item', 'card_p3', 'Phase 3 Book', 'Author P3', 'permanent_myo', 'streaming', 600.0);
                """)
        finally:
            conn.close()

        test_mqtt = YotoMqttBridge()
        test_mqtt.handle_message(EventPatch(
            "dev_p3",
            card_id="card_p3",
            position=45,
            track_length=600,
            playback_status="playing",
            chapter_key="02",
            track_key="02",
            chapter_title="Ch 2",
            volume=40,
            volume_max=60,
        ))
        test_mqtt.handle_message(StatusPatch(
            "dev_p3",
            day_mode=0,
            battery_level_percentage=82,
            charging=True,
        ))

        with patch("core.bridge.mqtt_client.get_mqtt_bridge", return_value=test_mqtt), \
             patch.object(clients.yoto_client, "get_devices", return_value=[{"deviceId": "dev_p3", "name": "Direct Kid Player", "online": True}]):
            players = player_service.get_live_players_map(force_refresh=True)
            self.assertIn("dev_p3", players)
            p = players["dev_p3"]
            self.assertTrue(p["is_playing"])
            self.assertEqual(p["card_id"], "card_p3")
            self.assertEqual(p["slot_id"], "slot_p3_1")
            self.assertEqual(p["title"], "Phase 3 Book")
            self.assertEqual(p["chapter_title"], "Ch 2")
            self.assertEqual(p["day_mode"], 0)
            self.assertEqual(p["battery"], 82)
            self.assertTrue(p["charging"])
            self.assertEqual(p["volume"], 40)
            self.assertEqual(p["volume_max"], 60)

            with patch.object(YotoMqttBridge, "is_connected", new_callable=PropertyMock, return_value=True), \
                 patch.object(test_mqtt, "set_volume", return_value=True) as mock_vol, \
                 patch.object(test_mqtt, "pause", return_value=True) as mock_pause, \
                 patch.object(test_mqtt, "resume", return_value=True) as mock_resume, \
                 patch.object(test_mqtt, "play", return_value=True) as mock_play:

                ok, res, code = player_service.dispatch_player_control("dev_p3", "volume", volume=80)
                self.assertTrue(ok)
                self.assertEqual(code, 200)
                self.assertEqual(res["volume"], 60)  # Clamped to volume_max=60
                mock_vol.assert_called_once_with("dev_p3", 60)

                ok, _, _ = player_service.dispatch_player_control("dev_p3", "pause")
                self.assertTrue(ok)
                mock_pause.assert_called_once_with("dev_p3")

                ok, _, _ = player_service.dispatch_player_control("dev_p3", "resume")
                self.assertTrue(ok)
                mock_resume.assert_called_once_with("dev_p3")

                ok, _, _ = player_service.dispatch_player_control("dev_p3", "seek", position=120)
                self.assertTrue(ok)
                mock_play.assert_any_call("dev_p3", "card_p3", seconds_in=120)

                ok, _, _ = player_service.dispatch_player_control("dev_p3", "back30")
                self.assertTrue(ok)
                mock_play.assert_any_call("dev_p3", "card_p3", seconds_in=15)

                ok, _, _ = player_service.dispatch_player_control("dev_p3", "fwd30")
                self.assertTrue(ok)
                mock_play.assert_any_call("dev_p3", "card_p3", seconds_in=75)

                ok, _, _ = player_service.dispatch_player_control("dev_p3", "next")
                self.assertTrue(ok)
                mock_play.assert_any_call("dev_p3", "card_p3", track=3)

    def test_playback_manager_position_speed_pause_and_abs_sync(self):
        """PlaybackManager tracks bytes, speed scaling, pauses, per-profile ABS tokens, and finish state."""
        database.upsert_profile("p3_kid", {
            "display_name": "P3 Kid",
            "abs_username": "kid_abs_user",
            "default_player_id": "dev_p3",
            "yoto": {"inherit_shared": False}
        })

        pb_mgr = PlaybackManager(sync_interval=15.0, end_grace_seconds=15.0, player_buffer_seconds=8.0)
        slot = {
            "slot_id": "slot_p3_pb",
            "abs_item_id": "abs_p3_book",
            "yoto_card_id": "card_p3_pb",
            "owner_profile_id": "p3_kid",
            "title": "P3 Audio",
            "total_duration": 1200.0,
            "own_place": 0,
        }
        track = {"track_idx": 1, "start_time": 100.0, "end_time": 1000.0}

        with patch.object(clients.abs_client, "get_user_token", return_value="kid_tok_xyz"), \
             patch.object(clients.abs_client, "start_playback_session", return_value={"id": "abs_sess_1"}), \
             patch.object(clients.abs_client, "sync_playback_session", return_value=(True, 200)) as mock_sync, \
             patch.object(clients.abs_client, "patch_media_progress", return_value=True) as mock_patch, \
             patch.object(clients.abs_client, "close_playback_session", return_value=True) as mock_close, \
             patch.object(clients.abs_client, "get_media_progress", return_value=None):

            sess = pb_mgr.open_stream(slot, track, byte_start=0, speed=1.5, byterate=8000.0, device_id="dev_p3")
            self.assertEqual(sess.abs_token, "kid_tok_xyz")
            self.assertEqual(sess.abs_session_id, "abs_sess_1")
            self.assertEqual(sess.base, 100.0)

            # Deliver 160,000 bytes (at 1.5x, rate = 5333.33 bytes/book_sec -> 30.0s book audio)
            pb_mgr.record_bytes(sess, 160000)
            now_m = time.monotonic()
            sess.started_at = now_m - 20.0
            sess.last_sync_at = now_m - 20.0
            # Without MQTT events: cap = 100 + min(30, 20*1.5) = 130; minus buffer lag (8*1.5 = 12) -> 118.0
            self.assertAlmostEqual(pb_mgr.compute_position(sess, now_mono=now_m), 118.0, places=1)

            # MQTT playing event reduces startup lag and bounds against delivered cap
            pb_mgr.on_mqtt_event("dev_p3", {"cardId": "card_p3_pb", "playbackStatus": "playing", "position": 10})
            pos_with_mqtt = pb_mgr.compute_position(sess)
            self.assertGreaterEqual(pos_with_mqtt, 114.0)
            self.assertLessEqual(pos_with_mqtt, 130.5)

            # sync_session pushes using kid_tok_xyz
            self.assertTrue(pb_mgr.sync_session(sess, force=True))
            mock_sync.assert_called()
            self.assertEqual(mock_sync.call_args.kwargs.get("token"), "kid_tok_xyz")

            # MQTT pause triggers immediate sync and freezes active clock
            pb_mgr.on_mqtt_event("dev_p3", {"cardId": "card_p3_pb", "playbackStatus": "paused"})
            self.assertIsNotNone(sess.paused_at)

            # HTTP 404 from /api/session/{id}/sync falls back to PATCH /api/me/progress/{id}
            mock_sync.return_value = (False, 404)
            sess.bytes_sent += 80000
            self.assertTrue(pb_mgr.sync_session(sess, force=True))
            mock_patch.assert_called()

            # own_place=1 suppresses ABS updates
            sess.own_place = True
            self.assertFalse(pb_mgr.sync_session(sess, force=True))
            sess.own_place = False

            # Finish near end of book triggers close_playback_session + mark finished
            sess.track_end = 1200.0
            sess.base = 1190.0
            sess.bytes_sent = 80000
            sess.started_at = time.monotonic() - 15.0
            mock_patch.reset_mock()
            self.assertTrue(pb_mgr.finish_session("slot_p3_pb", "done"))
            mock_close.assert_called_once()
            mock_patch.assert_called_with("abs_p3_book", 1200.0, 1200.0, is_finished=True, token="kid_tok_xyz")

    def test_stream_audio_endpoint_records_bytes_and_syncs_on_close(self):
        """GET /s/audio/<slot_id>/1 records delivered bytes and flushes progress to ABS on stream close."""
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO bridge_slots (slot_id, abs_item_id, yoto_card_id, title, kind, mode, total_duration, own_place)
                    VALUES ('slot_p3_stream', 'abs_p3_sbook', 'card_p3_s', 'Stream Test Book', 'permanent_myo', 'streaming', 60.0, 0);
                """)
                conn.execute("""
                    INSERT INTO bridge_tracks (slot_id, track_idx, title, start_time, end_time, duration, stream_url)
                    VALUES ('slot_p3_stream', 1, 'Chapter 1', 0.0, 60.0, 60.0, '/s/audio/slot_p3_stream/1');
                """)
        finally:
            conn.close()

        fake_item = {
            "id": "abs_p3_sbook",
            "media": {
                "duration": 60.0,
                "audioFiles": [{"ino": "1", "duration": 60.0}]
            }
        }

        with patch.object(clients.abs_client, "get_item", return_value=fake_item), \
             patch.object(clients.abs_client, "start_playback_session", return_value={"id": "sess_s1"}) as mock_start, \
             patch.object(clients.abs_client, "sync_playback_session", return_value=(True, 200)) as mock_sync, \
             patch.object(clients.abs_client, "patch_media_progress", return_value=True), \
             patch.object(clients.abs_client, "get_media_progress", return_value=None), \
             patch.object(AudioStreamer, "stream_segment", return_value=iter([b"A" * 8000, b"B" * 8000])):

            res = self.app.get(
                "/s/audio/slot_p3_stream/1",
                headers={"Range": "bytes=0-15999"},
                environ_base={"REMOTE_ADDR": "192.168.1.100"}
            )
            body = res.data
            self.assertEqual(res.status_code, 206)
            self.assertEqual(len(body), 16000)
            mock_start.assert_called_once()
            mock_sync.assert_called()

    def test_bridge_mqtt_status_endpoint(self):
        """Verifies GET /api/bridge/mqtt/status returns MQTT bridge & session status."""
        res = self.app.get("/api/bridge/mqtt/status", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("mqtt", data)
        self.assertIn("active_sessions", data)
        self.assertIsInstance(data["active_sessions"], list)

    def test_windows_selector_event_loop(self):
        """_create_event_loop returns SelectorEventLoop on win32 for aiomqtt add_reader/add_writer support."""
        import asyncio
        from core.bridge.mqtt_client import _create_event_loop

        with patch("core.bridge.mqtt_client.sys.platform", "win32"):
            loop = _create_event_loop()
            try:
                self.assertIsInstance(loop, asyncio.SelectorEventLoop)
            finally:
                loop.close()

    def test_hardware_volume_0_16_conversion_and_cap_propagation(self):
        """Raw 0-16 MQTT volume & volume_max convert to 0-100% and update YotoMqttClient cap."""
        bridge = YotoMqttBridge()
        mock_client = MagicMock()
        mock_client.is_connected = True
        bridge._client = mock_client
        bridge._loop = MagicMock(is_running=MagicMock(return_value=True))

        # 8/16 -> 50% (Wesley's night cap case)
        bridge.handle_message(EventPatch("dev_w", volume=8, volume_max=8))
        st_w = bridge.get_device_state("dev_w")
        self.assertEqual(st_w["volume"], 50)
        self.assertEqual(st_w["volume_max"], 50)
        self.assertEqual(st_w["volume_max_raw"], 8)
        mock_client.set_volume_max.assert_called_with("dev_w", 8)

        # 6/16 -> 38%, 12/16 -> 75%
        bridge.handle_message(EventPatch("dev_d", volume=6, volume_max=12))
        st_d = bridge.get_device_state("dev_d")
        self.assertEqual(st_d["volume"], 38)
        self.assertEqual(st_d["volume_max"], 75)

        # 16/16 -> 100%, 2/16 -> 13%
        bridge.handle_message(EventPatch("dev_full", volume=2, volume_max=16))
        st_f = bridge.get_device_state("dev_full")
        self.assertEqual(st_f["volume"], 13)
        self.assertEqual(st_f["volume_max"], 100)

        # set_volume delegates to client.set_volume(device_id, vol)
        coro_sentinel = object()
        mock_client.set_volume.return_value = coro_sentinel
        with patch.object(bridge, "_dispatch_coro", return_value=True) as mock_disp:
            ok = bridge.set_volume("dev_w", 45)
        self.assertTrue(ok)
        mock_client.set_volume.assert_called_once_with("dev_w", 45)
        mock_disp.assert_called_once_with(coro_sentinel)

    def test_player_service_config_fallback_for_volume_cap(self):
        """player_service falls back to /device-v2/{id}/config day/night cap when MQTT volume_max is missing."""
        test_mqtt = YotoMqttBridge()
        test_mqtt.handle_message(StatusPatch("dev_cfg_night", day_mode=0, battery_level_percentage=95))

        with patch("core.bridge.mqtt_client.get_mqtt_bridge", return_value=test_mqtt), \
             patch.object(clients.yoto_client, "get_devices", return_value=[{"deviceId": "dev_cfg_night", "name": "Wesley", "online": True}]), \
             patch.object(clients.yoto_client, "get_device_config", return_value={"maxVolumeLimit": "12", "nightMaxVolumeLimit": "8"}):
            players = player_service.get_live_players_map(force_refresh=True)

        p = players["dev_cfg_night"]
        self.assertEqual(p["volume_max"], 50)
        self.assertEqual(p["volume"], 50)  # Default 50 fits within cap=50

        # Day mode -> uses maxVolumeLimit=12 -> 75%
        test_mqtt_day = YotoMqttBridge()
        test_mqtt_day.handle_message(StatusPatch("dev_cfg_day", day_mode=1, battery_level_percentage=90))
        with patch("core.bridge.mqtt_client.get_mqtt_bridge", return_value=test_mqtt_day), \
             patch.object(clients.yoto_client, "get_devices", return_value=[{"deviceId": "dev_cfg_day", "name": "Jackson", "online": True}]), \
             patch.object(clients.yoto_client, "get_device_config", return_value={"maxVolumeLimit": "12", "nightMaxVolumeLimit": "8"}):
            players_day = player_service.get_live_players_map(force_refresh=True)

        self.assertEqual(players_day["dev_cfg_day"]["volume_max"], 75)


if __name__ == "__main__":
    unittest.main()
