"""
Authentication decorators, master API key verification, and per-device JWT helpers.
"""

import hmac
import hashlib
import base64
import json
import re
import secrets
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

def _parse_proxy_networks(entries) -> list:
    """Parses IP/CIDR strings into ip_network objects, skipping invalid values."""
    nets = []
    for raw in entries or []:
        p = str(raw or "").strip()
        if not p:
            continue
        try:
            nets.append(ipaddress.ip_network(p, strict=False))
        except ValueError:
            try:
                nets.append(ipaddress.ip_network(f"{p}/32", strict=False))
            except ValueError:
                logger.debug("Ignoring invalid extra trusted proxy entry: %s", p)
    return nets


def is_request_from_trusted_proxy() -> bool:
    """Checks whether the direct remote IP matches env TRUSTED_PROXIES or DB extra_trusted_proxies."""
    remote_addr = request.remote_addr or "127.0.0.1"
    try:
        remote_ip = ipaddress.ip_address(remote_addr)
        all_nets = list(TRUSTED_PROXIES)
        try:
            sso_cfg = database.get_sso_config()
            all_nets.extend(_parse_proxy_networks(sso_cfg.get("extra_trusted_proxies", [])))
        except Exception as e:
            logger.debug("SSO extra trusted proxy lookup skipped: %s", e)
        for net in all_nets:
            if remote_ip in net:
                return True
    except ValueError as e:
        logger.debug("Invalid client IP '%s' during proxy validation: %s", remote_addr, e)
    except Exception as e:
        logger.warning("Unexpected error during trusted proxy check for '%s': %s", remote_addr, e)
    return False


def _first_header_value(*names: str) -> str:
    """Returns the first non-empty HTTP header value matching any candidate header name."""
    seen = set()
    for name in names:
        clean_name = str(name or "").strip()
        if not clean_name or clean_name.lower() in seen:
            continue
        seen.add(clean_name.lower())
        val = request.headers.get(clean_name)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _resolve_sso_identity(require_admin_role: bool = False) -> Optional[Dict[str, Any]]:
    """
    Resolves reverse-proxy SSO headers (Authentik / Authelia / Cloudflare Access)
    when ForwardAuth is enabled and request arrives from a trusted proxy.
    Supports group-based role mapping and optional user auto-provisioning.
    """
    try:
        sso_cfg = database.get_sso_config()
    except Exception:
        sso_cfg = {}

    if not sso_cfg.get("forward_auth_enabled", True):
        return None
    if not is_request_from_trusted_proxy():
        return None

    raw_subject = _first_header_value(
        sso_cfg.get("header_subject"),
        "X-authentik-uid",
        "X-Forwarded-Sub",
    )
    sso_username = _first_header_value(
        sso_cfg.get("header_username"),
        "X-authentik-username",
        "X-Forwarded-User",
        "Remote-User",
    )
    sso_email = _first_header_value(
        sso_cfg.get("header_email"),
        "X-authentik-email",
        "Remote-Email",
        "X-Forwarded-Email",
        "Cf-Access-Authenticated-User-Email",
    ).lower()

    # Use immutable UID when supplied; fall back to username/email for proxies like Authelia ForwardAuth
    sso_subject = raw_subject or sso_username or sso_email
    if not sso_subject:
        return None

    sso_display_name = _first_header_value(
        sso_cfg.get("header_display_name"),
        "X-authentik-name",
        "Remote-Name",
        "X-Forwarded-Name",
    ) or sso_username or sso_email or sso_subject

    groups_raw = _first_header_value(
        sso_cfg.get("header_groups"),
        "X-authentik-groups",
        "Remote-Groups",
        "X-Forwarded-Groups",
    )
    groups = {g.strip().lower() for g in re.split(r"[|,;]", groups_raw) if g.strip()} if groups_raw else set()

    provider_label = str(sso_cfg.get("provider_name") or "Authentik").strip() or "Authentik"
    provider_slug = provider_label.lower()

    # Step 1: Primary lookup strictly by immutable SSO Subject / UID
    db_user = database.get_user_by_sso_subject(sso_subject, provider_slug)

    # Step 2: Initial bootstrap match for unbound accounts (Email first, then Username)
    if not db_user and sso_cfg.get("auto_link_existing_users", True):
        cand = None
        if sso_email:
            email_match = database.get_user_by_email(sso_email)
            if email_match and not email_match.get("sso_subject"):
                cand = email_match
        if not cand and sso_username:
            uname_match = database.get_user_by_username_ci(sso_username)
            if uname_match and not uname_match.get("sso_subject"):
                cand = uname_match
        if cand:
            db_user = database.bind_user_sso_subject(
                cand["id"], provider_slug, sso_subject, email=sso_email
            )

    if db_user:
        role = str(db_user.get("role") or "member").strip().lower()
        uid = db_user["id"]
        uname = db_user.get("username") or sso_username or sso_email or sso_subject
        uemail = db_user.get("email") or sso_email
        dname = db_user.get("display_name") or sso_display_name
        is_super = bool(db_user.get("is_super_admin", False))
    else:
        admin_group = str(sso_cfg.get("admin_group") or "").strip().lower()
        if admin_group:
            role = "admin" if admin_group in groups else "member"
        else:
            default_role = str(sso_cfg.get("default_role") or "member").strip().lower()
            role = default_role if default_role in ("admin", "member") else "member"

        uid = f"sso_{sso_subject}"
        uname = sso_username or sso_email or sso_subject
        uemail = sso_email
        dname = sso_display_name
        is_super = False

        # Step 3: Auto-add unmatched SSO user with bound immutable UID
        if sso_cfg.get("auto_provision_users", True):
            base_username = (
                sso_username
                or (sso_email.split("@")[0] if "@" in sso_email else sso_email)
                or f"sso_{sso_subject[:12]}"
            )
            provision_username = base_username
            if database.get_user_by_username_ci(provision_username):
                sub_tag = re.sub(r"[^a-zA-Z0-9_-]", "", sso_subject)[:6] or secrets.token_hex(3)
                provision_username = f"{base_username}_{sub_tag}"
                while database.get_user_by_username_ci(provision_username):
                    provision_username = f"{base_username}_{secrets.token_hex(2)}"

            email_to_store = sso_email if (sso_email and not database.get_user_by_email(sso_email)) else ""
            try:
                created = database.create_admin_user(
                    username=provision_username,
                    password=secrets.token_urlsafe(32),
                    display_name=sso_display_name,
                    role=role,
                    sso_provider=provider_slug,
                    email=email_to_store,
                    sso_subject=sso_subject,
                    is_super_admin=False,
                )
                uid = created["id"]
                uname = created.get("username") or provision_username
                uemail = created.get("email") or email_to_store
                dname = created.get("display_name") or sso_display_name
                is_super = bool(created.get("is_super_admin", False))
            except Exception as e:
                logger.debug("SSO auto-provision skipped/raced for '%s': %s", sso_subject, e)
                existing = database.get_user_by_sso_subject(sso_subject, provider_slug)
                if existing:
                    uid = existing["id"]
                    uname = existing.get("username") or provision_username
                    uemail = existing.get("email") or sso_email
                    dname = existing.get("display_name") or sso_display_name
                    role = str(existing.get("role") or role).strip().lower()
                    is_super = bool(existing.get("is_super_admin", False))

    if require_admin_role and role != "admin":
        return None

    return {
        "id": uid,
        "username": uname,
        "display_name": dname,
        "email": uemail,
        "role": role,
        "is_super_admin": is_super,
        "is_lan_guest": False,
        "auth_type": "sso",
        "sso_provider": provider_label,
        "sso_subject": sso_subject,
    }


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Retrieves the currently authenticated user identity.
    Checks in order:
    1. Master API Key (Role: admin)
    2. Reverse-Proxy SSO Headers (Role: looked up in DB, mapped by group, or configured default)
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
                "is_super_admin": True,
                "is_lan_guest": False,
                "auth_type": "api_key"
            }

    # 2. Reverse-Proxy SSO Headers (Authentik, Authelia, Cloudflare Access)
    sso_identity = _resolve_sso_identity(require_admin_role=False)
    if sso_identity:
        return sso_identity

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
                "is_super_admin": bool(db_user.get("is_super_admin", False)),
                "is_lan_guest": False,
                "auth_type": "session"
            }
        return {
            "id": user_id,
            "username": session.get("username", "user"),
            "display_name": session.get("display_name", "User"),
            "role": session.get("role", "member"),
            "is_super_admin": bool(session.get("is_super_admin", False)),
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
                    "is_super_admin": False,
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
                "is_super_admin": True,
                "is_lan_guest": False,
                "auth_type": "api_key"
            }

    # 2. Reverse-Proxy SSO Headers (Authentik, Authelia, Cloudflare Access)
    sso_identity = _resolve_sso_identity(require_admin_role=False)
    if sso_identity:
        return sso_identity if sso_identity.get("role") == "admin" else None

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
                "is_super_admin": bool(db_user.get("is_super_admin", False)),
                "is_lan_guest": False,
                "auth_type": "session"
            }
        elif not db_user and session.get("role") == "admin":
            return {
                "id": user_id,
                "username": session.get("username", "admin"),
                "display_name": session.get("display_name", "Admin"),
                "role": "admin",
                "is_super_admin": bool(session.get("is_super_admin", False)),
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

