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

