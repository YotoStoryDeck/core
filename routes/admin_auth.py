"""
Administrator authentication and session management blueprint.
"""

from flask import Blueprint, request, jsonify, render_template, session
import database
from core.auth import get_current_admin_user

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
