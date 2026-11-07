"""SQLite DDL Schema Creation, Incremental Migrations & Legacy Config Bootstrap."""
import json
import os
import sqlite3
import hashlib
import secrets
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .connection import get_db_connection, DB_PATH, LEGACY_CONFIG_PATH, logger

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
            # 2b. Media Playback History (tracks recent card/book listening per profile)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS media_playback_history (
                media_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                last_played_at DATETIME NOT NULL,
                PRIMARY KEY (media_id, profile_id)
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
CURRENT_SCHEMA_VERSION = 8
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

    # Version 7 -> 8: Add media_playback_history table and index
    if version < 8:
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS media_playback_history (
                media_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                last_played_at DATETIME NOT NULL,
                PRIMARY KEY (media_id, profile_id)
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_playback_hist_prof ON media_playback_history(profile_id);")
            conn.execute("PRAGMA user_version = 8;")
        logger.info("Migrated SQLite schema to version 8 (added media_playback_history table).")
# ============================================================================
# Password Hashing & Security Helpers (PBKDF2-HMAC-SHA256)
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
