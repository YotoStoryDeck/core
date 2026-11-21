import tests.test_isolation  # noqa: F401
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

import app as app_module
import clients
import database


class TestRefactorStandaloneFixes(unittest.TestCase):
    """Verifies standalone bug fixes (Bugs 1-5) and removal of legacy external-bridge routes."""

    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

    def test_01_removed_legacy_routes_return_404(self):
        """Legacy external bridge and simulator routes must be removed and return 404."""
        self._login_admin()
        checks = [
            ("POST", "/api/admin/test/bridge"),
            ("GET", "/api/admin/yoto/cards"),
            ("POST", "/api/admin/devices/aa:bb:cc:dd:ee:ff/reset-pin"),
            ("GET", "/simulator"),
            ("GET", "/simulator/"),
        ]
        for method, path in checks:
            res = self.client.open(path, method=method)
            self.assertEqual(res.status_code, 404, f"Expected 404 for {method} {path}, got {res.status_code}")

    def test_02_health_reports_real_standalone_features(self):
        """Bug 2: /health reports standalone connection_mode, embedded_bridge=True, and real feature flags."""
        orig_creds = database.get_api_credentials()
        try:
            database.update_api_credentials({
                "abs_base_url": "http://abs.local:13378",
                "abs_api_key": "abs_key_123456",
                "yoto_client_id": "yoto_cid_123",
                "yoto_refresh_token": "yoto_rt_123",
            })
            res = self.client.get("/health")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["connection_mode"], "standalone")
            self.assertTrue(data["abs_configured"])
            self.assertTrue(data["yoto_configured"])
            features = data["features"]
            self.assertTrue(features["abs_enabled"])
            self.assertTrue(features["yoto_enabled"])
            self.assertTrue(features["embedded_bridge"])
            self.assertIsInstance(features["ai_chapter_art"], dict)
            self.assertIn("enabled", features["ai_chapter_art"])
            self.assertIn("configured", features["ai_chapter_art"])
        finally:
            database.update_api_credentials(orig_creds)

    def test_03_discovery_abs_users_not_gated_on_bridge_mode(self):
        """Bug 3: /api/admin/discovery/abs-users works whenever ABS client is configured."""
        self._login_admin()
        mock_abs = MagicMock()
        mock_abs.base_url = "http://abs.local:13378"
        mock_abs.get_headers.return_value = {"Authorization": "Bearer test_tok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "users": [
                {"id": "u1", "username": "alice", "type": "user"},
                {"id": "u2", "username": "parent", "type": "root"},
            ]
        }

        with patch.object(clients, "abs_client", mock_abs), \
             patch("routes.admin_discovery.requests.get", return_value=mock_resp) as mock_get:
            res = self.client.get("/api/admin/discovery/abs-users")

        self.assertEqual(res.status_code, 200)
        mock_get.assert_called_once()
        users = res.get_json()
        self.assertEqual(len(users), 2)
        self.assertEqual(users[0]["username"], "alice")
        self.assertFalse(users[0]["is_admin"])
        self.assertTrue(users[1]["is_admin"])

    def test_04_play_abs_native_bridge_streaming_dispatch(self):
        """Bug 1: POST /api/play with type='abs' uses embedded BridgeManager + MQTT/Cloud natively."""
        self._login_admin()
        test_profile = {
            "display_name": "Bug1Tester",
            "default_player_id": "yoto_player_b1",
            "player_ids": ["yoto_player_b1"],
        }
        database.upsert_profile("bug1tester", test_profile)
        try:
            mock_mgr = MagicMock()
            mock_mgr.update_profile_primary_card.return_value = {
                "slot_id": "profile_bug1tester",
                "yoto_card_id": "card_slot_b1",
                "mode": "streaming",
                "title": "The Borrowers",
                "tracks": [{"title": "Chapter 1"}, {"title": "Chapter 2"}],
            }

            mock_mqtt = MagicMock()
            mock_mqtt.is_connected = True
            mock_mqtt.play.return_value = True

            mock_pb = MagicMock()
            mock_yoto = MagicMock()
            mock_yoto.save_stream_playlist.return_value = "card_slot_b1"

            with patch("core.bridge.manager.get_bridge_manager", return_value=mock_mgr), \
                 patch("core.bridge.mqtt_client.get_mqtt_bridge", return_value=mock_mqtt), \
                 patch("core.bridge.playback.get_playback_manager", return_value=mock_pb), \
                 patch.object(clients, "yoto_client", mock_yoto):
                res = self.client.post("/api/play", json={
                    "child": "bug1tester",
                    "type": "abs",
                    "id": "abs_item_b1",
                    "chapter": 2,
                })

            self.assertEqual(res.status_code, 200)
            payload = res.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["type"], "abs")
            self.assertEqual(payload["device_id"], "yoto_player_b1")
            self.assertEqual(payload["card_id"], "card_slot_b1")
            self.assertEqual(payload["chapter"], 2)
            self.assertEqual(payload["chapter_title"], "Chapter 2")
            mock_yoto.save_stream_playlist.assert_called_once()
            mock_mqtt.play.assert_called_once_with("yoto_player_b1", "card_slot_b1", track=2)
        finally:
            if hasattr(database, "delete_profile"):
                database.delete_profile("bug1tester")

    def test_05_serve_track_icon_reads_local_custom_icon(self):
        """Bug 5: GET /s/icon/<slot_id>/<track_idx>.png serves local CUSTOM_ICONS_DIR PNG."""
        img = Image.new("RGBA", (16, 16), (12, 34, 56, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        custom_png = buf.getvalue()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "abs_icon_item_1.png").write_bytes(custom_png)

            mock_mgr = MagicMock()
            mock_mgr.get_slot.return_value = {"slot_id": "slot_ic_1", "abs_item_id": "abs_icon_item"}

            with patch("routes.bridge_stream.CUSTOM_ICONS_DIR", tmp_path), \
                 patch("routes.bridge_stream.get_bridge_manager", return_value=mock_mgr):
                # track_idx=2 -> icon_idx=1 -> abs_icon_item_1.png
                res = self.client.get("/s/icon/slot_ic_1/2.png")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.mimetype, "image/png")
                self.assertEqual(res.data, custom_png)

                # Missing icon track falls back to synthesized orange PNG
                res_fallback = self.client.get("/s/icon/slot_ic_1/9.png")
                self.assertEqual(res_fallback.status_code, 200)
                self.assertEqual(res_fallback.mimetype, "image/png")
                self.assertNotEqual(res_fallback.data, custom_png)


if __name__ == "__main__":
    unittest.main()
