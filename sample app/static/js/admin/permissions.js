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
