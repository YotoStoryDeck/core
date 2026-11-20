"""
Audiobookshelf API client for library, item, and user metadata querying.
"""

import re
from typing import Dict, Any, List, Optional, Tuple
import requests
from core.config import logger


class ABSClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key.strip() if api_key else ""
        self._user_token_cache: Dict[str, str] = {}

    def get_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        auth_token = token if token else self.api_key
        return {
            "Authorization": f"Bearer {auth_token}",
            "Accept": "application/json"
        }

    def get_user_token(self, username: str) -> Optional[str]:
        """
        Retrieves the personal Bearer auth token for a given Audiobookshelf username
        by querying /api/users using the master administrative API key.
        Caches results in-memory.
        """
        if not username or not self.api_key or not self.base_url:
            return None

        uname_clean = username.strip().lower()
        if uname_clean in self._user_token_cache:
            return self._user_token_cache[uname_clean]

        try:
            headers = self.get_headers(self.api_key)
            res = requests.get(f"{self.base_url}/api/users", headers=headers, timeout=6)
            if res.status_code == 200:
                for u in res.json().get("users", []):
                    u_name = (u.get("username") or "").strip().lower()
                    u_token = u.get("token")
                    if u_token:
                        self._user_token_cache[u_name] = u_token
                return self._user_token_cache.get(uname_clean)
        except Exception as e:
            logger.debug("Failed to retrieve Audiobookshelf user token for '%s': %s", username, e)
        return None

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Fetches all configured Audiobookshelf user accounts using the master API key."""
        if not self.api_key or not self.base_url:
            return []
        try:
            res = requests.get(f"{self.base_url}/api/users", headers=self.get_headers(self.api_key), timeout=8)
            if res.status_code == 200:
                return res.json().get("users", [])
        except Exception as e:
            logger.debug("ABS get_all_users error: %s", e)
        return []

    def get_user_media_progress(self, user_id: str) -> List[Dict[str, Any]]:
        """Fetches mediaProgress entries for a specific Audiobookshelf user ID."""
        if not user_id or not self.api_key or not self.base_url:
            return []
        try:
            res = requests.get(f"{self.base_url}/api/users/{user_id}", headers=self.get_headers(self.api_key), timeout=8)
            if res.status_code == 200:
                return res.json().get("mediaProgress", [])
        except Exception as e:
            logger.debug("ABS get_user_media_progress error for '%s': %s", user_id, e)
        return []

    def get_libraries(self, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches all ABS libraries visible to the supplied token (or default api_key)."""
        headers = self.get_headers(token)
        if not headers.get("Authorization"):
            return []
        try:
            res = requests.get(f"{self.base_url}/api/libraries", headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json().get("libraries", [])
        except Exception as e:
            logger.error("ABS get_libraries error: %s", e)
        return []

    def get_items_for_profile(self, profile_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Retrieves audiobooks scoped for a specific child profile:
        1. Token/API Key:
           - Explicit override: `abs_api_key` or `abs_token`
           - Auto-resolved: queries child account's token via `abs_username` using master key
           - Fallback: master `self.api_key` (if unassigned)
        2. Audiobookshelf Server Filtering:
           - If using child account token, ABS automatically applies user permissions,
             allowed libraries, tag scoping (e.g. 'Children'), and explicit content limits!
        3. Local Overrides:
           - Limits scanning to `abs_library_id` if configured.
           - Filters by `abs_tag` if configured.
        """
        abs_username = (profile_cfg.get("abs_username") or "").strip()
        explicit_token = (profile_cfg.get("abs_api_key") or profile_cfg.get("abs_token") or "").strip()
        resolved_token = None

        if explicit_token:
            resolved_token = explicit_token
        elif abs_username:
            resolved_token = self.get_user_token(abs_username)

        token = resolved_token or self.api_key
        if not token:
            logger.warning("No ABS API key or child token configured.")
            return []

        target_lib_id = (profile_cfg.get("abs_library_id") or "").strip()
        tag_filter = (profile_cfg.get("abs_tag") or "").strip().lower()

        headers = self.get_headers(token)
        libraries = self.get_libraries(token)
        results: List[Dict[str, Any]] = []

        for lib in libraries:
            lib_id = lib.get("id")
            media_type = lib.get("mediaType", "book")
            if media_type != "book":
                continue

            # Check library ID constraint if specified
            if target_lib_id and lib_id != target_lib_id and lib.get("name", "").lower() != target_lib_id.lower():
                continue

            try:
                url = f"{self.base_url}/api/libraries/{lib_id}/items?limit=0"
                res = requests.get(url, headers=headers, timeout=15)
                if res.status_code != 200:
                    continue

                items = res.json().get("results", [])
                for item in items:
                    media = item.get("media", {})
                    metadata = media.get("metadata", {})
                    tags = [t.lower() for t in (metadata.get("tags") or item.get("tags") or [])]

                    # If tag filter is specified, require match; otherwise include all items in library
                    if tag_filter and tag_filter not in tags:
                        continue

                    item_id = item.get("id")
                    title = metadata.get("title") or item.get("name") or "Untitled"
                    author = metadata.get("authorName") or metadata.get("author") or "Unknown"

                    # Parse all series names and sequence values if available
                    raw_series = metadata.get("seriesName") or ""
                    series_list = []
                    fallback_seq = None
                    fallback_seq_disp = None
                    if title:
                        m_range = re.search(r"\b(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)", title, re.IGNORECASE)
                        if m_range:
                            fallback_seq_disp = re.sub(r"\s+", "", m_range.group(1))
                            m_lead = re.search(r"(\d+(?:\.\d+)?)", fallback_seq_disp)
                            if m_lead:
                                try:
                                    fallback_seq = float(m_lead.group(1))
                                except (ValueError, TypeError):
                                    pass
                        else:
                            m_book = re.search(r"\b(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)", title, re.IGNORECASE)
                            if m_book:
                                try:
                                    fallback_seq = float(m_book.group(1))
                                    fallback_seq_disp = str(m_book.group(1))
                                except (ValueError, TypeError):
                                    pass

                    if raw_series:
                        parts = [p.strip() for p in str(raw_series).split(",") if p.strip()]
                        for part in parts:
                            s_name = part
                            s_seq = fallback_seq
                            s_seq_disp = fallback_seq_disp
                            m = re.match(r"^(.*?)\s*#(\d+(?:\.\d+)?(?:\s*[-–—]\s*\d+(?:\.\d+)?)?)", part)
                            if m:
                                s_name = m.group(1).strip()
                                raw_val = m.group(2).strip()
                                s_seq_disp = re.sub(r"\s+", "", raw_val)
                                fnum = re.match(r"^(\d+(?:\.\d+)?)", s_seq_disp)
                                if fnum:
                                    try:
                                        s_seq = float(fnum.group(1))
                                    except (ValueError, TypeError):
                                        pass
                            if s_name:
                                series_list.append({
                                    "name": s_name,
                                    "sequence": s_seq,
                                    "sequence_display": s_seq_disp
                                })

                    primary_series = series_list[0]["name"] if series_list else ""
                    primary_sequence = series_list[0]["sequence"] if series_list else fallback_seq
                    primary_sequence_disp = series_list[0]["sequence_display"] if series_list else fallback_seq_disp

                    results.append({
                        "id": item_id,
                        "type": "abs",
                        "title": title,
                        "author": author,
                        "thumb": f"/api/thumb?type=abs&id={item_id}",
                        "series": primary_series,
                        "sequence": primary_sequence,
                        "sequence_display": primary_sequence_disp,
                        "series_list": series_list
                    })
            except Exception as e:
                logger.error("Error querying ABS library %s: %s", lib_id, e)

        # Sort ignoring leading articles 'The', 'A', 'An'
        results.sort(key=lambda x: re.sub(r"^(the|a|an)\s+", "", x["title"].strip(), flags=re.IGNORECASE).lower())
        return results

    def get_items_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Legacy helper: retrieves books by tag across all libraries using default key."""
        return self.get_items_for_profile({"abs_tag": tag})

    def get_item(self, item_id: str, token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetches full item details including chapters and description from Audiobookshelf."""
        headers = self.get_headers(token)
        try:
            url = f"{self.base_url}/api/items/{item_id}"
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logger.error("ABS get_item error for %s: %s", item_id, e)
        return None

    def get_item_tags(self, item_id: str) -> List[str]:
        """Retrieves list of tags assigned to a book media item."""
        data = self.get_item(item_id)
        if not data:
            return []
        media = data.get("media", {})
        return media.get("tags") or []

    def update_item_chapters(self, item_id: str, chapters: List[Dict[str, Any]]) -> bool:
        """Updates the chapter structure / track titles on an Audiobookshelf book via POST /api/items/{id}/chapters."""
        if not self.api_key:
            logger.warning("Cannot update ABS chapters: master API key not configured")
            return False
        headers = self.get_headers()
        try:
            url = f"{self.base_url}/api/items/{item_id}/chapters"
            res = requests.post(url, headers=headers, json={"chapters": chapters}, timeout=15)
            if res.status_code in (200, 204):
                logger.info("Successfully updated %d chapters on ABS item %s", len(chapters), item_id)
                return True
            logger.warning("Failed to update ABS chapters for %s (%d): %s", item_id, res.status_code, res.text)
        except Exception as e:
            logger.error("Exception updating ABS chapters for %s: %s", item_id, e)
        return False

    def update_item_tags(self, item_id: str, tags: List[str]) -> bool:
        """Updates the tags on an Audiobookshelf book via PATCH /api/items/{id}/media."""
        if not self.api_key:
            logger.warning("Cannot update ABS tags: master API key not configured")
            return False
        headers = self.get_headers()
        try:
            url = f"{self.base_url}/api/items/{item_id}/media"
            res = requests.patch(url, headers=headers, json={"tags": tags}, timeout=12)
            if res.status_code in (200, 204):
                logger.info("Successfully updated tags on ABS item %s: %s", item_id, tags)
                return True
            logger.warning("Failed to update ABS tags for %s (%d): %s", item_id, res.status_code, res.text)
        except Exception as e:
            logger.error("Exception updating ABS tags for %s: %s", item_id, e)
        return False

    def get_all_server_tags(self) -> List[str]:
        """Queries the complete list of unique tags in Audiobookshelf via /api/tags."""
        if not self.api_key:
            return []
        headers = self.get_headers()
        try:
            url = f"{self.base_url}/api/tags"
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                tags = res.json().get("tags", [])
                tags.sort(key=lambda s: s.lower())
                return tags
        except Exception as e:
            logger.error("Exception fetching ABS server tags: %s", e)
        return []

    def resolve_token_for_profile(self, profile_id: Optional[str] = None,
                                  device_id: Optional[str] = None) -> Optional[str]:
        """
        Resolves the Audiobookshelf Bearer token scoped to a child profile or Yoto player ID,
        falling back to the master API key if no profile mapping exists.
        """
        if not self.base_url:
            return None
        try:
            import database
            profiles = database.get_all_profiles()
            target_cfg = None
            if profile_id and profile_id in profiles:
                target_cfg = profiles[profile_id]
            elif device_id:
                for p_cfg in profiles.values():
                    if p_cfg.get("default_player_id") == device_id or device_id in (p_cfg.get("player_ids") or []):
                        target_cfg = p_cfg
                        break

            if target_cfg:
                explicit = (target_cfg.get("abs_api_key") or target_cfg.get("abs_token") or "").strip()
                if explicit:
                    return explicit
                uname = (target_cfg.get("abs_username") or "").strip()
                if uname:
                    resolved = self.get_user_token(uname)
                    if resolved:
                        return resolved
        except Exception as e:
            logger.debug("Profile token resolution notice (%s/%s): %s", profile_id, device_id, e)

        return self.api_key or None

    def get_media_progress(self, item_id: str, token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetches saved listening progress for an Audiobookshelf library item."""
        if not item_id or not self.base_url:
            return None
        try:
            res = requests.get(
                f"{self.base_url}/api/me/progress/{item_id}",
                headers=self.get_headers(token),
                timeout=8
            )
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logger.debug("ABS get_media_progress notice for %s: %s", item_id, e)
        return None

    def patch_media_progress(self, item_id: str, current_time: float, duration: float,
                             is_finished: bool = False, token: Optional[str] = None) -> bool:
        """Directly updates listening progress on Audiobookshelf via PATCH /api/me/progress/{id}."""
        if not item_id or not self.base_url:
            return False
        dur = float(duration or 0.0)
        cur_t = max(0.0, float(current_time or 0.0))
        progress = 1.0 if is_finished else (min(1.0, cur_t / dur) if dur > 0 else 0.0)
        payload = {
            "currentTime": round(cur_t, 1),
            "duration": dur,
            "progress": round(progress, 4),
            "isFinished": bool(is_finished),
        }
        try:
            res = requests.patch(
                f"{self.base_url}/api/me/progress/{item_id}",
                headers=self.get_headers(token),
                json=payload,
                timeout=8
            )
            return res.status_code in (200, 204)
        except Exception as e:
            logger.warning("ABS patch_media_progress error for %s: %s", item_id, e)
            return False

    def start_playback_session(self, item_id: str, device_id: str, device_name: str = "Yoto",
                               token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Opens an Audiobookshelf playback session via POST /api/items/{id}/play."""
        if not item_id or not self.base_url:
            return None
        payload = {
            "deviceInfo": {
                "deviceId": f"yoto-{device_id or 'storydeck'}",
                "clientName": "StoryDeck Core",
                "deviceName": device_name or "Yoto"
            },
            "forceDirectPlay": True,
            "forceTranscode": False,
            "mediaPlayer": "storydeck-core",
            "supportedMimeTypes": ["audio/mpeg", "audio/mp4", "audio/flac", "audio/ogg", "audio/aac"]
        }
        try:
            res = requests.post(
                f"{self.base_url}/api/items/{item_id}/play",
                headers=self.get_headers(token),
                json=payload,
                timeout=10
            )
            if res.status_code == 200:
                return res.json()
            logger.debug("ABS start_playback_session returned %d for %s", res.status_code, item_id)
        except Exception as e:
            logger.debug("ABS start_playback_session notice for %s: %s", item_id, e)
        return None

    def sync_playback_session(self, session_id: str, current_time: float, time_listened: float,
                              duration: float, token: Optional[str] = None) -> Tuple[bool, int]:
        """Reports interim playback progress to an open Audiobookshelf session."""
        if not session_id or not self.base_url:
            return False, 0
        payload = {
            "currentTime": round(max(0.0, float(current_time or 0.0)), 1),
            "timeListened": round(max(0.0, float(time_listened or 0.0)), 1),
            "duration": float(duration or 0.0)
        }
        try:
            res = requests.post(
                f"{self.base_url}/api/session/{session_id}/sync",
                headers=self.get_headers(token),
                json=payload,
                timeout=8
            )
            return res.status_code in (200, 204), res.status_code
        except Exception as e:
            logger.debug("ABS sync_playback_session notice for %s: %s", session_id, e)
            return False, 0

    def close_playback_session(self, session_id: str, current_time: float, time_listened: float,
                               duration: float, token: Optional[str] = None) -> bool:
        """Closes an active Audiobookshelf playback session with final listening telemetry."""
        if not session_id or not self.base_url:
            return False
        payload = {
            "currentTime": round(max(0.0, float(current_time or 0.0)), 1),
            "timeListened": round(max(0.0, float(time_listened or 0.0)), 1),
            "duration": float(duration or 0.0)
        }
        try:
            res = requests.post(
                f"{self.base_url}/api/session/{session_id}/close",
                headers=self.get_headers(token),
                json=payload,
                timeout=8
            )
            return res.status_code in (200, 204)
        except Exception as e:
            logger.debug("ABS close_playback_session notice for %s: %s", session_id, e)
            return False
