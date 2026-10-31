// ============================================================================
// Hardware Displays (Tab 3)
// ============================================================================

async function loadDevices() {
  try {
    const res = await fetch("/api/admin/devices");
    if (!res.ok) return;
    currentDevices = await res.json();
    renderDevicesTable();
  } catch (err) {
    console.error("Error loading devices:", err);
  }
}

function renderDevicesTable() {
  const tbody = document.getElementById("devicesTableBody");
  tbody.innerHTML = "";

  if (currentDevices.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 24px;">No ESP32 controllers discovered yet. Power on your controller to connect.</td></tr>`;
    return;
  }

  currentDevices.forEach(d => {
    const tr = document.createElement("tr");

    // Profile options dropdown
    let profileOptions = `<option value="">-- Shared / Select at Boot --</option>`;
    Object.keys(currentProfiles).forEach(pid => {
      const selected = d.assigned_profile_id === pid ? "selected" : "";
      profileOptions += `<option value="${pid}" ${selected}>${escapeHtml(currentProfiles[pid].display_name)}</option>`;
    });

    const statusBadge = d.is_approved
      ? `<span class="badge badge-success">Approved</span>`
      : `<span class="badge badge-danger">Quarantined</span>`;

    const actionBtns = d.is_approved
      ? `<button class="btn btn-secondary btn-sm" onclick="toggleDeviceApproval('${escapeHtml(d.mac_address)}', false)">Quarantine</button>
         <button class="btn btn-danger btn-sm" style="margin-left: 6px;" onclick="revokeDeviceAccess('${escapeHtml(d.mac_address)}')">🔒 Revoke</button>`
      : `<button class="btn btn-primary btn-sm" onclick="toggleDeviceApproval('${escapeHtml(d.mac_address)}', true)">Approve Device</button>`;

    tr.innerHTML = `
      <td><strong>${escapeHtml(d.friendly_name)}</strong></td>
      <td><code>${escapeHtml(d.mac_address)}</code></td>
      <td>${escapeHtml(d.ip_address || "Unknown")}</td>
      <td>
        <select class="form-control" style="max-width: 200px;" onchange="assignDeviceProfile('${escapeHtml(d.mac_address)}', this.value)">
          ${profileOptions}
        </select>
      </td>
      <td>${statusBadge}</td>
      <td>${actionBtns}</td>
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

async function assignDeviceProfile(mac, profileId) {
  try {
    await fetch(`/api/admin/devices/${encodeURIComponent(mac)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assigned_profile_id: profileId || null })
    });
    showToast("Default profile assigned to device.");
  } catch (err) {
    showToast("Failed to assign profile.", "danger");
  }
}
