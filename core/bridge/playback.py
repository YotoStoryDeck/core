"""
Bi-Directional Audiobookshelf Stream Progress Manager for StoryDeck Core.
Tracks active /s/audio/<slot_id>/<track_idx> streaming sessions per player,
estimates real-time book positions from delivered byte ranges, wall-clock play time,
and embedded MQTT telemetry, and syncs progress back to Audiobookshelf.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import clients
import database
from .mqtt_client import get_mqtt_bridge

logger = logging.getLogger("storydeck.bridge.playback")

DEFAULT_SYNC_INTERVAL = 15.0
DEFAULT_END_GRACE_SECONDS = 15.0
STARTUP_LAG_SECONDS = 3.0
DEFAULT_PLAYER_BUFFER_SECONDS = 8.0


@dataclass
class PlaybackSession:
    """Active HTTP audio streaming session correlated with a Yoto player and ABS book."""
    slot_id: str
    abs_item_id: str
    title: str
    owner_profile_id: str
    device_id: str
    abs_token: Optional[str]
    abs_session_id: str
    own_place: bool
    track_idx: int
    track_start: float
    track_end: float
    book_duration: float
    base: float
    speed: float = 1.0
    byterate: float = 8000.0
    bytes_sent: int = 0
    open_streams: int = 0
    started_at: float = field(default_factory=time.monotonic)
    ended_at: Optional[float] = None
    last_pos: float = 0.0
    last_sync_at: float = field(default_factory=time.monotonic)
    last_write_wall: float = field(default_factory=time.time)
    paused_at: Optional[float] = None
    paused_total: float = 0.0
    mqtt_event: Dict[str, Any] = field(default_factory=dict)
    mqtt_event_at: Optional[float] = None
    yoto_card_id: str = ""


class PlaybackManager:
    """Tracks live stream sessions and pushes bi-directional progress updates to ABS."""

    def __init__(self, sync_interval: float = DEFAULT_SYNC_INTERVAL,
                 end_grace_seconds: float = DEFAULT_END_GRACE_SECONDS,
                 player_buffer_seconds: float = DEFAULT_PLAYER_BUFFER_SECONDS):
        self.sync_interval = sync_interval
        self.end_grace_seconds = end_grace_seconds
        self.player_buffer_seconds = player_buffer_seconds
        self._lock = threading.Lock()
        self._sessions: Dict[str, PlaybackSession] = {}
        self._expected: Dict[str, Tuple[str, float]] = {}
        self._stop_event = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None

    def expect(self, device_id: str, card_id: str):
        """Records an impending player playback command so incoming streams bind to that player."""
        if device_id and card_id:
            with self._lock:
                self._expected[card_id] = (device_id, time.monotonic())

    def _resolve_device_id(self, slot: Dict[str, Any], explicit_device_id: str = "") -> str:
        if explicit_device_id and explicit_device_id.strip():
            return explicit_device_id.strip()

        yoto_cid = (slot.get("yoto_card_id") or "").strip()
        if yoto_cid:
            with self._lock:
                exp = self._expected.get(yoto_cid)
                if exp and (time.monotonic() - exp[1]) < 60.0:
                    self._expected.pop(yoto_cid, None)
                    return exp[0]

            try:
                mqtt_states = get_mqtt_bridge().get_device_states()
                for did, ev in mqtt_states.items():
                    if ev.get("cardId") == yoto_cid and (time.time() - float(ev.get("at") or 0)) < 60.0:
                        return did
            except Exception:
                pass

        owner_prof = (slot.get("owner_profile_id") or "").strip()
        if owner_prof:
            try:
                prof = database.get_profile_by_id(owner_prof)
                if prof and prof.get("default_player_id"):
                    return str(prof["default_player_id"])
            except Exception:
                pass

        return ""

    def open_stream(self, slot: Dict[str, Any], track: Dict[str, Any],
                    byte_start: int = 0, speed: float = 1.0,
                    byterate: float = 8000.0, device_id: str = "") -> PlaybackSession:
        """
        Opens or re-anchors a PlaybackSession when a Yoto player fetches /s/audio/<slot_id>/<track_idx>.
        """
        slot_id = slot["slot_id"]
        abs_item_id = slot["abs_item_id"]
        track_idx = int(track.get("track_idx") or 1)
        track_start = float(track.get("start_time") or 0.0)
        track_end = float(track.get("end_time") or 0.0)
        book_duration = max(float(slot.get("total_duration") or 0.0), track_end)
        eff_speed = max(0.1, float(speed or 1.0))
        eff_byterate = float(byterate or 8000.0)
        rate = eff_byterate / eff_speed
        seek_sec = max(0.0, float(byte_start or 0) / rate)
        req_start = track_start + seek_sec

        with self._lock:
            existing = self._sessions.get(slot_id)
            if existing and existing.abs_item_id == abs_item_id and existing.track_idx == track_idx and byte_start > 0:
                existing.open_streams += 1
                existing.ended_at = None
                if device_id and not existing.device_id:
                    existing.device_id = device_id
                return existing

        if existing and existing.abs_item_id == abs_item_id:
            try:
                self.sync_session(existing, force=True)
            except Exception as e:
                logger.debug("Pre-reanchor sync notice on %s: %s", slot_id, e)
            with self._lock:
                cur = self._sessions.get(slot_id)
                if cur is existing:
                    cur.track_idx = track_idx
                    cur.track_start = track_start
                    cur.track_end = track_end
                    cur.book_duration = book_duration
                    cur.base = req_start
                    cur.speed = eff_speed
                    cur.byterate = eff_byterate
                    cur.bytes_sent = 0
                    cur.started_at = time.monotonic()
                    cur.paused_at = None
                    cur.paused_total = 0.0
                    cur.open_streams += 1
                    cur.ended_at = None
                    cur.last_pos = req_start
                    cur.last_sync_at = time.monotonic()
                    cur.mqtt_event = {}
                    cur.mqtt_event_at = None
                    if device_id:
                        cur.device_id = device_id
                    return cur
        elif existing:
            self.finish_session(slot_id, "switched book")

        resolved_dev = self._resolve_device_id(slot, device_id)
        owner_profile_id = (slot.get("owner_profile_id") or "").strip()
        own_place = bool(slot.get("own_place"))

        abs_token: Optional[str] = None
        abs_session_id = ""
        if clients.abs_client and not own_place:
            abs_token = clients.abs_client.resolve_token_for_profile(
                owner_profile_id or None,
                resolved_dev or None
            )
            sess_data = clients.abs_client.start_playback_session(
                abs_item_id,
                resolved_dev or slot_id,
                device_name="Yoto",
                token=abs_token
            )
            if sess_data and sess_data.get("id"):
                abs_session_id = str(sess_data["id"])

        try:
            database.record_playback(abs_item_id, owner_profile_id or "default")
        except Exception as e:
            logger.debug("Playback history record notice for %s: %s", abs_item_id, e)

        now_m = time.monotonic()
        session = PlaybackSession(
            slot_id=slot_id,
            abs_item_id=abs_item_id,
            title=slot.get("title") or "Audiobook",
            owner_profile_id=owner_profile_id,
            device_id=resolved_dev,
            abs_token=abs_token,
            abs_session_id=abs_session_id,
            own_place=own_place,
            track_idx=track_idx,
            track_start=track_start,
            track_end=track_end,
            book_duration=book_duration,
            base=req_start,
            speed=eff_speed,
            byterate=eff_byterate,
            bytes_sent=0,
            open_streams=1,
            started_at=now_m,
            ended_at=None,
            last_pos=req_start,
            last_sync_at=now_m,
            last_write_wall=time.time(),
            yoto_card_id=(slot.get("yoto_card_id") or "").strip(),
        )
        with self._lock:
            self._sessions[slot_id] = session
        return session

    def record_bytes(self, session: PlaybackSession, num_bytes: int):
        """Tracks streamed MP3 byte delivery and periodically triggers ABS sync."""
        due = False
        with self._lock:
            session.bytes_sent += max(0, int(num_bytes))
            if (time.monotonic() - session.last_sync_at) >= self.sync_interval:
                due = True
        if due:
            try:
                self.sync_session(session)
            except Exception as e:
                logger.debug("Periodic stream byte sync notice on %s: %s", session.slot_id, e)

    def close_stream(self, session: PlaybackSession, force_sync: bool = True):
        """Marks an HTTP audio stream response closed and flushes progress to ABS."""
        with self._lock:
            session.open_streams = max(0, session.open_streams - 1)
            if session.open_streams == 0:
                session.ended_at = time.monotonic()
        if force_sync:
            try:
                self.sync_session(session, force=True)
            except Exception as e:
                logger.debug("Close stream sync notice on %s: %s", session.slot_id, e)

    def compute_position(self, session: PlaybackSession, now_mono: Optional[float] = None) -> float:
        """
        Computes current book position in seconds, bounded by delivered audio bytes
        and elapsed active playback time (excluding paused intervals).
        """
        now_t = now_mono if now_mono is not None else time.monotonic()
        rate = session.byterate / max(0.1, session.speed)
        delivered_book_sec = session.bytes_sent / rate
        played = now_t - session.started_at - session.paused_total
        if session.paused_at is not None:
            played -= (now_t - max(session.paused_at, session.started_at))

        cap = session.base + min(delivered_book_sec, max(0.0, played) * session.speed)
        if session.track_end > 0:
            cap = min(cap, session.track_end)
        if session.book_duration > 0:
            cap = min(cap, session.book_duration)

        ev = session.mqtt_event
        status = ev.get("playbackStatus")
        fresh = (
            session.mqtt_event_at is not None
            and ((now_t - session.mqtt_event_at) < 3 * self.sync_interval or status in ("paused", "stopped"))
        )
        if fresh and ev.get("position") is not None:
            p = float(ev["position"])
            if status == "playing" and session.mqtt_event_at is not None:
                p += max(0.0, now_t - session.mqtt_event_at)
            est = session.base + p * session.speed
            return round(max(session.base, min(est, cap)), 2)

        lag = STARTUP_LAG_SECONDS if status is not None else self.player_buffer_seconds
        pos = max(session.base, cap - lag * session.speed, min(session.last_pos, cap))
        return round(pos, 2)

    def _moved_elsewhere(self, session: PlaybackSession) -> bool:
        """Detects whether ABS progress was updated externally (e.g. phone app) since our last write."""
        if session.open_streams > 0 or session.own_place or not clients.abs_client:
            return False
        prog = clients.abs_client.get_media_progress(session.abs_item_id, token=session.abs_token) or {}
        if not prog:
            return False
        newer = (float(prog.get("lastUpdate") or 0.0) / 1000.0) > (session.last_write_wall + 2.0)
        moved = abs(float(prog.get("currentTime") or 0.0) - session.last_pos) > 2.0
        return bool(newer and moved)

    def sync_session(self, session: PlaybackSession, force: bool = False) -> bool:
        """Pushes current estimated book position and listened delta to Audiobookshelf."""
        if session.own_place or not clients.abs_client:
            return False

        pos = self.compute_position(session)
        if not force and abs(pos - session.last_pos) < 1.0:
            return False

        if self._moved_elsewhere(session):
            logger.info("%s moved on another client; dropping Yoto sync session without overwriting", session.title)
            with self._lock:
                self._sessions.pop(session.slot_id, None)
            return False

        now_t = time.monotonic()
        listened = max(0.0, min((pos - session.last_pos) / max(0.1, session.speed), max(0.0, now_t - session.last_sync_at)))

        ok = False
        status = 0
        if session.abs_session_id:
            ok, status = clients.abs_client.sync_playback_session(
                session.abs_session_id,
                pos,
                listened,
                session.book_duration,
                token=session.abs_token
            )
        if not session.abs_session_id or status == 404:
            ok = clients.abs_client.patch_media_progress(
                session.abs_item_id,
                pos,
                session.book_duration,
                token=session.abs_token
            )

        if ok:
            with self._lock:
                session.last_pos = pos
                session.last_sync_at = now_t
                session.last_write_wall = time.time()
            try:
                database.record_playback(session.abs_item_id, session.owner_profile_id or "default")
            except Exception:
                pass
        return bool(ok)

    def finish_session(self, slot_id: str, reason: str = "stream closed") -> bool:
        """Closes a finished/idle stream session in Audiobookshelf and removes it from active memory."""
        with self._lock:
            session = self._sessions.pop(slot_id, None)
        if not session:
            return False
        if session.own_place or not clients.abs_client:
            return True
        if self._moved_elsewhere(session):
            return False

        pos = self.compute_position(session)
        now_t = time.monotonic()
        listened = max(0.0, min((pos - session.last_pos) / max(0.1, session.speed), max(0.0, now_t - session.last_sync_at)))

        closed = False
        if session.abs_session_id:
            closed = clients.abs_client.close_playback_session(
                session.abs_session_id,
                pos,
                listened,
                session.book_duration,
                token=session.abs_token
            )
        if not closed:
            clients.abs_client.patch_media_progress(
                session.abs_item_id,
                pos,
                session.book_duration,
                token=session.abs_token
            )

        if session.book_duration > 0 and pos >= session.book_duration - min(30.0, 0.02 * session.book_duration):
            clients.abs_client.patch_media_progress(
                session.abs_item_id,
                session.book_duration,
                session.book_duration,
                is_finished=True,
                token=session.abs_token
            )
        logger.debug("Finished ABS playback session for %s at %.1fs (%s)", session.title, pos, reason)
        return True

    def on_mqtt_event(self, device_id: str, ev: Dict[str, Any]):
        """Correlates embedded MQTT EventPatch/StatusPatch updates with active streaming sessions."""
        card_id = ev.get("cardId")
        matched: List[PlaybackSession] = []
        now_t = time.monotonic()
        status = str(ev.get("playbackStatus") or "").lower()

        with self._lock:
            for sess in self._sessions.values():
                if (card_id and sess.yoto_card_id and card_id == sess.yoto_card_id) or sess.device_id == device_id:
                    if not sess.device_id:
                        sess.device_id = device_id
                    if status in ("paused", "stopped") and sess.paused_at is None:
                        sess.paused_at = now_t
                    elif status == "playing" and sess.paused_at is not None:
                        sess.paused_total += max(0.0, now_t - max(sess.paused_at, sess.started_at))
                        sess.paused_at = None
                    sess.mqtt_event = dict(ev)
                    sess.mqtt_event_at = now_t
                    matched.append(sess)

        for sess in matched:
            if status in ("paused", "stopped"):
                try:
                    self.sync_session(sess, force=True)
                except Exception as e:
                    logger.debug("MQTT pause/stop sync notice on %s: %s", sess.slot_id, e)
                if status == "stopped" and sess.open_streams == 0 and not card_id:
                    self.finish_session(sess.slot_id, "player stopped")

    def tick(self):
        """Periodic maintenance: finalizes expired buffered streams and syncs active sessions."""
        with self._lock:
            active_list = list(self._sessions.values())

        now_t = time.monotonic()
        for sess in active_list:
            try:
                if sess.open_streams == 0 and sess.ended_at is not None:
                    idle = now_t - sess.ended_at
                    status = str(sess.mqtt_event.get("playbackStatus") or "").lower()
                    rate = sess.byterate / max(0.1, sess.speed)
                    played = now_t - sess.started_at - sess.paused_total
                    if sess.paused_at is not None:
                        played -= (now_t - max(sess.paused_at, sess.started_at))
                    buffered = (sess.bytes_sent / rate) - played
                    if idle > self.end_grace_seconds and (status == "stopped" or (buffered < -self.end_grace_seconds and status != "playing")):
                        self.finish_session(sess.slot_id, "player stopped" if status == "stopped" else "stream closed")
                        continue
                self.sync_session(sess)
            except Exception as e:
                logger.debug("PlaybackManager tick notice for %s: %s", sess.slot_id, e)

    def start_sync_loop(self) -> bool:
        """Starts the periodic background ABS progress sync thread."""
        with self._lock:
            if self._sync_thread and self._sync_thread.is_alive():
                return False
            self._stop_event.clear()
            self._sync_thread = threading.Thread(target=self._loop, name="PlaybackProgressSync", daemon=True)
            self._sync_thread.start()
            return True

    def stop_sync_loop(self):
        """Signals the background ABS progress sync thread to stop."""
        self._stop_event.set()

    def _loop(self):
        while not self._stop_event.wait(self.sync_interval):
            try:
                self.tick()
            except Exception as e:
                logger.debug("PlaybackManager sync loop error: %s", e)

    def get_active_for_device(self, device_id: str) -> Optional[PlaybackSession]:
        """Returns the most recently active PlaybackSession for device_id, if any."""
        with self._lock:
            mine = [s for s in self._sessions.values() if s.device_id == device_id]
        if not mine:
            return None
        return max(mine, key=lambda s: s.started_at)

    def get_active_sessions_summary(self) -> List[Dict[str, Any]]:
        """Returns JSON-serializable summary of all active streaming sessions."""
        with self._lock:
            sessions = list(self._sessions.values())
        return [
            {
                "slot_id": s.slot_id,
                "abs_item_id": s.abs_item_id,
                "title": s.title,
                "device_id": s.device_id,
                "owner_profile_id": s.owner_profile_id,
                "track_idx": s.track_idx,
                "position": self.compute_position(s),
                "duration": s.book_duration,
                "speed": s.speed,
                "open_streams": s.open_streams,
                "own_place": s.own_place,
            }
            for s in sessions
        ]


_playback_manager: Optional[PlaybackManager] = None


def get_playback_manager() -> PlaybackManager:
    """Returns the global singleton PlaybackManager instance."""
    global _playback_manager
    if _playback_manager is None:
        _playback_manager = PlaybackManager()
    return _playback_manager
