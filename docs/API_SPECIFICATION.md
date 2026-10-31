# Complete REST API Reference & Catalog: Yoto-ESP32 Middleware Broker

**Document ID:** `API_CATALOG_MASTER`  
**Status:** Living Standard / Authoritative Specification  
**Base URL:** `http://<broker-ip>:5055`  
**Data Storage:** SQLite (`/data/broker.db`) with WAL Mode  
**Content Types:** `application/json`, `image/jpeg`  

---

## 📑 API Categories Summary

| Category | Target Client | Authentication / Access Gate | Description |
| :--- | :--- | :--- | :--- |
| **1. System Health & Probes** | ESP32, Admin UI, Docker | Open | Connectivity status, feature discovery flags, and uptime. |
| **2. Microcontroller Controller APIs** | ESP32 Bedside Touchscreen | Open / LAN Trusted | Lightweight JSON arrays and image streams for 800×480 screen. |
| **3. Live Playback & Telemetry** | ESP32, Home Assistant | Open / LAN Trusted | Real-time Yoto player MQTT state, progress sync, and transport. |
| **4. Onboarding, Auth & Sessions** | Admin Web Portal, SSO | First-run Open / Cookies / SSO | First-run wizard, Argon2id passwords, user management, and SSO. |
| **5. Profile & Household Admin** | Admin Web Portal | Admin Session / SSO Header | Child profiles, ABS API keys, libraries, and Yoto player bindings. |
| **6. Catalog Curation & Matrix** | Admin Web Portal | Admin Session / SSO Header | Matrix permission grid, seasonal highlights, and regex rules. |
| **7. Diagnostics, AI & Cache** | Admin Web Portal | Admin Session / SSO Header | Real-time connectivity tests, AI art previews, and cache management. |
| **8. Firmware & Remote OTA** | ESP32, Admin Web Portal | Admin Session / LAN Trusted | Binary storage, 1-click upgrades, version rollback, and progress telemetry. |
| **9. Home Assistant & MQTT** | Home Assistant Core | MQTT Broker / Auth | Auto-discovery entities, bedtime curfew locks, and sensors. |

---

## 1. System Health & Feature Discovery

### `GET /health`
Inspects upstream service connectivity, reporting active feature flags for microcontroller and UI auto-adaptation.
* **Auth:** None
* **Response (`200 OK`):**
  ```json
  {
    "status": "healthy",
    "features": {
      "abs_enabled": true,
      "yoto_enabled": true,
      "bridge_enabled": true,
      "multi_profile": true,
      "ai_chapter_art": {
        "enabled": true,
        "provider": "openrouter",
        "fallback_to_bridge": true
      }
    },
    "abs_configured": true,
    "yoto_configured": true,
    "yoto_bridge_url": "http://yoto-bridge:8080",
    "database": "sqlite_wal_active",
    "timestamp": 1792650000
  }
  ```

---

## 2. Microcontroller (ESP32-S3) Controller APIs

### `GET /api/device/config`
Queried by the ESP32 on boot to identify hardware-assigned default profile, settings, and available alternate profiles.
* **Auth:** None
* **Query Parameters:** `device_id` (string, required): Hardware MAC address (e.g. `c44f331122aa`).
* **Response (`200 OK`):**
  ```json
  {
    "device_id": "esp32_c44f331122aa",
    "assigned_profile": "child_one",
    "allow_profile_switch": true,
    "profiles": [
      {
        "id": "child_one",
        "display_name": "Oliver",
        "avatar_url": "/api/thumb?type=profile&id=child_one"
      },
      {
        "id": "child_two",
        "display_name": "Maya",
        "avatar_url": "/api/thumb?type=profile&id=child_two"
      }
    ]
  }
  ```

### `GET /api/profiles`
Returns active child profiles for the Screen 1 profile selection landing screen.
* **Auth:** None
* **Response (`200 OK`):**
  ```json
  [
    {
      "id": "child_one",
      "display_name": "Oliver",
      "avatar_url": "/api/thumb?type=profile&id=child_one"
    },
    {
      "id": "child_two",
      "display_name": "Maya",
      "avatar_url": "/api/thumb?type=profile&id=child_two"
    }
  ]
  ```

### `GET /api/kids/<profile_id>/abs`
Fetches Audiobookshelf books permitted for the specific child profile.
* **Auth:** None (microcontroller-accessible endpoint)
* **Scoping Resolution:**
  1. **Automatic Account Scoping (Default):** The profile's `abs_username` automatically resolves the child's Bearer token from Audiobookshelf (`GET /api/users` via master API key). Audiobookshelf natively filters allowed libraries, tag restrictions (e.g. `'Children'`), and explicit content limits without requiring manual child API keys!
  2. **Manual Token Override (Optional):** Explicit `abs_api_key` or `abs_token` override if specified.
  3. **Local Overrides:** Optional restriction to `abs_library_id` or additional `abs_tag`.
  4. **Master Fallback:** If `abs_username` is unassigned, queries using master `ABS_API_KEY`.
* **Response (`200 OK`):**
  ```json
  [
    {
      "id": "c1f7a4e8-8b9a-4c2d-9b1e-3a4f5c6d7e8f",
      "type": "abs",
      "title": "The Hobbit",
      "author": "J.R.R. Tolkien",
      "is_highlight": true,
      "thumb": "/api/thumb?type=abs&id=c1f7a4e8-8b9a-4c2d-9b1e-3a4f5c6d7e8f"
    }
  ]
  ```

### `GET /api/kids/<profile_id>/yoto`
Fetches curated native Yoto cards and MYO playlists for the child profile.
* **Auth:** None
* **Response (`200 OK`):**
  ```json
  [
    {
      "id": "1C9YE",
      "type": "yoto",
      "title": "Bedtime Stories Collection",
      "author": "Yoto",
      "is_myo": true,
      "is_highlight": true,
      "thumb": "/api/thumb?type=yoto&url=https%3A%2F%2Fassets.yotoplay.com%2F...jpg"
    }
  ]
  ```

### `GET /api/items/<id>/chapters`
Returns lightweight chapter track listings with durations and 16×16 pixel art icons for Screen 3 chapter browser.
* **Auth:** None
* **Response (`200 OK`):**
  ```json
  [
    {
      "index": 0,
      "title": "An Unexpected Party",
      "start": 0.0,
      "duration": 1845.2,
      "thumb": "/api/thumb?type=abs_chapter&id=c1f7a4e8...&chapter=0&size=100"
    }
  ]
  ```

### `GET /api/thumb`
Lightweight on-demand thumbnail resizer and AI chapter artwork stream.
* **Auth:** None
* **Query Parameters:**
  * `type`: `abs`, `abs_chapter`, `yoto`, or `profile`
  * `id`: Media UUID / Card ID
  * `chapter`: 0-indexed chapter number (for `abs_chapter`)
  * `url`: Upstream image URL (for `yoto`)
  * `size`: Dimensions (default: `100` for 100×100px)
* **Response (`200 OK`):** Binary `image/jpeg` with 24-hour cache headers.

### `POST /api/play`
Unified playback dispatcher triggering playback on the child's designated physical Yoto player.
* **Auth:** None
* **Payload:**
  ```json
  {
    "child": "child_one",
    "type": "abs",
    "id": "c1f7a4e8-8b9a-4c2d-9b1e-3a4f5c6d7e8f",
    "device_id": "optional_specific_yoto_device_id",
    "chapter": 1
  }
  ```
* **Response (`200 OK`):**
  ```json
  {
    "ok": true,
    "status": "playing",
    "type": "abs",
    "device_id": "y2_sample_player_id_1"
  }
  ```

---

## 3. Live Playback Telemetry & Remote Transport

### `GET /api/kids/<profile_id>/now-playing`
Real-time aggregated telemetry merging Yoto MQTT state with Audiobookshelf playback progress.
* **Auth:** None
* **Response (`200 OK`):**
  ```json
  {
    "player_id": "y2_sample_player_id_1",
    "player_name": "Oliver's Bedroom Yoto",
    "online": true,
    "state": "playing",
    "media_type": "abs",
    "item_id": "c1f7a4e8-8b9a-4c2d-9b1e-3a4f5c6d7e8f",
    "title": "The Hobbit",
    "chapter_title": "An Unexpected Party",
    "chapter_index": 1,
    "total_chapters": 19,
    "position_sec": 420.5,
    "duration_sec": 1845.2,
    "progress_percent": 22.8,
    "volume": 6,
    "night_mode": false,
    "bedtime_locked": false,
    "cover_url": "/api/thumb?type=abs&id=c1f7a4e8-8b9a-4c2d-9b1e-3a4f5c6d7e8f&size=100"
  }
  ```

### `POST /api/kids/<profile_id>/control`
Remote playback control commands with parental safety bounds.
* **Auth:** None
* **Payload:**
  ```json
  {
    "command": "play | pause | next | prev | set_volume | seek",
    "value": 8
  }
  ```
* **Response (`200 OK`):** `{"ok": true, "command": "set_volume", "volume": 8}`

### `POST /api/devices/register`
Self-announcement handshake called by ESP32 devices upon completing Wi-Fi connection and mDNS discovery.
* **Auth:** None (Automatic registration; placed into quarantine until approved).
* **Payload:**
  ```json
  {
    "mac_address": "c4:4f:33:11:22:aa",
    "friendly_name": "ESP32 Controller",
    "ip_address": "192.168.1.145",
    "firmware_version": "1.2.0"
  }
  ```
* **Response (`200 OK` or `201 Created`):**
  ```json
  {
    "status": "registered",
    "mac_address": "c4:4f:33:11:22:aa",
    "is_approved": false,
    "assigned_profile": null,
    "message": "Device registered and awaiting administrator approval in Admin Portal."
  }
  ```

---

## 4. Admin Onboarding, Multi-User Auth & SSO

### `GET /api/admin/auth/status`
Checks if initial administrator setup is required and returns active session identity.
* **Auth:** None
* **Response (`200 OK`):**
  ```json
  {
    "setup_required": false,
    "authenticated": true,
    "user": {
      "id": "usr_admin_01",
      "username": "admin",
      "role": "admin",
      "sso": false
    }
  }
  ```

### `POST /api/admin/auth/setup`
First-run onboarding endpoint to create the initial administrator credentials.
* **Auth:** None (Permanently locked with `403 Forbidden` once any user exists).
* **Payload:** `{"username": "admin", "password": "secure_password", "display_name": "Parent"}`
* **Response (`201 Created`):** `{"ok": true, "message": "Initial administrator account created."}`

### `POST /api/admin/auth/login`
Authenticates administrator credentials and issues an HTTP-only session cookie.
* **Auth:** None
* **Payload:** `{"username": "admin", "password": "password"}`
* **Response (`200 OK`):** Sets `Set-Cookie: broker_session=...; HttpOnly; SameSite=Lax`.

### `POST /api/admin/auth/logout`
Terminates active session cookie.
* **Auth:** Session Cookie
* **Response (`200 OK`):** `{"ok": true, "message": "Logged out"}`

### `GET /api/admin/users`
Lists registered administrator and curator accounts.
* **Auth:** Admin Session
* **Response (`200 OK`):** Array of user records (excluding password hashes).

### `POST /api/admin/users`
Creates a new manager/curator account or links an external SSO identity.
* **Auth:** Admin Session
* **Payload:** `{"username": "parent2", "password": "...", "role": "curator"}`

---

## 5. Child Profile Management

### `GET /api/admin/profiles`
Returns all child profiles with full configuration schemas.
* **Auth:** Admin Session
* **Response (`200 OK`):** Array of profiles with ABS tokens, library IDs, and Yoto player IDs.

### `POST /api/admin/profiles`
Creates a new child profile.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "id": "child_three",
    "display_name": "Liam",
    "abs_username": "liam_dean",
    "abs_api_key": "",
    "abs_library_id": "",
    "abs_tag": "",
    "default_player_id": "y2_sample_player_id_3",
    "player_ids": ["y2_sample_player_id_3"]
  }
  ```
  *(Note: `abs_username` automatically resolves Liam's user token from Audiobookshelf without requiring `abs_api_key`).*

### `PUT /api/admin/profiles/<profile_id>`
Updates child profile settings.
* **Auth:** Admin Session

### `DELETE /api/admin/profiles/<profile_id>`
Deletes a child profile and cascades permissions.
* **Auth:** Admin Session

### `GET /api/admin/discovery/players`
Live Yoto Player discovery endpoint. Queries the local Streaming Bridge (`GET /api/status`) if in Bridge mode, or Yoto Cloud (`GET /family/devices`) if in Direct mode.
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  [
    {
      "id": "y23sample_id_mini",
      "name": "Nursery Mini",
      "online": true,
      "status": "idle"
    },
    {
      "id": "y24sample_id_player",
      "name": "Leo's Player",
      "online": true,
      "status": "playing"
    }
  ]
  ```

### `GET /api/admin/discovery/household-match`
Auto-Discovery & Profile Matcher Engine. Simultaneously queries physical Yoto players and Audiobookshelf child users, performing string tokenization and fuzzy matching (e.g., "Leo's Player" $\leftrightarrow$ ABS user `leo`).
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  {
    "matches": [
      {
        "suggested_profile_id": "leo",
        "display_name": "Leo",
        "matched_abs_user": {
          "id": "usr_abs_01",
          "username": "leo"
        },
        "matched_yoto_player": {
          "id": "y24sample_id_player",
          "name": "Leo's Player",
          "online": true
        },
        "confidence": 0.95,
        "already_exists": false
      }
    ],
    "unmatched_players": [
      {"id": "y23sample_id_mini", "name": "Nursery Mini"}
    ],
    "unmatched_abs_users": []
  }
  ```

### `POST /api/admin/discovery/auto-import`
1-Click Profile Batch Provisioning. Takes an array of approved matches from `/api/admin/discovery/household-match` and provisions them into SQLite `profiles`.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "profiles": [
      {
        "id": "leo",
        "display_name": "Leo",
        "default_player_id": "y24sample_id_player",
        "abs_tag": "leo",
        "inherit_shared": true
      }
    ]
  }
  ```
* **Response (`201 Created`):** `{"ok": true, "imported_count": 1}`

### `GET /api/admin/discovery/abs`
Queries Audiobookshelf for live library names/IDs and active user accounts for dropdown selection.
* **Auth:** Admin Session

### `GET /api/admin/discovery/yoto`
Queries Yoto Developer Cloud for registered physical players and device status.
* **Auth:** Admin Session

### `GET /api/admin/devices`
Lists all discovered and registered ESP32 hardware controllers, including quarantine status and assigned child profile.
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  [
    {
      "mac_address": "c4:4f:33:11:22:aa",
      "friendly_name": "Oliver's Bedside Display",
      "assigned_profile_id": "child_one",
      "is_approved": true,
      "ip_address": "192.168.1.145",
      "firmware_version": "1.2.0",
      "last_seen": "2026-10-25T19:00:00Z"
    }
  ]
  ```

### `PUT /api/admin/devices/<mac_address>`
Updates a controller's friendly name, assigned default profile, or approval/quarantine toggle.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "friendly_name": "Oliver's Bedside Display",
    "assigned_profile_id": "child_one",
    "is_approved": true
  }
  ```
* **Response (`200 OK`):** `{"ok": true, "message": "Device configuration updated."}`

### `DELETE /api/admin/devices/<mac_address>`
Removes an ESP32 device from the database, resetting it to unapproved state if re-registered.
* **Auth:** Admin Session
* **Response (`200 OK`):** `{"ok": true, "message": "Device unregistered."}`

---

## 6. Catalog Curation Matrix & Seasonal Highlights

### `GET /api/admin/catalog/matrix`
Returns unified library list of all Yoto cards and ABS books with current permission matrix, highlight flags, tags, and library IDs.
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  {
    "items": [
      {
        "id": "c1f7a4e8-8b9a-4c2d-9b1e-3a4f5c6d7e8f",
        "type": "abs",
        "title": "The Hobbit",
        "author": "J.R.R. Tolkien",
        "cover_url": "/api/thumb?type=abs&id=c1f7a4e8...",
        "is_highlight": true,
        "tags": ["Children", "Fantasy"],
        "library_id": "bf10a0a9-38a2-49f1-8936-8e3c3fe5e3fa",
        "series": "Middle Earth",
        "series_order": "1",
        "profiles": {
          "jackson": { "allowed": true, "reason": "abs_account_permitted" },
          "wesley": { "allowed": true, "reason": "abs_account_permitted" }
        }
      }
    ],
    "profiles": ["jackson", "wesley"],
    "shared_rules": { "include_all": false, "include_myo_by_default": true }
  }
  ```

### `POST /api/admin/abs/item-tags`
One-stop administration endpoint to inspect and modify tags directly on an Audiobookshelf book via the master API key, instantly syncing permissions across child profiles.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "item_id": "7696c2d1-49bc-4165-a3dd-743b4ad79328",
    "tags": ["Children"]
  }
  ```
* **Response (`200 OK`):**
  ```json
  {
    "ok": true,
    "tags": ["Children"]
  }
  ```

### `GET /api/admin/abs/server-tags`
Returns the live, deduplicated list of all tags present in the connected Audiobookshelf instance across all libraries. Used to populate tag selectors and dropdowns dynamically.
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  {
    "ok": true,
    "tags": ["Action & Adventure", "Children", "Fantasy", "Kids", "Juvenile", "Sci-Fi"]
  }
  ```

### `GET /api/admin/settings/abs-tags`
Retrieves the array of tags configured as the default child account tags. Books bearing any of these tags in Audiobookshelf are automatically granted to child accounts.
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  {
    "ok": true,
    "tags": ["Children"]
  }
  ```

### `PUT /api/admin/settings/abs-tags`
Updates the default children account tags in system settings and recalculates catalog permissions.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "tags": ["Children", "Kids", "Juvenile"]
  }
  ```
* **Response (`200 OK`):**
  ```json
  {
    "ok": true,
    "tags": ["Children", "Kids", "Juvenile"],
    "message": "Default children tags updated."
  }
  ```

### `POST /api/admin/catalog/sync`
Queries upstream Yoto (via Streaming Bridge or Direct Cloud) and Audiobookshelf servers to refresh the `media_items` cache in SQLite, extracting series/collections, Yoto content groups, and tags.
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  {
    "ok": true,
    "count": 413
  }
  ```

### `POST /api/admin/curation/permission`
Toggles a single profile's permission on a card or audiobook.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "profile_id": "wesley",
    "media_id": "7gGiV",
    "allowed": true
  }
  ```
* **Response (`200 OK`):** `{"ok": true}`

### `POST /api/admin/curation/shared-rule`
Updates a shared household rule (`include_all` or `include_myo_by_default`).
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "key": "include_all",
    "value": true
  }
  ```
* **Response (`200 OK`):** `{"ok": true}`

### `POST /api/admin/curation/batch-permissions`
Atomically updates multiple card permissions across one or more child profiles in a single SQLite transaction.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "media_ids": ["7gGiV", "3JvKE", "7yTdy", "5L55K"],
    "profile_actions": {
      "wesley": "allow",
      "jackson": "exclude",
      "communal": "reset"
    },
    "is_highlight": null
  }
  ```
* **Response (`200 OK`):**
  ```json
  {
    "ok": true,
    "updated_cards": 4,
    "affected_profiles": 3
  }
  ```

### `POST /api/admin/curation/batch-highlight`
Bulk updates the seasonal highlight / pinned status (`is_highlight`) across multiple cards.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "media_ids": ["7gGiV", "3JvKE"],
    "is_highlight": true
  }
  ```
* **Response (`200 OK`):** `{"ok": true, "count": 2}`

### `POST /api/admin/catalog/matrix`
Saves updated permission matrix, seasonal highlight pins, and shared household rules to SQLite.
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "highlights": ["c1f7a4e8-8b9a-4c2d-9b1e-3a4f5c6d7e8f"],
    "permissions": {
      "child_one": { "allowed": ["c1", "c2"], "excluded": ["c3"] }
    },
    "shared_yoto": { "include_all": false, "include_myo_by_default": true }
  }
  ```

### `GET /api/admin/icons/search`
Unified Multi-Tier Community Icon Search. Aggregates 16×16 icons across:
1. **Tier 0:** Matching cards in the family Yoto library (`yoto_client.get_raw_library()`)
2. **Tier 1:** `yotoicons.com` (real-time community scrape, zero keys required)
3. **Tier 2:** `api.tinker.audio` (if `tinker_api_key` configured in settings)
4. **Tier 3:** On-demand generative AI preview (if user AI key configured)
* **Auth:** Admin Session
* **Query Params:** `q=<term>&source=<auto|yoto|yotoicons|tinker|ai>`
* **Response (`200 OK`):**
  ```json
  [
    {
      "id": "yoto_card_ch_1",
      "name": "The Hobbit - Chapter 1",
      "url": "http://192.168.1.100:8080/s/icon/card_hobbit/0/1.png",
      "source": "yoto_library",
      "match_confidence": 0.94
    },
    {
      "id": "yotoicons_8703",
      "name": "Gruffalo",
      "url": "https://yotoicons.com/static/uploads/8703.png",
      "source": "yotoicons",
      "artist": "@curiouscat"
    },
    {
      "id": "tinker_123",
      "name": "Fire Truck",
      "url": "https://cdn.tinker.audio/icons/123.png",
      "source": "tinker",
      "attribution": "Powered by Tinker"
    }
  ]
  ```

### `POST /api/admin/icons/assign`
Assigns a chosen 16×16 community or AI icon to a book chapter or Yoto card. Downloads the PNG, upscales to 100×100 for the ESP32 display, caches it in `./cache/ai_chapters/`, and syncs it upstream to the Bridge (`PUT /api/cards/{slot}/icon/chapters/{item}/{n}`).
* **Auth:** Admin Session
* **Payload:**
  ```json
  {
    "item_id": "abs_book_123",
    "chapter_index": 2,
    "icon_url": "https://yotoicons.com/static/uploads/8703.png"
  }
  ```
* **Response (`200 OK`):** `{"ok": true, "thumb_url": "/api/thumb?type=abs_chapter&id=abs_book_123&chapter=2"}`

---

## 7. Diagnostics, AI Art Previews & Cache Management

### `GET /api/admin/settings`
Returns system parameters, feature toggles, and cache statistics.
* **Auth:** Admin Session

### `PUT /api/admin/settings`
Updates system settings in SQLite (`thumbnail_size`, `thumbnail_quality`, `cache_ttl_hours`, Tinker API key, AI provider key).
* **Auth:** Admin Session

### `POST /api/admin/test/abs`
Tests Audiobookshelf server connection and key validity.
* **Auth:** Admin Session
* **Response (`200 OK`):** `{"ok": true, "libraries_found": 3, "latency_ms": 42}`

### `POST /api/admin/test/bridge`
Tests local Yoto ↔ Audiobookshelf Streaming Bridge connectivity and registered player devices.
* **Auth:** Admin Session
* **Response (`200 OK`):** `{"ok": true, "status": "Logged in", "devices_count": 2, "latency_ms": 12}`

### `POST /api/admin/test/yoto`
Tests Yoto OAuth token refresh and reports registered player device count.
* **Auth:** Admin Session
* **Response (`200 OK`):** `{"ok": true, "players_found": 2, "token_expires_in": 3590}`

### `POST /api/admin/test/tinker`
Tests Tinker Icons API key connectivity and reports remaining quota.
* **Auth:** Admin Session
* **Response (`200 OK`):** `{"ok": true, "message": "Tinker API key active", "daily_requests_remaining": 492}`

### `POST /api/admin/test/ai`
Tests configured AI provider (Gemini, Claude, OpenRouter) and generates a 16×16 preview.
* **Auth:** Admin Session
* **Payload:** `{"prompt": "A hobbit door in a green hill"}`
* **Response (`200 OK`):** `{"ok": true, "preview_url": "/api/thumb?type=test_ai"}`

### `POST /api/admin/cache/purge`
Purges cached cover thumbnails and generated AI artwork.
* **Auth:** Admin Session
* **Response (`200 OK`):** `{"ok": true, "files_purged": 142, "bytes_freed": 12450000}`

---

## 8. Firmware Repository & Remote OTA Rollback

### `GET /api/admin/firmware`
Lists all compiled firmware binary releases stored on the broker.
* **Auth:** Admin Session
* **Response (`200 OK`):**
  ```json
  [
    {
      "version": "v1.2.1",
      "release_tag": "Latest Stable",
      "file_size_bytes": 2457812,
      "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "git_commit": "7a35e53",
      "release_notes": "Added dual-tab Audiobookshelf catalog and seasonal highlight shelf.",
      "is_active_latest": true
    }
  ]
  ```

### `POST /api/admin/firmware/upload`
Uploads a newly compiled `firmware.bin` from PlatformIO directly into `/data/firmware/`.
* **Auth:** Admin Session
* **Payload:** `multipart/form-data` with `file`, `version`, `release_notes`.
* **Response (`201 Created`):** `{"ok": true, "version": "v1.2.1", "sha256": "..."}`

### `POST /api/admin/devices/<mac_address>/update`
Commands a specific controller to pull and flash a target firmware version (or rollback to an earlier version).
* **Auth:** Admin Session
* **Payload:** `{"version": "v1.2.0", "force": false}`
* **Response (`200 OK`):** `{"ok": true, "status": "update_initiated", "target": "v1.2.0"}`

### `POST /api/admin/devices/update-all`
Dispatches rolling batch updates across all approved ESP32 hardware displays with an optional delay.
* **Auth:** Admin Session
* **Payload:** `{"version": "v1.2.1", "batch_delay_sec": 30}`

### `GET /api/firmware/<version>/firmware.bin`
Streams binary firmware image to the ESP32 for OTA flashing.
* **Auth:** None (LAN Trusted)
* **Headers:** `Content-Type: application/octet-stream`, `X-SHA256: <hash>`, `Content-Length: <size>`.

### `POST /api/devices/<mac_address>/ota-progress`
Telemetry endpoint called by the ESP32 during streaming writes to update admin UI progress bar.
* **Auth:** None (LAN Trusted)
* **Payload:**
  ```json
  {
    "status": "flashing",
    "progress": 68,
    "bytes_written": 1671168,
    "total_bytes": 2457812
  }
  ```

---

## 9. Home Assistant & MQTT Integration

### MQTT Topics (Auto-Discovery)
* **Status Sensor:** `homeassistant/sensor/yoto_<child>_state/state` (e.g., `playing`, `paused`, `idle`).
* **Bedtime Curfew Lock:** `homeassistant/switch/yoto_<child>_bedtime_lock/set` (`ON` / `OFF`).
* **Progress Sensor:** `homeassistant/sensor/yoto_<child>_progress/state` (Percentage `0-100%`).
* **Volume Control:** `homeassistant/number/yoto_<child>_volume/set` (Volume slider `0-15`).