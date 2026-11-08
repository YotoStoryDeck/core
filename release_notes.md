# StoryDeck Core v1.1.0 — Official Release Notes

**Release Tag:** `v1.1.0`  
**Classification:** Full Production Release (Stable)  
**Target Architecture:** Docker (multi-arch `linux/amd64`, `linux/arm64`) & Python 3.12+  
**Release Date:** November 8, 2026  

---

## 📻 Overview

We are thrilled to announce the official **v1.1.0 production release of StoryDeck Core**, the self-hosted orchestration hub for the StoryDeck child-safe smart audio ecosystem!

StoryDeck Core bridges [Audiobookshelf](https://www.audiobookshelf.org/) and [Yoto](https://my.yotoplay.com/), transforming complex digital audio libraries into clean, kid-safe, visual catalogs. Whether powering dedicated bedside touchscreen appliances or communal tablet kiosks, Core provides granular parental curation, PIN-protected security gates, and seamless playback dispatch.

This milestone release establishes production-grade database modularity, introduces the standalone **Tablet Kiosk**, introduces dual-device catalog curation limits, and deploys intelligent upstream version tracking.

---

## 🌟 Major Highlights & New Features

### 1. 🤹 Production Tablet Kiosk (`/kiosk/`)
StoryDeck Core now bundles and serves a fully integrated, zero-dependency Single Page Application (SPA) directly from `static/kiosk/`:
* **Communal Profile Switcher:** Designed for shared family spaces (playrooms, kitchens, living rooms), greeting children with warm, time-aware greetings (*"Good Morning!"*, *"Good Afternoon!"*, *"Good Evening!"*, *"Night Owl 🌙"*) and circular avatar portraits.
* **Header Profile Badge:** Tapping the active child's avatar portrait in the header instantly returns to the profile picker so siblings can take turns without parental intervention.
* **Apple Web App & PWA Standalone Mode:** Built-in manifest and mobile directives automatically remove browser address bars and bottom toolbars when saved to the Home Screen on iPads (Safari) and Android/Fire tablets (Chrome/Edge).
* **Instant Tap-to-PIN Parental Gate:** Replaced long-press timer delays with an instant tap opening the 4-digit PIN security gate, eliminating native browser context menu popovers on touchscreens.
* **Resolution Presets:** Fluid responsive scaling with built-in aspect ratio locks (`?tablet10`, `?tablet8`, `?tablet43`, `?1080p`, or custom `?WIDTHxHEIGHT`).

---

### 2. 🎯 Dual-Profile Curation Limits & The Superset Principle
To solve touchscreen hardware memory constraints while empowering large tablet screens, Core profiles now enforce distinct catalog rotation limits:
* **Bedside Touch Limit (Default: `60` cards):** Caps the active catalog delivered to physical ESP32 controllers to maintain butter-smooth 60fps scrolling and eliminate SPI/DMA memory starvation.
* **Tablet Kiosk Limit (Default: `0` = Unlimited):** Delivers the child's entire allowed library on tablets, or can be capped at any custom positive number.
* **The Superset Principle:** Both devices consume the exact same 6-phase deterministic discovery ranking. When Kiosk is unlimited, the first 60 cards match the bedside controller card-for-card and order-for-order.
* **Atomic Series Clustering:** Books in a series rotate together atomically with Book #1 collection cover precomputation, ensuring children never encounter sequels without Book #1 present.

---

### 3. 🏛️ Modular SQLite Architecture (Schema v9)
The database backend has been refactored from a monolithic script into a clean, domain-driven package under `database/` with backwards-compatible facade exports:
* `database/schema.py`: Automated zero-downtime migration framework (v1 through v9).
* `database/profiles.py`: Granular child profile definitions, avatar colors/monograms, bedtime lockouts, and dual limits.
* `database/devices.py`: Microcontroller and kiosk registration, token management, and settings persistence.
* `database/curation.py`: Matrix permissions, category weights, and rotation algorithms.
* `database/history.py`: Discrete playback history tracking and recently played shelf integration.

---

### 4. 🔒 Zero-Trust Device Quarantine & JWT Security
* **Automatic Quarantine:** All newly discovered ESP32 controllers and virtual kiosks boot into quarantine by default until approved by an administrator in the Web Admin portal.
* **Ephemeral Rotating Device JWTs:** Approved devices receive short-lived cryptographic tokens signed with per-device secrets, with automated token refresh cycles.
* **Instant Revocation:** Deleting a device from the database instantly revokes all active and refresh tokens across the network.
* **Condensed Hardware Displays Dashboard:** Streamlined table featuring stacked Network & Hardware IDs (IP on top, MAC/UUID below), visual Device Type badges (📟 `ESP32 Touch` vs. 🖥️ `Tablet Kiosk`), engine version pills, and interactive Status badge dropdown menus (`● Approved ▾` / `⚠️ Quarantined ▾`).

---

### 5. ✈️ Network Proximity & Travel Safety
* **WAN Egress IP Matching:** Detects whether physical Yoto players and controllers reside on the local home network or are traveling remotely.
* **Travel Interlock Protection:** Displays `✈️ AWAY` indicators and guards against accidentally starting audio playback on players currently away from home with family members.

---

### 6. 📦 Core Version Tracking & Soft Update Checker (DLP-022)
* **Startup Identification:** Container and server boots now display an official startup banner:
  ```text
  ============================================================
   📻 StoryDeck Core Engine - Version: v1.1.0
  ============================================================
  ```
* **Soft GitHub Release Probe:** Non-blocking background service checks GitHub Releases with a 6-hour in-memory cache and 3.5s timeout, guaranteeing zero slowdowns on offline or rate-limited homelabs.
* **Admin Portal Alerts:** Displays a persistent version pill in the top navigation header (`#coreVersionBadge`) with animated gold pulse notifications when an update is available, paired with a dedicated System & Version card in the Settings tab.

---

## 🚀 Deployment & Upgrade Guide

### Docker Compose Configuration

Update your `docker-compose.yml` to target the stable production release:

```yaml
services:
  storydeck-core:
    image: ghcr.io/yotostorydeck/core:v1.1.0 # Or :latest for automatic stable updates
    container_name: storydeck-core
    restart: unless-stopped
    ports:
      - "5055:5055"
    environment:
      - PORT=5055
      - ABS_BASE_URL=http://audiobookshelf:80
      - ABS_API_KEY=${ABS_API_KEY}
      - YOTO_BRIDGE_URL=http://yoto-bridge:8080
      - YOTO_CLIENT_ID=${YOTO_CLIENT_ID}         # Required if running without Bridge
      - YOTO_CLIENT_SECRET=${YOTO_CLIENT_SECRET} # Required if running without Bridge
      - YOTO_REFRESH_TOKEN=${YOTO_REFRESH_TOKEN} # Required if running without Bridge
      - CACHE_DIR=/app/cache/thumbnails
      - DB_PATH=/app/data/broker.db
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/app/data
      - ./cache:/app/cache
```

### Performing the Upgrade

Pull the new image and recreate the container:

```bash
docker compose pull
docker compose up -d
```

Core will automatically apply SQLite schema migration v9 on initial boot without requiring manual database interventions.

---

## 📋 System Compatibility

| Component | Minimum Version | Recommended | Notes |
| :--- | :--- | :--- | :--- |
| **StoryDeck Touch Firmware** | `v0.1.0` | `v0.1.0` | Physical ESP32-S3 bedside appliance |
| **Audiobookshelf** | `v2.4.0` | `v2.10.0+` | Upstream audiobook and podcast server |
| **Yoto-Audiobookshelf-Bridge** | `v1.2.0` | `v1.4.0+` | Optional real-time audio transcoding engine |
| **Container Engine** | Docker 20.10+ | Docker 26.0+ | Docker Compose v2 required |

---

## 🤝 Contributors & Ecosystem Links

* **Core Hub Repository:** [github.com/YotoStoryDeck/core](https://github.com/YotoStoryDeck/core)
* **Touch Controller Repository:** [github.com/YotoStoryDeck/touch](https://github.com/YotoStoryDeck/touch)
* **Documentation & Specifications:** [github.com/alicia86/projects/tree/main/yotostorydeck](https://github.com/alicia86/projects/tree/main/yotostorydeck)
* **Web Flasher for Touch Hardware:** [yotostorydeck.github.io/touch/](https://yotostorydeck.github.io/touch/)
