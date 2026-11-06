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
      <div style="margin-top: auto; display: flex; gap: 8px;">
        <button class="btn btn-secondary btn-sm" onclick="editProfile('${escapeHtml(p.id)}')">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteProfile('${escapeHtml(p.id)}')">Delete</button>
      </div>
    `;
    grid.appendChild(card);
  });
}

let discoveredHouseholdMatches = [];
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

function computeHouseholdMonograms(profiles) {
  const byLetter = {};
  const profs = profiles || currentProfiles;
  Object.keys(profs).forEach(pid => {
    const p = profs[pid];
    const name = (p.display_name || pid).trim();
    const firstChar = (name[0] || "C").toUpperCase();
    if (!byLetter[firstChar]) byLetter[firstChar] = [];
    byLetter[firstChar].push({ id: pid, name, customInitial: p.avatar_initial });
  });

  const monograms = {};
  Object.keys(byLetter).forEach(letter => {
    const list = byLetter[letter];
    if (list.length === 1) {
      monograms[list[0].id] = list[0].customInitial || letter;
    } else {
      // Disambiguate when starting letter collides!
      const used = new Set();
      // 1. Multi-word pass (e.g. "Jack B" -> "JB")
      list.forEach(item => {
        if (item.customInitial) {
          monograms[item.id] = item.customInitial;
          used.add(item.customInitial);
          return;
        }
        const words = item.name.split(/\s+/);
        if (words.length >= 2 && words[0] && words[1]) {
          const mono = (words[0][0] + words[1][0]).toUpperCase();
          monograms[item.id] = mono;
          used.add(mono);
        }
      });

      // 2. Single-word distinctive pass
      list.forEach(item => {
        if (monograms[item.id]) return;
        const clean = item.name.replace(/[^a-zA-Z0-9]/g, "");
        if (clean.length >= 2) {
          const cand = clean.substring(0, 2);
          if (!used.has(cand)) {
            monograms[item.id] = cand;
            used.add(cand);
          } else if (clean.length >= 3) {
            const cand2 = clean[0] + clean[2];
            monograms[item.id] = cand2;
            used.add(cand2);
          } else {
            monograms[item.id] = cand;
          }
        } else {
          monograms[item.id] = letter;
        }
      });
    }
  });
  return monograms;
}

function getAvatarColor(nameOrId, customColor = "") {
  if (customColor && customColor.startsWith("#")) return customColor;
  const str = (nameOrId || "Child").trim().toLowerCase();
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) & 0xFFFFFFFF;
  }
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
}

function createInitialAvatarElement(initial, bgColor, size = 44) {
  const div = document.createElement("div");
  div.style.width = `${size}px`;
  div.style.height = `${size}px`;
  div.style.borderRadius = "50%";
  div.style.background = bgColor;
  div.style.color = "#ffffff";
  div.style.display = "flex";
  div.style.alignItems = "center";
  div.style.justifyContent = "center";
  div.style.fontSize = `${Math.round(size * (initial && initial.length > 1 ? 0.38 : 0.45))}px`;
  div.style.fontWeight = "700";
  div.style.flexShrink = "0";
  div.style.boxShadow = "0 2px 8px rgba(0,0,0,0.25)";
  div.innerText = initial || "C";
  return div;
}

let pendingAvatarFile = null;

function renderColorSwatches(activeColor) {
  const container = document.getElementById("avatarColorSwatches");
  if (!container) return;
  container.innerHTML = "";
  AVATAR_PALETTE.forEach(c => {
    const swatch = document.createElement("button");
    swatch.type = "button";
    swatch.className = "color-swatch-btn";
    swatch.style.width = "22px";
    swatch.style.height = "22px";
    swatch.style.borderRadius = "50%";
    swatch.style.background = c;
    swatch.style.border = (activeColor && activeColor.toLowerCase() === c.toLowerCase()) ? "2px solid #ffffff" : "2px solid rgba(0,0,0,0.3)";
    swatch.style.cursor = "pointer";
    swatch.style.padding = "0";
    swatch.style.boxShadow = (activeColor && activeColor.toLowerCase() === c.toLowerCase()) ? "0 0 0 2px var(--accent-info)" : "none";
    swatch.onclick = () => selectAvatarColor(c);
    container.appendChild(swatch);
  });
}

function selectAvatarColor(colorHex) {
  document.getElementById("profileAvatarColorHidden").value = colorHex;
  renderColorSwatches(colorHex);
  updateAvatarPreview(document.getElementById("profileAvatarUrlHidden").value);
}

function onCustomInitialInput(val) {
  updateAvatarPreview(document.getElementById("profileAvatarUrlHidden").value);
}

function updateAvatarPreview(url, fallbackName = "") {
  const img = document.getElementById("profileAvatarPreview");
  const placeholder = document.getElementById("profileAvatarPlaceholder");
  const wrapper = document.getElementById("profileAvatarPreviewWrapper");
  const removeBtn = document.getElementById("btnRemoveAvatar");
  const hiddenInput = document.getElementById("profileAvatarUrlHidden");
  const colorInput = document.getElementById("profileAvatarColorHidden");
  const initialInput = document.getElementById("profileAvatarInitialInput");
  const customizer = document.getElementById("avatarFallbackCustomizer");

  const name = fallbackName || document.getElementById("profileDisplayName").value || document.getElementById("profileIdField").value || "Child";
  const customColor = colorInput ? colorInput.value : "";
  const customInitial = initialInput ? initialInput.value.trim() : "";

  // Compute monogram
  let monogram = customInitial;
  if (!monogram) {
    const monos = computeHouseholdMonograms();
    const pid = document.getElementById("profileIdField").value || fallbackName;
    monogram = monos[pid] || (name.trim().charAt(0) || "C").toUpperCase();
  }

  const color = getAvatarColor(name, customColor);

  if (url) {
    img.src = url;
    img.style.display = "block";
    placeholder.style.display = "none";
    if (wrapper) wrapper.style.background = "var(--bg-surface-elevated)";
    removeBtn.style.display = "inline-block";
    hiddenInput.value = url;
    if (customizer) customizer.style.display = "none";
  } else {
    img.src = "";
    img.style.display = "none";
    placeholder.style.display = "flex";
    placeholder.innerText = monogram;
    placeholder.style.width = "100%";
    placeholder.style.height = "100%";
    placeholder.style.alignItems = "center";
    placeholder.style.justifyContent = "center";
    placeholder.style.fontSize = monogram.length > 1 ? "22px" : "28px";
    placeholder.style.fontWeight = "bold";
    placeholder.style.color = "#ffffff";
    if (wrapper) {
      wrapper.style.background = color;
      wrapper.style.border = `2px solid ${color}`;
    }
    removeBtn.style.display = "none";
    hiddenInput.value = "";
    if (customizer) customizer.style.display = "block";
  }
}

function handleAvatarFileSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  pendingAvatarFile = file;

  const reader = new FileReader();
  reader.onload = (event) => {
    updateAvatarPreview(event.target.result);
  };
  reader.readAsDataURL(file);
}

function toggleAvatarUrlInput() {
  const input = document.getElementById("profileAvatarUrlInput");
  if (input.style.display === "none") {
    input.style.display = "block";
    input.focus();
  } else {
    input.style.display = "none";
  }
}

function handleAvatarUrlInput(url) {
  pendingAvatarFile = null;
  updateAvatarPreview(url.trim());
}

function removeProfileAvatar() {
  pendingAvatarFile = null;
  document.getElementById("profileAvatarFileInput").value = "";
  document.getElementById("profileAvatarUrlInput").value = "";
  updateAvatarPreview("");
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
  const rotLimitInput = document.getElementById("profileRotationLimit");
  const rotHourInput = document.getElementById("profileRotationHour");
  const hidePhysCheck = document.getElementById("profileHidePhysical");
  if (rotLimitInput) rotLimitInput.value = (prof && prof.catalog_rotation_limit) ? prof.catalog_rotation_limit : 80;
  if (rotHourInput) rotHourInput.value = (prof && prof.catalog_rotation_hour !== undefined) ? prof.catalog_rotation_hour : 3;
  if (hidePhysCheck) hidePhysCheck.checked = !!(prof && prof.hide_physical);
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
    addlList.innerHTML = `<span class="text-secondary" style="font-size: 12px;">No Yoto players discovered yet. Connect your Streaming Bridge or Cloud to select devices.</span>`;
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

  const rotLimit = parseInt(document.getElementById("profileRotationLimit").value, 10) || 80;
  const rotHour = parseInt(document.getElementById("profileRotationHour").value, 10) || 3;
  const hidePhys = document.getElementById("profileHidePhysical").checked;

  const prof = currentProfiles[id];
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
    catalog_rotation_hour: rotHour,
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

// ----------------------------------------------------------------------------
// Household Auto-Discovery Handlers
// ----------------------------------------------------------------------------

async function runHouseholdAutoDiscovery() {
  const modal = document.getElementById("discoveryModal");
  const loading = document.getElementById("discoveryLoading");
  const results = document.getElementById("discoveryResults");
  const tbody = document.getElementById("discoveryTableBody");

  modal.style.display = "flex";
  loading.style.display = "block";
  results.style.display = "none";
  tbody.innerHTML = "";

  try {
    const res = await fetch("/api/admin/discovery/household-match");
    if (!res.ok) {
      throw new Error(`Discovery probe failed with status ${res.status}`);
    }
    const data = await res.json();
    discoveredHouseholdMatches = data.matches || [];

    loading.style.display = "none";
    results.style.display = "block";

    if (discoveredHouseholdMatches.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">No matching Yoto players or Audiobookshelf users discovered. Check Streaming Bridge or Audiobookshelf server connection.</td></tr>`;
      return;
    }

    discoveredHouseholdMatches.forEach((m, idx) => {
      const tr = document.createElement("tr");
      const playerInfo = m.matched_yoto_player ? `${escapeHtml(m.matched_yoto_player.name)} <code style="font-size: 11px;">(${escapeHtml(m.matched_yoto_player.id)})</code>` : "None";
      const absInfo = m.matched_abs_user ? `<code>${escapeHtml(m.matched_abs_user.username)}</code>` : "<span class='text-secondary'>Unmatched</span>";
      const confBadge = m.confidence >= 0.8
        ? `<span class="badge badge-success">High (${Math.round(m.confidence * 100)}%)</span>`
        : `<span class="badge badge-warning">Partial (${Math.round(m.confidence * 100)}%)</span>`;
      const alreadyBadge = m.already_exists ? ` <span class="badge badge-subtle">Exists</span>` : "";

      tr.innerHTML = `
        <td><input type="checkbox" class="discovery-select" data-idx="${idx}" ${m.already_exists ? "" : "checked"}></td>
        <td><strong>${escapeHtml(m.display_name)}</strong> <span class="text-secondary">(${escapeHtml(m.suggested_profile_id)})</span>${alreadyBadge}</td>
        <td>${playerInfo}</td>
        <td>${absInfo}</td>
        <td>${confBadge}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    loading.innerHTML = `<p style="color: var(--accent-danger);">Discovery failed: ${escapeHtml(err.message)}</p><button class="btn btn-secondary btn-sm" onclick="closeDiscoveryModal()">Close</button>`;
  }
}

function closeDiscoveryModal() {
  document.getElementById("discoveryModal").style.display = "none";
}

function toggleSelectAllDiscovery(checked) {
  document.querySelectorAll(".discovery-select").forEach(cb => cb.checked = checked);
}

async function confirmImportDiscovery() {
  const selectedIndices = [];
  document.querySelectorAll(".discovery-select:checked").forEach(cb => {
    selectedIndices.push(parseInt(cb.getAttribute("data-idx")));
  });

  if (selectedIndices.length === 0) {
    showToast("No profiles selected for import.", "info");
    return;
  }

  const profilesToImport = selectedIndices.map(idx => {
    const m = discoveredHouseholdMatches[idx];
    const pid = m.suggested_profile_id;
    const absUser = m.matched_abs_user ? m.matched_abs_user.username : "";
    const playerId = m.matched_yoto_player ? m.matched_yoto_player.id : "";
    return {
      id: pid,
      display_name: m.display_name,
      abs_username: absUser,
      abs_api_key: "",
      abs_tag: absUser || pid,
      default_player_id: playerId,
      player_ids: playerId ? [playerId] : []
    };
  });

  try {
    const res = await fetch("/api/admin/discovery/auto-import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profiles: profilesToImport })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Successfully provisioned ${data.imported_count} profile(s)!`, "success");
      closeDiscoveryModal();
      loadProfiles();
      loadMatrix();
    } else {
      showToast(data.error || "Failed to import profiles.", "danger");
    }
  } catch (err) {
    showToast("Network error importing profiles.", "danger");
  }
}

async function forceProfileRotationRefresh() {
  const editId = document.getElementById("profileEditId").value.trim();
  try {
    const url = editId ? `/api/admin/catalog/refresh/${encodeURIComponent(editId)}` : "/api/admin/catalog/refresh";
    const res = await fetch(url, { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      showToast(`Refreshed catalog rotation! (${data.count} items processed)`, "success");
    } else {
      showToast("Refresh failed: " + (data.error || "Unknown"), "error");
    }
  } catch (err) {
    showToast("Error triggering refresh: " + err.message, "error");
  }
}

