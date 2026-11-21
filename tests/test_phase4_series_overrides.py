"""
Unit & integration tests for Phase 4: Yoto Card Manual Series & Sequence Overrides (DLP-021).
"""

import tests.test_isolation  # noqa: F401 - must precede app/clients/database imports
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import app
import database


class TestPhase4SeriesOverrides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        self.client = app.test_client()
        conn = database.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM media_series_overrides;")
                conn.execute("DELETE FROM profile_media_permissions WHERE media_id LIKE 'p4_%';")
                conn.execute("DELETE FROM media_items WHERE id LIKE 'p4_%';")
                conn.execute("DELETE FROM profiles WHERE id = 'p4_child';")
        finally:
            conn.close()

        database.upsert_profile("p4_child", {
            "display_name": "P4 Child",
            "catalog_rotation_limit": 60,
            "yoto": {"inherit_shared": True},
        })
        database.set_shared_rule("include_all", True)
        database.set_shared_rule("include_myo_by_default", True)

        database.upsert_media_items([
            {
                "id": "p4_yoto_1",
                "type": "yoto",
                "title": "The Dragon's Prophecy",
                "author": "Yoto Studio",
                "cover_url": "https://cdn.example.com/dragon1.jpg",
                "raw_metadata": {"series": "AutoOldSeries", "series_order": "9"},
            },
            {
                "id": "p4_yoto_2",
                "type": "yoto",
                "title": "Lost Treasure of the Isles",
                "author": "Yoto Studio",
                "cover_url": "https://cdn.example.com/dragon2.jpg",
                "raw_metadata": {},
            },
            {
                "id": "p4_myo_1",
                "type": "yoto_myo",
                "title": "Secret Bridge Story",
                "author": "Parents",
                "cover_url": "https://cdn.example.com/dragon15.jpg",
                "raw_metadata": {"series": "TempGroup", "series_order": "3"},
            },
            {
                "id": "p4_abs_1",
                "type": "abs",
                "title": "Audiobook Item",
                "author": "ABS Author",
                "raw_metadata": {"series": "Native ABS Series", "series_order": "1", "tags": ["Children"]},
            },
        ])

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = "p4_admin"
            sess["username"] = "admin"
            sess["role"] = "admin"

    def test_01_schema_v11_and_synthetic_v10_upgrade(self):
        """Verifies live test DB is at schema v11 and a synthetic v10 DB migrates cleanly to v11."""
        conn = database.get_db_connection()
        try:
            ver = conn.execute("PRAGMA user_version;").fetchone()[0]
            self.assertGreaterEqual(ver, 11)
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='media_series_overrides';"
            ).fetchone()
            self.assertIsNotNone(tbl)
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_media_series_overrides_series';"
            ).fetchone()
            self.assertIsNotNone(idx)
        finally:
            conn.close()

        # Synthetic v10 -> v11 upgrade check
        with tempfile.TemporaryDirectory() as tmpdir:
            v10_path = Path(tmpdir) / "v10.db"
            c10 = sqlite3.connect(v10_path)
            try:
                c10.row_factory = sqlite3.Row
                c10.executescript("""
                    CREATE TABLE media_items (
                        id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        title TEXT NOT NULL
                    );
                    PRAGMA user_version = 10;
                """)
                database.run_schema_migrations(c10)
                new_ver = c10.execute("PRAGMA user_version;").fetchone()[0]
                self.assertGreaterEqual(new_ver, 11)
                ov_tbl = c10.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='media_series_overrides';"
                ).fetchone()
                self.assertIsNotNone(ov_tbl)
            finally:
                c10.close()

    def test_02_single_card_override_and_matrix_enrichment(self):
        """Verifies POST /api/admin/media/<id>/series works for yoto & yoto_myo and enriches get_catalog_matrix."""
        self._login_admin()

        res = self.client.post("/api/admin/media/p4_yoto_1/series", json={
            "series": "Wings of Fire",
            "series_order": "1",
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["series"], "Wings of Fire")
        self.assertEqual(data["series_order"], "1")
        self.assertTrue(data["is_series_overridden"])

        res_myo = self.client.post("/api/admin/media/p4_myo_1/series", json={
            "series": "Wings of Fire",
            "sequence": "1.5",
        })
        self.assertEqual(res_myo.status_code, 200)
        self.assertEqual(res_myo.get_json()["series_order"], "1.5")

        matrix = database.get_catalog_matrix()
        by_id = {it["id"]: it for it in matrix["items"]}
        y1 = by_id["p4_yoto_1"]
        self.assertEqual(y1["series"], "Wings of Fire")
        self.assertEqual(y1["series_order"], "1")
        self.assertEqual(y1["series_list"], [{"name": "Wings of Fire", "order": "1"}])
        self.assertTrue(y1["is_series_overridden"])
        self.assertEqual(y1["auto_series"], "AutoOldSeries")
        self.assertEqual(y1["auto_series_order"], "9")

        m1 = by_id["p4_myo_1"]
        self.assertEqual(m1["series"], "Wings of Fire")
        self.assertEqual(m1["series_order"], "1.5")
        self.assertTrue(m1["is_series_overridden"])

    def test_03_rejects_abs_unknown_and_unauthenticated_requests(self):
        """Rejects ABS items (400), unknown IDs (404), and unauthenticated callers (401/403)."""
        # Unauthenticated remote WAN caller
        unauth = self.client.post(
            "/api/admin/media/p4_yoto_1/series",
            json={"series": "Blocked"},
            environ_base={"REMOTE_ADDR": "8.8.8.8"},
        )
        self.assertIn(unauth.status_code, (401, 403))

        # Member role cannot mutate admin routes
        with self.client.session_transaction() as sess:
            sess["user_id"] = "p4_member"
            sess["username"] = "sitter"
            sess["role"] = "member"
        member_res = self.client.post("/api/admin/media/p4_yoto_1/series", json={"series": "Blocked"})
        self.assertIn(member_res.status_code, (401, 403))

        self._login_admin()

        # ABS single rejection
        abs_res = self.client.post("/api/admin/media/p4_abs_1/series", json={"series": "Hacked", "series_order": "1"})
        self.assertEqual(abs_res.status_code, 400)
        self.assertFalse(abs_res.get_json()["ok"])

        # Missing card single 404
        miss_res = self.client.post("/api/admin/media/p4_does_not_exist/series", json={"series": "Nope"})
        self.assertEqual(miss_res.status_code, 404)

        # Mixed batch containing ABS must reject atomically with zero writes
        batch_res = self.client.post("/api/admin/media/batch-series", json={
            "series": "AtomicFailSeries",
            "items": [
                {"id": "p4_yoto_1", "sequence": "1"},
                {"id": "p4_abs_1", "sequence": "2"},
            ],
        })
        self.assertEqual(batch_res.status_code, 400)
        self.assertEqual(database.get_all_series_overrides(), {})

    def test_04_upstream_resync_preserves_overrides(self):
        """Verifies upsert_media_items never overwrites manual parent series overrides."""
        self._login_admin()
        res = self.client.post("/api/admin/media/p4_yoto_1/series", json={
            "series": "Custom Saga",
            "series_order": "2",
        })
        self.assertEqual(res.status_code, 200)

        # Simulate upstream Yoto sync overwriting title/cover/raw_metadata
        database.upsert_media_items([{
            "id": "p4_yoto_1",
            "type": "yoto",
            "title": "The Dragon's Prophecy (Updated)",
            "author": "Yoto Studio",
            "cover_url": "https://cdn.example.com/dragon1_v2.jpg",
            "raw_metadata": {"series": "UpstreamChangedSeries", "series_order": "99"},
        }])

        matrix = database.get_catalog_matrix()
        y1 = next(it for it in matrix["items"] if it["id"] == "p4_yoto_1")
        self.assertEqual(y1["title"], "The Dragon's Prophecy (Updated)")
        self.assertTrue(y1["is_series_overridden"])
        self.assertEqual(y1["series"], "Custom Saga")
        self.assertEqual(y1["series_order"], "2")
        self.assertEqual(y1["auto_series"], "UpstreamChangedSeries")

    def test_05_standalone_clear_and_delete_revert(self):
        """Verifies empty series marks card Standalone, and DELETE reverts to auto_series."""
        self._login_admin()

        # Clear upstream series explicitly -> Standalone override
        res_clear = self.client.post("/api/admin/media/p4_yoto_1/series", json={
            "series": "",
            "series_order": "",
        })
        self.assertEqual(res_clear.status_code, 200)

        matrix_cleared = database.get_catalog_matrix()
        y1_cleared = next(it for it in matrix_cleared["items"] if it["id"] == "p4_yoto_1")
        self.assertTrue(y1_cleared["is_series_overridden"])
        self.assertEqual(y1_cleared["series"], "")
        self.assertEqual(y1_cleared["series_list"], [])
        self.assertEqual(y1_cleared["auto_series"], "AutoOldSeries")

        # DELETE reverts override back to AutoOldSeries #9
        res_del = self.client.delete("/api/admin/media/p4_yoto_1/series")
        self.assertEqual(res_del.status_code, 200)
        del_data = res_del.get_json()
        self.assertTrue(del_data["ok"])
        self.assertTrue(del_data["reverted"])
        self.assertEqual(del_data["series"], "AutoOldSeries")
        self.assertEqual(del_data["series_order"], "9")

        matrix_reverted = database.get_catalog_matrix()
        y1_rev = next(it for it in matrix_reverted["items"] if it["id"] == "p4_yoto_1")
        self.assertFalse(y1_rev["is_series_overridden"])
        self.assertEqual(y1_rev["series"], "AutoOldSeries")
        self.assertEqual(y1_rev["series_order"], "9")

    def test_06_batch_series_and_decimal_sequence_curation_integration(self):
        """Verifies batch-series decimal sequencing drives atomic whole-series rotation and Book #1 cover."""
        self._login_admin()

        res = self.client.post("/api/admin/media/batch-series", json={
            "series": "Dragon Isles",
            "items": [
                {"id": "p4_yoto_1", "sequence": "1"},
                {"id": "p4_myo_1", "sequence": "1.5"},
                {"id": "p4_yoto_2", "sequence": "2"},
            ],
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated_count"], 3)
        self.assertEqual(data["series"], "Dragon Isles")

        # Verify curation catalog sorts 1 -> 1.5 -> 2 and sets series_cover to Book #1 (p4_yoto_1)
        catalog = database.get_catalog_items_for_profile("p4_child", media_type="yoto", client_type="touch")
        dragon_books = [it for it in catalog if it.get("series") == "Dragon Isles"]
        self.assertEqual(len(dragon_books), 3)
        for book in dragon_books:
            self.assertEqual(book["series_cover_id"], "p4_yoto_1")
            self.assertIn("p4_yoto_1", book["series_cover"])

        # Sequence float values preserved for client sorting
        seqs_by_id = {b["id"]: b["sequence"] for b in dragon_books}
        self.assertEqual(seqs_by_id["p4_yoto_1"], 1.0)
        self.assertEqual(seqs_by_id["p4_myo_1"], 1.5)
        self.assertEqual(seqs_by_id["p4_yoto_2"], 2.0)

        # Verify media_ids fallback auto-numbers 1..N
        res_fallback = self.client.post("/api/admin/media/batch-series", json={
            "series": "Fallback Saga",
            "media_ids": ["p4_yoto_2", "p4_yoto_1"],
        })
        self.assertEqual(res_fallback.status_code, 200)
        overrides = database.get_all_series_overrides()
        self.assertEqual(overrides["p4_yoto_2"]["series"], "Fallback Saga")
        self.assertEqual(overrides["p4_yoto_2"]["series_order"], "1")
        self.assertEqual(overrides["p4_yoto_1"]["series_order"], "2")

    def test_07_prune_stale_cleans_orphan_overrides(self):
        """Verifies pruning a deleted Yoto card cascades/cleans its row in media_series_overrides."""
        database.set_media_series_override("p4_yoto_1", "Cleanup Series", "1")
        self.assertIn("p4_yoto_1", database.get_all_series_overrides())

        # Keep all other Yoto/MYO items intact and prune only p4_yoto_1
        keep_ids = [
            it["id"] for it in database.get_catalog_matrix()["items"]
            if it["type"] in ("yoto", "yoto_myo") and it["id"] != "p4_yoto_1"
        ]
        removed = database.prune_stale_media_items(
            valid_ids=keep_ids,
            media_types=["yoto", "yoto_myo"],
        )
        self.assertGreaterEqual(removed, 1)
        self.assertNotIn("p4_yoto_1", database.get_all_series_overrides())

    def test_08_admin_html_contains_series_override_modals(self):
        """Verifies /admin HTML renders single & bulk series override modal elements and triggers."""
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        for token in (
            'id="existingSeriesList"',
            'id="editSeriesModal"',
            'id="batchSeriesModal"',
            'openBatchSeriesModal()',
            '/static/js/admin/series.js?v=',
            '/static/js/admin/library.js?v=',
        ):
            self.assertIn(token, html, f"Expected {token} in /admin HTML")


if __name__ == "__main__":
    unittest.main()
