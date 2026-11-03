"""
Media and static resource routing blueprint.
"""

import io
import requests
from flask import Blueprint, request, Response, send_file, redirect
import clients
import database
from PIL import Image, ImageDraw
from core.config import ABS_BASE_URL, THUMBNAIL_SIZE
from core.image_resizer import get_thumbnail
from ai_service import PixelArtRenderer

media_bp = Blueprint("media", __name__)


def _placeholder_jpeg(size: int, crop: bool = False) -> Response:
    """Generates a clean JPEG placeholder so both web browsers and ESP32 JPEGDEC can decode it."""
    w = max(32, min(int(size or 160), 512))
    h = w if crop else int(round(w * (208.0 / 160.0)))
    img = Image.new("RGB", (w, h), (229, 53, 43))
    draw = ImageDraw.Draw(img)
    pad = max(6, w // 12)
    draw.rounded_rectangle([pad, pad, w - pad - 1, h - pad - 1], radius=max(8, w // 14), outline=(255, 255, 255), width=2)
    cx, cy = w // 2, h // 2
    r = max(12, w // 5)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return Response(buf.getvalue(), mimetype="image/jpeg")


@media_bp.route("/", methods=["GET"])
def root_index():
    """Redirects root browser visitors to the Web Admin Portal."""
    return redirect("/admin", code=302)


@media_bp.route("/favicon.ico", methods=["GET"])
def favicon():
    """Returns an empty 204 to prevent browser 404 noise."""
    return Response(status=204, mimetype="image/x-icon")


@media_bp.route("/api/thumb", methods=["GET"])
def serve_thumbnail():
    """
    Serves a lightweight, square, downscaled 100x100 JPEG thumbnail.
    Query params:
      - type: 'abs', 'abs_chapter', or 'yoto'
      - id: ABS item ID (for type=abs or abs_chapter)
      - url: direct image URL (for type=yoto)
      - size: optional dimensions (default: 100)
    """
    source_type = request.args.get("type", "abs")
    item_id = request.args.get("id", "")
    target_url = request.args.get("url", "")
    size = int(request.args.get("size", THUMBNAIL_SIZE))

    # Default crop=False for book covers (ABS / Yoto cards) to preserve 784x1248 aspect ratio;
    # crop=True for chapter icons / track icons (1:1 square pixel art)
    default_crop = (source_type not in ("abs", "yoto", "yoto_myo"))
    crop_arg = request.args.get("crop")
    crop = (crop_arg.lower() in ("1", "true")) if crop_arg is not None else default_crop

    cached_file = None

    if source_type == "abs":
        if not item_id:
            return Response("Missing item ID", status=400)

        def fetch_abs():
            abs_url = (clients.abs_client.base_url if clients.abs_client and clients.abs_client.base_url else ABS_BASE_URL).rstrip("/")
            cover_url = f"{abs_url}/api/items/{item_id}/cover"
            headers = clients.abs_client.get_headers() if clients.abs_client else {}
            try:
                res = requests.get(cover_url, headers=headers, timeout=10)
                return res.content if res.status_code == 200 else None
            except requests.RequestException:
                return None

        cached_file = get_thumbnail(f"abs_{item_id}", fetch_abs, size, crop=crop)

    elif source_type == "abs_chapter":
        if not item_id:
            return Response("Missing item ID", status=400)
        try:
            chapter_idx = int(request.args.get("chapter", 0))
        except ValueError:
            chapter_idx = 0

        def fetch_abs_chapter():
            # 0. Custom Assigned Chapter Icon (uploaded file or custom pixel art)
            from core.config import CUSTOM_ICONS_DIR
            custom_path = CUSTOM_ICONS_DIR / f"{item_id}_{chapter_idx}.png"
            if custom_path.exists():
                try:
                    return custom_path.read_bytes()
                except Exception:
                    pass

            # 1. Try AI Generation if configured
            if clients.ai_service and clients.ai_service.is_configured():
                item_data = clients.abs_client.get_item(item_id) if clients.abs_client else {}
                item_data = item_data or {}
                media = item_data.get("media", {})
                metadata = media.get("metadata", {})
                book_title = metadata.get("title") or item_data.get("name") or "Audiobook"
                author = metadata.get("authorName") or metadata.get("author") or "Author"
                description = metadata.get("description") or ""

                chapters = media.get("chapters", [])
                chapter_title = ""
                if 0 <= chapter_idx < len(chapters):
                    chapter_title = chapters[chapter_idx].get("title", "")
                elif not chapter_title:
                    chapter_title = f"Chapter {chapter_idx + 1}"

                # Text fallback heuristic for generic titles
                prompt_context = clients.ai_service.build_narrative_context(
                    book_title, author, chapter_title, description
                )

                grid = clients.ai_service.generate_pixel_art(prompt_context)
                if grid:
                    palette, rows = grid
                    rendered_img = PixelArtRenderer.render(palette, rows, target_size=size)
                    if rendered_img:
                        # Upstream sync to Yoto ABS Bridge so physical Yoto player matches!
                        clients.ai_service.sync_upstream_to_bridge(item_id, chapter_idx, palette, rows)
                        buf = io.BytesIO()
                        rendered_img.save(buf, format="JPEG", quality=85)
                        return buf.getvalue()

            # 2. Upstream Bridge Item-Level Chapter Icon Fallback
            if clients.yoto_client:
                item_icon = clients.yoto_client.get_item_chapter_icon(item_id, chapter_idx + 1)
                if item_icon:
                    return item_icon

            if clients.ai_service:
                bridge_icon = clients.ai_service.fetch_bridge_icon_fallback(item_id, chapter_idx)
                if bridge_icon:
                    return bridge_icon


            # 3. Parent Book Cover Fallback
            abs_url = (clients.abs_client.base_url if clients.abs_client and clients.abs_client.base_url else ABS_BASE_URL).rstrip("/")
            cover_url = f"{abs_url}/api/items/{item_id}/cover"
            headers = clients.abs_client.get_headers() if clients.abs_client else {}
            try:
                res = requests.get(cover_url, headers=headers, timeout=10)
                return res.content if res.status_code == 200 else None
            except requests.RequestException:
                return None

        cached_file = get_thumbnail(f"abs_ch_{item_id}_{chapter_idx}", fetch_abs_chapter, size)

    elif source_type in ("yoto", "yoto_myo"):
        if not target_url and item_id:
            conn = database.get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT cover_url FROM media_items WHERE id = ?;", (item_id,))
                row = cur.fetchone()
                if row and row["cover_url"]:
                    target_url = row["cover_url"]
            except Exception:
                pass
            finally:
                conn.close()

        if not target_url:
            return _placeholder_jpeg(size, crop=crop)

        def fetch_yoto():
            try:
                res = requests.get(target_url, timeout=10)
                return res.content if res.status_code == 200 else None
            except Exception:
                return None

        cached_file = get_thumbnail(f"yoto_{target_url}", fetch_yoto, size, crop=crop)

    elif source_type == "yoto_icon":
        ref = request.args.get("ref", "")
        fallback_id = request.args.get("fallback_id", "")
        
        # Check if we have a locally stored custom icon for this fallback ID
        if fallback_id:
            from core.config import CUSTOM_ICONS_DIR
            # If any custom icon exists for fallback_id
            for p in CUSTOM_ICONS_DIR.glob(f"{fallback_id}_*.png"):
                cached_file = get_thumbnail(f"abs_ch_{fallback_id}_{p.stem.split('_')[-1]}", p.read_bytes, size)
                if cached_file and cached_file.exists():
                    break
        
        if not cached_file or not cached_file.exists():
            # Return crisp pixel radio placeholder
            placeholder_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 100 100">
                <rect width="100" height="100" rx="12" fill="#2d3748"/>
                <text x="50" y="55" font-size="36" text-anchor="middle" dominant-baseline="central">🎨</text>
            </svg>"""
            return Response(placeholder_svg, mimetype="image/svg+xml")
    else:
        return Response("Invalid type", status=400)

    if not cached_file or not cached_file.exists():
        return _placeholder_jpeg(size, crop=crop)

    response = send_file(cached_file, mimetype="image/jpeg", max_age=86400)
    if source_type in ("abs_chapter", "yoto_icon") or request.args.get("v") or request.args.get("t"):
        response.headers["Cache-Control"] = "public, max-age=60, must-revalidate"
    return response
