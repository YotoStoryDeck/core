"""Admin User Authentication & PBKDF2 Password Hashing."""
import hashlib
import secrets
import sqlite3
from typing import Dict, Any, List, Optional, Tuple

from .connection import get_db_connection, logger

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
# ============================================================================
# Legacy Config Migration
# ============================================================================

def get_admin_user_count() -> int:
    """Returns total registered admin accounts (0 = setup wizard active)."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM admin_users;")
        return cur.fetchone()[0]
    finally:
        conn.close()
def create_admin_user(username: str, password: str, display_name: str = "Parent", role: str = "admin", sso_provider: str = "") -> Dict[str, Any]:
    """Creates a new admin user record with salted hash."""
    user_id = f"usr_{secrets.token_hex(6)}"
    pw_hash, salt = hash_password(password)
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
            INSERT INTO admin_users (id, username, password_hash, salt, display_name, role, sso_provider)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (user_id, username, pw_hash, salt, display_name, role, sso_provider))
        return {"id": user_id, "username": username, "display_name": display_name, "role": role}
    finally:
        conn.close()
def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Validates username and password, updating last_login timestamp on success."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, password_hash, salt, display_name, role, sso_provider FROM admin_users WHERE username = ?;", (username,))
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
                "role": row["role"],
                "sso": bool(row["sso_provider"])
            }
        return None
    finally:
        conn.close()
def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Retrieves an admin user by username (for SSO lookup)."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, display_name, role, sso_provider FROM admin_users WHERE username = ?;", (username,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()
def list_admin_users() -> List[Dict[str, Any]]:
    """Returns list of admin users excluding password hashes."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, display_name, role, sso_provider, last_login, created_at FROM admin_users ORDER BY created_at ASC;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
# ============================================================================
# Profiles & Children DAO
# ============================================================================
