"""
Shared media metadata, series extraction, tracklist resolution, and 16x16 pixel icon utilities.
"""
import io
import re
from typing import Dict, Any, List, Optional
from PIL import Image
import database
import clients


def parse_single_series(name_str: str, default_order: str = "") -> Optional[Dict[str, str]]:
    """Extracts series title and sequence/order (handling #12, #13-15, Book 1-4)."""
    name_str = (name_str or "").strip()
    order_str = str(default_order or "").strip()
    if not name_str:
        return None

    # Check for trailing #sequence (e.g. #55, #13-15)
    m_seq = re.search(r'\s*#\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', name_str)
    if m_seq:
        if not order_str:
            order_str = m_seq.group(1).replace(" ", "")
        name_str = name_str[:m_seq.start()].strip()
    else:
        # Check for trailing Book/Volume sequence
        m_book = re.search(r'[,:\s]+(?:Books?|Volumes?|Vol\.?|Parts?)\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$', name_str, re.IGNORECASE)
        if m_book:
            if not order_str:
                order_str = m_book.group(1).replace(" ", "")
            name_str = name_str[:m_book.start()].strip()

    return {"name": name_str, "order": order_str} if name_str else None


def extract_series_list(raw_series: Any, raw_series_order: str = "", title: str = "", known_series: Optional[list] = None) -> list:
    """Normalizes raw series into a list of {name, order} dicts, with title and known series fallback deduction."""
    series_list = []
    if isinstance(raw_series, list):
        for s_entry in raw_series:
            if isinstance(s_entry, dict):
                parsed = parse_single_series(s_entry.get("name"), s_entry.get("sequence") or raw_series_order)
            else:
                parsed = parse_single_series(str(s_entry), raw_series_order)
            if parsed:
                series_list.append(parsed)
    elif isinstance(raw_series, dict):
        parsed = parse_single_series(raw_series.get("name"), raw_series.get("sequence") or raw_series_order)
        if parsed:
            series_list.append(parsed)
    elif isinstance(raw_series, str) and raw_series.strip():
        # Handle comma-delimited series list with or without numbers
        raw_parts = [p.strip() for p in raw_series.split(",") if p.strip()]
        if len(raw_parts) > 1:
            for p in raw_parts:
                parsed = parse_single_series(p, raw_series_order if len(raw_parts) == 1 else "")
                if parsed:
                    series_list.append(parsed)
        else:
            parsed = parse_single_series(raw_series, raw_series_order)
            if parsed:
                series_list.append(parsed)

    # Sequence / order detection from title if missing
    clean_title = (title or "").strip()
    detected_order = str(raw_series_order or "").strip()
    if not detected_order and clean_title:
        m_range = re.search(r"#\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)", clean_title, re.IGNORECASE)
        if m_range:
            detected_order = re.sub(r"\s+", "", m_range.group(1) or m_range.group(2))
        else:
            m_num = re.search(r"#\s*(\d+(?:\.\d+)?)| (?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)", clean_title, re.IGNORECASE)
            if m_num:
                val = m_num.group(1) or m_num.group(2)
                detected_order = str(val).strip()

    # 1. Match against known cross-platform series (e.g. 'The Boxcar Children')
    if known_series and clean_title:
        for ks in known_series:
            ks_str = (ks or "").strip()
            if not ks_str:
                continue
            pat = r"^" + re.escape(ks_str) + r"(?:\s*Collection)?(?:[\s,:–—\-]|$)"
            if re.search(pat, clean_title, re.IGNORECASE):
                if not any(s["name"].lower() == ks_str.lower() for s in series_list):
                    series_list.append({"name": ks_str, "order": detected_order})

    # 2. Sub-title prefix deduction (e.g. 'The Boxcar Children: Mystery Ranch' -> 'The Boxcar Children')
    if not series_list and clean_title:
        for sep in [" - ", ": "]:
            if sep in clean_title:
                cand = clean_title.split(sep)[0].strip()
                if cand and len(cand) >= 3:
                    parsed_cand = parse_single_series(cand, detected_order)
                    if parsed_cand:
                        series_list.append(parsed_cand)
                break

    return series_list


def get_media_tracks_data(media_id: str) -> dict:
    """
    Returns chapter/track breakdown dict for any media item (ABS, Yoto Retail, or MYO).
    For ABS: returns chapters from Audiobookshelf with icon URLs.
    For Yoto Retail: returns read-only official tracklist and official Yoto 16x16 icons.
    For MYO: returns tracklist with editable icon status.
    """
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, type, title, author, cover_url, raw_metadata FROM media_items WHERE id = ?;", (media_id,))
    item_row = cur.fetchone()
    conn.close()

    media_type = item_row["type"] if item_row else "abs"
    title = item_row["title"] if item_row else "Unknown"
    author = item_row["author"] if item_row else ""
    cover_url = item_row["cover_url"] if item_row else ""

    tracks = []
    can_edit = False

    if media_type == "abs":
        can_edit = True
        if clients.abs_client:
            abs_data = clients.abs_client.get_item(media_id)
            if abs_data:
                media_obj = abs_data.get("media", {})
                chapters = media_obj.get("chapters", [])
                title = abs_data.get("media", {}).get("metadata", {}).get("title") or title
                author = abs_data.get("media", {}).get("metadata", {}).get("authorName") or author

                from core.config import CUSTOM_ICONS_DIR
                for idx, ch in enumerate(chapters):
                    ch_start = float(ch.get("start", 0))
                    ch_end = float(ch.get("end", 0))
                    dur = max(0, int(ch_end - ch_start))
                    dur_str = f"{dur // 60}:{dur % 60:02d}" if dur > 0 else ""

                    custom_file = CUSTOM_ICONS_DIR / f"{media_id}_{idx}.png"
                    if custom_file.exists():
                        v_param = f"&v={int(custom_file.stat().st_mtime)}"
                        has_custom = True
                    else:
                        v_param = ""
                        has_custom = False

                    tracks.append({
                        "index": idx,
                        "track_number": idx + 1,
                        "title": ch.get("title") or f"Chapter {idx + 1}",
                        "duration_seconds": dur,
                        "duration_formatted": dur_str,
                        "icon_url": f"/api/thumb?type=abs_chapter&id={media_id}&chapter={idx}&size=100{v_param}",
                        "has_custom_icon": has_custom
                    })

    elif media_type in ("yoto", "yoto_myo"):
        can_edit = (media_type == "yoto_myo")
        card_detail = None
        if clients.yoto_client:
            card_detail = clients.yoto_client.get_card_detail(media_id)

        if card_detail:
            c = card_detail.get("card") or card_detail
            meta = c.get("metadata") or {}
            content = c.get("content") or {}
            raw_chaps = content.get("chapters") or c.get("chapters") or []
            title = c.get("title") or title
            author = meta.get("author") or author

            from core.config import CUSTOM_ICONS_DIR
            for idx, ch in enumerate(raw_chaps):
                dur = int(ch.get("duration", 0))
                dur_str = f"{dur // 60}:{dur % 60:02d}" if dur > 0 else ""
                disp = ch.get("display") or {}
                ch_icon = disp.get("icon16x16") or ch.get("iconUrl") or ch.get("icon") or ""

                custom_file = CUSTOM_ICONS_DIR / f"{media_id}_{idx}.png"
                if custom_file.exists():
                    icon_display_url = f"/api/thumb?type=abs_chapter&id={media_id}&chapter={idx}&size=100&v={int(custom_file.stat().st_mtime)}"
                    has_custom = True
                elif ch_icon.startswith("yoto:#"):
                    icon_display_url = f"/api/thumb?type=yoto_icon&ref={ch_icon.replace('yoto:#', '')}&fallback_id={media_id}"
                    has_custom = True
                else:
                    icon_display_url = ch_icon or cover_url
                    has_custom = bool(ch_icon)

                ch_key = ch.get("key") or f"{idx + 1:02d}"
                ch_trks = ch.get("tracks") or []
                trk_key = (ch_trks[0].get("key") if ch_trks and isinstance(ch_trks[0], dict) else None) or ch_key
                tracks.append({
                    "index": idx,
                    "track_number": idx + 1,
                    "key": ch_key,
                    "track_key": trk_key,
                    "title": ch.get("title") or f"Track {idx + 1}",
                    "duration_seconds": dur,
                    "duration_formatted": dur_str,
                    "icon_url": icon_display_url,
                    "has_custom_icon": has_custom
                })

    # Fallback if no tracks were extracted
    if not tracks:
        tracks.append({
            "index": 0,
            "track_number": 1,
            "title": title,
            "duration_seconds": 0,
            "duration_formatted": "--:--",
            "icon_url": cover_url,
            "has_custom_icon": bool(cover_url)
        })

    return {
        "ok": True,
        "id": media_id,
        "type": media_type,
        "title": title,
        "author": author,
        "cover_url": cover_url,
        "can_edit": can_edit,
        "tracks": tracks
    }


def parse_track_names(raw_input: str) -> List[str]:
    """
    Parses flexible track name inputs:
    - Bullet list / Newline-delimited lines / Comma-delimited list.
    Strips leading bullet characters (•, -, *, ·) while preserving chapter titles.
    """
    if not raw_input or not isinstance(raw_input, str):
        return []

    lines = [ln.strip() for ln in raw_input.strip().splitlines() if ln.strip()]

    if len(lines) == 1 and "," in lines[0] and not lines[0].startswith(("•", "-", "*")):
        raw_items = [item.strip() for item in lines[0].split(",") if item.strip()]
    else:
        raw_items = lines

    cleaned: List[str] = []
    for item in raw_items:
        t = re.sub(r"^[\s•\-*·]+\s*", "", item).strip()
        if t:
            cleaned.append(t)
    return cleaned


# 3x4 pixel digits for corner numbers (matches Yoto pixel displays)
TINY_DIGITS = {
    "0": ["###", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#."],
    "2": ["##.", "..#", ".#.", "###"],
    "3": ["###", ".##", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#"],
    "5": ["###", "##.", "..#", "##."],
    "6": ["#..", "###", "#.#", "###"],
    "7": ["###", "..#", ".#.", ".#."],
    "8": ["###", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#"],
}


def extract_chapter_number(title: str, fallback_num: int = 1) -> int:
    """
    Extracts chapter number from title looking for 'Chapter 1', 'Ch. 2', 'Chap 3', 'Part 4',
    or leading digits ('01. Intro'). If no number is detected, defaults to fallback_num.
    """
    if not title:
        return fallback_num
    m = re.search(r'\b(?:chapter|chap|ch|c)\.?\s*#?\s*(\d+)\b', title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(?:part|pt|section|sec|track)\.?\s*#?\s*(\d+)\b', title, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'^\s*#?\s*(\d+)\s*[:.\-]', title)
    if m:
        return int(m.group(1))
    return fallback_num


def render_16x16_icon_with_overlay(raw_bytes: bytes, number: Optional[int] = None, corner: str = "top-right") -> bytes:
    """
    Center-crops raw image bytes to a square, resizes to 16x16, and optionally overlays
    a 3x4 pixel chapter/track number in the specified corner.
    """
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    w, h = img.size
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = (h - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))
    img = img.resize((16, 16), Image.Resampling.LANCZOS)

    if number is not None:
        text = str(max(0, number))[-3:]
        w_text = len(text) * 4 - 1
        x0 = (16 - w_text) if "right" in corner else 0
        y0 = (16 - 4) if "bottom" in corner else 0

        total_luma = 0.0
        count = 0
        for y in range(y0, min(16, y0 + 4)):
            for x in range(x0, min(16, x0 + w_text)):
                r, g, b, a = img.getpixel((x, y))
                total_luma += 0.299 * r + 0.587 * g + 0.114 * b
                count += 1
        avg_luma = total_luma / max(1, count)
        ink = (35, 35, 40, 255) if avg_luma > 140 else (240, 240, 245, 255)

        for n, ch in enumerate(text):
            if ch not in TINY_DIGITS:
                continue
            for cy, row in enumerate(TINY_DIGITS[ch]):
                for cx, c in enumerate(row):
                    if c == "#":
                        px_x = x0 + n * 4 + cx
                        px_y = y0 + cy
                        if 0 <= px_x < 16 and 0 <= px_y < 16:
                            curr = img.getpixel((px_x, px_y))
                            tinted = (
                                int(curr[0] * 0.25 + ink[0] * 0.75),
                                int(curr[1] * 0.25 + ink[1] * 0.75),
                                int(curr[2] * 0.25 + ink[2] * 0.75),
                                255
                            )
                            img.putpixel((px_x, px_y), tinted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
