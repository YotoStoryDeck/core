// ============================================================================
// Profiles Management (Tab 1)
// ============================================================================

async function loadProfiles() {
  try {
    const res = await fetch("/api/admin/profiles");
    if (!res.ok) return;
    currentProfiles = await res.json();
    renderProfileCards();
  } catch (err) {
    console.error("Error loading profiles:", err);
  }
}

function renderProfileCards() {
  const grid = document.getElementById("profileCardsGrid");
  grid.innerHTML = "";

  const keys = Object.keys(currentProfiles);
  if (keys.length === 0) {
    grid.innerHTML = "<p class='text-secondary'>No child profiles configured yet. Click '+ Add Child Profile' above.</p>";
    return;
  }

  const monograms = computeHouseholdMonograms(currentProfiles);

  keys.forEach(k => {
    const p = currentProfiles[k];
    const card = document.createElement("div");
    card.className = "profile-card";

    const allowedCount = (p.yoto && p.yoto.allowed_card_ids) ? p.yoto.allowed_card_ids.length : 0;
    const excludedCount = (p.yoto && p.yoto.excluded_card_ids) ? p.yoto.excluded_card_ids.length : 0;
    const additionalPlayers = (p.player_ids && p.player_ids.length > 0)
      ? p.player_ids.filter(id => id !== p.default_player_id).join(", ")
      : "";

    const monogram = p.avatar_initial || monograms[p.id] || (p.display_name || p.id || "C").trim().charAt(0).toUpperCase();
    const avatarBg = getAvatarColor(p.display_name || p.id, p.avatar_color);
    const fontSize = monogram.length > 1 ? "16px" : "20px";
    const avatarHtml = (p.avatar_url && !p.avatar_url.includes("avatar/placeholder"))
      ? `<img src="${escapeHtml(p.avatar_url)}" alt="${escapeHtml(p.display_name)}" onerror="this.onerror=null;this.replaceWith(createInitialAvatarElement('${escapeHtml(monogram)}', '${avatarBg}', 44));" style="width: 44px; height: 44px; border-radius: 50%; object-fit: cover; border: 2px solid var(--accent-info); flex-shrink: 0;">`
      : `<div style="width: 44px; height: 44px; border-radius: 50%; background: ${avatarBg}; color: #ffffff; display: flex; align-items: center; justify-content: center; font-size: ${fontSize}; font-weight: 700; flex-shrink: 0; box-shadow: 0 2px 8px rgba(0,0,0,0.25);">${escapeHtml(monogram)}</div>`;

    card.innerHTML = `
      <div class="profile-card-header" style="display: flex; align-items: center; gap: 12px;">
        ${avatarHtml}
        <div style="flex: 1; min-width: 0;">
          <div class="profile-card-title">${escapeHtml(p.display_name)}</div>
          <span class="badge badge-subtle" style="font-size: 10px;">${escapeHtml(p.id)}</span>
        </div>
      </div>
      <div>
        <p class="text-secondary"><strong>Audiobookshelf User:</strong> ${escapeHtml(p.abs_username || "Not assigned")}${p.abs_username ? ' <span class="badge badge-success" style="font-size: 10px;">Auto-linked</span>' : ''}${p.abs_api_key ? ' <span class="badge badge-subtle" style="font-size: 10px;">Custom Token</span>' : ''}</p>
        ${p.abs_tag ? `<p class="text-secondary"><strong>Tag Override:</strong> ${escapeHtml(p.abs_tag)}</p>` : ""}
        <p class="text-secondary"><strong>Primary Yoto Player:</strong> ${escapeHtml(p.default_player_id || "Unassigned")}</p>
        ${additionalPlayers ? `<p class="text-secondary"><strong>Additional / Communal:</strong> ${escapeHtml(additionalPlayers)}</p>` : ""}
        <p class="text-secondary"><strong>Custom Yoto Cards:</strong> ${allowedCount} allowed, ${excludedCount} excluded</p>
      </div>
      <div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border-subtle);">
        <p class="text-secondary" style="font-size: 11px; margin-bottom: 4px;"><strong>Rotation:</strong> ${p.catalog_rotation_limit || 80} cards (rolls at ${p.catalog_rotation_hour ?? 3}:00${p.hide_physical ? ', physical hidden' : ''})</p>
        <p class="text-secondary" style="font-size: 11px; margin-bottom: 8px;">
          <strong>Audio Delivery:</strong> ${p.default_playback_mode === 'offline' ? '<span class="badge badge-warning" style="font-size: 10px;">Offline (Yoto Cache)</span>' : '<span class="badge badge-info" style="font-size: 10px;">Streaming</span>'}
          <span style="font-size: 10px; color: var(--text-muted);">(Retain: ${p.offline_retention_limit || 8} recent books)</span>
        </p>
      </div>
      <div style="margin-top: auto; display: flex; flex-wrap: wrap; gap: 8px;">
        <button class="btn btn-secondary btn-sm" onclick="editProfile('${escapeHtml(p.id)}')">Edit</button>
        <button class="btn btn-secondary btn-sm" onclick="forceProfileRotationRefresh('${escapeHtml(p.id)}')" title="Force immediate catalog discovery rotation re-roll for ${escapeHtml(p.display_name)}">🔄 Refresh Rotation</button>
        <button class="btn btn-danger btn-sm" onclick="deleteProfile('${escapeHtml(p.id)}')">Delete</button>
      </div>
    `;
    grid.appendChild(card);
  });
}

let cachedDiscoveredPlayers = [];
let cachedDiscoveredAbsUsers = [];

async function fetchDiscoveredPlayers() {
  try {
    const res = await fetch("/api/admin/discovery/players");
    if (!res.ok) return [];
    cachedDiscoveredPlayers = await res.json();
    return cachedDiscoveredPlayers;
  } catch (err) {
    console.error("Failed to fetch discovery players:", err);
    return [];
  }
}

async function fetchDiscoveredAbsUsers() {
  try {
    const res = await fetch("/api/admin/discovery/abs-users");
    if (!res.ok) return [];
    cachedDiscoveredAbsUsers = await res.json();
    return cachedDiscoveredAbsUsers;
  } catch (err) {
    console.error("Failed to fetch ABS users:", err);
    return [];
  }
}

function onAbsUserSelectChange() {
  const select = document.getElementById("profileAbsUsernameSelect");
  const customInput = document.getElementById("profileAbsUsernameCustom");
  if (select.value === "__custom__") {
    customInput.style.display = "block";
    customInput.focus();
  } else {
    customInput.style.display = "none";
    // Also auto-sync tag if tag is empty or matches previous selection
    const tagInput = document.getElementById("profileAbsTag");
    if (!tagInput.value && select.value) {
      tagInput.value = select.value;
    }
  }
}

function syncPlayerCheckboxesWithPrimary() {
  const primaryId = document.getElementById("profilePlayerSelect").value;
  if (primaryId) {
    const cb = document.querySelector(`.profile-player-checkbox[value="${primaryId}"]`);
    if (cb) cb.checked = true;
  }
}

async function openProfileModal(existingId = null) {
  const prof = existingId ? currentProfiles[existingId] : null;
  const modal = document.getElementById("profileModal");
  const titleEl = document.getElementById("profileModalTitle");
  const editIdInput = document.getElementById("profileEditId");
  const nameInput = document.getElementById("profileDisplayName");
  const idInput = document.getElementById("profileIdField");
  const absSelect = document.getElementById("profileAbsUsernameSelect");
  const absCustom = document.getElementById("profileAbsUsernameCustom");
  const absApiKeyInput = document.getElementById("profileAbsApiKey");
  const tagInput = document.getElementById("profileAbsTag");
  const playerSelect = document.getElementById("profilePlayerSelect");
  const addlList = document.getElementById("profileAdditionalPlayersList");

  titleEl.innerText = existingId ? "✏️ Edit Child Profile" : "👶 Add Child Profile";
  editIdInput.value = existingId || "";

  // Curation Rotation & Physical settings
  const touchLimitInput = document.getElementById("profileTouchRotationLimit") || document.getElementById("profileRotationLimit");
  const kioskLimitInput = document.getElementById("profileKioskRotationLimit");
  const rotHourInput = document.getElementById("profileRotationHour");
  const hidePhysCheck = document.getElementById("profileHidePhysical");
  if (touchLimitInput) touchLimitInput.value = (prof && prof.catalog_rotation_limit) ? prof.catalog_rotation_limit : 60;
  if (kioskLimitInput) kioskLimitInput.value = (prof && prof.kiosk_catalog_limit !== undefined) ? prof.kiosk_catalog_limit : 0;
  if (rotHourInput) rotHourInput.value = (prof && prof.catalog_rotation_hour !== undefined) ? prof.catalog_rotation_hour : 3;
  if (hidePhysCheck) hidePhysCheck.checked = !!(prof && prof.hide_physical);

  // Audio Delivery & Offline Caching Preferences
  const defaultModeInput = document.getElementById("profileDefaultPlaybackMode");
  const retentionLimitInput = document.getElementById("profileOfflineRetentionLimit");
  const primaryCardInput = document.getElementById("profilePrimaryCardId");
  if (defaultModeInput) defaultModeInput.value = (prof && prof.default_playback_mode) ? prof.default_playback_mode : "streaming";
  if (retentionLimitInput) retentionLimitInput.value = (prof && prof.offline_retention_limit) ? prof.offline_retention_limit : 8;
  if (primaryCardInput) primaryCardInput.value = (prof && prof.primary_card_id) ? prof.primary_card_id : "";
  nameInput.value = prof ? prof.display_name : "";
  idInput.value = existingId || "";
  idInput.readOnly = !!existingId;
  absApiKeyInput.value = prof ? (prof.abs_api_key || "") : "";
  tagInput.value = prof ? prof.abs_tag : "";

  // Reset and initialize avatar preview & customizers
  pendingAvatarFile = null;
  document.getElementById("profileAvatarFileInput").value = "";
  document.getElementById("profileAvatarUrlInput").value = "";
  document.getElementById("profileAvatarUrlInput").style.display = "none";
  const initialColor = prof ? (prof.avatar_color || "") : "";
  const initialMono = prof ? (prof.avatar_initial || "") : "";
  document.getElementById("profileAvatarColorHidden").value = initialColor;
  document.getElementById("profileAvatarInitialInput").value = initialMono;
  renderColorSwatches(initialColor);
  updateAvatarPreview(prof ? (prof.avatar_url || "") : "", prof ? (prof.display_name || prof.id) : "");

  // Populate dynamic ABS User options
  absSelect.innerHTML = `<option value="">-- Unassigned (Master Library) --</option>`;
  absCustom.value = "";
  absCustom.style.display = "none";

  const absUsers = await fetchDiscoveredAbsUsers();
  const currentAbsUser = prof ? (prof.abs_username || "") : "";
  let matchedUserOption = false;

  absUsers.forEach(u => {
    const opt = document.createElement("option");
    opt.value = u.username;
    opt.innerText = `${u.username}${u.is_admin ? " (Admin)" : ""}`;
    if (currentAbsUser && currentAbsUser.toLowerCase() === u.username.toLowerCase()) {
      opt.selected = true;
      matchedUserOption = true;
    }
    absSelect.appendChild(opt);
  });

  const customOpt = document.createElement("option");
  customOpt.value = "__custom__";
  customOpt.innerText = "✍️ Custom / Enter Manually...";
  absSelect.appendChild(customOpt);

  if (currentAbsUser && !matchedUserOption) {
    absSelect.value = "__custom__";
    absCustom.value = currentAbsUser;
    absCustom.style.display = "block";
  }

  // Auto-fill ID from display name if creating new
  nameInput.oninput = () => {
    if (!editIdInput.value) {
      const slug = nameInput.value.toLowerCase().replace(/[^a-z0-9_]/g, "_");
      idInput.value = slug;
      // Preselect in ABS dropdown if username matches slug
      if (absSelect.value === "" || absSelect.value === "__custom__") {
        const option = Array.from(absSelect.options).find(o => o.value.toLowerCase() === slug);
        if (option) {
          absSelect.value = option.value;
          absCustom.style.display = "none";
        }
      }
    }
  };

  // Populate dynamic player options & checkboxes
  playerSelect.innerHTML = `<option value="">-- Unassigned (Auto-select on Playback) --</option>`;
  addlList.innerHTML = "";
  const players = await fetchDiscoveredPlayers();

  const assignedPlayers = new Set(prof && prof.player_ids ? prof.player_ids : []);
  if (prof && prof.default_player_id) {
    assignedPlayers.add(prof.default_player_id);
  }

  players.forEach(p => {
    // Primary Dropdown option
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.innerText = `${p.name} (${p.id})${p.online ? " • Online" : ""}`;
    if (prof && prof.default_player_id === p.id) {
      opt.selected = true;
    }
    playerSelect.appendChild(opt);

    // Multi-select Checkbox (additional or communal devices)
    const isChecked = assignedPlayers.has(p.id) ? "checked" : "";
    const row = document.createElement("label");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.gap = "8px";
    row.style.fontSize = "12px";
    row.style.cursor = "pointer";
    row.innerHTML = `
      <input type="checkbox" class="profile-player-checkbox" value="${escapeHtml(p.id)}" ${isChecked}>
      <span><strong>${escapeHtml(p.name)}</strong> <code style="font-size: 11px;">(${escapeHtml(p.id)})</code>${p.online ? " <span style='color: var(--accent-success);'>●</span>" : ""}</span>
    `;
    addlList.appendChild(row);
  });

  // Retain non-discovered configured player if present
  if (prof && prof.default_player_id && !players.some(p => p.id === prof.default_player_id)) {
    const customPlayerOpt = document.createElement("option");
    customPlayerOpt.value = prof.default_player_id;
    customPlayerOpt.innerText = `${prof.default_player_id} (Configured)`;
    customPlayerOpt.selected = true;
    playerSelect.appendChild(customPlayerOpt);

    const row = document.createElement("label");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.gap = "8px";
    row.style.fontSize = "12px";
    row.innerHTML = `
      <input type="checkbox" class="profile-player-checkbox" value="${escapeHtml(prof.default_player_id)}" checked>
      <span><code>${escapeHtml(prof.default_player_id)}</code> (Configured)</span>
    `;
    addlList.appendChild(row);
  }

  if (players.length === 0 && (!prof || !prof.default_player_id)) {
    addlList.innerHTML = `<span class="text-secondary" style="font-size: 12px;">No Yoto players discovered yet. Connect your Yoto account in Admin Settings to select devices.</span>`;
  }

  modal.style.display = "flex";
}

function closeProfileModal() {
  document.getElementById("profileModal").style.display = "none";
}

async function saveProfileForm(e) {
  e.preventDefault();
  const existingId = document.getElementById("profileEditId").value.trim();
  const name = document.getElementById("profileDisplayName").value.trim();
  const id = (existingId || document.getElementById("profileIdField").value.trim().toLowerCase()).replace(/[^a-z0-9_]/g, "_");
  
  // Resolve ABS Username from select or custom input
  const absSelect = document.getElementById("profileAbsUsernameSelect");
  const absCustom = document.getElementById("profileAbsUsernameCustom");
  let absUsername = absSelect.value === "__custom__" ? absCustom.value.trim() : absSelect.value.trim();

  const absApiKey = document.getElementById("profileAbsApiKey").value.trim();
  const absTag = document.getElementById("profileAbsTag").value.trim();
  const defPlayer = document.getElementById("profilePlayerSelect").value.trim();
  const avatarUrlHidden = document.getElementById("profileAvatarUrlHidden").value.trim();

  if (!id) {
    showToast("Profile ID is required.", "danger");
    return;
  }

  // Gather all selected players from checkboxes
  const selectedPlayers = [];
  document.querySelectorAll(".profile-player-checkbox:checked").forEach(cb => {
    selectedPlayers.push(cb.value);
  });
  if (defPlayer && !selectedPlayers.includes(defPlayer)) {
    selectedPlayers.unshift(defPlayer);
  }

  const avatarColorHidden = document.getElementById("profileAvatarColorHidden").value.trim();
  const avatarInitialInput = document.getElementById("profileAvatarInitialInput").value.trim().toUpperCase();

  const touchLimitEl = document.getElementById("profileTouchRotationLimit") || document.getElementById("profileRotationLimit");
  const kioskLimitEl = document.getElementById("profileKioskRotationLimit");
  const rotLimit = touchLimitEl ? (parseInt(touchLimitEl.value, 10) || 60) : 60;
  const kioskLimit = kioskLimitEl ? (parseInt(kioskLimitEl.value, 10) >= 0 ? parseInt(kioskLimitEl.value, 10) : 0) : 0;
  const rotHour = parseInt(document.getElementById("profileRotationHour").value, 10) || 3;
  const hidePhys = document.getElementById("profileHidePhysical").checked;

  const prof = currentProfiles[id];
  const defaultPlaybackMode = document.getElementById("profileDefaultPlaybackMode") ? document.getElementById("profileDefaultPlaybackMode").value : "streaming";
  const offlineRetentionLimit = document.getElementById("profileOfflineRetentionLimit") ? (parseInt(document.getElementById("profileOfflineRetentionLimit").value, 10) || 8) : 8;
  const primaryCardId = document.getElementById("profilePrimaryCardId") ? document.getElementById("profilePrimaryCardId").value.trim() : "";

  const payload = {
    display_name: name,
    abs_username: absUsername,
    abs_api_key: absApiKey,
    abs_tag: absTag,
    default_player_id: defPlayer,
    player_ids: selectedPlayers,
    avatar_url: avatarUrlHidden,
    avatar_color: avatarColorHidden,
    avatar_initial: avatarInitialInput,
    hide_physical: hidePhys,
    catalog_rotation_limit: rotLimit,
    kiosk_catalog_limit: kioskLimit,
    catalog_rotation_hour: rotHour,
    default_playback_mode: defaultPlaybackMode,
    offline_retention_limit: offlineRetentionLimit,
    primary_card_id: primaryCardId,
    yoto: prof ? prof.yoto : { inherit_shared: true, allowed_card_ids: [], excluded_card_ids: [], match_titles: [] }
  };

  try {
    const res = await fetch(`/api/admin/profiles/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      showToast("Failed to save profile.", "danger");
      return;
    }

    // If a new avatar file was selected, upload it now
    if (pendingAvatarFile) {
      const formData = new FormData();
      formData.append("avatar", pendingAvatarFile);
      const avatarRes = await fetch(`/api/admin/profiles/${id}/avatar`, {
        method: "POST",
        body: formData
      });
      const avatarData = await avatarRes.json();
      if (!avatarRes.ok || !avatarData.ok) {
        showToast(avatarData.error || "Profile saved, but avatar upload failed.", "warning");
      }
    } else if (avatarUrlHidden && avatarUrlHidden.startsWith("http")) {
      // If a remote URL was provided, trigger server-side optimization
      await fetch(`/api/admin/profiles/${id}/avatar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avatar_url: avatarUrlHidden })
      });
    }

    showToast(`Profile '${name}' saved successfully.`, "success");
    closeProfileModal();
    loadProfiles();
    loadMatrix();
  } catch (err) {
    showToast("Network error saving profile.", "danger");
  }
}

function editProfile(id) {
  openProfileModal(id);
}

function deleteProfile(id) {
  if (!confirm(`Are you sure you want to delete profile '${id}'?`)) return;
  fetch(`/api/admin/profiles/${id}`, { method: "DELETE" })
    .then(res => res.json())
    .then(data => {
      showToast("Profile deleted.");
      loadProfiles();
      loadMatrix();
    });
}

async function forceProfileRotationRefresh(profileId) {
  const editInput = document.getElementById("profileEditId");
  const editId = (profileId || (editInput ? editInput.value : "")).trim();
  const profileName = (editId && currentProfiles[editId]) ? currentProfiles[editId].display_name : editId;
  try {
    const url = editId ? `/api/admin/catalog/refresh/${encodeURIComponent(editId)}` : "/api/admin/catalog/refresh";
    const res = await fetch(url, { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      showToast(`Refreshed catalog rotation for ${profileName || 'profile'}! (${data.count} items processed)`, "success");
    } else {
      showToast("Refresh failed: " + (data.error || "Unknown"), "error");
    }
  } catch (err) {
    showToast("Error triggering refresh: " + err.message, "error");
  }
}

