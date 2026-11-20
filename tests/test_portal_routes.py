"""
Unit tests for Mobile Parent Portal & Player endpoints.
Verifies GET / serves portal.html with LAN auth, and player transport endpoints.
"""
import unittest
from unittest.mock import MagicMock, patch
from app import app
import database
import clients


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
        mock_devices = [{"deviceId": "yoto_123", "name": "Bedroom Yoto", "online": True}]
        with patch.object(clients.yoto_client, "get_devices", return_value=mock_devices):
            res = self.app.get("/api/player/devices", environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "Bedroom Yoto")

    def test_player_transport_endpoint(self):
        """Verifies POST /api/player/transport forwards actions to YotoClient."""
        with patch.object(clients.yoto_client, "send_transport_command", return_value=True) as mock_cmd, \
             patch.object(clients.yoto_client, "set_volume", return_value=True) as mock_vol:

            # Transport command
            res = self.app.post("/api/player/transport",
                                json={"device_id": "yoto_123", "action": "pause"},
                                environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res.status_code, 200)
            mock_cmd.assert_called_once_with("yoto_123", "pause")

            # Volume command
            res = self.app.post("/api/player/transport",
                                json={"device_id": "yoto_123", "action": "volume", "volume": 65},
                                environ_base={"REMOTE_ADDR": "192.168.1.100"})
            self.assertEqual(res.status_code, 200)
            mock_vol.assert_called_once_with("yoto_123", 65)

    def test_library_profile_endpoint(self):
        """Verifies GET /api/library/profile/<id> returns catalog array."""
        res = self.app.get("/api/library/profile/portal_child", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.get_json(), list)


if __name__ == "__main__":
    unittest.main()
