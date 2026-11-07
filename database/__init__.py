"""
StoryDeck Core Database Package - Modular SQLite Persistence Layer (WAL Mode).
Maintains 100% backward compatibility for all `import database` consumers.
"""
from .connection import get_db_connection, DB_PATH, LEGACY_CONFIG_PATH, DB_DEFAULT, CONFIG_DEFAULT, IS_DOCKER, logger
from .schema import init_db, run_schema_migrations, migrate_legacy_config
from .auth import (
    hash_password, verify_password, get_admin_user_count, create_admin_user,
    authenticate_user, get_user_by_username, list_admin_users
)
from .profiles import (
    get_all_profiles, get_profile_by_id, upsert_profile, delete_profile,
    get_shared_rules, set_shared_rule
)
from .devices import (
    register_esp32_device, get_esp32_device, list_esp32_devices, update_esp32_device,
    revoke_esp32_device, delete_esp32_device, prune_stale_devices
)
from .media import (
    upsert_media_items, get_media_item_by_id, get_catalog_matrix, prune_stale_media_items,
    record_playback, get_playback_history
)
from .curation import (
    sanitize_display_text, get_catalog_items_for_profile, set_item_highlight,
    batch_update_media_highlight, set_item_physical, batch_update_media_physical,
    batch_update_profile_media_permissions
)
from .settings import (
    get_system_settings, set_system_setting, get_api_credentials, update_api_credentials,
    get_master_api_key_details, get_master_api_key, regenerate_master_api_key
)

__all__ = [
    "get_db_connection", "DB_PATH", "LEGACY_CONFIG_PATH", "DB_DEFAULT", "CONFIG_DEFAULT", "IS_DOCKER", "logger",
    "init_db", "run_schema_migrations", "migrate_legacy_config",
    "hash_password", "verify_password", "get_admin_user_count", "create_admin_user",
    "authenticate_user", "get_user_by_username", "list_admin_users",
    "get_all_profiles", "get_profile_by_id", "upsert_profile", "delete_profile",
    "get_shared_rules", "set_shared_rule",
    "register_esp32_device", "get_esp32_device", "list_esp32_devices", "update_esp32_device",
    "revoke_esp32_device", "delete_esp32_device", "prune_stale_devices",
    "upsert_media_items", "get_media_item_by_id", "get_catalog_matrix", "prune_stale_media_items",
    "record_playback", "get_playback_history",
    "sanitize_display_text", "get_catalog_items_for_profile", "set_item_highlight",
    "batch_update_media_highlight", "set_item_physical", "batch_update_media_physical",
    "batch_update_profile_media_permissions",
    "get_system_settings", "set_system_setting", "get_api_credentials", "update_api_credentials",
    "get_master_api_key_details", "get_master_api_key", "regenerate_master_api_key",
]
