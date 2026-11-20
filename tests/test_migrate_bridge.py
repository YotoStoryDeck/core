"""
Unit test for legacy Yoto Bridge state migration script.
"""
import tests.test_isolation  # noqa: F401 - must precede database/app imports
import unittest
import json
from pathlib import Path
import tempfile
import database
from core.bridge.manager import get_bridge_manager
from scripts.migrate_yoto_bridge import migrate_bridge_state


class TestBridgeMigration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.state_file = self.tmp_path / "state.json"

        # Mock legacy state.json
        legacy_state = {
            "slots": {
                "dino_card": {
                    "slot": "dino_card",
                    "kind": "card",
                    "item_id": "abs_dino_123",
                    "title": "Dinosaur Roar",
                    "yoto_card_id": "yoto_uuid_999",
                    "speed": 1.25,
                    "own_place": True,
                    "layout_id": "lay_1",
                    "layouts": {
                        "lay_1": [
                            {"start": 0.0, "end": 120.0, "title": "Chapter 1: The T-Rex"},
                            {"start": 120.0, "end": 300.0, "title": "Chapter 2: The Volcano"}
                        ]
                    }
                }
            }
        }
        self.state_file.write_text(json.dumps(legacy_state), encoding="utf-8")

    def tearDown(self):
        conn = database.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM bridge_tracks WHERE slot_id = 'dino_card';")
                cur.execute("DELETE FROM bridge_slots WHERE slot_id = 'dino_card';")
        finally:
            conn.close()
        self.tmp_dir.cleanup()

    def test_migrate_bridge_state(self):
        count = migrate_bridge_state(self.state_file)
        self.assertEqual(count, 1)

        mgr = get_bridge_manager()
        slot = mgr.get_slot("dino_card")
        self.assertIsNotNone(slot)
        self.assertEqual(slot["abs_item_id"], "abs_dino_123")
        self.assertEqual(slot["yoto_card_id"], "yoto_uuid_999")
        self.assertEqual(slot["speed"], 1.25)
        self.assertEqual(slot["own_place"], 1)

        tracks = slot.get("tracks", [])
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]["title"], "Chapter 1: The T-Rex")
        self.assertEqual(tracks[1]["title"], "Chapter 2: The Volcano")


if __name__ == "__main__":
    unittest.main()
