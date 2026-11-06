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

async function quickBatchPhysical(hasPhysical) {
  if (selectedMatrixItemIds.size === 0) return;
  const ids = Array.from(selectedMatrixItemIds);
  try {
    const res = await fetch("/api/admin/curation/batch-physical", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_ids: ids, has_physical: hasPhysical })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`${hasPhysical ? "🎴 Marked" : "📱 Cleared physical tag for"} ${ids.length} card(s)`);
      currentMatrix.items.forEach(it => {
        if (selectedMatrixItemIds.has(it.id)) {
          it.has_physical = hasPhysical;
        }
      });
      renderMatrixTable();
    } else {
      showToast("Failed to update physical tags: " + (data.error || "Unknown error"), "error");
    }
  } catch (err) {
    showToast("Network error updating physical tags: " + err.message, "error");
  }
}

