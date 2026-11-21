// ============================================================================
// Diagnostics & Settings (Tab 4 Core)
// ============================================================================

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
  yoto: { client_id: "", refresh: "" },
  abs: { url: "", key: "" },
  tinker: { key: "" },
  ai: { key: "" },
  preferences: { exclude: true, refresh_enabled: true, refresh_hours: "6", lan_sitter: true }
};

function snapshotBaseline(section) {
  if (section === "yoto" || !section) {
    settingsBaseline.yoto = {
      client_id: document.getElementById("credYotoClientId")?.value.trim() || "",
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
  const btnMap = {
    yoto: "btnSaveYoto",
    abs: "btnSaveAbs",
    tinker: "btnSaveTinker",
    ai: "btnSaveAi",
    preferences: "btnSavePreferences"
  };
  const btn = document.getElementById(btnMap[section] || "");
  if (btn) {
    btn.classList.toggle("btn-unsaved", Boolean(isDirty));
  }
}

function checkDirty(section) {
  if (section === "yoto") {
    const cur = {
      client_id: document.getElementById("credYotoClientId")?.value.trim() || "",
      refresh: document.getElementById("credYotoRefresh")?.value.trim() || ""
    };
    const b = settingsBaseline.yoto;
    setSectionDirty("yoto", cur.client_id !== b.client_id || cur.refresh !== b.refresh);
  } else if (section === "abs") {
    const cur = {
      url: document.getElementById("credAbsUrl")?.value.trim() || "",
      key: document.getElementById("credAbsKey")?.value.trim() || ""
    };
    const b = settingsBaseline.abs;
    setSectionDirty("abs", cur.url !== b.url || cur.key !== b.key);
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

  const bindSection = (ids, section, updateBadgeFlag = false) => {
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const handler = () => {
        checkDirty(section);
        if (updateBadgeFlag) updateConnectionBadges();
      };
      el.addEventListener("input", handler);
      el.addEventListener("change", handler);
    });
  };

  bindSection(["credYotoClientId", "credYotoRefresh"], "yoto", true);
  bindSection(["credAbsUrl", "credAbsKey"], "abs", true);
  bindSection(["credTinkerKey"], "tinker", true);
  bindSection(["credOpenRouterKey"], "ai", true);
  bindSection(["toggleExcludeSingleSeries", "toggleAutoLibraryRefresh", "autoLibraryRefreshHours", "toggleLanSitterAccess"], "preferences", false);
}

async function loadApiCredentials() {
  try {
    const res = await fetch("/api/admin/settings/credentials");
    if (!res.ok) return;
    const creds = await res.json();
    if (creds.yoto_client_id && document.getElementById("credYotoClientId")) {
      document.getElementById("credYotoClientId").value = creds.yoto_client_id;
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

    await loadMasterApiKey();
    await loadHouseholdUsers();
    await loadCatalogSettings();
    await loadAbsDefaultTags();
    await fetchAbsServerTags();

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
    if (toggleExclude) toggleExclude.checked = Boolean(data.exclude_single_card_series);

    const toggleRefresh = document.getElementById("toggleAutoLibraryRefresh");
    if (toggleRefresh) toggleRefresh.checked = Boolean(data.auto_library_refresh_enabled);

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

  const excludeVal = document.getElementById("toggleExcludeSingleSeries")?.checked ?? true;
  const refreshEnabled = document.getElementById("toggleAutoLibraryRefresh")?.checked ?? true;
  const refreshHours = parseFloat(document.getElementById("autoLibraryRefreshHours")?.value || "6.0");
  const lanSitterEnabled = document.getElementById("toggleLanSitterAccess")?.checked ?? true;

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
// Audiobookshelf Default Children Tags Management
// ----------------------------------------------------------------------------

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

  const clientId = document.getElementById("credYotoClientId")?.value.trim() || "";
  const refresh = document.getElementById("credYotoRefresh")?.value.trim() || "";

  const success = await saveApiCredentialsPartial({
    yoto_client_id: clientId,
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

  const key = document.getElementById("credTinkerKey")?.value.trim() || "";

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

  const key = document.getElementById("credOpenRouterKey")?.value.trim() || "";

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
