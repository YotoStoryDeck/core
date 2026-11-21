# StoryDeck Core

An open-source, community-ready smart hub and middleware broker that connects children's hardware companion controllers ([**StoryDeck Touch**](https://github.com/YotoStoryDeck/touch)), **Audiobookshelf (ABS)** audio libraries, and physical **Yoto Players**.

StoryDeck Core unifies real-time MQTT telemetry, on-the-fly MP3 streaming, offline Yoto playlist uploads, catalog curation, multi-child profiles, thumbnail downscaling, remote Touch OTA firmware updates, and a mobile-first Parent Portal inside a single container.

---

## 🧩 Architecture Lineage & Foundations

StoryDeck Core integrates and builds upon foundational work from the open-source community:

1. **Hardware & Touchscreen Appliance:**
   * **Upstream:** [jayheavner/yoto-esp32-controller](https://github.com/jayheavner/yoto-esp32-controller)
   * **Attribution:** Created the original ESP32-S3 firmware, LVGL UI architecture, and 3D printable bedside enclosure for the Waveshare 4.3" panel.
2. **Audio Streaming & Two-Way Progress Sync (Now Integrated into Core):**
   * **Upstream:** [mylacc/yoto-audiobookshelf-bridge](https://github.com/mylacc/yoto-audiobookshelf-bridge)
   * **Attribution:** Pioneered the dynamic `ffmpeg` HTTP 206 MP3 streaming architecture, silence-snapped chapter splitting, offline track uploading, and MQTT bidirectional Audiobookshelf progress sync now integrated directly inside StoryDeck Core (`core/bridge/`).
3. **StoryDeck Core (This Hub):**
   * **Role:** Single-container orchestration server combining embedded Yoto Cloud streaming & MQTT telemetry with a mirrored collapsible-sidebar Parent Portal (`/`) and Admin Console (`/admin`), microcontroller-optimized JSON APIs, tag/series curation, multi-child profiles, SSO-ready user management, travel proximity detection, device quarantine, and remote OTA firmware management.

```mermaid
flowchart LR
    Touch["StoryDeck Touch & Tablet Kiosk (ESP32-S3 & /kiosk/)"] -->|"Optimized JSON & 100x100 Art"| Core["StoryDeck Core Hub (Flask, SQLite & Embedded Streaming/MQTT)"]
    Portal["Parent Portal & Admin Console (/ & /admin)"] -->|"Transport, Cards, Curation, Users & OTA"| Core
    Core -->|"Scoped Catalogs, Covers & Progress Sync"| ABS["Audiobookshelf Server"]
    Core -->|"HTTP 206 MP3 Stream & 16x16 Icons"| YotoPlayer["Physical Yoto Player"]
    Core -->|"OAuth2 PKCE, MQTT Events & Offline Uploads"| YotoCloud["Yoto Developer Cloud"]
    Core -.->|"Planned MQTT Discovery (Future Feature)"| HA["Home Assistant (MQTT)"]
```

---

## 🚀 Key Features

* **Parent Portal (`/`) & Mirrored Admin Console (`/admin`):** Shared collapsible left sidebar navigation with direct cross-portal links, consolidated `Core vX.Y.Z` status/version indicator, and real-time `/health` offline awareness banner (`#coreOfflineBanner`).
* **Bedside Player Controls & Profile Avatar Carousel:** Quick-switch child **Profile Avatar Carousel** paired directly with the **Target Yoto Player** selector, full `0–100%` volume slider displaying the Yoto App day/night ceiling cap (translated from Yoto's native `0–16` hardware scale), scrub seek, `±30s`, speed, sleep timers, Continue Listening, scoped Library browser, Primary & Fleet Card switcher (`Streaming` ↔ `Offline`), and Yoto Cloud playlist manager.
* **Dedicated Users & Access Management (Schema v13, SSO-Ready):** Standalone Admin `Users & Access` page supporting Primary Super Admin protection (`is_super_admin` on the initial setup account; protected with `403` against edits/deletes by other admins), full user profile editing, LAN/Sitter guest access policies, and 3-step ForwardAuth / OIDC-ready SSO identity resolution (Authentik, Authelia, etc.):
  1. Match by immutable `(sso_provider, sso_subject)` (`X-authentik-uid`, `X-Forwarded-Sub`, `Remote-Sub`).
  2. Initial match for unbound local accounts (`sso_subject == ''`) by `email` then `username`, atomically binding the immutable subject ID.
  3. Optional auto-provisioning of unmatched SSO users as `member` (with anti-hijack protection preventing re-binding of already-bound accounts).
* **Consolidated Streaming & Native MQTT Engine:** Embedded `ffmpeg` 64kbps mono HTTP `206` MP3 streamer, silence-snapped chapter cuts (`QuietSpots`), offline Yoto Cloud playlist uploads with warm SHA reuse & series-aware LRU pruning, native `YotoMqttBridge` telemetry, and bi-directional Audiobookshelf progress sync (`PlaybackManager`).
* **Microcontroller-Optimized APIs & Integrated Tablet Kiosk:** Tailored endpoints serving compact JSON payloads, 100×100 JPEG thumbnails for ESP32-S3 Touch displays, and a zero-dependency web companion at `/kiosk/`.
* **Multi-Child Profiles & Curation Matrix:** Separate libraries, ABS user scoping, daily discovery limits, physical card ownership tracking (`has_physical`), atomic whole-series rotation, and manual **Yoto Card Series & Sequence Overrides**.
* **Device Registration & Remote OTA Firmware Management:** Native zero-PIN hardware onboarding, automatic quarantine, rotating per-device JWTs, Core-hosted firmware repository with 1-click push/rollback OTA updates, and remote Touch MicroSD cache maintenance.
* **Network Proximity & Travel Protection:** Automatically detects whether a Yoto player is on the home network or traveling away, disarming bedtime sleep timers to protect roaming players.

### 🔮 Planned / Future Features
* **Home Assistant MQTT Integration:** Automatic entity discovery for bedtime screen locks, now-playing sensors, and automation switches.
* **Multi-Interval Bedtime & OK-to-Wake Schedules:** Core-synced weekday/weekend schedule overrides for bedside controllers.

---

## 🛠️ Technical Maintenance Notes & Stubborn Facts

> STUBBORN_FACT: `core/bridge/mqtt_client.py` forces `asyncio.SelectorEventLoop()` on `win32` — Windows' default `ProactorEventLoop` raises `NotImplementedError` on `add_reader`/`add_writer` required by `aiomqtt`.

> STUBBORN_FACT: Yoto hardware MQTT and API telemetry report volume on an integer `0–16` scale — Core converts this to `0–100%` for the UI while rendering the full `0–100%` bar with a visual cap marker matching the Yoto App day/night ceiling.

> STUBBORN_FACT: The Parent Portal fetches child profiles from `/api/profiles` rather than `/api/admin/profiles` — `/api/admin/profiles` is `@require_admin`-gated, whereas `/api/profiles` allows LAN guests and `member` accounts to render the avatar carousel without admin cookies.

> STUBBORN_FACT: Every `<input type="password">` in `/admin` must remain enclosed inside a `<form>` element — enforced by browser password-manager compatibility and verified by the unit test suite.

> STUBBORN_FACT: SSO resolution binds permanently to `(sso_provider, sso_subject)` and only falls back to `email`/`username` matching when `sso_subject == ''` — this prevents account hijacking if an upstream IdP recycles a username or a user changes their email address.

> STUBBORN_FACT: The Primary Super Admin (`is_super_admin = 1`, the first admin account created via setup) cannot be edited, demoted, or deleted by other admins (`403`) or removed at the DAO layer — guarantees the instance can never be locked out by a secondary admin.

---

## 🛠️ Quick Start & Deployment

### Option 1: Docker

Run StoryDeck Core directly using official container images from GitHub Container Registry (GHCR):

1. **Create an application directory, `.env`, and `docker-compose.yml`:**
   ```yaml
   services:
     storydeck-core:
       # For latest stable production release:
       image: ghcr.io/yotostorydeck/core:latest
       # For specific releases or dev builds, specify the tag:
       # image: ghcr.io/yotostorydeck/core:v1.1.0
       # image: ghcr.io/yotostorydeck/core:dev
       container_name: storydeck-core
       restart: unless-stopped
       ports:
         - "${PORT:-5055}:5055"
       env_file:
         - .env
       volumes:
         - ./data:/app/data
         - ./cache:/app/cache
   ```

2. **Launch the container:**
   ```bash
   docker compose up -d
   ```

---

### Option 2: Local Development (Python 3.10+)

For local development and testing:

```bash
git clone https://github.com/YotoStoryDeck/core.git
cd core
python -m venv venv

# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Linux / macOS:
# source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env (set SECRET_KEY and optional initial credentials)
python app.py
```

Once running, StoryDeck Core will be available at `http://localhost:5055`:
* **Mobile Parent Portal:** `http://localhost:5055/`
* **Admin Dashboard:** `http://localhost:5055/admin` *(opens `/admin/setup` on first boot)*
* **Tablet Kiosk:** `http://localhost:5055/kiosk/` *(Fully self-contained in `static/kiosk/` — zero external asset dependencies; runs edge-to-edge on iPads, Android tablets, Fire OS, and desktop browsers).*

---

## 🤖 AI Development Notice

This project utilizes artificial intelligence (AI) tools, including Anthropic Claude and Google Gemini / Antigravity, to assist in architectural design, code generation, refactoring, test suite development, and technical documentation. All AI-assisted contributions are human-reviewed, audited, and tested against live and simulated hardware.

---

## 📜 Credits & Acknowledgments

* **Jay Heavner** ([@jayheavner](https://github.com/jayheavner)) for the original [yoto-esp32-controller](https://github.com/jayheavner/yoto-esp32-controller), hardware schematics, and touchscreen UI patterns.
* **Mylacc** ([@mylacc](https://github.com/mylacc)) for the pioneering [yoto-audiobookshelf-bridge](https://github.com/mylacc/yoto-audiobookshelf-bridge) streaming and progress synchronization engine.
* **The Yoto Community** for reverse-engineering and documenting the Yoto API ecosystem.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
