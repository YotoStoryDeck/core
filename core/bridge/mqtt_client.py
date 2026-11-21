"""
Embedded Yoto MQTT Telemetry & Control Client for StoryDeck Core.
Maintains persistent subscriptions for EventPatch, StatusPatch, and PresenceEvent
messages in standalone/direct mode and dispatches remote MQTT player commands.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import clients

logger = logging.getLogger("storydeck.bridge.mqtt")

_HARDWARE_VOLUME_MAX = 16
# Matches yoto_api.const.VOLUME_MAPPING_INVERTED (steps 0..16 -> 0..100%)
_VOLUME_STEP_TO_PCT = (0, 7, 13, 19, 25, 32, 38, 44, 50, 57, 63, 69, 75, 82, 88, 94, 100)


def _hw_volume_to_pct(raw: Any) -> Optional[int]:
    """Converts Yoto raw 0-16 hardware volume/limit step into 0-100%, clamping >16 as percentage."""
    if raw is None or raw == "":
        return None
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        return None
    if val < 0:
        return 0
    if val <= _HARDWARE_VOLUME_MAX:
        return _VOLUME_STEP_TO_PCT[val]
    return min(100, val)


def _create_event_loop() -> asyncio.AbstractEventLoop:
    """Creates an asyncio event loop supporting add_reader/add_writer (SelectorEventLoop on Windows)."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


class YotoMqttBridge:
    """
    Thread-safe wrapper around yoto_api.mqtt.client.YotoMqttClient running on a
    dedicated daemon asyncio event loop for Flask worker compatibility.
    """

    def __init__(self, uri_format: str = "https://yoto.io/{card_id}"):
        self._lock = threading.Lock()
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._event_listeners: List[Callable[[str, Dict[str, Any]], None]] = []
        self._presence_listeners: List[Callable[[str, bool], None]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._client: Any = None
        self._device_ids: List[str] = []
        self._uri_format = uri_format

    @property
    def is_connected(self) -> bool:
        return bool(self._client and getattr(self._client, "is_connected", False))

    @property
    def device_ids(self) -> List[str]:
        with self._lock:
            return list(self._device_ids)

    def get_device_states(self) -> Dict[str, Dict[str, Any]]:
        """Returns a thread-safe snapshot of latest merged MQTT telemetry per player."""
        with self._lock:
            return {k: dict(v) for k, v in self._devices.items()}

    def get_device_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Returns merged MQTT state for a single Yoto player, or None if unseen."""
        with self._lock:
            st = self._devices.get(device_id)
            return dict(st) if st is not None else None

    def get_status_summary(self) -> Dict[str, Any]:
        """Returns diagnostic summary of the embedded MQTT worker and tracked players."""
        with self._lock:
            return {
                "connected": self.is_connected,
                "device_ids": list(self._device_ids),
                "tracked_devices": len(self._devices),
                "running": bool(self._thread and self._thread.is_alive()),
            }

    def add_event_listener(self, cb: Callable[[str, Dict[str, Any]], None]):
        """Registers a callback invoked on merged EventPatch / StatusPatch updates."""
        with self._lock:
            if cb not in self._event_listeners:
                self._event_listeners.append(cb)

    def add_presence_listener(self, cb: Callable[[str, bool], None]):
        """Registers a callback invoked when a player's online presence changes."""
        with self._lock:
            if cb not in self._presence_listeners:
                self._presence_listeners.append(cb)

    def _notify_presence(self, player_id: str, is_online: bool):
        with self._lock:
            listeners = list(self._presence_listeners)
        for cb in listeners:
            try:
                cb(player_id, is_online)
            except Exception as e:
                logger.debug("MQTT presence listener error for %s: %s", player_id, e)

    def _notify_event(self, player_id: str, merged_state: Dict[str, Any]):
        with self._lock:
            listeners = list(self._event_listeners)
        for cb in listeners:
            try:
                cb(player_id, dict(merged_state))
            except Exception as e:
                logger.debug("MQTT event listener error for %s: %s", player_id, e)

    def handle_message(self, msg: Any):
        """
        Ingests PresenceEvent, EventPatch, and StatusPatch messages from YotoMqttClient
        (or duck-typed test fixtures) and updates merged player state.
        """
        player_id = getattr(msg, "player_id", None)
        if not player_id:
            return

        cls_name = type(msg).__name__
        fields = getattr(msg, "fields", None)
        if fields is None:
            fields = {}

        def _val(v: Any) -> Any:
            return getattr(v, "value", v)

        if cls_name == "PresenceEvent" or (hasattr(msg, "is_online") and not hasattr(msg, "fields")):
            is_online = bool(getattr(msg, "is_online", False))
            with self._lock:
                st = self._devices.setdefault(player_id, {})
                st["online"] = is_online
                st["at"] = time.time()
            self._notify_presence(player_id, is_online)
            return

        is_event_patch = cls_name == "EventPatch" or (
            isinstance(fields, dict) and ("card_id" in fields or "playback_status" in fields)
        )
        if is_event_patch:
            raw_vol = _val(fields.get("volume"))
            raw_vmax = _val(fields.get("volume_max"))
            raw_vmax_int = None
            if raw_vmax is not None and raw_vmax != "":
                try:
                    rv = int(float(raw_vmax))
                    if 0 <= rv <= _HARDWARE_VOLUME_MAX:
                        raw_vmax_int = rv
                except (TypeError, ValueError):
                    pass

            raw_ev = {
                "cardId": _val(fields.get("card_id")),
                "position": _val(fields.get("position")),
                "trackLength": _val(fields.get("track_length")),
                "playbackStatus": _val(fields.get("playback_status")),
                "source": _val(fields.get("source")),
                "streaming": _val(fields.get("streaming")),
                "trackKey": _val(fields.get("track_key")),
                "chapterKey": _val(fields.get("chapter_key")),
                "chapterTitle": _val(fields.get("chapter_title")),
                "trackTitle": _val(fields.get("track_title")),
                "volume": _hw_volume_to_pct(raw_vol),
                "volume_max": _hw_volume_to_pct(raw_vmax),
                "volume_max_raw": raw_vmax_int,
            }
            ev = {k: v for k, v in raw_ev.items() if v is not None}

            if raw_vmax_int is not None and self._client and hasattr(self._client, "set_volume_max"):
                try:
                    self._client.set_volume_max(player_id, raw_vmax_int)
                except Exception as e:
                    logger.debug("Unable to propagate set_volume_max for %s: %s", player_id, e)

            with self._lock:
                merged = self._devices.setdefault(player_id, {})
                merged["online"] = True
                if ev.get("cardId") in ("none", ""):
                    for k in ("cardId", "position", "trackLength", "trackKey", "chapterKey", "chapterTitle", "trackTitle"):
                        merged.pop(k, None)
                    ev = {k: v for k, v in ev.items() if k != "cardId"}
                    merged["playbackStatus"] = ev.get("playbackStatus") or "stopped"
                merged.update(ev)
                merged["at"] = time.time()
                merged_copy = dict(merged)

            self._notify_presence(player_id, True)
            self._notify_event(player_id, merged_copy)
            return

        is_status_patch = cls_name == "StatusPatch" or (
            isinstance(fields, dict)
            and any(k in fields for k in ("user_volume_percentage", "system_volume_percentage", "day_mode", "battery_level_percentage"))
        )
        if is_status_patch:
            raw_ev = {
                "user_volume_percentage": fields.get("user_volume_percentage"),
                "system_volume_percentage": fields.get("system_volume_percentage"),
                "day_mode": fields.get("day_mode"),
                "battery_level_percentage": fields.get("battery_level_percentage"),
                "charging": fields.get("charging") if fields.get("charging") is not None else fields.get("is_charging"),
            }
            ev = {k: v for k, v in raw_ev.items() if v is not None}
            if ev.get("user_volume_percentage") is not None:
                ev["volume"] = ev["user_volume_percentage"]

            with self._lock:
                merged = self._devices.setdefault(player_id, {})
                merged["online"] = True
                merged.update(ev)
                merged["at"] = time.time()
                merged_copy = dict(merged)

            self._notify_presence(player_id, True)
            self._notify_event(player_id, merged_copy)

    def start(self) -> bool:
        """Starts the background MQTT connection thread if not already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="YotoMqttBridge", daemon=True)
            self._thread.start()
            return True

    def stop(self):
        """Stops the background MQTT client and closes its event loop."""
        self._stop_event.set()
        if self._client and self._loop and self._loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop)
                fut.result(timeout=3)
            except Exception as e:
                logger.debug("MQTT disconnect notice: %s", e)

    def _run_loop(self):
        loop = _create_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._maintain_connection())
        except Exception as e:
            logger.error("MQTT background loop exited with error: %s", e)
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None

    async def _maintain_connection(self):
        try:
            from yoto_api.mqtt.client import YotoMqttClient
        except ImportError:
            logger.warning("yoto-api package not installed; embedded Yoto MQTT client disabled.")
            return

        loop = asyncio.get_running_loop()
        backoff = 10

        async def _async_token_getter() -> str:
            if not clients.yoto_client:
                raise RuntimeError("Yoto client is not initialized")
            tok = await loop.run_in_executor(None, clients.yoto_client.get_token)
            if not tok:
                raise RuntimeError("No valid Yoto access token")
            return tok

        while not self._stop_event.is_set():
            try:
                yc = clients.yoto_client
                if not yc or not yc.client_id or not yc.refresh_token:
                    await asyncio.sleep(15)
                    continue

                devices = await loop.run_in_executor(None, yc.get_devices)
                device_ids = [d.get("deviceId") or d.get("id") for d in (devices or []) if d.get("deviceId") or d.get("id")]
                if not device_ids:
                    await asyncio.sleep(30)
                    continue

                with self._lock:
                    self._device_ids = device_ids

                client = YotoMqttClient()
                self._client = client
                await client.connect(None, device_ids, self.handle_message, token_getter=_async_token_getter)
                logger.info("Embedded Yoto MQTT connected for %d player(s).", len(device_ids))
                backoff = 10

                while not self._stop_event.is_set() and getattr(client, "is_connected", False):
                    await asyncio.sleep(5)

                if getattr(client, "is_connected", False):
                    await client.disconnect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Embedded Yoto MQTT connection error (retrying in %ds): %s", backoff, e)
            finally:
                if self._client:
                    try:
                        if getattr(self._client, "is_connected", False):
                            await self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None

            if not self._stop_event.is_set():
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)

    def _dispatch_coro(self, coro: Any, timeout: float = 5.0) -> bool:
        """Schedules an MQTT coroutine on the background event loop synchronously."""
        if not self.is_connected or not self._loop or not self._loop.is_running():
            return False
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
            fut.result(timeout=timeout)
            return True
        except Exception as e:
            logger.warning("MQTT command dispatch error: %s", e)
            return False

    def play(self, device_id: str, card_id: str, seconds_in: Optional[int] = None,
             track: int = 1, chapter_key: Optional[str] = None, track_key: Optional[str] = None) -> bool:
        """Commands a Yoto player via MQTT to start or seek playback on a card/playlist."""
        if not self.is_connected or not self._client:
            return False
        chap_k = chapter_key if chapter_key else f"{max(1, int(track)):02d}"
        trk_k = track_key if track_key else chap_k
        payload: Dict[str, Any] = {
            "uri": self._uri_format.format(card_id=card_id),
            "chapterKey": chap_k,
            "trackKey": trk_k,
        }
        if seconds_in is not None:
            payload["secondsIn"] = max(0, int(seconds_in))
        return self._dispatch_coro(
            self._client._publish(f"device/{device_id}/command/card/start", json.dumps(payload))
        )

    def pause(self, device_id: str) -> bool:
        """Sends an MQTT pause command to the target player."""
        if not self.is_connected or not self._client:
            return False
        return self._dispatch_coro(self._client.card_pause(device_id))

    def resume(self, device_id: str) -> bool:
        """Sends an MQTT resume command to the target player."""
        if not self.is_connected or not self._client:
            return False
        return self._dispatch_coro(self._client.card_resume(device_id))

    def stop_playback(self, device_id: str) -> bool:
        """Sends an MQTT stop command to the target player."""
        if not self.is_connected or not self._client:
            return False
        return self._dispatch_coro(self._client.card_stop(device_id))

    def set_volume(self, device_id: str, volume: int) -> bool:
        """Sets player volume (0-100) over MQTT via yoto_api volume mapping or command/volume/set."""
        if not self.is_connected or not self._client:
            return False
        vol = max(0, min(100, int(volume)))
        if hasattr(self._client, "set_volume"):
            return self._dispatch_coro(self._client.set_volume(device_id, vol))
        return self._dispatch_coro(
            self._client._publish(f"device/{device_id}/command/volume/set", json.dumps({"volume": vol}))
        )


_mqtt_bridge: Optional[YotoMqttBridge] = None


def get_mqtt_bridge() -> YotoMqttBridge:
    """Returns the global singleton YotoMqttBridge instance."""
    global _mqtt_bridge
    if _mqtt_bridge is None:
        _mqtt_bridge = YotoMqttBridge()
    return _mqtt_bridge
