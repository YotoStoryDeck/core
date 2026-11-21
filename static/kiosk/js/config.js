/**
 * Application Configuration & Global Constants
 * Resolves a unique, persistent per-browser Device ID for multi-kiosk registration.
 */
function _generateRandomId() {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return "kiosk-" + crypto.randomUUID().replace(/-/g, "").slice(0, 8);
    }
    if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
      const bytes = new Uint8Array(4);
      crypto.getRandomValues(bytes);
      return "kiosk-" + Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
    }
  } catch { /* fallback below */ }
  return "kiosk-" + Math.random().toString(16).slice(2, 10);
}

function _resolveKioskIdentity() {
  const fallback = {
    deviceId: "kiosk-default",
    friendlyName: "Web Kiosk",
    bookmarkUrl: ""
  };
  if (typeof window === "undefined") return fallback;

  const STORAGE_KEY = "storydeck_kiosk_device_id";
  const params = new URLSearchParams(window.location.search || "");
  const rawUrlId = (params.get("device_id") || "").trim().replace(/[^a-zA-Z0-9._:-]/g, "").slice(0, 48);
  const rawName = (params.get("name") || "").trim().slice(0, 48);

  let deviceId = rawUrlId;
  if (!deviceId) {
    try {
      deviceId = (localStorage.getItem(STORAGE_KEY) || "").trim();
    } catch { /* ignore storage errors */ }
  }
  if (!deviceId) {
    deviceId = _generateRandomId();
  }

  // Persist generated/resolved ID when no conflicting URL override is in use
  try {
    if (!rawUrlId || !localStorage.getItem(STORAGE_KEY)) {
      localStorage.setItem(STORAGE_KEY, deviceId);
    }
  } catch { /* ignore storage errors */ }

  // Sync ?device_id= into the address bar (preserving presets like ?tablet10) so bookmarks keep this UID
  try {
    if (!rawUrlId && window.history && typeof window.history.replaceState === "function") {
      const url = new URL(window.location.href);
      url.searchParams.set("device_id", deviceId);
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  } catch { /* ignore history errors */ }

  const shortTag = deviceId.replace(/^kiosk-/i, "").slice(0, 8).toUpperCase();
  const friendlyName = rawName || `Web Kiosk (${shortTag})`;
  const bookmarkUrl = `${window.location.origin}${window.location.pathname}?device_id=${encodeURIComponent(deviceId)}`;
  return { deviceId, friendlyName, bookmarkUrl };
}

const _identity = _resolveKioskIdentity();

export const CONFIG = {
  BROKER_BASE: (typeof window !== "undefined" && window.location.origin) ? window.location.origin : "http://127.0.0.1:5055",
  DEVICE_ID: _identity.deviceId,
  FRIENDLY_NAME: _identity.friendlyName,
  BOOKMARK_URL: _identity.bookmarkUrl,
  FIRMWARE_VERSION: "1.1.0-web"
};

/**
 * Global Utility Functions
 */
export const Utils = {
  esc: (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;'
  }[c])),

  mmss: (s) => {
    s = Math.max(0, Math.round(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  },

  longdur: (s) => {
    s = Math.round(s || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h ? `${h}h ${m}m` : `${m}m`;
  }
};
