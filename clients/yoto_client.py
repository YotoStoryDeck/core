"""
Yoto Play Cloud and Yoto-Bridge API client.
"""

import time
import re
from typing import Dict, Any, List, Optional
import requests
from core.config import logger


class YotoClient:
    TOKEN_URL = "https://login.yotoplay.com/oauth/token"
    API_URL = "https://api.yotoplay.com"

    def __init__(self, client_id: str = "", client_secret: str = "", refresh_token: str = "", bridge_url: str = "", bridge_api_key: str = ""):
        self.client_id = client_id.strip() if client_id else ""
        self.client_secret = client_secret.strip() if client_secret else ""
        self.refresh_token = refresh_token.strip() if refresh_token else ""
        self.bridge_url = bridge_url.rstrip("/") if bridge_url else ""
        self.bridge_api_key = bridge_api_key.strip() if bridge_api_key else ""
        self.access_token: Optional[str] = None
        self.expires_at: float = 0.0

    def _bridge_headers(self) -> Dict[str, str]:
        """Builds HTTP headers for authenticating requests against the Yoto Streaming Bridge."""
        headers = {}
        if self.bridge_api_key:
            headers["X-Api-Key"] = self.bridge_api_key
        return headers


    def get_token(self) -> Optional[str]:
        """Returns active access token or refreshes it via OAuth grant."""
        if self.access_token and time.time() < self.expires_at - 60:
            return self.access_token

        if not self.client_id:
            return None

        # For public clients that use refresh tokens without client_secret:
        if self.refresh_token:
            try:
                payload = {
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": self.refresh_token
                }
                if self.client_secret:
                    payload["client_secret"] = self.client_secret

                res = requests.post(self.TOKEN_URL, json=payload, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    self.access_token = data.get("access_token")
                    if data.get("refresh_token"):
                        self.refresh_token = data.get("refresh_token")
                    expires_in = data.get("expires_in", 3600)
                    self.expires_at = time.time() + expires_in
                    logger.info("Refreshed Yoto OAuth access token (expires in %ds)", expires_in)
                    return self.access_token
                else:
                    logger.error("Failed to refresh Yoto token: %d %s", res.status_code, res.text)
            except Exception as e:
                logger.error("Yoto token refresh exception: %s", e)

        return None

    def get_devices(self) -> List[Dict[str, Any]]:
        """Queries registered Yoto player devices (Bridge-first, falling back to direct cloud)."""
        # 1. Bridge-First query
        if self.bridge_url:
            try:
                res = requests.get(f"{self.bridge_url}/api/status", headers=self._bridge_headers(), timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    devices = data.get("devices", [])
                    if devices:
                        return [{"deviceId": d.get("id"), "name": d.get("name"), "online": d.get("online", True)} for d in devices]
            except Exception as e:
                logger.debug("Bridge status query notice: %s", e)

        # 2. Direct Cloud fallback
        token = self.get_token()
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            res = requests.get(f"{self.API_URL}/device-v2", headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    return data
                return data.get("devices", data.get("items", []))
            elif res.status_code == 404:
                res2 = requests.get(f"{self.API_URL}/device/family/library", headers=headers, timeout=10)
                if res2.status_code == 200:
                    return res2.json().get("devices", [])
        except Exception as e:
            logger.error("Yoto get_devices error: %s", e)
        return []

    def get_raw_library(self) -> List[Dict[str, Any]]:
        """Fetches raw cards from Yoto library (combining Bridge MYO cards and local/cloud retail library)."""
        bridge_results: List[Dict[str, Any]] = []

        # 1. Bridge-First query
        if self.bridge_url:
            try:
                res = requests.get(f"{self.bridge_url}/api/yoto/playlists", headers=self._bridge_headers(), timeout=8)
                if res.status_code == 200:
                    bridge_cards = res.json()
                    if bridge_cards:
                        # Build lookup map from /api/cards on bridge (yoto_card_id -> cover/slot)
                        card_map: Dict[str, Dict[str, str]] = {}
                        try:
                            cards_res = requests.get(f"{self.bridge_url}/api/cards", headers=self._bridge_headers(), timeout=6)
                            if cards_res.status_code == 200:
                                for card in cards_res.json():
                                    y_cid = card.get("yoto_card_id")
                                    if y_cid:
                                        card_map[y_cid] = {
                                            "slot": card.get("slot", ""),
                                            "item_id": card.get("item_id", "")
                                        }
                        except Exception as e:
                            logger.debug("Bridge cards lookup exception: %s", e)

                        cards = []
                        for c in bridge_cards:
                            cid = c.get("cardId")
                            if not cid:
                                continue
                            title = c.get("title") or "Yoto Playlist"
                            is_bridge = bool(c.get("bridge"))
                            cover_url = ""

                            # Case A: Mapped in bridge /api/cards
                            if cid in card_map:
                                item_id = card_map[cid]["item_id"]
                                slot = card_map[cid]["slot"]
                                if item_id:
                                    cover_url = f"{self.bridge_url}/api/cover/{item_id}"
                                elif slot:
                                    cover_url = f"{self.bridge_url}/s/icon/{slot}.png"
                            # Case B: Virtual Audiobookshelf player card
                            elif "audiobookshelf on" in title.lower():
                                cover_url = "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png"
                            # Case C: Query metadata cover via iTunes Search API fallback
                            else:
                                try:
                                    import urllib.parse
                                    clean_query = title.replace("Pokmon", "Pokemon").replace("Pokémon", "Pokemon").split(",")[0].strip()
                                    search_url = f"https://itunes.apple.com/search?term={urllib.parse.quote(clean_query)}&limit=1"
                                    s_res = requests.get(search_url, timeout=4)
                                    if s_res.status_code == 200:
                                        results = s_res.json().get("results", [])
                                        if results and results[0].get("artworkUrl100"):
                                            cover_url = results[0]["artworkUrl100"].replace("100x100bb.jpg", "600x600bb.jpg")
                                except Exception as e:
                                    logger.debug("Failed iTunes artwork search for %s: %s", title, e)

                            cards.append({
                                "cardId": cid,
                                "id": cid,
                                "title": title,
                                "author": "Audiobookshelf" if "audiobookshelf on" in title.lower() else "Yoto",
                                "isMyo": True,
                                "coverImageUrl": cover_url
                            })
                        bridge_results = cards

                # Query Yoto custom groups from bridge if available (e.g. Disney, BrainBots, Dinosaurs)
                card_groups_map: Dict[str, List[str]] = {}
                try:
                    res_grp = requests.get(f"{self.bridge_url}/api/yoto/groups", headers=self._bridge_headers(), timeout=10)
                    if res_grp.status_code == 200:
                        raw_groups = res_grp.json()
                        if isinstance(raw_groups, list):
                            for g in raw_groups:
                                gname = (g.get("name") or "").strip()
                                # Ignore child account name group (e.g. 'Wesley') to avoid noise
                                if not gname:
                                    continue
                                for itm in g.get("items", []):
                                    cnt_id = itm.get("contentId")
                                    if cnt_id:
                                        if cnt_id not in card_groups_map:
                                            card_groups_map[cnt_id] = []
                                        if gname not in card_groups_map[cnt_id]:
                                            card_groups_map[cnt_id].append(gname)
                except Exception as e:
                    logger.debug("Bridge groups query notice: %s", e)

                # Also query full family library from bridge if exposed
                try:
                    res_lib = requests.get(f"{self.bridge_url}/api/yoto/library", headers=self._bridge_headers(), timeout=30)
                    if res_lib.status_code == 200:
                        raw_lib = res_lib.json()
                        lib_cards = raw_lib if isinstance(raw_lib, list) else raw_lib.get("cards", [])
                        for item in lib_cards:
                            cid = item.get("cardId")
                            if not cid:
                                continue
                            c = item.get("card") or {}
                            meta = c.get("metadata") or {}
                            content = c.get("content") or {}
                            cover_url = meta.get("cover", {}).get("imageL") or content.get("cover", {}).get("imageL") or ""
                            share_type = item.get("shareType", "")
                            is_myo = (share_type == "myo") or bool(item.get("reason", "").startswith("myo")) or c.get("isMyo", False)
                            s_name = meta.get("seriestitle") or meta.get("series") or meta.get("group") or c.get("group") or ""
                            s_ord = meta.get("seriesorder") or ""
                            bridge_results.append({
                                "cardId": cid,
                                "id": cid,
                                "title": c.get("title") or item.get("title") or "Yoto Title",
                                "author": meta.get("author") or "Yoto",
                                "isMyo": is_myo,
                                "coverImageUrl": cover_url,
                                "series": str(s_name).strip() if s_name else "",
                                "series_order": str(s_ord).strip() if s_ord else "",
                                "groups": card_groups_map.get(cid, [])
                            })
                except Exception as e:
                    logger.debug("Bridge family library query notice: %s", e)
            except Exception as e:
                logger.debug("Bridge playlists query notice: %s", e)

        # 2. Direct Cloud query (if token configured)
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

        # 3. Local/Cached Family Library only as a fallback if no bridge or cloud cards found
        local_cards = []
        if not bridge_results and not cloud_cards:
            local_cards = self.load_local_family_library()

        # Combine items uniquely by cardId / id
        combined_map: Dict[str, Dict[str, Any]] = {}
        for c in local_cards:
            cid = c.get("cardId") or c.get("id")
            if cid:
                combined_map[cid] = c

        for c in cloud_cards:
            cid = c.get("cardId") or c.get("id")
            if cid:
                combined_map[cid] = c

        # Bridge playlists & library take precedence for live household data
        for c in bridge_results:
            cid = c.get("cardId") or c.get("id")
            if cid:
                combined_map[cid] = c

        return list(combined_map.values())

    def load_local_family_library(self) -> List[Dict[str, Any]]:
        """Parses locally cached household Yoto library (e.g. data/yoto_library.json)."""
        import json
        import os
        from pathlib import Path

        candidate_paths = [
            Path(__file__).parent.parent / "data" / "yoto_library.json",
            Path(__file__).parent.parent.parent.parent / "yoto-esp32-controller" / "fam.json",
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
                        cid = item.get("cardId")
                        if not cid:
                            continue
                        c = item.get("card") or {}
                        meta = c.get("metadata") or {}
                        content = c.get("content") or {}
                        
                        # Extract cover
                        cover_url = (
                            meta.get("cover", {}).get("imageL")
                            or content.get("cover", {}).get("imageL")
                            or ""
                        )
                        
                        share_type = item.get("shareType", "")
                        is_myo = (share_type == "myo") or bool(item.get("reason", "").startswith("myo")) or c.get("isMyo", False)

                        # Extract series / group metadata
                        series_name = (
                            meta.get("seriestitle")
                            or meta.get("series")
                            or meta.get("group")
                            or c.get("group")
                            or ""
                        )
                        series_order = meta.get("seriesorder") or ""

                        results.append({
                            "cardId": cid,
                            "id": cid,
                            "title": c.get("title") or item.get("title") or "Yoto Title",
                            "author": meta.get("author") or meta.get("authors", ["Yoto"])[0] if isinstance(meta.get("authors"), list) and meta.get("authors") else "Yoto",
                            "isMyo": is_myo,
                            "coverImageUrl": cover_url,
                            "series": str(series_name).strip() if series_name else "",
                            "series_order": str(series_order).strip() if series_order else ""
                        })
                    if results:
                        logger.info("Loaded %d cards from local library cache (%s)", len(results), p)
                        return results
                except Exception as e:
                    logger.warning("Error reading local Yoto library at %s: %s", p, e)
        return []

    def get_groups(self) -> List[Dict[str, Any]]:
        """
        Fetches user-defined Yoto family library card groups (folders/collections).
        Queries direct Yoto Cloud API (GET /card/family/library/groups) if authenticated,
        checks bridge endpoints if available, and inspects locally cached files
        (data/yoto_groups.json, data/yoto_library.json).
        Returns list of dicts: [{"id": str, "title": str, "cardIds": [str, ...]}, ...]
        """
        # 1. Direct Cloud API Query
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
                        # Also parse content-group items structure: [{"contentId": "18zSS", ...}, ...]
                        if not card_ids and g.get("items"):
                            card_ids = [item.get("contentId") for item in g.get("items", []) if item.get("contentId")]
                        clean_ids = [c if isinstance(c, str) else c.get("id") or c.get("cardId") for c in card_ids if c]
                        clean_ids = [c for c in clean_ids if c]
                        if title:
                            results.append({
                                "id": gid,
                                "title": title,
                                "cardIds": clean_ids
                            })
                    if results:
                        return results
            except Exception as e:
                logger.debug("Yoto Cloud groups query exception: %s", e)

        # 2. Bridge forward-compatibility check
        if self.bridge_url:
            for b_ep in ["/api/yoto/groups", "/api/groups"]:
                try:
                    res = requests.get(f"{self.bridge_url}{b_ep}", headers=self._bridge_headers(), timeout=15)
                    if res.status_code == 200:
                        data = res.json()
                        raw_groups = data if isinstance(data, list) else data.get("groups", [])
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
                                results.append({
                                    "id": gid,
                                    "title": title,
                                    "cardIds": clean_ids
                                })
                        if results:
                            return results
                except Exception as e:
                    logger.debug("Bridge groups endpoint %s check: %s", b_ep, e)

        # 3. Local/Cached JSON Files
        import json
        from pathlib import Path

        candidate_paths = [
            Path(__file__).parent.parent / "data" / "yoto_groups.json",
            Path(__file__).parent.parent / "data" / "yoto_library.json",
            Path(__file__).parent.parent.parent.parent / "yoto-esp32-controller" / "groups.json",
            Path(__file__).parent.parent.parent.parent / "yoto-esp32-controller" / "fam.json",
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
                            results.append({
                                "id": gid,
                                "title": title,
                                "cardIds": clean_ids
                            })
                    if results:
                        logger.info("Loaded %d Yoto groups from local cache (%s)", len(results), p)
                        return results
                except Exception as e:
                    logger.warning("Error reading local Yoto groups at %s: %s", p, e)

        return []

    def get_playlists(self) -> List[Dict[str, Any]]:
        """Fetches all family library playlists / cards without curation (fallback)."""
        cards = self.get_raw_library()
        results: List[Dict[str, Any]] = []
        for c in cards:
            card_id = c.get("cardId") or c.get("id")
            title = c.get("title") or "Yoto Playlist"
            cover_url = c.get("coverImageUrl") or c.get("iconUrl") or ""
            
            results.append({
                "id": card_id,
                "type": "yoto",
                "title": title[:37] + "..." if len(title) > 40 else title,
                "author": c.get("author") or "Yoto",
                "thumb": f"/api/thumb?type=yoto&url={requests.utils.quote(cover_url)}" if cover_url else "",
                "is_myo": c.get("isMyo", False)
            })
        results.sort(key=lambda x: x["title"].lower())
        return results

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

        # 1. Evaluate Shared Base
        shared_include_all = shared_cfg.get("include_all", False)
        shared_include_myo = shared_cfg.get("include_myo_by_default", True)
        shared_allowed = set(shared_cfg.get("allowed_card_ids", []))
        shared_regexes = [re.compile(p, re.IGNORECASE) for p in shared_cfg.get("match_titles", [])]

        # 2. Child rules
        child_yoto = profile_cfg.get("yoto", {})
        inherit_shared = child_yoto.get("inherit_shared", True)
        child_allowed = set(child_yoto.get("allowed_card_ids", []))
        child_excluded = set(child_yoto.get("excluded_card_ids", []))
        child_regexes = [re.compile(p, re.IGNORECASE) for p in child_yoto.get("match_titles", [])]

        selected_cards: List[Dict[str, Any]] = []

        for card in raw_cards:
            cid = card.get("cardId") or card.get("id")
            if not cid:
                continue

            # Strict exclusion always wins
            if cid in child_excluded:
                continue

            title = card.get("title") or "Yoto Playlist"
            is_myo = card.get("isMyo", False)
            is_included = False

            # Check direct child allowed
            if cid in child_allowed:
                is_included = True

            # Check child regexes
            if not is_included and any(r.search(title) for r in child_regexes):
                is_included = True

            # Check shared rules if inheriting
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

                # If no explicit series, deduce common series name from title prefix (e.g. 'Magic Tree House - ...')
                if not card_series:
                    for sep in [" - ", ": "]:
                        if sep in title:
                            candidate = title.split(sep)[0].strip()
                            if candidate:
                                card_series = candidate
                                break

                # Deduce sequence from title if missing (e.g. Book 3, Vol 2, or #5, or ranges #1-3)
                card_seq_disp = card.get("series_order") or None
                if card_seq_disp:
                    card_seq_disp = str(card_seq_disp).strip()
                    try:
                        card_seq = float(card_seq_disp.split("-")[0])
                    except (ValueError, TypeError):
                        pass

                if card_seq is None and title:
                    m_range = re.search(r"#\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)", title, re.IGNORECASE)
                    if m_range:
                        card_seq_disp = re.sub(r"\s+", "", m_range.group(1) or m_range.group(2))
                        try:
                            card_seq = float(card_seq_disp.split("-")[0])
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

                # Collect all series and groups this card belongs to
                groups = list(card.get("groups") or [])
                series_list = []

                # Add explicit or deduced album series
                if card_series:
                    series_list.append({"name": card_series, "sequence": card_seq, "sequence_display": card_seq_disp})

                # If title contains an album or sub-series prefix (e.g. BrainBots: Our Planet, BrainBots Science Fair)
                for sep in [" - ", ": "]:
                    if sep in title:
                        prefix = title.split(sep)[0].strip()
                        if prefix and not any(s["name"].lower() == prefix.lower() for s in series_list):
                            series_list.append({"name": prefix, "sequence": card_seq, "sequence_display": card_seq_disp})
                        break

                # Add Yoto Groups (e.g. 'Disney', 'BrainBots', 'Dinosaurs')
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

        # Sort ignoring leading articles 'The', 'A', 'An'
        selected_cards.sort(key=lambda x: re.sub(r"^(the|a|an)\s+", "", x["title"].strip(), flags=re.IGNORECASE).lower())
        return selected_cards

    def set_volume(self, device_id: str, volume: int) -> bool:
        """Sets playback volume level (0-100) on a target Yoto player via Yoto Cloud API."""
        token = self.get_token()
        if not token:
            return False

        vol_val = max(0, min(100, int(volume)))
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        # Yoto device command endpoints: POST /device-v2/{device_id}/command/volume/set or volume
        # Also try volume endpoint
        url = f"{self.API_URL}/device-v2/{device_id}/command/volume/set"
        try:
            res = requests.post(url, json={"volume": vol_val}, headers=headers, timeout=5)
            if res.status_code in (200, 204):
                logger.info("Successfully set volume to %d%% on Yoto %s via Cloud API", vol_val, device_id)
                return True
            if res.status_code == 404:
                url_alt = f"{self.API_URL}/device-v2/{device_id}/command/volume"
                res_alt = requests.post(url_alt, json={"volume": vol_val}, headers=headers, timeout=5)
                if res_alt.status_code in (200, 204):
                    logger.info("Successfully set volume to %d%% on Yoto %s via alt Cloud API", vol_val, device_id)
                    return True
            logger.warning("Yoto volume command rejected (%d): %s", res.status_code, res.text)
        except Exception as e:
            logger.error("Yoto volume dispatch error on %s: %s", device_id, e)
        return False

    def send_transport_command(self, device_id: str, action: str) -> bool:
        """Sends transport control (pause, resume, stop) to target Yoto player via Yoto Cloud API."""
        token = self.get_token()
        if not token:
            return False

        if action not in ("pause", "resume", "stop"):
            return False

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = f"{self.API_URL}/device-v2/{device_id}/command/card/{action}"
        try:
            res = requests.post(url, json={}, headers=headers, timeout=5)
            if res.status_code in (200, 204):
                logger.info("Successfully sent '%s' to Yoto %s via Cloud API", action, device_id)
                return True
            logger.warning("Yoto transport '%s' command rejected (%d): %s", action, res.status_code, res.text)
        except Exception as e:
            logger.error("Yoto transport command error on %s: %s", device_id, e)
        return False

    def start_playback(self, device_id: str, card_id: str, chapter: int = 1) -> bool:
        """Triggers playback of a card on a target Yoto player."""
        token = self.get_token()
        if not token:
            return False

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = f"{self.API_URL}/device-v2/{device_id}/command/card/start"
        key = f"{max(1, int(chapter)):02d}"
        payload = {
            "uri": f"https://yoto.io/{card_id}",
            "chapterKey": key,
            "trackKey": key
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.status_code in (200, 204):
                logger.info("Successfully commanded Yoto %s to play %s", device_id, card_id)
                return True
            logger.warning("Yoto play command rejected (%d): %s", res.status_code, res.text)
        except Exception as e:
            logger.error("Yoto playback dispatch error: %s", e)
        return False

    def get_card_detail(self, card_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves detailed metadata for a Yoto card (including tracklist, durations, and chapter icons).
        Checks Bridge /api/yoto/card/{card_id} or direct Yoto Cloud API.
        """
        if not card_id:
            return None

        # 1. Try Bridge endpoint
        if self.bridge_url:
            try:
                res = requests.get(f"{self.bridge_url}/api/yoto/card/{card_id}", headers=self._bridge_headers(), timeout=15)
                if res.status_code == 200:
                    return res.json()
            except Exception as e:
                logger.debug("Bridge get_card_detail error for %s: %s", card_id, e)

        # 2. Try Direct Cloud API
        token = self.get_token()
        if token:
            try:
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                res = requests.get(f"{self.API_URL}/content/{card_id}", headers=headers, timeout=15)
                if res.status_code == 200:
                    return res.json()
            except Exception as e:
                logger.debug("Cloud get_card_detail error for %s: %s", card_id, e)

        # 3. Check local family library cache
        raw_lib = self.get_raw_library()
        for item in raw_lib:
            if item.get("cardId") == card_id or item.get("id") == card_id:
                return item

        return None

    def update_card_playlist(self, card_id: str, title: Optional[str] = None, chapters: Optional[List[Dict[str, Any]]] = None, cover_url: Optional[str] = None) -> bool:
        """
        Updates an existing MYO playlist on Yoto Cloud via Bridge PUT /api/yoto/card/{card_id} or direct Yoto Cloud.
        """
        if not card_id:
            return False

        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = title
        if chapters is not None:
            payload["chapters"] = chapters
        if cover_url:
            payload["cover_url"] = cover_url

        # 1. Try Bridge
        if self.bridge_url:
            try:
                res = requests.put(f"{self.bridge_url}/api/yoto/card/{card_id}", headers=self._bridge_headers(), json=payload, timeout=20)
                if res.status_code in (200, 204):
                    logger.info("Successfully updated MYO card %s via bridge", card_id)
                    return True
                logger.warning("Bridge update_card_playlist for %s failed (%d): %s", card_id, res.status_code, res.text)
            except Exception as e:
                logger.error("Exception updating MYO card %s via bridge: %s", card_id, e)

        # 2. Try direct Cloud API if authenticated
        token = self.get_token()
        if token:
            try:
                detail = self.get_card_detail(card_id) or {}
                content = detail.get("content", {})
                if chapters is not None:
                    content["chapters"] = chapters
                body = {
                    "cardId": card_id,
                    "title": title or detail.get("title", ""),
                    "content": content,
                    "metadata": detail.get("metadata", {})
                }
                if cover_url:
                    body["metadata"]["cover"] = {"imageL": cover_url}
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                res = requests.post(f"{self.API_URL}/content", headers=headers, json=body, timeout=20)
                if res.status_code in (200, 201):
                    logger.info("Successfully updated MYO card %s via direct Yoto Cloud", card_id)
                    return True
            except Exception as e:
                logger.error("Exception updating MYO card %s via direct Yoto Cloud: %s", card_id, e)

        return False

    def upload_display_icon(self, image_bytes: bytes, filename: str = "icon.png") -> Optional[str]:
        """
        Uploads a 16x16 PNG to Yoto Cloud (via Bridge or direct API) and returns 'yoto:#<mediaId>'.
        """
        # 1. Try Bridge
        if self.bridge_url:
            try:
                headers = self._bridge_headers()
                headers["Content-Type"] = "image/png"
                res = requests.post(f"{self.bridge_url}/api/yoto/icons/upload", headers=headers, data=image_bytes, timeout=15)
                if res.status_code == 200:
                    return res.json().get("icon_ref")
            except Exception as e:
                logger.error("Bridge upload_display_icon error: %s", e)

        # 2. Try Direct Cloud API
        token = self.get_token()
        if token:
            try:
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "image/png"}
                params = {"autoConvert": "false", "filename": filename}
                res = requests.post(f"{self.API_URL}/media/displayIcons/user/me/upload", headers=headers, params=params, data=image_bytes, timeout=15)
                if res.status_code in (200, 201):
                    data = res.json()
                    media_id = data.get("displayIcon", {}).get("mediaId")
                    if media_id:
                        return f"yoto:#{media_id}"
            except Exception as e:
                logger.error("Direct Yoto Cloud upload_display_icon error: %s", e)

        return None

    def push_item_chapter_icons_batch(self, item_id: str, tracks_b64: Dict[str, str]) -> bool:
        """
        Pushes a batch of 16x16 chapter icons directly to the Yoto Bridge item-level cache.
        tracks_b64 maps 1-indexed track string numbers ("1", "2", ...) to base64-encoded PNG strings.
        """
        if not self.bridge_url:
            return False
        try:
            url = f"{self.bridge_url}/api/items/{item_id}/icon/chapters/batch"
            headers = self._bridge_headers()
            headers["Content-Type"] = "application/json"
            res = requests.post(url, json={"tracks": tracks_b64}, headers=headers, timeout=15)
            if res.status_code == 200:
                logger.info("Successfully pushed %d chapter icon(s) to Bridge item cache for %s", len(tracks_b64), item_id)
                return True
            logger.warning("Bridge item icons batch push failed (%d): %s", res.status_code, res.text)
        except Exception as e:
            logger.error("Exception pushing item chapter icons to Bridge: %s", e)
        return False

    def get_item_chapter_icon(self, item_id: str, chapter_number: int) -> Optional[bytes]:
        """
        Fetches 16x16 PNG for an item chapter directly from the Yoto Bridge item-level cache.
        chapter_number is 1-indexed.
        """
        if not self.bridge_url:
            return None
        try:
            url = f"{self.bridge_url}/api/items/{item_id}/icon/chapters/{chapter_number}"
            headers = self._bridge_headers()
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200 and res.content:
                return res.content
        except Exception as e:
            logger.debug("Bridge get_item_chapter_icon notice for %s ch %d: %s", item_id, chapter_number, e)
        return None

