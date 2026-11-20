"""
Administrator authentication and session management blueprint.
"""

from flask import Blueprint, request, jsonify, render_template, session
import database
from core.auth import get_current_admin_user, get_current_user, require_admin, require_auth

admin_auth_bp = Blueprint("admin_auth", __name__)


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
    if user_count == 0:
        return jsonify({
            "setup_required": True,
            "authenticated": False,
            "user": None
        })

    user = get_current_admin_user()
    return jsonify({
        "setup_required": False,
        "authenticated": bool(user),
        "user": user
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

    new_user = database.create_admin_user(username, password, display_name=display_name, role="admin")
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
    """Lists all registered system user accounts."""
    users = database.list_admin_users()
    return jsonify({"ok": True, "users": users}), 200


@admin_auth_bp.route("/api/admin/users", methods=["POST"])
@require_admin
def create_user():
    """Creates a new user account with specified role ('admin' or 'member')."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "User").strip()
    role = str(data.get("role") or "member").strip().lower()

    if not username:
        return jsonify({"ok": False, "error": "Username is required."}), 400
    if len(password) < 8:
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
            role=role
        )
        return jsonify({"ok": True, "message": f"User '{username}' created successfully.", "user": user}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_auth_bp.route("/api/admin/users/<user_id>", methods=["PUT"])
@require_admin
def update_user(user_id):
    """Updates user display name, role, or password."""
    data = request.get_json(silent=True) or {}
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({"ok": False, "error": "User not found."}), 404

    # Update display name
    if "display_name" in data:
        database.update_user_display_name(user_id, (data.get("display_name") or "").strip())

    # Update role
    if "role" in data:
        role = str(data.get("role") or "").strip().lower()
        if role not in ("admin", "member"):
            return jsonify({"ok": False, "error": "Role must be 'admin' or 'member'."}), 400
        try:
            database.update_user_role(user_id, role)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # Update password if provided
    if data.get("password"):
        new_pw = data.get("password")
        if len(new_pw) < 8:
            return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
        database.update_user_password(user_id, new_pw)

    updated_user = database.get_user_by_id(user_id)
    return jsonify({"ok": True, "message": "User updated successfully.", "user": updated_user}), 200


@admin_auth_bp.route("/api/admin/users/<user_id>", methods=["DELETE"])
@require_admin
def delete_user_route(user_id):
    """Deletes a user account, preventing deletion of the last admin."""
    try:
        success = database.delete_user(user_id)
        if not success:
            return jsonify({"ok": False, "error": "User not found."}), 404
        return jsonify({"ok": True, "message": "User deleted successfully."}), 200
    except ValueError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
