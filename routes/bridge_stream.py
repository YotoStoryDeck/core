"""
StoryDeck Core Audio Streaming & Chapter Icon Blueprint (/s/*).
Serves constant-bitrate MP3 streams with HTTP 206 Range requests and 16x16 PNG icons for Yoto Players.
"""
from __future__ import annotations
import io
import re
import logging
from typing import List
from flask import Blueprint, request, Response, jsonify
import clients
from core.config import CUSTOM_ICONS_DIR
from core.version_service import get_installed_version
from core.bridge.manager import get_bridge_manager
from core.bridge.streamer import AudioStreamer, AudioTrackSource
from core.bridge.playback import get_playback_manager

logger = logging.getLogger("storydeck.routes.bridge_stream")
bridge_stream_bp = Blueprint("bridge_stream", __name__)


@bridge_stream_bp.route("/s/health", methods=["GET"])
def health_check():
    """Health check endpoint for reverse proxy, deploy scripts, and Uptime Kuma."""
    return jsonify({
        "status": "healthy",
        "service": "storydeck-core",
        "version": get_installed_version()
    }), 200


@bridge_stream_bp.route("/s/audio/<slot_id>/<int:track_idx>", methods=["GET"])
def stream_track_audio(slot_id: str, track_idx: int):
    """
    Streams a constant-bitrate MP3 chapter track with HTTP 206 Range request support.
    Compatible with Yoto Player dynamic stream chapters and standard media players.
    """
    mgr = get_bridge_manager()
    slot = mgr.get_slot(slot_id)
    if not slot:
        return Response("Slot not found", status=404)

    track = mgr.get_track(slot_id, track_idx)
    if not track:
        return Response("Track not found", status=404)

    start_sec = float(track["start_time"])
    end_sec = float(track["end_time"])
    duration = max(0.1, end_sec - start_sec)
    speed = float(slot.get("speed") or 1.0)

    streamer = AudioStreamer(bitrate_kbps=64, channels=1, sample_rate=44100)
    total_bytes = streamer.seconds_to_bytes(duration, speed)

    abs_item_id = slot.get("abs_item_id")
    if not abs_item_id or not clients.abs_client:
        return Response("Audiobookshelf item not available", status=503)

    try:
        item_data = clients.abs_client.get_item(abs_item_id)
    except Exception as e:
        logger.error("Failed to fetch ABS item for stream %s/%d: %s", slot_id, track_idx, e)
        return Response("Audio source unavailable", status=502)

    media = (item_data or {}).get("media", {})
    audio_files = media.get("audioFiles", [])
    if not audio_files:
        return Response("No audio files in book", status=404)

    sources: List[AudioTrackSource] = []
    c_offset = 0.0
    abs_token = getattr(clients.abs_client, "token", "") or getattr(clients.abs_client, "api_key", "") or ""
    abs_base = getattr(clients.abs_client, "base_url", "") or ""
    auth_hdr = f"Bearer {abs_token}" if abs_token else ""

    for af in audio_files:
        ino = af.get("ino") or af.get("id") or ""
        f_dur = float(af.get("duration") or 0.0)
        url = f"{abs_base}/api/items/{abs_item_id}/file/{ino}"
        sources.append(AudioTrackSource(url=url, start=c_offset, duration=f_dur))
        c_offset += f_dur

    range_header = request.headers.get("Range")
    byte_start = 0
    byte_end = total_bytes - 1

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            byte_start = int(m.group(1))
            if m.group(2):
                byte_end = min(total_bytes - 1, int(m.group(2)))

    if byte_start >= total_bytes:
        return Response(status=416, headers={"Content-Range": f"bytes */{total_bytes}"})

    content_length = byte_end - byte_start + 1
    seek_sec = streamer.bytes_to_seconds(byte_start, speed)
    req_start_sec = start_sec + seek_sec
    req_end_sec = min(end_sec, start_sec + streamer.bytes_to_seconds(byte_end + 1, speed))

    pb_mgr = get_playback_manager()
    pb_session = pb_mgr.open_stream(
        slot,
        track,
        byte_start=byte_start,
        speed=speed,
        byterate=streamer.byterate,
        device_id=request.args.get("device_id", "")
    )

    def generate_chunks():
        bytes_sent = 0
        try:
            for chunk in streamer.stream_segment(sources, req_start_sec, req_end_sec, auth_header=auth_hdr, speed=speed):
                remaining = content_length - bytes_sent
                if remaining <= 0:
                    break
                if len(chunk) > remaining:
                    out_chunk = chunk[:remaining]
                    yield out_chunk
                    bytes_sent += remaining
                    pb_mgr.record_bytes(pb_session, len(out_chunk))
                    break
                yield chunk
                bytes_sent += len(chunk)
                pb_mgr.record_bytes(pb_session, len(chunk))
        finally:
            pb_mgr.close_stream(pb_session, force_sync=True)

    status_code = 206 if range_header else 200
    headers = {
        "Content-Type": "audio/mpeg",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Cache-Control": "no-cache",
    }
    if range_header:
        headers["Content-Range"] = f"bytes {byte_start}-{byte_end}/{total_bytes}"

    return Response(generate_chunks(), status=status_code, headers=headers)


@bridge_stream_bp.route("/s/stream/<slot_id>", methods=["GET"])
def stream_slot_legacy(slot_id: str):
    """Legacy whole-book stream endpoint, forwarding to track 1."""
    return stream_track_audio(slot_id, 1)


@bridge_stream_bp.route("/s/icon/<slot_id>.png", methods=["GET"])
@bridge_stream_bp.route("/s/icon/<slot_id>/<int:track_idx>.png", methods=["GET"])
def serve_track_icon(slot_id: str, track_idx: int = 1):
    """Serves a local custom 16x16 pixel art PNG icon (or default orange disc) for Yoto Player display."""
    mgr = get_bridge_manager()
    slot = mgr.get_slot(slot_id)
    abs_item_id = slot.get("abs_item_id") if slot else None

    if abs_item_id:
        icon_idx = max(0, int(track_idx) - 1)
        local_icon = CUSTOM_ICONS_DIR / f"{abs_item_id}_{icon_idx}.png"
        if local_icon.is_file():
            try:
                return Response(local_icon.read_bytes(), mimetype="image/png")
            except Exception as e:
                logger.debug("Failed reading custom icon %s: %s", local_icon, e)

    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([1, 1, 14, 14], fill=(229, 83, 30, 255))
    draw.ellipse([6, 6, 9, 9], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")
