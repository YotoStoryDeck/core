"""Admin User Authentication & PBKDF2 Password Hashing."""
import hashlib
import secrets
from typing import Dict, Any, List, Optional, Tuple

from .connection import get_db_connection, logger

_USER_PUBLIC_COLUMNS = (
    "id, username, display_name, email, role, sso_provider, sso_subject, "
    "is_super_admin, last_login, created_at"
)


def _normalize_user_row(row) -> Dict[str, Any]:
    """Converts a SQLite admin_users row into a typed dict with normalized strings and booleans."""
    d = dict(row)
    d["is_super_admin"] = bool(d.get("is_super_admin", 0))
    d["sso_provider"] = (d.get("sso_provider") or "").strip()
    d["sso_subject"] = (d.get("sso_subject") or "").strip()
    d["email"] = (d.get("email") or "").strip().lower()
    return d


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hashes a password with a cryptographic salt using PBKDF2-HMAC-SHA256."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations=100000
    )
    return key.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Verifies a password against the stored salt and hash."""
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, expected_hash)


def get_admin_user_count() -> int:
    """Returns total registered admin accounts (0 = setup wizard active)."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM admin_users;")
        return cur.fetchone()[0]
    finally:
        conn.close()


def create_admin_user(
    username: str,
    password: str,
    display_name: str = "Parent",
    role: str = "admin",
    sso_provider: str = "",
    email: str = "",
    sso_subject: str = "",
    is_super_admin: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Creates a new user record with salted hash and optional email / SSO subject binding.
    When is_super_admin is omitted (None), automatically promotes the first admin
    account to Super Admin; subsequent admins default to regular admins.
    """
    user_id = f"usr_{secrets.token_hex(6)}"
    clean_email = (email or "").strip().lower()
    clean_provider = (sso_provider or "").strip()
    clean_subject = (sso_subject or "").strip()
    pw_hash, salt = hash_password(password)
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            if is_super_admin is None:
                cur.execute("SELECT COUNT(*) FROM admin_users WHERE role = 'admin';")
                super_flag = 1 if (role == "admin" and cur.fetchone()[0] == 0) else 0
            else:
                super_flag = 1 if (is_super_admin and role == "admin") else 0

            conn.execute(
                """
                INSERT INTO admin_users (
                    id, username, password_hash, salt, display_name, email,
                    role, sso_provider, sso_subject, is_super_admin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    user_id, username, pw_hash, salt, display_name, clean_email,
                    role, clean_provider, clean_subject, super_flag
                )
            )
        return {
            "id": user_id,
            "username": username,
            "display_name": display_name,
            "email": clean_email,
            "role": role,
            "sso_provider": clean_provider,
            "sso_subject": clean_subject,
            "is_super_admin": bool(super_flag),
        }
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Validates username and password, updating last_login timestamp on success."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, salt, display_name, email, role, "
            "sso_provider, sso_subject, is_super_admin "
            "FROM admin_users WHERE username = ?;",
            (username,)
        )
        row = cur.fetchone()
        if not row:
            return None
        if verify_password(password, row["salt"], row["password_hash"]):
            with conn:
                conn.execute("UPDATE admin_users SET last_login = CURRENT_TIMESTAMP WHERE id = ?;", (row["id"],))
            return {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "email": (row["email"] or "").strip().lower(),
                "role": row["role"],
                "sso": bool(row["sso_provider"] or row["sso_subject"]),
                "sso_provider": (row["sso_provider"] or "").strip(),
                "sso_subject": (row["sso_subject"] or "").strip(),
                "is_super_admin": bool(row["is_super_admin"]),
            }
        return None
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Retrieves an admin or member user by exact username."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users WHERE username = ?;", (username,))
        row = cur.fetchone()
        return _normalize_user_row(row) if row else None
    finally:
        conn.close()


def get_user_by_username_ci(username: str) -> Optional[Dict[str, Any]]:
    """Retrieves a user by case-insensitive username for initial SSO bootstrap matching."""
    clean = (username or "").strip()
    if not clean:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users WHERE LOWER(username) = LOWER(?) LIMIT 1;", (clean,))
        row = cur.fetchone()
        return _normalize_user_row(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieves a user by case-insensitive non-empty email address."""
    clean = (email or "").strip().lower()
    if not clean:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users WHERE email != '' AND LOWER(email) = ? LIMIT 1;", (clean,))
        row = cur.fetchone()
        return _normalize_user_row(row) if row else None
    finally:
        conn.close()


def get_user_by_sso_subject(sso_subject: str, sso_provider: str = "") -> Optional[Dict[str, Any]]:
    """
    Retrieves a user strictly bound to an immutable SSO subject / UID (`sub` / `X-authentik-uid`).
    Checks provider-scoped match first, then unlabelled/generic 'sso' binding fallback.
    """
    clean_sub = (sso_subject or "").strip()
    clean_prov = (sso_provider or "").strip().lower()
    if not clean_sub:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if clean_prov:
            cur.execute(
                f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users "
                "WHERE sso_subject = ? AND LOWER(sso_provider) = ? LIMIT 1;",
                (clean_sub, clean_prov),
            )
            row = cur.fetchone()
            if row:
                return _normalize_user_row(row)
            cur.execute(
                f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users "
                "WHERE sso_subject = ? AND (sso_provider = '' OR LOWER(sso_provider) = 'sso') LIMIT 1;",
                (clean_sub,),
            )
            row = cur.fetchone()
            return _normalize_user_row(row) if row else None

        cur.execute(f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users WHERE sso_subject = ? LIMIT 1;", (clean_sub,))
        row = cur.fetchone()
        return _normalize_user_row(row) if row else None
    finally:
        conn.close()


def list_admin_users() -> List[Dict[str, Any]]:
    """Returns list of system users excluding password hashes."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users "
            "ORDER BY is_super_admin DESC, created_at ASC;"
        )
        return [_normalize_user_row(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves an admin or member user by user_id."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_PUBLIC_COLUMNS} FROM admin_users WHERE id = ?;", (user_id,))
        row = cur.fetchone()
        return _normalize_user_row(row) if row else None
    finally:
        conn.close()


def update_user_username(user_id: str, new_username: str) -> bool:
    """Updates username for a user record after verifying uniqueness."""
    clean = (new_username or "").strip()
    if not clean:
        raise ValueError("Username cannot be empty.")
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM admin_users WHERE username = ? AND id != ?;", (clean, user_id))
            if cur.fetchone():
                raise ValueError(f"Username '{clean}' already exists.")
            cur.execute("UPDATE admin_users SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (clean, user_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def update_user_email(user_id: str, email: str) -> bool:
    """Updates email address for a user record after checking uniqueness among non-empty emails."""
    clean = (email or "").strip().lower()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            if clean:
                cur.execute("SELECT id FROM admin_users WHERE email != '' AND LOWER(email) = ? AND id != ?;", (clean, user_id))
                if cur.fetchone():
                    raise ValueError(f"Email '{clean}' is already associated with another account.")
            cur.execute("UPDATE admin_users SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (clean, user_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def update_user_role(user_id: str, role: str) -> bool:
    """Updates the role for an admin user ('admin' or 'member'), protecting Super Admin & last admin."""
    if role not in ("admin", "member"):
        raise ValueError("Invalid role; must be 'admin' or 'member'")
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT role, is_super_admin FROM admin_users WHERE id = ?;", (user_id,))
            row = cur.fetchone()
            if not row:
                return False
            if row["is_super_admin"] and role != "admin":
                raise ValueError("The primary Super Admin account cannot be demoted from Admin.")
            if row["role"] == "admin" and role != "admin":
                cur.execute("SELECT COUNT(*) FROM admin_users WHERE role = 'admin';")
                if cur.fetchone()[0] <= 1:
                    raise ValueError("Cannot demote the last remaining administrator account.")
            cur.execute("UPDATE admin_users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (role, user_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def update_user_password(user_id: str, new_password: str) -> bool:
    """Updates password for a user record with salted hash."""
    if not new_password or len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    pw_hash, salt = hash_password(new_password)
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("UPDATE admin_users SET password_hash = ?, salt = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (pw_hash, salt, user_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def update_user_display_name(user_id: str, display_name: str) -> bool:
    """Updates display name for a user record."""
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("UPDATE admin_users SET display_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (display_name, user_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def update_user_sso_provider(user_id: str, sso_provider: str) -> bool:
    """Updates linked SSO provider identifier for a user record."""
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("UPDATE admin_users SET sso_provider = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (sso_provider.strip(), user_id))
            return cur.rowcount > 0
    finally:
        conn.close()


def update_user_sso_identity(user_id: str, sso_provider: str, sso_subject: str) -> bool:
    """Updates both SSO provider and immutable subject UID for a user record with uniqueness checks."""
    clean_prov = (sso_provider or "").strip()
    clean_sub = (sso_subject or "").strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            if clean_sub:
                cur.execute(
                    "SELECT id FROM admin_users WHERE sso_subject = ? AND LOWER(sso_provider) = LOWER(?) AND id != ?;",
                    (clean_sub, clean_prov, user_id)
                )
                if cur.fetchone():
                    raise ValueError(f"SSO Subject UID '{clean_sub}' is already linked to another account.")
            cur.execute(
                "UPDATE admin_users SET sso_provider = ?, sso_subject = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                (clean_prov, clean_sub, user_id)
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def bind_user_sso_subject(
    user_id: str,
    sso_provider: str,
    sso_subject: str,
    email: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Atomically binds an immutable SSO subject & provider onto an unbound local account
    (`sso_subject = ''`), optionally backfilling an empty email if unused elsewhere.
    """
    clean_prov = (sso_provider or "").strip().lower()
    clean_sub = (sso_subject or "").strip()
    clean_email = (email or "").strip().lower()
    if not clean_sub:
        return get_user_by_id(user_id)

    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE admin_users SET sso_provider = ?, sso_subject = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND (sso_subject IS NULL OR sso_subject = '');",
                (clean_prov, clean_sub, user_id),
            )
            if cur.rowcount > 0 and clean_email:
                cur.execute("SELECT email FROM admin_users WHERE id = ?;", (user_id,))
                row = cur.fetchone()
                if row and not (row["email"] or "").strip():
                    cur.execute(
                        "SELECT id FROM admin_users WHERE email != '' AND LOWER(email) = ? AND id != ?;",
                        (clean_email, user_id),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "UPDATE admin_users SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                            (clean_email, user_id),
                        )
    finally:
        conn.close()
    return get_user_by_id(user_id)


def delete_user(user_id: str) -> bool:
    """Deletes a user account (refuses to delete Super Admin or the last remaining admin)."""
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT role, is_super_admin FROM admin_users WHERE id = ?;", (user_id,))
            row = cur.fetchone()
            if not row:
                return False
            if row["is_super_admin"]:
                raise ValueError("The primary Super Admin account cannot be deleted.")
            if row["role"] == "admin":
                cur.execute("SELECT COUNT(*) FROM admin_users WHERE role = 'admin';")
                admin_count = cur.fetchone()[0]
                if admin_count <= 1:
                    raise ValueError("Cannot delete the last remaining administrator account.")
            cur.execute("DELETE FROM admin_users WHERE id = ?;", (user_id,))
            return cur.rowcount > 0
    finally:
        conn.close()
