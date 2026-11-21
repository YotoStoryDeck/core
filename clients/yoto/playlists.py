"""
Yoto Play Cloud MYO playlists, audio uploads, and display icons mixin.
"""
import time
from typing import Dict, Any, List, Optional
import requests
from core.config import logger


class YotoPlaylistsMixin:
    def get_card_detail(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves unwrapped card metadata/chapters from Yoto Cloud (/content/{id} or retail /card/{id})."""
        if not card_id:
            return None

        token = self.get_token()
        if token:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            for path in (f"/content/{card_id}", f"/card/{card_id}"):
                try:
                    res = requests.get(f"{self.API_URL}{path}", headers=headers, timeout=15)
                    if res.status_code == 200:
                        data = res.json()
                        if isinstance(data, dict) and isinstance(data.get("card"), dict):
                            return data["card"]
                        return data
                except Exception as e:
                    logger.debug("Cloud get_card_detail error on %s for %s: %s", path, card_id, e)

        raw_lib = self.get_raw_library()
        for item in raw_lib:
            if item.get("cardId") == card_id or item.get("id") == card_id:
                return item

        return None

    def update_card_playlist(self, card_id: str, title: Optional[str] = None,
                             chapters: Optional[List[Dict[str, Any]]] = None,
                             cover_url: Optional[str] = None) -> bool:
        """Updates an existing MYO playlist on Yoto Cloud via direct Cloud API."""
        if not card_id:
            return False

        token = self.get_token()
        if not token:
            return False

        try:
            detail_raw = self.get_card_detail(card_id) or {}
            detail = detail_raw.get("card") if isinstance(detail_raw.get("card"), dict) else detail_raw
            content = dict(detail.get("content") or {})
            metadata = dict(detail.get("metadata") or {})
            if chapters is not None:
                content["chapters"] = chapters
            body = {
                "cardId": card_id,
                "title": title or detail.get("title", ""),
                "content": content,
                "metadata": metadata,
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

    def get_all_cloud_playlists(self) -> List[Dict[str, Any]]:
        """Queries all user playlists directly from Yoto Cloud via GET /content/mine."""
        token = self.get_token()
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            res = requests.get(f"{self.API_URL}/content/mine", headers=headers, timeout=20)
            if res.status_code == 200:
                data = res.json()
                return data.get("cards", data if isinstance(data, list) else [])
        except Exception as e:
            logger.error("Exception fetching cloud playlists: %s", e)
        return []

    def delete_playlist(self, card_id: str) -> bool:
        """Deletes a playlist from Yoto Cloud via DELETE /content/{card_id}."""
        token = self.get_token()
        if not token:
            logger.error("Cannot delete playlist %s: No Yoto access token", card_id)
            return False
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            res = requests.delete(f"{self.API_URL}/content/{card_id}", headers=headers, timeout=15)
            if res.status_code in (200, 204):
                logger.info("Successfully deleted Yoto playlist %s", card_id)
                return True
            logger.warning("Yoto delete playlist %s failed (%d): %s", card_id, res.status_code, res.text)
            return False
        except Exception as e:
            logger.error("Exception deleting Yoto playlist %s: %s", card_id, e)
            return False

    def upload_audio(self, audio: bytes, title: str, on_phase=None) -> Dict[str, Any]:
        """Uploads an MP3 track to Yoto Cloud transcoding pipeline and returns sha/duration/fileSize."""
        token = self.get_token()
        if not token:
            raise RuntimeError("Cannot upload audio: No Yoto access token")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        if on_phase:
            on_phase("uploading")

        res = requests.get(f"{self.API_URL}/media/transcode/audio/uploadUrl", headers=headers, timeout=15)
        if res.status_code != 200:
            raise RuntimeError(f"Yoto uploadUrl request failed ({res.status_code}): {res.text}")
        up = res.json().get("upload", {})
        upload_url = up.get("uploadUrl")
        upload_id = up.get("uploadId")
        if not upload_url or not upload_id:
            raise RuntimeError("Missing uploadUrl or uploadId in Yoto response")

        put_res = requests.put(upload_url, data=audio, headers={"Content-Type": "audio/mpeg"}, timeout=600)
        if put_res.status_code not in (200, 201, 204):
            raise RuntimeError(f"Yoto PUT audio failed ({put_res.status_code}): {put_res.text[:200]}")

        if on_phase:
            on_phase("processing")
        began = time.time()
        poll_interval = 2.0
        timeout = 900.0
        while time.time() - began < timeout:
            t_res = requests.get(
                f"{self.API_URL}/media/upload/{upload_id}/transcoded",
                headers=headers, params={"loudnorm": "false"}, timeout=15
            )
            if t_res.status_code == 200:
                t = t_res.json().get("transcode", {})
                sha = t.get("transcodedSha256")
                if sha:
                    info = t.get("transcodedInfo") or {}
                    logger.info("Yoto processed %s in %.1fs (sha: %s)", title, time.time() - began, sha[:8])
                    return {
                        "sha": sha,
                        "duration": info.get("duration"),
                        "fileSize": info.get("fileSize"),
                        "channels": info.get("channels") or "mono",
                        "format": info.get("format") or "mp3"
                    }
            time.sleep(poll_interval)

        raise TimeoutError(f"Yoto transcode timed out after {timeout}s for {title}")

    def save_stream_playlist(self, title: str, tracks: List[Dict[str, Any]], card_id: Optional[str] = None,
                             cover_url: Optional[str] = None, description: str = "") -> Optional[str]:
        """Creates or overwrites a streaming playlist in Yoto Cloud."""
        token = self.get_token()
        if not token:
            logger.error("Cannot save stream playlist %s: No Yoto access token", title)
            return None
        chapters = []
        for t in tracks:
            key_str = f"{int(t.get('track_idx', 1)):02d}"
            track = {
                "key": key_str,
                "title": t.get("title") or title,
                "overlayLabel": str(int(t.get("track_idx", 1))),
                "type": "stream",
                "format": "mp3",
                "trackUrl": t.get("stream_url") or t.get("url") or ""
            }
            if t.get("icon_url"):
                track["display"] = {"iconUrl16x16": t["icon_url"]}
            chapter = {
                "key": key_str,
                "title": t.get("title") or title,
                "overlayLabel": str(int(t.get("track_idx", 1))),
                "tracks": [track]
            }
            if t.get("icon_url"):
                chapter["display"] = {"iconUrl16x16": t["icon_url"]}
            chapters.append(chapter)

        body = {
            "title": title,
            "content": {"chapters": chapters},
            "metadata": {
                "description": description or "Streams from Audiobookshelf via StoryDeck Core",
                "generator": "storydeck-core"
            }
        }
        if card_id:
            body["cardId"] = card_id
        if cover_url:
            body["metadata"]["cover"] = {"imageL": cover_url}

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            res = requests.post(f"{self.API_URL}/content", headers=headers, json=body, timeout=20)
            if res.status_code in (200, 201):
                data = res.json()
                cid = data.get("card", {}).get("cardId") or data.get("cardId") or card_id
                logger.info("Successfully saved stream playlist %s (cardId: %s)", title, cid)
                return cid
            logger.warning("Yoto save_stream_playlist failed (%d): %s", res.status_code, res.text)
        except Exception as e:
            logger.error("Exception saving stream playlist: %s", e)
        return None

    def save_track_playlist(self, title: str, tracks: List[Dict[str, Any]], card_id: str,
                            cover_url: Optional[str] = None, description: str = "") -> Optional[str]:
        """Overwrites a card playlist with offline uploaded tracks (yoto:#sha256)."""
        token = self.get_token()
        if not token:
            logger.error("Cannot save track playlist %s: No Yoto access token", title)
            return None
        chapters = []
        total_size = 0
        total_duration = 0.0
        for t in tracks:
            key_str = f"{int(t.get('track_idx', 1)):02d}"
            sha = t.get("sha") or t.get("yoto_sha256")
            f_size = t.get("fileSize") or 0
            dur = float(t.get("duration") or 0.0)
            total_size += f_size
            total_duration += dur
            track = {
                "key": key_str,
                "title": t.get("title") or title,
                "overlayLabel": str(int(t.get("track_idx", 1))),
                "type": "audio" if sha else "stream",
                "trackUrl": f"yoto:#{sha}" if sha else (t.get("stream_url") or ""),
                "format": "mp3",
                "fileSize": f_size,
                "duration": dur
            }
            if t.get("icon"):
                track["display"] = {"icon16x16": t["icon"]}
            elif t.get("icon_url"):
                track["display"] = {"iconUrl16x16": t["icon_url"]}

            chapter = {
                "key": key_str,
                "title": t.get("title") or title,
                "overlayLabel": str(int(t.get("track_idx", 1))),
                "tracks": [track]
            }
            if t.get("icon"):
                chapter["display"] = {"icon16x16": t["icon"]}
            elif t.get("icon_url"):
                chapter["display"] = {"iconUrl16x16": t["icon_url"]}
            chapters.append(chapter)

        body = {
            "title": title,
            "cardId": card_id,
            "content": {"chapters": chapters},
            "metadata": {
                "description": description or "Transcoded for offline playback via StoryDeck Core",
                "generator": "storydeck-core",
                "media": {
                    "duration": total_duration,
                    "fileSize": total_size,
                    "readableFileSize": f"{round(total_size / 1e6, 1)} MB"
                }
            }
        }
        if cover_url:
            body["metadata"]["cover"] = {"imageL": cover_url}

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            res = requests.post(f"{self.API_URL}/content", headers=headers, json=body, timeout=25)
            if res.status_code in (200, 201):
                data = res.json()
                cid = data.get("card", {}).get("cardId") or data.get("cardId") or card_id
                logger.info("Successfully saved offline track playlist %s (cardId: %s)", title, cid)
                return cid
            logger.warning("Yoto save_track_playlist failed (%d): %s", res.status_code, res.text)
        except Exception as e:
            logger.error("Exception saving track playlist: %s", e)
        return None

    def upload_display_icon(self, image_bytes: bytes, filename: str = "icon.png") -> Optional[str]:
        """Uploads a 16x16 PNG directly to Yoto Cloud and returns 'yoto:#<mediaId>'."""
        token = self.get_token()
        if not token:
            return None
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

    def resolve_display_icon_url(self, media_id: str) -> Optional[str]:
        """Resolves a Yoto 16x16 display icon reference ('yoto:#<id>' or '<id>') to its CDN URL."""
        clean_id = (media_id or "").replace("yoto:#", "").strip()
        if not clean_id:
            return None

        now = time.time()
        cache = getattr(self, "_icon_url_cache", None)
        cache_ts = float(getattr(self, "_icon_url_cache_ts", 0.0) or 0.0)

        if cache is None or (now - cache_ts) >= 600.0:
            token = self.get_token()
            if not token:
                return cache.get(clean_id) if isinstance(cache, dict) else None
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            new_cache: Dict[str, str] = {}
            for path in ("/media/displayIcons/user/me", "/media/displayIcons/user/yoto"):
                try:
                    res = requests.get(f"{self.API_URL}{path}", headers=headers, timeout=15)
                    if res.status_code == 200:
                        for icon in res.json().get("displayIcons", []):
                            if not isinstance(icon, dict):
                                continue
                            url = icon.get("url")
                            if not url:
                                continue
                            for key_field in ("mediaId", "displayIconId"):
                                val = icon.get(key_field)
                                if val:
                                    new_cache[str(val)] = url
                except Exception as e:
                    logger.debug("Display icon list notice (%s): %s", path, e)
            if new_cache:
                self._icon_url_cache = new_cache
                self._icon_url_cache_ts = now
                cache = new_cache
            elif isinstance(cache, dict):
                self._icon_url_cache_ts = now

        return cache.get(clean_id) if isinstance(cache, dict) else None
