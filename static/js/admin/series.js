// Series & Sequence Overrides + Bulk Sequencer (extracted from library.js)

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


