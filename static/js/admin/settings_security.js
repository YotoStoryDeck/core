// ============================================================================
// Admin Settings: Master API Key & Core Version Checker
// ============================================================================

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
  } else if (confirm("Regenerate Broker Master API Key?\n\nWarning: External services (Home Assistant, scripts) using the old key will immediately lose access until updated.")) {
    executeRegenerateMasterApiKey();
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
    const res = await fetch("/api/admin/security/regenerate-api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true })
    });
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

// ============================================================================
// Core Version & Upstream Update Checker (Feature 022)
// ============================================================================

function _normalizeVersionTag(raw) {
  const clean = String(raw || "").trim().replace(/^v+/i, "");
  return clean ? `v${clean}` : "";
}

async function checkCoreUpdates(force = false) {
  const btn = document.getElementById("btnCheckUpdates");
  const badge = document.getElementById("versionStatusBadge");
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

    const curVer = _normalizeVersionTag(data.current_version || "v1.1.0-dev");
    const isPre = data.is_prerelease;
    const hasUpdate = Boolean(data.has_update);
    const latestVer = _normalizeVersionTag(data.latest_version || curVer);

    if (window.StoryDeckHealth && typeof window.StoryDeckHealth.setUpdateInfo === "function") {
      window.StoryDeckHealth.setUpdateInfo({
        currentVersion: curVer,
        latestVersion: latestVer,
        hasUpdate
      });
    }

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
