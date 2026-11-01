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
