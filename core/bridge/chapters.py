"""
Chapters as Yoto tracks.
Segments an Audiobookshelf book's chapters and tracks into Yoto playlist tracks (max 99 tracks).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional

from .quiet import Snap, cut

MAX_TRACKS = 99
DEFAULT_PART_SECONDS = 1800  # 30 minutes


@dataclass
class Segment:
    item_id: str
    book: str              # book title
    start: float           # start time within book in seconds
    end: float             # end time within book in seconds
    number: int            # chapter (or part) number within the book, 1-based
    title: str
    book_duration: float
    chaptered: bool = True # False: a fixed-length part of a book without chapters


def chapter_spans(chapters: List[Dict[str, Any]], duration: float, part_seconds: int = DEFAULT_PART_SECONDS,
                  snap: Optional[Snap] = None) -> List[Tuple[float, float, str]]:
    """
    (start, end, title) per track: each chapter, with chapters longer than two parts split evenly
    into parts of at most part_seconds. Books with fewer than 2 chapters get fixed-length parts.
    """
    out = []
    for start, end, title in _raw_spans(chapters, duration, part_seconds, snap):
        n = 1 if end - start <= 2 * part_seconds else -(-(end - start) // part_seconds)
        n = int(n)
        step = (end - start) / n
        s = start
        for i in range(n):
            e = end if i == n - 1 else cut(snap, start + (i + 1) * step, s, end)
            part_title = f"{title} ({i + 1}/{n})" if n > 1 else title
            out.append((s, e, part_title))
            s = e
    return out


def _raw_spans(chapters: List[Dict[str, Any]], duration: float, part_seconds: int,
               snap: Optional[Snap] = None) -> List[Tuple[float, float, str]]:
    if len(chapters) >= 2:
        spans = []
        for i, c in enumerate(chapters):
            start = float(c.get("start", 0))
            nxt = float(chapters[i + 1].get("start", duration)) if i + 1 < len(chapters) else duration
            end = float(c["end"]) if c.get("end") else nxt
            if end - start > 0.5:
                spans.append((start, end, c.get("title") or f"Chapter {i + 1}"))
        if spans:
            return _fill_gaps(spans, duration, part_seconds, snap)

    out = []
    t = 0.0
    n = 1
    while t < duration - 0.5:
        e = min(duration, n * part_seconds)
        e = e if e >= duration else cut(snap, e, t, duration)
        out.append((t, e, f"Part {n}"))
        t = e
        n += 1
    return out or [(0.0, max(0.1, duration), "Part 1")]


def _fill_gaps(spans: List[Tuple[float, float, str]], duration: float,
               part_seconds: int, snap: Optional[Snap] = None) -> List[Tuple[float, float, str]]:
    """Cover audio that no chapter covers with parts of part_seconds."""
    out = []
    t = 0.0
    n = 1
    for start, end, title in spans + [(duration, duration, "")]:
        gap = t
        k = 1
        while start - t > 0.5:
            e = min(start, gap + k * part_seconds)
            e = e if e >= start else cut(snap, e, t, start)
            out.append((t, e, f"Part {n}"))
            t = e
            n += 1
            k += 1
        if title:
            out.append((start, end, title))
        t = max(t, end)
    return out
