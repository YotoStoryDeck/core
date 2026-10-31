"""
Yoto Play OAuth 2.0 PKCE in-browser authorization and token exchange blueprint.
"""

import time
import base64
import hashlib
import secrets
import urllib.parse
import html
from typing import Dict, Any
import requests
from flask import Blueprint, request, jsonify
import database
import clients
from core.config import logger
from core.auth import require_admin

yoto_oauth_bp = Blueprint("yoto_oauth", __name__)

# In-memory PKCE flow tracking for browser-based Yoto onboarding
YOTO_PKCE_FLOWS: Dict[str, Any] = {}


@yoto_oauth_bp.route("/api/admin/yoto/oauth/start", methods=["POST"])
@require_admin
def admin_yoto_oauth_start():
    """Generates a cryptographic PKCE challenge and authorization URL for in-browser Yoto login."""
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id") or (clients.yoto_client.client_id if clients.yoto_client else "")
    redirect_uri = data.get("redirect_uri", "").strip()

    if not client_id:
        return jsonify({"ok": False, "error": "Client ID is required to start Yoto login."}), 400

    # Yoto Developer Dashboard strictly enforces HTTPS for all URLs except loopback (127.0.0.1 / localhost).
    if not redirect_uri:
        host_url = request.host_url.rstrip("/")
        if host_url.startswith("https://") or "127.0.0.1" in host_url or "localhost" in host_url:
            redirect_uri = host_url + "/s/yoto-callback"
        else:
            redirect_uri = "http://127.0.0.1:8787/callback"

    # Generate 32 bytes entropy PKCE pair
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    state = secrets.token_hex(16)

    # Cache flow with 10-minute expiry
    expires_at = time.time() + 600
    YOTO_PKCE_FLOWS[state] = {
        "client_id": client_id,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "expires_at": expires_at
    }

    # Prune expired flows
    for s in list(YOTO_PKCE_FLOWS.keys()):
        if YOTO_PKCE_FLOWS[s]["expires_at"] < time.time():
            YOTO_PKCE_FLOWS.pop(s, None)

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
        "redirect_uri": redirect_uri
    })


@yoto_oauth_bp.route("/api/admin/yoto/oauth/finish", methods=["POST"])
@require_admin
def admin_yoto_oauth_finish():
    """Exchanges an authorization code or redirect landing URL for tokens and saves to SQLite."""
    data = request.get_json(silent=True) or {}
    url_or_code = data.get("url_or_code", "").strip()
    state = data.get("state", "").strip()

    code = url_or_code
    if "code=" in url_or_code:
        parsed = urllib.parse.urlparse(url_or_code)
        q = urllib.parse.parse_qs(parsed.query)
        code = q.get("code", [""])[0]
        if not state:
            state = q.get("state", [""])[0]

    if not code:
        return jsonify({"ok": False, "error": "No authorization code found in submission."}), 400

    flow = YOTO_PKCE_FLOWS.get(state)
    if not flow:
        if len(YOTO_PKCE_FLOWS) == 1:
            flow = next(iter(YOTO_PKCE_FLOWS.values()))
        else:
            return jsonify({"ok": False, "error": "OAuth session expired or state mismatch. Please click 'Connect Yoto' again."}), 400

    token_payload = {
        "grant_type": "authorization_code",
        "client_id": flow["client_id"],
        "code_verifier": flow["verifier"],
        "code": code,
        "redirect_uri": flow["redirect_uri"]
    }

    try:
        res = requests.post("https://login.yotoplay.com/oauth/token", json=token_payload, timeout=15)
        if res.status_code == 200:
            token_data = res.json()
            refresh_token = token_data.get("refresh_token")
            access_token = token_data.get("access_token")

            if not refresh_token:
                return jsonify({"ok": False, "error": "Yoto did not return a refresh token. Ensure 'offline_access' scope is enabled in dashboard.yoto.dev."}), 400

            # Update database
            database.update_api_credentials({
                "yoto_client_id": flow["client_id"],
                "yoto_refresh_token": refresh_token
            })

            # Reload client singletons
            clients.reload_clients()
            if clients.yoto_client:
                clients.yoto_client.access_token = access_token
                clients.yoto_client.expires_at = time.time() + token_data.get("expires_in", 3600)

            # Cleanup flow
            YOTO_PKCE_FLOWS.pop(state, None)
            return jsonify({
                "ok": True,
                "message": "Yoto connected successfully! Refresh token saved and client activated."
            })
        else:
            logger.error("Yoto token exchange failed: %d %s", res.status_code, res.text)
            return jsonify({"ok": False, "error": f"Token exchange failed ({res.status_code}): {res.text}"}), 502
    except Exception as e:
        logger.error("Exception during OAuth finish: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@yoto_oauth_bp.route("/s/yoto-callback", methods=["GET"])
def yoto_callback_landing():
    """Universal browser landing page for in-browser Yoto OAuth callbacks."""
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")
    error_desc = request.args.get("error_description", "")

    if error:
        return f"""<!doctype html>
        <html><body style="font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 60px;">
        <h2 style="color: #ef4444;">&#10008; Yoto Login Denied</h2>
        <p>{html.escape(error_desc or error)}</p>
        <p><a href="/admin" style="color: #38bdf8;">Return to Admin Portal</a></p>
        </body></html>""", 400

    return f"""<!doctype html>
    <html>
    <head><meta charset="utf-8"><title>Yoto Connected</title></head>
    <body style="font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 60px;">
        <h2 style="color: #22c55e;">&#10004; Yoto Authorization Successful!</h2>
        <p>Your browser received the authorization code from Yoto.</p>
        <div style="margin: 30px auto; max-width: 480px; background: #1e293b; padding: 20px; border-radius: 8px; border: 1px solid #334155;">
            <p style="margin-bottom: 12px; font-size: 14px; color: #94a3b8;">Copy this entire address bar URL or the code below back into your Admin Portal:</p>
            <input type="text" readonly value="{html.escape(code)}" style="width: 100%; padding: 10px; background: #0f172a; color: #38bdf8; border: 1px solid #475569; border-radius: 6px; font-family: monospace; font-size: 14px; text-align: center;">
        </div>
        <p><a href="/admin" style="display: inline-block; background: #f97316; color: #fff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold;">Return to Admin Portal</a></p>
        <script>
            if (window.opener && !window.opener.closed) {{
                try {{
                    window.opener.postMessage({{ type: "YOTO_AUTH_CALLBACK", code: "{code}", state: "{state}" }}, "*");
                    setTimeout(() => window.close(), 1500);
                }} catch (e) {{}}
            }}
        </script>
    </body>
    </html>"""
