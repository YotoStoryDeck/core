"""
Unit tests for StoryDeck Core Bridge Engine & Playlist Management.
Tests slot and track CRUD, profile card assignments, delivery mode overrides,
Yoto Cloud playlist classification, manual deletions, LRU pruning, and catalog deduplication.
"""
import tests.test_isolation  # noqa: F401 - must precede app/database/clients imports
import unittest
from unittest.mock import MagicMock, patch
import json
import sqlite3
from app import app
import database
import clients
from core.bridge.manager import BridgeManager, get_bridge_manager
from core.bridge.offline import prune_evicted_profile_playlists


class TestBridgeEngine(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

        # Seed test profile with default_playback_mode = 'streaming'
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM bridge_tracks;")
                cur.execute("DELETE FROM bridge_slots;")
                cur.execute("DELETE FROM profiles WHERE id = 'test_child';")
                cur.execute("""
                    INSERT INTO profiles (id, display_name, default_playback_mode, offline_retention_limit)
                    VALUES ('test_child', 'Test Child', 'streaming', 3);
                """)
        finally:
            conn.close()

    def tearDown(self):
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM bridge_tracks;")
                cur.execute("DELETE FROM bridge_slots;")
                cur.execute("DELETE FROM profiles WHERE id = 'test_child';")
        finally:
            conn.close()
        self.app_context.pop()

    def test_bridge_manager_slot_crud(self):
        """Verifies slot creation, speed clamping, own_place, and pin toggling."""
        mgr = get_bridge_manager()

        # 1. Assign book to fleet slot
        slot = mgr.assign_abs_book_to_slot(
            slot_id="fleet_dino",
            abs_item_id="item_123",
            title="Dinosaur Adventures",
            author="Author Dan",
            kind="permanent_myo",
            mode="streaming"
        )
        self.assertIsNotNone(slot)
        self.assertEqual(slot["slot_id"], "fleet_dino")
        self.assertEqual(slot["title"], "Dinosaur Adventures")

        # 2. Speed clamping test
        mgr.set_slot_speed("fleet_dino", 3.5)  # should clamp to 2.0
        slot = mgr.get_slot("fleet_dino")
        self.assertEqual(slot["speed"], 2.0)

        mgr.set_slot_speed("fleet_dino", 0.1)  # should clamp to 0.5
        slot = mgr.get_slot("fleet_dino")
        self.assertEqual(slot["speed"], 0.5)

        # 3. Own place and Pin toggle
        mgr.set_slot_own_place("fleet_dino", True)
        mgr.set_slot_pin("fleet_dino", True)
        slot = mgr.get_slot("fleet_dino")
        self.assertEqual(slot["own_place"], 1)
        self.assertEqual(slot["is_pinned"], 1)
        self.assertEqual(slot["is_protected"], 1)

    def test_profile_primary_card_assignment_and_mode_override(self):
        """Verifies profile primary card inherits profile default or applies override."""
        mgr = get_bridge_manager()

        # Case A: Mode omitted -> inherits profile default ("streaming")
        slot_stream = mgr.update_profile_primary_card(
            profile_id="test_child",
            abs_item_id="abs_book_1",
            mode_override="default"
        )
        self.assertEqual(slot_stream["slot_id"], "profile_test_child")
        self.assertEqual(slot_stream["mode"], "streaming")
        self.assertEqual(slot_stream["kind"], "profile_primary")

        # Case B: Mode overridden to "offline"
        slot_offline = mgr.update_profile_primary_card(
            profile_id="test_child",
            abs_item_id="abs_book_2",
            mode_override="offline"
        )
        self.assertEqual(slot_offline["mode"], "offline")

    def test_api_cards_endpoints(self):
        """Tests /api/cards REST operations."""
        mgr = get_bridge_manager()
        mgr.assign_abs_book_to_slot(
            slot_id="slot_mobile",
            abs_item_id="item_abc",
            title="Mobile Book",
            author="Jane Doe"
        )

        # GET /api/cards
        res = self.app.get("/api/cards")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(any(s["slot_id"] == "slot_mobile" for s in data))

        # PUT /api/cards/<slot_id>
        res = self.app.put("/api/cards/slot_mobile", json={"speed": 1.25, "is_pinned": True})
        self.assertEqual(res.status_code, 200)
        updated = res.get_json()
        self.assertEqual(updated["speed"], 1.25)
        self.assertEqual(updated["is_pinned"], 1)

        # DELETE /api/cards/<slot_id>
        res = self.app.delete("/api/cards/slot_mobile")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(mgr.get_slot("slot_mobile"))

    def test_yoto_playlists_classification(self):
        """Tests /api/yoto/playlists enriches cloud playlists with broker vs custom source and pin state."""
        mgr = get_bridge_manager()
        mgr.assign_abs_book_to_slot(
            slot_id="broker_slot_1",
            abs_item_id="item_xyz",
            title="StoryDeck Audiobook"
        )
        mgr.set_slot_pin("broker_slot_1", True)

        mock_playlists = [
            {
                "cardId": "broker_slot_1",
                "title": "StoryDeck Audiobook",
                "metadata": {"description": "Streams from Audiobookshelf via StoryDeck Core"}
            },
            {
                "cardId": "custom_yoto_card",
                "title": "Bedtime Lullabies",
                "shareType": "myo",
                "metadata": {"description": "Recorded songs from grandma"}
            }
        ]

        with patch.object(clients.yoto_client, "get_all_cloud_playlists", return_value=mock_playlists):
            res = self.app.get("/api/yoto/playlists")
            self.assertEqual(res.status_code, 200)
            items = res.get_json()
            self.assertEqual(len(items), 2)

            broker_item = next(x for x in items if x["card_id"] == "broker_slot_1")
            custom_item = next(x for x in items if x["card_id"] == "custom_yoto_card")

            self.assertEqual(broker_item["source"], "broker")
            self.assertTrue(broker_item["is_pinned"])

            self.assertEqual(custom_item["source"], "custom")
            self.assertTrue(custom_item["is_physical"])
            self.assertFalse(custom_item["is_pinned"])

    def test_lru_pruning_protects_pinned_and_active_recent_items(self):
        """Verifies LRU cache pruning only removes unpinned evicted items."""
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                # Slot 1: Active recent book (should survive)
                cur.execute("""
                    INSERT INTO bridge_slots (slot_id, abs_item_id, owner_profile_id, title, kind, mode, is_pinned, is_protected)
                    VALUES ('slot_active', 'book_active', 'test_child', 'Active Book', 'ephemeral_offline', 'offline', 0, 0);
                """)
                # Slot 2: Evicted book but PINNED (should survive)
                cur.execute("""
                    INSERT INTO bridge_slots (slot_id, abs_item_id, owner_profile_id, title, kind, mode, is_pinned, is_protected)
                    VALUES ('slot_pinned', 'book_old_pinned', 'test_child', 'Pinned Old Book', 'ephemeral_offline', 'offline', 1, 1);
                """)
                # Slot 3: Evicted book UNPINNED (should be pruned)
                cur.execute("""
                    INSERT INTO bridge_slots (slot_id, abs_item_id, owner_profile_id, title, kind, mode, is_pinned, is_protected)
                    VALUES ('slot_evicted', 'book_old_evicted', 'test_child', 'Evicted Old Book', 'ephemeral_offline', 'offline', 0, 0);
                """)
        finally:
            conn.close()

        # Set playback history so only 'book_active' is in recent
        database.record_playback("book_active", "test_child")

        with patch.object(clients.yoto_client, "delete_playlist", return_value=True) as mock_del:
            result = prune_evicted_profile_playlists()
            self.assertEqual(result["pruned_count"], 1)
            self.assertEqual(result["pruned_items"][0]["slot_id"], "slot_evicted")
            mock_del.assert_called_once_with("slot_evicted")

        # Verify database state
        mgr = get_bridge_manager()
        self.assertIsNotNone(mgr.get_slot("slot_active"))
        self.assertIsNotNone(mgr.get_slot("slot_pinned"))
        self.assertIsNone(mgr.get_slot("slot_evicted"))

    def test_catalog_deduplication(self):
        """Verifies get_raw_library filters out broker-created playlists so they don't duplicate ABS items."""
        mgr = get_bridge_manager()
        mgr.assign_abs_book_to_slot(
            slot_id="profile_test_child",
            abs_item_id="book_123",
            title="Profile Active Book"
        )

        mock_library = [
            {"cardId": "profile_test_child", "title": "Profile Active Book", "metadata": {"generator": "storydeck-core"}},
            {"cardId": "retail_card_999", "title": "Disney Frozen", "metadata": {"author": "Disney"}}
        ]

        with patch.object(clients.yoto_client, "load_local_family_library", return_value=[]), \
             patch.object(clients.yoto_client, "get_token", return_value="fake_token"), \
             patch("requests.get") as mock_get:

            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.json.return_value = {"cards": mock_library}
            mock_get.return_value = mock_res

            raw_catalog = clients.yoto_client.get_raw_library()
            card_ids = [c.get("cardId") for c in raw_catalog]

            self.assertIn("retail_card_999", card_ids)
            self.assertNotIn("profile_test_child", card_ids)


if __name__ == "__main__":
    unittest.main()
