"""
Yoto Play OAuth 2.0 PKCE in-browser authorization and token exchange blueprint.
"""

import os
import json
import time
import base64
import hashlib
import secrets
import urllib.parse
import html
from typing import Dict, Any, Optional, Tuple
import requests
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import logger
from core.auth import require_admin

yoto_oauth_bp = Blueprint("yoto_oauth", __name__)

# Multi-worker SQLite setting key + compatibility in-memory mirror for PKCE flows
_PKCE_FLOWS_SETTING_KEY = "yoto_oauth_pkce_flows"
_PKCE_FLOW_TTL_SECONDS = 600
YOTO_PKCE_FLOWS: Dict[str, Any] = {}


def _prune_expired_flows(flows: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    return {
        s: f for s, f in flows.items()
        if isinstance(f, dict) and float(f.get("expires_at", 0)) >= now
    }


def _load_pkce_flows() -> Dict[str, Any]:
    """Loads active PKCE flows from SQLite system_settings and syncs in-memory cache."""
    raw = database.get_system_settings().get(_PKCE_FLOWS_SETTING_KEY)
    flows: Dict[str, Any] = {}
    if isinstance(raw, dict):
        flows = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                flows = parsed
        except Exception:
            flows = {}
    pruned = _prune_expired_flows(flows)
    # Include any non-expired in-memory flows inserted directly by legacy callers/tests
    for s, f in list(_prune_expired_flows(YOTO_PKCE_FLOWS).items()):
        pruned.setdefault(s, f)
    return pruned


def _save_pkce_flows(flows: Dict[str, Any]) -> None:
    pruned = _prune_expired_flows(flows)
    database.set_system_setting(_PKCE_FLOWS_SETTING_KEY, pruned)
    YOTO_PKCE_FLOWS.clear()
    YOTO_PKCE_FLOWS.update(pruned)


def _put_pkce_flow(state: str, flow: Dict[str, Any]) -> None:
    flows = _load_pkce_flows()
    flows[state] = flow
    _save_pkce_flows(flows)


def _get_pkce_flow(state: str) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    flows = _load_pkce_flows()
    flow = flows.get(state)
    if flow:
        return flow
    mem_flow = YOTO_PKCE_FLOWS.get(state)
    if isinstance(mem_flow, dict) and float(mem_flow.get("expires_at", 0)) >= time.time():
        return mem_flow
    return None


def _update_pkce_flow(state: str, **updates: Any) -> None:
    if not state:
        return
    flows = _load_pkce_flows()
    if state in flows:
        flows[state].update(updates)
        _save_pkce_flows(flows)


def _resolve_redirect_uri(explicit_redirect_uri: str = "", client_origin: str = "") -> Tuple[str, bool]:
    """
    Determines the OAuth redirect_uri honoring explicit overrides, browser client_origin,
    and reverse-proxy X-Forwarded-Proto/Host headers.
    Yoto Auth0 (RFC 8252) permits https:// origins and http://127.0.0.1|localhost loopback;
    plain HTTP LAN IPs must fall back to the manual copy-paste loopback URI on :8787.
    """
    explicit = (explicit_redirect_uri or "").strip()
    if explicit:
        return explicit, explicit.endswith("/s/yoto-callback")

    origin = ""
    raw_origin = (client_origin or "").strip()
    if raw_origin:
        parsed_origin = urllib.parse.urlparse(raw_origin)
        if parsed_origin.scheme.lower() in ("http", "https") and parsed_origin.netloc:
            origin = f"{parsed_origin.scheme.lower()}://{parsed_origin.netloc}"

    if not origin:
        fwd_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        fwd_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
        if fwd_host:
            scheme = fwd_proto if fwd_proto in ("http", "https") else (request.scheme or "http")
            origin = f"{scheme}://{fwd_host}"
        elif fwd_proto in ("http", "https") and request.host:
            origin = f"{fwd_proto}://{request.host}"
        else:
            origin = request.host_url.rstrip("/")

    parsed = urllib.parse.urlparse(origin)
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()

    if scheme == "https" or hostname in ("127.0.0.1", "localhost"):
        return f"{origin}/s/yoto-callback", True

    return "http://127.0.0.1:8787/callback", False


def _exchange_pkce_code(code: str, state: str = "") -> Tuple[bool, str, int]:
    """
    Idempotently exchanges a Yoto OAuth 2.0 PKCE authorization code for tokens,
    persisting yoto_client_id + yoto_refresh_token in SQLite and reloading clients.
    """
    clean_code = (code or "").strip()
    clean_state = (state or "").strip()

    if not clean_code:
        return False, "No authorization code found in submission.", 400

    flows = _load_pkce_flows()
    resolved_state = clean_state
    flow = _get_pkce_flow(clean_state) if clean_state else None

    if not flow and not clean_state:
        pending = [
            (s, f) for s, f in flows.items()
            if f.get("status", "pending") == "pending"
        ]
        if len(pending) == 1:
            resolved_state, flow = pending[0]
        elif len(pending) > 1:
            resolved_state, flow = max(pending, key=lambda item: float(item[1].get("created_at", 0)))
        elif len(flows) == 1:
            resolved_state, flow = next(iter(flows.items()))

    if not flow:
        return False, "OAuth session expired or state mismatch. Please click 'Connect Yoto (OAuth)' again.", 400

    if flow.get("status") == "completed":
        msg = flow.get("message") or "Yoto connected successfully! Refresh token saved and client activated."
        return True, msg, 200

    # Public Client PKCE token exchange — never include client_secret (causes Auth0 HTTP 401)
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": flow["client_id"],
        "code_verifier": flow["verifier"],
        "code": clean_code,
        "redirect_uri": flow["redirect_uri"]
    }

    try:
        res = requests.post("https://login.yotoplay.com/oauth/token", json=token_payload, timeout=15)
        if res.status_code == 200:
            token_data = res.json()
            refresh_token = token_data.get("refresh_token")
            access_token = token_data.get("access_token")

            if not refresh_token:
                err_msg = "Yoto did not return a refresh token. Ensure 'offline_access' scope is enabled in dashboard.yoto.dev."
                _update_pkce_flow(resolved_state, status="error", error=err_msg)
                return False, err_msg, 400

            database.update_api_credentials({
                "yoto_client_id": flow["client_id"],
                "yoto_refresh_token": refresh_token
            })

            clients.reload_clients()
            if clients.yoto_client:
                clients.yoto_client.access_token = access_token
                clients.yoto_client.expires_at = time.time() + token_data.get("expires_in", 3600)

            if os.getenv("STORYDECK_TESTING", "").lower() not in ("1", "true", "yes"):
                try:
                    from core.bridge import get_mqtt_bridge
                    get_mqtt_bridge().start()
                except Exception as mqtt_err:
                    logger.debug("Post-OAuth MQTT start deferred: %s", mqtt_err)

            success_msg = "Yoto connected successfully! Refresh token saved and client activated."
            _update_pkce_flow(resolved_state, status="completed", message=success_msg, error="")
            return True, success_msg, 200

        err_msg = f"Token exchange failed ({res.status_code}): {res.text}"
        logger.error("Yoto token exchange failed: %d %s", res.status_code, res.text)
        _update_pkce_flow(resolved_state, status="error", error=err_msg)
        return False, err_msg, 502
    except Exception as e:
        logger.error("Exception during OAuth finish: %s", e)
        _update_pkce_flow(resolved_state, status="error", error=str(e))
        return False, str(e), 500


def _js_safe_json(payload: Dict[str, Any]) -> str:
    """Serializes payload safely for inline <script> injection."""
    return json.dumps(payload).replace("</", "<\\/")


def _render_callback_script(payload: Dict[str, Any], auto_close: bool = False) -> str:
    safe_json = _js_safe_json(payload)
    close_stmt = "setTimeout(() => { try { window.close(); } catch (e) {} }, 1200);" if auto_close else ""
    return f"""<script>
        (function() {{
            const payload = {safe_json};
            try {{
                if (typeof BroadcastChannel !== "undefined") {{
                    const ch = new BroadcastChannel("storydeck_yoto_oauth");
                    ch.postMessage(payload);
                    ch.close();
                }}
            }} catch (e) {{}}
            try {{
                localStorage.setItem("storydeck_yoto_oauth_result", JSON.stringify(Object.assign({{ ts: Date.now() }}, payload)));
            }} catch (e) {{}}
            try {{
                if (window.opener && !window.opener.closed) {{
                    window.opener.postMessage(payload, window.location.origin);
                }}
            }} catch (e) {{}}
            {close_stmt}
        }})();
    </script>"""


@yoto_oauth_bp.route("/api/admin/yoto/oauth/start", methods=["POST"])
@require_admin
def admin_yoto_oauth_start():
    """Generates a cryptographic PKCE challenge and authorization URL for in-browser Yoto login."""
    data = request.get_json(silent=True) or {}
    client_id = (data.get("client_id") or (clients.yoto_client.client_id if clients.yoto_client else "") or "").strip()
    if not client_id:
        return jsonify({"ok": False, "error": "Client ID is required to start Yoto login."}), 400

    explicit_redirect = (data.get("redirect_uri") or "").strip()
    client_origin = (data.get("client_origin") or "").strip()
    redirect_uri, auto_callback = _resolve_redirect_uri(explicit_redirect, client_origin)

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    state = secrets.token_hex(16)

    now = time.time()
    _put_pkce_flow(state, {
        "client_id": client_id,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "auto_callback": auto_callback,
        "status": "pending",
        "message": "",
        "error": "",
        "created_at": now,
        "expires_at": now + _PKCE_FLOW_TTL_SECONDS
    })

    params = {
        "audience": "https://api.yotoplay.com",
        "scope": "family:library:view user:content:manage family:devices:view family:devices:control offline_access",
        "response_type": "code",
        "client_id": client_id,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": redirect_uri,
        "state": state
    }
    auth_url = f"https://login.yotoplay.com/authorize?{urllib.parse.urlencode(params)}"
    return jsonify({
        "ok": True,
        "auth_url": auth_url,
        "state": state,
        "redirect_uri": redirect_uri,
        "auto_callback": auto_callback
    })


@yoto_oauth_bp.route("/api/admin/yoto/oauth/status", methods=["GET"])
@require_admin
def admin_yoto_oauth_status():
    """Polls multi-worker PKCE flow completion state from SQLite."""
    state = (request.args.get("state") or "").strip()
    flow = _get_pkce_flow(state) if state else None
    if not flow:
        return jsonify({
            "ok": True,
            "status": "not_found",
            "message": "",
            "error": ""
        })
    return jsonify({
        "ok": True,
        "status": flow.get("status", "pending"),
        "message": flow.get("message", ""),
        "error": flow.get("error", "")
    })


@yoto_oauth_bp.route("/api/admin/yoto/oauth/finish", methods=["POST"])
@require_admin
def admin_yoto_oauth_finish():
    """Exchanges an authorization code or redirect landing URL for tokens and saves to SQLite."""
    data = request.get_json(silent=True) or {}
    url_or_code = (data.get("url_or_code") or "").strip()
    state = (data.get("state") or "").strip()

    code = url_or_code
    if "code=" in url_or_code:
        parsed = urllib.parse.urlparse(url_or_code)
        q = urllib.parse.parse_qs(parsed.query)
        code = q.get("code", [""])[0]
        if not state:
            state = q.get("state", [""])[0]

    ok, msg, status_code = _exchange_pkce_code(code, state)
    if ok:
        return jsonify({"ok": True, "message": msg}), status_code
    return jsonify({"ok": False, "error": msg}), status_code


@yoto_oauth_bp.route("/s/yoto-callback", methods=["GET"])
def yoto_callback_landing():
    """Universal browser landing page that immediately completes OAuth token exchange server-side."""
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")
    error_desc = request.args.get("error_description", "")

    if error:
        err_text = error_desc or error
        if state:
            _update_pkce_flow(state, status="error", error=err_text)
        script = _render_callback_script({
            "type": "YOTO_AUTH_COMPLETE",
            "ok": False,
            "state": state,
            "error": err_text
        })
        return f"""<!doctype html>
        <html>
        <head><meta charset="utf-8"><title>Yoto Login Denied</title></head>
        <body style="font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 60px;">
        <h2 style="color: #ef4444;">&#10008; Yoto Login Denied</h2>
        <p>{html.escape(err_text)}</p>
        <p><a href="/admin#settings" style="display: inline-block; background: #f97316; color: #fff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">Return to Admin Portal</a></p>
        {script}
        </body></html>""", 400

    ok, msg, status_code = _exchange_pkce_code(code, state)
    if ok:
        script = _render_callback_script({
            "type": "YOTO_AUTH_COMPLETE",
            "ok": True,
            "state": state,
            "message": msg
        }, auto_close=True)
        return f"""<!doctype html>
        <html>
        <head><meta charset="utf-8"><title>Yoto Connected Automatically</title></head>
        <body style="font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 60px;">
            <h2 style="color: #22c55e;">&#10004; Yoto Connected Automatically!</h2>
            <p>{html.escape(msg)}</p>
            <p style="color: #94a3b8; font-size: 14px;">Your refresh token is saved in StoryDeck Core. This window will close automatically.</p>
            <p style="margin-top: 24px;"><a href="/admin#settings" style="display: inline-block; background: #f97316; color: #fff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">Return to Admin Portal</a></p>
            {script}
        </body>
        </html>""", 200

    script = _render_callback_script({
        "type": "YOTO_AUTH_COMPLETE",
        "ok": False,
        "state": state,
        "error": msg
    })
    return f"""<!doctype html>
    <html>
    <head><meta charset="utf-8"><title>Yoto Authorization Incomplete</title></head>
    <body style="font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 60px;">
        <h2 style="color: #f59e0b;">&#9888; Could Not Auto-Complete Yoto Login</h2>
        <p style="color: #fca5a5;">{html.escape(msg)}</p>
        <div style="margin: 30px auto; max-width: 520px; background: #1e293b; padding: 20px; border-radius: 8px; border: 1px solid #334155;">
            <p style="margin-bottom: 12px; font-size: 14px; color: #94a3b8;">If needed, copy this code or the full address bar URL into the Admin Portal fallback field:</p>
            <input type="text" readonly value="{html.escape(code)}" style="width: 100%; padding: 10px; background: #0f172a; color: #38bdf8; border: 1px solid #475569; border-radius: 6px; font-family: monospace; font-size: 14px; text-align: center;">
        </div>
        <p><a href="/admin#settings" style="display: inline-block; background: #f97316; color: #fff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">Return to Admin Portal</a></p>
        {script}
    </body>
    </html>""", status_code if status_code >= 400 else 400
