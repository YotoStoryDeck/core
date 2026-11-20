"""
Unit tests for Mobile Parent Portal & Player endpoints.
Verifies GET / serves portal.html with LAN auth, and player transport endpoints.
"""
import tests.test_isolation  # noqa: F401 - must precede app/database/clients imports
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import requests
from app import app
import database
import clients
from clients.yoto_client import YotoClient


class TestPortalRoutes(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

        # Seed profile
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM profiles WHERE id = 'portal_child';")
                cur.execute("""
                    INSERT INTO profiles (id, display_name, default_playback_mode, offline_retention_limit)
                    VALUES ('portal_child', 'Portal Child', 'streaming', 8);
                """)
        finally:
            conn.close()

    def tearDown(self):
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM profiles WHERE id = 'portal_child';")
        finally:
            conn.close()
        self.app_context.pop()

    def test_root_portal_serves_html_for_trusted_lan(self):
        """Verifies GET / serves portal.html for LAN clients (127.0.0.1)."""
        res = self.app.get("/", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"StoryDeck \xe2\x80\xa2 Parent Portal", res.data)
        self.assertIn(b"Target Yoto Player", res.data)
        self.assertIn(b"Physical Cards Inventory", res.data)

    def test_player_devices_endpoint(self):
        """Verifies GET /api/player/devices returns device list."""
        mock_map = {
            "yoto_123": {
                "id": "yoto_123",
                "deviceId": "yoto_123",
                "name": "Bedroom Yoto",
                "online": True,
                "status": "idle"
            }
        }
        with patch("core.player_service.get_live_players_map", return_value=mock_map):
            res = self.app.get("/api/player/devices", environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "Bedroom Yoto")

    def test_player_transport_endpoint(self):
        """Verifies POST /api/player/transport forwards actions to dispatch_player_control."""
        with patch("core.player_service.dispatch_player_control", return_value=(True, {"ok": True}, 200)) as mock_ctl:
            # Transport command
            res = self.app.post("/api/player/transport",
                                json={"device_id": "yoto_123", "action": "pause"},
                                environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res.status_code, 200)
            mock_ctl.assert_called_with("yoto_123", "pause", volume=None, minutes=None, position=None, speed=None)

            # Volume command
            res = self.app.post("/api/player/transport",
                                json={"device_id": "yoto_123", "action": "volume", "volume": 65},
                                environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res.status_code, 200)
            mock_ctl.assert_called_with("yoto_123", "volume", volume=65, minutes=None, position=None, speed=None)

    def test_library_profile_endpoint(self):
        """Verifies GET /api/library/profile/<id> returns catalog array."""
        res = self.app.get("/api/library/profile/portal_child", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.get_json(), list)

    def test_yoto_auth_status_invalid_grant_and_negative_cache(self):
        """Verifies GET /api/yoto/auth-status reports invalid_grant and honors 30s negative cache."""
        yc = YotoClient(client_id="cid_test", refresh_token="bad_ref")
        mock_res = MagicMock()
        mock_res.status_code = 400
        mock_res.text = '{"error":"invalid_grant","error_description":"Unknown or invalid refresh token."}'
        mock_res.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Unknown or invalid refresh token."
        }

        with patch.object(clients, "yoto_client", yc), \
             patch("requests.post", return_value=mock_res) as mock_post:
            res1 = self.app.get("/api/yoto/auth-status", environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res1.status_code, 200)
            d1 = res1.get_json()
            self.assertFalse(d1["token_valid"])
            self.assertFalse(d1["connected"])
            self.assertEqual(d1["reason"], "invalid_grant")
            self.assertEqual(mock_post.call_count, 1)

            # Immediate repeat without force=1 uses 30s negative cache
            res2 = self.app.get("/api/yoto/auth-status", environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res2.status_code, 200)
            self.assertFalse(res2.get_json()["token_valid"])
            self.assertEqual(mock_post.call_count, 1)

            # force=1 bypasses negative cache
            res3 = self.app.get("/api/yoto/auth-status?force=1", environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res3.status_code, 200)
            self.assertEqual(mock_post.call_count, 2)

    def test_yoto_auth_status_valid_token(self):
        """Verifies GET /api/yoto/auth-status succeeds and persists rotated refresh_token to temp DB."""
        orig_creds = database.get_api_credentials()
        yc = YotoClient(client_id="cid_test", refresh_token="init_ref_1")
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "access_token": "tok_ok",
            "refresh_token": "rot_ref_2",
            "expires_in": 3600
        }

        try:
            database.update_api_credentials({"yoto_client_id": "cid_test", "yoto_refresh_token": "init_ref_1"})
            with patch.object(clients, "yoto_client", yc), \
                 patch("requests.post", return_value=mock_res):
                res = self.app.get("/api/yoto/auth-status", environ_base={"REMOTE_ADDR": "192.168.1.100"})
                self.assertEqual(res.status_code, 200)
                data = res.get_json()
                self.assertTrue(data["token_valid"])
                self.assertTrue(data["connected"])
                self.assertEqual(data["reason"], "ok")
                self.assertEqual(database.get_api_credentials().get("yoto_refresh_token"), "rot_ref_2")
        finally:
            database.update_api_credentials(orig_creds)

    def test_yoto_get_token_thread_safe_single_refresh(self):
        """Verifies concurrent get_token() calls perform only a single HTTP refresh under lock."""
        yc = YotoClient(client_id="cid_concurrent", refresh_token="ref_conc_1")
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "access_token": "shared_access_tok",
            "refresh_token": "ref_conc_2",
            "expires_in": 3600
        }

        def slow_post(*args, **kwargs):
            time.sleep(0.05)
            return mock_res

        results = []
        errors = []

        def worker():
            try:
                results.append(yc.get_token())
            except Exception as exc:
                errors.append(exc)

        with patch("requests.post", side_effect=slow_post) as mock_post, \
             patch("database.update_api_credentials", return_value=True):
            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [])
            self.assertEqual(mock_post.call_count, 1)
            self.assertEqual(results, ["shared_access_tok"] * 6)

    def test_root_portal_contains_yoto_auth_lockout_ui(self):
        """Verifies GET / includes the Yoto token status pill and portal lockout panel."""
        res = self.app.get("/", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"yotoAuthStatusPill", res.data)
        self.assertIn(b"yotoAuthBlockedView", res.data)
        self.assertIn(b"Yoto API Token Not Resolving", res.data)
        self.assertIn(b"btnRetryYotoAuth", res.data)


if __name__ == "__main__":
    unittest.main()
