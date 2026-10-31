# Feature Specification: ESP32 Firmware Adaptive Catalog Tabs (Screen 2)
**Document ID:** `004-esp32_firmware_adaptive_catalog_tabs`  
**Status:** Approved  
**Component:** ESP32 Firmware UI & Image Streaming  
**Target Hardware:** Waveshare ESP32-S3-Touch-LCD-4.3B (800×480)  

---

## 1. Executive Summary & Purpose
The primary browsing interface on the bedside controller is the **Catalog Screen (Screen 2)**. In Jay Heavner's upstream implementation, this was a single scrollable grid showing only native Yoto cards.

This feature specification enhances Screen 2 into an **Adaptive Dual-Source Catalog**:
1. **Adaptive Tab Control:** Inspects the broker's `/health` flags. If Audiobookshelf is enabled, renders two top tabs: **Yoto Cards** and **Audiobooks**. If ABS is disabled, automatically suppresses the tab bar and presents the original single-grid Yoto view.
2. **High-Performance 4-Column Grid:** Displays 100×100px square cover art tiles with truncated title labels below.
3. **Streaming Memory Optimization:** Utilizes `TJpgDec` to decompress incoming HTTP JPEG streams chunk-by-chunk directly into PSRAM image buffers, preventing internal SRAM heap fragmentation.

---

## 2. Technical Entity Mapping & API Contracts

### 2.1 Broker Endpoints Consumed
* **Health Check:** `GET /health` (Reads `features.abs_enabled`).
* **ABS Audiobooks Catalog:** `GET /api/kids/<active_profile>/abs`
* **Curated Yoto Cards Catalog:** `GET /api/kids/<active_profile>/yoto`
* **Cover Thumbnail Stream:** `GET /api/thumb?type=abs&id=<id>&size=100` (or `type=yoto&url=<url>&size=100`)
* **Admin Playlist Curation:** `GET /api/admin/yoto/cards` and `PUT /api/admin/yoto/cards`

### 2.2 Audiobookshelf (ABS) Child Catalog Scoping Model

> [!IMPORTANT]
> **Account Architecture & Zero-Friction Token Resolution:**
> * **Automatic Child Account Scoping (`abs_username`):** The broker uses its master Audiobookshelf API key to query the server's user registry (`GET /api/users`), automatically resolving and caching the child's Bearer token in-memory. Parents do **NOT** need to generate, copy, or paste individual child API tokens!
> * **Native Audiobookshelf Permission Enforcement:** When querying the library as the child account, the Audiobookshelf server automatically scopes the catalog to the child's allowed libraries, allowed/disallowed tags (e.g. `'Children'`), and explicit content restrictions, while independently tracking per-child playback progress, bookmarks, and last-listened positions.
> * **Manual Override & Fallback (`abs_api_key` / `abs_token`):** If an advanced user specifies a custom child API token directly, the broker honors that token. If no child account is bound, the broker queries via the master `ABS_API_KEY`.

The broker resolves audiobooks for `GET /api/kids/<profile>/abs` through a flexible, multi-mode catalog scoping hierarchy:

1. **Auto-Resolved Child Account Token (`abs_username`):**
   - The broker automatically retrieves the child's user token from Audiobookshelf and queries `/api/libraries` and `/api/libraries/{lib}/items`.
   - The Audiobookshelf server natively enforces user permissions, allowed tags, and explicit content limits.
2. **Dedicated Children's Library ID (`abs_library_id`):**
   - For setups using dedicated kids' libraries (e.g. *"Kids Audiobooks"* or *"Bedtime Stories"*), the profile can optionally specify `abs_library_id`.
   - The broker limits scanning strictly to that specified library ID.
3. **Item Tag Filtering Override (`abs_tag`):**
   - If configured as an advanced override, the broker additionally filters books within the available library by tag.
   - If omitted, the child's native server-side tag permissions (configured directly in Audiobookshelf) govern catalog availability.

### 2.3 Yoto Curation & Playlist Filtering Architecture

The broker acts as a curation gateway between Yoto's unified family library (`https://api.yotoplay.com/card/family/library` or [yoto.dev/api](https://yoto.dev/api/)) and the child's bedside controller, backed by the broker's relational **SQLite database (`/data/broker.db`)**:

When `GET /api/kids/<profile>/yoto` is called:
1. **Shared Cards Base:** If `shared_yoto.include_all` is true, all household cards form the base. Otherwise, only cards matching `shared_yoto.allowed_card_ids`, matching `shared_yoto.match_titles` regexes, or having `isMyo: true` (if `include_myo_by_default` is enabled) are included.
2. **Profile Overrides:** If `profile.yoto.inherit_shared` is true, shared cards are merged with `child.allowed_card_ids` and `child.match_titles`. If false, only child-specific cards are allowed.
3. **Strict Exclusions:** Any card listed in `child.excluded_card_ids` is stripped from the final payload, preventing younger siblings from seeing older kids' or parents' content.
4. **Highlights & Seasonal Pinning:** Items flagged with `is_highlight = 1` in SQLite are pinned to the top row of the catalog response for seasonal rotations (e.g., Halloween, Christmas, or Summer Reading).
5. **Sanitization & Truncation:** Cards are sorted alphabetically (with highlights first) and formatted with 100x100 thumbnails for the ESP32 grid.

---

## 3. UI Blueprint & Component Layout

### 3.1 Display Layout (800×480 Landscape)

```text
+-----------------------------------------------------------------------------+
|  [ 👤 Child One ]     [ YOTO CARDS ]   [ AUDIOBOOKS ]          [ 🕒 8:16 PM] |
+-----------------------------------------------------------------------------+
|                                                                             |
|   +-----------+     +-----------+     +-----------+     +-----------+       |
|   |  [COVER]  |     |  [COVER]  |     |  [COVER]  |     |  [COVER]  |       |
|   |  100x100  |     |  100x100  |     |  100x100  |     |  100x100  |       |
|   +-----------+     +-----------+     +-----------+     +-----------+       |
|    The Hobbit        Peter Pan         Lion & Witch      Wind in Willows    |
|                                                                             |
|   +-----------+     +-----------+     +-----------+     +-----------+       |
|   |  [COVER]  |     |  [COVER]  |     |  [COVER]  |     |  [COVER]  |       |
|   |  100x100  |     |  100x100  |     |  100x100  |     |  100x100  |       |
|   +-----------+     +-----------+     +-----------+     +-----------+       |
|    Charlotte's Web   Secret Garden     Treasure Island   Matilda            |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 3.2 Component Coordinates & Styling Table
| Component | LVGL Widget | Dimensions / Position | Styling / Theme |
| :--- | :--- | :--- | :--- |
| **Top Header Bar** | `lv_obj_create` | `W=800, H=50, X=0, Y=0` | `#1A1A1A`, bottom border `#333333`. |
| **Tab Selector** | `lv_btnmatrix` | `W=360, H=38, X=220, Y=6` | Rounded pills; active tab `#E53935` (Yoto red), inactive `#2A2A2A`. |
| **Scroll Container** | `lv_obj_create` | `W=800, H=430, X=0, Y=50` | Transparent background, vertical scrolling enabled (`LV_SCROLL_DIR_VER`). |
| **Grid Cell Tile** | `lv_btn` | `W=170, H=180` | Centered 100×100 cover art canvas + 2-line label below. |
| **Cover Art** | `lv_canvas` / `lv_img` | `W=100, H=100, X=35, Y=10` | 1:1 aspect ratio, rounded corners `8px`. |
| **Title Label** | `lv_label` | `W=160, H=40, X=5, Y=115` | Font `lv_font_montserrat_14`, `#E0E0E0`, centered, wrap enabled. |

---

## 4. Streaming Image Decompression Pipeline

To ensure the ESP32 can render 40+ books without exhausting the 8 MB PSRAM or crashing due to heap fragmentation:

```mermaid
flowchart LR
    HTTPStream["HTTP GET Stream (/api/thumb)"] --> StreamBuffer["1 KB Chunk Buffer"]
    StreamBuffer --> TJpgDec["TJpgDec Decoder Engine"]
    TJpgDec --> LineBuffer["RGB565 Scanline Buffer"]
    LineBuffer --> PSRAMCanvas["PSRAM Frame Canvas (100x100x2 = 20 KB)"]
    PSRAMCanvas --> LVGLRender["LVGL Screen Draw"]
```

1. **Direct Stream Feeding:** Data from `WiFiClient` is fed directly into `TJpgDec` input callback.
2. **Fixed Memory Footprint:** Exactly 20,000 bytes (100×100×2 bytes) allocated in PSRAM per visible card tile.
3. **Tile Recyling:** Tiles offscreen release or reuse memory during long scrolls.

---

## 5. Verification & Acceptance Criteria
1. Switching tabs between Yoto Cards and Audiobooks reloads the grid in under 1 second.
2. Scrolling is smooth at 60 Hz without visual tearing or DMA underrun glitches.
3. When `ABS_API_KEY` is empty, tab bar is hidden and native Yoto grid renders identically to upstream.
