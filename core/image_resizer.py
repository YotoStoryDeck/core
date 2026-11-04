"""
Disk Image Cache & Thumbnail Resizer using Pillow Lanczos.
"""

import io
import hashlib
from pathlib import Path
from typing import Optional
from PIL import Image
from core.config import CACHE_DIR, THUMBNAIL_SIZE, logger


COMMON_THUMB_SIZES = (THUMBNAIL_SIZE, 50, 64, 100, 130, 160, 170, 200, 210, 240, 300, 320, 512, 784)


def invalidate_thumbnail(cache_key: str, size: Optional[int] = None) -> None:
    """Removes cached thumbnail files from disk for cache_key across common sizes and crop modes."""
    sizes = [size] if size is not None else list(COMMON_THUMB_SIZES)
    for s in set(sizes):
        for crop in (True, False, None):
            crop_str = f"_crop{crop}" if crop is not None else ""
            safe_hash = hashlib.sha256(f"{cache_key}_{s}{crop_str}".encode()).hexdigest()[:24]
            cached_path = CACHE_DIR / f"{safe_hash}.jpg"
            if cached_path.exists():
                try:
                    cached_path.unlink()
                except Exception as e:
                    logger.warning("Failed to invalidate thumbnail %s: %s", cached_path, e)


def prune_orphan_thumbnails(valid_items: list) -> int:
    """
    Scans CACHE_DIR and deletes any orphaned .jpg thumbnail files that do not belong
    to any active media item in `valid_items` (each dict having `id`, `type`, `cover_url`).
    """
    if not valid_items:
        return 0
    valid_hashes = set()
    for it in valid_items:
        mid = str(it.get("id") or "").strip()
        mtype = str(it.get("type") or "").strip()
        curl = str(it.get("cover_url") or "").strip()
        keys = []
        if mid:
            keys.append(f"abs_{mid}")
            # Also preserve up to 150 chapter icons per active item
            for ch_idx in range(150):
                keys.append(f"abs_ch_{mid}_{ch_idx}")
        if curl:
            keys.append(f"yoto_{curl}")
        for k in keys:
            for s in COMMON_THUMB_SIZES:
                for crop in (True, False, None):
                    crop_str = f"_crop{crop}" if crop is not None else ""
                    h = hashlib.sha256(f"{k}_{s}{crop_str}".encode()).hexdigest()[:24]
                    valid_hashes.add(f"{h}.jpg")

    removed = 0
    try:
        for f in CACHE_DIR.glob("*.jpg"):
            if f.name not in valid_hashes:
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Error scanning CACHE_DIR for orphan thumbnails: %s", e)
    return removed


def get_thumbnail(cache_key: str, fetch_callable, size: int = THUMBNAIL_SIZE, crop: bool = True) -> Optional[Path]:
    """
    Checks if a resized thumbnail exists on disk; if not, invokes fetch_callable
    to retrieve raw image bytes, downscales via Pillow, saves to cache, and returns the file path.
    - If crop=True (default for 1:1 chapter/track icons): square-crops from center.
    - If crop=False (for book cover art): preserves original aspect ratio (or fits within 784x1248 ratio bounds) without cropping.
    """
    safe_hash = hashlib.sha256(f"{cache_key}_{size}_crop{crop}".encode()).hexdigest()[:24]
    cached_path = CACHE_DIR / f"{safe_hash}.jpg"

    if cached_path.exists():
        # Check if cache is older than the custom icon file (if this is an abs_chapter)
        if cache_key.startswith("abs_ch_"):
            parts = cache_key.split("_")
            if len(parts) >= 4:
                item_id = "_".join(parts[2:-1])
                ch_idx = parts[-1]
                from core.config import CUSTOM_ICONS_DIR
                custom_icon_file = CUSTOM_ICONS_DIR / f"{item_id}_{ch_idx}.png"
                if custom_icon_file.exists() and custom_icon_file.stat().st_mtime >= cached_path.stat().st_mtime:
                    try:
                        cached_path.unlink()
                    except Exception:
                        pass
        if cached_path.exists():
            return cached_path

    raw_bytes = fetch_callable()
    if not raw_bytes:
        return None

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        # Convert RGBA / P palette images to standard RGB for JPEG output
        if img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size

        if crop:
            # Crop to square aspect ratio from center before downscaling (for 1:1 chapter/track icons)
            min_dim = min(width, height)
            left = (width - min_dim) // 2
            top = (height - min_dim) // 2
            right = left + min_dim
            bottom = top + min_dim
            img = img.crop((left, top, right, bottom))

            # If source is tiny pixel art (<= 32px), upscale with NEAREST to preserve crisp pixels
            if min_dim <= 32 and size > min_dim:
                img = img.resize((size, size), Image.Resampling.NEAREST)
            else:
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
        else:
            # Canonical 784 x 1248 (~0.6282 aspect ratio) cover art transformation.
            # Downscales without cropping and letterboxes/pillarboxes onto a 784:1248 ratio canvas.
            target_w = size
            target_h = int(round(size * (1248 / 784)))

            # Fit source image proportionally inside (target_w, target_h)
            scale = min(target_w / width, target_h / height)
            scaled_w = max(1, int(round(width * scale)))
            scaled_h = max(1, int(round(height * scale)))
            scaled_img = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

            # Sample corner pixel colors from original image for seamless edge/letterbox blending
            try:
                corners = [
                    img.getpixel((0, 0)),
                    img.getpixel((width - 1, 0)),
                    img.getpixel((0, height - 1)),
                    img.getpixel((width - 1, height - 1))
                ]
                bg_color = (
                    sum(c[0] for c in corners) // 4,
                    sum(c[1] for c in corners) // 4,
                    sum(c[2] for c in corners) // 4
                )
            except Exception:
                bg_color = (24, 21, 18)

            # Create canvas with exact canonical 784:1248 ratio
            canvas = Image.new("RGB", (target_w, target_h), bg_color)
            offset_x = (target_w - scaled_w) // 2
            offset_y = (target_h - scaled_h) // 2
            canvas.paste(scaled_img, (offset_x, offset_y))
            img = canvas

        # Save optimized JPEG
        img.save(cached_path, format="JPEG", quality=88, optimize=True)
        return cached_path
    except Exception as e:
        logger.error("Failed to generate thumbnail for '%s': %s", cache_key, e)
        return None
