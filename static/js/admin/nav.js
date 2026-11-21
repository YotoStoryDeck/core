// ============================================================================
// Tab Navigation & Hash Slugs
// ============================================================================

const VALID_TABS = ["profiles", "library", "hardware", "users", "settings"];

const TAB_TITLES = {
  profiles: "Child Profiles",
  library: "Library & Curation",
  hardware: "Hardware Displays",
  users: "Users & Access Control",
  settings: "Settings & Diagnostics"
};

function normalizeTabSlug(slug) {
  if (!slug) return "profiles";
  const s = slug.toLowerCase();
  if (s === "curation") return "library";
  if (s === "diagnostics") return "settings";
  if (s === "access" || s === "sso" || s === "accounts") return "users";
  return VALID_TABS.includes(s) ? s : "profiles";
}

function getTabFromHash() {
  const hash = window.location.hash.replace(/^#\/?/, "").trim().toLowerCase();
  return normalizeTabSlug(hash);
}

function switchTab(tabId, updateHash = true) {
  tabId = normalizeTabSlug(tabId);

  // Synchronize URL hash for deep-linking, refresh persistence, and back/forward navigation
  if (updateHash && window.location.hash.replace(/^#\/?/, "") !== tabId) {
    history.pushState(null, "", `#${tabId}`);
  }

  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(content => content.classList.remove("active"));

  const targetContent = document.getElementById(`tab-${tabId}`);
  if (targetContent) targetContent.classList.add("active");

  const activeBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`) ||
    Array.from(document.querySelectorAll(".tab-btn")).find(btn => {
      const onclickAttr = btn.getAttribute("onclick") || "";
      return onclickAttr.includes(`'${tabId}'`) || onclickAttr.includes(`"${tabId}"`);
    });
  if (activeBtn) activeBtn.classList.add("active");

  const pageTitle = document.getElementById("adminPageTitle");
  if (pageTitle) {
    pageTitle.innerText = TAB_TITLES[tabId] || "Admin Console";
  }

  if (typeof closeMobileSidebar === "function") {
    closeMobileSidebar();
  }

  if (tabId === "profiles") loadProfiles();
  if (tabId === "library") loadMatrix();
  if (tabId === "hardware") { loadDevices(); if (typeof loadFirmwareReleases === "function") loadFirmwareReleases(); }
  if (tabId === "users" && typeof loadUsersPage === "function") loadUsersPage();
  if (tabId === "settings") { loadApiCredentials(); if (typeof checkCoreUpdates === "function") checkCoreUpdates(); }
}

// Listen to browser Back / Forward buttons
window.addEventListener("popstate", () => {
  const targetTab = getTabFromHash();
  switchTab(targetTab, false);
});

window.addEventListener("hashchange", () => {
  const targetTab = getTabFromHash();
  switchTab(targetTab, false);
});

function loadInitialData() {
  // Restore tab from hash slug (e.g. #library, #hardware, #users, #settings)
  const initialTab = getTabFromHash();
  switchTab(initialTab, false);

  // Eagerly pre-load data for other tabs in the background so switching is instant
  if (initialTab !== "profiles") loadProfiles();
  if (initialTab !== "library") loadMatrix();
  if (initialTab !== "hardware") { loadDevices(); if (typeof loadFirmwareReleases === "function") loadFirmwareReleases(); }
  if (initialTab !== "users" && typeof loadUsersPage === "function") loadUsersPage();
  if (initialTab !== "settings") loadApiCredentials();
  if (typeof checkCoreUpdates === "function") checkCoreUpdates();
}
