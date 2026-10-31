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
      const isAbs = (data.type === "abs");
      actionsEl.innerHTML = `
        <button type="button" class="btn btn-sm btn-secondary" onclick="toggleBatchRenameDrawer()">
          📝 Rename Tracks
        </button>
        <button type="button" class="btn btn-sm btn-secondary" onclick="autoMatchCurrentTrackIcons()">
          ⚡ Auto-Match
        </button>
        ${isAbs ? `
        <button type="button" class="btn btn-sm btn-primary" id="btnSyncBridgeIcons" onclick="syncCurrentTrackIconsToBridge()">
          🔄 Sync to Bridge
        </button>` : ''}
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

async function syncCurrentTrackIconsToBridge() {
  if (!currentTracklistMedia || !currentTracklistMedia.id) return;
  const mediaId = currentTracklistMedia.id;
  const btn = document.getElementById("btnSyncBridgeIcons");

  if (btn) {
    btn.disabled = true;
    btn.innerText = "⏳ Syncing...";
  }

  showToast("Pushing local custom chapter icons to Yoto Bridge...", "info");

  try {
    const res = await fetch(`/api/admin/media/${encodeURIComponent(mediaId)}/sync-bridge-icons`, {
      method: "POST"
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`✅ ${data.message}`);
    } else {
      showToast("Sync to Bridge failed: " + (data.error || "Unknown error"), "error");
    }
  } catch (err) {
    showToast("Network error syncing to Bridge: " + err.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "🔄 Sync to Bridge";
    }
  }
}

