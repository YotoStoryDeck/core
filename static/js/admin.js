/* ==============================================================================
   YOTO & AUDIOBOOKSHELF CONTROLLER ADMIN PORTAL (ES6 SPA CLIENT)
   Handles auth lifecycle, profile CRUD, curation matrix, hardware, diagnostics.
   ============================================================================== */

let currentUser = null;
let currentProfiles = {};
let currentMatrix = { items: [], profiles: [], shared_rules: {} };
let currentDevices = [];
let cachedAbsServerTags = [];
let configuredDefaultChildTags = ["Children"];
let selectedMatrixItemIds = new Set();
let lastCheckedMatrixIndex = -1;

const AVATAR_PALETTE = [
  "#3b82f6",  // Blue
  "#ef4444",  // Red
  "#10b981",  // Emerald
  "#f59e0b",  // Amber
  "#8b5cf6",  // Purple
  "#ec4899",  // Pink
  "#06b6d4",  // Cyan
  "#f97316",  // Orange
  "#14b8a6",  // Teal
  "#6366f1"   // Indigo
];

// Lifecycle Boot
document.addEventListener("DOMContentLoaded", () => {
  checkAuthStatus();
});

// Toast notification helper
function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.3s";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// ============================================================================
// Auth & Setup Lifecycle
// ============================================================================

async function checkAuthStatus() {
  try {
    const res = await fetch("/api/admin/auth/status");
    const data = await res.json();

    if (data.setup_required) {
      document.getElementById("setupModal").style.display = "flex";
      document.getElementById("loginModal").style.display = "none";
      document.getElementById("mainApp").style.display = "none";
      document.getElementById("headerUserSection").style.display = "none";
    } else if (!data.authenticated) {
      document.getElementById("setupModal").style.display = "none";
      document.getElementById("loginModal").style.display = "flex";
      document.getElementById("mainApp").style.display = "none";
      document.getElementById("headerUserSection").style.display = "none";
    } else {
      currentUser = data.user;
      document.getElementById("setupModal").style.display = "none";
      document.getElementById("loginModal").style.display = "none";
      document.getElementById("mainApp").style.display = "block";
      document.getElementById("headerUserSection").style.display = "flex";
      document.getElementById("userGreeting").innerText = `Welcome, ${currentUser.display_name || currentUser.username}`;
      loadInitialData();
    }
  } catch (err) {
    console.error("Auth check failed:", err);
    showToast("Failed to verify authentication status.", "danger");
  }
}

async function handleInitialSetup(e) {
  e.preventDefault();
  const username = document.getElementById("setupUsername").value.trim();
  const displayName = document.getElementById("setupDisplayName").value.trim() || "Parent";
  const password = document.getElementById("setupPassword").value;

  try {
    const res = await fetch("/api/admin/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, display_name: displayName, password })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Primary administrator account created successfully!", "success");
      // Proceed to login
      await handleAutoLogin(username, password);
    } else {
      showToast(data.error || "Setup failed.", "danger");
    }
  } catch (err) {
    showToast("Network error during setup.", "danger");
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  await handleAutoLogin(username, password);
}

async function handleAutoLogin(username, password) {
  try {
    const res = await fetch("/api/admin/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Signed in successfully.", "success");
      checkAuthStatus();
    } else {
      showToast(data.error || "Invalid username or password.", "danger");
    }
  } catch (err) {
    showToast("Sign in failed. Check connection.", "danger");
  }
}

async function logout() {
  try {
    await fetch("/api/admin/auth/logout", { method: "POST" });
    showToast("Signed out.");
    checkAuthStatus();
  } catch (err) {
    location.reload();
  }
}

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
  if (tabId === "settings") loadApiCredentials();
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
}

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

// ============================================================================
// Curation Matrix (Tab 2)
// ============================================================================

async function loadMatrix() {
  try {
    const res = await fetch("/api/admin/catalog/matrix");
    if (!res.ok) return;
    currentMatrix = await res.json();

    // Populate shared checkboxes
    document.getElementById("sharedIncludeAll").checked = !!(currentMatrix.shared_rules && currentMatrix.shared_rules.include_all);
    document.getElementById("sharedIncludeMyo").checked = !!(currentMatrix.shared_rules && currentMatrix.shared_rules.include_myo_by_default);

    // Populate profile filter options
    populateCurationProfileOptions();

    renderMatrixTable();
  } catch (err) {
    console.error("Error loading matrix:", err);
  }
}

function populateCurationProfileOptions() {
  const select = document.getElementById("curationProfileFilter");
  if (!select) return;
  const currentVal = select.value;
  select.innerHTML = '<option value="all">Household (All Profiles)</option>';

  if (currentMatrix.profiles && currentMatrix.profiles.length > 0) {
    currentMatrix.profiles.forEach(pKey => {
      const p = currentProfiles[pKey] || { display_name: pKey };
      const opt = document.createElement("option");
      opt.value = pKey;
      opt.textContent = `👶 ${p.display_name || pKey}`;
      select.appendChild(opt);
    });
  }
  if (currentVal && Array.from(select.options).some(o => o.value === currentVal)) {
    select.value = currentVal;
  }
  onCurationProfileFilterChange();
}

function onCurationProfileFilterChange() {
  const profileFilterEl = document.getElementById("curationProfileFilter");
  const showAllWrapper = document.getElementById("curationShowAllWrapper");
  const selectedProfile = profileFilterEl ? profileFilterEl.value : "all";

  if (selectedProfile === "all") {
    if (showAllWrapper) showAllWrapper.style.display = "none";
  } else {
    if (showAllWrapper) showAllWrapper.style.display = "flex";
  }
  filterMatrix();
}

function renderMatrixTable() {
  const tbody = document.getElementById("matrixTableBody");
  tbody.innerHTML = "";

  if (!currentMatrix.items || currentMatrix.items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 24px;">No cards discovered yet. Click 'Refresh Catalogs' to pull from Yoto & Audiobookshelf.</td></tr>`;
    return;
  }

  // Populate dynamic series dropdown from unique series across items
  populateSeriesFilterDropdown();

  currentMatrix.items.forEach(item => {
    const tr = document.createElement("tr");
    // Parse series list (support multi-series like "Star Wars #55, Star Wars Classic Stories #7")
    const seriesList = [];
    if (Array.isArray(item.series_list) && item.series_list.length > 0) {
      item.series_list.forEach(s => {
        const clean = normalizeSeriesEntry(s.name, s.order);
        if (clean) seriesList.push(clean);
      });
    } else if (item.series) {
      const parts = String(item.series).split(",");
      if (parts.length > 1) {
        parts.forEach(p => {
          const clean = normalizeSeriesEntry(p);
          if (clean) seriesList.push(clean);
        });
      } else {
        const clean = normalizeSeriesEntry(item.series, item.series_order);
        if (clean) seriesList.push(clean);
      }
    }

    const allSeriesNames = seriesList.map(s => s.name.toLowerCase());
    const seriesText = seriesList.map(s => ` ${s.name} ${s.order}`).join(" ");

    tr.dataset.itemId = item.id;
    tr.dataset.title = (item.title + " " + (item.author || "") + seriesText).toLowerCase();
    tr.dataset.type = item.type || "abs";
    tr.dataset.series = JSON.stringify(allSeriesNames);
    tr.dataset.profiles = JSON.stringify(item.profiles || {});

    const isSelected = selectedMatrixItemIds.has(item.id);
    if (isSelected) {
      tr.classList.add("row-selected");
    }

    // Checkbox Column (Feature 011)
    const checkTd = document.createElement("td");
    checkTd.style.textAlign = "center";
    checkTd.style.verticalAlign = "middle";
    checkTd.innerHTML = `
      <input type="checkbox" class="bulk-checkbox matrix-row-checkbox" data-id="${escapeHtml(item.id)}" ${isSelected ? "checked" : ""} onchange="onMatrixRowCheckboxChange(event, '${escapeHtml(item.id)}')">
    `;
    tr.appendChild(checkTd);

    // Cover (Clickable to open Tracklist)
    const coverTd = document.createElement("td");
    const thumbUrl = item.cover_url || `/api/thumb?type=${item.type}&id=${item.id}&size=100`;
    coverTd.style.cursor = "pointer";
    coverTd.title = "Click to inspect tracklist & chapters";
    coverTd.onclick = () => openTracklistModal(item.id);
    coverTd.innerHTML = `<img src="${thumbUrl}" class="cover-thumb-sm" onerror="this.onerror=null; this.src='/static/img/placeholder.png';" alt="cover">`;
    tr.appendChild(coverTd);

    // Title / Author / Multi-Series Badges (Title Clickable to open Tracklist)
    const titleTd = document.createElement("td");
    let seriesBadgesHtml = "";
    if (seriesList.length > 0) {
      seriesBadgesHtml = '<div style="margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px;">';
      seriesList.forEach(s => {
        const orderText = s.order ? ` #${s.order}` : "";
        seriesBadgesHtml += `<span class="badge" style="font-size: 11px; padding: 2px 6px; background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.35);">📚 ${escapeHtml(s.name)}${escapeHtml(orderText)}</span>`;
      });
      seriesBadgesHtml += '</div>';
    }
    titleTd.innerHTML = `
      <div style="cursor: pointer;" title="Click to inspect tracklist & chapters" onclick="openTracklistModal('${escapeHtml(item.id)}')">
        <strong style="color: var(--text-primary); transition: color 0.15s;" onmouseover="this.style.color='var(--accent-yoto)'" onmouseout="this.style.color='var(--text-primary)'">${escapeHtml(item.title)}</strong>
      </div>
      <div class="text-secondary" style="font-size: 12px;">${escapeHtml(item.author || "Unknown")}</div>
      ${seriesBadgesHtml}
    `;
    tr.appendChild(titleTd);

    // Type Badge
    const typeTd = document.createElement("td");
    let badgeClass = "badge-warning";
    let typeLabel = "Audiobookshelf";
    if (item.type === "yoto_myo") {
      badgeClass = "badge-info";
      typeLabel = "MYO";
    } else if (item.type === "yoto") {
      badgeClass = "badge-success";
      typeLabel = "YOTO";
    } else if (item.type === "abs") {
      badgeClass = "badge-warning";
      typeLabel = "Audiobookshelf";
    }
    typeTd.innerHTML = `<span class="badge ${badgeClass}">${typeLabel}</span>`;
    tr.appendChild(typeTd);

    // Highlight Toggle
    const hiTd = document.createElement("td");
    hiTd.style.textAlign = "center";
    hiTd.innerHTML = `
      <label class="toggle-control" style="margin: 0 auto;">
        <input type="checkbox" ${item.is_highlight ? "checked" : ""} onchange="toggleItemHighlight('${escapeHtml(item.id)}', this.checked)">
        <span class="toggle-slider"></span>
      </label>
    `;
    tr.appendChild(hiTd);

    // Profile Access & Permissions Column
    const accessTd = document.createElement("td");
    accessTd.style.verticalAlign = "middle";

    let pillsHtml = "";
    const activeProfiles = currentMatrix.profiles || [];
    activeProfiles.forEach(pKey => {
      const pState = (item.profiles && item.profiles[pKey]) ? item.profiles[pKey] : { allowed: false, reason: "none" };
      const p = currentProfiles[pKey] || { display_name: pKey };
      const isAllowed = pState.allowed;
      const isAbsPermitted = pState.reason === "abs_account_permitted" || pState.reason === "abs_tag_match";
      
      let badgeStyle = "background: rgba(255,255,255,0.06); color: var(--text-muted); border: 1px solid var(--border-subtle);";
      let statusIcon = "⚪";
      if (isAllowed) {
        if (isAbsPermitted) {
          badgeStyle = "background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);";
          statusIcon = "🟢";
        } else {
          badgeStyle = "background: rgba(59, 130, 246, 0.15); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.4);";
          statusIcon = "🔵";
        }
      }

      pillsHtml += `<span class="badge" style="font-size: 11px; padding: 2px 7px; ${badgeStyle}" title="${escapeHtml(pState.reason || '')}">${statusIcon} ${escapeHtml(p.display_name || pKey)}</span> `;
    });

    accessTd.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
        <div style="display: flex; flex-wrap: wrap; gap: 4px; align-items: center;">
          ${pillsHtml || '<span class="text-secondary" style="font-size: 11px;">No access</span>'}
        </div>
        <div style="display: flex; gap: 4px; flex-shrink: 0;">
          <button class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 4px 8px;" onclick="openTracklistModal('${escapeHtml(item.id)}')">
            🎵 Tracks
          </button>
          <button class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 4px 8px;" onclick="openCurationPermissionsModal('${escapeHtml(item.id)}')">
            ⚙️ Permissions
          </button>
        </div>
      </div>
    `;
    tr.appendChild(accessTd);

    tbody.appendChild(tr);
  });

  filterMatrix();
  updateBulkActionBar();
}

function normalizeSeriesEntry(rawName, rawOrder = "") {
  let name = (rawName || "").trim();
  let order = String(rawOrder || "").trim();
  if (!name) return null;

  const matchSeq = name.match(/\s*#\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$/);
  if (matchSeq) {
    if (!order) order = matchSeq[1].replace(/\s+/g, "");
    name = name.slice(0, matchSeq.index).trim();
  } else {
    const matchBook = name.match(/[,:\s]+(?:Books?|Volumes?|Vol\.?|Parts?)\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–—,&]\s*[0-9]+(?:\.[0-9]+)?)*)$/i);
    if (matchBook) {
      if (!order) order = matchBook[1].replace(/\s+/g, "");
      name = name.slice(0, matchBook.index).trim();
    }
  }

  return name ? { name, order } : null;
}

function populateSeriesFilterDropdown() {
  const select = document.getElementById("curationSeriesFilter");
  if (!select) return;

  const currentVal = select.value;
  select.innerHTML = '<option value="all">All Series / Groups</option>';

  const seriesSet = new Set();
  (currentMatrix.items || []).forEach(it => {
    if (Array.isArray(it.series_list) && it.series_list.length > 0) {
      it.series_list.forEach(s => {
        const clean = normalizeSeriesEntry(s.name, s.order);
        if (clean && clean.name) seriesSet.add(clean.name);
      });
    } else if (it.series) {
      const parts = String(it.series).split(",");
      if (parts.length > 1) {
        parts.forEach(p => {
          const clean = normalizeSeriesEntry(p);
          if (clean && clean.name) seriesSet.add(clean.name);
        });
      } else {
        const clean = normalizeSeriesEntry(it.series, it.series_order);
        if (clean && clean.name) seriesSet.add(clean.name);
      }
    }
  });

  const sortedSeries = Array.from(seriesSet).sort((a, b) => a.localeCompare(b));
  sortedSeries.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s.toLowerCase();
    opt.textContent = `📚 ${s}`;
    select.appendChild(opt);
  });

  if (currentVal && Array.from(select.options).some(o => o.value === currentVal)) {
    select.value = currentVal;
  }
}

function filterMatrix() {
  const query = document.getElementById("matrixSearch").value.toLowerCase().trim();
  const typeFilterEl = document.getElementById("curationTypeFilter");
  const selectedType = typeFilterEl ? typeFilterEl.value : "all";

  const seriesFilterEl = document.getElementById("curationSeriesFilter");
  const selectedSeries = seriesFilterEl ? seriesFilterEl.value : "all";

  const profileFilterEl = document.getElementById("curationProfileFilter");
  const selectedProfile = profileFilterEl ? profileFilterEl.value : "all";

  const showAllEl = document.getElementById("curationShowAll");
  const showAll = showAllEl ? showAllEl.checked : false;

  const rows = document.querySelectorAll("#matrixTableBody tr");

  rows.forEach(r => {
    const matchesSearch = !query || (r.dataset.title && r.dataset.title.includes(query));
    const rowType = r.dataset.type || "abs";
    const matchesType = (selectedType === "all") || (rowType === selectedType);

    // Multi-series check
    let matchesSeries = true;
    if (selectedSeries !== "all") {
      let seriesNames = [];
      try {
        seriesNames = JSON.parse(r.dataset.series || "[]");
      } catch (e) {
        seriesNames = [r.dataset.series || ""];
      }
      matchesSeries = seriesNames.includes(selectedSeries);
    }

    // Profile eligibility check
    let matchesProfile = true;
    if (selectedProfile !== "all") {
      let profilesData = {};
      try {
        profilesData = JSON.parse(r.dataset.profiles || "{}");
      } catch (e) {
        profilesData = {};
      }
      const pState = profilesData[selectedProfile] || { allowed: false };
      const isEligible = !!pState.allowed;

      // If slider is NOT checked, only show eligible items. If checked, show all regardless of eligibility.
      if (!showAll && !isEligible) {
        matchesProfile = false;
      }
    }

    if (matchesSearch && matchesType && matchesSeries && matchesProfile) {
      r.style.display = "";
    } else {
      r.style.display = "none";
    }
  });

  syncSelectAllCheckboxState();
}

// ============================================================================
// Multi-Card Mass Edit & Bulk Selection (Feature 011)
// ============================================================================

function onMatrixRowCheckboxChange(event, itemId) {
  const checkbox = event.target;
  const isChecked = checkbox.checked;
  const rows = Array.from(document.querySelectorAll("#matrixTableBody tr")).filter(r => r.style.display !== "none");
  const currentIndex = rows.findIndex(r => r.dataset.itemId === itemId);

  // Shift-click range selection
  if (event.shiftKey && lastCheckedMatrixIndex !== -1 && currentIndex !== -1) {
    const start = Math.min(lastCheckedMatrixIndex, currentIndex);
    const end = Math.max(lastCheckedMatrixIndex, currentIndex);

    for (let i = start; i <= end; i++) {
      const r = rows[i];
      const rId = r.dataset.itemId;
      const cb = r.querySelector(".matrix-row-checkbox");
      if (cb) {
        cb.checked = isChecked;
      }
      if (isChecked) {
        selectedMatrixItemIds.add(rId);
        r.classList.add("row-selected");
      } else {
        selectedMatrixItemIds.delete(rId);
        r.classList.remove("row-selected");
      }
    }
  } else {
    if (isChecked) {
      selectedMatrixItemIds.add(itemId);
      const tr = checkbox.closest("tr");
      if (tr) tr.classList.add("row-selected");
    } else {
      selectedMatrixItemIds.delete(itemId);
      const tr = checkbox.closest("tr");
      if (tr) tr.classList.remove("row-selected");
    }
    lastCheckedMatrixIndex = currentIndex;
  }

  syncSelectAllCheckboxState();
  updateBulkActionBar();
}

function toggleSelectAllMatrix(checked) {
  const visibleRows = Array.from(document.querySelectorAll("#matrixTableBody tr")).filter(r => r.style.display !== "none");
  visibleRows.forEach(r => {
    const rId = r.dataset.itemId;
    const cb = r.querySelector(".matrix-row-checkbox");
    if (cb) cb.checked = checked;
    if (checked) {
      if (rId) selectedMatrixItemIds.add(rId);
      r.classList.add("row-selected");
    } else {
      if (rId) selectedMatrixItemIds.delete(rId);
      r.classList.remove("row-selected");
    }
  });

  updateBulkActionBar();
}

function syncSelectAllCheckboxState() {
  const selectAllCb = document.getElementById("matrixSelectAll");
  if (!selectAllCb) return;

  const visibleRows = Array.from(document.querySelectorAll("#matrixTableBody tr")).filter(r => r.style.display !== "none");
  if (visibleRows.length === 0) {
    selectAllCb.checked = false;
    selectAllCb.indeterminate = false;
    return;
  }

  const selectedCount = visibleRows.filter(r => selectedMatrixItemIds.has(r.dataset.itemId)).length;
  if (selectedCount === 0) {
    selectAllCb.checked = false;
    selectAllCb.indeterminate = false;
  } else if (selectedCount === visibleRows.length) {
    selectAllCb.checked = true;
    selectAllCb.indeterminate = false;
  } else {
    selectAllCb.checked = false;
    selectAllCb.indeterminate = true;
  }
}

function updateBulkActionBar() {
  const bar = document.getElementById("curationBulkBar");
  const countEl = document.getElementById("bulkSelectedCount");
  if (!bar || !countEl) return;

  const count = selectedMatrixItemIds.size;
  countEl.innerText = count;

  if (count > 0) {
    bar.classList.add("active");
  } else {
    bar.classList.remove("active");
  }
}

function clearMatrixSelection() {
  selectedMatrixItemIds.clear();
  lastCheckedMatrixIndex = -1;

  document.querySelectorAll(".matrix-row-checkbox").forEach(cb => {
    cb.checked = false;
  });
  document.querySelectorAll("#matrixTableBody tr").forEach(tr => {
    tr.classList.remove("row-selected");
  });

  const selectAllCb = document.getElementById("matrixSelectAll");
  if (selectAllCb) {
    selectAllCb.checked = false;
    selectAllCb.indeterminate = false;
  }

  updateBulkActionBar();
}

async function quickBatchHighlight(isHighlight) {
  if (selectedMatrixItemIds.size === 0) return;
  const ids = Array.from(selectedMatrixItemIds);

  try {
    const res = await fetch("/api/admin/curation/batch-highlight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_ids: ids, is_highlight: isHighlight })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`${isHighlight ? "⭐ Highlighted" : "☆ Removed highlight from"} ${ids.length} card(s)`);
      // Update local memory and DOM without full network refetch
      currentMatrix.items.forEach(it => {
        if (selectedMatrixItemIds.has(it.id)) {
          it.is_highlight = isHighlight;
        }
      });
      renderMatrixTable();
    } else {
      showToast("Failed to update highlights: " + (data.error || "Unknown error"), "error");
    }
  } catch (err) {
    showToast("Network error updating highlights: " + err.message, "error");
  }
}

function openMassEditModal() {
  if (selectedMatrixItemIds.size === 0) return;
  const modal = document.getElementById("curationMassEditModal");
  const count = selectedMatrixItemIds.size;

  document.getElementById("massEditModalSubtitle").innerText =
    `Configure permissions and settings across ${count} selected card(s).`;

  // Compute breakdown by type
  let yotoCount = 0;
  let myoCount = 0;
  let absCount = 0;

  currentMatrix.items.forEach(it => {
    if (selectedMatrixItemIds.has(it.id)) {
      if (it.type === "yoto_myo") myoCount++;
      else if (it.type === "yoto") yotoCount++;
      else absCount++;
    }
  });

  const breakdownEl = document.getElementById("massEditBreakdown");
  breakdownEl.innerHTML = `
    <div style="display: flex; gap: 14px; flex-wrap: wrap; align-items: center; font-size: 13px;">
      <strong>Selected (${count}):</strong>
      ${yotoCount > 0 ? `<span class="badge badge-success">📻 ${yotoCount} Yoto Retail</span>` : ""}
      ${myoCount > 0 ? `<span class="badge badge-info">🎨 ${myoCount} MYO</span>` : ""}
      ${absCount > 0 ? `<span class="badge badge-warning">📚 ${absCount} Audiobookshelf</span>` : ""}
    </div>
  `;

  // Build profile action controls
  const listEl = document.getElementById("massEditProfilesList");
  listEl.innerHTML = "";

  const monograms = computeHouseholdMonograms(currentProfiles);
  const activeProfiles = currentMatrix.profiles || Object.keys(currentProfiles);

  activeProfiles.forEach(pKey => {
    const prof = currentProfiles[pKey] || { display_name: pKey, id: pKey };
    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.justifyContent = "space-between";
    row.style.padding = "8px 12px";
    row.style.background = "var(--bg-base)";
    row.style.border = "1px solid var(--border-subtle)";
    row.style.borderRadius = "6px";

    const monogram = prof.avatar_initial || (monograms && monograms[prof.id]) || (prof.display_name || prof.id || "C").trim().charAt(0).toUpperCase();
    const avatarBg = getAvatarColor(prof.display_name || prof.id, prof.avatar_color);
    const fontSize = monogram.length > 1 ? "11px" : "13px";

    const avatarHtml = (prof.avatar_url && !prof.avatar_url.includes("avatar/placeholder"))
      ? `<img src="${escapeHtml(prof.avatar_url)}" alt="${escapeHtml(prof.display_name || prof.id)}" onerror="this.onerror=null;this.replaceWith(createInitialAvatarElement('${escapeHtml(monogram)}', '${avatarBg}', 28));" style="width: 28px; height: 28px; border-radius: 50%; object-fit: cover; border: 1.5px solid var(--accent-info); flex-shrink: 0;">`
      : `<div style="width: 28px; height: 28px; border-radius: 50%; background: ${avatarBg}; color: #ffffff; display: flex; align-items: center; justify-content: center; font-size: ${fontSize}; font-weight: 700; flex-shrink: 0; box-shadow: 0 1px 4px rgba(0,0,0,0.25);">${escapeHtml(monogram)}</div>`;

    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px;">
        ${avatarHtml}
        <strong style="color: var(--text-primary); font-size: 13px;">${escapeHtml(prof.display_name || pKey)}</strong>
      </div>
      <select class="form-control mass-profile-action-select" data-profile="${escapeHtml(pKey)}" style="width: auto; min-width: 170px; font-size: 12px;">
        <option value="no_change">-- No Change --</option>
        <option value="allow">🟢 Grant Access (Allow)</option>
        <option value="exclude">🔴 Restrict Access (Exclude)</option>
        <option value="reset">⚪ Reset (Household Default)</option>
      </select>
    `;
    listEl.appendChild(row);
  });

  // Reset highlight dropdown
  document.getElementById("massEditHighlightAction").value = "no_change";

  modal.style.display = "flex";
}

function closeMassEditModal() {
  const modal = document.getElementById("curationMassEditModal");
  if (modal) modal.style.display = "none";
}

async function submitMassEditModal() {
  const ids = Array.from(selectedMatrixItemIds);
  if (ids.length === 0) return;

  const profileActions = {};
  document.querySelectorAll(".mass-profile-action-select").forEach(sel => {
    const val = sel.value;
    const prof = sel.dataset.profile;
    if (val && val !== "no_change") {
      profileActions[prof] = val;
    }
  });

  const hiVal = document.getElementById("massEditHighlightAction").value;
  let isHighlight = null;
  if (hiVal === "set_highlight") isHighlight = true;
  else if (hiVal === "clear_highlight") isHighlight = false;

  if (Object.keys(profileActions).length === 0 && isHighlight === null) {
    showToast("No changes were selected.", "info");
    closeMassEditModal();
    return;
  }

  try {
    const res = await fetch("/api/admin/curation/batch-permissions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        media_ids: ids,
        profile_actions: profileActions,
        is_highlight: isHighlight
      })
    });
    let data;
    try {
      data = await res.json();
    } catch (e) {
      data = { ok: false, error: `HTTP ${res.status}: ${res.statusText}` };
    }
    if (res.ok && data.ok) {
      showToast(`Batch update applied across ${ids.length} card(s)`);
      closeMassEditModal();
      clearMatrixSelection();
      // Reload full matrix from server to refresh all profile badges
      await loadMatrix();
    } else {
      console.error("Batch update failed response:", res.status, data);
      showToast("Batch update failed: " + (data.error || `HTTP ${res.status}`), "error");
    }
  } catch (err) {
    console.error("Batch update caught error:", err);
    showToast("Network error during batch update: " + err.message, "error");
  }
}

// ============================================================================
// Tracklist Browser & Chapter Artwork Studio (Feature 012)
// ============================================================================

let currentTracklistMedia = null;
let activePickerTrackIndex = null;

async function openTracklistModal(mediaId) {
  // Always clean up previous modal and drawer state when switching cards
  revertPendingTrackNames(true);
  toggleBatchRenameDrawer(false);
  const inputEl = document.getElementById("batchTrackNamesInput");
  if (inputEl) inputEl.value = "";

  const modal = document.getElementById("curationTracklistModal");
  const coverEl = document.getElementById("tracklistModalCover");
  const titleEl = document.getElementById("tracklistModalTitle");
  const authorEl = document.getElementById("tracklistModalAuthor");
  const typeBadge = document.getElementById("tracklistModalTypeBadge");
  const statsEl = document.getElementById("tracklistModalStats");
  const actionsEl = document.getElementById("tracklistModalActions");
  const tbody = document.getElementById("tracklistTableBody");

  tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 32px; color: var(--text-muted);">Loading tracklist and chapter icons...</td></tr>`;
  modal.style.display = "flex";

  try {
    const res = await fetch(`/api/admin/media/${encodeURIComponent(mediaId)}/tracks?_t=${Date.now()}`);
    const data = await res.json();
    if (!data.ok) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--accent-danger); padding: 24px;">Failed to load tracks: ${escapeHtml(data.error || "Unknown error")}</td></tr>`;
      return;
    }

    currentTracklistMedia = data;

    titleEl.innerText = data.title;
    authorEl.innerText = data.author || "Unknown";
    coverEl.src = data.cover_url || `/api/thumb?type=${data.type}&id=${data.id}&size=100`;

    if (data.type === "yoto_myo") {
      typeBadge.className = "badge badge-info";
      typeBadge.innerText = "MYO Playlist";
    } else if (data.type === "yoto") {
      typeBadge.className = "badge badge-success";
      typeBadge.innerText = "Yoto Retail Card";
    } else {
      typeBadge.className = "badge badge-warning";
      typeBadge.innerText = "Audiobookshelf";
    }

    const count = data.tracks ? data.tracks.length : 0;
    statsEl.innerText = `${count} track${count === 1 ? '' : 's'} • ${data.can_edit ? 'Editable Chapter Artwork' : 'Official Retail Content (Read-Only)'}`;

    // Render header actions
    actionsEl.innerHTML = "";
    if (data.can_edit) {
      actionsEl.innerHTML = `
        <button type="button" class="btn btn-sm btn-secondary" onclick="toggleBatchRenameDrawer()">
          📝 Rename Tracks
        </button>
        <button type="button" class="btn btn-sm btn-primary" onclick="autoMatchCurrentTrackIcons()">
          ⚡ Auto-Match Icons
        </button>
      `;
    } else {
      actionsEl.innerHTML = `
        <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-size: 11px;">
          🔒 Official Retail Artwork
        </span>
      `;
    }

    renderTracklistRows();
  } catch (err) {
    console.error("Error opening tracklist modal:", err);
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--accent-danger); padding: 24px;">Network error loading tracklist: ${escapeHtml(err.message)}</td></tr>`;
  }
}

let originalTracklistBackup = null;
let pendingTracklistNames = null;

function renderTracklistRows() {
  const tbody = document.getElementById("tracklistTableBody");
  tbody.innerHTML = "";

  if (!currentTracklistMedia || !currentTracklistMedia.tracks || currentTracklistMedia.tracks.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 24px;">No tracks found for this title.</td></tr>`;
    return;
  }

  const canEdit = currentTracklistMedia.can_edit;

  currentTracklistMedia.tracks.forEach((tr, idx) => {
    const row = document.createElement("tr");

    // Check if this track has a pending preview title
    const isPending = pendingTracklistNames && pendingTracklistNames[idx] && pendingTracklistNames[idx] !== (originalTracklistBackup ? originalTracklistBackup[idx] : tr.title);
    const displayTitle = isPending ? pendingTracklistNames[idx] : tr.title;

    if (isPending) {
      row.style.background = "rgba(245, 158, 11, 0.08)";
    }

    // Track icon: interactive for ABS / MYO, read-only for Yoto Retail
    const iconUrl = tr.icon_url || "/static/img/placeholder.png";
    const iconClickableStyle = canEdit ? "cursor: pointer; transition: transform 0.15s, border-color 0.15s;" : "";
    const iconTitle = canEdit ? "Click to change icon (Studio Picker)" : "Official Yoto display icon";

    row.innerHTML = `
      <td style="text-align: center; color: var(--text-muted); font-size: 12px; font-weight: 600;">
        ${tr.track_number}
      </td>
      <td style="text-align: center;">
        <img src="${escapeHtml(iconUrl)}" 
             class="cover-thumb-sm" 
             style="width: 36px; height: 36px; border-radius: 6px; object-fit: cover; border: 1px solid var(--border-subtle); image-rendering: pixelated; ${iconClickableStyle}" 
             alt="icon" 
             title="${escapeHtml(iconTitle)}"
             onerror="this.onerror=null; this.src='/static/img/placeholder.png';"
             ${canEdit ? `onclick="openIconPickerForTrack(${tr.index})"` : ''}>
      </td>
      <td>
        <strong style="color: ${isPending ? '#fbbf24' : 'var(--text-primary)'}; font-size: 13px;">${escapeHtml(displayTitle)}</strong>
        ${isPending ? `<span class="badge" style="margin-left: 8px; font-size: 10px; background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4);">Preview</span>` : ''}
        ${isPending && originalTracklistBackup && originalTracklistBackup[idx] ? `<div style="font-size: 11px; color: var(--text-muted); text-decoration: line-through;">${escapeHtml(originalTracklistBackup[idx])}</div>` : ''}
      </td>
      <td style="text-align: right; color: var(--text-secondary); font-size: 12px;">
        ${tr.duration_formatted || "--:--"}
      </td>
      <td style="text-align: center;">
        ${canEdit ? `
          <button type="button" class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 3px 8px;" onclick="openIconPickerForTrack(${tr.index})">
            🎨 Edit Icon
          </button>
        ` : `
          <span style="font-size: 11px; color: var(--text-muted);">Curated</span>
        `}
      </td>
    `;
    tbody.appendChild(row);
  });
}

function closeTracklistModal() {
  const modal = document.getElementById("curationTracklistModal");
  if (modal) modal.style.display = "none";
  revertPendingTrackNames(true);
  toggleBatchRenameDrawer(false);
  const inputEl = document.getElementById("batchTrackNamesInput");
  if (inputEl) inputEl.value = "";
  currentTracklistMedia = null;
}

function parseClientTrackNames(rawInput) {
  if (!rawInput || typeof rawInput !== "string") return [];
  const lines = rawInput.split(/\r?\n/).map(l => l.trim()).filter(l => l.length > 0);
  let rawItems = lines;
  if (lines.length === 1 && lines[0].includes(",") && !lines[0].startsWith("•") && !lines[0].startsWith("-") && !lines[0].startsWith("*")) {
    rawItems = lines[0].split(",").map(i => i.trim()).filter(i => i.length > 0);
  }
  return rawItems.map(item => {
    return item.replace(/^[\s•\-*·]+\s*/, "").trim();
  }).filter(t => t.length > 0);
}

function toggleBatchRenameDrawer(show) {
  const drawer = document.getElementById("tracklistBatchRenameDrawer");
  if (!drawer) return;
  const isCurrentlyOpen = drawer.style.display !== "none";
  const shouldOpen = show !== undefined ? Boolean(show) : !isCurrentlyOpen;
  drawer.style.display = shouldOpen ? "block" : "none";
  if (shouldOpen) {
    const input = document.getElementById("batchTrackNamesInput");
    if (input) {
      // Repopulate with the currently selected book's track titles
      if (currentTracklistMedia && Array.isArray(currentTracklistMedia.tracks)) {
        input.value = currentTracklistMedia.tracks.map(t => `• ${t.title}`).join("\n");
      } else {
        input.value = "";
      }
      setTimeout(() => input.focus(), 50);
    }
  } else {
    // When closing drawer, if there are no pending changes, clear textarea
    if (!pendingTracklistNames) {
      const input = document.getElementById("batchTrackNamesInput");
      if (input) input.value = "";
    }
  }
}

function previewBatchTrackNames() {
  if (!currentTracklistMedia || !Array.isArray(currentTracklistMedia.tracks)) return;
  const inputEl = document.getElementById("batchTrackNamesInput");
  const rawText = inputEl ? inputEl.value.trim() : "";

  if (!rawText) {
    showToast("Please enter or paste track names to preview.", "warning");
    return;
  }

  const parsedNames = parseClientTrackNames(rawText);
  if (parsedNames.length === 0) {
    showToast("No valid track names found in input.", "warning");
    return;
  }

  // Backup original track titles if not already backed up
  if (!originalTracklistBackup) {
    originalTracklistBackup = currentTracklistMedia.tracks.map(t => t.title);
  }

  pendingTracklistNames = parsedNames;

  // Show pending banner
  const banner = document.getElementById("tracklistPendingBanner");
  const summary = document.getElementById("tracklistPendingSummary");
  const saveBtn = document.getElementById("btnSaveTrackNames");

  if (banner) banner.style.display = "flex";
  if (summary) {
    const count = Math.min(parsedNames.length, currentTracklistMedia.tracks.length);
    summary.innerText = `Previewing ${count} pending track name(s). Review table below, then click Save to commit.`;
  }
  if (saveBtn) {
    saveBtn.disabled = false;
    saveBtn.style.opacity = "1";
  }

  renderTracklistRows();
  showToast(`👁️ Previewing ${parsedNames.length} chapter title(s). Not yet saved!`);
}

function revertPendingTrackNames(silent = false) {
  if (originalTracklistBackup && currentTracklistMedia && Array.isArray(currentTracklistMedia.tracks)) {
    originalTracklistBackup.forEach((title, idx) => {
      if (currentTracklistMedia.tracks[idx]) {
        currentTracklistMedia.tracks[idx].title = title;
      }
    });
  }

  originalTracklistBackup = null;
  pendingTracklistNames = null;

  const banner = document.getElementById("tracklistPendingBanner");
  const saveBtn = document.getElementById("btnSaveTrackNames");
  if (banner) banner.style.display = "none";
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.style.opacity = "0.6";
  }

  renderTracklistRows();
  if (!silent) {
    showToast("↩ Reverted pending track changes to original titles.", "info");
  }
}

async function applyBatchTrackNames() {
  if (!currentTracklistMedia || !currentTracklistMedia.id) return;
  const mediaId = currentTracklistMedia.id;
  const inputEl = document.getElementById("batchTrackNamesInput");
  const rawText = inputEl ? inputEl.value.trim() : "";

  if (!rawText) {
    showToast("Please enter or paste track names first.", "warning");
    return;
  }

  showToast("Saving track and chapter names to Audiobookshelf...", "info");

  try {
    const res = await fetch(`/api/admin/media/${encodeURIComponent(mediaId)}/tracks`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: currentTracklistMedia.type || "abs",
        raw_text: rawText
      })
    });
    const data = await res.json();

    if (!data.ok) {
      showToast("Failed to update tracks: " + (data.error || "Unknown error"), "error");
      return;
    }

    showToast(`✅ ${data.message || "Track names saved successfully!"}`);
    
    // Clear pending preview state
    originalTracklistBackup = null;
    pendingTracklistNames = null;
    const banner = document.getElementById("tracklistPendingBanner");
    const saveBtn = document.getElementById("btnSaveTrackNames");
    if (banner) banner.style.display = "none";
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.style.opacity = "0.6";
    }

    toggleBatchRenameDrawer(false);

    // Refresh modal tracklist rows with updated names
    if (Array.isArray(data.chapters) && currentTracklistMedia.tracks) {
      data.chapters.forEach((ch, idx) => {
        if (currentTracklistMedia.tracks[idx]) {
          currentTracklistMedia.tracks[idx].title = ch.title || currentTracklistMedia.tracks[idx].title;
        }
      });
      renderTracklistRows();
    } else {
      await openTracklistModal(mediaId);
    }
  } catch (err) {
    console.error("Error applying batch track names:", err);
    showToast("Network error updating track names: " + err.message, "error");
  }
}

async function autoMatchCurrentTrackIcons() {
  if (!currentTracklistMedia || !currentTracklistMedia.id) return;
  const mediaId = currentTracklistMedia.id;

  showToast("Scanning community icon libraries for chapter matches...", "info");

  try {
    const res = await fetch(`/api/admin/media/${encodeURIComponent(mediaId)}/auto-match-icons`, {
      method: "POST"
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`⚡ Auto-matched ${data.matched_count} of ${data.total_tracks} track icon(s)!`);
      // Update local tracklist data with newly matched icons
      if (Array.isArray(data.assigned_tracks)) {
        data.assigned_tracks.forEach(at => {
          const target = currentTracklistMedia.tracks.find(t => t.index === at.track_index);
          if (target && at.icon_url) {
            target.icon_url = at.icon_url;
            target.has_custom_icon = true;
          }
        });
        renderTracklistRows();
      }
    } else {
      showToast("Auto-match failed: " + (data.error || "Unknown error"), "error");
    }
  } catch (err) {
    showToast("Network error during auto-match: " + err.message, "error");
  }
}

// ============================================================================
// Interactive Icon Search & Picker Modal (MYO Studio Style)
// ============================================================================

function openIconPickerForTrack(trackIndex) {
  activePickerTrackIndex = trackIndex;
  const modal = document.getElementById("iconPickerModal");
  const track = currentTracklistMedia && currentTracklistMedia.tracks ? currentTracklistMedia.tracks.find(t => t.index === trackIndex) : null;
  const trackTitle = track ? track.title : `Track ${trackIndex + 1}`;

  document.getElementById("iconPickerSubtitle").innerText =
    `Choose 16×16 pixel art for: "${trackTitle}"`;

  // Pre-fill search query with clean chapter title
  const cleanQ = trackTitle.replace(/^(?:Chapter|Track|Part|Book)\s*\d+[:.\s-]*/i, "").trim() || trackTitle;
  document.getElementById("iconSearchInput").value = cleanQ;

  modal.style.display = "flex";
  executeIconSearch();
}

function closeIconPickerModal() {
  const modal = document.getElementById("iconPickerModal");
  if (modal) modal.style.display = "none";
  activePickerTrackIndex = null;
}

function searchIconTag(tag) {
  document.getElementById("iconSearchInput").value = tag;
  executeIconSearch();
}

async function executeIconSearch() {
  const query = document.getElementById("iconSearchInput").value.trim();
  const resultsContainer = document.getElementById("iconPickerResults");
  if (!query) {
    resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px;">Type a keyword above to search icons.</p>`;
    return;
  }

  resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px;">Searching YotoIcons & Tinker...</p>`;

  try {
    const res = await fetch(`/api/admin/icons/search?q=${encodeURIComponent(query)}&limit=30`);
    const data = await res.json();
    if (!data.ok || !data.results || data.results.length === 0) {
      resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px;">No icons found for "${escapeHtml(query)}". Try another word.</p>`;
      return;
    }

    resultsContainer.innerHTML = "";
    data.results.forEach(icon => {
      const tile = document.createElement("div");
      tile.style.background = "var(--bg-base)";
      tile.style.border = "1px solid var(--border-subtle)";
      tile.style.borderRadius = "8px";
      tile.style.padding = "8px 6px";
      tile.style.display = "flex";
      tile.style.flexDirection = "column";
      tile.style.alignItems = "center";
      tile.style.cursor = "pointer";
      tile.style.transition = "transform 0.15s, border-color 0.15s, background 0.15s";
      tile.title = `${icon.name} (${icon.source})`;

      tile.onmouseover = () => {
        tile.style.borderColor = "var(--accent-yoto)";
        tile.style.background = "rgba(229, 53, 43, 0.08)";
        tile.style.transform = "translateY(-2px)";
      };
      tile.onmouseout = () => {
        tile.style.borderColor = "var(--border-subtle)";
        tile.style.background = "var(--bg-base)";
        tile.style.transform = "translateY(0)";
      };

      tile.onclick = () => selectIconForActiveTrack(icon);

      tile.innerHTML = `
        <img src="${escapeHtml(icon.url)}" style="width: 40px; height: 40px; image-rendering: pixelated; object-fit: contain; border-radius: 4px;" alt="${escapeHtml(icon.name)}">
        <span style="font-size: 10px; color: var(--text-primary); margin-top: 4px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; width: 100%; display: block;">${escapeHtml(icon.name)}</span>
        <span style="font-size: 9px; color: var(--text-muted);">${icon.source === "tinker" ? "Tinker" : "YotoIcons"}</span>
      `;
      resultsContainer.appendChild(tile);
    });
  } catch (err) {
    console.error("Error searching icons:", err);
    resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px; color: var(--accent-danger);">Network error searching icons.</p>`;
  }
}

function selectIconForActiveTrack(icon) {
  if (activePickerTrackIndex === null || !currentTracklistMedia) return;

  const targetIndex = activePickerTrackIndex;
  const track = currentTracklistMedia.tracks.find(t => t.index === targetIndex);
  if (track) {
    track.icon_url = icon.url;
    track.has_custom_icon = true;
    renderTracklistRows();
    showToast(`Assigned "${icon.name}" icon to ${track.title}`);

    // Persist to server (updates Yoto Cloud MYO or ABS chapter)
    const mediaId = currentTracklistMedia.id;
    const mediaType = currentTracklistMedia.type;
    fetch(`/api/admin/media/${encodeURIComponent(mediaId)}/tracks/${targetIndex}/icon`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken()
      },
      body: JSON.stringify({
        type: mediaType,
        icon_url: icon.url,
        icon_name: icon.name
      })
    })
    .then(res => res.json())
    .then(data => {
      if (data.ok) {
        showToast(`Artwork saved to ${mediaType === 'yoto_myo' ? 'Yoto Cloud' : 'library'}!`);
      } else {
        showToast(data.error || "Failed to persist artwork to server", true);
      }
    })
    .catch(err => {
      console.error("Error saving track icon:", err);
      showToast("Network error saving track icon", true);
    });
  }

  closeIconPickerModal();
}

// ============================================================================
// Curation Item Permissions & ABS Tagging Modal
// ============================================================================

let currentModalItem = null;

function openCurationPermissionsModal(itemId) {
  if (!currentMatrix || !currentMatrix.items) return;
  const item = currentMatrix.items.find(it => it.id === itemId);
  if (!item) return;

  currentModalItem = item;

  document.getElementById("curationModalTitle").innerText = item.title;
  document.getElementById("curationModalAuthor").innerText = item.author || "Unknown";
  document.getElementById("curationModalThumb").src = item.cover_url || `/api/thumb?type=${item.type}&id=${item.id}&size=100`;

  const typeBadge = document.getElementById("curationModalTypeBadge");
  if (item.type === "yoto_myo") {
    typeBadge.className = "badge badge-info";
    typeBadge.innerText = "MYO";
  } else if (item.type === "yoto") {
    typeBadge.className = "badge badge-success";
    typeBadge.innerText = "YOTO Retail";
  } else {
    typeBadge.className = "badge badge-warning";
    typeBadge.innerText = "Audiobookshelf";
  }

  // Populate profiles list
  const listContainer = document.getElementById("curationModalProfilesList");
  listContainer.innerHTML = "";

  (currentMatrix.profiles || []).forEach(pKey => {
    const pState = (item.profiles && item.profiles[pKey]) ? item.profiles[pKey] : { allowed: false, reason: "none" };
    const p = currentProfiles[pKey] || { display_name: pKey };
    const isAllowed = pState.allowed;
    const isAbsPermitted = pState.reason === "abs_account_permitted" || pState.reason === "abs_tag_match";

    let reasonBadge = `<span class="badge badge-subtle" style="font-size: 10px;">${escapeHtml(pState.reason || 'restricted')}</span>`;
    if (isAbsPermitted) {
      reasonBadge = `<span class="badge badge-success" style="font-size: 10px;">Auto-Permitted (ABS Account)</span>`;
    } else if (pState.reason === "explicit_allowed") {
      reasonBadge = `<span class="badge badge-info" style="font-size: 10px;">Local Override: Allowed</span>`;
    } else if (pState.reason === "explicit_excluded") {
      reasonBadge = `<span class="badge badge-danger" style="font-size: 10px;">Explicitly Blocked</span>`;
    }

    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.justifyContent = "space-between";
    row.style.padding = "6px 8px";
    row.style.borderRadius = "4px";
    row.style.background = isAllowed ? "rgba(16, 185, 129, 0.05)" : "transparent";

    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 14px;">${isAllowed ? "🟢" : "⚪"}</span>
        <div>
          <strong style="font-size: 13px;">${escapeHtml(p.display_name || pKey)}</strong>
          <div style="margin-top: 2px;">${reasonBadge}</div>
        </div>
      </div>
      <label class="toggle-control" style="margin: 0;">
        <input type="checkbox" ${isAllowed ? "checked" : ""} onchange="onModalToggleProfileAccess('${pKey}', '${escapeHtml(item.id)}', this.checked)">
        <span class="toggle-slider"></span>
      </label>
    `;
    listContainer.appendChild(row);
  });

  // Audiobookshelf Section
  const absSection = document.getElementById("curationModalAbsSection");
  if (item.type === "abs") {
    absSection.style.display = "block";
    renderModalAbsTags(item.tags || []);
    // Ensure dropdown options are populated
    populateAbsServerTagsDropdowns();
  } else {
    absSection.style.display = "none";
  }

  document.getElementById("curationPermissionsModal").style.display = "flex";
}

function renderModalAbsTags(tags) {
  const container = document.getElementById("curationModalTagsContainer");
  const badge = document.getElementById("curationModalAbsStatusBadge");
  const btn = document.getElementById("btnToggleChildrenTag");
  const defaultLabelEl = document.getElementById("curationModalConfiguredTagsLabel");

  if (defaultLabelEl) {
    defaultLabelEl.innerText = configuredDefaultChildTags.join(", ") || "Children";
  }

  container.innerHTML = "";
  const primaryChildTag = (configuredDefaultChildTags && configuredDefaultChildTags.length > 0)
    ? configuredDefaultChildTags[0]
    : "Children";

  const lowerDefaultTags = (configuredDefaultChildTags || ["Children"]).map(t => t.toLowerCase());
  const matchingChildTag = tags.find(t => lowerDefaultTags.includes(t.toLowerCase()));

  if (matchingChildTag) {
    badge.className = "badge badge-success";
    badge.innerText = `Tagged '${matchingChildTag}' in ABS`;
    btn.className = "btn btn-sm btn-secondary";
    btn.innerText = `Remove '${matchingChildTag}' Tag from ABS`;
  } else {
    badge.className = "badge badge-subtle";
    badge.innerText = "No Child Default Tag";
    btn.className = "btn btn-sm btn-primary";
    btn.innerText = `🏷️ Add '${primaryChildTag}' Tag to ABS`;
  }

  if (tags.length === 0) {
    container.innerHTML = `<span class="text-secondary" style="font-size: 11px;">No server tags assigned.</span>`;
  } else {
    tags.forEach(t => {
      const isChild = lowerDefaultTags.includes(t.toLowerCase());
      const pill = document.createElement("span");
      pill.className = `badge ${isChild ? "badge-success" : "badge-subtle"}`;
      pill.style.fontSize = "11px";
      pill.innerText = t;
      container.appendChild(pill);
    });
  }
}

async function toggleItemDefaultChildTag() {
  if (!currentModalItem) return;
  const item = currentModalItem;
  let tags = item.tags ? [...item.tags] : [];

  const lowerDefaultTags = (configuredDefaultChildTags || ["Children"]).map(t => t.toLowerCase());
  const primaryChildTag = (configuredDefaultChildTags && configuredDefaultChildTags.length > 0)
    ? configuredDefaultChildTags[0]
    : "Children";

  const idx = tags.findIndex(t => lowerDefaultTags.includes(t.toLowerCase()));

  if (idx >= 0) {
    tags.splice(idx, 1);
  } else {
    tags.push(primaryChildTag);
  }

  await updateItemTagsOnServer(item, tags);
}

// Backward compatibility alias for toggleItemChildrenTag
async function toggleItemChildrenTag() {
  await toggleItemDefaultChildTag();
}

async function addTagFromModalDropdown() {
  if (!currentModalItem) return;
  const select = document.getElementById("curationModalTagDropdown");
  if (!select) return;
  const tagToAdd = select.value.trim();
  if (!tagToAdd) {
    showToast("Please choose a tag from the dropdown.", "warning");
    return;
  }

  const item = currentModalItem;
  let tags = item.tags ? [...item.tags] : [];
  if (tags.some(t => t.toLowerCase() === tagToAdd.toLowerCase())) {
    showToast(`Book already has tag '${tagToAdd}'.`, "info");
    return;
  }

  tags.push(tagToAdd);
  await updateItemTagsOnServer(item, tags);
  select.value = "";
}

async function updateItemTagsOnServer(item, newTags) {
  try {
    const res = await fetch("/api/admin/abs/item-tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: item.id, tags: newTags })
    });
    const result = await res.json();
    if (result.ok) {
      item.tags = newTags;
      showToast(`Audiobookshelf tags updated for '${item.title}'.`);
      renderModalAbsTags(newTags);
      // Reload matrix to update profile permission calculations
      await loadMatrix();
      // Re-read updated item from matrix
      const updated = currentMatrix.items.find(it => it.id === item.id);
      if (updated) {
        currentModalItem = updated;
        openCurationPermissionsModal(updated.id);
      }
    } else {
      showToast(result.error || "Failed to update ABS tags", "danger");
    }
  } catch (err) {
    console.error("Error updating ABS tags:", err);
    showToast("Error updating ABS tags.", "danger");
  }
}

async function onModalToggleProfileAccess(profileId, mediaId, isAllowed) {
  await toggleProfilePermission(profileId, mediaId, isAllowed);
  // Refresh matrix and re-open modal with refreshed state
  await loadMatrix();
  if (currentModalItem) {
    const updated = currentMatrix.items.find(it => it.id === currentModalItem.id);
    if (updated) {
      openCurationPermissionsModal(updated.id);
    }
  }
}

function closeCurationPermissionsModal() {
  document.getElementById("curationPermissionsModal").style.display = "none";
  currentModalItem = null;
}

async function updateSharedRule(key, value) {
  try {
    const res = await fetch("/api/admin/curation/shared-rule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value })
    });
    showToast(`Shared rule '${key}' updated.`);
    loadMatrix();
  } catch (err) {
    showToast("Failed to update shared rule.", "danger");
  }
}

async function toggleItemHighlight(itemId, isHighlight) {
  try {
    await fetch(`/api/admin/catalog/highlight/${encodeURIComponent(itemId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_highlight: isHighlight })
    });
    showToast("Highlight state updated.");
  } catch (err) {
    showToast("Failed to toggle highlight.", "danger");
  }
}

async function toggleProfilePermission(profileId, mediaId, allowed) {
  try {
    await fetch(`/api/admin/curation/permission`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId, media_id: mediaId, allowed })
    });
    showToast(`Permission updated for ${profileId}.`);
  } catch (err) {
    showToast("Failed to update permission.", "danger");
  }
}

async function syncUpstreamCatalogs() {
  showToast("Scanning upstream Yoto & Audiobookshelf libraries...");
  try {
    const res = await fetch("/api/admin/catalog/sync", { method: "POST" });
    const data = await res.json();
    showToast(`Catalog sync complete (${data.count || 0} items updated).`, "success");
    loadMatrix();
  } catch (err) {
    showToast("Sync failed. Check connection to Yoto & Audiobookshelf.", "danger");
  }
}

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


// ============================================================================
// Diagnostics & Settings (Tab 4)
// ============================================================================

function onYotoModeChange() {
  const mode = document.getElementById("yotoConnectionMode").value;
  const bridgeSection = document.getElementById("sectionBridgeConfig");
  const directSection = document.getElementById("sectionDirectYotoCloud");
  const absSection = document.getElementById("sectionAbsConfig");
  const aiSection = document.getElementById("sectionAiConfig");

  const bridgeCard = document.getElementById("diagCardBridge");
  const yotoCard = document.getElementById("diagCardYoto");
  const absCard = document.getElementById("diagCardAbs");
  const aiCard = document.getElementById("diagCardAi");
  const tinkerCard = document.getElementById("diagCardTinker");

  if (mode === "bridge") {
    // Mode 1: Bridge Mode (Hybrid ABS + Yoto Streaming)
    if (bridgeSection) bridgeSection.style.display = "block";
    if (directSection) directSection.style.display = "none";
    if (absSection) absSection.style.display = "block";
    if (aiSection) aiSection.style.display = "block";

    if (bridgeCard) bridgeCard.style.display = "block";
    if (yotoCard) yotoCard.style.display = "none";
    if (absCard) absCard.style.display = "block";
    if (aiCard) aiCard.style.display = "block";
    if (tinkerCard) tinkerCard.style.display = "block";
  } else {
    // Mode 2: Standalone Direct Yoto Cloud (Pure Yoto - No ABS / No Bridge / No AI)
    if (bridgeSection) bridgeSection.style.display = "none";
    if (directSection) directSection.style.display = "block";
    if (absSection) absSection.style.display = "none";
    if (aiSection) aiSection.style.display = "none";

    if (bridgeCard) bridgeCard.style.display = "none";
    if (yotoCard) yotoCard.style.display = "block";
    if (absCard) absCard.style.display = "none";
    if (aiCard) aiCard.style.display = "none";
    if (tinkerCard) tinkerCard.style.display = "none";
  }
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
    if (creds.yoto_bridge_api_key) document.getElementById("credBridgeApiKey").value = creds.yoto_bridge_api_key;
    if (creds.tinker_api_key) document.getElementById("credTinkerKey").value = creds.tinker_api_key;
    if (creds.openrouter_api_key) document.getElementById("credOpenRouterKey").value = creds.openrouter_api_key;

    const modeSelect = document.getElementById("yotoConnectionMode");
    if (modeSelect) {
      modeSelect.value = creds.yoto_connection_mode || "bridge";
      onYotoModeChange();
    }

    // Load master security API key
    await loadMasterApiKey();

    // Load default children tags and fetch live ABS server tags
    await loadAbsDefaultTags();
    await fetchAbsServerTags();
  } catch (err) {
    console.error("Failed to load credentials:", err);
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
    btn.innerText = "🙈 Hide";
  } else {
    input.type = "password";
    btn.innerText = "👁️ Show";
  }
}

async function copyMasterApiKey() {
  const input = document.getElementById("brokerMasterApiKey");
  const keyToCopy = rawMasterApiKey || (input ? input.value : "");
  if (!keyToCopy) {
    showToast("No API key available to copy.", "warning");
    return;
  }
  try {
    await navigator.clipboard.writeText(keyToCopy);
    showToast("Master API Key copied to clipboard!", "success");
  } catch (err) {
    // Fallback selection copy
    if (input) {
      input.type = "text";
      input.select();
      document.execCommand("copy");
      input.type = "password";
      showToast("Master API Key copied to clipboard!", "success");
    } else {
      showToast("Unable to copy to clipboard.", "danger");
    }
  }
}

function openRegenerateApiKeyModal() {
  const modal = document.getElementById("regenerateApiKeyModal");
  if (modal) modal.style.display = "flex";
}

function closeRegenerateApiKeyModal() {
  const modal = document.getElementById("regenerateApiKeyModal");
  if (modal) modal.style.display = "none";
}

async function confirmRegenerateApiKey() {
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
      }
      closeRegenerateApiKeyModal();
      showToast("Master API Key regenerated successfully!", "success");
    } else {
      showToast(data.error || "Failed to regenerate API key.", "danger");
    }
  } catch (err) {
    showToast("Network error regenerating API key.", "danger");
  }
}


// ----------------------------------------------------------------------------
// Audiobookshelf Default Children Tags & Server Tag Management
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

function renderSelectedDefaultTags() {
  const container = document.getElementById("absSelectedDefaultTags");
  if (!container) return;
  container.innerHTML = "";

  if (!configuredDefaultChildTags || configuredDefaultChildTags.length === 0) {
    container.innerHTML = `<span class="text-secondary" style="font-size: 11px; padding: 2px 4px;">No tags selected (Defaults to 'Children').</span>`;
    return;
  }

  configuredDefaultChildTags.forEach(tag => {
    const pill = document.createElement("span");
    pill.className = "badge badge-success";
    pill.style.display = "inline-flex";
    pill.style.alignItems = "center";
    pill.style.gap = "4px";
    pill.style.fontSize = "11px";
    pill.style.padding = "2px 7px";

    pill.innerHTML = `
      <span>🏷️ ${escapeHtml(tag)}</span>
      <span style="cursor: pointer; font-weight: bold; margin-left: 2px;" onclick="removeAbsDefaultTag('${escapeHtml(tag)}')">&times;</span>
    `;
    container.appendChild(pill);
  });
}

function updateConfiguredTagsLabels() {
  const labelEl = document.getElementById("curationModalConfiguredTagsLabel");
  if (labelEl) {
    labelEl.innerText = configuredDefaultChildTags.join(", ") || "Children";
  }
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
  // Settings dropdown
  const settingsSelect = document.getElementById("absServerTagsDropdown");
  if (settingsSelect) {
    settingsSelect.innerHTML = `<option value="">-- Choose from Audiobookshelf tags --</option>`;
    cachedAbsServerTags.forEach(tag => {
      const opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag;
      settingsSelect.appendChild(opt);
    });
  }

  // Curation modal tag dropdown
  const modalSelect = document.getElementById("curationModalTagDropdown");
  if (modalSelect) {
    modalSelect.innerHTML = `<option value="">-- Add another ABS tag --</option>`;
    cachedAbsServerTags.forEach(tag => {
      const opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag;
      modalSelect.appendChild(opt);
    });
  }
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
      // Reload matrix to recalculate access reasons with new tags
      loadMatrix();
    } else {
      showToast(data.error || "Failed to update default tags.", "danger");
    }
  } catch (err) {
    showToast("Network error saving default tags.", "danger");
  }
}

async function saveApiCredentials(e) {
  e.preventDefault();
  const mode = document.getElementById("yotoConnectionMode").value;
  const tinkerInput = document.getElementById("credTinkerKey");
  const payload = {
    abs_base_url: document.getElementById("credAbsUrl").value.trim(),
    abs_api_key: document.getElementById("credAbsKey").value.trim(),
    yoto_connection_mode: mode,
    yoto_client_id: document.getElementById("credYotoClientId").value.trim(),
    yoto_client_secret: document.getElementById("credYotoSecret").value.trim(),
    yoto_refresh_token: document.getElementById("credYotoRefresh").value.trim(),
    yoto_bridge_url: document.getElementById("credBridgeUrl").value.trim(),
    yoto_bridge_api_key: document.getElementById("credBridgeApiKey") ? document.getElementById("credBridgeApiKey").value.trim() : "",
    tinker_api_key: tinkerInput ? tinkerInput.value.trim() : "",
    openrouter_api_key: document.getElementById("credOpenRouterKey").value.trim()
  };

  try {
    const res = await fetch("/api/admin/settings/credentials", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("API Credentials saved and active services reloaded!", "success");
      loadApiCredentials();
    } else {
      showToast(data.error || "Failed to save credentials.", "danger");
    }
  } catch (err) {
    showToast("Network error saving credentials.", "danger");
  }
}

async function runDiagnosticTest(target) {
  showToast(`Testing ${target.toUpperCase()}...`);
  try {
    const res = await fetch(`/api/admin/test/${target}`, { method: "POST" });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`${target.toUpperCase()} test PASSED: ${data.message || "OK"}`, "success");
    } else {
      showToast(`${target.toUpperCase()} test failed: ${data.error || "Check credentials"}`, "danger");
    }
  } catch (err) {
    showToast(`Network error testing ${target}.`, "danger");
  }
}

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
    document.getElementById("yotoOAuthManualHelper").style.display = "block";

    // Open Yoto login in popup window
    const popup = window.open(data.auth_url, "yotoAuthPopup", "width=600,height=750,menubar=no,toolbar=no");
    if (!popup || popup.closed || typeof popup.closed === "undefined") {
      // If popup blocked, open in new tab
      window.open(data.auth_url, "_blank");
    }
    showToast("Sign into Yoto in the opened window and approve access.", "info");
  } catch (err) {
    showToast("Network error starting Yoto OAuth: " + err.message, "danger");
  }
}

async function finishInBrowserYotoOAuth(codeOrUrl) {
  const input = codeOrUrl || document.getElementById("yotoPastedUrl").value.trim();
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
      document.getElementById("yotoOAuthManualHelper").style.display = "none";
      loadApiCredentials();
    } else {
      showToast(data.error || "Failed to complete Yoto login.", "danger");
    }
  } catch (err) {
    showToast("Network error completing Yoto login: " + err.message, "danger");
  }
}

// Listen for cross-window message from the callback landing page popup
window.addEventListener("message", (event) => {
  if (event.data && event.data.type === "YOTO_AUTH_CALLBACK") {
    console.log("Received Yoto callback code via window message:", event.data);
    finishInBrowserYotoOAuth(event.data.code);
  }
});

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

