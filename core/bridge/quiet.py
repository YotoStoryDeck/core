"""
Track cuts on a pause, where a cut is not at a chapter boundary.
Ported from yoto-audiobookshelf-bridge to support seamless chapter transitions.
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional, Dict, List, Tuple

WINDOW = 20.0              # seconds either side of a planned cut
GOOD_PAUSE = 0.5           # a pause at least this long beats a shorter one nearer the planned time

Snap = Callable[[float], float]


class QuietSpots:
    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "quiet.json"
        self.data: Dict[str, dict] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self.data = {}

    def snapper(self, item_id: str) -> Optional[Snap]:
        spots = (self.data.get(item_id) or {}).get("quiet") or []
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
        done = (self.data.get(item_id) or {}).get("scanned") or []
        return sorted({round(t, 1) for t in cuts
                       if not any(a <= t - WINDOW + 0.5 and t + WINDOW - 0.5 <= b for a, b in done)})

    def add(self, item_id: str, window: Tuple[float, float], spots: List[Tuple[float, float]]):
        d = self.data.setdefault(item_id, {"scanned": [], "quiet": []})
        d["scanned"].append([round(window[0], 2), round(window[1], 2)])
        known = {(round(a, 2), round(b, 2)) for a, b in d["quiet"]}
        d["quiet"] += [[round(a, 2), round(b, 2)] for a, b in spots if (round(a, 2), round(b, 2)) not in known]
        d["quiet"].sort()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".quiet")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)


def cut(snap: Optional[Snap], t: float, lo: float, hi: float) -> float:
    """Planned cut t, moved to a pause by snap if it stays clear of the neighbouring cuts lo and hi."""
    if snap is None:
        return t
    v = snap(t)
    return v if lo + 1 < v < hi - 1 else t
