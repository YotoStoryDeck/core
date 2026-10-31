# Feature Specification: Broker Web Admin Dashboard & Curation Portal
**Document ID:** `009-broker_web_admin_dashboard`  
**Status:** Approved  
**Component:** Broker Web Admin UI & REST Endpoints  
**Target Platform:** Python Flask Embedded SPA (Desktop / Tablet Responsive)  

---

## 1. Executive Summary & Purpose
The **Broker Web Admin Dashboard** provides a centralized, browser-based management portal for the Yoto & Audiobookshelf ESP32 Controller ecosystem. It eliminates the friction of editing raw JSON configuration files by hand, enabling parents and administrators to:
1. **Manage Child Profiles:** Create, update, reorder, and delete child profiles, linking them to dedicated ABS user API keys, restricted ABS library IDs, and default physical Yoto Player devices.
2. **Curate the Catalog via a Unified Matrix Grid:** View every card in the household Yoto family library alongside Audiobookshelf audiobooks in a single filterable table, managing household-shared permissions, child profile assignments, and seasonal "Highlights / Featured" lists.
3. **Configure & Test Settings Live:** Edit global broker parameters (thumbnails, AI providers, cache TTL) and run instant real-time diagnostic checks against Yoto OAuth, Audiobookshelf API, and AI Pixel Art engines.
4. **Secure Access with Proxy SSO & Basic Auth:** Protect the admin interface via HTTP Basic Auth with seamless pass-through support for reverse-proxy SSO (Authentik, Cloudflare Access).

---

## 2. Technical Architecture & Security Model

### 2.1 Web Architecture
* **Single-Page Application (SPA):** Built with Vanilla HTML5, modern scoped CSS, and modular ES6 JavaScript.
* **Server-Embedded:** Hosted directly inside the Flask broker container, served via `GET /admin` with static assets bundled in `broker/static/`.
* **Zero External Runtime Dependencies:** Runs completely offline on local LAN without requiring CDNs, npm build pipelines, or internet access.

### 2.2 First-Run Onboarding & Security Architecture

The broker enforces a secure authentication lifecycle supporting first-run setup, multiple local administrator accounts, and reverse-proxy SSO:

1. **First-Run Onboarding Wizard (`/admin/setup`):**
   - When the admin portal is opened for the very first time (i.e. zero users in `admin_users`), the broker redirects to a clean **First-Run Account Creation** screen.
   - The initial administrator sets their desired `username` and `password` (hashed using Argon2id / bcrypt / PBKDF2-HMAC-SHA256).
   - Once saved to SQLite, open setup is permanently closed.
2. **Multi-User Account Model:**
   - Multiple admin/manager accounts can be created with distinct usernames and credentials.
   - Supports role-based access (`admin` vs `curator`).
3. **Session Authentication & REST API Tokens:**
   - Standard sign-on uses secure, HTTP-only session cookies (`SameSite=Lax`).
   - Also supports bearer API tokens for external automations or scripts.
4. **Reverse-Proxy Single Sign-On (Authentik / Cloudflare Access):**
   - Inspects reverse-proxy headers (`X-authentik-username`, `X-Forwarded-User`, `Remote-User`, `Cf-Access-Authenticated-User-Email`).
   - **Anti-Spoofing Gate (`TRUSTED_PROXIES`):** Proxy headers are **strictly honored only if the incoming connection originates from an explicitly configured CIDR/IP list** (`TRUSTED_PROXIES=192.168.1.10,172.18.0.0/16`). Requests from untrusted LAN IPs attempting to pass SSO headers are rejected and prompted for local password authentication.
5. **Hardware Device Quarantine & Pairing Approval Gate:**
   - Newly discovered ESP32 devices auto-registering via mDNS/HTTP are placed into an **`Unapproved / Quarantined`** state in SQLite (`is_approved = 0`).
   - The device cannot fetch media catalogs, view child profiles, or dispatch playback commands until an administrator explicitly reviews and approves the device in the Admin Portal.

### 2.3 SQLite Persistence & Relational Data Model (`/data/broker.db`)

To ensure high-concurrency safety, eliminate JSON file lock race conditions, and support scalable many-to-many catalog queries, the broker utilizes an embedded **SQLite database with Write-Ahead Logging (WAL)** enabled (`PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL;`).

```sql
-- 0. Admin & User Accounts (Multi-User & SSO Support)
CREATE TABLE admin_users (
    id TEXT PRIMARY KEY,               -- e.g. 'usr_admin_01'
    username TEXT UNIQUE NOT NULL,     -- 'admin'
    password_hash TEXT NOT NULL,       -- PBKDF2 / Argon2id salted hash
    display_name TEXT DEFAULT '',      -- 'Parent Admin'
    role TEXT DEFAULT 'admin',         -- 'admin' or 'curator'
    sso_provider TEXT DEFAULT '',      -- 'authentik', 'cloudflare', or empty
    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 1. Child Profiles
CREATE TABLE profiles (
    id TEXT PRIMARY KEY,               -- e.g. 'child_one'
    display_name TEXT NOT NULL,        -- 'Child One'
    abs_api_key TEXT DEFAULT '',       -- Child's dedicated ABS user API key
    abs_library_id TEXT DEFAULT '',    -- Optional restricted library ID or name
    abs_tag TEXT DEFAULT '',           -- Optional tag filter (e.g. 'kids')
    default_player_id TEXT,            -- Default physical Yoto player ID
    player_ids TEXT DEFAULT '[]',      -- JSON array of allowed player IDs
    avatar_url TEXT DEFAULT '',
    inherit_shared BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. Household Media Items Cache (Yoto Cards & Audiobooks)
CREATE TABLE media_items (
    id TEXT PRIMARY KEY,               -- Card UID or ABS item UUID
    type TEXT NOT NULL,                -- 'yoto', 'yoto_myo', or 'abs'
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    cover_url TEXT DEFAULT '',
    is_highlight BOOLEAN DEFAULT 0,    -- Pinned / Seasonal Feature flag
    raw_metadata TEXT DEFAULT '{}',    -- JSON string of source metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. Profile Media Permissions Matrix (Many-to-Many)
CREATE TABLE profile_media_permissions (
    profile_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    permission TEXT CHECK(permission IN ('allowed', 'excluded')),
    PRIMARY KEY (profile_id, media_id),
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (media_id) REFERENCES media_items(id) ON DELETE CASCADE
);

-- 4. Registered ESP32 Hardware Controllers (Device-Profile Bindings & Quarantine)
CREATE TABLE esp32_devices (
    mac_address TEXT PRIMARY KEY,      -- e.g. 'c4:4f:33:11:22:aa'
    friendly_name TEXT NOT NULL,       -- "Oliver's Bedside Display"
    assigned_profile_id TEXT,          -- Default child profile (NULL = prompt selection)
    is_approved BOOLEAN DEFAULT 0,     -- 0 = Quarantined/Pending approval; 1 = Approved
    ip_address TEXT DEFAULT '',        -- Last known LAN IP
    firmware_version TEXT DEFAULT '',
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assigned_profile_id) REFERENCES profiles(id) ON DELETE SET NULL
);

-- 5. Shared Household Rules & Title Regexes
CREATE TABLE shared_rules (
    key TEXT PRIMARY KEY,              -- 'include_all', 'include_myo', etc.
    value TEXT NOT NULL
);

CREATE TABLE shared_regex_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_scope TEXT DEFAULT 'shared',-- 'shared' or profile_id
    pattern TEXT NOT NULL,             -- Regex pattern (e.g. '^Bedtime.*')
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 6. System Settings (Key-Value)
CREATE TABLE system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### Automatic Migration on Boot
If a legacy `config.json` exists on first startup, the broker parses its contents, migrates all profiles, allowed cards, and settings cleanly into `broker.db`, and creates a `config.json.migrated` backup.

---

## 3. UI Blueprint & Component Layout

### 3.1 Display Layout (Desktop / Tablet 1200px+)

```text
+----------------------------------------------------------------------------------------------------+
|  [📻 Yoto ESP32 Broker Admin]    [ 👤 Profiles ]   [ 🎛️ Catalog Curation ]   [ ⚙️ Settings ]   [🔒 Logout] |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   CATALOG CURATION MATRIX                                                                          |
|   Search: [ Filter by title, author, or tag... ]   Source: [ All Sources v ]   Type: [ All v ]     |
|                                                                                                    |
|   +----+----------+-----------------------+----------+--------+---------+---------+------------+   |
|   | #  | Cover    | Title                 | Source   | Shared | Oliver  | Maya    | Highlights |   |
|   +----+----------+-----------------------+----------+--------+---------+---------+------------+   |
|   | 1  | [100x100]| The Hobbit            | ABS      | [ x ]  | [ x ]   | [ x ]   | [★ Pinned] |   |
|   | 2  | [100x100]| Paw Patrol Rescue     | Yoto     | [   ]  | [ x ]   | [   ]   | [☆]        |   |
|   | 3  | [100x100]| Bedtime Lullabies     | Yoto MYO | [ x ]  | [ x ]   | [ x ]   | [★ Pinned] |   |
|   | 4  | [100x100]| Harry Potter Book 1   | ABS      | [   ]  | [   ]   | [ x ]   | [☆]        |   |
|   +----+----------+-----------------------+----------+--------+---------+---------+------------+   |
|                                                                                                    |
|   [ 💾 Save Curation Changes ]                                      [ Showing 24 items in catalog] |
+----------------------------------------------------------------------------------------------------+
```

### 3.2 Visual Permission & Accessibility Indicators
Items in the Matrix Grid include real-time permission badges to explain *why* an item is accessible:
- 🟢 **Explicitly Allowed:** Card ID or Book ID is directly listed in the child's allowed list.
- 🔵 **Inherited Shared:** Card is part of the household base (`shared_yoto`) and inherited by profile.
- 🟣 **Regex Matched:** Title matches an active pattern (e.g., `^Bedtime.*` or `.*[Oliver].*`).
- 🟡 **Library Scoped:** Audiobookshelf item visible by virtue of child's user account permissions or `abs_library_id`.
- 🔴 **Excluded:** Card is explicitly in the child's exclusion blacklist (overrides all inclusions).

---

### 4.1 Authentication & Setup Endpoints
* **`GET /api/admin/auth/status`**: Checks whether setup is completed (`setup_required: true/false`) and current user session identity.
* **`POST /api/admin/auth/setup`**: First-run endpoint to create initial administrator credentials (blocked once any user exists).
* **`POST /api/admin/auth/login`**: Standard username/password login, issuing an HTTP-only session cookie.
* **`POST /api/admin/auth/logout`**: Clears active session.
* **`GET /api/admin/users`**: Lists administrator accounts (admin role only).
* **`POST /api/admin/users`**: Creates a new user or links an SSO identity.

### 4.2 Profile Management Endpoints
* **`GET /api/admin/profiles`**: Returns full profile configurations from SQLite.
* **`POST /api/admin/profiles`**: Creates a new child profile.
* **`PUT /api/admin/profiles/<profile_id>`**: Updates an existing profile.
* **`DELETE /api/admin/profiles/<profile_id>`**: Deletes a profile.
* **`GET /api/admin/discovery/players`**: Live Yoto Player discovery endpoint. Queries the local Streaming Bridge (`/api/status`) if in Bridge mode, or Yoto Cloud (`/family/devices`) if in Direct mode. Returns list of player devices (`id`, `name`, `online`, `status`) to dynamically populate player dropdowns without manual typing.
* **`GET /api/admin/discovery/abs`**: Queries Audiobookshelf for available libraries, active tags, and user accounts.
* **`GET /api/admin/discovery/household-match`**: Auto-Discovery & Profile Matcher Engine. Simultaneously probes the Bridge (`GET /api/status`) and Audiobookshelf (`GET /api/users`), executing fuzzy name matching between physical Yoto player names (e.g., "Oliver's Player", "Maya's Mini") and ABS child user accounts (e.g., `oliver`, `maya`). Returns structured candidate profiles with confidence ratings ready for 1-click creation.
* **`POST /api/admin/discovery/auto-import`**: 1-Click Profile Provisioning. Accepts selected matched candidates and automatically inserts them into SQLite `profiles`, linking player IDs and child ABS user tokens in a single transaction.

---

## 4.3 First-Time Setup & Discovery Automation Matrix

To minimize parental onboarding friction, the broker automates credential discovery and profile creation while clearly declaring the exact prerequisite inputs required on first boot:

| Integration Element | First-Time Manual Input Required | Automated by Broker | Auto-Fill / Matching Target |
| :--- | :--- | :--- | :--- |
| **Broker Security** | Admin Username & Password | Session cookies, Argon2id hashing, SQLite user table creation | Admin access & SSO headers |
| **Yoto Connectivity (Bridge Mode)** | Local Streaming Bridge URL (e.g. `http://192.168.1.100:8080`) | Probes `/api/status` for connection, player lists, and library cards | **Zero Yoto API keys or developer setup needed** |
| **Yoto Connectivity (Direct Cloud Mode)** | Yoto Client ID from `dashboard.yoto.dev` | 1-Click browser PKCE OAuth popup (`/api/admin/yoto/oauth/start`) | Automatically captures Refresh Token via loopback callback |
| **Audiobookshelf Connection** | ABS Server URL & Primary/Admin API Key | Fetches visible libraries, child accounts, audiobooks, and chapter tracks | Validates connectivity and loads child user list |
| **Yoto Player Discovery** | None | Queries Bridge (`/api/status`) or Yoto Cloud | Populates player dropdowns (`id`, `name`) in profile editor |
| **Child Profiles Setup** | None (Parent clicks **"⚡ Auto-Discover Household Profiles"**) | Fuzzy matches ABS users $\leftrightarrow$ Yoto Player names | Auto-creates child profiles with pre-linked Yoto player & ABS user token |
| **ESP32 Bedside Hardware** | Turn on ESP32 & connect to Wi-Fi | Discovered via HTTP handshake, assigned friendly name | Parents select default child profile with 1-click in Hardware tab |
| **Existing Yoto Library Match (Tier 0)** | None | Fuzzy matches ABS books to family's physical Yoto cards | Automatically reuses official Yoto card & chapter icons |
| **Community Icons (Tiers 1 & 2)** | Free Tinker Developer Key (Optional; YotoIcons needs 0 keys) | Searches `yotoicons.com` (Tier 1) and `api.tinker.audio` (Tier 2) | Renders 16×16 icons with *"Powered by Tinker"* attribution |
| **AI Chapter Artwork (Tier 3 Fallback)** | OpenRouter / Anthropic / Gemini Key (or left blank) | If community icons miss, synthesizes bespoke 16×16 pixel art | Generates pixel grid and upscales to 100×100 for display |

### 4.4 ESP32 Device Registration & Profile Assignment Endpoints
* **`GET /api/admin/devices`**: Lists all registered ESP32 touchscreen devices, current assigned profile, IP, and last seen timestamp.
* **`PUT /api/admin/devices/<mac_address>`**: Updates device friendly name and assigned default child profile.
* **`DELETE /api/admin/devices/<mac_address>`**: Unregisters an ESP32 device.
* **`GET /api/device/config?device_id=<mac_address>`**: Device handshake endpoint queried by the ESP32 on boot to fetch its assigned default profile and available alternate profiles.

### 4.5 Unified Catalog Curation & Icon Search Endpoints
* **`GET /api/admin/catalog/matrix`**: Returns unified array of all Yoto cards and ABS books with active permission matrix.
* **`POST /api/admin/catalog/matrix`**: Saves updated matrix permissions and seasonal highlight flags to SQLite database.
* **`POST /api/admin/catalog/sync`**: Discovers cards, audiobooks, series, and groups from upstream Yoto and ABS servers to refresh SQLite cache.
* **`POST /api/admin/curation/permission`**: Real-time single card profile permission toggle (allowed/excluded).
* **`POST /api/admin/curation/shared-rule`**: Household baseline shared rule toggle (`include_all`, `include_myo_by_default`).
* **`POST /api/admin/curation/batch-permissions`**: Batch permissions update across multiple selected cards and profiles (see Feature `011`).
* **`POST /api/admin/curation/batch-highlight`**: Batch toggle for seasonal highlight / pinned status.
* **`POST /api/admin/abs/item-tags`**: Inspects and updates tags directly on an ABS book via master API.
* **`GET /api/admin/abs/server-tags`**: Fetches deduplicated live tags from Audiobookshelf server.
* **`GET /api/admin/settings/abs-tags`** & **`PUT /api/admin/settings/abs-tags`**: Configures default children account tags.
* **`GET /api/admin/icons/search`**: Unified Multi-Tier Community Icon Search. Accepts `?q=<term>` and queries in priority order:
  1. **Tier 0:** Existing household Yoto cards (matching playlists/cards)
  2. **Tier 1:** `yotoicons.com` (real-time community scrape, zero keys required)
  3. **Tier 2:** `api.tinker.audio` (if `tinker_api_key` configured in settings)
  4. **Tier 3:** On-demand AI synthesis preview (if AI key configured)
  Returns an aggregated array of icon objects (`id`, `name`, `url`, `source`, `attribution`).
* **`POST /api/admin/icons/assign`**: Assigns a chosen icon to a book chapter or Yoto card, syncing upstream to the Bridge.

### 4.6 Diagnostics & Settings Endpoints
* **`GET /api/admin/settings`**: Returns current system settings and feature flags.
* **`PUT /api/admin/settings`**: Updates system settings in SQLite database (hot-reloads ABS, Bridge, Tinker, and AI credentials).
* **`POST /api/admin/test/abs`**: Tests Audiobookshelf connectivity, API key, and library access.
* **`POST /api/admin/test/bridge`**: Tests live connectivity to the local Yoto ↔ Audiobookshelf Streaming Bridge.
* **`POST /api/admin/test/yoto`**: Tests Yoto OAuth token refresh and lists registered devices.
* **`POST /api/admin/test/tinker`**: Tests Tinker Icons API key and reports remaining daily quota.
* **`POST /api/admin/test/ai`**: Sends a prompt to the configured AI provider and returns a 16x16 pixel art preview.
* **`POST /api/admin/cache/purge`**: Purges cached cover and chapter thumbnails.

---

## 5. Verification & Acceptance Criteria
1. On a fresh installation, opening `/admin` redirects to `/admin/setup` prompting the user to create their initial admin credentials.
2. Attempting to call `/api/admin/auth/setup` after an initial admin exists returns `403 Forbidden`.
3. Valid credentials authenticate the user and persist across page refreshes via secure session cookies.
4. When reverse-proxy headers (`X-authentik-username`) are present, access is automatically granted without manual login prompts.
5. Multiple user accounts can be managed within the settings panel.
6. Adding a new profile via the Web UI immediately makes it selectable on the ESP32 landing screen.
7. Toggling an item in the Matrix Grid and saving updates `broker.db` immediately without requiring a broker restart.
8. "Test Connection" buttons return live JSON status in under 2 seconds.