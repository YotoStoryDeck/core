import unittest
import json
from pathlib import Path
import sys

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from app import app
import database
from core.scheduler import get_refresh_status


class TestLibraryRefreshSettings(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin"
            sess["username"] = "admin"
            sess["role"] = "admin"

    def test_default_refresh_settings(self):
        res = self.client.get("/api/admin/settings/catalog")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("auto_library_refresh_enabled", data)
        self.assertIn("auto_library_refresh_hours", data)
        self.assertEqual(data.get("auto_library_refresh_hours"), 6.0)
        self.assertTrue(data.get("auto_library_refresh_enabled"))
        self.assertIn("scheduler_status", data)

    def test_update_refresh_settings(self):
        # Update to 12 hours
        res = self.client.put("/api/admin/settings/catalog", json={
            "auto_library_refresh_enabled": False,
            "auto_library_refresh_hours": 12.0
        })
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertFalse(data.get("auto_library_refresh_enabled"))
        self.assertEqual(data.get("auto_library_refresh_hours"), 12.0)

        # Verify persisted
        settings = database.get_system_settings()
        self.assertFalse(settings.get("auto_library_refresh_enabled"))
        self.assertEqual(settings.get("auto_library_refresh_hours"), 12.0)

        # Restore defaults
        self.client.put("/api/admin/settings/catalog", json={
            "auto_library_refresh_enabled": True,
            "auto_library_refresh_hours": 6.0
        })


if __name__ == "__main__":
    unittest.main()

