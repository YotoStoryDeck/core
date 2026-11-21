// ==============================================================================
// StoryDeck Parent-First Mobile Front Portal Script
// ==============================================================================

let currentProfiles = {};
let profileList = [];
let activeProfileId = "";
let currentDevices = [];
let activeDeviceId = "";
let libraryItems = [];
let cardSlots = [];
let cloudPlaylists = [];
let activeBook = null;
let householdYotoCards = [];
let currentPlaylistFilter = "all";
let currentVolumeMax = 100;
let pollInterval = null;
let isScrubbing = false;
let yotoTokenValid = true;
let authCheckInterval = null;

const PORTAL_PROFILE_STORAGE_KEY = "storydeck_portal_profile";
const PORTAL_TAB_TITLES = {
  player: "Player",
  library: "Child Library",
  cards: "Physical Cards",
  playlists: "Yoto Cloud Playlists"
};

document.addEventListener("DOMContentLoaded", () => {
  initPortal();
});

window.addEventListener("storydeck:core-status", async (e) => {
  if (e && e.detail && e.detail.recovered) {
    await checkYotoAuthStatus(false);
    await loadPortalUserIdentity();
    if (yotoTokenValid) {
      await loadProfiles();
      await loadDevices();
      await loadLibrary();
      loadContinueListening();
      loadCards();
      loadPlaylists();
      pollPlayerStatus();
    }
  }
});

// -----------------------------------------------------------------------------
// Navigation & Tab Switching
// -----------------------------------------------------------------------------

function switchTab(tabName) {
  if (!yotoTokenValid) return;
  if (window.StoryDeckHealth && window.StoryDeckHealth.isOffline()) return;

  document.querySelectorAll(".tab-view").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".sidebar-nav-item[data-tab]").forEach(el => el.classList.remove("active"));

  const cap = tabName.charAt(0).toUpperCase() + tabName.slice(1);
  const targetTab = document.getElementById(`tab${cap}`);
  const targetNav = document.getElementById(`navTab${cap}`);

  if (targetTab) targetTab.classList.add("active");
  if (targetNav) targetNav.classList.add("active");

  const titleEl = document.getElementById("portalPageTitle");
  if (titleEl) {
    titleEl.innerText = PORTAL_TAB_TITLES[tabName] || cap;
  }

  if (typeof closeMobileSidebar === "function") {
    closeMobileSidebar();
  }

  if (tabName === "cards") loadCards();
  if (tabName === "playlists") loadPlaylists();
  if (tabName === "library") loadLibrary();
  if (tabName === "player") loadContinueListening();
}

// -----------------------------------------------------------------------------
// Yoto Token Health Gate & Lockout
// -----------------------------------------------------------------------------

async function checkYotoAuthStatus(force = false) {
  const pill = document.getElementById("yotoAuthStatusPill");
  const blockedView = document.getElementById("yotoAuthBlockedView");
  const errDetail = document.getElementById("yotoAuthErrorDetail");
  const retryBtn = document.getElementById("btnRetryYotoAuth");

  if (force && retryBtn) {
    retryBtn.disabled = true;
    retryBtn.innerText = "⏳ Checking Yoto Token...";
  }

  let data = null;
  let coreReachable = true;

  try {
    const res = await fetch(`/api/yoto/auth-status${force ? "?force=1" : ""}`, { cache: "no-store" });
    if (res.status === 502 || res.status === 503 || res.status === 504) {
      coreReachable = false;
      if (window.StoryDeckHealth) {
        window.StoryDeckHealth.reportNetworkError(`Core gateway returned HTTP ${res.status}.`);
      }
    } else if (res.ok) {
      data = await res.json();
    } else {
      data = { token_valid: false, error: `Yoto status check returned HTTP ${res.status}.` };
    }
  } catch (err) {
    coreReachable = false;
    if (window.StoryDeckHealth) {
      window.StoryDeckHealth.reportNetworkError("Unable to reach StoryDeck Core server.");
    }
  } finally {
    if (force && retryBtn) {
      retryBtn.disabled = false;
      retryBtn.innerText = "🔄 Retry Yoto Connection";
    }
  }

  if (!coreReachable) {
    if (pill) {
      pill.className = "yoto-status-pill checking";
      pill.innerText = "⚠️ Core Offline";
      pill.title = "StoryDeck Core server is unreachable";
    }
    document.body.classList.remove("yoto-auth-locked");
    if (blockedView) blockedView.style.display = "none";
    return false;
  }

  const valid = Boolean(data && data.token_valid);

  if (pill) {
    if (valid) {
      pill.className = "yoto-status-pill ok";
      pill.innerText = "🟢 Yoto";
      pill.title = "Yoto API Connected";
    } else {
      pill.className = "yoto-status-pill error";
      pill.innerText = "🔴 Yoto Token Error";
      pill.title = (data && data.error) || "Yoto API Token Not Resolving";
    }
  }

  if (!valid) {
    yotoTokenValid = false;
    document.body.classList.add("yoto-auth-locked");
    if (blockedView) blockedView.style.display = "block";
    if (errDetail) {
      errDetail.innerText = (data && data.error) || "Yoto OAuth token is expired or invalid. Open Admin Settings → Yoto Play Cloud to reconnect.";
    }
    return false;
  }

  const wasBlocked = !yotoTokenValid;
  yotoTokenValid = true;
  document.body.classList.remove("yoto-auth-locked");
  if (blockedView) blockedView.style.display = "none";

  if (wasBlocked) {
    await loadProfiles();
    await loadDevices();
    await loadLibrary();
    loadContinueListening();
    loadCards();
    loadPlaylists();
    loadHouseholdYotoCards();
    pollPlayerStatus();
  }
  return true;
}

// -----------------------------------------------------------------------------
// Portal Identity & Initialization
// -----------------------------------------------------------------------------

async function loadPortalUserIdentity() {
  const badgeEl = document.getElementById("portalUserBadge");
  const nameEl = document.getElementById("sidebarUserName");
  const roleEl = document.getElementById("sidebarUserRole");

  try {
    const res = await fetch("/api/auth/me", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.authenticated || !data.user) {
      if (nameEl) nameEl.innerText = "Sign In Required";
      if (roleEl) roleEl.innerText = "Unauthenticated";
      return;
    }

    const u = data.user;
    const displayName = u.display_name || u.username || "Household";
    let roleLabel = u.role === "admin" ? "Admin" : "Member";
    if (u.is_lan_guest) {
      roleLabel = "LAN Guest";
    } else if (u.auth_type === "sso") {
      roleLabel = `SSO (${u.sso_provider || "Authentik"})`;
    }

    if (nameEl) nameEl.innerText = displayName;
    if (roleEl) roleEl.innerText = roleLabel;
    if (badgeEl) {
      badgeEl.style.display = "inline-flex";
      badgeEl.innerText = u.is_lan_guest ? "🏠 LAN" : (u.auth_type === "sso" ? `🛡️ ${displayName}` : `👤 ${displayName}`);
      badgeEl.title = `${displayName} • ${roleLabel}`;
    }
  } catch (err) {
    if (window.StoryDeckHealth) {
      window.StoryDeckHealth.reportNetworkError("Failed checking portal session.");
    }
  }
}

async function initPortal() {
  loadPortalUserIdentity();
  const yotoOk = await checkYotoAuthStatus(false);
  if (yotoOk) {
    await loadProfiles();
    await loadDevices();
    await loadLibrary();
    loadContinueListening();
    loadCards();
    loadPlaylists();
    loadHouseholdYotoCards();
    pollPlayerStatus();
  }

  // Start polling player status every 3.5s (only while Yoto token & Core are healthy)
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(() => {
    if (yotoTokenValid && !(window.StoryDeckHealth && window.StoryDeckHealth.isOffline())) {
      pollPlayerStatus();
    }
  }, 3500);

  // Periodically check Yoto token health every 15s (only while Core is online)
  if (authCheckInterval) clearInterval(authCheckInterval);
  authCheckInterval = setInterval(() => {
    if (!(window.StoryDeckHealth && window.StoryDeckHealth.isOffline())) {
      checkYotoAuthStatus(false);
    }
  }, 15000);
}

// -----------------------------------------------------------------------------
// Profile Avatar Carousel & Active Child Switching
// -----------------------------------------------------------------------------

async function loadProfiles() {
  try {
    const res = await fetch("/api/profiles", { cache: "no-store" });
    if (!res.ok) {
      if (res.status >= 502 && window.StoryDeckHealth) {
        window.StoryDeckHealth.reportNetworkError(`Profiles fetch failed (HTTP ${res.status})`);
      }
      return;
    }
    const list = await res.json();
    profileList = Array.isArray(list) ? list : [];
    currentProfiles = {};
    profileList.forEach(p => {
      if (p && p.id) {
        currentProfiles[p.id] = p;
      }
    });

    let savedId = "";
    try {
      savedId = sessionStorage.getItem(PORTAL_PROFILE_STORAGE_KEY) || "";
    } catch (e) {
      savedId = "";
    }

    if (savedId && (savedId === "__all__" || currentProfiles[savedId])) {
      activeProfileId = savedId;
    } else if (profileList.length > 0 && (!activeProfileId || (activeProfileId !== "__all__" && !currentProfiles[activeProfileId]))) {
      activeProfileId = profileList[0].id;
    } else if (!activeProfileId) {
      activeProfileId = "__all__";
    }

    renderProfileCarousel();
    updateProfileSummaryLabels();
  } catch (err) {
    console.error("Failed to load profiles:", err);
    if (window.StoryDeckHealth) {
      window.StoryDeckHealth.reportNetworkError("Failed fetching child profiles.");
    }
  }
}

function renderProfileCarousel() {
  const carousel = document.getElementById("profileAvatarCarousel");
  if (!carousel) return;
  carousel.innerHTML = "";

  profileList.forEach(p => {
    const pid = p.id;
    const name = p.display_name || pid;
    const avatarUrl = p.avatar_url || `/api/avatar/${encodeURIComponent(pid)}`;
    const bgColor = p.avatar_color || "#3b82f6";
    const monogram = p.avatar_initial || name.charAt(0).toUpperCase() || "?";
    const isActive = activeProfileId === pid;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `profile-avatar-chip${isActive ? " active" : ""}`;
    btn.dataset.profileId = pid;
    btn.setAttribute("role", "option");
    btn.setAttribute("aria-selected", String(isActive));
    btn.title = `Switch to ${name}`;
    btn.onclick = () => switchActiveProfile(pid);

    btn.innerHTML = `
      <span class="profile-avatar-ring">
        <img class="profile-avatar-img" src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(name)}">
      </span>
      <span class="profile-avatar-name">${escapeHtml(name)}</span>
    `;

    const img = btn.querySelector("img");
    if (img) {
      img.addEventListener("error", () => {
        const ring = btn.querySelector(".profile-avatar-ring");
        if (ring) {
          ring.innerHTML = `<span class="profile-avatar-fallback" style="background: ${escapeHtml(bgColor)};">${escapeHtml(monogram)}</span>`;
        }
      });
    }

    carousel.appendChild(btn);
  });

  // Append "All" Household Library chip using a clean vector icon (no emoji)
  const isAllActive = activeProfileId === "__all__";
  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = `profile-avatar-chip${isAllActive ? " active" : ""}`;
  allBtn.dataset.profileId = "__all__";
  allBtn.setAttribute("role", "option");
  allBtn.setAttribute("aria-selected", String(isAllActive));
  allBtn.title = "Show All Household Library";
  allBtn.onclick = () => switchActiveProfile("__all__");
  allBtn.innerHTML = `
    <span class="profile-avatar-ring">
      <span class="profile-avatar-all-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
        </svg>
      </span>
    </span>
    <span class="profile-avatar-name">All Books</span>
  `;
  carousel.appendChild(allBtn);
}

function updateProfileSummaryLabels() {
  const p = currentProfiles[activeProfileId];
  const summaryEl = document.getElementById("activeProfileSummaryLabel");
  if (summaryEl) {
    if (activeProfileId === "__all__") {
      summaryEl.innerText = "All Household";
    } else if (p) {
      summaryEl.innerText = p.display_name || activeProfileId;
    } else {
      summaryEl.innerText = "No Profiles";
    }
  }

  const childLabel = document.getElementById("libraryChildNameLabel");
  if (childLabel) {
    if (activeProfileId === "__all__") {
      childLabel.innerText = "Showing all household books";
    } else if (p) {
      childLabel.innerText = `Showing books for ${p.display_name || activeProfileId}`;
    }
  }
}

function switchActiveProfile(profileId) {
  activeProfileId = profileId;
  try {
    sessionStorage.setItem(PORTAL_PROFILE_STORAGE_KEY, profileId);
  } catch (e) {
    // Ignore storage access restriction errors
  }

  document.querySelectorAll("#profileAvatarCarousel .profile-avatar-chip").forEach((chip) => {
    const match = chip.dataset.profileId === profileId;
    chip.classList.toggle("active", match);
    chip.setAttribute("aria-selected", String(match));
  });

  updateProfileSummaryLabels();

  const p = currentProfiles[profileId];
  if (p && p.default_player_id) {
    const hasDevice = currentDevices.length === 0 || currentDevices.some(d => (d.deviceId || d.id) === p.default_player_id);
    if (hasDevice) {
      activeDeviceId = p.default_player_id;
      const devSelect = document.getElementById("playerDeviceSelect");
      if (devSelect) devSelect.value = activeDeviceId;
      if (typeof pollPlayerStatus === "function") {
        pollPlayerStatus();
      }
    }
  }

  if (typeof updatePlayerContextBadges === "function") {
    updatePlayerContextBadges();
  }
  loadLibrary();
  loadContinueListening();
}

// -----------------------------------------------------------------------------
// Utilities
// -----------------------------------------------------------------------------

function formatSeconds(secs) {
  const s = Math.floor(secs || 0);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem < 10 ? '0' : ''}${rem}`;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
