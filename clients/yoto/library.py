"""
Yoto Play Cloud device discovery, family library fetching, groups, and curation mixin.
"""
import json
import re
from pathlib import Path
from typing import Dict, Any, List
import requests
from core.config import logger


class YotoLibraryMixin:
    @staticmethod
    def _normalize_family_card(item: Dict[str, Any]) -> Dict[str, Any]:
        """Normalizes wrapped (/card/family/library) or flat Yoto card payloads into a canonical schema."""
        if not isinstance(item, dict):
            return {}

        cid = item.get("cardId") or item.get("id") or ""
        inner = item.get("card") if isinstance(item.get("card"), dict) else {}
        meta = inner.get("metadata") or item.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        content = inner.get("content") or item.get("content") or {}
        if not isinstance(content, dict):
            content = {}

        share_type = item.get("shareType") or inner.get("shareType") or ""
        reason = str(item.get("reason") or inner.get("reason") or "")
        if item.get("isMyo") is not None:
            is_myo = bool(item.get("isMyo"))
        elif inner.get("isMyo") is not None:
            is_myo = bool(inner.get("isMyo"))
        else:
            is_myo = (share_type == "myo") or reason.startswith("myo")

        title = item.get("title") or inner.get("title") or "Yoto Card"

        authors_list = meta.get("authors")
        raw_author = item.get("author") or meta.get("author")
        if not raw_author and isinstance(authors_list, list) and authors_list:
            first = authors_list[0]
            raw_author = first.get("name") if isinstance(first, dict) else (first if isinstance(first, str) else "")
        author = str(raw_author or "Yoto").strip() or "Yoto"

        meta_cover = meta.get("cover") if isinstance(meta.get("cover"), dict) else {}
        content_cover = content.get("cover") if isinstance(content.get("cover"), dict) else {}
        cover_url = (
            item.get("coverImageUrl")
            or item.get("iconUrl")
            or meta_cover.get("imageL")
            or meta_cover.get("imageM")
            or content_cover.get("imageL")
            or ""
        )

        series_name = (
            item.get("series")
            or meta.get("seriestitle")
            or meta.get("series")
            or meta.get("group")
            or inner.get("group")
            or item.get("group")
            or ""
        )
        raw_order = item.get("series_order")
        if raw_order is None or str(raw_order).strip() == "":
            raw_order = meta.get("seriesorder") or meta.get("seriesOrder") or ""

        last_played = (
            item.get("lastPlayedAt")
            or item.get("lastPlaybackAt")
            or inner.get("lastPlayedAt")
            or meta.get("lastPlayedAt")
            or ""
        )

        normalized = dict(item)
        normalized.update({
            "cardId": cid,
            "id": cid,
            "title": str(title),
            "author": author,
            "isMyo": is_myo,
            "coverImageUrl": cover_url,
            "series": str(series_name).strip() if series_name else "",
            "series_order": str(raw_order).strip() if raw_order not in (None, "") else "",
            "lastPlayedAt": last_played,
            "shareType": share_type,
            "metadata": meta,
            "content": content,
            "groups": list(item.get("groups") or inner.get("groups") or []),
        })
        if inner:
            normalized["card"] = inner
        return normalized

    def get_devices(self) -> List[Dict[str, Any]]:
        """Queries registered Yoto player devices from Yoto Cloud API v2 (/device-v2/devices/mine)."""
        token = self.get_token()
        if not token:
            return []

        url = f"{self.API_URL}/device-v2/devices/mine"
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    raw_devices = data if isinstance(data, list) else data.get("devices", data.get("items", []))
                    cleaned: List[Dict[str, Any]] = []
                    for d in (raw_devices or []):
                        if isinstance(d, dict):
                            item = dict(d)
                            if isinstance(item.get("name"), str):
                                item["name"] = item["name"].strip()
                            cleaned.append(item)
                    return cleaned
                if res.status_code in (401, 403) and attempt == 0:
                    token = self.get_token(force_refresh=True)
                    if token:
                        continue
                logger.warning("Yoto get_devices failed (%d): %s", res.status_code, (res.text or "")[:200])
                break
            except Exception as e:
                logger.error("Yoto get_devices error: %s", e)
                break
        return []

    def get_raw_library(self) -> List[Dict[str, Any]]:
        """Fetches raw cards from Yoto family library (direct Yoto Cloud with local cache fallback)."""
        cloud_cards = []
        token = self.get_token()
        if token:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            try:
                res = requests.get(f"{self.API_URL}/card/family/library", headers=headers, timeout=25)
                if res.status_code == 200:
                    cloud_cards = res.json().get("cards", [])
                else:
                    logger.debug("Yoto family library query notice: %d %s", res.status_code, res.text)
            except Exception as e:
                logger.debug("Yoto get_raw_library error: %s", e)

        local_cards = []
        if not cloud_cards:
            local_cards = self.load_local_family_library()

        combined_map: Dict[str, Dict[str, Any]] = {}
        for c in local_cards:
            norm = self._normalize_family_card(c)
            cid = norm.get("cardId") or norm.get("id")
            if cid:
                combined_map[cid] = norm

        for c in cloud_cards:
            norm = self._normalize_family_card(c)
            cid = norm.get("cardId") or norm.get("id")
            if cid:
                combined_map[cid] = norm

        # Deduplicate & filter StoryDeck-generated playlists from general retail library
        try:
            import database
            conn = database.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT slot_id FROM bridge_slots;")
            registered_slots = {row["slot_id"] for row in cur.fetchall()}
            conn.close()
        except Exception:
            registered_slots = set()

        filtered_cards = []
        for c in combined_map.values():
            cid = c.get("cardId") or c.get("id") or ""
            if cid in registered_slots or cid.startswith("profile_"):
                continue
            meta = c.get("metadata") or (c.get("card") or {}).get("metadata") or {}
            desc = (meta.get("description") or c.get("description") or "").lower()
            gen = (meta.get("generator") or c.get("generator") or "").lower()
            if "streams from audiobookshelf via" in desc or gen == "storydeck-core" or "storydeck" in desc:
                continue
            filtered_cards.append(c)

        return filtered_cards

    def load_local_family_library(self) -> List[Dict[str, Any]]:
        """Parses locally cached household Yoto library (e.g. data/yoto_library.json)."""
        root_dir = Path(__file__).resolve().parent.parent.parent
        candidate_paths = [
            root_dir / "data" / "yoto_library.json",
            Path("/app/data/yoto_library.json"),
        ]

        for p in candidate_paths:
            if p.is_file():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    raw_list = data.get("cards", [])
                    results = []
                    for item in raw_list:
                        cid = item.get("cardId") or item.get("id")
                        if not cid:
                            continue
                        results.append(self._normalize_family_card(item))
                    if results:
                        logger.info("Loaded %d cards from local library cache (%s)", len(results), p)
                        return results
                except Exception as e:
                    logger.warning("Error reading local Yoto library at %s: %s", p, e)
        return []

    def get_groups(self) -> List[Dict[str, Any]]:
        """
        Fetches user-defined Yoto family library card groups (folders/collections)
        from direct Yoto Cloud API or local JSON caches.
        """
        token = self.get_token()
        if token:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            try:
                res = requests.get(f"{self.API_URL}/card/family/library/groups", headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    raw_groups = data if isinstance(data, list) else data.get("groups", data.get("items", []))
                    if isinstance(raw_groups, dict):
                        raw_groups = list(raw_groups.values())
                    results = []
                    for g in raw_groups:
                        gid = g.get("id") or g.get("groupId") or ""
                        title = (g.get("title") or g.get("name") or "").strip()
                        card_ids = g.get("cardIds") or g.get("card_ids") or g.get("cards") or []
                        if not card_ids and g.get("items"):
                            card_ids = [item.get("contentId") for item in g.get("items", []) if item.get("contentId")]
                        clean_ids = [c if isinstance(c, str) else c.get("id") or c.get("cardId") for c in card_ids if c]
                        clean_ids = [c for c in clean_ids if c]
                        if title:
                            results.append({"id": gid, "title": title, "cardIds": clean_ids})
                    if results:
                        return results
            except Exception as e:
                logger.debug("Yoto Cloud groups query exception: %s", e)

        root_dir = Path(__file__).resolve().parent.parent.parent
        candidate_paths = [
            root_dir / "data" / "yoto_groups.json",
            root_dir / "data" / "yoto_library.json",
            Path("/app/data/yoto_groups.json"),
        ]

        for p in candidate_paths:
            if p.is_file():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    raw_groups = []
                    if isinstance(data, list):
                        raw_groups = data
                    elif isinstance(data, dict):
                        raw_groups = data.get("groups") or data.get("cardGroups") or []
                        if isinstance(raw_groups, dict):
                            raw_groups = list(raw_groups.values())
                    results = []
                    for g in raw_groups:
                        gid = g.get("id") or g.get("groupId") or ""
                        title = g.get("title") or g.get("name") or ""
                        card_ids = g.get("cardIds") or g.get("card_ids") or g.get("cards") or []
                        clean_ids = [c if isinstance(c, str) else c.get("id") or c.get("cardId") for c in card_ids if c]
                        clean_ids = [c for c in clean_ids if c]
                        if title:
                            results.append({"id": gid, "title": title, "cardIds": clean_ids})
                    if results:
                        logger.info("Loaded %d Yoto groups from local cache (%s)", len(results), p)
                        return results
                except Exception as e:
                    logger.warning("Error reading local Yoto groups at %s: %s", p, e)

        return []

    def get_curated_playlists_for_profile(self, profile_key: str, profile_cfg: Dict[str, Any], shared_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Filters the family library according to shared and child-specific curation rules:
        1. Base pool: shared_yoto (allowed_card_ids, regex match_titles, include_myo_by_default)
        2. Child overrides: inherit_shared, allowed_card_ids, regex match_titles
        3. Exclusions: excluded_card_ids
        """
        raw_cards = self.get_raw_library()
        if not raw_cards:
            return []

        shared_include_all = shared_cfg.get("include_all", False)
        shared_include_myo = shared_cfg.get("include_myo_by_default", True)
        shared_allowed = set(shared_cfg.get("allowed_card_ids", []))
        shared_regexes = [re.compile(p, re.IGNORECASE) for p in shared_cfg.get("match_titles", [])]

        child_yoto = profile_cfg.get("yoto", {})
        inherit_shared = child_yoto.get("inherit_shared", True)
        child_allowed = set(child_yoto.get("allowed_card_ids", []))
        child_excluded = set(child_yoto.get("excluded_card_ids", []))
        child_regexes = [re.compile(p, re.IGNORECASE) for p in child_yoto.get("match_titles", [])]

        selected_cards: List[Dict[str, Any]] = []

        for card in raw_cards:
            cid = card.get("cardId") or card.get("id")
            if not cid or cid in child_excluded:
                continue

            title = card.get("title") or "Yoto Playlist"
            is_myo = card.get("isMyo", False)
            is_included = False

            if cid in child_allowed:
                is_included = True
            if not is_included and any(r.search(title) for r in child_regexes):
                is_included = True
            if not is_included and inherit_shared:
                if shared_include_all:
                    is_included = True
                elif cid in shared_allowed:
                    is_included = True
                elif shared_include_myo and is_myo:
                    is_included = True
                elif any(r.search(title) for r in shared_regexes):
                    is_included = True

            if is_included:
                cover_url = card.get("coverImageUrl") or card.get("iconUrl") or ""
                card_series = card.get("series") or ""
                card_seq = None
                raw_seq = card.get("series_order")
                if raw_seq:
                    try:
                        card_seq = float(raw_seq)
                    except (ValueError, TypeError):
                        pass

                if not card_series:
                    for sep in [" - ", ": "]:
                        if sep in title:
                            candidate = title.split(sep)[0].strip()
                            if candidate:
                                card_series = candidate
                                break

                card_seq_disp = card.get("series_order") if card.get("series_order") is not None else None
                if card_seq_disp is not None and str(card_seq_disp).strip() != "":
                    card_seq_disp = str(card_seq_disp).strip()
                    m_lead = re.search(r"(\d+(?:\.\d+)?)", card_seq_disp)
                    if m_lead:
                        try:
                            card_seq = float(m_lead.group(1))
                        except (ValueError, TypeError):
                            pass

                if card_seq is None and title:
                    m_range = re.search(r"#\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)", title, re.IGNORECASE)
                    if m_range:
                        card_seq_disp = re.sub(r"\s+", "", m_range.group(1) or m_range.group(2))
                        m_lead = re.search(r"(\d+(?:\.\d+)?)", card_seq_disp)
                        if m_lead:
                            try:
                                card_seq = float(m_lead.group(1))
                            except (ValueError, TypeError):
                                pass
                    else:
                        m_num = re.search(r"#\s*(\d+(?:\.\d+)?)|\b(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)", title, re.IGNORECASE)
                        if m_num:
                            val = m_num.group(1) or m_num.group(2)
                            card_seq_disp = str(val).strip()
                            try:
                                card_seq = float(val)
                            except (ValueError, TypeError):
                                pass

                groups = list(card.get("groups") or [])
                series_list = []

                if card_series:
                    series_list.append({"name": card_series, "sequence": card_seq, "sequence_display": card_seq_disp})

                for sep in [" - ", ": "]:
                    if sep in title:
                        prefix = title.split(sep)[0].strip()
                        if prefix and not any(s["name"].lower() == prefix.lower() for s in series_list):
                            series_list.append({"name": prefix, "sequence": card_seq, "sequence_display": card_seq_disp})
                        break

                for g in groups:
                    if not any(s["name"].lower() == g.lower() for s in series_list):
                        series_list.append({"name": g, "sequence": card_seq, "sequence_display": card_seq_disp})

                primary_series = series_list[0]["name"] if series_list else card_series

                selected_cards.append({
                    "id": cid,
                    "type": "yoto",
                    "title": title,
                    "author": card.get("author") or "Yoto",
                    "thumb": f"/api/thumb?type=yoto&url={requests.utils.quote(cover_url)}" if cover_url else "",
                    "is_myo": is_myo,
                    "series": primary_series,
                    "sequence": card_seq,
                    "sequence_display": card_seq_disp,
                    "groups": groups,
                    "series_list": series_list
                })

        selected_cards.sort(key=lambda x: re.sub(r"^(the|a|an)\s+", "", x["title"].strip(), flags=re.IGNORECASE).lower())
        return selected_cards
