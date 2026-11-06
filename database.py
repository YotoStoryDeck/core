"""
==============================================================================
SQLITE PERSISTENCE & RELATIONAL DATA MODEL (WAL MODE)
==============================================================================
Manages /data/broker.db with Write-Ahead Logging (WAL) for high concurrency.
Provides data access methods for:
- Multi-user admin accounts and password hashing (PBKDF2-HMAC-SHA256)
- Child profiles (ABS tokens, library IDs, Yoto player bindings)
- Household media cache & permissions matrix
- Registered ESP32 hardware devices (quarantine & profile assignment)
- Shared curation rules & regex title patterns
- Firmware releases catalog & rollback tracking
- Legacy config.json bootstrap migration
==============================================================================
"""
import os
import json
import sqlite3
import hashlib
import secrets
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
logger = logging.getLogger("yoto_broker.database")
# Detect Docker container vs local host development
IS_DOCKER = os.path.exists("/.dockerenv") or (os.path.exists("/app") and os.path.isfile("/app/app.py"))
DB_DEFAULT = "/app/data/broker.db" if IS_DOCKER else str(Path(__file__).parent / "data" / "broker.db")
CONFIG_DEFAULT = "/app/data/config.json" if IS_DOCKER else str(Path(__file__).parent / "config.example.json")
DB_PATH = Path(os.getenv("DB_PATH", DB_DEFAULT))
LEGACY_CONFIG_PATH = Path(os.getenv("CONFIG_PATH", CONFIG_DEFAULT))
def get_db_connection() -> sqlite3.Connection:
    """Creates a new SQLite connection with WAL mode and row factory enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
def init_db():
    """Initializes SQLite tables and migrates legacy config.json if needed."""
    logger.info("Initializing SQLite database at %s", DB_PATH)
    conn = get_db_connection()
    try:
        with conn:
            # 0. Admin & User Accounts (Multi-User & SSO Support)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                role TEXT DEFAULT 'admin',
                sso_provider TEXT DEFAULT '',
                last_login DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            # 1. Child Profiles
            conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                abs_username TEXT DEFAULT '',
                abs_api_key TEXT DEFAULT '',
                abs_library_id TEXT DEFAULT '',
                abs_tag TEXT DEFAULT '',
                default_player_id TEXT DEFAULT '',
                player_ids TEXT DEFAULT '[]',
                avatar_url TEXT DEFAULT '',
                avatar_color TEXT DEFAULT '',
                avatar_initial TEXT DEFAULT '',
                inherit_shared BOOLEAN DEFAULT 1,
                hide_physical BOOLEAN DEFAULT 0,
                catalog_rotation_limit INTEGER DEFAULT 80,
                catalog_rotation_hour INTEGER DEFAULT 3,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            # 2. Household Media Items Cache (Yoto Cards & Audiobooks)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS media_items (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                cover_url TEXT DEFAULT '',
                is_highlight BOOLEAN DEFAULT 0,
                has_physical BOOLEAN DEFAULT 0,
                raw_metadata TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            # 3. Profile Media Permissions Matrix
            conn.execute("""
            CREATE TABLE IF NOT EXISTS profile_media_permissions (
                profile_id TEXT NOT NULL,
                media_id TEXT NOT NULL,
                permission TEXT CHECK(permission IN ('allowed', 'excluded')),
                PRIMARY KEY (profile_id, media_id),
                FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                FOREIGN KEY (media_id) REFERENCES media_items(id) ON DELETE CASCADE
            );
            """)
            # 4. Registered ESP32 Hardware Controllers
            conn.execute("""
            CREATE TABLE IF NOT EXISTS esp32_devices (
                mac_address TEXT PRIMARY KEY,
                friendly_name TEXT NOT NULL,
                assigned_profile_id TEXT,
                is_approved BOOLEAN DEFAULT 0,
                ip_address TEXT DEFAULT '',
                firmware_version TEXT DEFAULT '',
                target_firmware_version TEXT,
                ota_status TEXT DEFAULT 'idle',
                ota_progress INTEGER DEFAULT 0,
                ota_last_error TEXT DEFAULT '',
                previous_firmware_version TEXT DEFAULT '',
                jwt_secret TEXT DEFAULT '',
                token_version INTEGER DEFAULT 1,
                last_token_issued DATETIME,
                parent_pin TEXT DEFAULT '',
                lock_player BOOLEAN DEFAULT 0,
                locked_player_id TEXT DEFAULT '',
                settings_json TEXT DEFAULT '{}',
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assigned_profile_id) REFERENCES profiles(id) ON DELETE SET NULL
            );
            """)
            # 5. Shared Household Rules & Title Regexes
            conn.execute("""
            CREATE TABLE IF NOT EXISTS shared_rules (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS shared_regex_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_scope TEXT DEFAULT 'shared',
                pattern TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            # 6. System Settings
            conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            # 7. Firmware Releases Catalog
            conn.execute("""
            CREATE TABLE IF NOT EXISTS firmware_releases (
                version TEXT PRIMARY KEY,
                release_tag TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                sha256_hash TEXT NOT NULL,
                git_commit TEXT DEFAULT '',
                release_notes TEXT DEFAULT '',
                is_active_latest BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
        # Execute incremental schema migrations based on PRAGMA user_version
        run_schema_migrations(conn)
        # Check and migrate legacy config.json if database has 0 profiles
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM profiles;")
        if cursor.fetchone()[0] == 0:
            migrate_legacy_config(conn)
    except Exception as e:
        logger.critical("Database initialization failed: %s", e, exc_info=True)
        raise
    finally:
        conn.close()
# ============================================================================
# Schema Migrations Engine (PRAGMA user_version)
# ============================================================================
CURRENT_SCHEMA_VERSION = 6
def run_schema_migrations(conn: sqlite3.Connection):
    """
    Applies incremental database schema migrations sequentially using SQLite's
    built-in PRAGMA user_version. Ensures seamless database upgrades across
    Docker container rebuilds without manual database recreation or data loss.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA user_version;")
    version = cur.fetchone()[0]
    logger.info("Current SQLite schema version: %d (Target: %d)", version, CURRENT_SCHEMA_VERSION)
    # Version 0 -> 1: Base Relational Setup
    if version < 1:
        with conn:
            # Ensure indexes on frequently queried columns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_highlight ON media_items(is_highlight);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_media_type ON media_items(type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_permissions_prof ON profile_media_permissions(profile_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_approved ON esp32_devices(is_approved);")
            conn.execute("PRAGMA user_version = 1;")
        logger.info("Migrated SQLite schema to version 1.")
    # Version 1 -> 2: Add abs_username to profiles table
    if version < 2:
        with conn:
            # Check if column already exists before adding
            cur.execute("PRAGMA table_info(profiles);")
            columns = [c[1] for c in cur.fetchall()]
            if "abs_username" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN abs_username TEXT DEFAULT '';")
            conn.execute("PRAGMA user_version = 2;")
        logger.info("Migrated SQLite schema to version 2 (added abs_username to profiles).")
    # Version 2 -> 3: Add avatar_color and avatar_initial to profiles table
    if version < 3:
        with conn:
            cur.execute("PRAGMA table_info(profiles);")
            columns = [c[1] for c in cur.fetchall()]
            if "avatar_color" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN avatar_color TEXT DEFAULT '';")
            if "avatar_initial" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN avatar_initial TEXT DEFAULT '';")
            conn.execute("PRAGMA user_version = 3;")
        logger.info("Migrated SQLite schema to version 3 (added avatar_color, avatar_initial to profiles).")
    # Version 3 -> 4: Add JWT and security token columns to esp32_devices table and seed master_api_key
    if version < 4:
        with conn:
            cur.execute("PRAGMA table_info(esp32_devices);")
            dev_columns = [c[1] for c in cur.fetchall()]
            if "jwt_secret" not in dev_columns:
                conn.execute("ALTER TABLE esp32_devices ADD COLUMN jwt_secret TEXT DEFAULT '';")
            if "token_version" not in dev_columns:
                conn.execute("ALTER TABLE esp32_devices ADD COLUMN token_version INTEGER DEFAULT 1;")
            if "last_token_issued" not in dev_columns:
                conn.execute("ALTER TABLE esp32_devices ADD COLUMN last_token_issued DATETIME;")
            # Seed default master_api_key in system_settings if not present
            cur.execute("SELECT value FROM system_settings WHERE key = 'master_api_key';")
            if not cur.fetchone():
                init_key = secrets.token_hex(16)
                conn.execute("INSERT INTO system_settings (key, value) VALUES ('master_api_key', ?);", (json.dumps(init_key),))
                logger.info("Generated initial master_api_key.")
            conn.execute("PRAGMA user_version = 4;")
        logger.info("Migrated SQLite schema to version 4 (added JWT fields to esp32_devices, master_api_key).")
    # Version 4 -> 5: Add parent_pin column to esp32_devices table for OTA PIN reset
    if version < 5:
        with conn:
            cur.execute("PRAGMA table_info(esp32_devices);")
            dev_columns = [col[1] for col in cur.fetchall()]
            if "parent_pin" not in dev_columns:
                conn.execute("ALTER TABLE esp32_devices ADD COLUMN parent_pin TEXT DEFAULT '';")
            conn.execute("PRAGMA user_version = 5;")
        logger.info("Migrated SQLite schema to version 5 (added parent_pin to esp32_devices).")

    # Version 5 -> 6: Add lock_player, locked_player_id, and settings_json to esp32_devices table
    if version < 6:
        with conn:
            cur.execute("PRAGMA table_info(esp32_devices);")
            dev_columns = [col[1] for col in cur.fetchall()]
            if "lock_player" not in dev_columns:
                conn.execute("ALTER TABLE esp32_devices ADD COLUMN lock_player BOOLEAN DEFAULT 0;")
            if "locked_player_id" not in dev_columns:
                conn.execute("ALTER TABLE esp32_devices ADD COLUMN locked_player_id TEXT DEFAULT '';")
            if "settings_json" not in dev_columns:
                conn.execute("ALTER TABLE esp32_devices ADD COLUMN settings_json TEXT DEFAULT '{}';")
            conn.execute("PRAGMA user_version = 6;")
        logger.info("Migrated SQLite schema to version 6 (added lock_player, locked_player_id, settings_json to esp32_devices).")

    # Version 6 -> 7: Add has_physical column to media_items and curation rotation columns to profiles
    if version < 7:
        with conn:
            cur.execute("PRAGMA table_info(media_items);")
            m_columns = [col[1] for col in cur.fetchall()]
            if "has_physical" not in m_columns:
                conn.execute("ALTER TABLE media_items ADD COLUMN has_physical BOOLEAN DEFAULT 0;")
            cur.execute("PRAGMA table_info(profiles);")
            p_columns = [col[1] for col in cur.fetchall()]
            if "hide_physical" not in p_columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN hide_physical BOOLEAN DEFAULT 0;")
            if "catalog_rotation_limit" not in p_columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN catalog_rotation_limit INTEGER DEFAULT 80;")
            if "catalog_rotation_hour" not in p_columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN catalog_rotation_hour INTEGER DEFAULT 3;")
            conn.execute("PRAGMA user_version = 7;")
        logger.info("Migrated SQLite schema to version 7 (added has_physical to media_items, rotation columns to profiles).")
# ============================================================================
# Password Hashing & Security Helpers (PBKDF2-HMAC-SHA256)
# ============================================================================
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
def migrate_legacy_config(conn: sqlite3.Connection):
    """Imports profiles, shared rules, and settings from config.json if present."""
    if not LEGACY_CONFIG_PATH.exists():
        logger.info("No legacy config.json found to migrate.")
        return
    logger.info("Migrating legacy config from %s into SQLite...", LEGACY_CONFIG_PATH)
    try:
        with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        with conn:
            # Shared Rules
            shared = data.get("shared_yoto", {})
            conn.execute("INSERT OR REPLACE INTO shared_rules (key, value) VALUES (?, ?);", 
                         ("include_all", json.dumps(shared.get("include_all", False))))
            conn.execute("INSERT OR REPLACE INTO shared_rules (key, value) VALUES (?, ?);", 
                         ("include_myo_by_default", json.dumps(shared.get("include_myo_by_default", True))))
            
            # Shared Allowed Cards
            for card_id in shared.get("allowed_card_ids", []):
                conn.execute("""
                INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'yoto', ?);
                """, (card_id, f"Card {card_id}"))
            # Shared Regexes
            for pattern in shared.get("match_titles", []):
                conn.execute("""
                INSERT INTO shared_regex_patterns (target_scope, pattern) VALUES ('shared', ?);
                """, (pattern,))
            # Profiles
            profiles = data.get("profiles", data.get("children", {}))
            for prof_id, pcfg in profiles.items():
                display_name = pcfg.get("display_name", prof_id.capitalize())
                abs_key = pcfg.get("abs_api_key", "")
                abs_lib = pcfg.get("abs_library_id", "")
                abs_tag = pcfg.get("abs_tag", "")
                def_player = pcfg.get("default_player_id", "")
                player_ids = json.dumps(pcfg.get("player_ids", [def_player] if def_player else []))
                avatar = pcfg.get("avatar_url", "")
                inherit = 1 if pcfg.get("yoto", {}).get("inherit_shared", True) else 0
                conn.execute("""
                INSERT OR REPLACE INTO profiles 
                (id, display_name, abs_api_key, abs_library_id, abs_tag, default_player_id, player_ids, avatar_url, inherit_shared)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (prof_id, display_name, abs_key, abs_lib, abs_tag, def_player, player_ids, avatar, inherit))
                # Per-profile rules
                yoto_cfg = pcfg.get("yoto", {})
                for card_id in yoto_cfg.get("allowed_card_ids", []):
                    conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'yoto', ?);", (card_id, f"Card {card_id}"))
                    conn.execute("""
                    INSERT OR REPLACE INTO profile_media_permissions (profile_id, media_id, permission)
                    VALUES (?, ?, 'allowed');
                    """, (prof_id, card_id))
                for card_id in yoto_cfg.get("excluded_card_ids", []):
                    conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'yoto', ?);", (card_id, f"Card {card_id}"))
                    conn.execute("""
                    INSERT OR REPLACE INTO profile_media_permissions (profile_id, media_id, permission)
                    VALUES (?, ?, 'excluded');
                    """, (prof_id, card_id))
                for pat in yoto_cfg.get("match_titles", []):
                    conn.execute("""
                    INSERT INTO shared_regex_patterns (target_scope, pattern) VALUES (?, ?);
                    """, (prof_id, pat))
            # System Settings & Credentials
            settings = data.get("settings", {})
            for k, v in settings.items():
                conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?);", (k, json.dumps(v)))
            # Transfer upstream credentials from config.json if present
            creds_to_migrate = {
                "abs_base_url": data.get("abs_base_url") or settings.get("abs_base_url") or os.getenv("ABS_BASE_URL", "http://audiobookshelf:80"),
                "abs_api_key": data.get("abs_api_key") or settings.get("abs_api_key") or os.getenv("ABS_API_KEY", ""),
                "yoto_client_id": data.get("yoto_client_id") or settings.get("yoto_client_id") or os.getenv("YOTO_CLIENT_ID", ""),
                "yoto_client_secret": data.get("yoto_client_secret") or settings.get("yoto_client_secret") or os.getenv("YOTO_CLIENT_SECRET", ""),
                "yoto_refresh_token": data.get("yoto_refresh_token") or settings.get("yoto_refresh_token") or os.getenv("YOTO_REFRESH_TOKEN", ""),
                "yoto_bridge_url": data.get("yoto_bridge_url") or settings.get("yoto_bridge_url") or os.getenv("YOTO_BRIDGE_URL", "http://yoto-bridge:8080"),
                "gemini_api_key": data.get("gemini_api_key") or settings.get("gemini_api_key") or os.getenv("GEMINI_API_KEY", ""),
                "anthropic_api_key": data.get("anthropic_api_key") or settings.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY", ""),
                "openrouter_api_key": data.get("openrouter_api_key") or settings.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY", "")
            }
            for cred_k, cred_v in creds_to_migrate.items():
                if cred_v:
                    conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?);", 
                                 (cred_k, json.dumps(str(cred_v).strip())))
        logger.info("Successfully migrated legacy config.json into SQLite.")
    except Exception as e:
        logger.error("Failed to migrate config.json: %s", e)
# ============================================================================
# Admin User Authentication & Session DAO
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
def get_all_profiles() -> Dict[str, Any]:
    """Returns all profiles formatted for broker ingestion and ESP32 responses."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM profiles ORDER BY created_at ASC;")
        rows = cur.fetchall()
        result = {}
        for r in rows:
            prof_id = r["id"]
            # Fetch allowed/excluded cards
            cur.execute("SELECT media_id, permission FROM profile_media_permissions WHERE profile_id = ?;", (prof_id,))
            perms = cur.fetchall()
            allowed = [p["media_id"] for p in perms if p["permission"] == "allowed"]
            excluded = [p["media_id"] for p in perms if p["permission"] == "excluded"]
            # Fetch profile regexes
            cur.execute("SELECT pattern FROM shared_regex_patterns WHERE target_scope = ?;", (prof_id,))
            match_titles = [row["pattern"] for row in cur.fetchall()]
            player_ids = []
            try:
                player_ids = json.loads(r["player_ids"]) if r["player_ids"] else []
            except Exception:
                player_ids = []
            result[prof_id] = {
                "id": prof_id,
                "display_name": r["display_name"],
                "abs_username": r["abs_username"] if "abs_username" in r.keys() else "",
                "abs_api_key": r["abs_api_key"],
                "abs_library_id": r["abs_library_id"],
                "abs_tag": r["abs_tag"],
                "default_player_id": r["default_player_id"],
                "player_ids": player_ids,
                "avatar_url": r["avatar_url"],
                "avatar_color": r["avatar_color"] if "avatar_color" in r.keys() else "",
                "avatar_initial": r["avatar_initial"] if "avatar_initial" in r.keys() else "",
                "hide_physical": bool(r["hide_physical"]) if "hide_physical" in r.keys() else False,
                "catalog_rotation_limit": int(r["catalog_rotation_limit"]) if "catalog_rotation_limit" in r.keys() and r["catalog_rotation_limit"] is not None else 80,
                "catalog_rotation_hour": int(r["catalog_rotation_hour"]) if "catalog_rotation_hour" in r.keys() and r["catalog_rotation_hour"] is not None else 3,
                "yoto": {
                    "inherit_shared": bool(r["inherit_shared"]),
                    "allowed_card_ids": allowed,
                    "excluded_card_ids": excluded,
                    "match_titles": match_titles
                }
            }
        return result
    finally:
        conn.close()
def get_profile_by_id(profile_id: str) -> Optional[Dict[str, Any]]:
    """Returns single profile config."""
    profiles = get_all_profiles()
    return profiles.get(profile_id)
def upsert_profile(prof_id: str, data: Dict[str, Any]) -> bool:
    """Inserts or updates a child profile and its permission rules."""
    conn = get_db_connection()
    try:
        with conn:
            display_name = data.get("display_name", prof_id.capitalize())
            abs_username = data.get("abs_username", "")
            abs_api_key = data.get("abs_api_key", "")
            abs_library_id = data.get("abs_library_id", "")
            abs_tag = data.get("abs_tag", "")
            default_player_id = data.get("default_player_id", "")
            player_ids = json.dumps(data.get("player_ids", []))
            avatar_url = data.get("avatar_url", "")
            avatar_color = data.get("avatar_color", "")
            avatar_initial = data.get("avatar_initial", "")
            hide_phys = 1 if data.get("hide_physical", False) else 0
            rot_lim = int(data.get("catalog_rotation_limit", 80) or 80)
            rot_hr = int(data.get("catalog_rotation_hour", 3) if data.get("catalog_rotation_hour") is not None else 3)
            yoto = data.get("yoto", {})
            inherit = 1 if yoto.get("inherit_shared", True) else 0
            conn.execute("""
            INSERT INTO profiles (id, display_name, abs_username, abs_api_key, abs_library_id, abs_tag, default_player_id, player_ids, avatar_url, avatar_color, avatar_initial, inherit_shared, hide_physical, catalog_rotation_limit, catalog_rotation_hour, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                display_name = excluded.display_name,
                abs_username = excluded.abs_username,
                abs_api_key = excluded.abs_api_key,
                abs_library_id = excluded.abs_library_id,
                abs_tag = excluded.abs_tag,
                default_player_id = excluded.default_player_id,
                player_ids = excluded.player_ids,
                avatar_url = excluded.avatar_url,
                avatar_color = excluded.avatar_color,
                avatar_initial = excluded.avatar_initial,
                inherit_shared = excluded.inherit_shared,
                hide_physical = excluded.hide_physical,
                catalog_rotation_limit = excluded.catalog_rotation_limit,
                catalog_rotation_hour = excluded.catalog_rotation_hour,
                updated_at = CURRENT_TIMESTAMP;
            """, (prof_id, display_name, abs_username, abs_api_key, abs_library_id, abs_tag, default_player_id, player_ids, avatar_url, avatar_color, avatar_initial, inherit, hide_phys, rot_lim, rot_hr))
            # Reset & rebuild permissions
            conn.execute("DELETE FROM profile_media_permissions WHERE profile_id = ?;", (prof_id,))
            for card_id in yoto.get("allowed_card_ids", []):
                conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'yoto', ?);", (card_id, f"Card {card_id}"))
                conn.execute("INSERT INTO profile_media_permissions (profile_id, media_id, permission) VALUES (?, ?, 'allowed');", (prof_id, card_id))
            for card_id in yoto.get("excluded_card_ids", []):
                conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'yoto', ?);", (card_id, f"Card {card_id}"))
                conn.execute("INSERT INTO profile_media_permissions (profile_id, media_id, permission) VALUES (?, ?, 'excluded');", (prof_id, card_id))
            # Rebuild regexes
            conn.execute("DELETE FROM shared_regex_patterns WHERE target_scope = ?;", (prof_id,))
            for pat in yoto.get("match_titles", []):
                conn.execute("INSERT INTO shared_regex_patterns (target_scope, pattern) VALUES (?, ?);", (prof_id, pat))
        return True
    finally:
        conn.close()
def delete_profile(prof_id: str) -> bool:
    """Deletes a child profile and cascades permissions."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DELETE FROM profiles WHERE id = ?;", (prof_id,))
            conn.execute("DELETE FROM shared_regex_patterns WHERE target_scope = ?;", (prof_id,))
        return True
    finally:
        conn.close()
# ============================================================================
# Shared Household Curation Rules
# ============================================================================
def get_shared_rules() -> Dict[str, Any]:
    """Returns shared household Yoto curation rules."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM shared_rules;")
        rules = {r["key"]: json.loads(r["value"]) for r in cur.fetchall()}
        # Allowed media items (include both 'yoto' and 'yoto_myo'; per-profile exclusions are evaluated per profile in get_catalog_matrix)
        cur.execute("SELECT id FROM media_items WHERE type IN ('yoto', 'yoto_myo');")
        allowed = [r["id"] for r in cur.fetchall()]
        # Regexes
        cur.execute("SELECT pattern FROM shared_regex_patterns WHERE target_scope = 'shared';")
        match_titles = [r["pattern"] for r in cur.fetchall()]
        return {
            "include_all": rules.get("include_all", False),
            "include_myo_by_default": rules.get("include_myo_by_default", True),
            "allowed_card_ids": allowed,
            "match_titles": match_titles
        }
    finally:
        conn.close()
def set_shared_rule(key: str, value: Any):
    """Sets a shared rule key-value pair."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO shared_rules (key, value) VALUES (?, ?);", (key, json.dumps(value)))
    finally:
        conn.close()
# ============================================================================
# Registered ESP32 Hardware & Quarantine Management
# ============================================================================
def register_esp32_device(mac_address: str, friendly_name: str, ip_address: str, firmware_version: str) -> Dict[str, Any]:
    """Registers an ESP32 device upon boot handshake (quarantined by default if new)."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT mac_address, friendly_name, assigned_profile_id, is_approved FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
            existing = cur.fetchone()
            if existing:
                conn.execute("""
                UPDATE esp32_devices 
                SET ip_address = ?, firmware_version = ?, last_seen = CURRENT_TIMESTAMP
                WHERE mac_address = ?;
                """, (ip_address, firmware_version, mac_clean))
                return {
                    "mac_address": mac_clean,
                    "friendly_name": existing["friendly_name"],
                    "assigned_profile_id": existing["assigned_profile_id"],
                    "is_approved": bool(existing["is_approved"]),
                    "status": "updated"
                }
            else:
                conn.execute("""
                INSERT INTO esp32_devices (mac_address, friendly_name, ip_address, firmware_version, is_approved)
                VALUES (?, ?, ?, ?, 0);
                """, (mac_clean, friendly_name or f"ESP32 ({mac_clean[-5:]})", ip_address, firmware_version))
                return {
                    "mac_address": mac_clean,
                    "friendly_name": friendly_name or f"ESP32 ({mac_clean[-5:]})",
                    "assigned_profile_id": None,
                    "is_approved": False,
                    "status": "registered_quarantined"
                }
    finally:
        conn.close()
def get_esp32_device(mac_address: str) -> Optional[Dict[str, Any]]:
    """Retrieves device record by MAC address."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
def list_esp32_devices() -> List[Dict[str, Any]]:
    """Lists all registered devices for Admin Portal Hardware tab."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM esp32_devices ORDER BY last_seen DESC;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
def update_esp32_device(mac_address: str, updates: Dict[str, Any]) -> bool:
    """Updates device friendly name, assigned default profile, or approval state."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT mac_address FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
            if not cur.fetchone():
                return False
            fields = []
            values = []
            for k in [
                "friendly_name", "assigned_profile_id", "is_approved",
                "target_firmware_version", "ota_status", "ota_progress", "ota_last_error",
                "jwt_secret", "token_version", "last_token_issued", "parent_pin",
                "lock_player", "locked_player_id", "settings_json"
            ]:
                if k in updates:
                    fields.append(f"{k} = ?")
                    values.append(updates[k])
            if fields:
                values.append(mac_clean)
                query = f"UPDATE esp32_devices SET {', '.join(fields)}, last_seen = CURRENT_TIMESTAMP WHERE mac_address = ?;"
                conn.execute(query, tuple(values))
        return True
    finally:
        conn.close()
def revoke_esp32_device(mac_address: str) -> bool:
    """Instantly revokes device tokens, increments token_version, and places in quarantine."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT mac_address, token_version FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
            row = cur.fetchone()
            if not row:
                return False
            curr_ver = int(row["token_version"] or 1)
            conn.execute("""
                UPDATE esp32_devices
                SET token_version = ?, is_approved = 0, last_seen = CURRENT_TIMESTAMP
                WHERE mac_address = ?;
            """, (curr_ver + 1, mac_clean))
        return True
    finally:
        conn.close()
def delete_esp32_device(mac_address: str) -> bool:
    """Deletes device registration."""
    mac_clean = mac_address.lower().strip()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DELETE FROM esp32_devices WHERE mac_address = ?;", (mac_clean,))
        return True
    finally:
        conn.close()
def prune_stale_devices(hours: int = 48) -> int:
    """Purges unapproved or stale devices not seen in the last `hours`."""
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM esp32_devices
                WHERE is_approved = 0 AND last_seen < datetime('now', '-' || ? || ' hours');
            """, (hours,))
            return cur.rowcount
    finally:
        conn.close()
# ============================================================================
# Media Catalog & Highlights Matrix DAO
# ============================================================================
def upsert_media_items(items: List[Dict[str, Any]]) -> int:
    """Caches discovered Yoto cards or ABS books into media_items table, invalidating cached thumbnails whenever an item's cover changes."""
    conn = get_db_connection()
    count = 0
    changed_covers = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, type, cover_url FROM media_items;")
        existing_covers = {r["id"]: (r["type"], r["cover_url"] or "") for r in cur.fetchall()}
        with conn:
            for it in items:
                m_id = it.get("id")
                m_type = it.get("type", "yoto")
                title = it.get("title", "")
                author = it.get("author", "")
                cover = it.get("cover_url", it.get("thumb", "")) or ""
                is_hi = 1 if it.get("is_highlight", False) else 0
                raw = json.dumps(it.get("raw_metadata") or it)
                if m_id in existing_covers:
                    old_type, old_cover = existing_covers[m_id]
                    if old_cover and old_cover != cover:
                        changed_covers.append((m_id, old_type, old_cover))
                conn.execute("""
                INSERT INTO media_items (id, type, title, author, cover_url, is_highlight, raw_metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    title = excluded.title,
                    author = excluded.author,
                    cover_url = excluded.cover_url,
                    raw_metadata = excluded.raw_metadata,
                    updated_at = CURRENT_TIMESTAMP;
                """, (m_id, m_type, title, author, cover, is_hi, raw))
                count += 1
        if changed_covers:
            try:
                from core.image_resizer import invalidate_thumbnail
                for cid, ctype, old_c in changed_covers:
                    invalidate_thumbnail(f"abs_{cid}")
                    if old_c:
                        invalidate_thumbnail(f"yoto_{old_c}")
                logger.info("Invalidated cached thumbnails for %d updated media covers.", len(changed_covers))
            except Exception as e:
                logger.warning("Failed invalidating changed cover thumbnails: %s", e)
        return count
    finally:
        conn.close()

def get_media_item_by_id(media_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single cached media item from SQLite by ID."""
    if not media_id:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, type, title, author, cover_url, is_highlight, raw_metadata FROM media_items WHERE id = ?;", (media_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_catalog_matrix() -> Dict[str, Any]:
    """Returns complete media catalog with highlight flags and per-profile permissions."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM media_items;")
        media_rows = cur.fetchall()
        # Sort with same methodology as Controller: highlight first, then title ignoring leading articles (A, An, The)
        def _matrix_sort_key(r):
            t = (r["title"] or "").strip()
            clean_t = re.sub(r"^(the|a|an)\s+", "", t, flags=re.IGNORECASE).lower()
            return (not bool(r["is_highlight"]), clean_t)
        media_rows = sorted(media_rows, key=_matrix_sort_key)
        profiles = get_all_profiles()
        shared_rules = get_shared_rules()
        settings = get_system_settings()
        default_child_tags = [t.lower() for t in settings.get("abs_default_children_tags", ["Children"])]
        items = []
        for mr in media_rows:
            m_id = mr["id"]
            m_type = mr["type"]
            is_hi = bool(mr["is_highlight"])
            
            raw_data = {}
            try:
                raw_data = json.loads(mr["raw_metadata"]) if mr["raw_metadata"] else {}
            except Exception:
                raw_data = {}
            tags = raw_data.get("tags") or []
            library_id = raw_data.get("library_id") or ""
            series = raw_data.get("series") or ""
            series_order = raw_data.get("series_order") or ""
            series_list = raw_data.get("series_list") or []
            if not series_list and series:
                series_list = [{"name": series, "order": series_order}]
            profile_states = {}
            for pid, pcfg in profiles.items():
                yoto_rules = pcfg.get("yoto", {})
                allowed_ids = yoto_rules.get("allowed_card_ids", [])
                excluded_ids = yoto_rules.get("excluded_card_ids", [])
                if m_id in excluded_ids:
                    allowed = False
                    reason = "explicit_excluded"
                elif m_id in allowed_ids:
                    allowed = True
                    reason = "explicit_allowed"
                elif m_type == "abs":
                    # Check ABS user scoping
                    child_tag = (pcfg.get("abs_tag") or "").strip().lower()
                    abs_uname = (pcfg.get("abs_username") or "").strip().lower()
                    
                    item_tags_lower = [t.lower() for t in tags]
                    
                    if child_tag and child_tag in item_tags_lower:
                        allowed = True
                        reason = "abs_tag_match"
                    elif any(dt in item_tags_lower for dt in default_child_tags):
                        allowed = True
                        reason = "abs_account_permitted"
                    elif abs_uname and any(dt in item_tags_lower for dt in default_child_tags):
                        allowed = True
                        reason = "abs_account_permitted"
                    else:
                        allowed = False
                        reason = "abs_restricted"
                elif yoto_rules.get("inherit_shared", True) and shared_rules.get("include_all", False):
                    allowed = True
                    reason = "inherited_shared_all"
                elif yoto_rules.get("inherit_shared", True) and (m_id in shared_rules.get("allowed_card_ids", [])):
                    allowed = True
                    reason = "inherited_shared"
                elif yoto_rules.get("inherit_shared", True) and shared_rules.get("include_myo_by_default", True) and m_type == "yoto_myo":
                    allowed = True
                    reason = "inherited_myo_default"
                else:
                    allowed = False
                    reason = "default_not_shared"
                profile_states[pid] = {"allowed": allowed, "reason": reason}
            last_played_at = raw_data.get("lastPlayedAt") or raw_data.get("last_played") or ""
            items.append({
                "id": m_id,
                "type": m_type,
                "title": mr["title"],
                "author": mr["author"],
                "cover_url": mr["cover_url"],
                "is_highlight": is_hi,
                "has_physical": bool(mr["has_physical"]) if "has_physical" in mr.keys() else False,
                "last_played_at": last_played_at,
                "tags": tags,
                "library_id": library_id,
                "series": series,
                "series_order": series_order,
                "series_list": series_list,
                "profiles": profile_states
            })
        return {
            "items": items,
            "profiles": list(profiles.keys()),
            "shared_rules": shared_rules,
            "exclude_single_card_series": bool(settings.get("exclude_single_card_series", True))
        }
    finally:
        conn.close()
def prune_stale_media_items(valid_ids: List[str], media_types: List[str] = None) -> int:
    """Removes cached media_items of given types that are no longer present in upstream libraries, and deletes their cached cover/chapter images from disk."""
    if not valid_ids:
        return 0
    if media_types is None:
        media_types = ["abs", "yoto", "yoto_myo"]
    conn = get_db_connection()
    stale_rows = []
    removed_count = 0
    try:
        placeholders_types = ",".join("?" for _ in media_types)
        placeholders_ids = ",".join("?" for _ in valid_ids)
        params = list(media_types) + list(valid_ids)
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, type, cover_url FROM media_items WHERE type IN ({placeholders_types}) AND id NOT IN ({placeholders_ids});",
            params
        )
        stale_rows = [dict(r) for r in cur.fetchall()]
        if stale_rows:
            with conn:
                del_cur = conn.execute(
                    f"DELETE FROM media_items WHERE type IN ({placeholders_types}) AND id NOT IN ({placeholders_ids});",
                    params
                )
                removed_count = del_cur.rowcount
                conn.execute(
                    f"DELETE FROM profile_media_permissions WHERE media_id NOT IN (SELECT id FROM media_items);"
                )
    finally:
        conn.close()

    if stale_rows:
        try:
            from core.image_resizer import invalidate_thumbnail
            from core.config import CUSTOM_ICONS_DIR
            for sr in stale_rows:
                sid = sr.get("id") or ""
                scover = sr.get("cover_url") or ""
                if sid:
                    invalidate_thumbnail(f"abs_{sid}")
                    for ch_idx in range(150):
                        invalidate_thumbnail(f"abs_ch_{sid}_{ch_idx}")
                    for icon_file in CUSTOM_ICONS_DIR.glob(f"{sid}_*.png"):
                        try:
                            icon_file.unlink()
                        except Exception:
                            pass
                if scover:
                    invalidate_thumbnail(f"yoto_{scover}")
        except Exception as e:
            logger.warning("Error cleaning up cached images for pruned media items: %s", e)

    return removed_count
def get_catalog_items_for_profile(profile_key: str, media_type: str = "abs") -> List[Dict[str, Any]]:
    """
    Retrieves filtered media catalog items for a child profile directly from SQLite cache.
    Implements multi-tiered rotation curation:
    1. 'Last Played' Tier: Sorted directly to the top for instant one-touch resumption.
    2. 'Sticky Favorites' Tier: Parent-pinned highlights (is_highlight = 1).
    3. 'Discovery Rotation Pool': Deterministically rotated daily mix with Book #1 series prioritization
       and physical card down-weighting, capped at the configurable profile rotation limit (default 80).
    Returns microcontroller-optimized array matching the client response schema.
    """
    from datetime import datetime, timezone
    import hashlib

    matrix = get_catalog_matrix()
    items = matrix.get("items", [])
    profiles = get_all_profiles()
    pcfg = profiles.get(profile_key.lower(), {})
    hide_physical = bool(pcfg.get("hide_physical", False))
    rotation_limit = int(pcfg.get("catalog_rotation_limit", 80) or 80)
    if rotation_limit <= 0:
        rotation_limit = 80

    def _parse_seq(val, title):
        seq = None
        seq_disp = str(val).strip() if (val is not None and str(val).strip() != "") else None
        if seq_disp:
            m_lead = re.search(r"(\d+(?:\.\d+)?)", seq_disp)
            if m_lead:
                try:
                    seq = float(m_lead.group(1))
                except (ValueError, TypeError):
                    pass
        if seq is None and title:
            m_range = re.search(r"#\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?)", title, re.IGNORECASE)
            if m_range:
                seq_disp = re.sub(r"\s+", "", m_range.group(1) or m_range.group(2))
                m_lead = re.search(r"(\d+(?:\.\d+)?)", seq_disp)
                if m_lead:
                    try:
                        seq = float(m_lead.group(1))
                    except (ValueError, TypeError):
                        pass
            else:
                m_num = re.search(r"#\s*(\d+(?:\.\d+)?)|(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)", title, re.IGNORECASE)
                if m_num:
                    v = m_num.group(1) or m_num.group(2)
                    seq_disp = str(v).strip()
                    try:
                        seq = float(v)
                    except (ValueError, TypeError):
                        pass
        return seq, seq_disp

    allowed_entries = []
    for it in items:
        m_type = it.get("type")
        if media_type == "abs" and m_type != "abs":
            continue
        if media_type == "yoto" and not m_type.startswith("yoto"):
            continue
        if not it.get("profiles", {}).get(profile_key, {}).get("allowed"):
            continue

        has_phys = bool(it.get("has_physical", False))
        if hide_physical and has_phys:
            continue

        title = it.get("title") or ""
        primary_series = it.get("series") or ""
        raw_order = it.get("series_order") or ""
        raw_list = it.get("series_list") or []
        s_seq, s_seq_disp = _parse_seq(raw_order, title)
        series_list = []
        for s in raw_list:
            s_name = s.get("name") or ""
            s_ord = s.get("order") or s.get("sequence_display") or s.get("sequence") or raw_order
            sub_seq, sub_seq_disp = _parse_seq(s_ord, title)
            if s_name:
                series_list.append({
                    "name": s_name,
                    "sequence": sub_seq,
                    "sequence_display": sub_seq_disp
                })

        cover_url = it.get("cover_url") or ""
        cover_v = hashlib.sha256(cover_url.encode("utf-8")).hexdigest()[:8] if cover_url else "1"
        if media_type == "yoto":
            if cover_url and not cover_url.startswith("/api/thumb"):
                import urllib.parse
                thumb = f"/api/thumb?type=yoto&id={it.get('id', '')}&url={urllib.parse.quote(cover_url)}&v={cover_v}"
            elif not cover_url:
                thumb = f"/api/thumb?type=yoto&id={it.get('id', '')}&v={cover_v}"
            else:
                thumb = cover_url if "v=" in cover_url else f"{cover_url}{'&' if '?' in cover_url else '?'}v={cover_v}"
        else:
            base_t = cover_url or f"/api/thumb?type=abs&id={it.get('id', '')}"
            thumb = base_t if "v=" in base_t else f"{base_t}{'&' if '?' in base_t else '?'}v={cover_v}"

        entry = {
            "id": it.get("id"),
            "type": "abs" if m_type == "abs" else "yoto",
            "title": title,
            "author": it.get("author") or ("Unknown" if m_type == "abs" else "Yoto"),
            "thumb": thumb,
            "is_highlight": bool(it.get("is_highlight")),
            "has_physical": has_phys,
            "series": primary_series,
            "sequence": s_seq,
            "sequence_display": s_seq_disp,
            "series_list": series_list,
            "_last_played_at": it.get("last_played_at") or ""
        }
        if media_type == "yoto":
            entry["is_myo"] = (m_type == "yoto_myo")
            entry["groups"] = [s.get("name") for s in raw_list if s.get("name")]
        allowed_entries.append(entry)

    # Partition into tiers
    recent_items = []
    highlight_items = []
    pool_items = []

    for e in allowed_entries:
        lp = e.get("_last_played_at")
        if lp and str(lp).strip():
            recent_items.append(e)
        elif e.get("is_highlight"):
            highlight_items.append(e)
        else:
            pool_items.append(e)

    # Sort recent tier newest first (lexical sort on ISO timestamp descending)
    recent_items.sort(key=lambda x: str(x.get("_last_played_at") or ""), reverse=True)
    recent_tier = recent_items[:8]
    # Any overflow recent items move to pool
    pool_items.extend(recent_items[8:])

    # Sort highlight tier alphabetically ignoring articles
    def _clean_title(t):
        return re.sub(r"^(the|a|an)\s+", "", (t or "").strip(), flags=re.IGNORECASE).lower()

    highlight_items.sort(key=lambda x: _clean_title(x.get("title", "")))

    # Apply Series Book #1 Prioritization to pool_items
    series_map = {}
    for it in pool_items:
        s_name = (it.get("series") or "").strip().lower()
        if s_name:
            series_map.setdefault(s_name, []).append(it)

    # For each series, identify Book #1 (lowest sequence number >= 0.0 or lowest alphanumeric sequence_display)
    series_first_ids = set()
    for s_name, books in series_map.items():
        if len(books) == 1:
            series_first_ids.add(books[0]["id"])
            continue
        def _book_seq_key(b):
            sq = b.get("sequence")
            if sq is not None and sq >= 0.0:
                return (0, sq)
            disp = b.get("sequence_display") or ""
            return (1, disp.lower() if disp else "zzzz")
        sorted_books = sorted(books, key=_book_seq_key)
        series_first_ids.add(sorted_books[0]["id"])

    primary_pool = []
    deferred_pool = []
    for it in pool_items:
        s_name = (it.get("series") or "").strip().lower()
        if not s_name or it["id"] in series_first_ids:
            primary_pool.append(it)
        else:
            deferred_pool.append(it)

    # Deterministic daily shuffle on primary_pool with physical down-weighting
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seed_base = f"{profile_key.lower()}:{today_str}"

    for x in primary_pool:
        h = int(hashlib.sha256(f"{seed_base}:{x['id']}".encode()).hexdigest()[:8], 16)
        # Down-weight physical cards by placing them in a higher rank range
        weight_mult = 3 if x.get("has_physical") else 1
        x["_rank"] = h * weight_mult

    primary_pool.sort(key=lambda x: x["_rank"])

    # Determine slots for discovery
    slots_left = max(0, rotation_limit - len(recent_tier) - len(highlight_items))
    selected_discovery = primary_pool[:slots_left]

    # If library has room and deferred series books exist, backfill
    if len(selected_discovery) < slots_left and deferred_pool:
        backfill_slots = slots_left - len(selected_discovery)
        deferred_pool.sort(key=lambda x: (
            x.get("sequence") if (x.get("sequence") is not None and x.get("sequence") >= 0.0) else 999999.0,
            _clean_title(x.get("title", ""))
        ))
        selected_discovery.extend(deferred_pool[:backfill_slots])

    final_results = recent_tier + highlight_items + selected_discovery

    # Clean up internal metadata keys
    for r in final_results:
        r.pop("_last_played_at", None)
        r.pop("_rank", None)

    return final_results[:rotation_limit]

def set_item_highlight(media_id: str, is_highlight: bool) -> bool:
    """Toggles the seasonal/pinned highlight status of a media item."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE media_items SET is_highlight = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (1 if is_highlight else 0, media_id))
        return True
    finally:
        conn.close()
def batch_update_media_highlight(media_ids: List[str], is_highlight: bool) -> int:
    """Atomically sets is_highlight for multiple media items."""
    if not media_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ",".join("?" for _ in media_ids)
        val = 1 if is_highlight else 0
        with conn:
            cur = conn.execute(
                f"UPDATE media_items SET is_highlight = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                [val] + list(media_ids)
            )
            return cur.rowcount
    finally:
        conn.close()

def set_item_physical(media_id: str, has_physical: bool) -> bool:
    """Sets the physical plastic card ownership flag of a media item."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE media_items SET has_physical = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (1 if has_physical else 0, media_id))
        return True
    finally:
        conn.close()

def batch_update_media_physical(media_ids: List[str], has_physical: bool) -> int:
    """Atomically sets has_physical for multiple media items."""
    if not media_ids:
        return 0
    conn = get_db_connection()
    try:
        placeholders = ",".join("?" for _ in media_ids)
        val = 1 if has_physical else 0
        with conn:
            cur = conn.execute(
                f"UPDATE media_items SET has_physical = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                [val] + list(media_ids)
            )
            return cur.rowcount
    finally:
        conn.close()
def batch_update_profile_media_permissions(media_ids: List[str], profile_actions: Dict[str, str], is_highlight: Optional[bool] = None, has_physical: Optional[bool] = None) -> Dict[str, Any]:
    """
    Atomically updates media permissions for multiple items across one or more profiles.
    profile_actions: { profile_id: "allow" | "exclude" | "reset" }
    is_highlight: optional boolean to update highlight status simultaneously
    has_physical: optional boolean to update physical ownership flag simultaneously
    """
    if not media_ids:
        return {"updated_cards": 0, "affected_profiles": 0}
    conn = get_db_connection()
    try:
        with conn:
            # 1. Optional bulk highlight update
            placeholders = ",".join("?" for _ in media_ids)
            if is_highlight is not None:
                val = 1 if is_highlight else 0
                conn.execute(
                    f"UPDATE media_items SET is_highlight = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                    [val] + list(media_ids)
                )
            if has_physical is not None:
                val_phy = 1 if has_physical else 0
                conn.execute(
                    f"UPDATE media_items SET has_physical = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders});",
                    [val_phy] + list(media_ids)
                )
            # 2. Bulk profile permission changes
            affected_profiles = 0
            for prof_id, action in profile_actions.items():
                action = str(action).lower().strip()
                if action not in ("allow", "exclude", "reset"):
                    continue
                affected_profiles += 1
                placeholders = ",".join("?" for _ in media_ids)
                # First, remove existing records for these media items for this profile
                conn.execute(
                    f"DELETE FROM profile_media_permissions WHERE profile_id = ? AND media_id IN ({placeholders});",
                    [prof_id] + list(media_ids)
                )
                if action in ("allow", "exclude"):
                    perm_val = "allowed" if action == "allow" else "excluded"
                    for mid in media_ids:
                        # Ensure media item exists in media_items table to satisfy FOREIGN KEY constraint
                        conn.execute("INSERT OR IGNORE INTO media_items (id, type, title) VALUES (?, 'abs', ?);", (mid, f"Item {mid}"))
                        conn.execute(
                            "INSERT OR REPLACE INTO profile_media_permissions (profile_id, media_id, permission) VALUES (?, ?, ?);",
                            (prof_id, mid, perm_val)
                        )
                # If action == "reset", we deleted the rows so they fall back to household default rules
            return {
                "updated_cards": len(media_ids),
                "affected_profiles": affected_profiles
            }
    finally:
        conn.close()
# ============================================================================
# System Settings DAO
# ============================================================================
def get_system_settings() -> Dict[str, Any]:
    """Returns global broker settings."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM system_settings;")
        res = {}
        for r in cur.fetchall():
            try:
                res[r["key"]] = json.loads(r["value"])
            except Exception:
                res[r["key"]] = r["value"]
        
        defaults = {
            "thumbnail_size": 100,
            "thumbnail_quality": 80,
            "cache_ttl_hours": 168,
            "abs_default_children_tags": ["Children"],
            "exclude_single_card_series": True,
            "auto_library_refresh_enabled": True,
            "auto_library_refresh_hours": 6,
            "ai_chapter_art": {
                "enabled": False,
                "provider": "openrouter",
                "fallback_to_bridge": True
            }
        }
        for k, v in defaults.items():
            if k not in res:
                res[k] = v
        return res
    finally:
        conn.close()
def set_system_setting(key: str, value: Any) -> bool:
    """Saves or updates a global broker setting into SQLite system_settings table."""
    conn = get_db_connection()
    try:
        val_str = json.dumps(value) if not isinstance(value, str) else value
        conn.execute("""
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP;
        """, (key, val_str))
        conn.commit()
        return True
    except Exception as e:
        logger.error("Failed to set system setting %s: %s", key, e)
        return False
    finally:
        conn.close()
# ============================================================================
# API Credentials & Service Connection DAO
# ============================================================================
def get_api_credentials() -> Dict[str, str]:
    """
    Returns upstream API credentials, prioritizing SQLite system_settings
    and falling back to environment variables.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        keys = [
            "abs_base_url", "abs_api_key",
            "yoto_connection_mode",
            "yoto_client_id", "yoto_client_secret", "yoto_refresh_token",
            "yoto_bridge_url", "yoto_bridge_api_key", "yoto_ui_pin",
            "tinker_api_key",
            "gemini_api_key", "anthropic_api_key", "openrouter_api_key"
        ]
        cur.execute(f"SELECT key, value FROM system_settings WHERE key IN ({','.join(['?']*len(keys))});", keys)
        db_creds = {}
        for r in cur.fetchall():
            try:
                db_creds[r["key"]] = json.loads(r["value"])
            except Exception:
                db_creds[r["key"]] = r["value"]
        # Fallback helper to inspect legacy config.json if unpopulated
        legacy_data = {}
        if LEGACY_CONFIG_PATH.exists():
            try:
                with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                    legacy_data = json.load(f)
            except Exception:
                pass
        legacy_settings = legacy_data.get("settings", {})
        def resolve_val(db_key: str, env_key: str, default_val: str = "") -> str:
            val = db_creds.get(db_key)
            if val:
                return str(val).strip()
            env_val = os.getenv(env_key)
            if env_val:
                return str(env_val).strip()
            legacy_val = legacy_data.get(db_key) or legacy_settings.get(db_key)
            if legacy_val:
                return str(legacy_val).strip()
            return default_val
        # Infer mode if unset: bridge if bridge url present or yoto keys empty
        raw_mode = db_creds.get("yoto_connection_mode")
        if not raw_mode:
            raw_mode = os.getenv("YOTO_CONNECTION_MODE", "bridge")
        return {
            "abs_base_url": resolve_val("abs_base_url", "ABS_BASE_URL", "http://audiobookshelf:80"),
            "abs_api_key": resolve_val("abs_api_key", "ABS_API_KEY", ""),
            "yoto_connection_mode": str(raw_mode).strip(),
            "yoto_client_id": resolve_val("yoto_client_id", "YOTO_CLIENT_ID", ""),
            "yoto_client_secret": resolve_val("yoto_client_secret", "YOTO_CLIENT_SECRET", ""),
            "yoto_refresh_token": resolve_val("yoto_refresh_token", "YOTO_REFRESH_TOKEN", ""),
            "yoto_bridge_url": resolve_val("yoto_bridge_url", "YOTO_BRIDGE_URL", "http://yoto-bridge:8080"),
            "yoto_bridge_api_key": resolve_val("yoto_bridge_api_key", "YOTO_BRIDGE_API_KEY", ""),
            "yoto_ui_pin": resolve_val("yoto_ui_pin", "YOTO_UI_PIN", ""),
            "tinker_api_key": resolve_val("tinker_api_key", "TINKER_API_KEY", ""),
            "gemini_api_key": resolve_val("gemini_api_key", "GEMINI_API_KEY", ""),
            "anthropic_api_key": resolve_val("anthropic_api_key", "ANTHROPIC_API_KEY", ""),
            "openrouter_api_key": resolve_val("openrouter_api_key", "OPENROUTER_API_KEY", "")
        }
    finally:
        conn.close()
def update_api_credentials(creds: Dict[str, str]) -> bool:
    """Updates API credentials in SQLite system_settings."""
    allowed = {
        "abs_base_url", "abs_api_key",
        "yoto_connection_mode",
        "yoto_client_id", "yoto_client_secret", "yoto_refresh_token",
        "yoto_bridge_url", "yoto_bridge_api_key", "yoto_ui_pin",
        "tinker_api_key",
        "gemini_api_key", "anthropic_api_key", "openrouter_api_key"
    }
    conn = get_db_connection()
    try:
        with conn:
            for k, v in creds.items():
                if k in allowed and v is not None:
                    conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?);", (k, json.dumps(str(v).strip())))
        return True
    finally:
        conn.close()
# ============================================================================
# Master API Key DAO
# ============================================================================
def get_master_api_key_details() -> Dict[str, Any]:
    """Returns the Broker's master API key details including created and updated timestamps."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value, updated_at FROM system_settings WHERE key = 'master_api_key';")
        row = cur.fetchone()
        if row and row["value"]:
            try:
                key_val = json.loads(row["value"])
            except Exception:
                key_val = row["value"]
            return {
                "api_key": key_val,
                "updated_at": row["updated_at"] or ""
            }
        
        # If missing, generate new 32-char hex key
        new_key = secrets.token_hex(16)
        conn.execute("INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES ('master_api_key', ?, CURRENT_TIMESTAMP);", (json.dumps(new_key),))
        conn.commit()
        return {
            "api_key": new_key,
            "updated_at": ""
        }
    finally:
        conn.close()
def get_master_api_key() -> str:
    """Returns the raw 32-character hex master API key."""
    return get_master_api_key_details()["api_key"]
def regenerate_master_api_key() -> str:
    """Generates a fresh 32-character hex master API key, invalidating prior tokens."""
    new_key = secrets.token_hex(16)
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('master_api_key', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP;
            """, (json.dumps(new_key),))
        logger.info("Regenerated Broker master API key.")
        return new_key
    finally:
        conn.close()
