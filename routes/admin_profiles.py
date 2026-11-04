"""
Child profiles and avatar management blueprint.
"""

import io
import time
from typing import Dict, Any, List, Tuple, Optional
from PIL import Image
import requests
from flask import Blueprint, request, jsonify, Response, send_file
import database
from core.config import AVATARS_DIR, logger
from core.auth import require_admin

admin_profiles_bp = Blueprint("admin_profiles", __name__)


@admin_profiles_bp.route("/api/admin/profiles", methods=["GET"])
@require_admin
def admin_get_profiles():
    """Returns all profiles with full schemas."""
    return jsonify(database.get_all_profiles())


def _materialize_avatar_bytes_to_disk(pid: str, raw_bytes: bytes) -> Optional[str]:
    """Center-crops, resizes to 160x160 baseline RGB JPEG, writes AVATARS_DIR/{pid}.jpg, and returns /api/avatar/{pid}?t=..."""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))
        img = img.resize((160, 160), Image.Resampling.LANCZOS)
        avatar_path = AVATARS_DIR / f"{pid}.jpg"
        img.save(avatar_path, format="JPEG", quality=85, optimize=False, progressive=False)
        bubble_path = AVATARS_DIR / f"{pid}_bubble.jpg"
        if bubble_path.exists():
            try:
                bubble_path.unlink()
            except Exception:
                pass
        return f"/api/avatar/{pid}?t={int(avatar_path.stat().st_mtime)}"
    except Exception as e:
        logger.warning("Failed to materialize avatar for %s: %s", pid, e)
        return None


def prune_stale_profile_avatars() -> int:
    """Deletes any orphaned avatar files in AVATARS_DIR whose profile ID no longer exists in SQLite."""
    valid_pids = set(database.get_all_profiles().keys())
    removed = 0
    try:
        for p in AVATARS_DIR.glob("*.jpg"):
            stem = p.stem
            if stem.endswith("_bubble"):
                stem = stem[:-7]
            if stem not in valid_pids:
                try:
                    p.unlink()
                    removed += 1
                except Exception as e:
                    logger.warning("Failed to remove stale avatar file %s: %s", p, e)
    except Exception as e:
        logger.warning("Error scanning AVATARS_DIR for stale files: %s", e)
    return removed


def sync_all_bubble_avatars() -> None:
    """
    Re-renders and saves custom colored bubble JPEGs (`{pid}_bubble.jpg`) for all profiles
    that do not have a custom photo (`{pid}.jpg`), and updates their `avatar_url` with a fresh
    `?t=<mtime>` cache-buster whenever the color or household monogram changes.
    Also prunes any orphaned files in AVATARS_DIR.
    """
    prune_stale_profile_avatars()
    profiles = database.get_all_profiles()
    monograms = compute_household_monograms()
    for pid, pdata in profiles.items():
        custom_photo_path = AVATARS_DIR / f"{pid}.jpg"
        bubble_path = AVATARS_DIR / f"{pid}_bubble.jpg"
        if custom_photo_path.exists():
            if bubble_path.exists():
                try:
                    bubble_path.unlink()
                except Exception:
                    pass
            continue

        display_name = pdata.get("display_name", pid.title())
        custom_color = pdata.get("avatar_color") or None
        custom_mono = pdata.get("avatar_initial") or monograms.get(pid)
        try:
            buf = generate_initial_avatar(display_name, monogram=custom_mono, custom_color=custom_color, size=160)
            new_bytes = buf.getvalue()
            old_bytes = bubble_path.read_bytes() if bubble_path.exists() else None
            if old_bytes != new_bytes:
                bubble_path.write_bytes(new_bytes)
            mtime = int(bubble_path.stat().st_mtime)
            target_url = f"/api/avatar/{pid}?t={mtime}"
            if pdata.get("avatar_url") != target_url:
                pdata["avatar_url"] = target_url
                database.upsert_profile(pid, pdata)
        except Exception as e:
            logger.warning("Failed to generate bubble avatar on disk for %s: %s", pid, e)


@admin_profiles_bp.route("/api/admin/profiles/<profile_id>", methods=["PUT"])
@require_admin
def admin_upsert_profile(profile_id: str):
    """Creates or updates a child profile, materializes custom or bubble avatars, and prunes stale avatar files."""
    import base64
    pid = profile_id.lower().strip()
    data = request.get_json(silent=True) or {}
    av_url = str(data.get("avatar_url") or "").strip()
    custom_photo_path = AVATARS_DIR / f"{pid}.jpg"

    if av_url.startswith("data:image/") and ";base64," in av_url:
        try:
            b64_part = av_url.split(";base64,", 1)[1]
            raw_bytes = base64.b64decode(b64_part)
            normalized = _materialize_avatar_bytes_to_disk(pid, raw_bytes)
            if normalized:
                data["avatar_url"] = normalized
        except Exception as e:
            logger.warning("Failed decoding base64 avatar for %s: %s", pid, e)
    elif av_url.startswith("http://") or av_url.startswith("https://"):
        try:
            res = requests.get(av_url, timeout=8)
            if res.status_code == 200 and res.content:
                normalized = _materialize_avatar_bytes_to_disk(pid, res.content)
                if normalized:
                    data["avatar_url"] = normalized
        except Exception as e:
            logger.warning("Failed downloading remote avatar for %s: %s", pid, e)
    elif not av_url:
        # User cleared the custom photo or opted for the colored bubble avatar: remove stale custom photo file
        if custom_photo_path.exists():
            try:
                custom_photo_path.unlink()
            except Exception as e:
                logger.warning("Failed to delete cleared custom avatar %s: %s", custom_photo_path, e)

    success = database.upsert_profile(pid, data)
    sync_all_bubble_avatars()
    updated_prof = database.get_profile_by_id(pid) or data
    return jsonify({"ok": success, "avatar_url": updated_prof.get("avatar_url", "")})


@admin_profiles_bp.route("/api/admin/profiles/<profile_id>", methods=["DELETE"])
@require_admin
def admin_delete_profile(profile_id: str):
    """Deletes a child profile and removes its cached avatar files from disk."""
    pid = profile_id.lower().strip()
    success = database.delete_profile(pid)
    for p in (AVATARS_DIR / f"{pid}.jpg", AVATARS_DIR / f"{pid}_bubble.jpg"):
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    sync_all_bubble_avatars()
    return jsonify({"ok": success})


@admin_profiles_bp.route("/api/admin/profiles/<profile_id>/avatar", methods=["POST"])
@require_admin
def admin_upload_profile_avatar(profile_id: str):
    """Uploads, squares, crops, and optimizes an avatar image for the child's profile."""
    pid = profile_id.lower().strip()
    profile = database.get_profile_by_id(pid)
    if not profile:
        return jsonify({"ok": False, "error": f"Profile '{pid}' not found."}), 404

    # 1. Check for file upload (multipart/form-data)
    file_bytes = None
    if "avatar" in request.files:
        file = request.files["avatar"]
        if file and file.filename:
            file_bytes = file.read()

    # 2. Check for JSON URL payload
    if not file_bytes:
        data = request.get_json(silent=True) or {}
        img_url = data.get("avatar_url", "").strip()
        if img_url:
            try:
                res = requests.get(img_url, timeout=10)
                if res.status_code == 200:
                    file_bytes = res.content
            except Exception as e:
                return jsonify({"ok": False, "error": f"Failed to download image from URL: {str(e)}"}), 400

    if not file_bytes:
        return jsonify({"ok": False, "error": "No avatar file or valid image URL provided."}), 400

    try:
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Center-crop to square
        w, h = img.size
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))

        # Resize to standard avatar size (160x160 for ESP32 and UI)
        img.thumbnail((160, 160), Image.Resampling.LANCZOS)

        avatar_path = AVATARS_DIR / f"{pid}.jpg"
        img.save(avatar_path, format="JPEG", quality=85, optimize=True)

        avatar_url = f"/api/avatar/{pid}?t={int(time.time())}"
        profile["avatar_url"] = avatar_url
        database.upsert_profile(pid, profile)

        return jsonify({"ok": True, "avatar_url": avatar_url})
    except Exception as e:
        logger.error("Failed to process profile avatar for %s: %s", pid, e)
        return jsonify({"ok": False, "error": f"Failed to process image: {str(e)}"}), 500


PALETTE_COLORS = [
    "#3b82f6",  # Blue
    "#ef4444",  # Red
    "#10b981",  # Emerald
    "#f59e0b",  # Amber
    "#8b5cf6",  # Purple
    "#ec4899",  # Pink
    "#06b6d4",  # Cyan
    "#f97316",  # Orange
    "#14b8a6",  # Teal
    "#6366f1",  # Indigo
]


def compute_household_monograms() -> Dict[str, str]:
    """
    Analyzes all profiles in the household. If multiple profiles share the same
    starting letter, automatically disambiguates them using 2 letters (e.g. 'Ja' vs 'Jm',
    or first/last initials if multi-word like 'JB' vs 'JD').
    """
    profiles = database.get_all_profiles()
    by_letter: Dict[str, List[Tuple[str, str]]] = {}
    for pid, pdata in profiles.items():
        if pdata.get("avatar_initial"):
            continue
        name = (pdata.get("display_name") or pid).strip()
        first_char = (name[0] if name else "C").upper()
        by_letter.setdefault(first_char, []).append((pid, name))

    monograms: Dict[str, str] = {}
    for pid, pdata in profiles.items():
        if pdata.get("avatar_initial"):
            monograms[pid] = pdata["avatar_initial"]

    for letter, items in by_letter.items():
        if len(items) == 1:
            pid, name = items[0]
            monograms[pid] = letter
        else:
            # Conflict detected! Disambiguate with smart multi-word or distinctive 2-letter monogram
            used_monos = set()
            # 1. Multi-word pass (e.g. "Jack B" -> "JB")
            for pid, name in items:
                words = name.split()
                if len(words) >= 2 and words[0] and words[1]:
                    mono = (words[0][0] + words[1][0]).upper()
                    monograms[pid] = mono
                    used_monos.add(mono)

            # 2. Single-word distinctive pass
            for pid, name in items:
                if pid in monograms:
                    continue
                clean = ''.join(c for c in name if c.isalnum())
                if len(clean) >= 2:
                    cand = clean[:2].title()
                    if cand not in used_monos:
                        monograms[pid] = cand
                        used_monos.add(cand)
                    elif len(clean) >= 3:
                        # If first 2 chars match (e.g. Jackson & James both 'Ja'), pick 1st + 3rd (e.g. 'Jm')
                        cand2 = (clean[0] + clean[2]).title()
                        monograms[pid] = cand2
                        used_monos.add(cand2)
                    else:
                        monograms[pid] = cand
                else:
                    monograms[pid] = letter
    return monograms


def generate_initial_avatar(name_or_id: str, monogram: Optional[str] = None, custom_color: Optional[str] = None, size: int = 160) -> io.BytesIO:
    """Generates a baseline RGB JPEG avatar with the profile's selected/hashed background color and 1-2 letter monogram."""
    from PIL import ImageDraw, ImageFont

    clean_str = (name_or_id or "Child").strip()
    text = (monogram if monogram else (clean_str[0] if clean_str else "C")).strip()
    if len(text) > 2:
        text = text[:2]

    # Color selection: explicit custom color or deterministic polynomial hash
    if custom_color and custom_color.startswith("#"):
        color_hex = custom_color
    else:
        h = 0
        for c in clean_str.lower():
            h = (h * 31 + ord(c)) & 0xFFFFFFFF
        color_hex = PALETTE_COLORS[h % len(PALETTE_COLORS)]

    # Render at 2x supersampled resolution for crisp anti-aliased typography
    ss = size * 2
    img = Image.new("RGB", (ss, ss), color=color_hex)
    draw = ImageDraw.Draw(img)

    # Scale font size based on 1 vs 2 letters
    font_size = int(ss * (0.42 if len(text) > 1 else 0.52))
    font = None
    for font_candidate in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "segoeui.ttf"):
        try:
            font = ImageFont.truetype(font_candidate, font_size)
            break
        except Exception:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()

    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (ss - text_w) // 2 - bbox[0]
    y = (ss - text_h) // 2 - bbox[1]

    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    img = img.resize((size, size), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, optimize=False, progressive=False)
    buf.seek(0)
    return buf


@admin_profiles_bp.route("/api/avatar/<profile_id>", methods=["GET"])
def serve_profile_avatar(profile_id: str):
    """Serves the optimized baseline RGB avatar JPEG (supporting ?size=W for ESP32 JPEGDEC)."""
    import base64
    pid = profile_id.lower().strip()
    req_size = request.args.get("size", type=int)
    target_size = max(24, min(512, req_size)) if req_size else 160

    avatar_path = AVATARS_DIR / f"{pid}.jpg"
    profile = database.get_profile_by_id(pid)

    # If avatar_path does not exist yet, check if profile["avatar_url"] has data:image/... or http...
    if not avatar_path.exists() and profile and profile.get("avatar_url"):
        av_url = str(profile["avatar_url"]).strip()
        if av_url.startswith("data:image/") and ";base64," in av_url:
            try:
                raw_bytes = base64.b64decode(av_url.split(";base64,", 1)[1])
                norm = _materialize_avatar_bytes_to_disk(pid, raw_bytes)
                if norm:
                    profile["avatar_url"] = norm
                    database.upsert_profile(pid, profile)
            except Exception:
                pass
        elif av_url.startswith("http://") or av_url.startswith("https://"):
            try:
                res = requests.get(av_url, timeout=8)
                if res.status_code == 200 and res.content:
                    norm = _materialize_avatar_bytes_to_disk(pid, res.content)
                    if norm:
                        profile["avatar_url"] = norm
                        database.upsert_profile(pid, profile)
            except Exception:
                pass

    if avatar_path.exists():
        try:
            img = Image.open(avatar_path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            if img.size != (target_size, target_size):
                img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=False, progressive=False)
            buf.seek(0)
            return send_file(buf, mimetype="image/jpeg", max_age=86400)
        except Exception as e:
            logger.warning("Error serving resized avatar for %s: %s", pid, e)
            return send_file(avatar_path, mimetype="image/jpeg", max_age=86400)

    # Serve or materialize the custom-generated colored bubble JPEG on disk ({pid}_bubble.jpg)
    bubble_path = AVATARS_DIR / f"{pid}_bubble.jpg"
    if not bubble_path.exists() and profile:
        sync_all_bubble_avatars()

    if bubble_path.exists():
        try:
            img = Image.open(bubble_path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            if img.size != (target_size, target_size):
                img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90, optimize=False, progressive=False)
            buf.seek(0)
            return send_file(buf, mimetype="image/jpeg", max_age=86400)
        except Exception as e:
            logger.warning("Error serving bubble avatar for %s: %s", pid, e)
            return send_file(bubble_path, mimetype="image/jpeg", max_age=86400)

    # Default fallback for unknown profile ID
    display_name = profile.get("display_name", pid.title()) if profile else pid.title()
    custom_color = profile.get("avatar_color") if profile else None
    custom_mono = profile.get("avatar_initial") if profile else None

    if not custom_mono:
        all_monos = compute_household_monograms()
        custom_mono = all_monos.get(pid)

    buf = generate_initial_avatar(display_name, monogram=custom_mono, custom_color=custom_color, size=target_size)
    return send_file(buf, mimetype="image/jpeg", max_age=3600)

