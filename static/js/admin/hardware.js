// ============================================================================
// Hardware Displays (Tab 3)
// ============================================================================

let currentEditDeviceMac = null;

async function loadDevices() {
  try {
    if (typeof fetchDiscoveredPlayers === "function") {
      await fetchDiscoveredPlayers();
    }
    const res = await fetch("/api/admin/devices");
    if (!res.ok) return;
    currentDevices = await res.json();
    renderDevicesTable();
  } catch (err) {
    console.error("Error loading devices:", err);
  }
}

function getPlayerDisplayName(playerId) {
  if (!playerId) return "";
  if (Array.isArray(cachedDiscoveredPlayers)) {
    const found = cachedDiscoveredPlayers.find(p => p.id === playerId);
    if (found && found.name) return found.name;
  }
  return playerId;
}

function renderDevicesTable() {
  const tbody = document.getElementById("devicesTableBody");
  tbody.innerHTML = "";

  if (currentDevices.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No ESP32 controllers discovered yet. Power on your controller to connect.</td></tr>`;
    return;
  }

  currentDevices.forEach(d => {
    const tr = document.createElement("tr");

    // Profile display pill
    let profileDisplay = `<span style="color: var(--text-muted);">None</span>`;
    if (d.assigned_profile_id && currentProfiles[d.assigned_profile_id]) {
      const p = currentProfiles[d.assigned_profile_id];
      const avColor = p.avatar_color || "#3b82f6";
      const initial = p.avatar_initial || (p.display_name ? p.display_name[0] : "P");
      profileDisplay = `
        <div style="display: inline-flex; align-items: center; gap: 8px; background: rgba(255,255,255,0.06); padding: 4px 10px; border-radius: 14px; border: 1px solid var(--border-color);">
          <span style="display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: ${avColor}; color: #fff; font-size: 11px; font-weight: bold;">${escapeHtml(initial)}</span>
          <span style="font-weight: 500;">${escapeHtml(p.display_name)}</span>
        </div>
      `;
    }

    // Player display pill
    let playerDisplay = `<span style="color: var(--text-muted);">None</span>`;
    if (d.locked_player_id) {
      const pName = getPlayerDisplayName(d.locked_player_id);
      playerDisplay = `
        <div style="display: inline-flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.06); padding: 4px 10px; border-radius: 14px; border: 1px solid var(--border-color);">
          <span style="color: #10b981; font-size: 10px;">●</span>
          <span style="font-weight: 500;">${escapeHtml(pName)}</span>
        </div>
      `;
    }

    const statusBadge = d.is_approved
      ? `<span class="badge badge-success">Approved</span>`
      : `<span class="badge badge-danger">Quarantined</span>`;

    const ipDisplay = d.ip_address ? `<span id="ping-${d.mac_address.replace(/:/g, '')}">${escapeHtml(d.ip_address)}</span>` : "Unknown";

    const editBtn = `<button class="btn btn-primary btn-sm" title="Configure Profile & Player" onclick="openEditDeviceModal('${escapeHtml(d.mac_address)}')">⚙️ Edit</button>`;
    const pingBtn = `<button class="btn btn-secondary btn-sm" style="margin-left: 4px;" title="Ping Device" onclick="pingSingleDevice('${escapeHtml(d.mac_address)}')">📡</button>`;
    const deleteBtn = `<button class="btn btn-danger btn-sm" style="margin-left: 4px;" title="Delete Device" onclick="deleteDevice('${escapeHtml(d.mac_address)}')">🗑️</button>`;

    let actionBtns = "";
    if (d.is_approved) {
      actionBtns = `
        ${editBtn}
        <button class="btn btn-secondary btn-sm" style="margin-left: 4px;" onclick="toggleDeviceApproval('${escapeHtml(d.mac_address)}', false)">Quarantine</button>
        <button class="btn btn-secondary btn-sm" style="margin-left: 4px;" onclick="openResetPinModal('${escapeHtml(d.mac_address)}', '${escapeHtml(d.friendly_name)}')">🔑 PIN</button>
        <button class="btn btn-secondary btn-sm" style="margin-left: 4px;" onclick="revokeDeviceAccess('${escapeHtml(d.mac_address)}')">🔒 Revoke</button>
        ${pingBtn}
        ${deleteBtn}
      `;
    } else {
      actionBtns = `
        <button class="btn btn-primary btn-sm" onclick="toggleDeviceApproval('${escapeHtml(d.mac_address)}', true)">Approve Device</button>
        ${editBtn}
        ${pingBtn}
        ${deleteBtn}
      `;
    }

    tr.innerHTML = `
      <td><strong>${escapeHtml(d.friendly_name)}</strong></td>
      <td><code>${escapeHtml(d.mac_address)}</code></td>
      <td>${ipDisplay}</td>
      <td>${profileDisplay}</td>
      <td>${playerDisplay}</td>
      <td>${statusBadge}</td>
      <td style="white-space: nowrap;">${actionBtns}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function toggleDeviceApproval(mac, approve) {
  try {
    await fetch(`/api/admin/devices/${encodeURIComponent(mac)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_approved: approve })
    });
    showToast(approve ? "Device approved!" : "Device placed in quarantine.");
    loadDevices();
  } catch (err) {
    showToast("Failed to update device approval.", "danger");
  }
}

// ============================================================================
// Edit Device Modal Logic
// ============================================================================

async function openEditDeviceModal(mac) {
  if (!Array.isArray(cachedDiscoveredPlayers) || cachedDiscoveredPlayers.length === 0) {
    try {
      const pRes = await fetch("/api/admin/discovery/players");
      if (pRes.ok) cachedDiscoveredPlayers = await pRes.json();
    } catch(e) {}
  }
  const d = currentDevices.find(x => x.mac_address === mac);
  if (!d) return;

  currentEditDeviceMac = mac;
  document.getElementById("editDeviceFriendlyName").textContent = d.friendly_name || "ESP32 Controller";
  document.getElementById("editDeviceMac").textContent = mac;
  document.getElementById("editDeviceNameInput").value = d.friendly_name || "";

  // Populate profiles dropdown
  const profSelect = document.getElementById("editDeviceProfileSelect");
  profSelect.innerHTML = `<option value="">-- Shared / Select at Boot --</option>`;
  Object.keys(currentProfiles).forEach(pid => {
    const selected = d.assigned_profile_id === pid ? "selected" : "";
    profSelect.innerHTML += `<option value="${pid}" ${selected}>${escapeHtml(currentProfiles[pid].display_name)}</option>`;
  });

  populateEditDevicePlayers(d.assigned_profile_id, d.locked_player_id);

  const modalEl = document.getElementById("editDeviceModal");
  if (modalEl) modalEl.style.display = "flex";
}

function onEditDeviceProfileChange() {
  const profId = document.getElementById("editDeviceProfileSelect").value;
  const d = currentDevices.find(x => x.mac_address === currentEditDeviceMac);
  const currentLock = d ? d.locked_player_id : "";
  populateEditDevicePlayers(profId, currentLock);
}

function populateEditDevicePlayers(profId, selectedPlayerId) {
  const playerSelect = document.getElementById("editDevicePlayerSelect");
  playerSelect.innerHTML = `<option value="">-- No Player Assigned --</option>`;

  const prof = currentProfiles[profId];
  const preferredId = (prof && prof.default_player_id) ? prof.default_player_id : "";
  const profPlayerIds = (prof && Array.isArray(prof.player_ids)) ? prof.player_ids : [];

  let players = Array.isArray(cachedDiscoveredPlayers) ? [...cachedDiscoveredPlayers] : [];
  if (players.length === 0 && selectedPlayerId) {
    players.push({ id: selectedPlayerId, name: getPlayerDisplayName(selectedPlayerId), online: true });
  }

  let matched = false;
  players.forEach(p => {
    const isPreferred = (p.id === preferredId) || profPlayerIds.includes(p.id);
    const isSel = (p.id === selectedPlayerId) || (!matched && !selectedPlayerId && isPreferred);
    if (isSel) matched = true;
    const statusText = p.online ? "Online" : "Offline";
    const label = `${p.name || p.id}${isPreferred ? " (Profile Default)" : ""} • ${statusText}`;
    playerSelect.innerHTML += `<option value="${escapeHtml(p.id)}" ${isSel ? "selected" : ""}>${escapeHtml(label)}</option>`;
  });
}

function closeEditDeviceModal() {
  currentEditDeviceMac = null;
  const modalEl = document.getElementById("editDeviceModal");
  if (modalEl) modalEl.style.display = "none";
}

async function submitEditDevice() {
  if (!currentEditDeviceMac) return;
  const friendlyName = (document.getElementById("editDeviceNameInput").value || "").trim();
  const assignedProfile = document.getElementById("editDeviceProfileSelect").value || null;
  const lockedPlayer = document.getElementById("editDevicePlayerSelect").value || "";

  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(currentEditDeviceMac)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        friendly_name: friendlyName,
        assigned_profile_id: assignedProfile,
        locked_player_id: lockedPlayer,
        lock_player: lockedPlayer ? 1 : 0
      })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Device configuration saved!", "success");
      closeEditDeviceModal();
      loadDevices();
    } else {
      showToast(data.error || "Failed to save device settings.", "danger");
    }
  } catch (err) {
    showToast("Network error saving device settings.", "danger");
  }
}

async function revokeDeviceAccess(mac) {
  if (!confirm(`Are you sure you want to revoke all access tokens for ESP32 device ${mac}? The controller will immediately be returned to pairing quarantine.`)) {
    return;
  }
  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(mac)}/revoke`, {
      method: "POST"
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Device tokens revoked. Controller placed in quarantine.", "success");
      loadDevices();
    } else {
      showToast(data.error || "Failed to revoke device.", "danger");
    }
  } catch (err) {
    showToast("Network error revoking device.", "danger");
  }
}

// ============================================================================
// OTA PIN Reset Modal Logic
// ============================================================================

let currentResetPinMac = null;

function openResetPinModal(mac, friendlyName) {
  currentResetPinMac = mac;
  const nameEl = document.getElementById("resetPinDeviceName");
  const macEl = document.getElementById("resetPinDeviceMac");
  const inputEl = document.getElementById("resetPinInput");
  const modalEl = document.getElementById("resetDevicePinModal");

  if (nameEl) nameEl.textContent = friendlyName || "Controller";
  if (macEl) macEl.textContent = mac;
  if (inputEl) inputEl.value = "1234";
  if (modalEl) modalEl.style.display = "flex";
}

function closeResetPinModal() {
  currentResetPinMac = null;
  const modalEl = document.getElementById("resetDevicePinModal");
  if (modalEl) modalEl.style.display = "none";
}

async function submitResetPin() {
  if (!currentResetPinMac) return;
  const inputEl = document.getElementById("resetPinInput");
  const pin = (inputEl ? inputEl.value : "").trim();

  if (!pin || pin.length !== 4 || !/^\d{4}$/.test(pin)) {
    showToast("Parent PIN must be exactly 4 numeric digits.", "danger");
    if (inputEl) inputEl.focus();
    return;
  }

  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(currentResetPinMac)}/reset-pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: pin })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Parent PIN for ${currentResetPinMac} reset to ${pin}!`, "success");
      closeResetPinModal();
      loadDevices();
    } else {
      showToast(data.error || "Failed to reset device PIN.", "danger");
    }
  } catch (err) {
    showToast("Network error resetting device PIN.", "danger");
  }
}

// ============================================================================
// Device Management (Delete, Ping, Prune)
// ============================================================================

async function deleteDevice(mac) {
  if (!confirm(`Are you sure you want to remove device ${mac} from the controller list? If online, it will re-announce itself.`)) {
    return;
  }
  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(mac)}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Device ${mac} deleted.`, "success");
      loadDevices();
    } else {
      showToast(data.error || "Failed to delete device.", "danger");
    }
  } catch (err) {
    showToast("Network error deleting device.", "danger");
  }
}

async function pingSingleDevice(mac) {
  const elId = "ping-" + mac.replace(/:/g, "");
  const el = document.getElementById(elId);
  const origText = el ? el.textContent : "";
  if (el) el.innerHTML = `${origText} <span class="spinner-border spinner-border-sm"></span>`;
  try {
    const res = await fetch(`/api/admin/devices/${encodeURIComponent(mac)}/ping`);
    const data = await res.json();
    if (res.ok && data.online) {
      showToast(`Device ${mac} is ONLINE at ${data.ip}`, "success");
      if (el) el.innerHTML = `${data.ip} <span style="color: #10b981; font-weight: bold;">● Online</span>`;
    } else {
      showToast(`Device ${mac} is OFFLINE (${data.error || 'unreachable'})`, "warning");
      if (el) el.innerHTML = `${origText} <span style="color: #ef4444; font-weight: bold;">● Offline</span>`;
    }
  } catch (err) {
    showToast(`Failed to ping ${mac}`, "danger");
    if (el) el.textContent = origText;
  }
}

async function pingAllDevices() {
  if (!currentDevices || currentDevices.length === 0) {
    showToast("No devices to ping.", "info");
    return;
  }
  showToast(`Pinging ${currentDevices.length} device(s)...`, "info");
  for (const d of currentDevices) {
    await pingSingleDevice(d.mac_address);
  }
}

async function pruneStaleDevices() {
  if (!confirm("Are you sure you want to remove all unapproved devices that have been inactive for over 48 hours?")) {
    return;
  }
  try {
    const res = await fetch("/api/admin/devices/prune", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hours: 48 })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(data.message || `Pruned ${data.pruned} inactive device(s).`, "success");
      loadDevices();
    } else {
      showToast(data.error || "Failed to prune inactive devices.", "danger");
    }
  } catch (err) {
    showToast("Network error pruning devices.", "danger");
  }
}
