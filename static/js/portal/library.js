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

async function openBookModal(book) {
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

  // Reset and fetch book details (synopsis & chapters)
  const synContainer = document.getElementById("bookModalSynopsisContainer");
  const synText = document.getElementById("bookModalSynopsis");
  const durBadge = document.getElementById("bookModalDurationBadge");
  const chapSelect = document.getElementById("bookModalChapterSelect");
  if (synContainer) synContainer.style.display = "none";
  if (durBadge) durBadge.style.display = "none";
  if (chapSelect) chapSelect.innerHTML = `<option value="1">Chapter 1</option>`;

  modal.style.display = "flex";

  try {
    const res = await fetch(`/api/library/book/${encodeURIComponent(book.id)}/details`);
    if (res.ok) {
      const details = await res.json();
      if (details.description && synContainer && synText) {
        synText.innerText = details.description.replace(/<[^>]*>/g, "");
        synContainer.style.display = "block";
      }
      if (details.total_duration && durBadge) {
        const hrs = Math.floor(details.total_duration / 3600);
        const mins = Math.round((details.total_duration % 3600) / 60);
        durBadge.innerText = hrs > 0 ? `⏱️ ${hrs}h ${mins}m` : `⏱️ ${mins}m`;
        durBadge.style.display = "inline-block";
      }
      if (Array.isArray(details.tracks) && details.tracks.length > 0 && chapSelect) {
        chapSelect.innerHTML = "";
        details.tracks.forEach((tr, idx) => {
          const chNum = tr.index || (idx + 1);
          const durStr = tr.duration ? ` (${formatSeconds(tr.duration)})` : "";
          const opt = document.createElement("option");
          opt.value = String(chNum);
          opt.innerText = `${chNum}. ${tr.title || "Chapter " + chNum}${durStr}`;
          chapSelect.appendChild(opt);
        });
      }
    }
  } catch (err) {
    console.error("Book details fetch error:", err);
  }
}

function closeBookModal() {
  document.getElementById("bookModal").style.display = "none";
}

async function executeBookPlay() {
  if (!activeBook) return;
  const modeVal = document.getElementById("bookModalModeSelect").value;
  const chapVal = parseInt(document.getElementById("bookModalChapterSelect")?.value || "1", 10) || 1;
  const targetProfId = (activeProfileId && activeProfileId !== "__all__") ? activeProfileId : Object.keys(currentProfiles)[0];
  if (!targetProfId) return;

  try {
    // 1. Assign book to profile primary card
    const res = await fetch("/api/cards/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_id: targetProfId,
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
          chapter: chapVal
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

