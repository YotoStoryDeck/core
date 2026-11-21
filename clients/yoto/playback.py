"""
Yoto Play Cloud playback, volume, and transport control mixin.
"""
from typing import Optional
import requests
from core.config import logger


class YotoPlaybackMixin:
    def set_volume(self, device_id: str, volume: int) -> bool:
        """Sets playback volume level (0-100) on a target Yoto player via Yoto Cloud API."""
        token = self.get_token()
        if not token:
            return False

        vol_val = max(0, min(100, int(volume)))
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
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
        if not token or action not in ("pause", "resume", "stop"):
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

    def start_playback(self, device_id: str, card_id: str, chapter: int = 1,
                       chapter_key: Optional[str] = None, track_key: Optional[str] = None) -> bool:
        """Triggers playback of a card on a target Yoto player via Yoto Cloud API."""
        token = self.get_token()
        if not token:
            return False

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = f"{self.API_URL}/device-v2/{device_id}/command/card/start"
        default_key = f"{max(1, int(chapter)):02d}"
        ck = chapter_key or default_key
        tk = track_key or ck
        payload = {
            "uri": f"https://yoto.io/{card_id}",
            "chapterKey": ck,
            "trackKey": tk
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
