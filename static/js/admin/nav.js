// ============================================================================
// Tab Navigation & Hash Slugs
// ============================================================================

const VALID_TABS = ["profiles", "library", "hardware", "settings"];

function normalizeTabSlug(slug) {
  if (!slug) return "profiles";
  const s = slug.toLowerCase();
  if (s === "curation") return "library";
  if (s === "diagnostics") return "settings";
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

  if (tabId === "profiles") loadProfiles();
  if (tabId === "library") loadMatrix();
  if (tabId === "hardware") loadDevices();
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
  // Restore tab from hash slug (e.g. #library, #hardware, #settings)
  const initialTab = getTabFromHash();
  switchTab(initialTab, false);

  // Eagerly pre-load data for other tabs in the background so switching is instant
  if (initialTab !== "profiles") loadProfiles();
  if (initialTab !== "library") loadMatrix();
  if (initialTab !== "hardware") loadDevices();
  if (initialTab !== "settings") loadApiCredentials();
  if (typeof checkCoreUpdates === "function") checkCoreUpdates();
}
