# Yoto Developer App & OAuth Token Setup Guide

This guide explains how Yoto OAuth 2.0 authentication works, whether your broker must be exposed externally, and step-by-step instructions for obtaining tokens for both **Public Clients** (PKCE) and **Confidential Clients**.

---

## 1. Must the Broker Be Exposed Externally?

### **Short Answer:**
- **No, the broker does NOT need to be exposed to the public internet** to authenticate with Yoto or to communicate with your ESP32 bedside controllers on your local LAN.
- The only time external HTTPS exposure is necessary is if you want physical Yoto players to stream audio when they are **outside your home Wi-Fi network** (e.g. car hotspot, vacation, or cellular tether).

### **Why Public Exposure Is Not Required for OAuth:**
1. **OAuth Callbacks happen in your browser, not from Yoto's servers directly to your server.**
   - In standard OAuth 2.0 (Authorization Code flow with or without PKCE), after you click "Approve" on Yoto's website (`login.yotoplay.com`), Yoto instructs **your browser** (your phone or desktop PC) to redirect to the configured Callback URL.
   - If your callback URL is `http://127.0.0.1:8787/callback` or `http://192.168.1.50:5055/callback`, your browser initiates the HTTP request to that local IP. Yoto's cloud servers never make an inbound connection to your home network.
2. **Yoto API Calls (`api.yotoplay.com`) are Outbound:**
   - When the broker queries playlists, controls volume, or triggers playback, the broker makes standard **outbound HTTPS requests** to Yoto. Standard home NAT/firewalls handle this without open ports.

---

## 2. Public Client vs. Confidential Client

When creating an app on [dashboard.yoto.dev](https://dashboard.yoto.dev):

| Feature | **Public Client** (Recommended by Yoto) | **Confidential Client** (Server-to-Server) |
|---|---|---|
| **Client Secret** | None (public apps cannot safely hide secrets) | Yes (`client_secret` issued) |
| **Auth Flow** | Authorization Code + PKCE | Authorization Code or Client Credentials |
| **Token Refresh** | Uses `client_id` + `refresh_token` (No secret needed) | Uses `client_id` + `client_secret` + `refresh_token` |
| **External URL Needed?** | **No** (Localhost loopback or LAN IP is supported) | **No** (Localhost loopback or LAN IP is supported) |
| **Enforced Protocol** | Yoto dashboard UI suggests `https://`, but allows loopback `http://127.0.0.1:...` | Yoto dashboard UI suggests `https://`, but allows loopback `http://127.0.0.1:...` |

---

## 3. Step-by-Step: Creating Your Yoto App (dashboard.yoto.dev)

1. Navigate to **[dashboard.yoto.dev](https://dashboard.yoto.dev)** and sign in with the primary Yoto parent account managing your household players.
2. Click **Create Application**.
3. Choose **Public Client** (or Confidential if you prefer managing a client secret).
4. Set the **Application Name** (e.g., `Home Bedside Broker`).
5. Under **Scopes**, select the following:
   - ✅ `family:library:view` (*Required* – View the library of commercial and family Yoto cards)
   - ✅ `user:content:manage` (*Required* – View, create, and manage Make Your Own cards/playlists)
   - ✅ `family:devices:view` (*Required* – Discover players linked to your family and battery/online status)
   - ✅ `family:devices:control` (*Required* – Remotely command and monitor Yoto players, start tracks, and volume)
   - ✅ `offline_access` (*Required* – Retain persistent access via Refresh Token so you don't have to re-login)
   - ℹ️ `user:content:view` *(Included automatically by Yoto)*
   - ℹ️ `user:icons:manage` *(Included automatically by Yoto)*
   - ❌ `family:library:manage` *(Not needed – prevents accidental deletion of library cards)*
   - ❌ `family:devices:manage` *(Not needed – covers Wi-Fi setup and renaming)*
6. Under **Allowed Callback URLs**, paste the following (comma-separated):
   ```
   http://127.0.0.1:8787/callback, http://127.0.0.1:8090/s/yoto-callback, http://127.0.0.1:5055/s/yoto-callback
   ```
   > ⚠️ **IMPORTANT OAuth Rule:** Yoto's Auth0 identity service enforces **RFC 8252** for Public Clients. It strictly **forbids plain HTTP IP addresses (like `http://192.168.1.11:...`)**. Any non-loopback URL **MUST** be HTTPS (e.g. `https://yoto.yourdomain.com/s/yoto-callback`). For local non-HTTPS setups, you **MUST use `http://127.0.0.1:...`**.
7. Click **Save Changes** and copy your **Client ID**.

---

## 4. Setup Architecture: Bridge-First vs. Standalone Broker

### **Option 1: Bridge-First Integration (Strongly Recommended)**
* **Client Type Required:** **`Public Client` ONLY**
  *(The `yoto-audiobookshelf-bridge` codebase is hardcoded to OAuth PKCE and does not support confidential clients or client secrets).*
* **How It Operates:** The bridge acts as the sole client to Yoto. The broker needs zero direct Yoto credentials and communicates entirely through the bridge over your local network.

**Configuration Steps:**
1. On [dashboard.yoto.dev](https://dashboard.yoto.dev), create your app as a **Public Client**.
2. Under **Allowed Callback URLs**, add your bridge callback:
   - `http://<bridge-host-ip>:8090/s/yoto-callback` (or your reverse-proxy URL).
3. In `yoto-audiobookshelf-bridge/data/config.yaml`, set your `yoto_client_id`:
   ```yaml
   yoto_client_id: "your_client_id"
   ```
4. Open the Bridge web interface (`http://<host-ip>:8090`), click **Connect Yoto**, and approve.
5. In the Broker Admin Portal (`http://<host-ip>:5055/admin` → Tab 4):
   - Set **Yoto-ABS Bridge URL**: `http://yoto-bridge:8080` (or LAN IP).
   - Leave `YOTO_CLIENT_ID`, `YOTO_CLIENT_SECRET`, and `YOTO_REFRESH_TOKEN` **blank**.
   - Click **Save API Credentials**, then click **Test Bridge Connection**.
6. **Key Advantage:** Eliminates all token rotation issues.

---

### **Option 2: Standalone Broker Direct Cloud (No Bridge)**
* **Client Type Implemented:** **`Public Client` (Recommended)** or **`Confidential Client`**
  *(The broker's built-in OAuth engine supports both. Public Client is recommended by Yoto because it uses PKCE and does not require managing client secrets).*
* **How It Operates:** The broker talks directly to Yoto Developer Cloud to query family cards and send playback commands.

**Configuration Steps:**
1. On [dashboard.yoto.dev](https://dashboard.yoto.dev), create your app as a **Public Client** (or Confidential Client if you prefer managing a secret).
2. Under **Allowed Callback URLs**, add your broker's callback:
   - `http://<broker-ip>:5055/s/yoto-callback` or `http://localhost:5055/s/yoto-callback`
3. Open the Broker Web Admin Portal (`/admin` → Tab 4: **Diagnostics & Settings**).
4. Enter your **Client ID** under the Yoto Developer App card (leave Client Secret blank if Public Client).
5. Click **⚡ Connect Yoto in Browser**.
6. Sign in on the secure popup and click **Allow**.
7. The browser automatically completes the PKCE exchange, stores your `refresh_token` in SQLite, and hot-reloads the service!
8. Click **Test Yoto Cloud** to confirm your active connection.

---

## 5. Summary & Best Practices
- **Security:** Never expose the Admin Panel or raw `/api/` endpoints to the public internet without an authenticating reverse proxy (e.g. Authelia, Authentik, or Cloudflare Access).
- **Zero Token Clashing:** By letting the Bridge handle Yoto OAuth, the broker stays completely isolated from token lifecycle churn.

