// ============================================================================
// Firmware Repository, Remote OTA Deployment & MicroSD Cache Controls (DLP-010, DLP-020)
// ============================================================================

let currentFirmwareReleases = [];
let pushFirmwareTargetMac = null;
let selectedPushFirmwareVersion = null;
let otaProgressPollTimer = null;

async function loadFirmwareReleases() {
  try {
    const res = await fetch("/api/admin/firmware");
    if (!res.ok) return;
    currentFirmwareReleases = await res.json();
    renderFirmwareReleasesTable();
  } catch (err) {
    console.error("Error loading firmware releases:", err);
  }
}

function renderFirmwareReleasesTable() {
  const tbody = document.getElementById("firmwareReleasesBody");
  const countBadge = document.getElementById("firmwareCountBadge");
  const latestBadge = document.getElementById("firmwareLatestBadge");
  if (!tbody) return;

  const list = Array.isArray(currentFirmwareReleases) ? currentFirmwareReleases : [];
  if (countBadge) {
    countBadge.textContent = `${list.length} release${list.length === 1 ? "" : "s"}`;
  }
  const activeLatest = list.find(r => r.is_active_latest);
  if (latestBadge) {
    latestBadge.textContent = activeLatest ? `Latest: ${activeLatest.version}` : "Latest: None";
  }

  tbody.innerHTML = "";
  if (list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">No firmware binaries uploaded yet. Click 'Upload Firmware (.bin)' to add one.</td></tr>`;
    return;
  }

  list.forEach(r => {
    const tr = document.createElement("tr");
    const shortSha = (r.sha256_hash || "").slice(0, 12);
    const statusBadge = r.is_active_latest
      ? `<span class="badge badge-success">★ Active Latest</span>`
      : `<span class="badge badge-subtle">Archived</span>`;
    const fileMissingWarn = !r.file_exists
      ? `<span class="badge badge-danger" style="margin-left: 4px;">Missing .bin</span>`
      : "";
    const commitHtml = r.git_commit
      ? `<div style="font-size: 11px; font-family: monospace; color: var(--text-muted);">${escapeHtml(r.git_commit)}</div>`
      : "";

    tr.innerHTML = `
      <td><strong style="font-family: monospace;">${escapeHtml(r.version)}</strong></td>
      <td>
        <div>${escapeHtml(r.release_tag || r.version)}</div>
        ${commitHtml}
      </td>
      <td>${escapeHtml(r.file_size_human || "")}</td>
      <td><code title="${escapeHtml(r.sha256_hash || "")}" style="font-size: 11px;">${escapeHtml(shortSha)}...</code></td>
      <td style="max-width: 260px; font-size: 12px; color: var(--text-secondary);">${escapeHtml(r.release_notes || "—")}</td>
      <td>${statusBadge}${fileMissingWarn}</td>
      <td style="white-space: nowrap;">
        <div style="display: flex; gap: 6px;">
          ${!r.is_active_latest
            ? `<button type="button" class="btn btn-secondary btn-sm" onclick="setLatestFirmwareRelease('${escapeHtml(r.version)}')">★ Set Latest</button>`
            : ""
          }
          <button type="button" class="btn btn-secondary btn-sm" style="color: var(--accent-danger);" onclick="deleteFirmwareRelease('${escapeHtml(r.version)}')">🗑️ Delete</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderDeviceOtaBadge(device) {
  const status = (device.ota_status || "idle").toLowerCase();
  const prog = Number(device.ota_progress || 0);
  const target = device.target_firmware_version ? ` → ${escapeHtml(device.target_firmware_version)}` : "";

  if (status === "idle" && prog === 0 && !device.ota_last_error) {
    return "";
  }
  if (status === "idle" && prog === 100) {
    return `<div style="margin-top: 4px;"><span class="badge badge-success" style="font-size: 10px;">✓ OTA Verified</span></div>`;
  }
  if (status === "pending" || status === "downloading" || status === "flashing" || status === "flashing_done") {
    return `
      <div style="margin-top: 4px;">
        <span class="badge badge-warning" style="font-size: 10px;">⏳ ${escapeHtml(status.toUpperCase())} ${prog}%${target}</span>
      </div>
    `;
  }
  if (status === "failed" || status === "rolled_back") {
    const errTitle = device.ota_last_error ? `title="${escapeHtml(device.ota_last_error)}"` : "";
    return `
      <div style="margin-top: 4px;">
        <span class="badge badge-danger" ${errTitle} style="font-size: 10px;">⚠️ ${escapeHtml(status.replace("_", " ").toUpperCase())}</span>
      </div>
    `;
  }
  return "";
}

function syncOtaProgressPolling() {
  const list = Array.isArray(currentDevices) ? currentDevices : [];
  const activeOta = list.some(d => {
    const st = (d.ota_status || "idle").toLowerCase();
    return st === "pending" || st === "downloading" || st === "flashing" || st === "flashing_done";
  });

  if (activeOta && !otaProgressPollTimer) {
    otaProgressPollTimer = setInterval(() => {
      if (typeof loadDevices === "function") loadDevices();
    }, 3000);
  } else if (!activeOta && otaProgressPollTimer) {
    clearInterval(otaProgressPollTimer);
    otaProgressPollTimer = null;
  }
}

function openUploadFirmwareModal() {
  const fileEl = document.getElementById("uploadFirmwareFile");
  if (fileEl) fileEl.value = "";
  document.getElementById("uploadFirmwareVersion").value = "";
  document.getElementById("uploadFirmwareTag").value = "";
  document.getElementById("uploadFirmwareCommit").value = "";
  document.getElementById("uploadFirmwareNotes").value = "";
  document.getElementById("uploadFirmwareSetLatest").checked = true;
  document.getElementById("uploadFirmwareModal").style.display = "flex";
}

function closeUploadFirmwareModal() {
  const modal = document.getElementById("uploadFirmwareModal");
  if (modal) modal.style.display = "none";
}

async function submitUploadFirmware() {
  const fileEl = document.getElementById("uploadFirmwareFile");
  const version = document.getElementById("uploadFirmwareVersion").value.trim();
  const tag = document.getElementById("uploadFirmwareTag").value.trim();
  const commit = document.getElementById("uploadFirmwareCommit").value.trim();
  const notes = document.getElementById("uploadFirmwareNotes").value.trim();
  const setLatest = document.getElementById("uploadFirmwareSetLatest").checked;

  if (!fileEl || !fileEl.files || fileEl.files.length === 0) {
    showToast("Please select a .bin firmware file.", "danger");
    return;
  }
  if (!version) {
    showToast("Please enter a semantic version (e.g. v1.2.1).", "danger");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileEl.files[0]);
  formData.append("version", version);
  if (tag) formData.append("release_tag", tag);
  if (commit) formData.append("git_commit", commit);
  if (notes) formData.append("release_notes", notes);
  formData.append("is_active_latest", setLatest ? "true" : "false");

  try {
    const res = await fetch("/api/admin/firmware/upload", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Uploaded firmware ${version}!`, "success");
      closeUploadFirmwareModal();
      await loadFirmwareReleases();
    } else {
      showToast(data.error || `Upload failed (HTTP ${res.status})`, "danger");
    }
  } catch (err) {
    showToast("Network error uploading firmware: " + err.message, "danger");
  }
}

async function setLatestFirmwareRelease(version) {
  try {
    const res = await fetch(`/api/admin/firmware/${encodeURIComponent(version)}/set-latest`, {
      method: "POST",
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`${version} marked as active latest release.`, "success");
      await loadFirmwareReleases();
    } else {
      showToast(data.error || "Failed updating active latest firmware.", "danger");
    }
  } catch (err) {
    showToast("Network error updating firmware release.", "danger");
  }
}

async function deleteFirmwareRelease(version) {
  if (!confirm(`Delete firmware release ${version} and its binary image from disk?`)) return;
  try {
    const res = await fetch(`/api/admin/firmware/${encodeURIComponent(version)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Deleted firmware release ${version}.`, "success");
      await loadFirmwareReleases();
    } else {
      showToast(data.error || "Failed deleting firmware release.", "danger");
    }
  } catch (err) {
    showToast("Network error deleting firmware release.", "danger");
  }
}

async function openPushFirmwareModal(mac) {
  if (!Array.isArray(currentFirmwareReleases) || currentFirmwareReleases.length === 0) {
    await loadFirmwareReleases();
  }
  const dev = (currentDevices || []).find(d => d.mac_address === mac);
  if (!dev) return;

  pushFirmwareTargetMac = mac;
  document.getElementById("pushFirmwareDeviceName").textContent = dev.friendly_name || "ESP32 Touch";
  document.getElementById("pushFirmwareDeviceMac").textContent = mac;
  const curVer = dev.firmware_version || "1.0.0";
  document.getElementById("pushFirmwareCurrentVer").textContent = curVer.startsWith("v") ? curVer : `v${curVer}`;
  document.getElementById("pushFirmwareForce").checked = false;

  const listEl = document.getElementById("pushFirmwareVersionList");
  listEl.innerHTML = "";
  if (currentFirmwareReleases.length === 0) {
    listEl.innerHTML = `<div class="text-secondary" style="padding: 12px; font-size: 12px;">No firmware releases cataloged yet. Upload a .bin first.</div>`;
    document.getElementById("pushFirmwareChangelog").textContent = "—";
    selectedPushFirmwareVersion = null;
  } else {
    const defaultRel = currentFirmwareReleases.find(r => r.is_active_latest) || currentFirmwareReleases[0];
    selectedPushFirmwareVersion = defaultRel.version;

    currentFirmwareReleases.forEach(r => {
      const checked = r.version === selectedPushFirmwareVersion ? "checked" : "";
      const isCur = (r.version === curVer || r.version === `v${curVer}`) ? `<span class="badge badge-subtle">CURRENT</span>` : "";
      const isLat = r.is_active_latest ? `<span class="badge badge-success">LATEST</span>` : "";
      const row = document.createElement("label");
      row.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 10px; background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 6px; cursor: pointer;";
      row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px;">
          <input type="radio" name="pushFirmwareVersionRadio" value="${escapeHtml(r.version)}" ${checked} onchange="selectPushFirmwareVersion('${escapeHtml(r.version)}')">
          <strong style="font-family: monospace;">${escapeHtml(r.version)}</strong>
          <span class="text-secondary" style="font-size: 12px;">${escapeHtml(r.release_tag || "")}</span>
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          ${isCur}${isLat}
          <span class="text-muted" style="font-size: 11px;">${escapeHtml(r.file_size_human || "")}</span>
        </div>
      `;
      listEl.appendChild(row);
    });
    selectPushFirmwareVersion(selectedPushFirmwareVersion);
  }

  document.getElementById("pushFirmwareModal").style.display = "flex";
}

function selectPushFirmwareVersion(version) {
  selectedPushFirmwareVersion = version;
  const rel = currentFirmwareReleases.find(r => r.version === version);
  const logEl = document.getElementById("pushFirmwareChangelog");
  if (!rel || !logEl) return;
  const sha = (rel.sha256_hash || "").slice(0, 16);
  logEl.textContent = `${rel.release_notes || "No release notes provided."}\nSHA-256: ${sha}...`;
}

function closePushFirmwareModal() {
  pushFirmwareTargetMac = null;
  const modal = document.getElementById("pushFirmwareModal");
  if (modal) modal.style.display = "none";
}

async function submitPushFirmware() {
  if (!pushFirmwareTargetMac || !selectedPushFirmwareVersion) {
    showToast("Select a firmware version first.", "danger");
    return;
  }
  const force = document.getElementById("pushFirmwareForce").checked;
  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(pushFirmwareTargetMac)}/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: selectedPushFirmwareVersion, force }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`OTA initiated for ${pushFirmwareTargetMac} -> ${selectedPushFirmwareVersion}`, "success");
      closePushFirmwareModal();
      if (typeof loadDevices === "function") await loadDevices();
    } else {
      showToast(data.error || `OTA trigger failed (HTTP ${res.status})`, "danger");
    }
  } catch (err) {
    showToast("Network error dispatching OTA: " + err.message, "danger");
  }
}

async function pushFirmwareUpdateAll() {
  if (!Array.isArray(currentFirmwareReleases) || currentFirmwareReleases.length === 0) {
    await loadFirmwareReleases();
  }
  const latest = currentFirmwareReleases.find(r => r.is_active_latest) || currentFirmwareReleases[0];
  if (!latest) {
    showToast("Upload a firmware release first before pushing fleet updates.", "warning");
    return;
  }
  if (!confirm(`Push firmware ${latest.version} to all approved ESP32 Touch displays on the LAN?`)) {
    return;
  }
  try {
    const res = await fetch("/api/admin/devices/update-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: latest.version, force: false, delay_seconds: 0 }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`OTA update-all (${latest.version}): ${data.dispatched || 0} initiated, ${data.skipped || 0} skipped.`, "success");
      if (typeof loadDevices === "function") await loadDevices();
    } else {
      showToast(data.error || "Batch OTA update failed.", "danger");
    }
  } catch (err) {
    showToast("Network error running batch OTA update: " + err.message, "danger");
  }
}

// ============================================================================
// Touch MicroSD Cache Controls (DLP-020)
// ============================================================================

async function fetchDeviceCacheStatus(mac) {
  const safeMac = mac.replace(/[:]/g, "");
  const slot = document.getElementById(`sd-status-${safeMac}`);
  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(mac)}/cache/status`);
    const data = await res.json();
    if (res.ok && data.ok && data.sd) {
      const sd = data.sd;
      const used = sd.used_mb !== undefined ? `${sd.used_mb} MB` : "?";
      const files = sd.files !== undefined ? `${sd.files} files` : "";
      const orphans = sd.orphans > 0 ? ` (${sd.orphans} orphans)` : "";
      const text = `💾 SD: ${used}${files ? " • " + files : ""}${orphans}`;
      if (slot) {
        slot.innerHTML = `<span class="badge badge-subtle" style="font-size: 10px;">${escapeHtml(text)}</span>`;
      }
      showToast(`${mac}: ${text}`, "success");
    } else {
      showToast(data.error || `Failed fetching SD status for ${mac}`, "warning");
    }
  } catch (err) {
    showToast("Network error checking Touch MicroSD status: " + err.message, "danger");
  }
}

async function pruneDeviceCache(mac) {
  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(mac)}/cache/prune`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      const devResp = data.device_response || {};
      const deleted = devResp.deleted_count !== undefined ? ` (${devResp.deleted_count} orphan file(s) removed)` : "";
      showToast(`MicroSD orphan prune triggered on ${mac}${deleted}.`, "success");
    } else {
      showToast(data.error || `Failed pruning MicroSD cache on ${mac}`, "danger");
    }
  } catch (err) {
    showToast("Network error pruning Touch MicroSD cache: " + err.message, "danger");
  }
}

async function purgeDeviceCache(mac) {
  if (!confirm(`Wipe the entire MicroSD /ythumbs/ artwork cache on Touch controller ${mac}? It will rebuild automatically in the background.`)) {
    return;
  }
  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(mac)}/cache`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`MicroSD cache purged on ${mac}; background rebuild started.`, "success");
    } else {
      showToast(data.error || `Failed purging MicroSD cache on ${mac}`, "danger");
    }
  } catch (err) {
    showToast("Network error purging Touch MicroSD cache: " + err.message, "danger");
  }
}
