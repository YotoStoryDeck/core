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
    : (slot.mode === "retail"
        ? '<span class="badge badge-success" style="font-size: 10px;">💿 Official Yoto</span>'
        : '<span class="badge badge-info" style="font-size: 10px;">⚡ Streaming</span>');

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

  const curSpeed = parseFloat(slot.speed || 1.0);
  const nextMode = slot.mode === "offline" ? "streaming" : "offline";
  const nextModeLabel = slot.mode === "offline" ? "⚡ Stream" : "💾 Make Offline";

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
        ${slot.own_place ? '<span class="badge badge-info" style="font-size: 10px;">📍 Own Place</span>' : '<span class="badge badge-subtle" style="font-size: 10px;">🔗 ABS Synced</span>'}
      </div>
      <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; align-items: center;">
        <select class="form-control" style="width: 68px; font-size: 10px; padding: 2px 4px; height: 24px;" onchange="changeCardSpeed('${escapeHtml(slot.slot_id)}', this.value)" title="Slot Playback Speed">
          <option value="0.75" ${curSpeed === 0.75 ? 'selected' : ''}>0.75x</option>
          <option value="1" ${curSpeed === 1.0 ? 'selected' : ''}>1.0x</option>
          <option value="1.25" ${curSpeed === 1.25 ? 'selected' : ''}>1.25x</option>
          <option value="1.5" ${curSpeed === 1.5 ? 'selected' : ''}>1.5x</option>
          <option value="2" ${curSpeed === 2.0 ? 'selected' : ''}>2.0x</option>
        </select>
        <button class="btn btn-secondary btn-sm" style="font-size: 10px; padding: 2px 6px;" onclick="toggleCardOwnPlace('${escapeHtml(slot.slot_id)}', ${!slot.own_place})" title="Toggle Own-Place Progress Isolation">
          ${slot.own_place ? "🔗 Sync ABS" : "📍 Own Place"}
        </button>
        ${slot.abs_item_id ? `<button class="btn btn-secondary btn-sm" style="font-size: 10px; padding: 2px 6px;" onclick="switchCardDeliveryMode('${escapeHtml(slot.slot_id)}', '${nextMode}')">${nextModeLabel}</button>` : ''}
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

async function changeCardSpeed(slotId, speedVal) {
  try {
    await fetch(`/api/cards/${encodeURIComponent(slotId)}/speed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speed: parseFloat(speedVal) })
    });
    loadCards();
  } catch (err) {
    console.error("Card speed error:", err);
  }
}

async function toggleCardOwnPlace(slotId, ownPlaceState) {
  try {
    await fetch(`/api/cards/${encodeURIComponent(slotId)}/own-place`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ own_place: ownPlaceState })
    });
    loadCards();
  } catch (err) {
    console.error("Own-place toggle error:", err);
  }
}

async function switchCardDeliveryMode(slotId, mode) {
  try {
    const res = await fetch(`/api/cards/${encodeURIComponent(slotId)}/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode })
    });
    if (res.ok) {
      loadCards();
    } else {
      const errData = await res.json();
      alert(errData.error || "Failed to switch card delivery mode.");
    }
  } catch (err) {
    console.error("Mode switch error:", err);
  }
}

async function loadHouseholdYotoCards() {
  try {
    const res = await fetch("/api/library/yoto");
    if (!res.ok) return;
    householdYotoCards = await res.json();
    const sel = document.getElementById("newSlotYotoCardSelect");
    if (sel) {
      sel.innerHTML = `<option value="">-- Leave Empty / Assign Audiobook Later --</option>`;
      householdYotoCards.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c.yoto_card_id || c.id;
        opt.innerText = `💿 ${c.title}${c.author ? " (" + c.author + ")" : ""}`;
        sel.appendChild(opt);
      });
    }
  } catch (err) {
    console.error("Failed to load household Yoto cards:", err);
  }
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
  const sel = document.getElementById("newSlotYotoCardSelect");
  if (sel) sel.value = "";
  loadHouseholdYotoCards();
  document.getElementById("addCardModal").style.display = "flex";
}

function closeAddCardModal() {
  document.getElementById("addCardModal").style.display = "none";
}

async function executeCreateCardSlot() {
  const slotId = document.getElementById("newSlotId").value.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_");
  const title = document.getElementById("newSlotTitle").value.trim();
  const yotoCardId = document.getElementById("newSlotYotoCardSelect")?.value || "";
  if (!slotId) return alert("Slot ID is required");

  try {
    const res = await fetch("/api/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot_id: slotId, title: title || slotId, kind: "permanent_myo" })
    });
    if (res.ok) {
      if (yotoCardId) {
        const matched = householdYotoCards.find(c => (c.yoto_card_id || c.id) === yotoCardId);
        await fetch("/api/cards/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            slot_id: slotId,
            yoto_card_id: yotoCardId,
            title: title || (matched ? matched.title : slotId),
            author: matched ? matched.author : "Official Yoto Card",
            mode: "retail"
          })
        });
      }
      closeAddCardModal();
      loadCards();
    } else {
      alert("Failed to create card slot");
    }
  } catch (err) {
    console.error("Create card error:", err);
  }
}

