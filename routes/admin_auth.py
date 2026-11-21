"""
Administrator authentication and session management blueprint.
"""

import ipaddress
import secrets
from flask import Blueprint, request, jsonify, render_template, session
import database
from core.config import TRUSTED_PROXIES
from core.auth import get_current_admin_user, get_current_user, require_admin, require_auth

admin_auth_bp = Blueprint("admin_auth", __name__)


def _sso_public_meta() -> dict:
    """Returns non-secret SSO configuration metadata safe for auth status responses."""
    sso_cfg = database.get_sso_config()
    return {
        "provider_name": sso_cfg.get("provider_name") or "Authentik",
        "forward_auth_enabled": bool(sso_cfg.get("forward_auth_enabled", True)),
        "oidc_enabled": bool(sso_cfg.get("oidc_enabled", False)),
        "logout_url": sso_cfg.get("logout_url") or "",
    }


def _mask_sso_config(sso_cfg: dict) -> dict:
    """Returns a copy of sso_config with secrets masked for admin API display."""
    masked = dict(sso_cfg)
    secret = str(masked.get("oidc_client_secret") or "")
    if secret:
        masked["oidc_client_secret"] = (secret[:4] + "••••••••" + secret[-4:]) if len(secret) > 8 else "••••••••"
    return masked


@admin_auth_bp.route("/admin", methods=["GET"])
@admin_auth_bp.route("/admin/setup", methods=["GET"])
@admin_auth_bp.route("/admin/login", methods=["GET"])
def admin_portal_page():
    """Serves the single-page application for the admin dashboard."""
    return render_template("admin.html")


@admin_auth_bp.route("/api/admin/auth/status", methods=["GET"])
def admin_auth_status():
    """Checks whether initial admin onboarding is needed and reports active session identity."""
    user_count = database.get_admin_user_count()
    sso_meta = _sso_public_meta()
    if user_count == 0:
        return jsonify({
            "setup_required": True,
            "authenticated": False,
            "user": None,
            "sso": sso_meta
        })

    user = get_current_admin_user()
    return jsonify({
        "setup_required": False,
        "authenticated": bool(user),
        "user": user,
        "sso": sso_meta
    })


@admin_auth_bp.route("/api/admin/auth/setup", methods=["POST"])
def admin_auth_setup():
    """Initial administrator account creation (only allowed when 0 accounts exist)."""
    if database.get_admin_user_count() > 0:
        return jsonify({"ok": False, "error": "Setup is permanently locked."}), 403

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "Parent").strip()

    if not username or len(password) < 8:
        return jsonify({"ok": False, "error": "Username required, and password must be at least 8 characters."}), 400

    new_user = database.create_admin_user(username, password, display_name=display_name, role="admin", is_super_admin=True)
    return jsonify({"ok": True, "message": "Initial administrator account created.", "user": new_user}), 201


@admin_auth_bp.route("/api/admin/auth/login", methods=["POST"])
def admin_auth_login():
    """Authenticates admin credentials and issues an HTTP-only session cookie."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = database.authenticate_user(username, password)
    if not user:
        return jsonify({"ok": False, "error": "Invalid username or password"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user["display_name"]
    session["role"] = user["role"]
    session["is_super_admin"] = bool(user.get("is_super_admin", False))

    return jsonify({"ok": True, "message": "Signed in successfully.", "user": user})


@admin_auth_bp.route("/api/admin/auth/logout", methods=["POST"])
def admin_auth_logout():
    """Terminates session."""
    session.clear()
    return jsonify({"ok": True, "message": "Signed out."})


# ============================================================================
# User Identity & RBAC User Management Endpoints
# ============================================================================

@admin_auth_bp.route("/api/auth/me", methods=["GET"])
def auth_me():
    """Returns the identity and role of the currently connected user (admin, member, or LAN guest)."""
    user = get_current_user()
    if not user:
        return jsonify({"authenticated": False, "user": None}), 200
    return jsonify({
        "authenticated": True,
        "user": user
    }), 200


@admin_auth_bp.route("/api/admin/users", methods=["GET"])
@require_admin
def list_users():
    """Lists all registered system user accounts with actor-scoped management permissions."""
    actor = get_current_admin_user() or {}
    actor_id = actor.get("id")
    actor_is_super = bool(actor.get("is_super_admin", False))

    users = database.list_admin_users()
    enriched = []
    for u in users:
        is_super = bool(u.get("is_super_admin", False))
        is_self = bool(actor_id and actor_id == u["id"])
        item = dict(u)
        item["is_super_admin"] = is_super
        item["is_self"] = is_self
        item["can_edit"] = (not is_super) or actor_is_super or is_self
        item["can_change_role"] = (not is_super) and (not is_self)
        item["can_delete"] = (not is_super) and (not is_self)
        enriched.append(item)

    return jsonify({
        "ok": True,
        "users": enriched,
        "current_user_id": actor_id,
        "current_is_super_admin": actor_is_super,
    }), 200


@admin_auth_bp.route("/api/admin/users", methods=["POST"])
@require_admin
def create_user():
    """Creates a new user account with specified role ('admin' or 'member') and optional SSO link."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or username or "User").strip()
    role = str(data.get("role") or "member").strip().lower()
    sso_provider = (data.get("sso_provider") or "").strip()

    if not username:
        return jsonify({"ok": False, "error": "Username is required."}), 400
    if sso_provider and not password:
        # Pre-linked SSO users authenticate via reverse proxy / IdP and receive a strong unusable local placeholder secret
        password = secrets.token_urlsafe(32)
    elif len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    if role not in ("admin", "member"):
        return jsonify({"ok": False, "error": "Role must be 'admin' or 'member'."}), 400

    existing = database.get_user_by_username(username)
    if existing:
        return jsonify({"ok": False, "error": f"Username '{username}' already exists."}), 409

    try:
        user = database.create_admin_user(
            username=username,
            password=password,
            display_name=display_name,
            role=role,
            sso_provider=sso_provider,
            is_super_admin=False
        )
        return jsonify({"ok": True, "message": f"User '{username}' created successfully.", "user": user}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_auth_bp.route("/api/admin/users/<user_id>", methods=["PUT"])
@require_admin
def update_user(user_id):
    """Updates user username, display name, role, SSO provider link, or password."""
    data = request.get_json(silent=True) or {}
    actor = get_current_admin_user() or {}
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({"ok": False, "error": "User not found."}), 404

    is_super_target = bool(user.get("is_super_admin", False))
    is_self = bool(actor.get("id") and actor.get("id") == user["id"])
    actor_is_super = bool(actor.get("is_super_admin", False))

    if is_super_target and not actor_is_super and not is_self:
        return jsonify({"ok": False, "error": "The primary Super Admin account cannot be modified by other administrators."}), 403

    # Validate role transitions before applying any partial mutations
    if "role" in data:
        role = str(data.get("role") or "").strip().lower()
        if role not in ("admin", "member"):
            return jsonify({"ok": False, "error": "Role must be 'admin' or 'member'."}), 400
        if is_super_target and role != "admin":
            return jsonify({"ok": False, "error": "The primary Super Admin account cannot be demoted from Admin."}), 400
        if is_self and role != "admin":
            return jsonify({"ok": False, "error": "You cannot demote your own active administrator account."}), 400

    # Validate username change before applying partial mutations
    if "username" in data:
        new_username = (data.get("username") or "").strip()
        if not new_username:
            return jsonify({"ok": False, "error": "Username cannot be empty."}), 400
        if new_username != user["username"]:
            existing = database.get_user_by_username(new_username)
            if existing and existing["id"] != user_id:
                return jsonify({"ok": False, "error": f"Username '{new_username}' already exists."}), 409

    # Validate password length before applying partial mutations
    if data.get("password"):
        new_pw = data.get("password")
        if len(new_pw) < 8:
            return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400

    if "username" in data:
        try:
            database.update_user_username(user_id, (data.get("username") or "").strip())
        except ValueError as ve:
            return jsonify({"ok": False, "error": str(ve)}), 409

    if "display_name" in data:
        database.update_user_display_name(user_id, (data.get("display_name") or "").strip())

    if "sso_provider" in data:
        database.update_user_sso_provider(user_id, str(data.get("sso_provider") or "").strip())

    if "role" in data:
        role = str(data.get("role") or "").strip().lower()
        try:
            database.update_user_role(user_id, role)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    if data.get("password"):
        database.update_user_password(user_id, data.get("password"))

    updated_user = database.get_user_by_id(user_id)
    if is_self and actor.get("auth_type") == "session" and updated_user:
        session["username"] = updated_user["username"]
        session["display_name"] = updated_user["display_name"]

    return jsonify({"ok": True, "message": "User updated successfully.", "user": updated_user}), 200


@admin_auth_bp.route("/api/admin/users/<user_id>", methods=["DELETE"])
@require_admin
def delete_user_route(user_id):
    """Deletes a user account, protecting the primary Super Admin, self-deletion, and the last admin."""
    actor = get_current_admin_user() or {}
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({"ok": False, "error": "User not found."}), 404

    is_super_target = bool(user.get("is_super_admin", False))
    is_self = bool(actor.get("id") and actor.get("id") == user["id"])
    actor_is_super = bool(actor.get("is_super_admin", False))

    if is_super_target:
        if not actor_is_super and not is_self:
            return jsonify({"ok": False, "error": "The primary Super Admin account cannot be deleted by other administrators."}), 403
        return jsonify({"ok": False, "error": "The primary Super Admin account cannot be deleted."}), 400

    if is_self:
        return jsonify({"ok": False, "error": "You cannot delete your own active account."}), 400

    try:
        success = database.delete_user(user_id)
        if not success:
            return jsonify({"ok": False, "error": "User not found."}), 404
        return jsonify({"ok": True, "message": "User deleted successfully."}), 200
    except ValueError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================================
# Access Policy & SSO / Authentik Configuration Endpoints
# ============================================================================

@admin_auth_bp.route("/api/admin/auth/sso-config", methods=["GET", "PUT"])
@require_admin
def admin_sso_config():
    """Gets or updates reverse-proxy SSO, Authentik header mapping, OIDC readiness, and LAN guest access."""
    admin_user = get_current_admin_user() or {}

    if request.method == "GET":
        settings = database.get_system_settings()
        sso_cfg = database.get_sso_config()
        return jsonify({
            "ok": True,
            "sso_config": _mask_sso_config(sso_cfg),
            "env_trusted_proxies": [str(n) for n in TRUSTED_PROXIES],
            "lan_sitter_access_enabled": bool(settings.get("lan_sitter_access_enabled", True)),
            "current_auth_type": admin_user.get("auth_type", "session"),
            "oidc_callback_path": "/api/auth/oidc/callback",
        }), 200

    data = request.get_json(silent=True) or {}
    if "lan_sitter_access_enabled" in data:
        database.set_system_setting("lan_sitter_access_enabled", bool(data.get("lan_sitter_access_enabled", True)))

    incoming_sso = data.get("sso_config") if isinstance(data.get("sso_config"), dict) else None
    if incoming_sso is None:
        sso_keys = set(database.DEFAULT_SSO_CONFIG.keys())
        flat_sso = {k: v for k, v in data.items() if k in sso_keys}
        incoming_sso = flat_sso if flat_sso else None

    if incoming_sso is not None:
        current_sso = database.get_sso_config()
        merged = dict(current_sso)

        for bool_key in ("forward_auth_enabled", "auto_provision_users", "oidc_enabled"):
            if bool_key in incoming_sso:
                merged[bool_key] = bool(incoming_sso.get(bool_key))

        for str_key in (
            "provider_name", "header_username", "header_display_name", "header_groups",
            "admin_group", "logout_url", "oidc_issuer_url", "oidc_client_id"
        ):
            if str_key in incoming_sso and incoming_sso.get(str_key) is not None:
                merged[str_key] = str(incoming_sso.get(str_key)).strip()

        if "default_role" in incoming_sso:
            role_val = str(incoming_sso.get("default_role") or "admin").strip().lower()
            if role_val not in ("admin", "member"):
                return jsonify({"ok": False, "error": "SSO default_role must be 'admin' or 'member'."}), 400
            merged["default_role"] = role_val

        if "extra_trusted_proxies" in incoming_sso:
            raw_proxies = incoming_sso.get("extra_trusted_proxies")
            if isinstance(raw_proxies, str):
                candidates = [p.strip() for p in raw_proxies.replace("\n", ",").split(",") if p.strip()]
            elif isinstance(raw_proxies, list):
                candidates = [str(p).strip() for p in raw_proxies if str(p).strip()]
            else:
                return jsonify({"ok": False, "error": "extra_trusted_proxies must be a list or comma-separated string."}), 400

            validated_proxies = []
            for entry in candidates:
                try:
                    ipaddress.ip_network(entry, strict=False)
                except ValueError:
                    try:
                        ipaddress.ip_network(f"{entry}/32", strict=False)
                    except ValueError:
                        return jsonify({"ok": False, "error": f"Invalid trusted proxy IP/CIDR: '{entry}'"}), 400
                validated_proxies.append(entry)
            merged["extra_trusted_proxies"] = validated_proxies

        if "oidc_client_secret" in incoming_sso:
            new_secret = str(incoming_sso.get("oidc_client_secret") or "").strip()
            if new_secret and "••••" not in new_secret:
                merged["oidc_client_secret"] = new_secret
            elif new_secret == "":
                merged["oidc_client_secret"] = ""

        database.set_system_setting("sso_config", merged)

    settings = database.get_system_settings()
    sso_cfg = database.get_sso_config()
    return jsonify({
        "ok": True,
        "message": "Access & SSO settings saved.",
        "sso_config": _mask_sso_config(sso_cfg),
        "env_trusted_proxies": [str(n) for n in TRUSTED_PROXIES],
        "lan_sitter_access_enabled": bool(settings.get("lan_sitter_access_enabled", True)),
        "current_auth_type": admin_user.get("auth_type", "session"),
        "oidc_callback_path": "/api/auth/oidc/callback",
    }), 200


@admin_auth_bp.route("/api/auth/oidc/callback", methods=["GET", "POST"])
def oidc_callback_placeholder():
    """Reserved OIDC Authorization Code callback route for future native OIDC support."""
    return jsonify({
        "ok": False,
        "error": "Native OIDC callback is reserved for future OIDC authorization code flow. Use Reverse-Proxy ForwardAuth (Authentik / NPM) for active SSO."
    }), 501
