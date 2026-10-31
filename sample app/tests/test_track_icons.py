import unittest
import json
import time
from pathlib import Path
import sys

# Ensure sample app path is loaded
app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from app import app
from core.config import CUSTOM_ICONS_DIR
from core.image_resizer import invalidate_thumbnail, get_thumbnail


class TestTrackIconCaching(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["user_id"] = "admin"
            sess["username"] = "admin"
            sess["role"] = "admin"

    def test_invalidate_thumbnail_all_crops(self):
        import io
        from PIL import Image
        
        cache_key = "test_invalidate_cache_key"
        
        # Create valid image bytes
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), color="red").save(buf, format="PNG")
        raw_bytes = buf.getvalue()
        
        # Create thumbnail with crop=True
        thumb_path = get_thumbnail(cache_key, lambda: raw_bytes, size=100, crop=True)
        self.assertIsNotNone(thumb_path)
        self.assertTrue(thumb_path.exists())

        # Invalidate
        invalidate_thumbnail(cache_key, size=100)
        self.assertFalse(thumb_path.exists())

    def test_tracks_endpoint_returns_versioned_icon_url(self):
        # Media id for Volume 4
        media_id = "68b4d0eb-1c0d-42fe-84f8-a546c9c223a7"
        custom_icon_path = CUSTOM_ICONS_DIR / f"{media_id}_0.png"
        
        if custom_icon_path.exists():
            expected_v = str(int(custom_icon_path.stat().st_mtime))
            res = self.client.get(f"/api/admin/media/{media_id}/tracks")
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data.get("ok"))
            tracks = data.get("tracks", [])
            self.assertGreater(len(tracks), 0)
            track0 = tracks[0]
            self.assertIn(f"&v={expected_v}", track0.get("icon_url", ""))
            self.assertTrue(track0.get("has_custom_icon"))


if __name__ == "__main__":
    unittest.main()
