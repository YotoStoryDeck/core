"""
Authentication decorators, master API key verification, and per-device JWT helpers.
"""

import hmac
import hashlib
import base64
import json
import time
import ipaddress
from typing import Dict, Any, Optional, Tuple
from flask import request, jsonify, session, redirect
import database
from core.config import TRUSTED_PROXIES, logger


# ============================================================================
# Compact Pure-Python JWT Engine (HS256)
# ============================================================================

def _b64url_encode(data: bytes) -> str:
    """Encodes bytes into URL-safe base64 without '=' padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    """Decodes URL-safe base64 string, restoring missing '=' padding."""
    pad_len = 4 - (len(data) % 4)
    if pad_len and pad_len < 4:
        data += "=" * pad_len
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def create_device_jwt(mac: str, profile_id: str, secret: str, token_version: int, token_type: str = "access", expires_in: int = 86400) -> str:
    """
    Creates an HS256-signed JWT token tailored for ESP32 microcontroller RAM.
    Access token expires in 24 hours (86400s).
    Refresh token expires in 30 days (2592000s).
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": f"esp32_{mac.lower().strip()}",
        "mac": mac.lower().strip(),
        "prof": profile_id or "",
        "ver": int(token_version or 1),
        "type": token_type,
        "iat": now,
        "exp": now + expires_in
    }

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    unsigned_token = f"{_b64url_encode(header_bytes)}.{_b64url_encode(payload_bytes)}"
    sig = hmac.new(secret.encode("utf-8"), unsigned_token.encode("utf-8"), hashlib.sha256).digest()
    return f"{unsigned_token}.{_b64url_encode(sig)}"


def decode_and_verify_device_jwt(token: str, secret: str) -> Optional[Dict[str, Any]]:
    """
    Validates HS256 signature, expiry, and payload format of a device token.
    Returns claims dictionary if valid, None if invalid or expired.
    """
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if "exp" in payload and time.time() > payload["exp"]:
            return None

        return payload
    except Exception as e:
        logger.debug("Device JWT decode/verify error: %s", e)
        return None


# ============================================================================
# Admin User & Master API Key Resolution
# ============================================================================


def is_trusted_lan_ip(remote_ip: str) -> bool:
    """Returns True if the client IP belongs to RFC1918 private subnets or loopback."""
    if not remote_ip:
        return False
    try:
        ip = ipaddress.ip_address(remote_ip.strip())
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def get_effective_client_ip() -> str:
    """Extracts real client IP considering reverse proxy headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"

def is_request_from_trusted_proxy() -> bool:
    """Checks whether the direct remote IP matches TRUSTED_PROXIES."""
    remote_addr = request.remote_addr or "127.0.0.1"
    try:
        remote_ip = ipaddress.ip_address(remote_addr)
        for net in TRUSTED_PROXIES:
            if remote_ip in net:
                return True
    except Exception:
        pass
    return False


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Retrieves the currently authenticated user identity.
    Checks in order:
    1. Master API Key (Role: admin)
    2. Reverse-Proxy SSO Headers (Role: looked up in DB or defaults to admin)
    3. Authenticated Session Cookie (Role: member or admin)
    4. Trusted LAN / Sitter Access Bypass (Role: member, is_lan_guest: True)
    """
    # 1. Master API Key Check
    req_key = request.headers.get("X-Api-Key") or request.headers.get("X-API-KEY")
    if not req_key:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            bearer_val = auth_hdr[7:].strip()
            if len(bearer_val) == 32:
                req_key = bearer_val

    if not req_key and request.method == "GET":
        req_key = request.args.get("apikey") or request.args.get("api_key")

    if req_key:
        configured_master = database.get_master_api_key()
        if configured_master and hmac.compare_digest(req_key.strip(), configured_master.strip()):
            return {
                "id": "master_api_key",
                "username": "api_client",
                "display_name": "Master API Key",
                "role": "admin",
                "is_lan_guest": False,
                "auth_type": "api_key"
            }

    # 2. Reverse-Proxy SSO Headers (Authentik, Cloudflare Access)
    if is_request_from_trusted_proxy():
        sso_user = (
            request.headers.get("X-authentik-username") or
            request.headers.get("X-Forwarded-User") or
            request.headers.get("Remote-User") or
            request.headers.get("Cf-Access-Authenticated-User-Email")
        )
        if sso_user:
            user = database.get_user_by_username(sso_user.strip())
            if user:
                return {
                    "id": user["id"],
                    "username": user["username"],
                    "display_name": user["display_name"] or user["username"],
                    "role": user.get("role", "admin"),
                    "is_lan_guest": False,
                    "auth_type": "sso"
                }
            return {
                "id": f"sso_{sso_user.strip()}",
                "username": sso_user.strip(),
                "display_name": sso_user.strip(),
                "role": "admin",
                "is_lan_guest": False,
                "auth_type": "sso"
            }

    # 3. Local Session Cookie
    user_id = session.get("user_id")
    if user_id:
        db_user = database.get_user_by_id(user_id)
        if db_user:
            return {
                "id": db_user["id"],
                "username": db_user["username"],
                "display_name": db_user["display_name"] or db_user["username"],
                "role": db_user.get("role", "member"),
                "is_lan_guest": False,
                "auth_type": "session"
            }
        return {
            "id": user_id,
            "username": session.get("username", "user"),
            "display_name": session.get("display_name", "User"),
            "role": session.get("role", "member"),
            "is_lan_guest": False,
            "auth_type": "session"
        }

    # 4. Trusted LAN / Sitter Access Bypass
    try:
        settings = database.get_system_settings()
        if settings.get("lan_sitter_access_enabled", True):
            client_ip = get_effective_client_ip()
            if is_trusted_lan_ip(client_ip):
                return {
                    "id": "lan_guest",
                    "username": "lan_guest",
                    "display_name": "LAN Guest (Sitter)",
                    "role": "member",
                    "is_lan_guest": True,
                    "auth_type": "lan_guest"
                }
    except Exception as e:
        logger.debug("LAN guest check notice: %s", e)

    return None


def get_current_admin_user() -> Optional[Dict[str, Any]]:
    """
    Resolves active administrator identity.
    Strictly enforces role == 'admin' and NEVER allows LAN guest bypass.
    """
    # 1. Master API Key Check
    req_key = request.headers.get("X-Api-Key") or request.headers.get("X-API-KEY")
    if not req_key:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            bearer_val = auth_hdr[7:].strip()
            if len(bearer_val) == 32:
                req_key = bearer_val

    if not req_key and request.method == "GET":
        req_key = request.args.get("apikey") or request.args.get("api_key")

    if req_key:
        configured_master = database.get_master_api_key()
        if configured_master and hmac.compare_digest(req_key.strip(), configured_master.strip()):
            return {
                "id": "master_api_key",
                "username": "api_client",
                "display_name": "Master API Key",
                "role": "admin",
                "is_lan_guest": False,
                "auth_type": "api_key"
            }

    # 2. Reverse-Proxy SSO Headers (Authentik, Cloudflare Access)
    if is_request_from_trusted_proxy():
        sso_user = (
            request.headers.get("X-authentik-username") or
            request.headers.get("X-Forwarded-User") or
            request.headers.get("Remote-User") or
            request.headers.get("Cf-Access-Authenticated-User-Email")
        )
        if sso_user:
            user = database.get_user_by_username(sso_user.strip())
            if user and user.get("role") == "admin":
                return {
                    "id": user["id"],
                    "username": user["username"],
                    "display_name": user["display_name"] or user["username"],
                    "role": "admin",
                    "is_lan_guest": False,
                    "auth_type": "sso"
                }
            elif not user:
                return {
                    "id": f"sso_{sso_user.strip()}",
                    "username": sso_user.strip(),
                    "display_name": sso_user.strip(),
                    "role": "admin",
                    "is_lan_guest": False,
                    "auth_type": "sso"
                }

    # 3. Local Session Cookie (Must have role == 'admin')
    user_id = session.get("user_id")
    if user_id:
        db_user = database.get_user_by_id(user_id)
        if db_user and db_user.get("role") == "admin":
            return {
                "id": db_user["id"],
                "username": db_user["username"],
                "display_name": db_user["display_name"] or db_user["username"],
                "role": "admin",
                "is_lan_guest": False,
                "auth_type": "session"
            }
        elif not db_user and session.get("role") == "admin":
            return {
                "id": user_id,
                "username": session.get("username", "admin"),
                "display_name": session.get("display_name", "Admin"),
                "role": "admin",
                "is_lan_guest": False,
                "auth_type": "session"
            }

    return None


def require_auth(func):
    """
    Decorator guarding member and parent portal endpoints.
    Allows authenticated users (members/admins) OR local LAN guests.
    """
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Authentication required"}), 401
            return redirect(f"/admin/login?next={request.path}")
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


def require_admin(func):
    """
    Decorator strictly guarding admin endpoints.
    Requires role == 'admin'; LAN guest bypass is NEVER permitted.
    Returns 401 if unauthenticated or LAN guest, 403 if signed in as a non-admin member.
    """
    def wrapper(*args, **kwargs):
        admin = get_current_admin_user()
        if not admin:
            if request.path.startswith("/api/"):
                user = get_current_user()
                if user and not user.get("is_lan_guest"):
                    return jsonify({"ok": False, "error": "Admin privileges required"}), 403
                return jsonify({"ok": False, "error": "Unauthorized"}), 401
            return redirect(f"/admin/login?next={request.path}")
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ============================================================================
# ESP32 Controller JWT Verification Gate
# ============================================================================

def get_current_device() -> Optional[Dict[str, Any]]:
    """
    Validates per-device JWT from Authorization: Bearer <token>.
    Ensures device is approved and token_version matches active SQLite record.
    """
    auth_hdr = request.headers.get("Authorization", "")
    token = None
    if auth_hdr.startswith("Bearer "):
        token = auth_hdr[7:].strip()
    elif request.method == "GET" and request.args.get("token"):
        token = request.args.get("token")

    if not token or len(token) < 20:
        return None

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        mac = payload.get("mac")
        if not mac:
            sub = payload.get("sub", "")
            if sub.startswith("esp32_"):
                mac = sub[6:]

        if not mac:
            return None

        device = database.get_esp32_device(mac)
        if not device or not device.get("is_approved"):
            return None

        # Verify token_version matches active database state (immediate revocation check)
        dev_ver = int(device.get("token_version") or 1)
        if int(payload.get("ver", -1)) != dev_ver:
            return None

        secret = device.get("jwt_secret")
        if not secret:
            return None

        verified = decode_and_verify_device_jwt(token, secret)
        if not verified or verified.get("type") != "access":
            return None

        return {
            "mac_address": mac,
            "device": device,
            "profile_id": verified.get("prof") or device.get("assigned_profile_id")
        }
    except Exception as e:
        logger.debug("Device validation failed: %s", e)
        return None


def require_device_jwt(func):
    """Decorator guarding microcontroller routes, requiring a valid device access token."""
    def wrapper(*args, **kwargs):
        dev = get_current_device()
        if not dev:
            # Check if admin session or API key is being used for development/testing
            admin = get_current_admin_user()
            if admin:
                return func(*args, **kwargs)
            return jsonify({"ok": False, "error": "device_revoked", "message": "Valid ESP32 device token required"}), 403
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

