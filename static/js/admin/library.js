// ============================================================================
// Curation Matrix (Tab 2)
// ============================================================================

// Helper to clean titles for article-insensitive sorting (matching Controller behavior)
function cleanTitleForSort(str) {
  if (!str) return "";
  return String(str).replace(/^(the|a|an)\s+/i, "").trim().toLowerCase();
}


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

function toggleCurationProfileDropdown(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById("curationProfileMenu");
  if (!menu) return;
  const isHidden = menu.style.display === "none";
  menu.style.display = isHidden ? "flex" : "none";
}

// Global click listener to close custom dropdown
document.addEventListener("click", (e) => {
  if (!e.target.closest("#curationProfilePicker")) {
    const menu = document.getElementById("curationProfileMenu");
    if (menu) menu.style.display = "none";
  }
});

function selectCurationProfile(pKey) {
  const select = document.getElementById("curationProfileFilter");
  if (select) {
    select.value = pKey;
  }
  updateCurationProfilePickerUI(pKey);
  const menu = document.getElementById("curationProfileMenu");
  if (menu) menu.style.display = "none";
  onCurationProfileFilterChange();
}

function updateCurationProfilePickerUI(selectedKey) {
  const labelEl = document.getElementById("curationProfileSelectedLabel");
  const avatarSlot = document.getElementById("curationProfileSelectedAvatar");
  if (!labelEl || !avatarSlot) return;

  const monograms = typeof computeHouseholdMonograms === "function" ? computeHouseholdMonograms(currentProfiles) : {};

  if (!selectedKey || selectedKey === "all") {
    labelEl.textContent = "Household (All Profiles)";
    avatarSlot.innerHTML = `<span style="font-size: 16px;">🏠</span>`;
  } else {
    const p = currentProfiles[selectedKey] || { display_name: selectedKey };
    labelEl.textContent = p.display_name || selectedKey;
    const monogram = p.avatar_initial || (monograms && monograms[selectedKey]) || (p.display_name || selectedKey || "C").trim().charAt(0).toUpperCase();
    const avatarBg = typeof getAvatarColor === "function" ? getAvatarColor(p.display_name || selectedKey, p.avatar_color) : "#6366f1";
    const fontSize = monogram.length > 1 ? "10px" : "12px";

    if (p.avatar_url && !p.avatar_url.includes("avatar/placeholder")) {
      avatarSlot.innerHTML = `<img src="${escapeHtml(p.avatar_url)}" alt="${escapeHtml(p.display_name || selectedKey)}" onerror="this.onerror=null;this.replaceWith(createInitialAvatarElement('${escapeHtml(monogram)}', '${avatarBg}', 22));" style="width: 22px; height: 22px; border-radius: 50%; object-fit: cover; border: 1.5px solid var(--accent-info); flex-shrink: 0;">`;
    } else {
      avatarSlot.innerHTML = `<div style="width: 22px; height: 22px; border-radius: 50%; background: ${avatarBg}; color: #ffffff; display: flex; align-items: center; justify-content: center; font-size: ${fontSize}; font-weight: 700; flex-shrink: 0;">${escapeHtml(monogram)}</div>`;
    }
  }

  // Update active state in menu
  document.querySelectorAll(".custom-profile-opt").forEach(opt => {
    opt.classList.toggle("active", opt.dataset.profileKey === selectedKey);
  });
}

function populateCurationProfileOptions() {
  const select = document.getElementById("curationProfileFilter");
  const menu = document.getElementById("curationProfileMenu");
  if (!select) return;
  const currentVal = select.value || "all";
  select.innerHTML = '<option value="all">Household (All Profiles)</option>';

  if (menu) {
    menu.innerHTML = `
      <div class="custom-profile-opt ${currentVal === 'all' ? 'active' : ''}" data-profile-key="all" onclick="selectCurationProfile('all')">
        <span style="font-size: 16px;">🏠</span>
        <span>Household (All Profiles)</span>
      </div>
    `;
  }

  const monograms = typeof computeHouseholdMonograms === "function" ? computeHouseholdMonograms(currentProfiles) : {};

  if (currentMatrix.profiles && currentMatrix.profiles.length > 0) {
    currentMatrix.profiles.forEach(pKey => {
      const p = currentProfiles[pKey] || { display_name: pKey };
      const opt = document.createElement("option");
      opt.value = pKey;
      opt.textContent = p.display_name || pKey;
      select.appendChild(opt);

      if (menu) {
        const monogram = p.avatar_initial || (monograms && monograms[pKey]) || (p.display_name || pKey || "C").trim().charAt(0).toUpperCase();
        const avatarBg = typeof getAvatarColor === "function" ? getAvatarColor(p.display_name || pKey, p.avatar_color) : "#6366f1";
        const fontSize = monogram.length > 1 ? "10px" : "12px";

        const avatarSnippet = (p.avatar_url && !p.avatar_url.includes("avatar/placeholder"))
          ? `<img src="${escapeHtml(p.avatar_url)}" alt="${escapeHtml(p.display_name || pKey)}" onerror="this.onerror=null;this.replaceWith(createInitialAvatarElement('${escapeHtml(monogram)}', '${avatarBg}', 24));" style="width: 24px; height: 24px; border-radius: 50%; object-fit: cover; border: 1.5px solid var(--accent-info); flex-shrink: 0;">`
          : `<div style="width: 24px; height: 24px; border-radius: 50%; background: ${avatarBg}; color: #ffffff; display: flex; align-items: center; justify-content: center; font-size: ${fontSize}; font-weight: 700; flex-shrink: 0;">${escapeHtml(monogram)}</div>`;

        const optDiv = document.createElement("div");
        optDiv.className = `custom-profile-opt ${currentVal === pKey ? 'active' : ''}`;
        optDiv.dataset.profileKey = pKey;
        optDiv.onclick = () => selectCurationProfile(pKey);
        optDiv.innerHTML = `
          ${avatarSnippet}
          <span style="font-weight: 500;">${escapeHtml(p.display_name || pKey)}</span>
        `;
        menu.appendChild(optDiv);
      }
    });
  }

  if (currentVal && Array.from(select.options).some(o => o.value === currentVal)) {
    select.value = currentVal;
  }
  updateCurationProfilePickerUI(select.value);
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
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No cards discovered yet. Click 'Refresh Catalogs' to pull from Yoto & Audiobookshelf.</td></tr>`;
    return;
  }

  // Populate dynamic series dropdown from unique series across items
  populateSeriesFilterDropdown();

  // Sort items using Controller methodology: Highlights first, then article-insensitive (ignoring 'A', 'An', 'The')
  const sortedItems = [...currentMatrix.items].sort((a, b) => {
    const hiA = !!a.is_highlight;
    const hiB = !!b.is_highlight;
    if (hiA !== hiB) {
      return hiA ? -1 : 1; // Highlights on top
    }
    const titleA = cleanTitleForSort(a.title);
    const titleB = cleanTitleForSort(b.title);
    return titleA.localeCompare(titleB);
  });

  sortedItems.forEach(item => {
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
    tr.dataset.physical = item.has_physical ? "true" : "false";
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
        if (item.is_series_overridden) {
          seriesBadgesHtml += `<span class="badge badge-series-override" title="Manual parent override">📚 ${escapeHtml(s.name)}${escapeHtml(orderText)} (Custom)</span>`;
        } else {
          seriesBadgesHtml += `<span class="badge" style="font-size: 11px; padding: 2px 6px; background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.35);">📚 ${escapeHtml(s.name)}${escapeHtml(orderText)}</span>`;
        }
      });
      seriesBadgesHtml += '</div>';
    } else if (item.is_series_overridden) {
      seriesBadgesHtml = '<div style="margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px;"><span class="badge badge-series-override" title="Explicitly marked Standalone by parent">📚 Standalone (Custom)</span></div>';
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

    // Physical Ownership Toggle
    const physTd = document.createElement("td");
    physTd.style.textAlign = "center";
    physTd.innerHTML = `
      <label class="toggle-control" style="margin: 0 auto;">
        <input type="checkbox" ${item.has_physical ? "checked" : ""} onchange="toggleItemPhysical('${escapeHtml(item.id)}', this.checked)">
        <span class="toggle-slider"></span>
      </label>
    `;
    tr.appendChild(physTd);

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

    const isYotoItem = (item.type === "yoto" || item.type === "yoto_myo");
    const editSeriesBtnHtml = isYotoItem
      ? `<button class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 4px 8px;" onclick="openEditSeriesModal('${escapeHtml(item.id)}')" title="Edit manual series & sequence override">📚 Series</button>`
      : "";

    accessTd.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
        <div style="display: flex; flex-wrap: wrap; gap: 4px; align-items: center;">
          ${pillsHtml || '<span class="text-secondary" style="font-size: 11px;">No access</span>'}
        </div>
        <div style="display: flex; gap: 4px; flex-shrink: 0;">
          ${editSeriesBtnHtml}
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

  // Populate autocomplete datalist with ALL unique series across library (even single-card series)
  const allSeriesSorted = Array.from(seriesSet).sort((a, b) => {
    return cleanTitleForSort(a).localeCompare(cleanTitleForSort(b));
  });
  populateSeriesDatalist(allSeriesSorted);

  // Check if exclude_single_card_series is enabled (default true, matching Controller)
  const excludeSingle = (currentMatrix.exclude_single_card_series !== false);

  // Filter out single-card series if exclude_single_card_series is active
  const filteredSeries = Array.from(seriesSet).filter(seriesName => {
    if (!excludeSingle) return true;
    const count = (currentMatrix.items || []).filter(it => {
      if (Array.isArray(it.series_list) && it.series_list.length > 0) {
        return it.series_list.some(s => {
          const clean = normalizeSeriesEntry(s.name, s.order);
          return clean && clean.name.toLowerCase() === seriesName.toLowerCase();
        });
      } else if (it.series) {
        const parts = String(it.series).split(",");
        return parts.some(p => {
          const clean = normalizeSeriesEntry(p, it.series_order);
          return clean && clean.name.toLowerCase() === seriesName.toLowerCase();
        });
      }
      return false;
    }).length;
    return count > 1;
  });

  // Sort series alphabetically ignoring 'The', 'A', 'An' (matching Controller)
  const sortedSeries = filteredSeries.sort((a, b) => {
    return cleanTitleForSort(a).localeCompare(cleanTitleForSort(b));
  });

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

  const physFilterEl = document.getElementById("curationPhysicalFilter");
  const selectedPhys = physFilterEl ? physFilterEl.value : "all";

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

    const rowPhys = (r.dataset.physical === "true");
    let matchesPhys = true;
    if (selectedPhys === "physical") matchesPhys = rowPhys;
    else if (selectedPhys === "digital") matchesPhys = !rowPhys;

    if (matchesSearch && matchesType && matchesSeries && matchesProfile && matchesPhys) {
      r.style.display = "";
    } else {
      r.style.display = "none";
    }
  });

  syncSelectAllCheckboxState();
}

async function toggleItemPhysical(mediaId, hasPhysical) {
  try {
    const res = await fetch(`/api/admin/catalog/physical/${encodeURIComponent(mediaId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ has_physical: hasPhysical })
    });
    const data = await res.json();
    if (data.ok) {
      const it = currentMatrix.items.find(i => i.id === mediaId);
      if (it) it.has_physical = hasPhysical;
      const row = document.querySelector(`tr[data-item-id="${mediaId}"]`);
      if (row) row.dataset.physical = hasPhysical ? "true" : "false";
      showToast(`${hasPhysical ? "🎴 Marked as physical card" : "📱 Marked as digital-only"}`);
    } else {
      showToast("Failed to update physical ownership: " + (data.error || "Unknown error"), "error");
    }
  } catch (err) {
    showToast("Network error updating physical ownership: " + err.message, "error");
  }
}

// ============================================================================
// Yoto Card Manual Series & Sequence Overrides + Bulk Sequencer (DLP-021)
// ============================================================================

let editingSeriesMediaId = null;
let batchSeriesItems = [];
let dragSourceSeriesIndex = null;

function populateSeriesDatalist(seriesNames) {
  const datalist = document.getElementById("existingSeriesList");
  if (!datalist) return;
  datalist.innerHTML = "";
  (seriesNames || []).forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    datalist.appendChild(opt);
  });
}

function openEditSeriesModal(mediaId) {
  const item = (currentMatrix.items || []).find(i => i.id === mediaId);
  if (!item) return;
  if (item.type !== "yoto" && item.type !== "yoto_myo") {
    showToast("Manual series overrides apply only to Yoto cards.", "error");
    return;
  }

  editingSeriesMediaId = mediaId;
  const thumbUrl = item.cover_url || `/api/thumb?type=${item.type}&id=${encodeURIComponent(item.id)}&size=100`;
  document.getElementById("editSeriesCover").src = thumbUrl;
  document.getElementById("editSeriesCardTitle").textContent = item.title || item.id;

  const typeBadge = document.getElementById("editSeriesTypeBadge");
  if (item.type === "yoto_myo") {
    typeBadge.className = "badge badge-info";
    typeBadge.textContent = "MYO";
  } else {
    typeBadge.className = "badge badge-success";
    typeBadge.textContent = "YOTO";
  }

  const autoHintEl = document.getElementById("editSeriesAutoHint");
  const autoSeries = (item.auto_series || "").trim();
  const autoOrder = (item.auto_series_order || "").trim();
  if (autoSeries) {
    autoHintEl.textContent = `Auto-detected: ${autoSeries}${autoOrder ? " #" + autoOrder : ""}`;
  } else {
    autoHintEl.textContent = "Auto-detected: None (Standalone)";
  }

  const overrideBadge = document.getElementById("editSeriesOverrideBadge");
  const revertBtn = document.getElementById("editSeriesRevertBtn");
  const isOverridden = !!item.is_series_overridden;
  overrideBadge.style.display = isOverridden ? "inline-flex" : "none";
  revertBtn.style.display = isOverridden ? "inline-flex" : "none";

  document.getElementById("editSeriesNameInput").value = item.series || "";
  document.getElementById("editSeriesOrderInput").value = item.series_order || "";

  document.getElementById("editSeriesModal").style.display = "flex";
}

function closeEditSeriesModal() {
  editingSeriesMediaId = null;
  const modal = document.getElementById("editSeriesModal");
  if (modal) modal.style.display = "none";
}

async function saveEditSeriesModal() {
  if (!editingSeriesMediaId) return;
  const seriesName = document.getElementById("editSeriesNameInput").value.trim();
  const seriesOrder = document.getElementById("editSeriesOrderInput").value.trim();

  try {
    const res = await fetch(`/api/admin/media/${encodeURIComponent(editingSeriesMediaId)}/series`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        series: seriesName,
        series_order: seriesOrder
      })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(seriesName ? `Saved series "${seriesName}"${seriesOrder ? " #" + seriesOrder : ""}` : "Marked card as Standalone (Custom)");
      closeEditSeriesModal();
      await loadMatrix();
    } else {
      showToast("Failed to save series override: " + (data.error || `HTTP ${res.status}`), "error");
    }
  } catch (err) {
    showToast("Network error saving series override: " + err.message, "error");
  }
}

async function revertEditSeriesModal() {
  if (!editingSeriesMediaId) return;
  try {
    const res = await fetch(`/api/admin/media/${encodeURIComponent(editingSeriesMediaId)}/series`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Reverted card series to automatic detection");
      closeEditSeriesModal();
      await loadMatrix();
    } else {
      showToast("Failed to revert series override: " + (data.error || `HTTP ${res.status}`), "error");
    }
  } catch (err) {
    showToast("Network error reverting series override: " + err.message, "error");
  }
}

function parseNumericSeq(val) {
  const m = String(val || "").match(/(\d+(?:\.\d+)?)/);
  return m ? parseFloat(m[1]) : Number.POSITIVE_INFINITY;
}

function openBatchSeriesModal() {
  if (selectedMatrixItemIds.size === 0) return;

  const selectedItems = (currentMatrix.items || []).filter(it => selectedMatrixItemIds.has(it.id));
  const yotoItems = selectedItems.filter(it => it.type === "yoto" || it.type === "yoto_myo");
  const absCount = selectedItems.length - yotoItems.length;

  if (yotoItems.length === 0) {
    showToast("Bulk series editing is only supported for Yoto cards (ABS series come from Audiobookshelf).", "error");
    return;
  }

  const noticeEl = document.getElementById("batchSeriesAbsNotice");
  if (absCount > 0) {
    noticeEl.style.display = "block";
    noticeEl.textContent = `⚠️ Skipped ${absCount} Audiobookshelf item(s) — manual series overrides apply only to Yoto cards.`;
  } else {
    noticeEl.style.display = "none";
    noticeEl.textContent = "";
  }

  document.getElementById("batchSeriesSubtitle").textContent =
    `Drag rows or use arrow buttons to set book order across ${yotoItems.length} Yoto card(s).`;

  const nonEmptySeries = Array.from(new Set(
    yotoItems.map(it => (it.series || "").trim()).filter(Boolean)
  ));
  document.getElementById("batchSeriesNameInput").value = nonEmptySeries.length === 1 ? nonEmptySeries[0] : "";

  yotoItems.sort((a, b) => {
    const na = parseNumericSeq(a.series_order);
    const nb = parseNumericSeq(b.series_order);
    if (na !== nb) return na - nb;
    return cleanTitleForSort(a.title).localeCompare(cleanTitleForSort(b.title));
  });

  const autoCheck = document.getElementById("batchSeriesAutoNumber");
  if (autoCheck) autoCheck.checked = true;

  batchSeriesItems = yotoItems.map((it, idx) => ({
    id: it.id,
    title: it.title || it.id,
    type: it.type,
    cover_url: it.cover_url || `/api/thumb?type=${it.type}&id=${encodeURIComponent(it.id)}&size=100`,
    sequence: String(idx + 1)
  }));

  renderBatchSeriesList();
  document.getElementById("batchSeriesModal").style.display = "flex";
}

function closeBatchSeriesModal() {
  batchSeriesItems = [];
  dragSourceSeriesIndex = null;
  const modal = document.getElementById("batchSeriesModal");
  if (modal) modal.style.display = "none";
}

function reindexBatchSeriesRows() {
  const autoCheck = document.getElementById("batchSeriesAutoNumber");
  if (autoCheck && autoCheck.checked) {
    batchSeriesItems.forEach((it, idx) => {
      it.sequence = String(idx + 1);
    });
  }
}

function onBatchSeriesAutoNumberToggle() {
  const autoCheck = document.getElementById("batchSeriesAutoNumber");
  if (autoCheck && autoCheck.checked) {
    reindexBatchSeriesRows();
    renderBatchSeriesList();
  }
}

function onBatchSeriesSeqInput(index, value) {
  if (index < 0 || index >= batchSeriesItems.length) return;
  batchSeriesItems[index].sequence = value;
  const autoCheck = document.getElementById("batchSeriesAutoNumber");
  if (autoCheck && autoCheck.checked) {
    autoCheck.checked = false;
  }
}

function moveBatchSeriesRow(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= batchSeriesItems.length) return;
  const [moved] = batchSeriesItems.splice(index, 1);
  batchSeriesItems.splice(target, 0, moved);
  reindexBatchSeriesRows();
  renderBatchSeriesList();
}

function sortBatchSeriesAlpha() {
  batchSeriesItems.sort((a, b) => cleanTitleForSort(a.title).localeCompare(cleanTitleForSort(b.title)));
  reindexBatchSeriesRows();
  renderBatchSeriesList();
}

function renderBatchSeriesList() {
  const listEl = document.getElementById("batchSeriesList");
  if (!listEl) return;
  listEl.innerHTML = "";

  batchSeriesItems.forEach((it, idx) => {
    const row = document.createElement("div");
    row.className = "batch-series-row";
    row.draggable = true;
    row.dataset.index = String(idx);

    const badgeClass = it.type === "yoto_myo" ? "badge-info" : "badge-success";
    const typeLabel = it.type === "yoto_myo" ? "MYO" : "YOTO";

    row.innerHTML = `
      <span class="drag-handle" title="Drag to reorder">≡</span>
      <input type="text" class="batch-seq-input" value="${escapeHtml(it.sequence)}" title="Sequence number (e.g. 1, 1.5, 2)" oninput="onBatchSeriesSeqInput(${idx}, this.value)">
      <img src="${escapeHtml(it.cover_url)}" onerror="this.onerror=null; this.src='/static/img/placeholder.png';" alt="cover" style="width: 34px; height: 34px; border-radius: 5px; object-fit: cover; flex-shrink: 0;">
      <div style="min-width: 0; flex: 1;">
        <div style="font-size: 13px; font-weight: 500; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(it.title)}</div>
      </div>
      <span class="badge ${badgeClass}" style="flex-shrink: 0;">${typeLabel}</span>
      <div style="display: flex; gap: 4px; flex-shrink: 0;">
        <button type="button" class="btn btn-secondary btn-sm" style="padding: 2px 7px; font-size: 11px;" ${idx === 0 ? "disabled" : ""} onclick="moveBatchSeriesRow(${idx}, -1)" title="Move up">▲</button>
        <button type="button" class="btn btn-secondary btn-sm" style="padding: 2px 7px; font-size: 11px;" ${idx === batchSeriesItems.length - 1 ? "disabled" : ""} onclick="moveBatchSeriesRow(${idx}, 1)" title="Move down">▼</button>
      </div>
    `;

    row.addEventListener("dragstart", (e) => {
      dragSourceSeriesIndex = idx;
      row.classList.add("dragging");
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(idx));
      }
    });

    row.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
      if (dragSourceSeriesIndex !== null && dragSourceSeriesIndex !== idx) {
        row.classList.add("drag-over");
      }
    });

    row.addEventListener("dragleave", () => {
      row.classList.remove("drag-over");
    });

    row.addEventListener("drop", (e) => {
      e.preventDefault();
      row.classList.remove("drag-over");
      if (dragSourceSeriesIndex === null || dragSourceSeriesIndex === idx) return;
      const [moved] = batchSeriesItems.splice(dragSourceSeriesIndex, 1);
      batchSeriesItems.splice(idx, 0, moved);
      dragSourceSeriesIndex = null;
      reindexBatchSeriesRows();
      renderBatchSeriesList();
    });

    row.addEventListener("dragend", () => {
      dragSourceSeriesIndex = null;
      listEl.querySelectorAll(".batch-series-row").forEach(r => {
        r.classList.remove("dragging", "drag-over");
      });
    });

    listEl.appendChild(row);
  });
}

async function saveBatchSeriesModal() {
  const seriesName = document.getElementById("batchSeriesNameInput").value.trim();
  if (!seriesName) {
    showToast("Please enter a Shared Series Name.", "error");
    document.getElementById("batchSeriesNameInput").focus();
    return;
  }
  if (batchSeriesItems.length === 0) return;

  const payloadItems = batchSeriesItems.map(it => ({
    id: it.id,
    sequence: String(it.sequence || "").trim()
  }));

  try {
    const res = await fetch("/api/admin/media/batch-series", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        series: seriesName,
        items: payloadItems
      })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Assigned "${seriesName}" across ${data.updated_count} Yoto card(s)`);
      closeBatchSeriesModal();
      if (typeof clearMatrixSelection === "function") {
        clearMatrixSelection();
      }
      await loadMatrix();
    } else {
      showToast("Batch series update failed: " + (data.error || `HTTP ${res.status}`), "error");
    }
  } catch (err) {
    showToast("Network error saving batch series: " + err.message, "error");
  }
}


