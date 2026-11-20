// ============================================================================
// Diagnostics & Settings (Tab 4)
// ============================================================================

function toggleYotoRefreshTokenVisibility() {
  const input = document.getElementById("credYotoRefresh");
  const btn = document.getElementById("btnToggleYotoRefresh");
  if (!input) return;
  if (input.type === "password") {
    input.type = "text";
    if (btn) btn.innerText = "🙈";
  } else {
    input.type = "password";
    if (btn) btn.innerText = "👁️";
  }
}

// Deprecated mode switcher kept as no-op for backwards compatibility
function onYotoModeChange() {}

// ----------------------------------------------------------------------------
// Card Expansion / Collapsing
// ----------------------------------------------------------------------------

function toggleCardExpansion(cardId) {
  const body = document.getElementById(`${cardId}Body`);
  const chevron = document.getElementById(`${cardId}Chevron`);
  if (!body) return;
  const isHidden = window.getComputedStyle(body).display === "none";
  body.style.display = isHidden ? "block" : "none";
  if (chevron) {
    if (isHidden) {
      chevron.classList.add("expanded");
    } else {
      chevron.classList.remove("expanded");
    }
  }
}

// ----------------------------------------------------------------------------
// Section Connection Badges (Connected vs Not Connected)
// ----------------------------------------------------------------------------

function updateBadge(target, isConnected) {
  const badge = document.getElementById(`${target}ConnectionBadge`);
  if (!badge) return;
  if (isConnected) {
    badge.className = "badge badge-success";
    badge.innerText = "Connected";
  } else {
    badge.className = "badge badge-subtle";
    badge.innerText = "Not Connected";
  }
}

function updateConnectionBadges() {
  const yotoClient = document.getElementById("credYotoClientId")?.value.trim();
  const yotoRefresh = document.getElementById("credYotoRefresh")?.value.trim();
  updateBadge("yoto", Boolean(yotoClient && yotoRefresh));

  const absUrl = document.getElementById("credAbsUrl")?.value.trim();
  const absKey = document.getElementById("credAbsKey")?.value.trim();
  updateBadge("abs", Boolean(absUrl && absKey));

  const tinkerKey = document.getElementById("credTinkerKey")?.value.trim();
  updateBadge("tinker", Boolean(tinkerKey));

  const aiKey = document.getElementById("credOpenRouterKey")?.value.trim();
  updateBadge("ai", Boolean(aiKey));
}

// ----------------------------------------------------------------------------
// Unsaved Changes Tracking System
// ----------------------------------------------------------------------------

let settingsBaseline = {
  yoto: { client_id: "", secret: "", refresh: "" },
  abs: { url: "", key: "" },
  tinker: { key: "" },
  ai: { key: "" },
  preferences: { exclude: true, refresh_enabled: true, refresh_hours: "6", lan_sitter: true }
};

function snapshotBaseline(section) {
  if (section === "yoto" || !section) {
    settingsBaseline.yoto = {
      client_id: document.getElementById("credYotoClientId")?.value.trim() || "",
      secret: document.getElementById("credYotoSecret")?.value.trim() || "",
      refresh: document.getElementById("credYotoRefresh")?.value.trim() || ""
    };
  }
  if (section === "abs" || !section) {
    settingsBaseline.abs = {
      url: document.getElementById("credAbsUrl")?.value.trim() || "",
      key: document.getElementById("credAbsKey")?.value.trim() || ""
    };
  }
  if (section === "tinker" || !section) {
    settingsBaseline.tinker = {
      key: document.getElementById("credTinkerKey")?.value.trim() || ""
    };
  }
  if (section === "ai" || !section) {
    settingsBaseline.ai = {
      key: document.getElementById("credOpenRouterKey")?.value.trim() || ""
    };
  }
  if (section === "preferences" || !section) {
    settingsBaseline.preferences = {
      exclude: document.getElementById("toggleExcludeSingleSeries")?.checked ?? true,
      refresh_enabled: document.getElementById("toggleAutoLibraryRefresh")?.checked ?? true,
      refresh_hours: String(document.getElementById("autoLibraryRefreshHours")?.value || "6"),
      lan_sitter: document.getElementById("toggleLanSitterAccess")?.checked ?? true
    };
  }
}

function setSectionDirty(section, isDirty) {
  const badge = document.getElementById(`unsaved-${section}`);
  if (badge) {
    badge.style.display = isDirty ? "inline-flex" : "none";
  }
  const headerBadge = document.getElementById(`unsaved-header-${section}`);
  if (headerBadge) {
    headerBadge.style.display = isDirty ? "inline-flex" : "none";
  }
  let btnId = "";
  if (section === "yoto") btnId = "btnSaveYoto";
  else if (section === "abs") btnId = "btnSaveAbs";
  else if (section === "tinker") btnId = "btnSaveTinker";
  else if (section === "ai") btnId = "btnSaveAi";
  else if (section === "preferences") btnId = "btnSavePreferences";

  const btn = document.getElementById(btnId);
  if (btn) {
    if (isDirty) {
      btn.classList.add("btn-unsaved");
    } else {
      btn.classList.remove("btn-unsaved");
    }
  }
}

function checkDirty(section) {
  if (section === "yoto") {
    const cur = {
      client_id: document.getElementById("credYotoClientId")?.value.trim() || "",
      secret: document.getElementById("credYotoSecret")?.value.trim() || "",
      refresh: document.getElementById("credYotoRefresh")?.value.trim() || ""
    };
    const b = settingsBaseline.yoto;
    const dirty = cur.client_id !== b.client_id || cur.secret !== b.secret || cur.refresh !== b.refresh;
    setSectionDirty("yoto", dirty);
  } else if (section === "abs") {
    const cur = {
      url: document.getElementById("credAbsUrl")?.value.trim() || "",
      key: document.getElementById("credAbsKey")?.value.trim() || ""
    };
    const b = settingsBaseline.abs;
    const dirty = cur.url !== b.url || cur.key !== b.key;
    setSectionDirty("abs", dirty);
  } else if (section === "tinker") {
    const curKey = document.getElementById("credTinkerKey")?.value.trim() || "";
    setSectionDirty("tinker", curKey !== settingsBaseline.tinker.key);
  } else if (section === "ai") {
    const curKey = document.getElementById("credOpenRouterKey")?.value.trim() || "";
    setSectionDirty("ai", curKey !== settingsBaseline.ai.key);
  } else if (section === "preferences") {
    const cur = {
      exclude: document.getElementById("toggleExcludeSingleSeries")?.checked ?? true,
      refresh_enabled: document.getElementById("toggleAutoLibraryRefresh")?.checked ?? true,
      refresh_hours: String(document.getElementById("autoLibraryRefreshHours")?.value || "6"),
      lan_sitter: document.getElementById("toggleLanSitterAccess")?.checked ?? true
    };
    const b = settingsBaseline.preferences;
    const dirty = cur.exclude !== b.exclude || cur.refresh_enabled !== b.refresh_enabled || cur.refresh_hours !== b.refresh_hours || cur.lan_sitter !== b.lan_sitter;
    setSectionDirty("preferences", dirty);
  }
}

function checkAllDirtyStates() {
  ["yoto", "abs", "tinker", "ai", "preferences"].forEach(checkDirty);
}

let dirtyListenersInitialized = false;
function setupSettingsDirtyListeners() {
  if (dirtyListenersInitialized) return;
  dirtyListenersInitialized = true;

  const yotoInputs = ["credYotoClientId", "credYotoSecret", "credYotoRefresh"];
  yotoInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => { checkDirty("yoto"); updateConnectionBadges(); });
      el.addEventListener("change", () => { checkDirty("yoto"); updateConnectionBadges(); });
    }
  });

  const absInputs = ["credAbsUrl", "credAbsKey"];
  absInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => { checkDirty("abs"); updateConnectionBadges(); });
      el.addEventListener("change", () => { checkDirty("abs"); updateConnectionBadges(); });
    }
  });

  const tinkerEl = document.getElementById("credTinkerKey");
  if (tinkerEl) {
    tinkerEl.addEventListener("input", () => { checkDirty("tinker"); updateConnectionBadges(); });
    tinkerEl.addEventListener("change", () => { checkDirty("tinker"); updateConnectionBadges(); });
  }

  const aiEl = document.getElementById("credOpenRouterKey");
  if (aiEl) {
    aiEl.addEventListener("input", () => { checkDirty("ai"); updateConnectionBadges(); });
    aiEl.addEventListener("change", () => { checkDirty("ai"); updateConnectionBadges(); });
  }

  const prefInputs = ["toggleExcludeSingleSeries", "toggleAutoLibraryRefresh", "autoLibraryRefreshHours", "toggleLanSitterAccess"];
  prefInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => checkDirty("preferences"));
      el.addEventListener("change", () => checkDirty("preferences"));
    }
  });
}

async function loadApiCredentials() {
  try {
    const res = await fetch("/api/admin/settings/credentials");
    if (!res.ok) return;
    const creds = await res.json();
    if (creds.yoto_client_id && document.getElementById("credYotoClientId")) {
      document.getElementById("credYotoClientId").value = creds.yoto_client_id;
    }
    if (creds.yoto_client_secret && document.getElementById("credYotoSecret")) {
      document.getElementById("credYotoSecret").value = creds.yoto_client_secret;
    }
    if (creds.yoto_refresh_token && document.getElementById("credYotoRefresh")) {
      document.getElementById("credYotoRefresh").value = creds.yoto_refresh_token;
    }
    if (creds.abs_base_url && document.getElementById("credAbsUrl")) {
      document.getElementById("credAbsUrl").value = creds.abs_base_url;
    }
    if (creds.abs_api_key && document.getElementById("credAbsKey")) {
      document.getElementById("credAbsKey").value = creds.abs_api_key;
    }
    if (creds.tinker_api_key && document.getElementById("credTinkerKey")) {
      document.getElementById("credTinkerKey").value = creds.tinker_api_key;
    }
    if (creds.openrouter_api_key && document.getElementById("credOpenRouterKey")) {
      document.getElementById("credOpenRouterKey").value = creds.openrouter_api_key;
    }

    // Load master security API key
    await loadMasterApiKey();

    // Load household user accounts
    await loadHouseholdUsers();

    // Load preferences / catalog display settings
    await loadCatalogSettings();

    // Load default children tags and fetch live ABS server tags
    await loadAbsDefaultTags();
    await fetchAbsServerTags();

    // Snapshot clean baseline, check dirty flags, and setup listeners
    snapshotBaseline();
    checkAllDirtyStates();
    updateConnectionBadges();
    setupSettingsDirtyListeners();
  } catch (err) {
    console.error("Failed to load credentials:", err);
  }
}

// ----------------------------------------------------------------------------
// Preferences (Catalog & Automatic Library Refresh Settings)
// ----------------------------------------------------------------------------

async function loadCatalogSettings() {
  try {
    const res = await fetch("/api/admin/settings/catalog");
    if (!res.ok) return;
    const data = await res.json();
    if (!data.ok) return;

    const toggleExclude = document.getElementById("toggleExcludeSingleSeries");
    if (toggleExclude) {
      toggleExclude.checked = Boolean(data.exclude_single_card_series);
    }

    const toggleRefresh = document.getElementById("toggleAutoLibraryRefresh");
    if (toggleRefresh) {
      toggleRefresh.checked = Boolean(data.auto_library_refresh_enabled);
    }

    const selectHours = document.getElementById("autoLibraryRefreshHours");
    if (selectHours && data.auto_library_refresh_hours !== undefined) {
      selectHours.value = String(data.auto_library_refresh_hours);
    }

    const toggleLanSitter = document.getElementById("toggleLanSitterAccess");
    if (toggleLanSitter && data.lan_sitter_access_enabled !== undefined) {
      toggleLanSitter.checked = Boolean(data.lan_sitter_access_enabled);
    }

    onAutoRefreshToggleChange();
    renderLibraryRefreshStatus(data.scheduler_status);
  } catch (err) {
    console.error("Failed to load catalog & refresh settings:", err);
  }
}

function onAutoRefreshToggleChange() {
  const toggleRefresh = document.getElementById("toggleAutoLibraryRefresh");
  const intervalContainer = document.getElementById("autoRefreshIntervalContainer");
  if (intervalContainer && toggleRefresh) {
    const enabled = toggleRefresh.checked;
    intervalContainer.style.opacity = enabled ? "1" : "0.5";
    intervalContainer.style.pointerEvents = enabled ? "auto" : "none";
  }
}

function renderLibraryRefreshStatus(status) {
  const noticeEl = document.getElementById("libraryRefreshStatusNotice");
  if (!noticeEl || !status) return;

  let text = `Status: ${status.last_refresh_status || "Idle"}`;
  if (status.last_refresh_time) {
    const d = new Date(status.last_refresh_time * 1000);
    text += ` • Last run: ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  }
  if (status.enabled && status.next_run_seconds > 0) {
    const min = Math.round(status.next_run_seconds / 60);
    text += ` • Next run in ~${min >= 60 ? (min / 60).toFixed(1) + ' hrs' : min + ' mins'}`;
  }
  noticeEl.innerText = text;
}

async function savePreferencesSettings() {
  const btn = document.getElementById("btnSavePreferences");
  if (btn) {
    btn.disabled = true;
    btn.innerText = "💾 Saving...";
  }

  const toggleExclude = document.getElementById("toggleExcludeSingleSeries");
  const toggleRefresh = document.getElementById("toggleAutoLibraryRefresh");
  const selectHours = document.getElementById("autoLibraryRefreshHours");
  const toggleLanSitter = document.getElementById("toggleLanSitterAccess");

  const excludeVal = toggleExclude ? toggleExclude.checked : true;
  const refreshEnabled = toggleRefresh ? toggleRefresh.checked : true;
  const refreshHours = selectHours ? parseFloat(selectHours.value) : 6.0;
  const lanSitterEnabled = toggleLanSitter ? toggleLanSitter.checked : true;

  try {
    const res = await fetch("/api/admin/settings/catalog", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exclude_single_card_series: excludeVal,
        auto_library_refresh_enabled: refreshEnabled,
        auto_library_refresh_hours: refreshHours,
        lan_sitter_access_enabled: lanSitterEnabled
      })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      snapshotBaseline("preferences");
      checkDirty("preferences");
      renderLibraryRefreshStatus(data.scheduler_status);
      showToast("Preferences saved successfully!", "success");
    } else {
      showToast(data.error || "Failed to update preferences", "error");
    }
  } catch (err) {
    console.error("Failed to save preferences:", err);
    showToast("Error saving preferences", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "💾 Save Preferences";
    }
  }
}

// Backwards-compatible alias for any residual calls
async function saveCatalogSettings() {
  return savePreferencesSettings();
}

async function triggerManualLibrarySync() {
  const btn = document.getElementById("btnSyncNowSettings");
  if (btn) {
    btn.disabled = true;
    btn.innerText = "🔄 Syncing...";
  }

  showToast("Scanning upstream Yoto and Audiobookshelf libraries...", "info");
  try {
    const res = await fetch("/api/admin/catalog/sync", { method: "POST" });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Catalog sync complete (${data.count || 0} items updated).`, "success");
      if (typeof loadMatrix === "function") loadMatrix();
      await loadCatalogSettings();
    } else {
      showToast(data.error || "Failed to sync catalog.", "error");
    }
  } catch (err) {
    console.error("Error triggering manual sync:", err);
    showToast("Network error syncing library.", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "🔄 Sync Now";
    }
  }
}

// ----------------------------------------------------------------------------
// Feature 013: Master API Key Management
// ----------------------------------------------------------------------------

let rawMasterApiKey = "";

async function loadMasterApiKey() {
  try {
    const res = await fetch("/api/admin/security/api-key");
    if (!res.ok) return;
    const data = await res.json();
    if (data.ok && data.api_key) {
      rawMasterApiKey = data.api_key;
      const input = document.getElementById("brokerMasterApiKey");
      if (input) {
        input.value = rawMasterApiKey;
      }
    }
  } catch (err) {
    console.error("Failed to load master API key:", err);
  }
}

function toggleMasterApiKeyVisibility() {
  const input = document.getElementById("brokerMasterApiKey");
  const btn = document.getElementById("btnToggleMasterApiKey");
  if (!input || !btn) return;

  if (input.type === "password") {
    input.type = "text";
    btn.innerHTML = "🙈 Hide";
  } else {
    input.type = "password";
    btn.innerHTML = "👁️ Show";
  }
}

async function copyMasterApiKey() {
  const input = document.getElementById("brokerMasterApiKey");
  if (!input || !input.value) return;

  try {
    await navigator.clipboard.writeText(input.value);
    showToast("Master API key copied to clipboard!", "success");
  } catch (err) {
    input.type = "text";
    input.select();
    document.execCommand("copy");
    showToast("Master API key copied to clipboard!", "success");
  }
}

function openRegenerateApiKeyModal() {
  const modal = document.getElementById("regenerateApiKeyModal");
  if (modal) {
    modal.style.display = "flex";
  } else {
    if (confirm("Regenerate Broker Master API Key?\n\nWarning: External services (Home Assistant, scripts) using the old key will immediately lose access until updated.")) {
      executeRegenerateMasterApiKey();
    }
  }
}

function closeRegenerateApiKeyModal() {
  const modal = document.getElementById("regenerateApiKeyModal");
  if (modal) modal.style.display = "none";
}

async function executeRegenerateMasterApiKey() {
  closeRegenerateApiKeyModal();
  showToast("Regenerating Master API Key...", "info");

  try {
    const res = await fetch("/api/admin/security/api-key/regenerate", { method: "POST" });
    const data = await res.json();
    if (res.ok && data.ok) {
      rawMasterApiKey = data.api_key;
      const input = document.getElementById("brokerMasterApiKey");
      if (input) {
        input.value = rawMasterApiKey;
        input.type = "text";
      }
      const btn = document.getElementById("btnToggleMasterApiKey");
      if (btn) btn.innerHTML = "🙈 Hide";
      showToast("Master API Key regenerated successfully!", "success");
    } else {
      showToast(data.error || "Failed to regenerate API key.", "danger");
    }
  } catch (err) {
    showToast("Network error regenerating API key.", "danger");
  }
}

// ----------------------------------------------------------------------------
// Audiobookshelf Default Children Tags Management
// ----------------------------------------------------------------------------

// configuredDefaultChildTags declared in core.js
// cachedAbsServerTags declared in core.js

async function loadAbsDefaultTags() {
  try {
    const res = await fetch("/api/admin/settings/abs-tags");
    if (!res.ok) return;
    const data = await res.json();
    if (data.ok && Array.isArray(data.tags)) {
      configuredDefaultChildTags = data.tags;
      renderSelectedDefaultTags();
      updateConfiguredTagsLabels();
    }
  } catch (err) {
    console.error("Failed to load ABS default tags:", err);
  }
}

function updateConfiguredTagsLabels() {
  const labelText = configuredDefaultChildTags.join(", ");
  document.querySelectorAll(".configured-default-tags-label").forEach(el => {
    el.innerText = labelText || "Children";
  });
}

function renderSelectedDefaultTags() {
  const container = document.getElementById("absSelectedDefaultTags");
  if (!container) return;
  container.innerHTML = "";

  if (configuredDefaultChildTags.length === 0) {
    container.innerHTML = '<span class="text-secondary" style="font-size: 11px; padding: 2px 4px;">No default tags selected.</span>';
    return;
  }

  configuredDefaultChildTags.forEach(tag => {
    const pill = document.createElement("span");
    pill.className = "badge badge-info";
    pill.style.display = "inline-flex";
    pill.style.alignItems = "center";
    pill.style.gap = "4px";
    pill.style.fontSize = "11px";
    pill.style.padding = "2px 8px";
    pill.innerHTML = `
      <span>🏷️ ${escapeHtml(tag)}</span>
      <span style="cursor: pointer; font-weight: bold; margin-left: 2px;" onclick="removeAbsDefaultTag('${escapeHtml(tag)}')">&times;</span>
    `;
    container.appendChild(pill);
  });
}

async function fetchAbsServerTags() {
  try {
    const res = await fetch("/api/admin/abs/server-tags");
    if (!res.ok) return;
    const data = await res.json();
    if (data.ok && Array.isArray(data.tags)) {
      cachedAbsServerTags = data.tags;
      populateAbsServerTagsDropdowns();
    }
  } catch (err) {
    console.error("Failed to fetch ABS server tags:", err);
  }
}

function populateAbsServerTagsDropdowns() {
  const select = document.getElementById("absServerTagsDropdown");
  if (!select) return;
  select.innerHTML = '<option value="">-- Choose from Audiobookshelf tags --</option>';

  cachedAbsServerTags.forEach(tag => {
    const opt = document.createElement("option");
    opt.value = tag;
    opt.textContent = tag;
    select.appendChild(opt);
  });
}

async function addSelectedAbsDefaultTag() {
  const select = document.getElementById("absServerTagsDropdown");
  if (!select) return;
  const tag = select.value.trim();
  if (!tag) {
    showToast("Please choose a tag to add.", "warning");
    return;
  }
  if (configuredDefaultChildTags.some(t => t.toLowerCase() === tag.toLowerCase())) {
    showToast(`Tag '${tag}' is already in default tags.`, "info");
    return;
  }

  const updatedTags = [...configuredDefaultChildTags, tag];
  await saveAbsDefaultTags(updatedTags);
  select.value = "";
}

async function removeAbsDefaultTag(tagToRemove) {
  const updatedTags = configuredDefaultChildTags.filter(t => t.toLowerCase() !== tagToRemove.toLowerCase());
  if (updatedTags.length === 0) {
    showToast("At least one default child tag should be configured.", "warning");
  }
  await saveAbsDefaultTags(updatedTags.length > 0 ? updatedTags : ["Children"]);
}

async function saveAbsDefaultTags(tags) {
  try {
    const res = await fetch("/api/admin/settings/abs-tags", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: tags })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      configuredDefaultChildTags = data.tags;
      renderSelectedDefaultTags();
      updateConfiguredTagsLabels();
      showToast("Default child account tags updated.", "success");
      if (typeof loadMatrix === "function") loadMatrix();
    } else {
      showToast(data.error || "Failed to update default tags.", "danger");
    }
  } catch (err) {
    showToast("Network error saving default tags.", "danger");
  }
}

// ----------------------------------------------------------------------------
// Section-by-Section Save & Test Handlers
// ----------------------------------------------------------------------------

async function saveApiCredentialsPartial(payload, notify = true) {
  try {
    const res = await fetch("/api/admin/settings/credentials", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      if (notify) showToast("Settings saved and services reloaded!", "success");
      return true;
    } else {
      if (notify) showToast(data.error || "Failed to save settings.", "danger");
      return false;
    }
  } catch (err) {
    if (notify) showToast("Network error saving settings.", "danger");
    return false;
  }
}

async function saveYotoSettings() {
  const btn = document.getElementById("btnSaveYoto");
  if (btn) { btn.disabled = true; btn.innerText = "💾 Saving..."; }

  const clientId = document.getElementById("credYotoClientId") ? document.getElementById("credYotoClientId").value.trim() : "";
  const secret = document.getElementById("credYotoSecret") ? document.getElementById("credYotoSecret").value.trim() : "";
  const refresh = document.getElementById("credYotoRefresh") ? document.getElementById("credYotoRefresh").value.trim() : "";

  const success = await saveApiCredentialsPartial({
    yoto_client_id: clientId,
    yoto_client_secret: secret,
    yoto_refresh_token: refresh
  });

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save Yoto Settings"; }
  if (success) {
    snapshotBaseline("yoto");
    checkDirty("yoto");
    updateConnectionBadges();
    const statusEl = document.getElementById("yotoStatusInline");
    if (statusEl) statusEl.innerText = "Saved. Click Test Connection to verify.";
  }
}

// Backwards-compatible alias
const saveYotoStandaloneSettings = saveYotoSettings;
async function saveBridgeSettings() { return saveYotoSettings(); }

async function saveAbsSettings() {
  const btn = document.getElementById("btnSaveAbs");
  if (btn) { btn.disabled = true; btn.innerText = "💾 Saving..."; }

  const url = document.getElementById("credAbsUrl").value.trim();
  const key = document.getElementById("credAbsKey").value.trim();

  const success = await saveApiCredentialsPartial({
    abs_base_url: url,
    abs_api_key: key
  });

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save ABS Settings"; }
  if (success) {
    snapshotBaseline("abs");
    checkDirty("abs");
    updateConnectionBadges();
    const statusEl = document.getElementById("absStatusInline");
    if (statusEl) statusEl.innerText = "Saved. Click Test Connection to verify.";
  }
}

async function saveTinkerSettings() {
  const btn = document.getElementById("btnSaveTinker");
  if (btn) { btn.disabled = true; btn.innerText = "💾 Saving..."; }

  const keyInput = document.getElementById("credTinkerKey");
  const key = keyInput ? keyInput.value.trim() : "";

  const success = await saveApiCredentialsPartial({
    tinker_api_key: key
  });

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save Tinker Settings"; }
  if (success) {
    snapshotBaseline("tinker");
    checkDirty("tinker");
    updateConnectionBadges();
    const statusEl = document.getElementById("tinkerStatusInline");
    if (statusEl) statusEl.innerText = "Saved. Click Test API Key to verify.";
  }
}

async function saveAiSettings() {
  const btn = document.getElementById("btnSaveAi");
  if (btn) { btn.disabled = true; btn.innerText = "💾 Saving..."; }

  const keyInput = document.getElementById("credOpenRouterKey");
  const key = keyInput ? keyInput.value.trim() : "";

  const success = await saveApiCredentialsPartial({
    openrouter_api_key: key
  });

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save AI Settings"; }
  if (success) {
    snapshotBaseline("ai");
    checkDirty("ai");
    updateConnectionBadges();
    const statusEl = document.getElementById("aiStatusInline");
    if (statusEl) statusEl.innerText = "Saved. Click Test API Key to verify.";
  }
}

async function testServiceConnection(target) {
  const statusEl = document.getElementById(`${target}StatusInline`);
  const btn = document.getElementById(`btnTest${target.charAt(0).toUpperCase() + target.slice(1)}`);

  if (btn) btn.disabled = true;
  if (statusEl) {
    statusEl.innerHTML = `<span style="color: var(--accent-info);">⏳ Testing ${target.toUpperCase()}...</span>`;
  }

  showToast(`Testing ${target.toUpperCase()}...`, "info");

  try {
    const res = await fetch(`/api/admin/test/${target}`, { method: "POST" });
    const data = await res.json();
    if (res.ok && data.ok) {
      const msg = data.message || "OK";
      if (statusEl) {
        statusEl.innerHTML = `<span style="color: var(--accent-success);">✅ ${escapeHtml(msg)}</span>`;
      }
      updateBadge(target, true);
      showToast(`${target.toUpperCase()} PASSED: ${msg}`, "success");
    } else {
      const err = data.error || "Connection check failed.";
      if (statusEl) {
        statusEl.innerHTML = `<span style="color: var(--accent-danger);">❌ ${escapeHtml(err)}</span>`;
      }
      updateBadge(target, false);
      showToast(`${target.toUpperCase()} failed: ${err}`, "danger");
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerHTML = `<span style="color: var(--accent-danger);">❌ Network error reaching endpoint.</span>`;
    }
    updateBadge(target, false);
    showToast(`Network error testing ${target}.`, "danger");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Backwards-compatible alias for any legacy diagnostic call
async function runDiagnosticTest(target) {
  return testServiceConnection(target);
}

// ----------------------------------------------------------------------------
// Cache Maintenance
// ----------------------------------------------------------------------------

async function purgeImageCache() {
  if (!confirm("Are you sure you want to clear all downscaled thumbnails and AI icons?")) return;
  try {
    const res = await fetch("/api/admin/cache/purge", { method: "POST" });
    const data = await res.json();
    showToast(`Purged ${data.files_purged || 0} cached images.`, "success");
  } catch (err) {
    showToast("Failed to purge image cache.", "danger");
  }
}

// ----------------------------------------------------------------------------
// In-Browser Yoto OAuth Helpers
// ----------------------------------------------------------------------------

async function startInBrowserYotoOAuth() {
  const clientId = document.getElementById("credYotoClientId").value.trim();
  if (!clientId) {
    showToast("Please enter your Yoto Client ID first.", "danger");
    document.getElementById("credYotoClientId").focus();
    return;
  }

  showToast("Starting Yoto authorization flow...");
  try {
    const res = await fetch("/api/admin/yoto/oauth/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      showToast(data.error || "Failed to start Yoto OAuth.", "danger");
      return;
    }

    // Reveal manual callback paste input in case popup is blocked or loopback differs
    const helper = document.getElementById("yotoOAuthManualHelper");
    if (helper) helper.style.display = "block";

    // Open Yoto login in popup window
    const popup = window.open(data.auth_url, "yotoAuthPopup", "width=600,height=750,menubar=no,toolbar=no");
    if (!popup || popup.closed || typeof popup.closed === "undefined") {
      window.open(data.auth_url, "_blank");
    }
    showToast("Sign into Yoto in the opened window and approve access.", "info");
  } catch (err) {
    showToast("Network error starting Yoto OAuth: " + err.message, "danger");
  }
}

async function finishInBrowserYotoOAuth(codeOrUrl) {
  const helperInput = document.getElementById("yotoPastedUrl");
  const input = codeOrUrl || (helperInput ? helperInput.value.trim() : "");
  if (!input) {
    showToast("Please paste the callback URL or authorization code.", "danger");
    return;
  }

  showToast("Exchanging code for Yoto Refresh Token...");
  try {
    const res = await fetch("/api/admin/yoto/oauth/finish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url_or_code: input })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(data.message || "Yoto connected successfully!", "success");
      const helper = document.getElementById("yotoOAuthManualHelper");
      if (helper) helper.style.display = "none";
      loadApiCredentials();
    } else {
      showToast(data.error || "Failed to complete Yoto login.", "danger");
    }
  } catch (err) {
    showToast("Network error completing Yoto login: " + err.message, "danger");
  }
}

// Listen for cross-window message from callback landing page popup
window.addEventListener("message", (event) => {
  if (event.data && event.data.type === "YOTO_AUTH_CALLBACK") {
    console.log("Received Yoto callback code via window message:", event.data);
    finishInBrowserYotoOAuth(event.data.code);
  }
});

// (escapeHtml defined in core.js)



// ============================================================================
// Core Version & Upstream Update Checker (Feature 022)
// ============================================================================

async function checkCoreUpdates(force = false) {
  const btn = document.getElementById("btnCheckUpdates");
  const badge = document.getElementById("versionStatusBadge");
  const topNavBadge = document.getElementById("coreVersionBadge");
  const installedText = document.getElementById("installedVersionText");
  const latestText = document.getElementById("latestVersionText");
  const channelText = document.getElementById("releaseChannelText");
  const banner = document.getElementById("updateNoticeBanner");
  const bannerTag = document.getElementById("updateBannerTag");
  const bannerNotes = document.getElementById("updateBannerNotes");
  const viewNotesBtn = document.getElementById("btnViewReleaseNotes");
  const lastCheckedText = document.getElementById("versionLastCheckedText");

  if (btn) {
    btn.disabled = true;
    btn.innerText = "⏳ Checking...";
  }
  if (badge) {
    badge.className = "badge badge-subtle";
    badge.innerText = "Checking...";
  }

  try {
    const url = force ? "/api/admin/version?force=true" : "/api/admin/version";
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const curVer = data.current_version || "v1.1.0-dev";
    const isPre = data.is_prerelease;
    const hasUpdate = data.has_update;
    const latestVer = data.latest_version || curVer;

    // Update TopNav Header Badge
    if (topNavBadge) {
      if (hasUpdate) {
        topNavBadge.classList.add("update-available");
        topNavBadge.title = `Update available: ${latestVer} (Click to open Settings)`;
        topNavBadge.innerHTML = `🚀 ${curVer} <span style="font-size:10px; opacity:0.9;">(${latestVer})</span>`;
      } else {
        topNavBadge.classList.remove("update-available");
        topNavBadge.title = `StoryDeck Core ${curVer} (Up to date)`;
        topNavBadge.innerText = curVer;
      }
    }

    // Update Settings Card
    if (installedText) installedText.innerText = curVer;
    if (latestText) latestText.innerText = latestVer;
    if (channelText) channelText.innerText = isPre ? "Release Candidate (RC)" : "Stable";

    if (badge) {
      if (hasUpdate) {
        badge.className = "badge badge-warning";
        badge.innerText = "Update Available";
      } else {
        badge.className = "badge badge-success";
        badge.innerText = "Up to Date";
      }
    }

    if (banner) {
      if (hasUpdate) {
        banner.style.display = "block";
        if (bannerTag) bannerTag.innerText = latestVer;
        if (bannerNotes && data.release_notes) {
          const firstLine = data.release_notes.split("\n")[0].replace(/^#+\s*/, "").slice(0, 120);
          bannerNotes.innerText = firstLine || "A new release of StoryDeck Core is available on GitHub.";
        }
        if (viewNotesBtn && data.release_url) {
          viewNotesBtn.href = data.release_url;
        }
      } else {
        banner.style.display = "none";
      }
    }

    if (lastCheckedText) {
      const dt = data.checked_at ? new Date(data.checked_at).toLocaleTimeString() : "Just now";
      lastCheckedText.innerText = `Last checked: ${dt}` + (data.cache_hit ? " (Cached)" : "");
    }

    if (force && typeof showToast === "function") {
      showToast(hasUpdate ? `New version ${latestVer} available!` : "StoryDeck Core is up to date.", hasUpdate ? "info" : "success");
    }
  } catch (err) {
    console.error("Failed to check version status:", err);
    if (badge) {
      badge.className = "badge badge-subtle";
      badge.innerText = "Offline / Rate-limited";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "🔄 Check for Updates";
    }
  }
}

// ============================================================================
// Household User Accounts & Role Management (DLP-009)
// ============================================================================

async function loadHouseholdUsers() {
  const tbody = document.getElementById("adminUsersTableBody");
  if (!tbody) return;
  try {
    const res = await fetch("/api/admin/users");
    if (!res.ok) return;
    const data = await res.json();
    renderHouseholdUsers(data.users || []);
  } catch (err) {
    console.error("Failed to load household users:", err);
  }
}

function renderHouseholdUsers(users) {
  const tbody = document.getElementById("adminUsersTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!users || users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="padding: 12px; color: var(--text-secondary);">No user accounts configured.</td></tr>`;
    return;
  }
  users.forEach(u => {
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-subtle)";
    const isAdmin = u.role === "admin";
    tr.innerHTML = `
      <td style="padding: 8px; font-weight: 600;">${escapeHtml(u.username)}</td>
      <td style="padding: 8px;">${escapeHtml(u.display_name || u.username)}</td>
      <td style="padding: 8px;">
        <select class="form-control" style="width: 155px; font-size: 12px; padding: 3px 6px;" onchange="changeHouseholdUserRole('${escapeHtml(u.user_id)}', this.value)">
          <option value="admin" ${isAdmin ? 'selected' : ''}>🛡️ Admin (Console)</option>
          <option value="member" ${!isAdmin ? 'selected' : ''}>👤 Member (Portal)</option>
        </select>
      </td>
      <td style="padding: 8px; text-align: right; white-space: nowrap;">
        <button type="button" class="btn btn-secondary btn-sm" style="font-size: 11px;" onclick="resetHouseholdUserPassword('${escapeHtml(u.user_id)}', '${escapeHtml(u.username)}')">🔑 Reset Password</button>
        <button type="button" class="btn btn-danger btn-sm" style="font-size: 11px; margin-left: 4px;" onclick="deleteHouseholdUser('${escapeHtml(u.user_id)}', '${escapeHtml(u.username)}')">🗑️</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function createNewHouseholdUser() {
  const usernameEl = document.getElementById("newAdminUsername");
  const displayEl = document.getElementById("newAdminDisplayName");
  const roleEl = document.getElementById("newAdminRole");
  const passwordEl = document.getElementById("newAdminPassword");

  const username = usernameEl?.value.trim() || "";
  const display_name = displayEl?.value.trim() || username;
  const role = roleEl?.value || "member";
  const password = passwordEl?.value || "";

  if (!username || !password) {
    showToast("Username and password (min 6 chars) are required.", "warning");
    return;
  }

  try {
    const res = await fetch("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, display_name, role, password })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Created user '${username}' (${role}).`, "success");
      if (usernameEl) usernameEl.value = "";
      if (displayEl) displayEl.value = "";
      if (passwordEl) passwordEl.value = "";
      await loadHouseholdUsers();
    } else {
      showToast(data.error || "Failed to create user.", "danger");
    }
  } catch (err) {
    showToast("Network error creating user.", "danger");
  }
}

async function changeHouseholdUserRole(userId, role) {
  try {
    const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Updated user role.", "success");
      await loadHouseholdUsers();
    } else {
      showToast(data.error || "Failed to update role.", "danger");
      await loadHouseholdUsers();
    }
  } catch (err) {
    showToast("Network error updating role.", "danger");
  }
}

async function resetHouseholdUserPassword(userId, username) {
  const newPassword = prompt(`Enter new password for '${username}' (minimum 6 characters):`);
  if (!newPassword) return;
  if (newPassword.length < 6) {
    showToast("Password must be at least 6 characters.", "warning");
    return;
  }
  try {
    const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: newPassword })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Password updated for '${username}'.`, "success");
    } else {
      showToast(data.error || "Failed to reset password.", "danger");
    }
  } catch (err) {
    showToast("Network error resetting password.", "danger");
  }
}

async function deleteHouseholdUser(userId, username) {
  if (!confirm(`Delete user account '${username}'?`)) return;
  try {
    const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Deleted user '${username}'.`, "success");
      await loadHouseholdUsers();
    } else {
      showToast(data.error || "Failed to delete user.", "danger");
    }
  } catch (err) {
    showToast("Network error deleting user.", "danger");
  }
}
