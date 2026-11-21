/* ==============================================================================
   YOTO & AUDIOBOOKSHELF CONTROLLER ADMIN PORTAL (ES6 SPA CLIENT)
   Handles auth lifecycle, profile CRUD, curation matrix, hardware, diagnostics.
   ============================================================================== */

let currentUser = null;
let currentProfiles = {};
let currentMatrix = { items: [], profiles: [], shared_rules: {} };
let currentDevices = [];
let cachedAbsServerTags = [];
let configuredDefaultChildTags = ["Children"];
let selectedMatrixItemIds = new Set();
let lastCheckedMatrixIndex = -1;

const AVATAR_PALETTE = [
  "#3b82f6",  // Blue
  "#ef4444",  // Red
  "#10b981",  // Emerald
  "#f59e0b",  // Amber
  "#8b5cf6",  // Purple
  "#ec4899",  // Pink
  "#06b6d4",  // Cyan
  "#f97316",  // Orange
  "#14b8a6",  // Teal
  "#6366f1"   // Indigo
];

// Lifecycle Boot
document.addEventListener("DOMContentLoaded", () => {
  checkAuthStatus();
});

window.currentSsoMeta = {};
let initialDataLoaded = false;

window.addEventListener("storydeck:core-status", (e) => {
  if (e && e.detail && e.detail.recovered) {
    showToast("StoryDeck Core server reconnected.", "success");
    checkAuthStatus();
  }
});

// HTML escape helper
function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Global helper to populate ABS server tag dropdowns across views and modals
function populateAbsServerTagsDropdowns() {
  const settingsSelect = document.getElementById("absServerTagsDropdown");
  if (settingsSelect) {
    settingsSelect.innerHTML = '<option value="">-- Choose from Audiobookshelf tags --</option>';
    cachedAbsServerTags.forEach(tag => {
      const opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag;
      settingsSelect.appendChild(opt);
    });
  }

  const modalSelect = document.getElementById("curationModalTagDropdown");
  if (modalSelect) {
    modalSelect.innerHTML = '<option value="">-- Add another ABS tag --</option>';
    cachedAbsServerTags.forEach(tag => {
      const opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag;
      modalSelect.appendChild(opt);
    });
  }
}

// Toast notification helper
function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// ============================================================================
// Auth & Setup Lifecycle
// ============================================================================

async function checkAuthStatus() {
  try {
    const res = await fetch("/api/admin/auth/status", { cache: "no-store" });
    if (res.status === 502 || res.status === 503 || res.status === 504 || !res.ok) {
      if (window.StoryDeckHealth) {
        window.StoryDeckHealth.reportNetworkError(`Core gateway returned HTTP ${res.status}.`);
      }
      return;
    }
    const data = await res.json();
    window.currentSsoMeta = data.sso || {};

    const ssoNoticeEl = document.getElementById("loginSsoNotice");
    if (ssoNoticeEl) {
      if (window.currentSsoMeta.forward_auth_enabled) {
        const prov = window.currentSsoMeta.provider_name || "Authentik";
        ssoNoticeEl.style.display = "block";
        ssoNoticeEl.innerText = `🛡️ Reverse-proxy ForwardAuth (${prov}) is enabled. Accessing via your SSO gateway signs you in automatically.`;
      } else {
        ssoNoticeEl.style.display = "none";
      }
    }

    if (data.setup_required) {
      document.getElementById("setupModal").style.display = "flex";
      document.getElementById("loginModal").style.display = "none";
      document.getElementById("mainApp").style.display = "none";
      document.getElementById("headerUserSection").style.display = "none";
    } else if (!data.authenticated) {
      document.getElementById("setupModal").style.display = "none";
      document.getElementById("loginModal").style.display = "flex";
      document.getElementById("mainApp").style.display = "none";
      document.getElementById("headerUserSection").style.display = "none";
    } else {
      currentUser = data.user;
      document.getElementById("setupModal").style.display = "none";
      document.getElementById("loginModal").style.display = "none";
      document.getElementById("mainApp").style.display = "flex";
      document.getElementById("headerUserSection").style.display = "flex";

      const displayName = currentUser.display_name || currentUser.username;
      document.getElementById("userGreeting").innerText = `Welcome, ${displayName}`;

      const authBadge = document.getElementById("userAuthBadge");
      const sidebarName = document.getElementById("sidebarAdminName");
      const sidebarRole = document.getElementById("sidebarAdminRole");
      let authText = "Local";
      let authBadgeClass = "badge badge-subtle";
      if (currentUser.auth_type === "sso") {
        authText = `SSO: ${currentUser.sso_provider || window.currentSsoMeta.provider_name || "Authentik"}`;
        authBadgeClass = "badge badge-info";
      } else if (currentUser.auth_type === "api_key") {
        authText = "API Key";
        authBadgeClass = "badge badge-warning";
      }
      if (authBadge) {
        authBadge.style.display = "inline-flex";
        authBadge.className = authBadgeClass;
        authBadge.innerText = authText;
      }
      if (sidebarName) sidebarName.innerText = displayName;
      if (sidebarRole) sidebarRole.innerText = `${authText} · Admin`;

      if (!initialDataLoaded) {
        initialDataLoaded = true;
        loadInitialData();
      }
    }
  } catch (err) {
    console.error("Auth check failed:", err);
    if (window.StoryDeckHealth) {
      window.StoryDeckHealth.reportNetworkError("Cannot reach StoryDeck Core server to verify authentication.");
    }
  }
}

async function handleInitialSetup(e) {
  e.preventDefault();
  const username = document.getElementById("setupUsername").value.trim();
  const displayName = document.getElementById("setupDisplayName").value.trim() || "Parent";
  const password = document.getElementById("setupPassword").value;

  try {
    const res = await fetch("/api/admin/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, display_name: displayName, password })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Primary administrator account created successfully!", "success");
      // Proceed to login
      await handleAutoLogin(username, password);
    } else {
      showToast(data.error || "Setup failed.", "danger");
    }
  } catch (err) {
    showToast("Network error during setup.", "danger");
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  await handleAutoLogin(username, password);
}

async function handleAutoLogin(username, password) {
  try {
    const res = await fetch("/api/admin/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Signed in successfully.", "success");
      initialDataLoaded = false;
      checkAuthStatus();
    } else {
      showToast(data.error || "Invalid username or password.", "danger");
    }
  } catch (err) {
    showToast("Sign in failed. Check connection.", "danger");
  }
}

async function logout() {
  const wasSso = Boolean(currentUser && currentUser.auth_type === "sso");
  const ssoLogoutUrl = (window.currentSsoMeta && window.currentSsoMeta.logout_url) ? window.currentSsoMeta.logout_url.trim() : "";
  try {
    await fetch("/api/admin/auth/logout", { method: "POST" });
    initialDataLoaded = false;
    if (wasSso && ssoLogoutUrl) {
      window.location.href = ssoLogoutUrl;
      return;
    }
    showToast("Signed out.");
    checkAuthStatus();
  } catch (err) {
    location.reload();
  }
}
