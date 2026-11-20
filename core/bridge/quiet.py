"""
Track cuts on a pause, where a cut is not at a chapter boundary.
Ported from yoto-audiobookshelf-bridge to support seamless chapter transitions.
"""
from __future__ import annotations
import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional, Dict, List, Tuple, Any

logger = logging.getLogger("storydeck.bridge.quiet")

WINDOW = 20.0              # seconds either side of a planned cut
GOOD_PAUSE = 0.5           # a pause at least this long beats a shorter one nearer the planned time

Snap = Callable[[float], float]


class QuietSpots:
    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "quiet.json"
        self.data: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._active_scans: set[str] = set()
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self.data = {}

    def snapper(self, item_id: str) -> Optional[Snap]:
        with self._lock:
            spots = list((self.data.get(item_id) or {}).get("quiet") or [])
        if not spots:
            return None

        def snap(t: float) -> float:
            near = [(s, e) for s, e in spots if abs((s + e) / 2.0 - t) <= WINDOW]
            if not near:
                return t
            s, e = min(near, key=lambda p: (p[1] - p[0] < GOOD_PAUSE, abs((p[0] + p[1]) / 2.0 - t)))
            return round((s + e) / 2.0, 2)
        return snap

    def missing(self, item_id: str, cuts: List[float]) -> List[float]:
        """The cuts whose window has not been listened to yet."""
        with self._lock:
            done = list((self.data.get(item_id) or {}).get("scanned") or [])
        return sorted({round(t, 1) for t in cuts
                       if not any(a <= t - WINDOW + 0.5 and t + WINDOW - 0.5 <= b for a, b in done)})

    def add(self, item_id: str, window: Tuple[float, float], spots: List[Tuple[float, float]]):
        with self._lock:
            d = self.data.setdefault(item_id, {"scanned": [], "quiet": []})
            d["scanned"].append([round(window[0], 2), round(window[1], 2)])
            known = {(round(a, 2), round(b, 2)) for a, b in d["quiet"]}
            d["quiet"] += [[round(a, 2), round(b, 2)] for a, b in spots if (round(a, 2), round(b, 2)) not in known]
            d["quiet"].sort()

    def save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".quiet")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.data, f)
                os.replace(tmp, self.path)
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                except OSError:
                    pass
                raise

    def scan_windows(self, item_id: str, planned_cuts: List[float], sources: List[Any],
                     auth_header: str = "", streamer: Any = None,
                     budget: Optional[float] = 20.0, noise_db: int = -35,
                     min_len: float = 0.25) -> int:
        """
        Scans unscanned planned cut windows using ffmpeg silencedetect and persists results.
        Returns the count of newly scanned cut windows.
        """
        todo = self.missing(item_id, planned_cuts)
        if not todo or not sources:
            return 0

        if streamer is None:
            from .streamer import AudioStreamer
            streamer = AudioStreamer()

        end = float(sources[-1].start) + float(sources[-1].duration)
        t0 = time.monotonic()

        def _look(t: float) -> bool:
            if budget is not None and (time.monotonic() - t0) > budget:
                return False
            win_start = max(0.0, t - WINDOW)
            win_end = min(end, t + WINDOW)
            if win_end <= win_start:
                return False
            try:
                spots = streamer.detect_quiet_spots(
                    sources,
                    win_start,
                    win_end,
                    auth_header=auth_header,
                    noise_db=noise_db,
                    min_len=min_len
                )
            except Exception as e:
                logger.warning("Could not scan quiet spots near %.0fs of %s: %s", t, item_id, e or type(e).__name__)
                return False

            self.add(item_id, (t - WINDOW, t + WINDOW), spots)
            return True

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_look, todo))

        scanned = sum(1 for ok in results if ok)
        if scanned > 0:
            self.save()
            logger.info("Scanned quiet pauses near %d of %d cuts for %s in %.1fs",
                        scanned, len(todo), item_id, time.monotonic() - t0)
        return scanned

    def schedule_background_scan(self, item_id: str, planned_cuts: List[float], sources: List[Any],
                                 auth_header: str = "", budget: Optional[float] = 60.0,
                                 on_complete: Optional[Callable[[], None]] = None) -> bool:
        """Schedules an asynchronous background quiet-spot scan for unscanned cut windows."""
        todo = self.missing(item_id, planned_cuts)
        if not todo or not sources:
            return False

        with self._lock:
            if item_id in self._active_scans:
                return False
            self._active_scans.add(item_id)

        def _worker():
            scanned = 0
            try:
                scanned = self.scan_windows(
                    item_id,
                    planned_cuts,
                    sources,
                    auth_header=auth_header,
                    budget=budget
                )
            except Exception as e:
                logger.debug("Background quiet spot scan error for %s: %s", item_id, e)
            finally:
                with self._lock:
                    self._active_scans.discard(item_id)
            if scanned > 0 and on_complete:
                try:
                    on_complete()
                except Exception as e:
                    logger.debug("Quiet spot on_complete callback error for %s: %s", item_id, e)

        t = threading.Thread(target=_worker, name=f"QuietScan-{item_id}", daemon=True)
        t.start()
        return True


def cut(snap: Optional[Snap], t: float, lo: float, hi: float) -> float:
    """Planned cut t, moved to a pause by snap if it stays clear of the neighbouring cuts lo and hi."""
    if snap is None:
        return t
    v = snap(t)
    return v if lo + 1 < v < hi - 1 else t


_quiet_spots: Optional[QuietSpots] = None


def get_quiet_spots(data_dir: Optional[str] = None) -> QuietSpots:
    """Returns a QuietSpots instance for data_dir, or the global singleton backed by DB_PATH.parent."""
    if data_dir is not None:
        return QuietSpots(data_dir)
    global _quiet_spots
    if _quiet_spots is None:
        import database
        _quiet_spots = QuietSpots(str(database.DB_PATH.parent))
    return _quiet_spots
