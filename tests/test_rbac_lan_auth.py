import sys
from pathlib import Path

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

import tests.test_isolation  # noqa: F401 - must precede app/database imports
import unittest
import json
import sqlite3

from app import app
import database
from core.auth import is_trusted_lan_ip, get_effective_client_ip, get_current_user, get_current_admin_user


class TestRBACAndLANAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        self.client = app.test_client()
        # Clean up test users if any
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM admin_users WHERE username LIKE 'test_%';")
        finally:
            conn.close()

    def tearDown(self):
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM admin_users WHERE username LIKE 'test_%';")
        finally:
            conn.close()

    def test_01_is_trusted_lan_ip(self):
        """Verifies RFC1918 private subnets and loopback are identified as trusted LAN."""
        # Trusted LAN / Private
        self.assertTrue(is_trusted_lan_ip("127.0.0.1"))
        self.assertTrue(is_trusted_lan_ip("::1"))
        self.assertTrue(is_trusted_lan_ip("192.168.1.50"))
        self.assertTrue(is_trusted_lan_ip("192.168.0.1"))
        self.assertTrue(is_trusted_lan_ip("10.0.1.15"))
        self.assertTrue(is_trusted_lan_ip("172.16.0.1"))
        self.assertTrue(is_trusted_lan_ip("172.31.255.255"))

        # Public WAN / Untrusted
        self.assertFalse(is_trusted_lan_ip("8.8.8.8"))
        self.assertFalse(is_trusted_lan_ip("1.1.1.1"))
        self.assertFalse(is_trusted_lan_ip("104.28.1.1"))
        self.assertFalse(is_trusted_lan_ip("172.32.0.1"))
        self.assertFalse(is_trusted_lan_ip(""))
        self.assertFalse(is_trusted_lan_ip("invalid_ip"))

    def test_02_database_user_roles_and_helpers(self):
        """Verifies admin vs member user creation, updates, and deletion rules."""
        # Create an admin user and a member user
        admin_u = database.create_admin_user("test_admin_1", "Password123!", display_name="Admin One", role="admin")
        self.assertEqual(admin_u["role"], "admin")

        member_u = database.create_admin_user("test_member_1", "Password123!", display_name="Member One", role="member")
        self.assertEqual(member_u["role"], "member")

        # Test get_user_by_id
        fetched_member = database.get_user_by_id(member_u["id"])
        self.assertIsNotNone(fetched_member)
        self.assertEqual(fetched_member["username"], "test_member_1")
        self.assertEqual(fetched_member["role"], "member")

        # Test role update
        self.assertTrue(database.update_user_role(member_u["id"], "admin"))
        updated = database.get_user_by_id(member_u["id"])
        self.assertEqual(updated["role"], "admin")

        # Test password update
        self.assertTrue(database.update_user_password(member_u["id"], "NewPassword456!"))
        # Verify authentication with new password
        auth_res = database.authenticate_user("test_member_1", "NewPassword456!")
        self.assertIsNotNone(auth_res)
        self.assertIsNone(database.authenticate_user("test_member_1", "Password123!"))

        # Test delete member
        self.assertTrue(database.delete_user(member_u["id"]))
        self.assertIsNone(database.get_user_by_id(member_u["id"]))

    def test_03_prevent_deleting_last_admin(self):
        """Verifies that the database layer refuses to delete the last remaining administrator."""
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM admin_users WHERE role = 'admin';")
            admins = cur.fetchall()
            if len(admins) == 1:
                with self.assertRaises(ValueError):
                    database.delete_user(admins[0]["id"])
        finally:
            conn.close()

    def test_04_auth_me_lan_guest_vs_remote(self):
        """Verifies /api/auth/me detects LAN guest on RFC1918 IPs and blocks remote WAN without session."""
        # Simulate local LAN request without session
        res_lan = self.client.get("/api/auth/me", environ_base={"REMOTE_ADDR": "192.168.1.88"})
        self.assertEqual(res_lan.status_code, 200)
        data_lan = json.loads(res_lan.data)
        self.assertTrue(data_lan["authenticated"])
        self.assertEqual(data_lan["user"]["role"], "member")
        self.assertTrue(data_lan["user"]["is_lan_guest"])

        # Simulate remote WAN request without session
        res_wan = self.client.get("/api/auth/me", environ_base={"REMOTE_ADDR": "8.8.8.8"})
        self.assertEqual(res_wan.status_code, 200)
        data_wan = json.loads(res_wan.data)
        self.assertFalse(data_wan["authenticated"])
        self.assertIsNone(data_wan["user"])

    def test_05_admin_users_api_rbac(self):
        """Verifies that /api/admin/users strictly enforces role == 'admin'."""
        admin_u = database.create_admin_user("test_admin_2", "AdminPass123!", display_name="Admin Two", role="admin")
        member_u = database.create_admin_user("test_member_2", "MemberPass123!", display_name="Member Two", role="member")

        # 1. Access as LAN Guest (Should be rejected with 401: Unauthorized / Requires login)
        res_lan = self.client.get("/api/admin/users", environ_base={"REMOTE_ADDR": "192.168.1.88"})
        self.assertEqual(res_lan.status_code, 401)

        # 2. Access as Member session (Should be rejected with 403)
        with self.client.session_transaction() as sess:
            sess["user_id"] = member_u["id"]
            sess["username"] = member_u["username"]
            sess["role"] = member_u["role"]

        res_member = self.client.get("/api/admin/users")
        self.assertEqual(res_member.status_code, 403)

        # 3. Access as Admin session (Should succeed with 200)
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_u["id"]
            sess["username"] = admin_u["username"]
            sess["role"] = admin_u["role"]

        res_admin = self.client.get("/api/admin/users")
        self.assertEqual(res_admin.status_code, 200)
        users_data = json.loads(res_admin.data)
        self.assertTrue(users_data["ok"])
        usernames = [u["username"] for u in users_data["users"]]
        self.assertIn("test_admin_2", usernames)
        self.assertIn("test_member_2", usernames)

    def test_06_admin_create_update_delete_user_api(self):
        """Tests admin API CRUD operations for users."""
        admin_u = database.create_admin_user("test_admin_3", "AdminPass123!", display_name="Admin Three", role="admin")

        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_u["id"]
            sess["username"] = admin_u["username"]
            sess["role"] = admin_u["role"]

        # Create new member via API
        create_res = self.client.post("/api/admin/users", json={
            "username": "test_created_user",
            "password": "SecurePassword123!",
            "display_name": "Created Sitter",
            "role": "member"
        })
        self.assertEqual(create_res.status_code, 201)
        created_data = json.loads(create_res.data)
        self.assertTrue(created_data["ok"])
        created_id = created_data["user"]["id"]

        # Update member via API
        update_res = self.client.put(f"/api/admin/users/{created_id}", json={
            "display_name": "Updated Sitter Name",
            "role": "member"
        })
        self.assertEqual(update_res.status_code, 200)
        updated_data = json.loads(update_res.data)
        self.assertEqual(updated_data["user"]["display_name"], "Updated Sitter Name")

        # Delete member via API
        del_res = self.client.delete(f"/api/admin/users/{created_id}")
        self.assertEqual(del_res.status_code, 200)
        del_data = json.loads(del_res.data)
        self.assertTrue(del_data["ok"])

    def test_07_schema_version_10_elements(self):
        """Verifies schema version 10 tables and profile playback columns exist."""
        conn = database.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA user_version;")
            version = cur.fetchone()[0]
            self.assertGreaterEqual(version, 10)

            # Check profile columns
            cur.execute("PRAGMA table_info(profiles);")
            cols = [c[1] for c in cur.fetchall()]
            self.assertIn("default_playback_mode", cols)
            self.assertIn("primary_card_id", cols)
            self.assertIn("offline_retention_limit", cols)

            # Check bridge_slots table
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bridge_slots';")
            self.assertIsNotNone(cur.fetchone())

            # Check bridge_tracks table
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bridge_tracks';")
            self.assertIsNotNone(cur.fetchone())

            # Check profile_catalog_permissions table
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profile_catalog_permissions';")
            self.assertIsNotNone(cur.fetchone())
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
