# Deployment & Operations Guide: Yoto-ESP32 Middleware Broker

## 1. Prerequisites & Ecosystem Architecture
This broker connects your hardware controller to your media server and streaming infrastructure:

* **Hardware Controller:** An ESP32-S3 touchscreen appliance running the adapted [jayheavner/yoto-esp32-controller](https://github.com/jayheavner/yoto-esp32-controller) firmware.
* **Audio Streaming Bridge:** An instance of [mylacc/yoto-audiobookshelf-bridge](https://github.com/mylacc/yoto-audiobookshelf-bridge) running on your local network (handles live MP3 transcoding and MQTT progress syncing to Audiobookshelf).
* **Audiobookshelf:** Version 2.4.0+ running locally or accessible via HTTP.
* **Yoto Developer App:** A registered personal application at [dashboard.yoto.dev](https://dashboard.yoto.dev) for family library and device control access.
* **Docker Engine:** Version 24.0+ with Docker Compose v2 on any Linux host, VM, or SBC.

---

## 2. Quickstart Deployment

### Step 1: Directory Setup
Clone or copy the broker into your home server's application directory:

```bash
mkdir -p /opt/yoto-esp32-broker/data /opt/yoto-esp32-broker/cache
cd /opt/yoto-esp32-broker
```

### Step 2: Environment Configuration (`.env`)
Create `.env` using generic placeholders:

```ini
# ==============================================================================
# Yoto-ESP32 Middleware Broker Environment
# ==============================================================================

PORT=5055
LOG_LEVEL=INFO

# Audiobookshelf Server
# Use internal Docker container name if in same network, or local LAN IP
ABS_BASE_URL=http://192.168.1.100:1337
ABS_API_KEY=your_abs_service_api_key_here

# Yoto Developer Application Credentials (https://dashboard.yoto.dev)
YOTO_CLIENT_ID=your_yoto_client_id_here
YOTO_CLIENT_SECRET=your_yoto_client_secret_here
YOTO_REFRESH_TOKEN=your_oauth_refresh_token_here

# Optional: Yoto-Audiobookshelf Bridge (for ABS streaming and fallback chapter icons)
YOTO_BRIDGE_URL=http://192.168.1.100:8090

# Performance & Caching
CACHE_DIR=/app/cache/thumbnails
THUMBNAIL_SIZE=100

# ==============================================================================
# Optional: Multi-Platform AI Chapter Artwork Generation
# ==============================================================================
# Master Toggle: true | false (default: false)
# When false or unconfigured, chapter artwork gracefully falls back to Yoto ABS Bridge icons.
AI_CHAPTER_ART_ENABLED=false

# Active Provider: gemini | claude | openrouter
AI_PROVIDER=openrouter

# 1. Google Gemini / Antigravity
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# 2. Anthropic Claude
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# 3. OpenRouter (Unified multi-model API)
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=stabilityai/stable-diffusion-xl-base-1.0

# Optional: Admin Authentication & Reverse-Proxy SSO
# (If unset, first-run wizard prompts at /admin/setup; proxy headers auto-bypass only from TRUSTED_PROXIES)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=

# Security & Reverse Proxy Access Control
# Subnets or IPs permitted to pass SSO identity headers (e.g. X-authentik-username)
TRUSTED_PROXIES=127.0.0.1,192.168.1.10,172.18.0.0/16
```

### Step 3: Seed Configuration / Initial Bootstrap (`data/config.json`)
The broker uses an embedded **SQLite database (`/data/broker.db`)** for all runtime state, profiles, and curation rules. You can provide a seed `/opt/yoto-esp32-broker/data/config.json` on initial boot, which will automatically migrate into SQLite:

```json
{
  "shared_yoto": {
    "include_all": false,
    "include_myo_by_default": true,
    "allowed_card_ids": ["card_disney_classics"],
    "match_titles": ["^Bedtime.*", ".*\\[All\\].*"]
  },
  "profiles": {
    "child_one": {
      "display_name": "Child One",
      "abs_api_key": "child_user_specific_abs_key",
      "abs_library_id": "lib_kids_audiobooks_id",
      "abs_tag": "child_one",
      "default_player_id": "y2_sample_player_id_1",
      "player_ids": ["y2_sample_player_id_1", "y2_sample_player_id_2"],
      "yoto": {
        "inherit_shared": true,
        "allowed_card_ids": ["card_paw_patrol_01"],
        "excluded_card_ids": ["card_older_sibling_spooky"],
        "match_titles": [".*\\[Child One\\].*"]
      }
    },
    "child_two": {
      "display_name": "Child Two",
      "abs_api_key": "",
      "abs_library_id": "lib_kids_audiobooks_id",
      "abs_tag": "child_two",
      "default_player_id": "y2_sample_player_id_3",
      "player_ids": ["y2_sample_player_id_3"],
      "yoto": {
        "inherit_shared": true,
        "allowed_card_ids": ["card_older_sibling_spooky"],
        "excluded_card_ids": [],
        "match_titles": [".*\\[Child Two\\].*"]
      }
    }
  },
  "settings": {
    "thumbnail_size": 100,
    "thumbnail_quality": 80,
    "cache_ttl_hours": 168,
    "ai_chapter_art": {
      "enabled": false,
      "provider": "openrouter",
      "fallback_to_bridge": true
    }
  }
}
```

> [!TIP]
> After first startup, all changes should be managed directly through the **Web Admin Curation Dashboard (`http://<broker-ip>:5055/admin`)**, which saves immediately to SQLite without requiring container restarts.

### Step 4: Docker Compose Manifest (`docker-compose.yml`)
```yaml
services:
  yoto-esp32-broker:
    image: python:3.12-slim
    container_name: yoto-esp32-broker
    restart: unless-stopped
    working_dir: /app
    ports:
      - "5055:5055"
    environment:
      - PORT=5055
      - ABS_BASE_URL=${ABS_BASE_URL}
      - ABS_API_KEY=${ABS_API_KEY}
      - YOTO_CLIENT_ID=${YOTO_CLIENT_ID}
      - YOTO_CLIENT_SECRET=${YOTO_CLIENT_SECRET}
      - YOTO_REFRESH_TOKEN=${YOTO_REFRESH_TOKEN}
      - YOTO_BRIDGE_URL=${YOTO_BRIDGE_URL}
      - CACHE_DIR=/app/cache/thumbnails
      - THUMBNAIL_SIZE=100
      - AI_CHAPTER_ART_ENABLED=${AI_CHAPTER_ART_ENABLED:-false}
      - AI_PROVIDER=${AI_PROVIDER:-openrouter}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - GEMINI_MODEL=${GEMINI_MODEL:-gemini-2.5-flash}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - ANTHROPIC_MODEL=${ANTHROPIC_MODEL:-claude-3-5-sonnet-20241022}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
      - OPENROUTER_MODEL=${OPENROUTER_MODEL:-stabilityai/stable-diffusion-xl-base-1.0}
      - TRUSTED_PROXIES=${TRUSTED_PROXIES:-127.0.0.1}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - ./data:/app/data
      - ./cache:/app/cache
    command: >
      sh -c "pip install --no-cache-dir flask requests pillow gunicorn python-dotenv &&
             gunicorn --bind 0.0.0.0:5055 --workers 2 --threads 4 --timeout 60 app:app"
```

### Step 5: Start the Container
```bash
docker compose up -d
docker compose logs -f yoto-esp32-broker
```

---

## 3. Security, Reverse Proxy & Onboarding Operations

### First-Run Admin Setup (`/admin/setup`)
When the container starts with an empty SQLite database, the web portal operates in **First-Run Onboarding Mode**:
1. Open `http://<broker-ip>:5055/admin` in any browser.
2. The UI automatically redirects to `/admin/setup`.
3. Enter your initial administrator username and a strong password. Credentials are encrypted and hashed into `/data/broker.db` (`admin_users` table).
4. Upon successful setup, the open wizard is permanently sealed.

### Reverse Proxy & SSO Integration (Authentik, Cloudflare Access)
To protect your broker behind an external reverse proxy (e.g. Nginx Proxy Manager, Traefik, or Caddy) with SSO headers (`X-authentik-username` or `Cf-Access-Authenticated-User-Email`):
* Configure `TRUSTED_PROXIES` in `.env` to match the exact internal IP or Docker network CIDR of your reverse proxy.
* If a request originates from an untrusted client attempting to inject authentication headers, the broker rejects the header and enforces local password authentication.

### ESP32 Device Registration & Quarantine Gate
* When a new ESP32 bedside controller boots on your network, it automatically announces itself via `POST /api/devices/register`.
* The broker enters the device into an **Unapproved / Quarantined** state (`is_approved = 0`).
* Open the **Hardware** tab in the Admin Web Portal to review the device, assign it a friendly name and default child profile, and click **Approve Device**. Until approved, the device cannot pull child catalogs or issue playback commands.

---

## 4. Verification & Validation Steps

### 1. Test Health Probe
```bash
curl -s http://localhost:5055/health | jq .
```
Expected output:
```json
{
  "status": "healthy",
  "abs_configured": true,
  "yoto_configured": true,
  "yoto_bridge_url": "http://192.168.1.100:8090",
  "timestamp": 1792650000
}
```

### 2. Test Profile Discovery
```bash
curl -s http://localhost:5055/api/profiles | jq .
```

### 3. Test ABS Tag Filtering
```bash
curl -s http://localhost:5055/api/kids/child_one/abs | jq .
```

### 4. Test Thumbnail Resizing & Caching
```bash
curl -I "http://localhost:5055/api/thumb?type=abs&id=<sample_book_id>&size=100"
```
Verify that the response returns `HTTP/1.1 200 OK` with `Content-Type: image/jpeg`, and verify the file is stored under `./cache/thumbnails/`.
