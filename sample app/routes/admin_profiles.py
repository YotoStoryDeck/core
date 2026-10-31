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


@admin_profiles_bp.route("/api/admin/profiles/<profile_id>", methods=["PUT"])
@require_admin
def admin_upsert_profile(profile_id: str):
    """Creates or updates a child profile."""
    data = request.get_json(silent=True) or {}
    success = database.upsert_profile(profile_id.lower().strip(), data)
    return jsonify({"ok": success})


@admin_profiles_bp.route("/api/admin/profiles/<profile_id>", methods=["DELETE"])
@require_admin
def admin_delete_profile(profile_id: str):
    """Deletes a child profile."""
    success = database.delete_profile(profile_id.lower().strip())
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
    """Generates an in-memory JPEG avatar with a selected or hashed background color and 1-2 letter monogram."""
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

    img = Image.new("RGB", (size, size), color=color_hex)
    draw = ImageDraw.Draw(img)

    # Scale font size based on 1 vs 2 letters
    font_size = int(size * (0.42 if len(text) > 1 else 0.52))
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        font = ImageFont.load_default()

    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]

    draw.text((x, y), text, font=font, fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf


@admin_profiles_bp.route("/api/avatar/<profile_id>", methods=["GET"])
def serve_profile_avatar(profile_id: str):
    """Serves the optimized avatar JPEG for the ESP32 and web dashboard."""
    pid = profile_id.lower().strip()
    avatar_path = AVATARS_DIR / f"{pid}.jpg"
    if avatar_path.exists():
        return send_file(avatar_path, mimetype="image/jpeg", max_age=86400)

    # If no local uploaded avatar, check if a remote avatar_url is configured on profile
    profile = database.get_profile_by_id(pid)
    if profile and profile.get("avatar_url") and profile["avatar_url"].startswith("http"):
        try:
            res = requests.get(profile["avatar_url"], timeout=8)
            if res.status_code == 200:
                img = Image.open(io.BytesIO(res.content))
                if img.mode != "RGB":
                    img = img.convert("RGB")
                w, h = img.size
                min_dim = min(w, h)
                left = (w - min_dim) // 2
                top = (h - min_dim) // 2
                img = img.crop((left, top, left + min_dim, top + min_dim))
                img.thumbnail((160, 160), Image.Resampling.LANCZOS)
                img.save(avatar_path, format="JPEG", quality=85)
                return send_file(avatar_path, mimetype="image/jpeg", max_age=86400)
        except Exception:
            pass

    # Default fallback: generate a colored letter avatar using household monogram & custom color
    display_name = profile.get("display_name", pid.title()) if profile else pid.title()
    custom_color = profile.get("avatar_color") if profile else None
    custom_mono = profile.get("avatar_initial") if profile else None

    if not custom_mono:
        all_monos = compute_household_monograms()
        custom_mono = all_monos.get(pid)

    buf = generate_initial_avatar(display_name, monogram=custom_mono, custom_color=custom_color, size=160)
    return send_file(buf, mimetype="image/jpeg", max_age=3600)

