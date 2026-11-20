"""
Constant-bitrate MP3 streaming engine with HTTP 206 Range request support.
Converts any source Audiobookshelf audio files into seamless constant-bitrate MP3 on the fly.
"""
from __future__ import annotations
import subprocess
import logging
from dataclasses import dataclass
from typing import List, Generator, Optional, Tuple

logger = logging.getLogger("storydeck.streamer")
CHUNK_SIZE = 16 * 1024


class SourceError(Exception):
    """Raised when audio source cannot be read by ffmpeg."""
    pass


@dataclass
class AudioTrackSource:
    url: str
    start: float      # offset within the book, seconds
    duration: float


class AudioStreamer:
    def __init__(self, bitrate_kbps: int = 64, channels: int = 1, sample_rate: int = 44100, ffmpeg_bin: str = "ffmpeg"):
        self.bitrate = bitrate_kbps
        self.channels = channels
        self.sample_rate = sample_rate
        self.ffmpeg = ffmpeg_bin
        self.byterate = bitrate_kbps * 1000 // 8  # e.g., 64000 // 8 = 8000 bytes/sec

    def bytes_to_seconds(self, byte_offset: int, speed: float = 1.0) -> float:
        """Converts a byte offset to book playback seconds."""
        effective_rate = self.byterate / max(0.1, speed)
        return byte_offset / effective_rate

    def seconds_to_bytes(self, seconds: float, speed: float = 1.0) -> int:
        """Converts book seconds to stream byte count."""
        effective_rate = self.byterate / max(0.1, speed)
        return int(round(seconds * effective_rate))

    def _ffmpeg_output_args(self) -> List[str]:
        return [
            "-vn",
            "-ac", str(self.channels),
            "-ar", str(self.sample_rate),
            "-c:a", "libmp3lame",
            "-b:a", f"{self.bitrate}k",
            "-write_xing", "0",
            "-id3v2_version", "0",
            "-map_metadata", "-1",
            "-f", "mp3",
            "pipe:1"
        ]

    def stream_segment(self, sources: List[AudioTrackSource], start_sec: float, end_sec: float,
                       auth_header: str = "", speed: float = 1.0) -> Generator[bytes, None, None]:
        """
        Yields constant-bitrate MP3 audio chunks covering book seconds [start_sec, end_sec) at specified speed.
        """
        for t in sources:
            t_end = t.start + t.duration
            if t_end <= start_sec or t.start >= end_sec:
                continue

            seek = max(0.0, start_sec - t.start)
            seg_len = min(t_end, end_sec) - max(t.start, start_sec)

            args = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
            if t.url.startswith("http"):
                if auth_header:
                    args += ["-headers", f"Authorization: {auth_header}\r\n"]
                args += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]

            if seek > 0.05:
                args += ["-ss", f"{seek:.3f}"]

            args += ["-i", t.url, "-t", f"{(seg_len / max(0.1, speed)):.3f}"]

            if abs(speed - 1.0) > 0.001:
                args += ["-af", f"atempo={speed:g}"]

            args += self._ffmpeg_output_args()

            proc = None
            try:
                proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                while True:
                    chunk = proc.stdout.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
                proc.wait()
                if proc.returncode != 0:
                    err = proc.stderr.read().decode(errors="replace")[-400:]
                    logger.warning("ffmpeg exited %s on %s: %s", proc.returncode, t.url, err)
            finally:
                if proc and proc.poll() is None:
                    try:
                        proc.kill()
                        proc.wait()
                    except Exception as e:
                        logger.debug("ffmpeg cleanup kill notice on %s: %s", t.url, e)

    def detect_quiet_spots(self, sources: List[AudioTrackSource], start_sec: float, end_sec: float,
                           auth_header: str = "", noise_db: int = -35, min_len: float = 0.25,
                           timeout: float = 60.0) -> List[Tuple[float, float]]:
        """Finds quiet pauses (start, end in book time) within [start_sec, end_sec) using ffmpeg silencedetect."""
        spots: List[Tuple[float, float]] = []
        for t in sources:
            t_end = t.start + t.duration
            if t_end <= start_sec or t.start >= end_sec:
                continue

            seek = max(0.0, start_sec - t.start)
            seg_len = min(t_end, end_sec) - max(t.start, start_sec)

            args = [self.ffmpeg, "-hide_banner", "-nostdin", "-nostats"]
            if t.url.startswith("http") and auth_header:
                args += ["-headers", f"Authorization: {auth_header}\r\n"]
            if seek > 0.05:
                args += ["-ss", f"{seek:.3f}"]
            args += [
                "-i", t.url,
                "-t", f"{seg_len:.3f}",
                "-vn",
                "-af", f"silencedetect=noise={noise_db}dB:d={min_len:g}",
                "-f", "null", "-"
            ]

            res = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)
            err = (res.stderr or b"").decode(errors="replace")
            if res.returncode != 0:
                raise SourceError(f"could not read the audio around {start_sec:.0f}s: {' '.join(err.split())[-120:]}")

            base = t.start + seek
            s0: Optional[float] = None
            for line in err.splitlines():
                if "silence_start:" in line:
                    s0 = float(line.rsplit("silence_start:", 1)[1].split()[0])
                elif "silence_end:" in line and s0 is not None:
                    e0 = float(line.rsplit("silence_end:", 1)[1].split()[0])
                    spots.append((base + max(0.0, s0), base + e0))
                    s0 = None
            if s0 is not None:
                spots.append((base + max(0.0, s0), base + seg_len))

        return spots
