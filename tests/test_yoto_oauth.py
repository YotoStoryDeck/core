"""
Isolated unit tests for Yoto OAuth 2.0 PKCE automatic callback exchange,
multi-worker SQLite flow storage, and reverse-proxy HTTPS / origin detection.
"""
import tests.test_isolation  # noqa: F401 - must precede app/database/clients imports

import unittest
from unittest.mock import MagicMock, patch

from app import app
import database
import clients
import routes.yoto_oauth as yoto_oauth


class TestYotoOAuthFlow(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

        self.orig_creds = database.get_api_credentials()
        database.set_system_setting("yoto_oauth_pkce_flows", {})
        yoto_oauth.YOTO_PKCE_FLOWS.clear()

        with self.app.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

    def tearDown(self):
        database.set_system_setting("yoto_oauth_pkce_flows", {})
        yoto_oauth.YOTO_PKCE_FLOWS.clear()
        database.update_api_credentials(self.orig_creds)
        clients.reload_clients()
        self.app_context.pop()

    def test_01_reverse_proxy_https_detection(self):
        """Verifies X-Forwarded-Proto/Host resolves to https://<host>/s/yoto-callback."""
        res = self.app.post(
            "/api/admin/yoto/oauth/start",
            json={"client_id": "pub_client_https"},
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "storydeck.example.com"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["redirect_uri"], "https://storydeck.example.com/s/yoto-callback")
        self.assertTrue(data["auto_callback"])

    def test_02_client_origin_loopback_and_plain_http_lan_fallback(self):
        """Verifies loopback origins auto-callback while plain HTTP LAN IPs use :8787 fallback."""
        for origin in ("http://127.0.0.1:5055", "http://localhost:5055"):
            res = self.app.post(
                "/api/admin/yoto/oauth/start",
                json={"client_id": "pub_client_local", "client_origin": origin}
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["redirect_uri"], f"{origin}/s/yoto-callback")
            self.assertTrue(data["auto_callback"])

        res_lan = self.app.post(
            "/api/admin/yoto/oauth/start",
            json={"client_id": "pub_client_lan", "client_origin": "http://192.168.1.50:5055"}
        )
        self.assertEqual(res_lan.status_code, 200)
        lan_data = res_lan.get_json()
        self.assertEqual(lan_data["redirect_uri"], "http://127.0.0.1:8787/callback")
        self.assertFalse(lan_data["auto_callback"])

    def test_03_callback_landing_exchanges_code_server_side_without_secret(self):
        """Verifies GET /s/yoto-callback exchanges PKCE code directly without client_secret."""
        start_res = self.app.post(
            "/api/admin/yoto/oauth/start",
            json={"client_id": "pub_client_auto", "client_origin": "https://storydeck.example.com"}
        )
        state = start_res.get_json()["state"]

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "access_token": "acc_token_auto",
            "refresh_token": "ref_token_auto_987",
            "expires_in": 3600
        }

        with patch("routes.yoto_oauth.requests.post", return_value=mock_resp) as mock_post:
            cb_res = self.app.get(f"/s/yoto-callback?code=auth_code_123&state={state}")

        self.assertEqual(cb_res.status_code, 200)
        html_body = cb_res.get_data(as_text=True)
        self.assertIn("BroadcastChannel", html_body)
        self.assertIn("YOTO_AUTH_COMPLETE", html_body)

        mock_post.assert_called_once()
        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["grant_type"], "authorization_code")
        self.assertEqual(sent_payload["client_id"], "pub_client_auto")
        self.assertEqual(sent_payload["code"], "auth_code_123")
        self.assertEqual(sent_payload["redirect_uri"], "https://storydeck.example.com/s/yoto-callback")
        self.assertNotIn("client_secret", sent_payload)

        creds = database.get_api_credentials()
        self.assertEqual(creds["yoto_client_id"], "pub_client_auto")
        self.assertEqual(creds["yoto_refresh_token"], "ref_token_auto_987")

        status_res = self.app.get(f"/api/admin/yoto/oauth/status?state={state}")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.get_json()
        self.assertEqual(status_data["status"], "completed")

    def test_04_multi_worker_sqlite_flow_persistence(self):
        """Clearing in-memory YOTO_PKCE_FLOWS simulates a second Gunicorn worker handling callback."""
        start_res = self.app.post(
            "/api/admin/yoto/oauth/start",
            json={"client_id": "pub_client_worker2", "client_origin": "http://localhost:5055"}
        )
        state = start_res.get_json()["state"]

        # Simulate different worker process having empty in-memory dict
        yoto_oauth.YOTO_PKCE_FLOWS.clear()

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "access_token": "acc_worker2",
            "refresh_token": "ref_worker2_abc",
            "expires_in": 3600
        }

        with patch("routes.yoto_oauth.requests.post", return_value=mock_resp):
            cb_res = self.app.get(f"/s/yoto-callback?code=worker2_code&state={state}")

        self.assertEqual(cb_res.status_code, 200)
        creds = database.get_api_credentials()
        self.assertEqual(creds["yoto_refresh_token"], "ref_worker2_abc")

    def test_05_idempotent_finish_after_callback_completion(self):
        """Calling /finish after /s/yoto-callback completed returns 200 without re-calling Auth0."""
        start_res = self.app.post(
            "/api/admin/yoto/oauth/start",
            json={"client_id": "pub_client_idem", "client_origin": "https://storydeck.example.com"}
        )
        state = start_res.get_json()["state"]

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "access_token": "acc_idem",
            "refresh_token": "ref_idem_111",
            "expires_in": 3600
        }

        with patch("routes.yoto_oauth.requests.post", return_value=mock_resp) as mock_post:
            cb_res = self.app.get(f"/s/yoto-callback?code=idem_code&state={state}")
            self.assertEqual(cb_res.status_code, 200)
            mock_post.assert_called_once()

            mock_post.reset_mock()
            fin_res = self.app.post(
                "/api/admin/yoto/oauth/finish",
                json={"url_or_code": "idem_code", "state": state}
            )
            self.assertEqual(fin_res.status_code, 200)
            self.assertTrue(fin_res.get_json()["ok"])
            mock_post.assert_not_called()

    def test_06_manual_paste_8787_callback_url(self):
        """Verifies manual copy-paste of http://127.0.0.1:8787/callback?code=... completes flow."""
        start_res = self.app.post(
            "/api/admin/yoto/oauth/start",
            json={"client_id": "pub_client_manual", "client_origin": "http://192.168.1.50:5055"}
        )
        start_data = start_res.get_json()
        state = start_data["state"]
        self.assertFalse(start_data["auto_callback"])

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "access_token": "acc_manual",
            "refresh_token": "ref_manual_xyz",
            "expires_in": 3600
        }

        with patch("routes.yoto_oauth.requests.post", return_value=mock_resp) as mock_post:
            fin_res = self.app.post(
                "/api/admin/yoto/oauth/finish",
                json={
                    "url_or_code": f"http://127.0.0.1:8787/callback?code=manual_xyz&state={state}"
                }
            )

        self.assertEqual(fin_res.status_code, 200)
        self.assertTrue(fin_res.get_json()["ok"])
        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["redirect_uri"], "http://127.0.0.1:8787/callback")
        self.assertNotIn("client_secret", sent_payload)

        creds = database.get_api_credentials()
        self.assertEqual(creds["yoto_refresh_token"], "ref_manual_xyz")


if __name__ == "__main__":
    unittest.main()
