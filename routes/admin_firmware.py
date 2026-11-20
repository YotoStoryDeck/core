"""
Admin Firmware Repository, Remote OTA Deployment & Touch MicroSD Cache Controls (DLP-010 & DLP-020).
"""

import hashlib
import ipaddress
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, jsonify, request, send_file

import core.config as core_config
import database
from core.auth import (
    get_current_admin_user,
    get_current_device,
    get_effective_client_ip,
    is_trusted_lan_ip,
    require_admin,
)
from core.config import logger

admin_firmware_bp = Blueprint("admin_firmware", __name__)

_VERSION_RE = re.compile(r"^[vV]?[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
_ESP_IMAGE_HEADER_MAGIC = 0xE9
_MAX_FIRMWARE_BYTES = 16 * 1024 * 1024
_ALLOWED_OTA_STATUSES = {
    "idle",
    "pending",
    "downloading",
    "flashing",
    "flashing_done",
    "success",
    "failed",
    "rolled_back",
}


def _is_kiosk_device(dev: Dict[str, Any]) -> bool:
    """Returns True if the device record represents a Web Kiosk rather than an ESP32 Touch unit."""
    mac = (dev.get("mac_address") or "").lower().strip()
    fw = (dev.get("firmware_version") or "").lower()
    return mac.startswith("kiosk-") or "-web" in fw or "kiosk" in fw


def _validate_touch_lan_device(mac_address: str) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Any, int]]]:
    """
    Validates that a target MAC belongs to an approved ESP32 Touch hardware unit
    reachable on a private, non-loopback LAN IP (SSRF protection).
    """
    mac_clean = (mac_address or "").lower().strip()
    dev = database.get_esp32_device(mac_clean)
    if not dev:
        return None, (jsonify({"ok": False, "error": "Device not found."}), 404)
    if not dev.get("is_approved"):
        return None, (jsonify({"ok": False, "error": "Device is quarantined or not approved."}), 400)
    if _is_kiosk_device(dev):
        return None, (jsonify({"ok": False, "error": "Remote OTA & MicroSD cache commands apply only to ESP32 Touch hardware."}), 400)

    ip_str = (dev.get("ip_address") or "").strip()
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return None, (jsonify({"ok": False, "error": f"Device has invalid IP address: '{ip_str}'."}), 400)

    if not ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
        return None, (jsonify({"ok": False, "error": f"Blocked non-LAN device IP: '{ip_str}'."}), 400)

    return dev, None


def _is_lan_device_or_admin() -> bool:
    """Authorizes ESP32 pull/progress requests from trusted LAN IPs, valid device JWTs, or admins."""
    if get_current_admin_user() or get_current_device():
        return True
    return is_trusted_lan_ip(get_effective_client_ip())


def _safe_firmware_path(rel: Dict[str, Any]) -> Optional[Path]:
    """Resolves a firmware binary path within FIRMWARE_DIR safely."""
    raw_path = (rel.get("file_path") or "").strip()
    if not raw_path:
        return None
    fw_root = core_config.FIRMWARE_DIR.resolve()
    p = Path(raw_path).resolve()
    try:
        p.relative_to(fw_root)
    except ValueError:
        return None
    return p


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _dispatch_single_ota(
    dev: Dict[str, Any],
    rel: Dict[str, Any],
    host_url: str,
    force: bool = False,
) -> Tuple[Dict[str, Any], int]:
    """Triggers pull-based HTTP OTA on a single validated ESP32 Touch unit."""
    mac = dev["mac_address"]
    ip_str = (dev.get("ip_address") or "").strip()
    target_ver = rel["version"]
    current_ver = (dev.get("firmware_version") or "").strip()

    if current_ver == target_ver and not force:
        return {
            "ok": False,
            "error": f"Device '{dev.get('friendly_name') or mac}' is already running {target_ver}. Enable force to re-flash.",
        }, 400

    bin_path = _safe_firmware_path(rel)
    if not bin_path or not bin_path.is_file():
        return {"ok": False, "error": f"Firmware binary for {target_ver} is missing on disk."}, 404

    rel_url = f"/api/firmware/{target_ver}/firmware.bin"
    full_url = f"{host_url.rstrip('/')}{rel_url}" if host_url else rel_url

    database.update_esp32_device(
        mac,
        {
            "previous_firmware_version": current_ver,
            "target_firmware_version": target_ver,
            "ota_status": "pending",
            "ota_progress": 0,
            "ota_last_error": "",
        },
    )

    trigger_payload = {
        "url": rel_url,
        "full_url": full_url,
        "sha256": rel["sha256_hash"],
        "version": target_ver,
        "size": rel["file_size_bytes"],
    }

    try:
        resp = requests.post(f"http://{ip_str}/ota/trigger", json=trigger_payload, timeout=5)
        if 200 <= resp.status_code < 300:
            logger.info("Initiated OTA %s -> %s on ESP32 %s (%s)", current_ver, target_ver, mac, ip_str)
            return {
                "ok": True,
                "status": "update_initiated",
                "mac": mac,
                "target": target_ver,
                "previous": current_ver,
                "sha256": rel["sha256_hash"],
            }, 200
        err_msg = f"Device rejected OTA trigger (HTTP {resp.status_code})"
    except requests.RequestException as exc:
        err_msg = f"Failed to reach ESP32 at {ip_str}: {exc}"

    database.update_esp32_device(
        mac,
        {
            "ota_status": "failed",
            "ota_progress": 0,
            "ota_last_error": err_msg,
        },
    )
    return {"ok": False, "status": "failed", "mac": mac, "error": err_msg}, 502


def _relay_touch_cache_command(
    mac_address: str,
    method: str,
    endpoint: str,
    action: str,
    include_pin: bool = True,
    extra_params: Optional[Dict[str, str]] = None,
    timeout: int = 8,
) -> Tuple[Any, int]:
    """Shared proxy helper forwarding authenticated MicroSD cache commands to a Touch controller."""
    dev, err_resp = _validate_touch_lan_device(mac_address)
    if err_resp:
        return err_resp

    ip_str = (dev.get("ip_address") or "").strip()
    params: Dict[str, str] = {}
    if include_pin:
        body = request.get_json(silent=True) or {}
        pin = str(
            body.get("pin")
            or request.args.get("pin")
            or dev.get("parent_pin")
            or "1234"
        ).strip()
        params["pin"] = pin
    if extra_params:
        params.update(extra_params)

    target_url = f"http://{ip_str}{endpoint}"
    try:
        resp = requests.request(method=method, url=target_url, params=params or None, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Touch SD cache relay failed (%s %s): %s", method, target_url, exc)
        return jsonify({"ok": False, "error": f"Failed to reach ESP32 at {ip_str}: {exc}"}), 502

    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}

    if not (200 <= resp.status_code < 300):
        return jsonify({
            "ok": False,
            "error": f"Device returned HTTP {resp.status_code} for SD {action}",
            "device_response": payload,
        }), 502

    result: Dict[str, Any] = {
        "ok": True,
        "mac": dev["mac_address"],
        "ip": ip_str,
        "action": action,
        "device_response": payload,
    }
    if action == "status":
        result["sd"] = payload
    return jsonify(result), 200


# ============================================================================
# Admin Firmware Repository & Remote OTA Endpoints (DLP-010)
# ============================================================================

@admin_firmware_bp.route("/api/admin/firmware", methods=["GET"])
@require_admin
def admin_list_firmware():
    """Lists all uploaded firmware releases along with on-disk binary availability."""
    releases = database.list_firmware_releases()
    for r in releases:
        p = _safe_firmware_path(r)
        r["file_exists"] = bool(p and p.is_file())
        r["file_size_human"] = _format_bytes(r["file_size_bytes"])
    return jsonify(releases)


@admin_firmware_bp.route("/api/admin/firmware/upload", methods=["POST"])
@require_admin
def admin_upload_firmware():
    """Uploads an ESP32-S3 .bin image, validates header magic & SHA-256, and catalogs in SQLite."""
    version = (request.form.get("version") or "").strip()
    if not version or not _VERSION_RE.match(version):
        return jsonify({
            "ok": False,
            "error": "Invalid or missing semantic version (allowed: letters, digits, '.', '_', '-').",
        }), 400

    up_file = request.files.get("file")
    if not up_file or not up_file.filename:
        return jsonify({"ok": False, "error": "Missing firmware binary file."}), 400
    if not up_file.filename.lower().endswith(".bin"):
        return jsonify({"ok": False, "error": "Firmware upload must have a .bin extension."}), 400

    raw_bytes = up_file.read()
    size_bytes = len(raw_bytes)
    if size_bytes < 24 or size_bytes > _MAX_FIRMWARE_BYTES:
        return jsonify({
            "ok": False,
            "error": f"Firmware binary size ({size_bytes} bytes) is outside valid range (24 B - 16 MB).",
        }), 400

    if raw_bytes[0] != _ESP_IMAGE_HEADER_MAGIC:
        return jsonify({
            "ok": False,
            "error": "Invalid ESP32 binary image: missing 0xE9 ESP-IDF image header magic byte.",
        }), 400

    sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
    fw_dir = core_config.FIRMWARE_DIR
    fw_dir.mkdir(parents=True, exist_ok=True)
    target_path = (fw_dir / f"firmware_{version}.bin").resolve()
    if target_path.parent != fw_dir.resolve():
        return jsonify({"ok": False, "error": "Invalid firmware destination path."}), 400

    target_path.write_bytes(raw_bytes)

    release_tag = (request.form.get("release_tag") or version).strip()
    git_commit = (request.form.get("git_commit") or "").strip()
    release_notes = (request.form.get("release_notes") or "").strip()
    is_latest = str(request.form.get("is_active_latest", "false")).strip().lower() in ("1", "true", "yes", "on")

    record = database.upsert_firmware_release(
        version=version,
        release_tag=release_tag,
        file_path=str(target_path),
        file_size_bytes=size_bytes,
        sha256_hash=sha256_hex,
        git_commit=git_commit,
        release_notes=release_notes,
        is_active_latest=is_latest,
    )
    record["file_exists"] = True
    record["file_size_human"] = _format_bytes(size_bytes)
    logger.info("Cataloged firmware release %s (%d bytes, sha256=%s)", version, size_bytes, sha256_hex[:12])
    return jsonify({"ok": True, "release": record}), 201


@admin_firmware_bp.route("/api/admin/firmware/<version>/set-latest", methods=["POST"])
@require_admin
def admin_set_latest_firmware(version: str):
    """Marks a cataloged firmware release as the active latest default."""
    if not database.set_active_latest_firmware(version):
        return jsonify({"ok": False, "error": f"Firmware version '{version}' not found."}), 404
    return jsonify({"ok": True, "version": version, "is_active_latest": True})


@admin_firmware_bp.route("/api/admin/firmware/<version>", methods=["DELETE"])
@require_admin
def admin_delete_firmware(version: str):
    """Removes a firmware release record from SQLite and deletes its .bin file if inside FIRMWARE_DIR."""
    deleted = database.delete_firmware_release(version)
    if not deleted:
        return jsonify({"ok": False, "error": f"Firmware version '{version}' not found."}), 404

    p = _safe_firmware_path(deleted)
    if p and p.is_file():
        try:
            p.unlink()
        except OSError as exc:
            logger.warning("Failed deleting firmware binary %s: %s", p, exc)

    return jsonify({"ok": True, "deleted": version})


@admin_firmware_bp.route("/api/admin/devices/<mac_address>/update", methods=["POST"])
@require_admin
def admin_push_device_ota(mac_address: str):
    """Pushes a firmware update or rollback trigger to a single approved ESP32 Touch display."""
    dev, err_resp = _validate_touch_lan_device(mac_address)
    if err_resp:
        return err_resp

    data = request.get_json(silent=True) or {}
    version = (data.get("version") or "").strip()
    force = bool(data.get("force", False))

    rel = database.get_firmware_release(version) if version else database.get_latest_firmware_release()
    if not rel:
        return jsonify({"ok": False, "error": f"Firmware version '{version or 'latest'}' not found in repository."}), 404

    payload, status_code = _dispatch_single_ota(dev, rel, request.host_url, force=force)
    return jsonify(payload), status_code


@admin_firmware_bp.route("/api/admin/devices/update-all", methods=["POST"])
@require_admin
def admin_push_all_devices_ota():
    """Dispatches rolling or immediate OTA updates across all approved ESP32 Touch displays."""
    data = request.get_json(silent=True) or {}
    version = (data.get("version") or "").strip()
    force = bool(data.get("force", False))
    try:
        delay_seconds = max(0, min(300, int(data.get("delay_seconds", 0) or 0)))
    except (ValueError, TypeError):
        delay_seconds = 0

    rel = database.get_firmware_release(version) if version else database.get_latest_firmware_release()
    if not rel:
        return jsonify({"ok": False, "error": f"Firmware version '{version or 'latest'}' not found in repository."}), 404

    bin_path = _safe_firmware_path(rel)
    if not bin_path or not bin_path.is_file():
        return jsonify({"ok": False, "error": f"Firmware binary for {rel['version']} missing on disk."}), 404

    targets: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for d in database.list_esp32_devices():
        _, err_resp = _validate_touch_lan_device(d["mac_address"])
        if err_resp:
            skipped.append({"mac": d["mac_address"], "reason": "not_eligible_touch_lan"})
            continue
        if (d.get("firmware_version") or "").strip() == rel["version"] and not force:
            skipped.append({"mac": d["mac_address"], "reason": "already_on_version"})
            continue
        targets.append(d)

    host_url = request.host_url

    if delay_seconds > 0 and len(targets) > 1:
        def _rolling_worker(worker_targets: List[Dict[str, Any]], release_rec: Dict[str, Any], h_url: str, delay_s: int, f_flag: bool):
            for idx, dev_item in enumerate(worker_targets):
                if idx > 0:
                    time.sleep(delay_s)
                _dispatch_single_ota(dev_item, release_rec, h_url, force=f_flag)

        t = threading.Thread(
            target=_rolling_worker,
            args=(targets, rel, host_url, delay_seconds, force),
            daemon=True,
        )
        t.start()
        return jsonify({
            "ok": True,
            "status": "rolling_update_started",
            "target": rel["version"],
            "queued": len(targets),
            "skipped": len(skipped),
            "delay_seconds": delay_seconds,
            "targets": [d["mac_address"] for d in targets],
        }), 202

    results = []
    dispatched = 0
    failed = 0
    for d in targets:
        res_payload, res_code = _dispatch_single_ota(d, rel, host_url, force=force)
        results.append(res_payload)
        if res_code == 200 and res_payload.get("ok"):
            dispatched += 1
        else:
            failed += 1

    return jsonify({
        "ok": True,
        "target": rel["version"],
        "dispatched": dispatched,
        "failed": failed,
        "skipped": len(skipped),
        "results": results,
    }), 200


# ============================================================================
# ESP32 Binary Stream & Live OTA Progress Telemetry (DLP-010)
# ============================================================================

@admin_firmware_bp.route("/api/firmware/<version>/firmware.bin", methods=["GET"])
def serve_firmware_binary(version: str):
    """Streams the requested firmware binary to trusted LAN ESP32 controllers with X-SHA256 header."""
    if not _is_lan_device_or_admin():
        return jsonify({"ok": False, "error": "Firmware downloads are restricted to trusted LAN devices or admins."}), 403

    clean_ver = (version or "").strip()
    if not clean_ver or not _VERSION_RE.match(clean_ver):
        return jsonify({"ok": False, "error": "Invalid firmware version format."}), 400

    rel = database.get_firmware_release(clean_ver)
    if not rel:
        return jsonify({"ok": False, "error": f"Firmware version '{clean_ver}' not found."}), 404

    bin_path = _safe_firmware_path(rel)
    if not bin_path or not bin_path.is_file():
        return jsonify({"ok": False, "error": f"Firmware file missing on disk for '{clean_ver}'."}), 404

    resp = send_file(
        str(bin_path),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f"firmware_{clean_ver}.bin",
    )
    resp.headers["X-SHA256"] = rel["sha256_hash"]
    resp.headers["X-Firmware-Version"] = clean_ver
    resp.headers["Content-Length"] = str(bin_path.stat().st_size)
    return resp


@admin_firmware_bp.route("/api/devices/<mac_address>/ota-progress", methods=["POST"])
def report_device_ota_progress(mac_address: str):
    """Receives live chunked flash progress & error telemetry from an ESP32 controller."""
    if not _is_lan_device_or_admin():
        return jsonify({"ok": False, "error": "OTA telemetry restricted to trusted LAN devices or admins."}), 403

    mac_clean = (mac_address or "").lower().strip()
    dev = database.get_esp32_device(mac_clean)
    if not dev:
        return jsonify({"ok": False, "error": "Device not found."}), 404

    data = request.get_json(silent=True) or {}
    raw_prog = data.get("progress")
    if raw_prog is None:
        raw_prog = data.get("percent")

    default_status = "flashing" if raw_prog is not None else "idle"
    status = str(data.get("status") or default_status).strip().lower()
    if status not in _ALLOWED_OTA_STATUSES:
        return jsonify({"ok": False, "error": f"Invalid ota_status '{status}'."}), 400

    if raw_prog is None:
        progress = 100 if status in ("flashing_done", "success") else int(dev.get("ota_progress") or 0)
    else:
        try:
            progress = max(0, min(100, int(round(float(raw_prog)))))
        except (ValueError, TypeError):
            progress = 0

    err_msg = str(data.get("error") or data.get("ota_last_error") or "").strip()
    updates: Dict[str, Any] = {
        "ota_status": status,
        "ota_progress": progress,
        "ota_last_error": err_msg,
    }
    if status == "success" and data.get("version"):
        updates["firmware_version"] = str(data["version"]).strip()

    database.update_esp32_device(mac_clean, updates)
    return jsonify({
        "ok": True,
        "mac": mac_clean,
        "ota_status": status,
        "ota_progress": progress,
    })


# ============================================================================
# Touch MicroSD Cache Inspection, Orphan Pruning & Purge Proxies (DLP-020)
# ============================================================================

@admin_firmware_bp.route("/api/admin/devices/<mac_address>/cache/status", methods=["GET"])
@require_admin
def admin_device_cache_status(mac_address: str):
    """Fetches live /sd/status storage metrics from an approved Touch display on the LAN."""
    return _relay_touch_cache_command(
        mac_address=mac_address,
        method="GET",
        endpoint="/sd/status",
        action="status",
        include_pin=False,
        timeout=5,
    )


@admin_firmware_bp.route("/api/admin/devices/<mac_address>/cache/prune", methods=["POST"])
@admin_firmware_bp.route("/api/devices/<mac_address>/cache/prune", methods=["POST"])
@require_admin
def admin_device_cache_prune(mac_address: str):
    """Relays POST /sd/prune to unlink orphaned .565/.chap files on the Touch MicroSD card."""
    return _relay_touch_cache_command(
        mac_address=mac_address,
        method="POST",
        endpoint="/sd/prune",
        action="prune",
    )


@admin_firmware_bp.route("/api/admin/devices/<mac_address>/cache/refresh", methods=["POST"])
@admin_firmware_bp.route("/api/devices/<mac_address>/cache/refresh", methods=["POST"])
@require_admin
def admin_device_cache_refresh(mac_address: str):
    """Relays POST /sd/refresh to invalidate and re-warm a specific card's MicroSD cache."""
    body = request.get_json(silent=True) or {}
    card_id = str(body.get("card_id") or body.get("id") or request.args.get("card_id") or "").strip()
    extra = {"id": card_id} if card_id else None
    return _relay_touch_cache_command(
        mac_address=mac_address,
        method="POST",
        endpoint="/sd/refresh",
        action="refresh",
        extra_params=extra,
    )


@admin_firmware_bp.route("/api/admin/devices/<mac_address>/cache", methods=["DELETE"])
@admin_firmware_bp.route("/api/admin/devices/<mac_address>/cache/rebuild", methods=["POST"])
@admin_firmware_bp.route("/api/devices/<mac_address>/cache/rebuild", methods=["POST"])
@require_admin
def admin_device_cache_purge(mac_address: str):
    """Relays DELETE /sd/cache?confirm=1 to flush /ythumbs/ on the Touch MicroSD card."""
    return _relay_touch_cache_command(
        mac_address=mac_address,
        method="DELETE",
        endpoint="/sd/cache",
        action="purge",
        extra_params={"confirm": "1"},
    )
