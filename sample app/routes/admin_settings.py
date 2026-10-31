"""
Admin settings, service credentials, connectivity diagnostics, and cache management blueprint.
"""

import time
import requests
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import CACHE_DIR, logger
from core.auth import require_admin

admin_settings_bp = Blueprint("admin_settings", __name__)


# ============================================================================
# Settings & Credentials Management
# ============================================================================

@admin_settings_bp.route("/api/admin/settings/credentials", methods=["GET", "PUT"])
@require_admin
def admin_credentials():
    """Manages API keys and service connection URLs from the admin dashboard."""
    if request.method == "GET":
        creds = database.get_api_credentials()
        # Mask sensitive secrets for UI display
        masked = {}
        for k, v in creds.items():
            if "key" in k or "secret" in k or "token" in k:
                if v and len(v) > 8:
                    masked[k] = v[:4] + "••••••••" + v[-4:]
                elif v:
                    masked[k] = "••••••••"
                else:
                    masked[k] = ""
            else:
                masked[k] = v
        return jsonify(masked)

    elif request.method == "PUT":
        data = request.get_json(silent=True) or {}
        # Ignore masked placeholder submissions
        filtered = {}
        for k, v in data.items():
            if v and "••••" in v:
                continue
            filtered[k] = v

        if database.update_api_credentials(filtered):
            # Hot-reload global clients with new credentials
            clients.reload_clients()
            return jsonify({"ok": True, "message": "API credentials updated and services reloaded."})
        return jsonify({"ok": False, "error": "Failed to update credentials."}), 500


# ============================================================================
# Master API Security Endpoints
# ============================================================================

@admin_settings_bp.route("/api/admin/security/api-key", methods=["GET"])
@require_admin
def admin_get_master_api_key():
    """Returns the Broker master API key for administrative management."""
    details = database.get_master_api_key_details()
    return jsonify({
        "ok": True,
        "api_key": details["api_key"],
        "updated_at": details.get("updated_at") or ""
    })


@admin_settings_bp.route("/api/admin/security/regenerate-api-key", methods=["POST"])
@require_admin
def admin_regenerate_master_api_key():
    """
    Regenerates the master API key.
    Requires confirm: true in JSON body.
    """
    data = request.get_json(silent=True) or {}
    if not data.get("confirm"):
        return jsonify({"ok": False, "error": "Confirmation required to regenerate API key."}), 400

    new_key = database.regenerate_master_api_key()
    return jsonify({
        "ok": True,
        "api_key": new_key,
        "message": "Master API key regenerated successfully. All external integrations must be updated."
    })



@admin_settings_bp.route("/api/admin/abs/server-tags", methods=["GET"])
@require_admin
def admin_get_abs_server_tags():
    """Returns the live list of all tags present in Audiobookshelf."""
    if not clients.abs_client:
        return jsonify({"ok": False, "error": "Audiobookshelf client not configured"}), 503
    tags = clients.abs_client.get_all_server_tags()
    return jsonify({"ok": True, "tags": tags})


@admin_settings_bp.route("/api/admin/settings/abs-tags", methods=["GET", "PUT"])
@require_admin
def admin_manage_abs_default_tags():
    """Gets or updates the default children account tags configuration."""
    if request.method == "GET":
        settings = database.get_system_settings()
        tags = settings.get("abs_default_children_tags", ["Children"])
        return jsonify({"ok": True, "tags": tags})

    elif request.method == "PUT":
        data = request.get_json(silent=True) or {}
        tags = data.get("tags")
        if not isinstance(tags, list):
            return jsonify({"ok": False, "error": "Tags must be a list of strings"}), 400

        # Clean tags list
        clean_tags = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
        if not clean_tags:
            clean_tags = ["Children"]

        database.set_system_setting("abs_default_children_tags", clean_tags)
        return jsonify({"ok": True, "tags": clean_tags, "message": "Default children tags updated."})


@admin_settings_bp.route("/api/admin/settings/catalog", methods=["GET", "PUT"])
@require_admin
def admin_manage_catalog_settings():
    """Gets or updates general catalog display and library refresh settings."""
    from core.scheduler import get_refresh_status
    if request.method == "GET":
        settings = database.get_system_settings()
        status = get_refresh_status()
        return jsonify({
            "ok": True,
            "exclude_single_card_series": bool(settings.get("exclude_single_card_series", True)),
            "auto_library_refresh_enabled": bool(settings.get("auto_library_refresh_enabled", True)),
            "auto_library_refresh_hours": float(settings.get("auto_library_refresh_hours", 6)),
            "scheduler_status": status
        })

    elif request.method == "PUT":
        data = request.get_json(silent=True) or {}
        if "exclude_single_card_series" in data:
            exclude_val = bool(data.get("exclude_single_card_series", True))
            database.set_system_setting("exclude_single_card_series", exclude_val)
        
        if "auto_library_refresh_enabled" in data:
            auto_refresh_enabled = bool(data.get("auto_library_refresh_enabled", True))
            database.set_system_setting("auto_library_refresh_enabled", auto_refresh_enabled)

        if "auto_library_refresh_hours" in data:
            try:
                refresh_hours = float(data.get("auto_library_refresh_hours", 6))
                if refresh_hours < 0.25:
                    refresh_hours = 0.25
                elif refresh_hours > 168:
                    refresh_hours = 168
            except (ValueError, TypeError):
                refresh_hours = 6.0
            database.set_system_setting("auto_library_refresh_hours", refresh_hours)

        settings = database.get_system_settings()
        status = get_refresh_status()
        return jsonify({
            "ok": True,
            "exclude_single_card_series": bool(settings.get("exclude_single_card_series", True)),
            "auto_library_refresh_enabled": bool(settings.get("auto_library_refresh_enabled", True)),
            "auto_library_refresh_hours": float(settings.get("auto_library_refresh_hours", 6)),
            "scheduler_status": status,
            "message": "Settings updated."
        })


# ============================================================================
# Diagnostics & Service Probes
# ============================================================================

@admin_settings_bp.route("/api/admin/test/abs", methods=["POST"])
@require_admin
def admin_test_abs():
    """Live connectivity probe against Audiobookshelf."""
    t0 = time.time()
    libs = clients.abs_client.get_libraries() if clients.abs_client else []
    latency = int((time.time() - t0) * 1000)
    if libs:
        return jsonify({"ok": True, "message": f"Connected! Found {len(libs)} libraries ({latency}ms)."})
    return jsonify({"ok": False, "error": "Failed to connect or no libraries found. Verify ABS_BASE_URL & ABS_API_KEY."}), 502


@admin_settings_bp.route("/api/admin/test/yoto", methods=["POST"])
@require_admin
def admin_test_yoto():
    """Live OAuth token test against Yoto Developer Cloud."""
    if not clients.yoto_client or not clients.yoto_client.client_id:
        return jsonify({"ok": False, "error": "Yoto Client ID is not configured."}), 400

    token = clients.yoto_client.get_token()
    if token:
        players = clients.yoto_client.get_devices()
        return jsonify({"ok": True, "message": f"Connected! Token valid, {len(players)} player devices registered."})
    
    # Public clients without client_secret may only have a client_id and no refresh_token yet
    if not clients.yoto_client.refresh_token:
        return jsonify({"ok": False, "error": "Public client configured, but Refresh Token is missing. Authorize via Yoto OAuth to generate a refresh token."}), 400

    return jsonify({"ok": False, "error": "OAuth refresh failed. Check your Client ID and Refresh Token."}), 502


@admin_settings_bp.route("/api/admin/test/bridge", methods=["POST"])
@require_admin
def admin_test_bridge():
    """Live connectivity and health check against the local Yoto ↔ Audiobookshelf Streaming Bridge."""
    creds = database.get_api_credentials()
    bridge_url = creds.get("yoto_bridge_url", "").rstrip("/")
    bridge_api_key = creds.get("yoto_bridge_api_key", "").strip()
    if not bridge_url:
        return jsonify({"ok": False, "error": "Yoto-ABS Bridge URL is not configured."}), 400

    headers = {}
    if bridge_api_key:
        headers["X-Api-Key"] = bridge_api_key

    try:
        t0 = time.time()
        # 1. Probe protected endpoint to verify API key status
        auth_res = requests.get(f"{bridge_url}/api/yoto/playlists", headers=headers, timeout=5)
        latency = int((time.time() - t0) * 1000)

        if auth_res.status_code == 401:
            if not bridge_api_key:
                return jsonify({
                    "ok": False,
                    "error": "Bridge requires authentication, but no Master API Key is configured in the Broker (HTTP 401 Unauthorized)."
                }), 401
            return jsonify({
                "ok": False,
                "error": "Bridge rejected the provided Master API Key (HTTP 401 Unauthorized). Please check your key."
            }), 401

        # 2. Probe status endpoint for telemetry
        res = requests.get(f"{bridge_url}/api/status", headers=headers, timeout=5)
        auth_note = " • API Key Verified" if bridge_api_key else ""


        if res.status_code == 200:
            try:
                data = res.json()
                yoto_login = "Logged in" if data.get("yoto_logged_in") else "Not logged in"
                devices_count = len(data.get("devices", []))
                return jsonify({
                    "ok": True,
                    "message": f"Bridge Connected ({latency}ms)! Status: {yoto_login}, {devices_count} active players detected{auth_note}."
                })
            except Exception:
                return jsonify({"ok": True, "message": f"Bridge reachable at {bridge_url} ({latency}ms){auth_note}."})
        
        # Check /s/health fallback
        res2 = requests.get(f"{bridge_url}/s/health", timeout=5)
        if res2.status_code == 200:
            return jsonify({"ok": True, "message": f"Bridge online and responding to health probe ({latency}ms){auth_note}."})

        return jsonify({"ok": False, "error": f"Bridge returned HTTP {res.status_code} at {probe_url}."}), 502

    except requests.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": f"Connection refused to bridge at {bridge_url}. Is the container running?"}), 502
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": f"Timed out connecting to bridge at {bridge_url}."}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": f"Bridge test error: {str(e)}"}), 500


@admin_settings_bp.route("/api/admin/test/tinker", methods=["POST"])
@require_admin
def admin_test_tinker():
    """Live probe against Tinker Icons API."""
    creds = database.get_api_credentials()
    key = creds.get("tinker_api_key", "").strip()
    if not key:
        return jsonify({"ok": False, "error": "Tinker Icons API Key is not configured."}), 400

    try:
        url = "https://api.tinker.audio/icons?q=test&limit=1"
        res = requests.get(url, headers={"X-Tinker-Key": key, "User-Agent": "YotoBroker/1.0"}, timeout=6)
        if res.status_code == 200:
            return jsonify({"ok": True, "message": "Tinker Icons API key is valid and connected."})
        elif res.status_code == 401:
            return jsonify({"ok": False, "error": "Invalid Tinker API key. Get a free key at developers.tinker.audio"}), 401
        elif res.status_code == 429:
            return jsonify({"ok": False, "error": "Tinker rate limit reached (429)."}), 429
        return jsonify({"ok": False, "error": f"Tinker returned status {res.status_code}."}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error reaching Tinker: {str(e)}"}), 500




@admin_settings_bp.route("/api/admin/test/ai", methods=["POST"])
@require_admin
def admin_test_ai():
    """Live probe against configured AI provider (OpenRouter / Gemini / Claude)."""
    creds = database.get_api_credentials()
    openrouter_key = creds.get("openrouter_api_key", "").strip()
    gemini_key = creds.get("gemini_api_key", "").strip()
    claude_key = creds.get("anthropic_api_key", "").strip()

    if not openrouter_key and not gemini_key and not claude_key:
        return jsonify({"ok": False, "error": "No AI API key configured (OpenRouter, Gemini, or Claude)."}), 400

    # Probe OpenRouter if configured
    if openrouter_key:
        try:
            url = "https://openrouter.ai/api/v1/auth/key"
            res = requests.get(url, headers={"Authorization": f"Bearer {openrouter_key}"}, timeout=8)
            if res.status_code == 200:
                data = res.json().get("data", {})
                label = data.get("label") or "OpenRouter Key"
                limit_info = ""
                if "limit" in data and data["limit"] is not None:
                    limit_info = f" (Limit: ${data['limit']})"
                return jsonify({"ok": True, "message": f"OpenRouter API key verified: {label}{limit_info}."})
            elif res.status_code == 401:
                return jsonify({"ok": False, "error": "Invalid OpenRouter API Key (401 Unauthorized)."}), 401
            else:
                return jsonify({"ok": False, "error": f"OpenRouter returned status {res.status_code}."}), 502
        except Exception as e:
            return jsonify({"ok": False, "error": f"Error reaching OpenRouter: {str(e)}"}), 500

    # Probe Gemini if configured
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
            res = requests.get(url, timeout=8)
            if res.status_code == 200:
                return jsonify({"ok": True, "message": "Google Gemini API key verified successfully."})
            elif res.status_code in (400, 401, 403):
                return jsonify({"ok": False, "error": f"Gemini API rejected key ({res.status_code})."}), 401
            return jsonify({"ok": False, "error": f"Gemini returned status {res.status_code}."}), 502
        except Exception as e:
            return jsonify({"ok": False, "error": f"Error reaching Gemini: {str(e)}"}), 500

    # Probe Anthropic if configured
    if claude_key:
        try:
            url = "https://api.anthropic.com/v1/models"
            headers = {"x-api-key": claude_key, "anthropic-version": "2023-06-01"}
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                return jsonify({"ok": True, "message": "Anthropic Claude API key verified successfully."})
            elif res.status_code == 401:
                return jsonify({"ok": False, "error": "Invalid Anthropic API Key (401 Unauthorized)."}), 401
            return jsonify({"ok": False, "error": f"Anthropic returned status {res.status_code}."}), 502
        except Exception as e:
            return jsonify({"ok": False, "error": f"Error reaching Anthropic: {str(e)}"}), 500

    return jsonify({"ok": False, "error": "No valid provider test available."}), 400


@admin_settings_bp.route("/api/admin/cache/purge", methods=["POST"])
@require_admin
def admin_purge_cache():
    """Purges disk thumbnail cache."""
    purged_count = 0
    bytes_freed = 0
    try:
        for f in CACHE_DIR.glob("*"):
            if f.is_file():
                bytes_freed += f.stat().st_size
                f.unlink()
                purged_count += 1
        return jsonify({"ok": True, "files_purged": purged_count, "bytes_freed": bytes_freed})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
