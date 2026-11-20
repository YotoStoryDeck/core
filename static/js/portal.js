// ==============================================================================
// StoryDeck Parent-First Mobile Front Portal Script
// ==============================================================================

let currentProfiles = {};
let activeProfileId = "";
let currentDevices = [];
let activeDeviceId = "";
let libraryItems = [];
let cardSlots = [];
let cloudPlaylists = [];
let activeBook = null;
let currentPlaylistFilter = "all";
let pollInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  initPortal();
});

// -----------------------------------------------------------------------------
// Navigation & Tab Switching
// -----------------------------------------------------------------------------

function switchTab(tabName) {
  document.querySelectorAll(".tab-view").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));

  const targetTab = document.getElementById(`tab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);
  const targetNav = document.getElementById(`navTab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);

  if (targetTab) targetTab.classList.add("active");
  if (targetNav) targetNav.classList.add("active");

  if (tabName === "cards") loadCards();
  if (tabName === "playlists") loadPlaylists();
  if (tabName === "library") loadLibrary();
}

// -----------------------------------------------------------------------------
// Initialization
// -----------------------------------------------------------------------------

async function initPortal() {
  await loadProfiles();
  await loadDevices();
  await loadLibrary();
  loadCards();
  loadPlaylists();

  // Start polling player status every 3.5s
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(pollPlayerStatus, 3500);
}

// -----------------------------------------------------------------------------
// Profile Handling
// -----------------------------------------------------------------------------

async function loadProfiles() {
  try {
    const res = await fetch("/api/admin/profiles");
    if (!res.ok) return;
    currentProfiles = await res.json();

    const select = document.getElementById("headerProfileSelect");
    select.innerHTML = "";

    const pids = Object.keys(currentProfiles);
    pids.forEach((pid, idx) => {
      const p = currentProfiles[pid];
      const opt = document.createElement("option");
      opt.value = pid;
      opt.innerText = `👶 ${p.display_name || pid}`;
      select.appendChild(opt);
    });

    if (pids.length > 0 && !activeProfileId) {
      activeProfileId = pids[0];
      select.value = activeProfileId;
    }
  } catch (err) {
    console.error("Failed to load profiles:", err);
  }
}

function switchActiveProfile(profileId) {
  activeProfileId = profileId;
  const p = currentProfiles[profileId];
  if (p && p.default_player_id) {
    activeDeviceId = p.default_player_id;
    const devSelect = document.getElementById("playerDeviceSelect");
    if (devSelect) devSelect.value = activeDeviceId;
  }
  const childLabel = document.getElementById("libraryChildNameLabel");
  if (childLabel && p) {
    childLabel.innerText = `Showing books for ${p.display_name || profileId}`;
  }
  loadLibrary();
}

// -----------------------------------------------------------------------------
// Yoto Hardware Devices
// -----------------------------------------------------------------------------

async function loadDevices() {
  try {
    const res = await fetch("/api/player/devices");
    if (!res.ok) return;
    currentDevices = await res.json();

    const select = document.getElementById("playerDeviceSelect");
    select.innerHTML = "";

    if (currentDevices.length === 0) {
      select.innerHTML = "<option value=''>No Yoto Devices Found</option>";
      return;
    }

    currentDevices.forEach((d, idx) => {
      const opt = document.createElement("option");
      opt.value = d.deviceId || d.id;
      opt.innerText = `📻 ${d.name || d.deviceId}${d.online ? " (Online)" : ""}`;
      select.appendChild(opt);
    });

    // Auto-select profile default player or first device
    const activeProf = currentProfiles[activeProfileId];
    if (activeProf && activeProf.default_player_id && currentDevices.some(d => (d.deviceId || d.id) === activeProf.default_player_id)) {
      activeDeviceId = activeProf.default_player_id;
    } else if (currentDevices.length > 0 && !activeDeviceId) {
      activeDeviceId = currentDevices[0].deviceId || currentDevices[0].id;
    }
    select.value = activeDeviceId;
  } catch (err) {
    console.error("Failed to load devices:", err);
  }
}

function onPlayerDeviceChange(deviceId) {
  activeDeviceId = deviceId;
  pollPlayerStatus();
}

// -----------------------------------------------------------------------------
// TAB 1: Player Operations
// -----------------------------------------------------------------------------

let isPlaying = false;
let currentDuration = 0;
let currentPosition = 0;

async function pollPlayerStatus() {
  if (!activeDeviceId) return;
  try {
    const res = await fetch(`/api/player/status/${activeDeviceId}`);
    if (!res.ok) return;
    const data = await res.json();

    const titleEl = document.getElementById("playerTitle");
    const subEl = document.getElementById("playerSubtitle");
    const coverEl = document.getElementById("playerCoverImg");

    const hasActiveMedia = data && (data.is_playing || data.has_card || (data.status === "playing" || data.status === "paused"));

    if (hasActiveMedia) {
      if (titleEl) titleEl.innerText = data.now_playing || data.title || "Audiobook";
      const ch = data.chapter_title || data.chapterTitle;
      if (subEl) {
        subEl.innerText = data.author ? `${data.author}${ch ? ` · ${ch}` : ""}` : (ch ? `Chapter: ${ch}` : "Playing on Yoto");
      }
      const cover = data.cover_url || data.coverUrl || data.coverImageUrl;
      if (coverEl && cover) {
        coverEl.src = cover;
      }
    } else if (data) {
      if (titleEl) titleEl.innerText = "No Active Playback";
      if (subEl) {
        subEl.innerText = data.name ? `${data.name} · ${data.online ? "Online" : "Offline"}` : "Select an audiobook from Library";
      }
      if (coverEl) {
        coverEl.src = "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png";
      }
    }

    if (data && data.playback) {
      isPlaying = data.playback.state === "playing" || Boolean(data.is_playing);
      const playBtn = document.getElementById("btnPlayPause");
      if (playBtn) playBtn.innerText = isPlaying ? "⏸️" : "▶️";

      currentPosition = data.playback.position || data.position || 0;
      currentDuration = data.playback.duration || data.duration || 1;
      const pct = currentDuration > 0 ? Math.min(100, (currentPosition / currentDuration) * 100) : 0;
      const scrubBar = document.getElementById("playerScrubBar");
      if (scrubBar) scrubBar.value = pct;
      const elElapsed = document.getElementById("playerTimeElapsed");
      if (elElapsed) elElapsed.innerText = formatSeconds(currentPosition);
      const elRem = document.getElementById("playerTimeRemaining");
      if (elRem) elRem.innerText = `-${formatSeconds(Math.max(0, currentDuration - currentPosition))}`;
    }

    if (data && data.volume !== undefined) {
      const volSlider = document.getElementById("playerVolumeSlider");
      if (volSlider) volSlider.value = data.volume;
      const volLabel = document.getElementById("playerVolumeLabel");
      if (volLabel) volLabel.innerText = `${data.volume}%`;
    }
  } catch (err) {
    // Poll notice
  }
}

async function sendPlayerTransport(action) {
  if (!activeDeviceId) return;
  try {
    await fetch("/api/player/transport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: activeDeviceId, action })
    });
    setTimeout(pollPlayerStatus, 400);
  } catch (err) {
    console.error("Transport error:", err);
  }
}

function togglePlayPause() {
  sendPlayerTransport(isPlaying ? "pause" : "resume");
}

function onVolumeInput(val) {
  document.getElementById("playerVolumeLabel").innerText = `${val}%`;
}

async function onVolumeChange(val) {
  if (!activeDeviceId) return;
  try {
    await fetch("/api/player/transport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: activeDeviceId, action: "volume", volume: parseInt(val, 10) })
    });
  } catch (err) {
    console.error("Volume error:", err);
  }
}

async function setSleepTimer(minutes) {
  if (!activeDeviceId) return;
  try {
    await fetch("/api/player/transport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: activeDeviceId, action: "sleep_timer", minutes })
    });
    alert(minutes > 0 ? `Bedtime sleep timer set for ${minutes} minutes.` : "Sleep timer cancelled.");
  } catch (err) {
    console.error("Sleep timer error:", err);
  }
}

function onScrubChange(pct) {
  // Seek position calculation
}

// -----------------------------------------------------------------------------
// TAB 2: Library Operations
// -----------------------------------------------------------------------------

async function loadLibrary() {
  if (!activeProfileId) return;
  try {
    const res = await fetch(`/api/library/profile/${activeProfileId}`);
    if (!res.ok) return;
    libraryItems = await res.json();
    populateSeriesFilter();
    renderLibraryGrid(libraryItems);
  } catch (err) {
    console.error("Library load error:", err);
  }
}

function populateSeriesFilter() {
  const seriesSet = new Set();
  libraryItems.forEach(item => {
    if (item.series) seriesSet.add(item.series);
    if (item.series_list) {
      item.series_list.forEach(s => { if (s.name) seriesSet.add(s.name); });
    }
  });

  const select = document.getElementById("librarySeriesSelect");
  select.innerHTML = "<option value=''>All Series</option>";
  Array.from(seriesSet).sort().forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.innerText = s;
    select.appendChild(opt);
  });
}

function filterLibraryGrid() {
  const q = document.getElementById("librarySearchInput").value.toLowerCase().trim();
  const seriesFilter = document.getElementById("librarySeriesSelect").value;

  const filtered = libraryItems.filter(item => {
    const title = (item.title || "").toLowerCase();
    const author = (item.author || "").toLowerCase();
    const matchesQ = !q || title.includes(q) || author.includes(q);

    let matchesSeries = true;
    if (seriesFilter) {
      const inPrimary = (item.series || "") === seriesFilter;
      const inList = item.series_list && item.series_list.some(s => s.name === seriesFilter);
      matchesSeries = inPrimary || inList;
    }
    return matchesQ && matchesSeries;
  });

  renderLibraryGrid(filtered);
}

function renderLibraryGrid(items) {
  const grid = document.getElementById("libraryGrid");
  grid.innerHTML = "";

  if (items.length === 0) {
    grid.innerHTML = "<p class='text-secondary' style='grid-column: 1/-1; text-align: center; padding: 30px;'>No audiobooks match your search.</p>";
    return;
  }

  items.forEach(item => {
    const card = document.createElement("div");
    card.className = "book-card";
    card.onclick = () => openBookModal(item);

    const thumbUrl = item.thumb || "/static/img/placeholder.png";
    const seriesText = item.series ? (item.sequence_display ? `${item.series} #${item.sequence_display}` : item.series) : "";

    card.innerHTML = `
      <div class="book-thumb">
        <img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(item.title)}" loading="lazy">
      </div>
      <div class="book-info">
        <div class="book-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
        <div class="book-author">${escapeHtml(item.author || "Unknown")}</div>
        ${seriesText ? `<span class="badge badge-info" style="font-size: 9px; margin-top: 4px; align-self: flex-start;">${escapeHtml(seriesText)}</span>` : ""}
      </div>
    `;
    grid.appendChild(card);
  });
}

function openBookModal(book) {
  activeBook = book;
  const modal = document.getElementById("bookModal");
  document.getElementById("bookModalThumb").src = book.thumb || "/static/img/placeholder.png";
  document.getElementById("bookModalBookTitle").innerText = book.title;
  document.getElementById("bookModalAuthor").innerText = book.author || "Audiobookshelf";

  const seriesEl = document.getElementById("bookModalSeries");
  if (book.series) {
    seriesEl.innerText = book.sequence_display ? `${book.series} #${book.sequence_display}` : book.series;
    seriesEl.style.display = "inline-block";
  } else {
    seriesEl.style.display = "none";
  }

  // Populate Profile Default indicator in delivery mode select
  const activeProf = currentProfiles[activeProfileId];
  const defMode = (activeProf && activeProf.default_playback_mode) ? activeProf.default_playback_mode : "streaming";
  document.getElementById("optProfileDefaultMode").innerText = defMode === "offline" ? "Offline (Cache)" : "Streaming (Instant)";
  document.getElementById("bookModalModeSelect").value = "default";

  modal.style.display = "flex";
}

function closeBookModal() {
  document.getElementById("bookModal").style.display = "none";
}

async function executeBookPlay() {
  if (!activeBook || !activeProfileId) return;
  const modeVal = document.getElementById("bookModalModeSelect").value;

  try {
    // 1. Assign book to profile primary card
    const res = await fetch("/api/cards/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_id: activeProfileId,
        abs_item_id: activeBook.id,
        mode: modeVal,
        title: activeBook.title,
        author: activeBook.author
      })
    });

    if (!res.ok) {
      alert("Failed to assign book to player card.");
      return;
    }
    const slot = await res.json();
    closeBookModal();

    // 2. Begin playback on active player device
    if (activeDeviceId && slot.yoto_card_id) {
      await fetch("/api/player/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: activeDeviceId,
          card_id: slot.yoto_card_id,
          chapter: 1
        })
      });
    }

    switchTab("player");
    setTimeout(pollPlayerStatus, 600);
  } catch (err) {
    console.error("Play error:", err);
  }
}

function openLinkToCardModal() {
  closeBookModal();
  const select = document.getElementById("targetSlotSelect");
  select.innerHTML = "";

  // Add profile card option
  const profOpt = document.createElement("option");
  profOpt.value = `profile:${activeProfileId}`;
  profOpt.innerText = `👶 Profile Primary Card (${currentProfiles[activeProfileId]?.display_name || activeProfileId})`;
  select.appendChild(profOpt);

  // Add fleet card options
  cardSlots.forEach(s => {
    if (s.kind !== "profile_primary") {
      const opt = document.createElement("option");
      opt.value = `slot:${s.slot_id}`;
      opt.innerText = `💳 ${s.title || s.slot_id} (${s.slot_id})`;
      select.appendChild(opt);
    }
  });

  document.getElementById("linkCardModal").style.display = "flex";
}

function closeLinkCardModal() {
  document.getElementById("linkCardModal").style.display = "none";
}

async function executeAssignToSlot() {
  const targetVal = document.getElementById("targetSlotSelect").value;
  if (!targetVal || !activeBook) return;

  const modeVal = document.getElementById("bookModalModeSelect").value;
  let payload = {
    abs_item_id: activeBook.id,
    mode: modeVal,
    title: activeBook.title,
    author: activeBook.author
  };

  if (targetVal.startsWith("profile:")) {
    payload.profile_id = targetVal.split(":")[1];
  } else {
    payload.slot_id = targetVal.split(":")[1];
  }

  try {
    const res = await fetch("/api/cards/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeLinkCardModal();
      alert(`Linked '${activeBook.title}' successfully!`);
      loadCards();
    } else {
      alert("Failed to assign book to card slot.");
    }
  } catch (err) {
    console.error("Assign error:", err);
  }
}

// -----------------------------------------------------------------------------
// TAB 3: Cards Inventory
// -----------------------------------------------------------------------------

async function loadCards() {
  try {
    const res = await fetch("/api/cards");
    if (!res.ok) return;
    cardSlots = await res.json();
    renderCardsList();
  } catch (err) {
    console.error("Cards load error:", err);
  }
}

function renderCardsList() {
  const profContainer = document.getElementById("profileCardsList");
  const fleetContainer = document.getElementById("fleetCardsList");
  profContainer.innerHTML = "";
  fleetContainer.innerHTML = "";

  const profileSlots = cardSlots.filter(s => s.kind === "profile_primary" || (s.slot_id && s.slot_id.startsWith("profile_")));
  const fleetSlots = cardSlots.filter(s => s.kind !== "profile_primary" && (!s.slot_id || !s.slot_id.startsWith("profile_")));

  if (profileSlots.length === 0) {
    profContainer.innerHTML = "<p class='text-secondary' style='font-size: 12px;'>No profile cards linked yet. Play a book from the Library to pair automatically.</p>";
  } else {
    profileSlots.forEach(s => profContainer.appendChild(createCardItemElement(s, true)));
  }

  if (fleetSlots.length === 0) {
    fleetContainer.innerHTML = "<p class='text-secondary' style='font-size: 12px;'>No fleet cards added yet. Click '+ Add Card Slot' above.</p>";
  } else {
    fleetSlots.forEach(s => fleetContainer.appendChild(createCardItemElement(s, false)));
  }
}

function createCardItemElement(slot, isProfile) {
  const el = document.createElement("div");
  el.className = "list-item-card";

  const modeBadge = slot.mode === "offline"
    ? '<span class="badge badge-warning" style="font-size: 10px;">💾 Offline (Cached)</span>'
    : '<span class="badge badge-info" style="font-size: 10px;">⚡ Streaming</span>';

  const transcodeJob = slot.transcode;
  let progressHtml = "";
  if (transcodeJob && transcodeJob.status !== "ready") {
    const pct = Math.round((transcodeJob.progress || 0) * 100);
    progressHtml = `
      <div style="margin-top: 6px;">
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--accent-abs); margin-bottom: 2px;">
          <span>${transcodeJob.status} (${transcodeJob.done}/${transcodeJob.total} tracks)</span>
          <span>${pct}%</span>
        </div>
        <div style="height: 4px; background: rgba(0,0,0,0.3); border-radius: 2px; overflow: hidden;">
          <div style="width: ${pct}%; height: 100%; background: var(--accent-abs);"></div>
        </div>
      </div>
    `;
  }

  el.innerHTML = `
    <div class="list-item-thumb">
      ${slot.abs_item_id ? `<img src="/api/cover/${escapeHtml(slot.abs_item_id)}" alt="Cover" onerror="this.onerror=null;this.parentElement.innerText='💳'">` : '💳'}
    </div>
    <div class="list-item-body">
      <div class="list-item-title">${escapeHtml(slot.title || slot.slot_id)}</div>
      <div class="list-item-desc">${escapeHtml(slot.author || "Make-Your-Own NFC Card")}</div>
      <div class="list-item-tags">
        ${modeBadge}
        ${slot.is_pinned ? '<span class="badge badge-success" style="font-size: 10px;">📌 Pinned</span>' : ''}
        ${slot.speed && slot.speed !== 1.0 ? `<span class="badge" style="font-size: 10px;">${slot.speed}x</span>` : ''}
      </div>
      ${progressHtml}
    </div>
    <div style="display: flex; flex-direction: column; gap: 4px; align-items: flex-end;">
      <button class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 3px 8px;" onclick="toggleCardPin('${escapeHtml(slot.slot_id)}', ${!slot.is_pinned})">${slot.is_pinned ? "Unpin" : "📌 Pin"}</button>
      ${!isProfile ? `<button class="btn btn-danger btn-sm" style="font-size: 11px; padding: 3px 8px;" onclick="deleteCardSlot('${escapeHtml(slot.slot_id)}')">Delete</button>` : ''}
    </div>
  `;
  return el;
}

async function toggleCardPin(slotId, pinState) {
  try {
    await fetch(`/api/cards/${slotId}/pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_pinned: pinState })
    });
    loadCards();
  } catch (err) {
    console.error("Pin error:", err);
  }
}

async function deleteCardSlot(slotId) {
  if (!confirm(`Delete card slot '${slotId}'?`)) return;
  try {
    await fetch(`/api/cards/${slotId}`, { method: "DELETE" });
    loadCards();
  } catch (err) {
    console.error("Delete slot error:", err);
  }
}

function openAddCardModal() {
  document.getElementById("newSlotId").value = "";
  document.getElementById("newSlotTitle").value = "";
  document.getElementById("addCardModal").style.display = "flex";
}

function closeAddCardModal() {
  document.getElementById("addCardModal").style.display = "none";
}

async function executeCreateCardSlot() {
  const slotId = document.getElementById("newSlotId").value.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_");
  const title = document.getElementById("newSlotTitle").value.trim();
  if (!slotId) return alert("Slot ID is required");

  try {
    const res = await fetch("/api/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot_id: slotId, title: title || slotId, kind: "permanent_myo" })
    });
    if (res.ok) {
      closeAddCardModal();
      loadCards();
    } else {
      alert("Failed to create card slot");
    }
  } catch (err) {
    console.error("Create card error:", err);
  }
}

// -----------------------------------------------------------------------------
// TAB 4: Playlists Operations
// -----------------------------------------------------------------------------

async function loadPlaylists() {
  try {
    const res = await fetch("/api/yoto/playlists");
    if (!res.ok) return;
    cloudPlaylists = await res.json();
    updatePlaylistCounts();
    renderPlaylistsList();
  } catch (err) {
    console.error("Playlists load error:", err);
  }
}

function updatePlaylistCounts() {
  document.getElementById("countAll").innerText = cloudPlaylists.length;
  document.getElementById("countBroker").innerText = cloudPlaylists.filter(p => p.source === "broker").length;
  document.getElementById("countCustom").innerText = cloudPlaylists.filter(p => p.source === "custom").length;
  document.getElementById("countPinned").innerText = cloudPlaylists.filter(p => p.is_pinned).length;
}

function setPlaylistFilter(filter) {
  currentPlaylistFilter = filter;
  document.querySelectorAll("#tabPlaylists .btn-sm").forEach(b => {
    b.classList.remove("btn-primary");
    b.classList.add("btn-secondary");
  });
  const chip = document.getElementById(`chip${filter.charAt(0).toUpperCase() + filter.slice(1)}`);
  if (chip) {
    chip.classList.remove("btn-secondary");
    chip.classList.add("btn-primary");
  }
  renderPlaylistsList();
}

function renderPlaylistsList() {
  const container = document.getElementById("playlistsList");
  container.innerHTML = "";

  const filtered = cloudPlaylists.filter(p => {
    if (currentPlaylistFilter === "broker") return p.source === "broker";
    if (currentPlaylistFilter === "custom") return p.source === "custom";
    if (currentPlaylistFilter === "pinned") return p.is_pinned;
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = "<p class='text-secondary' style='text-align: center; padding: 24px;'>No playlists found.</p>";
    return;
  }

  filtered.forEach(p => {
    const card = document.createElement("div");
    card.className = "list-item-card";

    const sourceBadge = p.source === "broker"
      ? '<span class="badge badge-info" style="font-size: 10px;">📻 StoryDeck</span>'
      : '<span class="badge badge-subtle" style="font-size: 10px;">🎵 Custom</span>';

    const modeBadge = p.mode === "offline"
      ? '<span class="badge badge-warning" style="font-size: 10px;">💾 Offline</span>'
      : '<span class="badge badge-info" style="font-size: 10px;">⚡ Stream</span>';

    card.innerHTML = `
      <div class="list-item-thumb">
        ${p.cover_url ? `<img src="${escapeHtml(p.cover_url)}" alt="Cover" onerror="this.onerror=null;this.parentElement.innerText='🎵'">` : '🎵'}
      </div>
      <div class="list-item-body">
        <div class="list-item-title">${escapeHtml(p.title)}</div>
        <div class="list-item-desc">${escapeHtml(p.author || "Yoto Playlist")} • ${p.chapters_count || 1} chapter(s)</div>
        <div class="list-item-tags">
          ${sourceBadge}
          ${modeBadge}
          ${p.is_physical ? '<span class="badge" style="font-size: 10px;">Physical MYO</span>' : ''}
          ${p.is_pinned ? '<span class="badge badge-success" style="font-size: 10px;">📌 Pinned</span>' : ''}
        </div>
      </div>
      <div style="display: flex; flex-direction: column; gap: 4px; align-items: flex-end;">
        <button class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 3px 8px;" onclick="togglePlaylistPin('${escapeHtml(p.card_id)}', ${!p.is_pinned})">${p.is_pinned ? "Unpin" : "📌 Pin"}</button>
        <button class="btn btn-danger btn-sm" style="font-size: 11px; padding: 3px 8px;" onclick="deleteCloudPlaylist('${escapeHtml(p.card_id)}', '${escapeHtml(p.title)}')">🗑️</button>
      </div>
    `;
    container.appendChild(card);
  });
}

async function togglePlaylistPin(cardId, pinState) {
  try {
    await fetch(`/api/yoto/playlists/${cardId}/pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_pinned: pinState })
    });
    loadPlaylists();
  } catch (err) {
    console.error("Playlist pin error:", err);
  }
}

async function deleteCloudPlaylist(cardId, title) {
  if (!confirm(`Permanently delete playlist '${title}' from Yoto Cloud?`)) return;
  try {
    const res = await fetch(`/api/yoto/playlists/${cardId}`, { method: "DELETE" });
    if (res.ok) {
      loadPlaylists();
    } else {
      alert("Failed to delete playlist from Yoto Cloud.");
    }
  } catch (err) {
    console.error("Delete playlist error:", err);
  }
}

async function triggerManualPrune() {
  if (!confirm("Run automated LRU cache pruner now? This removes evicted profile caches while preserving pinned and physical cards.")) return;
  try {
    const res = await fetch("/api/yoto/playlists/prune", { method: "POST" });
    if (res.ok) {
      const result = await res.json();
      alert(`Pruning complete: Evicted ${result.pruned_count} cached playlist(s).`);
      loadPlaylists();
    } else {
      alert("Pruning failed.");
    }
  } catch (err) {
    console.error("Prune error:", err);
  }
}

// -----------------------------------------------------------------------------
// Utilities
// -----------------------------------------------------------------------------

function formatSeconds(secs) {
  const s = Math.floor(secs || 0);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem < 10 ? '0' : ''}${rem}`;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
