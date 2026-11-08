// ============================================================================
// Diagnostics & Settings (Tab 4)
// ============================================================================

function onYotoModeChange() {
  const mode = document.getElementById("yotoConnectionMode").value;
  const bridgeSection = document.getElementById("sectionBridgeConfig");
  const directSection = document.getElementById("sectionDirectYotoCloud");
  const absSection = document.getElementById("sectionAbsConfig");
  const tinkerSection = document.getElementById("sectionTinkerConfig");
  const aiSection = document.getElementById("sectionAiConfig");

  if (mode === "bridge") {
    // Mode 1: Bridge Mode (Hybrid ABS + Yoto Streaming)
    if (bridgeSection) bridgeSection.style.display = "block";
    if (directSection) directSection.style.display = "none";
    if (absSection) absSection.style.display = "block";
    if (tinkerSection) tinkerSection.style.display = "block";
    if (aiSection) aiSection.style.display = "block";
  } else {
    // Mode 2: Standalone Direct Yoto Cloud (Pure Yoto - No ABS / No Bridge / No AI)
    if (bridgeSection) bridgeSection.style.display = "none";
    if (directSection) directSection.style.display = "block";
    if (absSection) absSection.style.display = "none";
    if (tinkerSection) tinkerSection.style.display = "none";
    if (aiSection) aiSection.style.display = "none";
  }

  // Also auto-save the selected mode
  saveApiCredentialsPartial({ yoto_connection_mode: mode }, false);
}

async function loadApiCredentials() {
  try {
    const res = await fetch("/api/admin/settings/credentials");
    if (!res.ok) return;
    const creds = await res.json();
    if (creds.abs_base_url) document.getElementById("credAbsUrl").value = creds.abs_base_url;
    if (creds.abs_api_key) document.getElementById("credAbsKey").value = creds.abs_api_key;
    if (creds.yoto_client_id) document.getElementById("credYotoClientId").value = creds.yoto_client_id;
    if (creds.yoto_client_secret) document.getElementById("credYotoSecret").value = creds.yoto_client_secret;
    if (creds.yoto_refresh_token) document.getElementById("credYotoRefresh").value = creds.yoto_refresh_token;
    if (creds.yoto_bridge_url) document.getElementById("credBridgeUrl").value = creds.yoto_bridge_url;
    if (creds.yoto_bridge_api_key && document.getElementById("credBridgeApiKey")) {
      document.getElementById("credBridgeApiKey").value = creds.yoto_bridge_api_key;
    }
    if (creds.tinker_api_key && document.getElementById("credTinkerKey")) {
      document.getElementById("credTinkerKey").value = creds.tinker_api_key;
    }
    if (creds.openrouter_api_key && document.getElementById("credOpenRouterKey")) {
      document.getElementById("credOpenRouterKey").value = creds.openrouter_api_key;
    }

    const modeSelect = document.getElementById("yotoConnectionMode");
    if (modeSelect) {
      modeSelect.value = creds.yoto_connection_mode || "bridge";
      onYotoModeChange();
    }

    // Load master security API key
    await loadMasterApiKey();

    // Load preferences / catalog display settings
    await loadCatalogSettings();

    // Load default children tags and fetch live ABS server tags
    await loadAbsDefaultTags();
    await fetchAbsServerTags();
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

  const excludeVal = toggleExclude ? toggleExclude.checked : true;
  const refreshEnabled = toggleRefresh ? toggleRefresh.checked : true;
  const refreshHours = selectHours ? parseFloat(selectHours.value) : 6.0;

  try {
    const res = await fetch("/api/admin/settings/catalog", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exclude_single_card_series: excludeVal,
        auto_library_refresh_enabled: refreshEnabled,
        auto_library_refresh_hours: refreshHours
      })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
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

async function saveBridgeSettings() {
  const btn = document.getElementById("btnSaveBridge");
  if (btn) { btn.disabled = true; btn.innerText = "💾 Saving..."; }

  const url = document.getElementById("credBridgeUrl").value.trim();
  const apiKey = document.getElementById("credBridgeApiKey") ? document.getElementById("credBridgeApiKey").value.trim() : "";
  const mode = document.getElementById("yotoConnectionMode").value;

  const success = await saveApiCredentialsPartial({
    yoto_connection_mode: mode,
    yoto_bridge_url: url,
    yoto_bridge_api_key: apiKey
  });

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save"; }
  if (success) {
    const statusEl = document.getElementById("bridgeStatusInline");
    if (statusEl) statusEl.innerText = "Saved. Click Test Connection to verify.";
  }
}

async function saveYotoStandaloneSettings() {
  const btn = document.getElementById("btnSaveYoto");
  if (btn) { btn.disabled = true; btn.innerText = "💾 Saving..."; }

  const mode = document.getElementById("yotoConnectionMode").value;
  const clientId = document.getElementById("credYotoClientId").value.trim();
  const secret = document.getElementById("credYotoSecret").value.trim();
  const refresh = document.getElementById("credYotoRefresh").value.trim();

  const success = await saveApiCredentialsPartial({
    yoto_connection_mode: mode,
    yoto_client_id: clientId,
    yoto_client_secret: secret,
    yoto_refresh_token: refresh
  });

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save"; }
  if (success) {
    const statusEl = document.getElementById("yotoStatusInline");
    if (statusEl) statusEl.innerText = "Saved. Click Test OAuth to verify.";
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

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save"; }
  if (success) {
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

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save"; }
  if (success) {
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

  if (btn) { btn.disabled = false; btn.innerText = "💾 Save"; }
  if (success) {
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
      showToast(`${target.toUpperCase()} PASSED: ${msg}`, "success");
    } else {
      const err = data.error || "Connection check failed.";
      if (statusEl) {
        statusEl.innerHTML = `<span style="color: var(--accent-danger);">❌ ${escapeHtml(err)}</span>`;
      }
      showToast(`${target.toUpperCase()} failed: ${err}`, "danger");
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerHTML = `<span style="color: var(--accent-danger);">❌ Network error reaching endpoint.</span>`;
    }
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
