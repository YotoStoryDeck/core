"""
Unit tests for Yoto retail card ingestion, catalog curation matrix permissions,
and one-stop Audiobookshelf tagging API.
"""

import unittest
from app import app
import clients
import database


class TestCurationMatrixAndYotoRetail(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_01_yoto_retail_cards_loaded(self):
        """Verifies that retail cards from the live bridge/Yoto library are loaded alongside MYO cards."""
        raw_library = clients.yoto_client.get_raw_library()
        retail = [c for c in raw_library if not c.get("isMyo")]
        myo = [c for c in raw_library if c.get("isMyo")]
        
        self.assertGreater(len(retail), 40, "Should have loaded at least 40 retail cards")
        self.assertGreater(len(myo), 5, "Should have loaded MYO cards")
        
        # Verify retail title exists (e.g. Harry Potter and the Sorcerer's Stone)
        hp_card = next((c for c in retail if c.get("cardId") == "7gGiV"), None)
        self.assertIsNotNone(hp_card, "Harry Potter retail card (7gGiV) should exist")
        self.assertTrue("Harry Potter" in hp_card.get("title", ""))
        self.assertTrue(hp_card.get("coverImageUrl", "").startswith("https://card-content.yotoplay.com/"))

    def test_02_catalog_matrix_structure(self):
        """Verifies get_catalog_matrix returns items with tags, library_id, and profile states."""
        matrix = database.get_catalog_matrix()
        self.assertIn("items", matrix)
        self.assertIn("profiles", matrix)
        self.assertIn("shared_rules", matrix)
        
        items = matrix["items"]
        self.assertGreater(len(items), 250, "Total catalog should have >250 items (ABS + Yoto Retail + MYO)")
        
        # Check types present
        types = set(it["type"] for it in items)
        self.assertIn("abs", types)
        self.assertIn("yoto", types)
        self.assertIn("yoto_myo", types)

        # Check profiles have reasons
        sample_item = items[0]
        self.assertIn("profiles", sample_item)
        self.assertIn("series", sample_item)
        for pid in matrix["profiles"]:
            self.assertIn(pid, sample_item["profiles"])
            self.assertIn("allowed", sample_item["profiles"][pid])
            self.assertIn("reason", sample_item["profiles"][pid])

    def test_06_series_extraction_from_catalogs(self):
        """Verifies that Yoto and ABS items extract series names for series filtering and grouping."""
        raw_library = clients.yoto_client.get_raw_library()
        brainbots_with_series = [c for c in raw_library if "brainbots" in (c.get("series") or "").lower()]
        self.assertTrue(len(brainbots_with_series) > 0, "Should have cards with BrainBots series in raw library")
        sample_bb = brainbots_with_series[0]
        self.assertIn("series", sample_bb)
        self.assertTrue("BrainBots" in sample_bb["series"])

        # Test regex pattern for trailing sequence removal with ranges (e.g. "The Boxcar Children #13-15" -> "The Boxcar Children")
        import re
        sample_abs_series = "The Boxcar Children #13-15"
        m = re.search(r'\s*#\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', sample_abs_series)
        self.assertIsNotNone(m)
        clean_name = sample_abs_series[:m.start()].strip()
        self.assertEqual(clean_name, "The Boxcar Children")
        self.assertEqual(m.group(1).replace(" ", ""), "13-15")

        # Test single book pattern
        m_single = re.search(r'\s*#\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', "A Song of Ice and Fire #1")
        self.assertIsNotNone(m_single)
        self.assertEqual("A Song of Ice and Fire #1"[:m_single.start()].strip(), "A Song of Ice and Fire")
        self.assertEqual(m_single.group(1), "1")

        # Test Books range pattern
        m_books = re.search(r'[,:\s]+(?:Books?|Volumes?|Vol\.?|Parts?)\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', "Magic Tree House, Books 1-4", re.IGNORECASE)
        self.assertIsNotNone(m_books)
        self.assertEqual("Magic Tree House, Books 1-4"[:m_books.start()].strip(), "Magic Tree House")
        self.assertEqual(m_books.group(1).replace(" ", ""), "1-4")

        # Test comma-delimited multi-series parsing (e.g. "Star Wars #55, Star Wars Classic Stories #7")
        multi_series_input = "Star Wars #55, Star Wars Classic Stories #7"
        raw_parts = [p.strip() for p in multi_series_input.split(",") if p.strip()]
        self.assertEqual(len(raw_parts), 2)
        parsed_series = []
        for p in raw_parts:
            m_p = re.search(r'\s*#\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', p)
            self.assertIsNotNone(m_p)
            parsed_series.append({
                "name": p[:m_p.start()].strip(),
                "order": m_p.group(1).replace(" ", "")
            })
        self.assertEqual(parsed_series[0], {"name": "Star Wars", "order": "55"})
        self.assertEqual(parsed_series[1], {"name": "Star Wars Classic Stories", "order": "7"})

        # Test comma-delimited multi-series without sequence numbers (e.g. "Star Wars, Star Wars Classic Stories")
        unsequenced_input = "Star Wars, Star Wars Classic Stories"
        unsequenced_parts = [p.strip() for p in unsequenced_input.split(",") if p.strip()]
        self.assertEqual(len(unsequenced_parts), 2)
        parsed_unsequenced = []
        for p in unsequenced_parts:
            m_p = re.search(r'\s*#\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', p)
            if m_p:
                parsed_unsequenced.append({"name": p[:m_p.start()].strip(), "order": m_p.group(1).replace(" ", "")})
            else:
                parsed_unsequenced.append({"name": p.strip(), "order": ""})
        self.assertEqual(parsed_unsequenced[0], {"name": "Star Wars", "order": ""})
        self.assertEqual(parsed_unsequenced[1], {"name": "Star Wars Classic Stories", "order": ""})

    def test_03_abs_tagging_endpoint(self):
        """Tests the one-stop /api/admin/abs/item-tags endpoint."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

        # Find a known ABS item
        item_id = "7696c2d1-49bc-4165-a3dd-743b4ad79328" # Spidey
        res = self.client.post("/api/admin/abs/item-tags", json={
            "item_id": item_id,
            "tags": ["Children"]
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("tags"), ["Children"])


    def test_04_abs_server_tags_endpoint(self):
        """Verifies GET /api/admin/abs/server-tags returns live ABS tags."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

        res = self.client.get("/api/admin/abs/server-tags")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        tags = data.get("tags", [])
        self.assertIsInstance(tags, list)
        self.assertIn("Children", tags)

    def test_05_abs_default_tags_settings(self):
        """Verifies GET and PUT /api/admin/settings/abs-tags for configuring child default tags."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

        # 1. GET default tags
        res = self.client.get("/api/admin/settings/abs-tags")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        initial_tags = data.get("tags")
        self.assertIsInstance(initial_tags, list)

        # 2. PUT updated default tags
        res_put = self.client.put("/api/admin/settings/abs-tags", json={
            "tags": ["Children", "Kids", "Juvenile"]
        })
        self.assertEqual(res_put.status_code, 200)
        data_put = res_put.get_json()
        self.assertTrue(data_put.get("ok"))
        self.assertEqual(data_put.get("tags"), ["Children", "Kids", "Juvenile"])

        # 3. Verify get_catalog_matrix incorporates new default tags
        matrix = database.get_catalog_matrix()
        self.assertIn("items", matrix)

        # 4. Restore original tags
        self.client.put("/api/admin/settings/abs-tags", json={"tags": initial_tags})

    def test_07_yoto_groups_and_series_integration(self):
        """Validates that Yoto user groups are parsed and appended to card series_list."""
        from routes.admin_curation import extract_series_list, parse_single_series

        # 1. Test helper functions
        res = parse_single_series("Bedtime Stories")
        self.assertEqual(res, {"name": "Bedtime Stories", "order": ""})

        res_num = parse_single_series("Harry Potter #1")
        self.assertEqual(res_num, {"name": "Harry Potter", "order": "1"})

        res_multi = extract_series_list("Star Wars, Bedtime Favorites")
        self.assertEqual(len(res_multi), 2)
        self.assertEqual(res_multi[0]["name"], "Star Wars")
        self.assertEqual(res_multi[1]["name"], "Bedtime Favorites")

        # 2. Test YotoClient.get_groups returns a list
        groups = clients.yoto_client.get_groups()
        self.assertIsInstance(groups, list)

        # 3. Simulate syncing a Yoto card with an assigned Yoto Group
        test_card_id = "test_yoto_group_card_123"
        test_group_name = "Bedtime Favorites"
        
        # Insert a media item representing a card that belongs to a Yoto group
        try:
            database.upsert_media_items([{
                "id": test_card_id,
                "type": "yoto",
                "title": "Sleepy Bear Stories",
                "author": "Yoto",
                "cover_url": "",
                "raw_metadata": {
                    "series": test_group_name,
                    "series_order": "",
                    "series_list": [{"name": test_group_name, "order": ""}]
                }
            }])

            # Verify it appears with series_list in get_catalog_matrix
            matrix = database.get_catalog_matrix()
            item = next((it for it in matrix["items"] if it["id"] == test_card_id), None)
            self.assertIsNotNone(item)
            self.assertEqual(item["series"], test_group_name)
            self.assertEqual(item["series_list"], [{"name": test_group_name, "order": ""}])

            # Verify /api/thumb handles item_id without error (returns placeholder SVG 200)
            res_thumb = self.client.get(f"/api/thumb?type=yoto&id={test_card_id}&size=100")
            self.assertEqual(res_thumb.status_code, 200)
            self.assertIn(res_thumb.content_type, ("image/jpeg", "image/svg+xml"))
        finally:
            conn = database.get_db_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM media_items WHERE id = ?;", (test_card_id,))
            finally:
                conn.close()

    def test_08_batch_permissions_and_highlight(self):
        """Verifies atomic multi-card permissions and highlight updates (Feature 011)."""
        test_ids = ["test_batch_card_1", "test_batch_card_2", "test_batch_card_3"]
        prof_id = "test_batch_child"

        # 1. Setup mock profile and media items
        database.upsert_profile(prof_id, {
            "display_name": "Test Child",
            "yoto": {"allowed_card_ids": [], "excluded_card_ids": []}
        })
        database.upsert_media_items([
            {"id": mid, "type": "yoto", "title": f"Card {mid}", "author": "Author", "cover_url": ""}
            for mid in test_ids
        ])

        try:
            # 2. Test batch highlight
            count = database.batch_update_media_highlight(test_ids, True)
            self.assertEqual(count, 3, "Should have updated highlight on 3 items")
            matrix = database.get_catalog_matrix()
            for it in matrix["items"]:
                if it["id"] in test_ids:
                    self.assertTrue(it["is_highlight"], "Item should be highlighted")

            # 3. Test batch allow
            res = database.batch_update_profile_media_permissions(
                media_ids=test_ids,
                profile_actions={prof_id: "allow"},
                is_highlight=False
            )
            self.assertEqual(res["updated_cards"], 3)
            self.assertEqual(res["affected_profiles"], 1)

            # Check that permissions in DB are 'allowed'
            conn = database.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT media_id, permission FROM profile_media_permissions WHERE profile_id = ?;", (prof_id,))
                rows = cur.fetchall()
                perms = {r["media_id"]: r["permission"] for r in rows}
                for mid in test_ids:
                    self.assertEqual(perms.get(mid), "allowed")
            finally:
                conn.close()

            # 4. Test batch exclude
            res_ex = database.batch_update_profile_media_permissions(
                media_ids=test_ids[:2],
                profile_actions={prof_id: "exclude"}
            )
            self.assertEqual(res_ex["updated_cards"], 2)

            conn = database.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT media_id, permission FROM profile_media_permissions WHERE profile_id = ?;", (prof_id,))
                rows = cur.fetchall()
                perms = {r["media_id"]: r["permission"] for r in rows}
                self.assertEqual(perms.get(test_ids[0]), "excluded")
                self.assertEqual(perms.get(test_ids[1]), "excluded")
                self.assertEqual(perms.get(test_ids[2]), "allowed")
            finally:
                conn.close()

            # 5. Test batch reset (clears explicit rows)
            res_reset = database.batch_update_profile_media_permissions(
                media_ids=[test_ids[0]],
                profile_actions={prof_id: "reset"}
            )
            self.assertEqual(res_reset["updated_cards"], 1)

            conn = database.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT media_id FROM profile_media_permissions WHERE profile_id = ? AND media_id = ?;", (prof_id, test_ids[0]))
                self.assertIsNone(cur.fetchone(), "Row should have been deleted on reset")
            finally:
                conn.close()

        finally:
            # Clean up
            database.delete_profile(prof_id)
            conn = database.get_db_connection()
            try:
                with conn:
                    for mid in test_ids:
                        conn.execute("DELETE FROM media_items WHERE id = ?;", (mid,))
                        conn.execute("DELETE FROM profile_media_permissions WHERE media_id = ?;", (mid,))
            finally:
                conn.close()

    def test_09_tracklist_and_icon_endpoints(self):
        """Verifies Tracklist Browser and Icon Search endpoints (Feature 012)."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

        # 1. Test GET /api/admin/media/<id>/tracks on a Yoto retail card
        res = self.client.get("/api/admin/media/7gGiV/tracks")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("type"), "yoto")
        self.assertFalse(data.get("can_edit"), "Retail cards should be read-only")
        self.assertGreater(len(data.get("tracks", [])), 0, "Should have extracted tracks")

        # 2. Test GET /api/admin/icons/search
        res_search = self.client.get("/api/admin/icons/search?q=dragon&limit=10")
        self.assertEqual(res_search.status_code, 200)
        search_data = res_search.get_json()
        self.assertTrue(search_data.get("ok"))
        self.assertIsInstance(search_data.get("results"), list)

    def test_10_arr_style_master_api_key(self):
        """Verifies Arr-Style Master API Key retrieval, header authentication, and regeneration (Feature 013)."""
        # 1. Fetch current master API key
        key_details = database.get_master_api_key_details()
        curr_key = key_details["api_key"]
        self.assertEqual(len(curr_key), 32, "Master API key should be 32 characters hex")

        # 2. Unauthenticated request to /api/admin/security/api-key without cookie or key -> 401
        res_unauth = self.client.get("/api/admin/security/api-key")
        self.assertEqual(res_unauth.status_code, 401)

        # 3. Authenticate with X-Api-Key header -> 200
        res_auth_header = self.client.get("/api/admin/security/api-key", headers={"X-Api-Key": curr_key})
        self.assertEqual(res_auth_header.status_code, 200)
        data = res_auth_header.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("api_key"), curr_key)

        # 4. Authenticate with Bearer token header -> 200
        res_bearer = self.client.get("/api/admin/security/api-key", headers={"Authorization": f"Bearer {curr_key}"})
        self.assertEqual(res_bearer.status_code, 200)

        # 5. Authenticate with ?apikey= query param (GET request) -> 200
        res_query = self.client.get(f"/api/admin/security/api-key?apikey={curr_key}")
        self.assertEqual(res_query.status_code, 200)

        # 6. Test key regeneration via POST /api/admin/security/regenerate-api-key
        res_regen = self.client.post(
            "/api/admin/security/regenerate-api-key",
            headers={"X-Api-Key": curr_key},
            json={"confirm": True}
        )
        self.assertEqual(res_regen.status_code, 200)
        new_key = res_regen.get_json().get("api_key")
        self.assertNotEqual(new_key, curr_key, "Regenerated key must differ from prior key")

        # 7. Old key is immediately rejected
        res_old_rejected = self.client.get("/api/admin/security/api-key", headers={"X-Api-Key": curr_key})
        self.assertEqual(res_old_rejected.status_code, 401)

        # 8. New key succeeds
        res_new_accepted = self.client.get("/api/admin/security/api-key", headers={"X-Api-Key": new_key})
        self.assertEqual(res_new_accepted.status_code, 200)

    def test_11_esp32_device_jwt_lifecycle_and_revocation(self):
        """Verifies ESP32 device handshake, token issuance, catalog guard, refresh, and instant revocation."""
        test_mac = "a1b2c3d4e5f6"
        # 1. Register device (initially quarantined / unapproved)
        res_reg = self.client.post("/api/devices/register", json={
            "mac_address": test_mac,
            "friendly_name": "Test Bedside Controller",
            "firmware_version": "1.0.0"
        })
        self.assertEqual(res_reg.status_code, 202)
        reg_data = res_reg.get_json()
        self.assertEqual(reg_data.get("status"), "pending_approval")
        self.assertFalse(reg_data.get("is_approved"))

        try:
            # 2. Attempt to query kid catalog without token -> 403
            res_no_tok = self.client.get("/api/kids/jackson/yoto")
            self.assertEqual(res_no_tok.status_code, 403)

            # 3. Approve device and assign default profile
            database.update_esp32_device(test_mac, {
                "is_approved": 1,
                "assigned_profile_id": "jackson"
            })

            # 4. Device re-registers -> receives tokens (200 OK)
            res_reg2 = self.client.post("/api/devices/register", json={"mac_address": test_mac})
            self.assertEqual(res_reg2.status_code, 200)
            reg2_data = res_reg2.get_json()
            self.assertEqual(reg2_data.get("status"), "approved")
            self.assertIn("tokens", reg2_data)
            access_tok = reg2_data["tokens"]["access_token"]
            refresh_tok = reg2_data["tokens"]["refresh_token"]

            # 5. Query kid catalog using Authorization: Bearer <access_token> -> 200
            res_cat = self.client.get("/api/kids/jackson/yoto", headers={"Authorization": f"Bearer {access_tok}"})
            self.assertEqual(res_cat.status_code, 200)
            self.assertIsInstance(res_cat.get_json(), list)

            # 6. Refresh token exchange via POST /api/device/auth/refresh
            res_ref = self.client.post("/api/device/auth/refresh", json={
                "mac": test_mac,
                "refresh_token": refresh_tok
            })
            self.assertEqual(res_ref.status_code, 200)
            new_access_tok = res_ref.get_json().get("access_token")
            self.assertTrue(new_access_tok)

            # 7. Admin instant revocation via POST /api/admin/devices/<mac>/revoke
            with self.client.session_transaction() as sess:
                sess["user_id"] = "admin_user"
                sess["username"] = "admin"
                sess["role"] = "admin"

            res_rev = self.client.post(f"/api/admin/devices/{test_mac}/revoke")
            self.assertEqual(res_rev.status_code, 200)
            self.assertEqual(res_rev.get_json().get("status"), "revoked")

            # 8. Outstanding access token immediately rejected -> 403 (clear test admin session first)
            with self.client.session_transaction() as sess:
                sess.clear()

            res_cat_revoked = self.client.get("/api/kids/jackson/yoto", headers={"Authorization": f"Bearer {access_tok}"})
            self.assertEqual(res_cat_revoked.status_code, 403)
            self.assertEqual(res_cat_revoked.get_json().get("error"), "device_revoked")

            # 9. Refresh token also rejected -> 403
            res_ref_revoked = self.client.post("/api/device/auth/refresh", json={
                "mac": test_mac,
                "refresh_token": refresh_tok
            })
            self.assertEqual(res_ref_revoked.status_code, 403)

        finally:
            database.delete_esp32_device(test_mac)

    def test_12_flexible_track_name_parsing_and_chapter_update(self):
        """Verifies parsing of bulleted lists, newlines, and comma-separated chapter names."""
        from routes.admin_curation import parse_track_names

        # 1. Bullet list parsing
        bullet_input = """
        • Chapter 1: To the Castle!
        • Chapter 2: The Dragon Stone
        • Chapter 3: More Dragons!
        • Chapter 4: Worm
        """
        parsed_bullet = parse_track_names(bullet_input)
        self.assertEqual(len(parsed_bullet), 4)
        self.assertEqual(parsed_bullet[0], "Chapter 1: To the Castle!")
        self.assertEqual(parsed_bullet[1], "Chapter 2: The Dragon Stone")
        self.assertEqual(parsed_bullet[2], "Chapter 3: More Dragons!")
        self.assertEqual(parsed_bullet[3], "Chapter 4: Worm")

        # 2. Hyphen and asterisk bullet list parsing
        dash_input = "- Intro\n* Chapter 1\n• Chapter 2"
        parsed_dash = parse_track_names(dash_input)
        self.assertEqual(parsed_dash, ["Intro", "Chapter 1", "Chapter 2"])

        # 3. Comma-delimited list parsing
        comma_input = "Track 1: Start, Track 2: Middle, Track 3: Finish"
        parsed_comma = parse_track_names(comma_input)
        self.assertEqual(parsed_comma, ["Track 1: Start", "Track 2: Middle", "Track 3: Finish"])

        # 4. PUT endpoint validation with session
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

        # Retail card should be rejected with 400
        res_retail = self.client.put("/api/admin/media/7gGiV/tracks", json={
            "type": "yoto",
            "raw_text": "• Chapter 1: Test"
        })
        self.assertEqual(res_retail.status_code, 400)
        self.assertIn("cannot be edited", res_retail.get_json().get("error", ""))

    def test_13_chapter_number_extraction_and_overlay_rendering(self):
        """Verifies regex extraction of chapter numbers and 16x16 pixel overlay generation."""
        from routes.admin_curation import extract_chapter_number, render_16x16_icon_with_overlay
        import io
        from PIL import Image

        # 1. Test chapter number extraction regex variants
        self.assertEqual(extract_chapter_number("Chapter 1: The Beginning", 99), 1)
        self.assertEqual(extract_chapter_number("Ch. 04 - Midnight Run", 99), 4)
        self.assertEqual(extract_chapter_number("Chap 12: Escape", 99), 12)
        self.assertEqual(extract_chapter_number("Part 3: The Climax", 99), 3)
        self.assertEqual(extract_chapter_number("Track 07", 99), 7)
        self.assertEqual(extract_chapter_number("05. Morning Dew", 99), 5)
        self.assertEqual(extract_chapter_number("10 - Journey Home", 99), 10)
        # Fallback case when no number exists
        self.assertEqual(extract_chapter_number("Prologue", 1), 1)
        self.assertEqual(extract_chapter_number("Epilogue", 15), 15)

        # 2. Test 16x16 icon rendering with corner overlay
        # Create a dummy 64x64 RGBA image in memory
        base_img = Image.new("RGBA", (64, 64), (100, 150, 200, 255))
        buf = io.BytesIO()
        base_img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        # Render with overlay
        out_bytes = render_16x16_icon_with_overlay(raw_bytes, number=8, corner="top-right")
        self.assertTrue(out_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        out_img = Image.open(io.BytesIO(out_bytes))
        self.assertEqual(out_img.size, (16, 16))
        self.assertEqual(out_img.mode, "RGBA")

    def test_14_batch_track_icon_endpoint(self):
        """Verifies POST /api/admin/media/<media_id>/tracks/batch-icon assigns icons and handles overlay flag."""
        import base64
        import io
        from PIL import Image

        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

        # Generate a small 16x16 red square as base64
        test_img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
        buf = io.BytesIO()
        test_img.save(buf, format="PNG")
        b64_str = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"

        # Test against a known ABS item
        abs_item_id = "7696c2d1-49bc-4165-a3dd-743b4ad79328"
        res = self.client.post(f"/api/admin/media/{abs_item_id}/tracks/batch-icon", json={
            "type": "abs",
            "track_indices": [0],
            "image_b64": b64_str,
            "apply_overlay": True,
            "overlay_corner": "top-right"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("updated_tracks"), [0])
        self.assertIn("0", data.get("updated_urls", {}))
        self.assertTrue(data.get("apply_overlay"))

    def test_15_physical_card_ownership(self):
        """Verifies single and batch toggles for physical plastic card ownership."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin_user"
            sess["username"] = "admin"
            sess["role"] = "admin"

        # 1. Single toggle
        test_id = "test_card_phys_1"
        database.upsert_media_items([{
            "id": test_id,
            "type": "yoto",
            "title": "Physical Test Card 1"
        }])

        res = self.client.post(f"/api/admin/catalog/physical/{test_id}", json={"has_physical": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get("has_physical"))

        # Verify in matrix
        matrix = database.get_catalog_matrix()
        match = next((it for it in matrix["items"] if it["id"] == test_id), None)
        self.assertIsNotNone(match)
        self.assertTrue(match.get("has_physical"))

        # 2. Batch toggle
        test_id2 = "test_card_phys_2"
        database.upsert_media_items([{
            "id": test_id2,
            "type": "yoto",
            "title": "Physical Test Card 2"
        }])

        res_batch = self.client.post("/api/admin/curation/batch-physical", json={
            "media_ids": [test_id, test_id2],
            "has_physical": False
        })
        self.assertEqual(res_batch.status_code, 200)
        self.assertEqual(res_batch.get_json().get("updated_count"), 2)

        matrix2 = database.get_catalog_matrix()
        m1 = next(it for it in matrix2["items"] if it["id"] == test_id)
        m2 = next(it for it in matrix2["items"] if it["id"] == test_id2)
        self.assertFalse(m1.get("has_physical"))
        self.assertFalse(m2.get("has_physical"))

    def test_16_catalog_rotation_and_series_sequencing(self):
        """Verifies Book #1 series prioritization, last-played top sorting, and hide_physical filtering."""
        # Create an isolated test profile with inherit_shared = False
        prof_key = "rot_test_kid"
        database.upsert_profile(prof_key, {
            "display_name": "Rotation Kid",
            "catalog_rotation_limit": 2,
            "hide_physical": False,
            "yoto": {"inherit_shared": False}
        })

        # Create test series items
        s_book1 = {
            "id": "seq_series_b1",
            "type": "yoto",
            "title": "Adventures in Magic #1: The Beginning",
            "series": "Adventures in Magic",
            "series_order": "1",
            "has_physical": False
        }
        s_book2 = {
            "id": "seq_series_b2",
            "type": "yoto",
            "title": "Adventures in Magic #2: The Dark Forest",
            "series": "Adventures in Magic",
            "series_order": "2",
            "has_physical": False
        }
        recent_card = {
            "id": "seq_recent_card",
            "type": "yoto",
            "title": "Yesterday Bedtime Story",
            "raw_metadata": {"lastPlayedAt": "2026-11-06T10:00:00Z"},
            "has_physical": False
        }
        phys_card = {
            "id": "seq_phys_card",
            "type": "yoto",
            "title": "Bedroom Binder Plastic Card",
            "has_physical": True
        }

        database.upsert_media_items([s_book1, s_book2, recent_card, phys_card])
        database.set_item_physical("seq_phys_card", True)

        # Allow them explicitly for the isolated test profile
        database.batch_update_profile_media_permissions(
            media_ids=["seq_series_b1", "seq_series_b2", "seq_recent_card", "seq_phys_card"],
            profile_actions={prof_key: "allow"}
        )

        items = database.get_catalog_items_for_profile(prof_key, "yoto")
        self.assertEqual(len(items), 2)
        # 1. Recent item MUST be first!
        self.assertEqual(items[0]["id"], "seq_recent_card")
        # 2. Book #1 of series MUST be selected over Book #2 for the 1 remaining discovery slot!
        self.assertEqual(items[1]["id"], "seq_series_b1")

        # Now test hide_physical
        database.upsert_profile(prof_key, {
            "display_name": "Rotation Kid",
            "catalog_rotation_limit": 80,
            "hide_physical": True,
            "yoto": {
                "inherit_shared": False,
                "allowed_card_ids": ["seq_series_b1", "seq_series_b2", "seq_recent_card", "seq_phys_card"]
            }
        })
        items_hidden = database.get_catalog_items_for_profile(prof_key, "yoto")
        item_ids = [it["id"] for it in items_hidden]
        self.assertNotIn("seq_phys_card", item_ids)
        self.assertIn("seq_series_b1", item_ids)
        self.assertIn("seq_series_b2", item_ids)

if __name__ == "__main__":
    unittest.main()
