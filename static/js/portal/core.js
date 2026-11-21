// ==============================================================================
// StoryDeck Parent-First Mobile Front Portal Script
// ==============================================================================

let currentProfiles = {};
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

document.addEventListener("DOMContentLoaded", () => {
  initPortal();
});

// -----------------------------------------------------------------------------
// Navigation & Tab Switching
// -----------------------------------------------------------------------------

function switchTab(tabName) {
  if (!yotoTokenValid) return;
  document.querySelectorAll(".tab-view").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));

  const targetTab = document.getElementById(`tab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);
  const targetNav = document.getElementById(`navTab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);

  if (targetTab) targetTab.classList.add("active");
  if (targetNav) targetNav.classList.add("active");

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

  let data = {
    token_valid: false,
    error: "Unable to verify Yoto API connection."
  };

  try {
    const res = await fetch(`/api/yoto/auth-status${force ? "?force=1" : ""}`);
    if (res.ok) {
      data = await res.json();
    } else {
      data.error = `Yoto status check returned HTTP ${res.status}.`;
    }
  } catch (err) {
    data.error = "Unable to reach StoryDeck Core server to verify Yoto token.";
  } finally {
    if (force && retryBtn) {
      retryBtn.disabled = false;
      retryBtn.innerText = "🔄 Retry Yoto Connection";
    }
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
      pill.title = data.error || "Yoto API Token Not Resolving";
    }
  }

  if (!valid) {
    yotoTokenValid = false;
    document.body.classList.add("yoto-auth-locked");
    if (blockedView) blockedView.style.display = "block";
    if (errDetail) {
      errDetail.innerText = data.error || "Yoto OAuth token is expired or invalid. Open Admin Settings → Yoto Play Cloud to reconnect.";
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
// Initialization
// -----------------------------------------------------------------------------

async function initPortal() {
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

  // Start polling player status every 3.5s (only while Yoto token is healthy)
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(() => {
    if (yotoTokenValid) pollPlayerStatus();
  }, 3500);

  // Periodically check Yoto token health every 15s
  if (authCheckInterval) clearInterval(authCheckInterval);
  authCheckInterval = setInterval(() => checkYotoAuthStatus(false), 15000);
}

// -----------------------------------------------------------------------------
// Profile Handling
// -----------------------------------------------------------------------------

async function loadProfiles() {
  try {
    const res = await fetch("/api/admin/profiles");
    if (!res.ok) return;
    currentProfiles = await res.json();

    const select = document.getElementById("headerProfileSelect");
    select.innerHTML = "";

    const pids = Object.keys(currentProfiles);
    pids.forEach((pid, idx) => {
      const p = currentProfiles[pid];
      const opt = document.createElement("option");
      opt.value = pid;
      opt.innerText = `👶 ${p.display_name || pid}`;
      select.appendChild(opt);
    });

    // Append All Household Library scope option
    const allOpt = document.createElement("option");
    allOpt.value = "__all__";
    allOpt.innerText = "📚 All Household Library";
    select.appendChild(allOpt);

    if (pids.length > 0 && !activeProfileId) {
      activeProfileId = pids[0];
      select.value = activeProfileId;
    } else if (!activeProfileId) {
      activeProfileId = "__all__";
      select.value = "__all__";
    }
  } catch (err) {
    console.error("Failed to load profiles:", err);
  }
}

function switchActiveProfile(profileId) {
  activeProfileId = profileId;
  const p = currentProfiles[profileId];
  if (p && p.default_player_id) {
    activeDeviceId = p.default_player_id;
    const devSelect = document.getElementById("playerDeviceSelect");
    if (devSelect) devSelect.value = activeDeviceId;
  }
  const childLabel = document.getElementById("libraryChildNameLabel");
  if (childLabel) {
    if (profileId === "__all__") {
      childLabel.innerText = "Showing all household books";
    } else if (p) {
      childLabel.innerText = `Showing books for ${p.display_name || profileId}`;
    }
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
