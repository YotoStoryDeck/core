"""
Unit tests for StoryDeck Web UI Overhaul, Shared Core Offline Awareness, and SSO/Authentik Integration.
"""
import tests.test_isolation  # noqa: F401 - must precede app/database imports
import json
import unittest
from html.parser import HTMLParser

from app import app
import database


class _SectionAndFormParser(HTMLParser):
    """Collects section/form nesting to ensure dedicated tabs and proper form containment."""

    def __init__(self):
        super().__init__()
        self.form_depth = 0
        self.orphan_passwords = []
        self.id_to_section = {}
        self._section_stack = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if t == "section":
            self._section_stack.append(attr_map.get("id", ""))
        el_id = attr_map.get("id")
        if el_id:
            self.id_to_section[el_id] = list(self._section_stack)
        if t == "form":
            self.form_depth += 1
        elif t == "input" and attr_map.get("type", "").lower() == "password":
            if self.form_depth == 0:
                self.orphan_passwords.append(attr_map.get("id") or attr_map.get("name") or "<unnamed>")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "form" and self.form_depth > 0:
            self.form_depth -= 1
        elif t == "section" and self._section_stack:
            self._section_stack.pop()


class TestUIOverhaulAndSSO(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        database.init_db()

    def setUp(self):
        self.client = app.test_client()
        self._orig_sso_cfg = database.get_sso_config()
        self._orig_lan = database.get_system_settings().get("lan_sitter_access_enabled", True)
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM admin_users WHERE username LIKE 'sso_ui_%';")
                conn.execute("DELETE FROM profiles WHERE id = 'ui_test_child';")
        finally:
            conn.close()

    def tearDown(self):
        database.set_system_setting("sso_config", self._orig_sso_cfg)
        database.set_system_setting("lan_sitter_access_enabled", self._orig_lan)
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM admin_users WHERE username LIKE 'sso_ui_%';")
                conn.execute("DELETE FROM profiles WHERE id = 'ui_test_child';")
        finally:
            conn.close()

    def _login_session(self, role="admin", user_id="ui_admin_1", username="ui_admin"):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = username
            sess["display_name"] = username
            sess["role"] = role

    def test_01_portal_renders_sidebar_avatar_carousel_and_offline_awareness(self):
        """Parent Portal renders collapsible sidebar, /admin link, avatar carousel paired with player select, and offline UI."""
        res = self.client.get("/", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        for expected in (
            'id="appSidebar"',
            'id="sidebarCollapseBtn"',
            'href="/admin"',
            'id="portalContextBar"',
            'id="profileAvatarCarousel"',
            'Target Yoto Player',
            'id="playerDeviceSelect"',
            'id="coreConnectionPill"',
            'id="coreOfflineBanner"',
            'id="btnRetryCoreHealth"',
            '/static/js/sidebar.js',
            '/static/js/core_health.js',
        ):
            self.assertIn(expected, html)

        self.assertNotIn('class="bottom-nav"', html)
        self.assertNotIn('id="headerProfileSelect"', html)

    def test_02_admin_renders_mirror_sidebar_users_tab_and_offline_awareness(self):
        """Admin Console mirrors sidebar + Parent Portal link, isolates Users & Access tab, and encloses all passwords in forms."""
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        for expected in (
            'id="appSidebar"',
            'id="sidebarCollapseBtn"',
            'href="/"',
            'data-tab="users"',
            'id="tab-users"',
            'id="coreConnectionPill"',
            'id="coreOfflineBanner"',
            'id="btnRetryCoreHealth"',
            '/static/js/sidebar.js',
            '/static/js/core_health.js',
        ):
            self.assertIn(expected, html)

        self.assertNotIn('class="dashboard-tabs"', html)
        self.assertNotIn('id="coreVersionBadge"', html)

        # Ensure Core version tag helper strips duplicate leading 'v' prefixes (prevents 'vv1.1.0')
        with open("static/js/core_health.js", "r", encoding="utf-8") as f:
            ch_js = f.read()
        self.assertIn("function formatVersionTag", ch_js)
        self.assertNotIn("`v${state.lastVersion}`", ch_js)

        parser = _SectionAndFormParser()
        parser.feed(html)
        self.assertEqual(parser.orphan_passwords, [], f"Password input(s) outside <form>: {parser.orphan_passwords}")
        self.assertIn("tab-users", parser.id_to_section.get("cardUserAccounts", []))
        self.assertIn("tab-users", parser.id_to_section.get("cardSsoConfig", []))
        self.assertIn("tab-users", parser.id_to_section.get("toggleLanSitterAccess", []))
        self.assertNotIn("tab-settings", parser.id_to_section.get("cardUserAccounts", []))
        self.assertNotIn("tab-settings", parser.id_to_section.get("toggleLanSitterAccess", []))

    def test_03_public_profiles_and_health_endpoints(self):
        """GET /api/profiles works for Portal clients without admin cookie and exposes avatar & playback metadata."""
        database.upsert_profile("ui_test_child", {
            "display_name": "Wesley",
            "default_player_id": "yoto_dev_1",
            "player_ids": ["yoto_dev_1"],
            "default_playback_mode": "offline",
            "avatar_color": "#10b981",
            "avatar_initial": "W",
        })

        prof_res = self.client.get("/api/profiles", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(prof_res.status_code, 200)
        profiles = prof_res.get_json()
        child = next((p for p in profiles if p["id"] == "ui_test_child"), None)
        self.assertIsNotNone(child)
        self.assertIn("/api/avatar/ui_test_child", child["avatar_url"])
        self.assertEqual(child["default_playback_mode"], "offline")
        self.assertEqual(child["default_player_id"], "yoto_dev_1")
        self.assertEqual(child["avatar_color"], "#10b981")
        self.assertEqual(child["avatar_initial"], "W")

        health_res = self.client.get("/health", environ_base={"REMOTE_ADDR": "192.168.1.100"})
        self.assertEqual(health_res.status_code, 200)
        self.assertEqual(health_res.get_json().get("status"), "healthy")

    def test_04_sso_config_api_rbac_persistence_and_validation(self):
        """Verifies RBAC, secret masking/preservation, CIDR validation, LAN toggle, and OIDC callback placeholder."""
        # 1. LAN guest denied (401)
        lan_res = self.client.get("/api/admin/auth/sso-config", environ_base={"REMOTE_ADDR": "192.168.1.88"})
        self.assertEqual(lan_res.status_code, 401)

        # 2. Member denied (403)
        self._login_session(role="member", user_id="ui_mem_1", username="ui_member")
        mem_res = self.client.get("/api/admin/auth/sso-config")
        self.assertEqual(mem_res.status_code, 403)

        # 3. Admin GET & PUT validation/persistence
        self._login_session(role="admin", user_id="ui_adm_1", username="ui_admin")
        bad_cidr = self.client.put("/api/admin/auth/sso-config", json={
            "sso_config": {"extra_trusted_proxies": ["not_an_ip"]}
        })
        self.assertEqual(bad_cidr.status_code, 400)

        save_res = self.client.put("/api/admin/auth/sso-config", json={
            "lan_sitter_access_enabled": False,
            "sso_config": {
                "forward_auth_enabled": True,
                "provider_name": "Authentik",
                "admin_group": "storydeck-admins",
                "default_role": "member",
                "auto_provision_users": True,
                "extra_trusted_proxies": ["10.10.0.5"],
                "logout_url": "https://auth.example.com/logout",
                "oidc_enabled": True,
                "oidc_issuer_url": "https://auth.example.com/application/o/storydeck/",
                "oidc_client_id": "sd-client",
                "oidc_client_secret": "supersecret_oidc_value_99",
            }
        })
        self.assertEqual(save_res.status_code, 200)
        payload = save_res.get_json()
        self.assertFalse(payload["lan_sitter_access_enabled"])
        self.assertIn("••••", payload["sso_config"]["oidc_client_secret"])
        self.assertNotIn("supersecret_oidc_value_99", payload["sso_config"]["oidc_client_secret"])

        # Preserves secret when masked string is submitted back
        resave_res = self.client.put("/api/admin/auth/sso-config", json={
            "sso_config": {
                "provider_name": "Authentik",
                "oidc_client_secret": payload["sso_config"]["oidc_client_secret"],
            }
        })
        self.assertEqual(resave_res.status_code, 200)
        self.assertEqual(database.get_sso_config().get("oidc_client_secret"), "supersecret_oidc_value_99")

        # Reserved OIDC callback route returns explicit 501 notice
        cb_res = self.client.get("/api/auth/oidc/callback")
        self.assertEqual(cb_res.status_code, 501)

    def test_05_sso_forward_auth_group_mapping_auto_provision_and_disable(self):
        """Authentik group headers map admin_group -> admin vs member, support auto-provision, and respect disable toggle."""
        database.set_system_setting("sso_config", {
            "forward_auth_enabled": True,
            "provider_name": "Authentik",
            "header_username": "X-authentik-username",
            "header_display_name": "X-authentik-name",
            "header_groups": "X-authentik-groups",
            "admin_group": "storydeck-admins",
            "default_role": "member",
            "auto_provision_users": True,
            "extra_trusted_proxies": [],
        })

        # Unprivileged Authentik user gets member & is auto-provisioned
        me_member = self.client.get(
            "/api/auth/me",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-username": "sso_ui_sitter",
                "X-authentik-name": "Aunt Sitter",
                "X-authentik-groups": "family|sitters",
            },
        )
        self.assertEqual(me_member.status_code, 200)
        d_mem = me_member.get_json()
        self.assertTrue(d_mem["authenticated"])
        self.assertEqual(d_mem["user"]["role"], "member")
        self.assertEqual(d_mem["user"]["auth_type"], "sso")
        self.assertEqual(d_mem["user"]["display_name"], "Aunt Sitter")
        db_mem = database.get_user_by_username("sso_ui_sitter")
        self.assertIsNotNone(db_mem)
        self.assertEqual(db_mem["sso_provider"], "authentik")

        # Member SSO identity cannot access admin route
        adm_denied = self.client.get(
            "/api/admin/users",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-username": "sso_ui_sitter",
                "X-authentik-groups": "family|sitters",
            },
        )
        self.assertEqual(adm_denied.status_code, 403)

        # User inside admin_group gets admin role
        adm_allowed = self.client.get(
            "/api/admin/users",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-username": "sso_ui_parent",
                "X-authentik-name": "Mom Admin",
                "X-authentik-groups": "family|storydeck-admins",
            },
        )
        self.assertEqual(adm_allowed.status_code, 200)

        # Disabling forward_auth_enabled prevents SSO header bypass on /admin endpoints
        cfg = database.get_sso_config()
        cfg["forward_auth_enabled"] = False
        database.set_system_setting("sso_config", cfg)
        disabled_res = self.client.get(
            "/api/admin/users",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-username": "sso_ui_parent",
                "X-authentik-groups": "storydeck-admins",
            },
        )
        self.assertEqual(disabled_res.status_code, 401)

    def test_06_create_sso_prelinked_user_without_local_password(self):
        """Admins can pre-create an SSO-linked account without entering a local password."""
        self._login_session(role="admin", user_id="ui_adm_2", username="ui_admin_2")

        # Local account still requires 8+ char password
        short_res = self.client.post("/api/admin/users", json={
            "username": "sso_ui_local_short",
            "display_name": "Short Pw",
            "role": "member",
            "password": "123",
        })
        self.assertEqual(short_res.status_code, 400)

        # SSO pre-linked account succeeds without password
        sso_res = self.client.post("/api/admin/users", json={
            "username": "sso_ui_prelinked",
            "display_name": "Authentik Uncle",
            "email": "sso_ui_uncle@example.com",
            "role": "member",
            "sso_provider": "authentik",
            "password": "",
        })
        self.assertEqual(sso_res.status_code, 201)
        u = sso_res.get_json()["user"]
        self.assertEqual(u["sso_provider"], "authentik")
        self.assertEqual(u["email"], "sso_ui_uncle@example.com")

    def test_07_sso_initial_match_by_email_then_username_and_uid_binding(self):
        """Matches unbound accounts by email first, then username, binds immutable UID, and survives later renames."""
        # 1. Pre-existing local account with different username but matching email
        by_email_user = database.create_admin_user(
            "sso_ui_local_alice",
            "AliceSecret1!",
            display_name="Alice Local",
            role="admin",
            email="sso_ui_alice@family.local",
        )
        res1 = self.client.get(
            "/api/auth/me",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-uid": "uid_test_alice_001",
                "X-authentik-username": "alice_renamed_in_idp",
                "X-authentik-email": "SSO_UI_ALICE@family.local",
            },
        )
        self.assertEqual(res1.status_code, 200)
        d1 = res1.get_json()["user"]
        self.assertEqual(d1["id"], by_email_user["id"])
        self.assertEqual(d1["role"], "admin")
        self.assertEqual(d1["sso_subject"], "uid_test_alice_001")

        # Subsequent login with BOTH username and email changed in Authentik still resolves by immutable UID
        res1_renamed = self.client.get(
            "/api/auth/me",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-uid": "uid_test_alice_001",
                "X-authentik-username": "totally_new_handle",
                "X-authentik-email": "new.alice@family.local",
            },
        )
        self.assertEqual(res1_renamed.status_code, 200)
        self.assertEqual(res1_renamed.get_json()["user"]["id"], by_email_user["id"])

        # 2. Pre-existing local account matched by case-insensitive username also binds UID & backfills empty email
        by_uname_user = database.create_admin_user(
            "sso_ui_local_bob",
            "BobSecret1!",
            display_name="Bob Local",
            role="member",
        )
        res2 = self.client.get(
            "/api/auth/me",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-uid": "uid_test_bob_002",
                "X-authentik-username": "SSO_UI_LOCAL_BOB",
                "X-authentik-email": "sso_ui_bob@family.local",
            },
        )
        self.assertEqual(res2.status_code, 200)
        d2 = res2.get_json()["user"]
        self.assertEqual(d2["id"], by_uname_user["id"])
        refetched_bob = database.get_user_by_id(by_uname_user["id"])
        self.assertEqual(refetched_bob["sso_subject"], "uid_test_bob_002")
        self.assertEqual(refetched_bob["email"], "sso_ui_bob@family.local")

    def test_08_sso_unmatched_user_auto_added_and_prevents_hijack(self):
        """Unmatched SSO user is auto-added; another UID with same username/email cannot hijack the bound account."""
        # Completely new SSO user -> auto-added as 'member' with bound UID & email
        res_new = self.client.get(
            "/api/auth/me",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-uid": "uid_test_carol_003",
                "X-authentik-username": "sso_ui_carol",
                "X-authentik-email": "sso_ui_carol@family.local",
                "X-authentik-name": "Carol Sitter",
            },
        )
        self.assertEqual(res_new.status_code, 200)
        u_carol = res_new.get_json()["user"]
        self.assertEqual(u_carol["role"], "member")
        self.assertEqual(u_carol["sso_subject"], "uid_test_carol_003")
        carol_db = database.get_user_by_sso_subject("uid_test_carol_003", "authentik")
        self.assertIsNotNone(carol_db)
        self.assertEqual(carol_db["email"], "sso_ui_carol@family.local")

        # Another UID claiming Carol's username and email MUST NOT resolve to Carol's existing DB ID
        res_other = self.client.get(
            "/api/auth/me",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={
                "X-authentik-uid": "uid_test_other_999",
                "X-authentik-username": "sso_ui_carol",
                "X-authentik-email": "sso_ui_carol@family.local",
            },
        )
        self.assertEqual(res_other.status_code, 200)
        u_other = res_other.get_json()["user"]
        self.assertNotEqual(u_other["id"], carol_db["id"])
        self.assertTrue(u_other["username"].startswith("sso_ui_carol_"))
        self.assertEqual(u_other["sso_subject"], "uid_test_other_999")

    def test_09_schema_v13_migration_and_admin_email_subject_crud(self):
        """Verifies schema >= 13 migration, admin UI fields, duplicate email 409, and UID unlink via PUT."""
        import sqlite3
        import tempfile
        from pathlib import Path

        conn = database.get_db_connection()
        try:
            self.assertGreaterEqual(conn.execute("PRAGMA user_version;").fetchone()[0], 13)
            cols = [c[1] for c in conn.execute("PRAGMA table_info(admin_users);").fetchall()]
            self.assertIn("email", cols)
            self.assertIn("sso_subject", cols)
        finally:
            conn.close()

        with tempfile.TemporaryDirectory() as tmpdir:
            p12 = Path(tmpdir) / "v12.db"
            c12 = sqlite3.connect(p12)
            try:
                c12.execute(
                    """
                    CREATE TABLE admin_users (
                        id TEXT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        salt TEXT NOT NULL,
                        display_name TEXT DEFAULT '',
                        role TEXT DEFAULT 'admin',
                        sso_provider TEXT DEFAULT '',
                        is_super_admin BOOLEAN DEFAULT 0,
                        last_login DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                c12.execute("PRAGMA user_version = 12;")
                database.run_schema_migrations(c12)
                self.assertGreaterEqual(c12.execute("PRAGMA user_version;").fetchone()[0], 13)
                m_cols = [c[1] for c in c12.execute("PRAGMA table_info(admin_users);").fetchall()]
                self.assertIn("email", m_cols)
                self.assertIn("sso_subject", m_cols)
            finally:
                c12.close()

        # Admin email & sso_subject CRUD + duplicate rejection + unlink
        self._login_session(role="admin", user_id="ui_adm_v13", username="ui_admin_v13")
        u1 = database.create_admin_user(
            "sso_ui_m1",
            "PassWord1!",
            role="member",
            email="sso_ui_m1@test.local",
            sso_provider="authentik",
            sso_subject="uid_test_m1",
            is_super_admin=False,
        )
        u2 = database.create_admin_user(
            "sso_ui_m2",
            "PassWord1!",
            role="member",
            email="sso_ui_m2@test.local",
            is_super_admin=False,
        )

        dup_email_res = self.client.put(f"/api/admin/users/{u2['id']}", json={"email": "sso_ui_m1@test.local"})
        self.assertEqual(dup_email_res.status_code, 409)

        unlink_res = self.client.put(f"/api/admin/users/{u1['id']}", json={
            "email": "sso_ui_m1_new@test.local",
            "sso_subject": "",
        })
        self.assertEqual(unlink_res.status_code, 200)
        u1_after = unlink_res.get_json()["user"]
        self.assertEqual(u1_after["email"], "sso_ui_m1_new@test.local")
        self.assertEqual(u1_after["sso_subject"], "")


if __name__ == "__main__":
    unittest.main()
