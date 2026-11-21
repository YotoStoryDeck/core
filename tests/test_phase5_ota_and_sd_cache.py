"""
Unit & integration tests for Phase 5: Remote OTA Firmware Endpoints & Touch MicroSD Cache Controls (DLP-010 & DLP-020).
"""

import tests.test_isolation  # noqa: F401 - must precede app/clients/database imports
import hashlib
import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import app
import core.config as core_config
import database


class TestPhase5OtaAndSdCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        self.client = app.test_client()
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM firmware_releases;")
                conn.execute("DELETE FROM esp32_devices WHERE mac_address LIKE 'p5:%' OR mac_address LIKE 'kiosk-p5-%';")
        finally:
            conn.close()

        # Clean up any leftover test .bin files in isolated FIRMWARE_DIR
        fw_dir = Path(core_config.FIRMWARE_DIR)
        if fw_dir.exists():
            for f in fw_dir.glob("*.bin"):
                f.unlink(missing_ok=True)

        # Register approved Touch LAN unit #1, Touch LAN unit #2, quarantined unit, and Web Kiosk
        database.register_esp32_device("p5:aa:bb:cc:dd:01", "Oliver's Bedside Display", "192.168.1.80", "v1.2.0")
        database.update_esp32_device("p5:aa:bb:cc:dd:01", {"is_approved": 1, "parent_pin": "4321"})

        database.register_esp32_device("p5:aa:bb:cc:dd:02", "Maya's Bedroom Display", "192.168.1.81", "v1.2.0")
        database.update_esp32_device("p5:aa:bb:cc:dd:02", {"is_approved": 1, "parent_pin": "1234"})

        database.register_esp32_device("p5:aa:bb:cc:dd:03", "Quarantined Display", "192.168.1.82", "v1.1.0")
        # Leave p5:aa:bb:cc:dd:03 unapproved (is_approved = 0)

        database.register_esp32_device("kiosk-p5-wall", "Playroom Wall Kiosk", "192.168.1.90", "v1.2.0-web")
        database.update_esp32_device("kiosk-p5-wall", {"is_approved": 1})

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = "p5_admin"
            sess["username"] = "admin"
            sess["role"] = "admin"

    def _make_esp32_bin(self, tag: bytes = b"TEST_BUILD") -> bytes:
        # Starts with 0xE9 ESP-IDF image magic byte and >= 24 bytes
        return b"\xe9\x04\x02\x20" + tag + (b"\xaa" * 64)

    def test_01_firmware_upload_list_set_latest_and_delete(self):
        """Verifies upload validation, SHA-256 cataloging, active-latest switching, and deletion cleanup."""
        # Unauthenticated / member callers rejected
        unauth = self.client.get("/api/admin/firmware", environ_base={"REMOTE_ADDR": "192.168.1.50"})
        self.assertIn(unauth.status_code, (401, 403))

        with self.client.session_transaction() as sess:
            sess["user_id"] = "p5_member"
            sess["username"] = "sitter"
            sess["role"] = "member"
        mem_res = self.client.get("/api/admin/firmware")
        self.assertEqual(mem_res.status_code, 403)

        self._login_admin()

        # Reject invalid magic header
        bad_magic = self.client.post(
            "/api/admin/firmware/upload",
            data={
                "version": "v1.2.0",
                "file": (io.BytesIO(b"NOT_AN_ESP32_BINARY_PAYLOAD_12345"), "firmware.bin"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(bad_magic.status_code, 400)

        # Reject path traversal version string
        bad_ver = self.client.post(
            "/api/admin/firmware/upload",
            data={
                "version": "../evil",
                "file": (io.BytesIO(self._make_esp32_bin()), "firmware.bin"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(bad_ver.status_code, 400)

        # Reject non-.bin filename
        bad_ext = self.client.post(
            "/api/admin/firmware/upload",
            data={
                "version": "v1.2.0",
                "file": (io.BytesIO(self._make_esp32_bin()), "firmware.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(bad_ext.status_code, 400)

        # Upload valid v1.2.0
        bin_v120 = self._make_esp32_bin(b"V120")
        res1 = self.client.post(
            "/api/admin/firmware/upload",
            data={
                "version": "v1.2.0",
                "release_tag": "Previous Stable",
                "git_commit": "ede4c6c",
                "release_notes": "Initial SQLite release",
                "is_active_latest": "true",
                "file": (io.BytesIO(bin_v120), "firmware_v1.2.0.bin"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(res1.status_code, 201)
        d1 = res1.get_json()
        self.assertTrue(d1["ok"])
        expected_sha = hashlib.sha256(bin_v120).hexdigest()
        self.assertEqual(d1["release"]["sha256_hash"], expected_sha)
        self.assertTrue(d1["release"]["is_active_latest"])
        p1 = Path(d1["release"]["file_path"])
        self.assertTrue(p1.is_file())
        self.assertEqual(p1.resolve().parent, Path(core_config.FIRMWARE_DIR).resolve())

        # Upload valid v1.2.1 marked as latest
        bin_v121 = self._make_esp32_bin(b"V121")
        res2 = self.client.post(
            "/api/admin/firmware/upload",
            data={
                "version": "v1.2.1",
                "release_tag": "Latest Stable",
                "git_commit": "7a35e53",
                "release_notes": "Dual-tab catalog + OTA rollback guard",
                "is_active_latest": "true",
                "file": (io.BytesIO(bin_v121), "firmware_v1.2.1.bin"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(res2.status_code, 201)

        list_res = self.client.get("/api/admin/firmware")
        self.assertEqual(list_res.status_code, 200)
        rels = {r["version"]: r for r in list_res.get_json()}
        self.assertTrue(rels["v1.2.1"]["is_active_latest"])
        self.assertFalse(rels["v1.2.0"]["is_active_latest"])

        # Switch latest back to v1.2.0 via set-latest
        sw_res = self.client.post("/api/admin/firmware/v1.2.0/set-latest")
        self.assertEqual(sw_res.status_code, 200)
        rels2 = {r["version"]: r for r in self.client.get("/api/admin/firmware").get_json()}
        self.assertTrue(rels2["v1.2.0"]["is_active_latest"])
        self.assertFalse(rels2["v1.2.1"]["is_active_latest"])

        # Delete v1.2.0 -> removes .bin on disk and promotes v1.2.1
        del_res = self.client.delete("/api/admin/firmware/v1.2.0")
        self.assertEqual(del_res.status_code, 200)
        self.assertFalse(p1.exists())
        rels3 = {r["version"]: r for r in self.client.get("/api/admin/firmware").get_json()}
        self.assertNotIn("v1.2.0", rels3)
        self.assertTrue(rels3["v1.2.1"]["is_active_latest"])

    def test_02_firmware_binary_streaming_and_security(self):
        """Verifies trusted LAN ESP32 pull stream headers and WAN 403 block."""
        self._login_admin()
        bin_bytes = self._make_esp32_bin(b"STREAM_CHECK")
        up = self.client.post(
            "/api/admin/firmware/upload",
            data={
                "version": "v1.2.1",
                "is_active_latest": "true",
                "file": (io.BytesIO(bin_bytes), "firmware.bin"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(up.status_code, 201)

        # Logout session to verify raw LAN ESP32 pull
        with self.client.session_transaction() as sess:
            sess.clear()

        # WAN blocked
        wan_res = self.client.get("/api/firmware/v1.2.1/firmware.bin", environ_base={"REMOTE_ADDR": "8.8.8.8"})
        self.assertEqual(wan_res.status_code, 403)
        wan_res.close()

        # LAN allowed with SHA-256 and Content-Length headers
        lan_res = self.client.get("/api/firmware/v1.2.1/firmware.bin", environ_base={"REMOTE_ADDR": "192.168.1.80"})
        self.assertEqual(lan_res.status_code, 200)
        body = lan_res.data
        lan_res.close()
        self.assertEqual(body, bin_bytes)
        self.assertEqual(lan_res.headers.get("X-SHA256"), hashlib.sha256(bin_bytes).hexdigest())
        self.assertEqual(lan_res.headers.get("X-Firmware-Version"), "v1.2.1")
        self.assertEqual(int(lan_res.headers.get("Content-Length", 0)), len(bin_bytes))

    def test_03_single_ota_push_rollback_error_and_update_all(self):
        """Tests 1-click OTA update, same-version gate, rollback, upstream failure, and update-all."""
        self._login_admin()
        self.client.post(
            "/api/admin/firmware/upload",
            data={"version": "v1.2.0", "is_active_latest": "false", "file": (io.BytesIO(self._make_esp32_bin(b"120")), "fw120.bin")},
            content_type="multipart/form-data",
        )
        up2 = self.client.post(
            "/api/admin/firmware/upload",
            data={"version": "v1.2.1", "is_active_latest": "true", "file": (io.BytesIO(self._make_esp32_bin(b"121")), "fw121.bin")},
            content_type="multipart/form-data",
        )
        sha121 = up2.get_json()["release"]["sha256_hash"]

        # Same version without force rejected with 400
        same_res = self.client.post("/api/admin/devices/p5:aa:bb:cc:dd:01/update", json={"version": "v1.2.0"})
        self.assertEqual(same_res.status_code, 400)

        # Push v1.2.1 to device #1 -> HTTP 202 mocked from ESP32 /ota/trigger
        mock_ok = MagicMock(status_code=202)
        with patch("routes.admin_firmware.requests.post", return_value=mock_ok) as mock_post:
            res = self.client.post(
                "/api/admin/devices/p5:aa:bb:cc:dd:01/update",
                json={"version": "v1.2.1"},
            )
        self.assertEqual(res.status_code, 200)
        d = res.get_json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["target"], "v1.2.1")
        self.assertEqual(d["previous"], "v1.2.0")
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        self.assertEqual(call_args[0], "http://192.168.1.80/ota/trigger")
        self.assertEqual(call_kwargs["json"]["url"], "/api/firmware/v1.2.1/firmware.bin")
        self.assertEqual(call_kwargs["json"]["sha256"], sha121)

        dev1 = database.get_esp32_device("p5:aa:bb:cc:dd:01")
        self.assertEqual(dev1["ota_status"], "pending")
        self.assertEqual(dev1["target_firmware_version"], "v1.2.1")
        self.assertEqual(dev1["previous_firmware_version"], "v1.2.0")

        # Network error sets ota_status='failed' and returns 502
        import requests as req_mod
        with patch("routes.admin_firmware.requests.post", side_effect=req_mod.ConnectionError("timeout")):
            fail_res = self.client.post(
                "/api/admin/devices/p5:aa:bb:cc:dd:01/update",
                json={"version": "v1.2.1", "force": True},
            )
        self.assertEqual(fail_res.status_code, 502)
        dev1_fail = database.get_esp32_device("p5:aa:bb:cc:dd:01")
        self.assertEqual(dev1_fail["ota_status"], "failed")
        self.assertIn("timeout", dev1_fail["ota_last_error"])

        # Update-All targets approved Touch displays (dd:01, dd:02) and skips quarantined (dd:03) & kiosk
        with patch("routes.admin_firmware.requests.post", return_value=mock_ok) as mock_batch:
            all_res = self.client.post("/api/admin/devices/update-all", json={"version": "v1.2.1", "delay_seconds": 0})
        self.assertEqual(all_res.status_code, 200)
        all_data = all_res.get_json()
        self.assertEqual(all_data["dispatched"], 2)
        self.assertEqual(all_data["skipped"], 2)
        dispatched_urls = [c.args[0] for c in mock_batch.call_args_list]
        self.assertIn("http://192.168.1.80/ota/trigger", dispatched_urls)
        self.assertIn("http://192.168.1.81/ota/trigger", dispatched_urls)

    def test_04_ota_progress_telemetry_and_boot_verification_rollback(self):
        """Verifies /ota-progress updates DB, WAN blocked, and register boot_state handles verified/rolled_back."""
        # Set initial pending target
        database.update_esp32_device("p5:aa:bb:cc:dd:01", {
            "target_firmware_version": "v1.2.1",
            "ota_status": "pending",
            "ota_progress": 0,
        })

        # WAN blocked
        wan = self.client.post(
            "/api/devices/p5:aa:bb:cc:dd:01/ota-progress",
            json={"status": "flashing", "percent": 50},
            environ_base={"REMOTE_ADDR": "8.8.8.8"},
        )
        self.assertEqual(wan.status_code, 403)

        # LAN telemetry accepted with percent and clamped
        prog_res = self.client.post(
            "/api/devices/p5:aa:bb:cc:dd:01/ota-progress",
            json={"status": "flashing", "percent": 68},
            environ_base={"REMOTE_ADDR": "192.168.1.80"},
        )
        self.assertEqual(prog_res.status_code, 200)
        dev = database.get_esp32_device("p5:aa:bb:cc:dd:01")
        self.assertEqual(dev["ota_status"], "flashing")
        self.assertEqual(dev["ota_progress"], 68)

        # Simulate successful self-test boot check via /api/devices/register
        reg_ok = self.client.post("/api/devices/register", json={
            "mac_address": "p5:aa:bb:cc:dd:01",
            "ip_address": "192.168.1.80",
            "firmware_version": "v1.2.1",
            "boot_state": "verified",
        })
        self.assertEqual(reg_ok.status_code, 200)
        dev_verified = database.get_esp32_device("p5:aa:bb:cc:dd:01")
        self.assertEqual(dev_verified["firmware_version"], "v1.2.1")
        self.assertEqual(dev_verified["ota_status"], "idle")
        self.assertEqual(dev_verified["ota_progress"], 100)

        # Simulate bootloader auto-rollback
        reg_rb = self.client.post("/api/devices/register", json={
            "mac_address": "p5:aa:bb:cc:dd:01",
            "ip_address": "192.168.1.80",
            "firmware_version": "v1.2.0",
            "boot_state": "rolled_back",
        })
        self.assertEqual(reg_rb.status_code, 200)
        dev_rb = database.get_esp32_device("p5:aa:bb:cc:dd:01")
        self.assertEqual(dev_rb["firmware_version"], "v1.2.0")
        self.assertEqual(dev_rb["ota_status"], "rolled_back")

    def test_05_touch_microsd_cache_relay_and_ssrf_guards(self):
        """Verifies /cache/status, /cache/prune, /cache/refresh, DELETE /cache relays & SSRF guards."""
        self._login_admin()

        # Quarantined device & Web Kiosk rejected (400)
        q_res = self.client.post("/api/admin/devices/p5:aa:bb:cc:dd:03/cache/prune", json={})
        self.assertEqual(q_res.status_code, 400)
        k_res = self.client.post("/api/admin/devices/kiosk-p5-wall/cache/prune", json={})
        self.assertEqual(k_res.status_code, 400)

        # Non-LAN IP (SSRF check) rejected (400)
        database.register_esp32_device("p5:aa:bb:cc:dd:99", "Bad IP Unit", "8.8.4.4", "v1.2.0")
        database.update_esp32_device("p5:aa:bb:cc:dd:99", {"is_approved": 1})
        ssrf_res = self.client.get("/api/admin/devices/p5:aa:bb:cc:dd:99/cache/status")
        self.assertEqual(ssrf_res.status_code, 400)

        # Status check
        m_status = MagicMock(status_code=200)
        m_status.json.return_value = {"mounted": True, "used_mb": 42, "files": 128, "orphans": 4}
        with patch("routes.admin_firmware.requests.request", return_value=m_status) as mock_req:
            st_res = self.client.get("/api/admin/devices/p5:aa:bb:cc:dd:01/cache/status")
        self.assertEqual(st_res.status_code, 200)
        self.assertEqual(st_res.get_json()["sd"]["orphans"], 4)
        self.assertEqual(mock_req.call_args.kwargs["method"], "GET")
        self.assertEqual(mock_req.call_args.kwargs["url"], "http://192.168.1.80/sd/status")

        # Prune relays stored parent_pin='4321'
        m_prune = MagicMock(status_code=200)
        m_prune.json.return_value = {"ok": True, "deleted_count": 4, "reclaimed_bytes": 286720}
        with patch("routes.admin_firmware.requests.request", return_value=m_prune) as mock_req:
            pr_res = self.client.post("/api/admin/devices/p5:aa:bb:cc:dd:01/cache/prune", json={})
        self.assertEqual(pr_res.status_code, 200)
        self.assertEqual(pr_res.get_json()["device_response"]["deleted_count"], 4)
        self.assertEqual(mock_req.call_args.kwargs["method"], "POST")
        self.assertEqual(mock_req.call_args.kwargs["url"], "http://192.168.1.80/sd/prune")
        self.assertEqual(mock_req.call_args.kwargs["params"], {"pin": "4321"})

        # Refresh specific card
        m_ref = MagicMock(status_code=200)
        m_ref.json.return_value = {"ok": True, "card_id": "abc123"}
        with patch("routes.admin_firmware.requests.request", return_value=m_ref) as mock_req:
            rf_res = self.client.post("/api/devices/p5:aa:bb:cc:dd:01/cache/refresh", json={"card_id": "abc123"})
        self.assertEqual(rf_res.status_code, 200)
        self.assertEqual(mock_req.call_args.kwargs["url"], "http://192.168.1.80/sd/refresh")
        self.assertEqual(mock_req.call_args.kwargs["params"], {"pin": "4321", "id": "abc123"})

        # Purge / wipe entire SD cache
        m_del = MagicMock(status_code=200)
        m_del.json.return_value = {"ok": True, "cleared_dir": "/ythumbs", "total_deleted": 128}
        with patch("routes.admin_firmware.requests.request", return_value=m_del) as mock_req:
            dl_res = self.client.delete("/api/admin/devices/p5:aa:bb:cc:dd:01/cache")
        self.assertEqual(dl_res.status_code, 200)
        self.assertEqual(mock_req.call_args.kwargs["method"], "DELETE")
        self.assertEqual(mock_req.call_args.kwargs["url"], "http://192.168.1.80/sd/cache")
        self.assertEqual(mock_req.call_args.kwargs["params"], {"pin": "4321", "confirm": "1"})

    def test_06_admin_html_contains_firmware_and_cache_ui(self):
        """Verifies /admin HTML renders Firmware Repository, OTA modals, and firmware.js script."""
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        for token in (
            'id="uploadFirmwareModal"',
            'id="pushFirmwareModal"',
            'id="firmwareReleasesTable"',
            'openUploadFirmwareModal()',
            'pushFirmwareUpdateAll()',
            '/static/js/admin/firmware.js?v=',
        ):
            self.assertIn(token, html, f"Expected {token} in /admin HTML")


if __name__ == "__main__":
    unittest.main()
