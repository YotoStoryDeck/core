"""Firmware Releases Repository DAO for Remote OTA Updates & Rollbacks (DLP-010)."""
from typing import Dict, Any, List, Optional

from .connection import get_db_connection


def _serialize_release(row) -> Dict[str, Any]:
    d = dict(row)
    d["is_active_latest"] = bool(d.get("is_active_latest", False))
    d["file_size_bytes"] = int(d.get("file_size_bytes") or 0)
    return d


def list_firmware_releases() -> List[Dict[str, Any]]:
    """Lists all cataloged firmware binary releases ordered with active latest first."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM firmware_releases ORDER BY is_active_latest DESC, created_at DESC, version DESC;")
        return [_serialize_release(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_firmware_release(version: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single firmware release record by semantic version string."""
    clean_ver = (version or "").strip()
    if not clean_ver:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM firmware_releases WHERE version = ?;", (clean_ver,))
        row = cur.fetchone()
        return _serialize_release(row) if row else None
    finally:
        conn.close()


def get_latest_firmware_release() -> Optional[Dict[str, Any]]:
    """Retrieves the active latest firmware release (falling back to newest uploaded)."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM firmware_releases ORDER BY is_active_latest DESC, created_at DESC, version DESC LIMIT 1;"
        )
        row = cur.fetchone()
        return _serialize_release(row) if row else None
    finally:
        conn.close()


def upsert_firmware_release(
    version: str,
    release_tag: str,
    file_path: str,
    file_size_bytes: int,
    sha256_hash: str,
    git_commit: str = "",
    release_notes: str = "",
    is_active_latest: bool = False,
) -> Dict[str, Any]:
    """Inserts or updates a cataloged firmware release in SQLite."""
    clean_ver = (version or "").strip()
    clean_tag = (release_tag or clean_ver).strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM firmware_releases;")
            existing_count = int(cur.fetchone()[0] or 0)
            make_latest = bool(is_active_latest) or (existing_count == 0)
            if make_latest:
                conn.execute("UPDATE firmware_releases SET is_active_latest = 0;")
            conn.execute(
                """
                INSERT INTO firmware_releases (
                    version, release_tag, file_path, file_size_bytes,
                    sha256_hash, git_commit, release_notes, is_active_latest
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version) DO UPDATE SET
                    release_tag = excluded.release_tag,
                    file_path = excluded.file_path,
                    file_size_bytes = excluded.file_size_bytes,
                    sha256_hash = excluded.sha256_hash,
                    git_commit = excluded.git_commit,
                    release_notes = excluded.release_notes,
                    is_active_latest = CASE
                        WHEN ? = 1 THEN 1
                        ELSE firmware_releases.is_active_latest
                    END;
                """,
                (
                    clean_ver,
                    clean_tag,
                    file_path,
                    int(file_size_bytes),
                    sha256_hash,
                    (git_commit or "").strip(),
                    release_notes or "",
                    1 if make_latest else 0,
                    1 if make_latest else 0,
                ),
            )
    finally:
        conn.close()
    return get_firmware_release(clean_ver) or {}


def set_active_latest_firmware(version: str) -> bool:
    """Marks a cataloged firmware version as the active latest release."""
    clean_ver = (version or "").strip()
    if not clean_ver:
        return False
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT version FROM firmware_releases WHERE version = ?;", (clean_ver,))
            if not cur.fetchone():
                return False
            conn.execute("UPDATE firmware_releases SET is_active_latest = 0;")
            conn.execute("UPDATE firmware_releases SET is_active_latest = 1 WHERE version = ?;", (clean_ver,))
        return True
    finally:
        conn.close()


def delete_firmware_release(version: str) -> Optional[Dict[str, Any]]:
    """Deletes a firmware release record, promoting the newest remaining release if needed."""
    clean_ver = (version or "").strip()
    if not clean_ver:
        return None
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM firmware_releases WHERE version = ?;", (clean_ver,))
            row = cur.fetchone()
            if not row:
                return None
            deleted = _serialize_release(row)
            conn.execute("DELETE FROM firmware_releases WHERE version = ?;", (clean_ver,))
            if deleted["is_active_latest"]:
                cur.execute("SELECT version FROM firmware_releases ORDER BY created_at DESC, version DESC LIMIT 1;")
                nxt = cur.fetchone()
                if nxt:
                    conn.execute("UPDATE firmware_releases SET is_active_latest = 1 WHERE version = ?;", (nxt["version"],))
            return deleted
    finally:
        conn.close()
