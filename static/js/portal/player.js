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
    const modeBadge = document.getElementById("playerModeBadge");
    const attachedCardTag = document.getElementById("playerAttachedCardTag");
    const attachedCardText = document.getElementById("playerAttachedCardText");

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

      // Update Mode Badge & Attached Playlist Tag
      if (data.has_attached_playlist || data.card_id || data.playback_mode === "offline") {
        if (modeBadge) {
          modeBadge.innerText = data.playback_mode === "offline" ? "💾 Attached Offline" : "💾 Attached Playlist";
          modeBadge.style.borderColor = "var(--accent-yoto)";
          modeBadge.style.color = "var(--accent-yoto)";
        }
        if (attachedCardTag && attachedCardText) {
          attachedCardTag.style.display = "block";
          const cardRef = data.card_id ? `Card: ${data.card_id}` : (data.slot_id ? `Slot: ${data.slot_id}` : "MYO Card");
          attachedCardText.innerText = `💳 Attached Playlist (${cardRef})`;
        }
      } else if (data.playback_mode === "retail") {
        if (modeBadge) {
          modeBadge.innerText = "💿 Retail Card";
          modeBadge.style.borderColor = "var(--accent-info)";
          modeBadge.style.color = "var(--accent-info)";
        }
        if (attachedCardTag && attachedCardText) {
          attachedCardTag.style.display = "block";
          attachedCardText.innerText = `💿 Yoto Retail Card (${data.card_id || data.item_id})`;
        }
      } else {
        if (modeBadge) {
          modeBadge.innerText = "⚡ Streaming";
          modeBadge.style.borderColor = "var(--border-subtle)";
          modeBadge.style.color = "var(--text-primary)";
        }
        if (attachedCardTag) attachedCardTag.style.display = "none";
      }
    } else if (data) {
      if (titleEl) titleEl.innerText = "No Active Playback";
      if (subEl) {
        subEl.innerText = data.name ? `${data.name} · ${data.online ? "Online" : "Offline"}` : "Select an audiobook from Library";
      }
      if (coverEl) {
        coverEl.src = "https://raw.githubusercontent.com/advplyr/audiobookshelf/master/client/static/Logo.png";
      }
      if (attachedCardTag) attachedCardTag.style.display = "none";
      if (modeBadge) {
        modeBadge.innerText = "⚡ Streaming";
        modeBadge.style.borderColor = "var(--border-subtle)";
        modeBadge.style.color = "var(--text-primary)";
      }
    }

    if (data && data.playback) {
      isPlaying = data.playback.state === "playing" || Boolean(data.is_playing);
      const playBtn = document.getElementById("btnPlayPause");
      if (playBtn) playBtn.innerText = isPlaying ? "⏸️" : "▶️";

      currentPosition = data.playback.position || data.position || 0;
      currentDuration = data.playback.duration || data.duration || 1;
      if (!isScrubbing) {
        const pct = currentDuration > 0 ? Math.min(100, (currentPosition / currentDuration) * 100) : 0;
        const scrubBar = document.getElementById("playerScrubBar");
        if (scrubBar) scrubBar.value = pct;
        const elElapsed = document.getElementById("playerTimeElapsed");
        if (elElapsed) elElapsed.innerText = formatSeconds(currentPosition);
        const elRem = document.getElementById("playerTimeRemaining");
        if (elRem) elRem.innerText = `-${formatSeconds(Math.max(0, currentDuration - currentPosition))}`;
      }
    }

    // Sync Playback Speed Select
    if (data && data.speed) {
      const speedSel = document.getElementById("playerSpeedSelect");
      if (speedSel) {
        const speedStr = String(parseFloat(data.speed));
        if (Array.from(speedSel.options).some(o => o.value === speedStr)) {
          speedSel.value = speedStr;
        }
      }
    }

    // Render Player Telemetry Badges (Online/Offline, Day/Night, Battery, Sleep Timer)
    const badgesEl = document.getElementById("playerTelemetryBadges");
    if (badgesEl && data) {
      const pills = [];
      pills.push(data.online
        ? `<span class="badge badge-success" style="font-size: 10px;">🟢 Online</span>`
        : `<span class="badge badge-subtle" style="font-size: 10px;">⚪ Offline</span>`);
      if (data.day_mode !== undefined && data.day_mode !== null) {
        pills.push(data.day_mode === 0
          ? `<span class="badge badge-info" style="font-size: 10px;">🌙 Night Mode</span>`
          : `<span class="badge badge-warning" style="font-size: 10px;">☀️ Day Mode</span>`);
      }
      if (data.battery !== undefined && data.battery !== null) {
        pills.push(`<span class="badge badge-subtle" style="font-size: 10px;">${data.charging ? '⚡' : '🔋'} ${data.battery}%</span>`);
      }
      if (data.sleep_timer_remaining && data.sleep_timer_remaining > 0) {
        const minsLeft = Math.ceil(data.sleep_timer_remaining / 60);
        pills.push(`<span class="badge badge-warning" style="font-size: 10px;">⏲️ Sleep: ${minsLeft}m</span>`);
      }
      badgesEl.innerHTML = pills.join("");
    }
    const sleepLabel = document.getElementById("sleepTimerStatusLabel");
    if (sleepLabel) {
      if (data && data.sleep_timer_remaining && data.sleep_timer_remaining > 0) {
        const minsLeft = Math.ceil(data.sleep_timer_remaining / 60);
        sleepLabel.innerText = `🌙 Bedtime Sleep Timer (Active: ${minsLeft}m remaining)`;
      } else {
        sleepLabel.innerText = "🌙 Bedtime Sleep Timer";
      }
    }

    // Volume with Ceiling Clamp Enforcement
    currentVolumeMax = (data && data.volume_max != null) ? parseInt(data.volume_max, 10) : 100;
    if (data && data.volume !== undefined) {
      const volSlider = document.getElementById("playerVolumeSlider");
      if (volSlider) {
        volSlider.max = currentVolumeMax;
        volSlider.value = Math.min(currentVolumeMax, data.volume);
      }
      const volLabel = document.getElementById("playerVolumeLabel");
      if (volLabel) {
        const val = volSlider ? volSlider.value : data.volume;
        volLabel.innerText = currentVolumeMax < 100 ? `${val}% (Limit: ${currentVolumeMax}%)` : `${val}%`;
      }
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
  let v = parseInt(val, 10);
  if (v > currentVolumeMax) {
    v = currentVolumeMax;
    const slider = document.getElementById("playerVolumeSlider");
    if (slider) slider.value = v;
  }
  const label = document.getElementById("playerVolumeLabel");
  if (label) {
    label.innerText = currentVolumeMax < 100 ? `${v}% (Limit: ${currentVolumeMax}%)` : `${v}%`;
  }
}

async function onVolumeChange(val) {
  if (!activeDeviceId) return;
  let v = parseInt(val, 10);
  if (v > currentVolumeMax) {
    v = currentVolumeMax;
    const slider = document.getElementById("playerVolumeSlider");
    if (slider) slider.value = v;
  }
  try {
    const res = await fetch("/api/player/transport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: activeDeviceId, action: "volume", volume: v })
    });
    if (res.ok) {
      const resp = await res.json();
      if (resp.volume !== undefined) {
        const slider = document.getElementById("playerVolumeSlider");
        if (slider) slider.value = resp.volume;
        const label = document.getElementById("playerVolumeLabel");
        if (label) {
          label.innerText = currentVolumeMax < 100 ? `${resp.volume}% (Limit: ${currentVolumeMax}%)` : `${resp.volume}%`;
        }
      }
    }
  } catch (err) {
    console.error("Volume error:", err);
  }
}

async function setSleepTimer(minutes) {
  if (!activeDeviceId) return;
  try {
    const res = await fetch("/api/player/transport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: activeDeviceId, action: "sleep_timer", minutes })
    });
    if (res.ok) {
      await pollPlayerStatus();
    }
  } catch (err) {
    console.error("Sleep timer error:", err);
  }
}

function onScrubInput(pct) {
  isScrubbing = true;
  if (currentDuration > 0) {
    const targetSec = Math.round((parseFloat(pct) / 100) * currentDuration);
    const elElapsed = document.getElementById("playerTimeElapsed");
    if (elElapsed) elElapsed.innerText = formatSeconds(targetSec);
    const elRem = document.getElementById("playerTimeRemaining");
    if (elRem) elRem.innerText = `-${formatSeconds(Math.max(0, currentDuration - targetSec))}`;
  }
}

async function onScrubChange(pct) {
  isScrubbing = false;
  if (!activeDeviceId || currentDuration <= 0) return;
  const targetSec = Math.round((parseFloat(pct) / 100) * currentDuration);
  try {
    await fetch("/api/player/transport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: activeDeviceId, action: "seek", position: targetSec })
    });
    setTimeout(pollPlayerStatus, 400);
  } catch (err) {
    console.error("Seek error:", err);
  }
}

async function onPlayerSpeedChange(speedVal) {
  if (!activeDeviceId) return;
  const speed = parseFloat(speedVal);
  if (isNaN(speed)) return;
  try {
    await fetch("/api/player/transport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: activeDeviceId, action: "speed", speed })
    });
    setTimeout(pollPlayerStatus, 400);
  } catch (err) {
    console.error("Speed change error:", err);
  }
}

async function loadContinueListening() {
  const container = document.getElementById("continueListeningList");
  if (!container) return;
  try {
    const scope = activeProfileId || "__all__";
    const res = await fetch(`/api/library/recent/${encodeURIComponent(scope)}`);
    if (!res.ok) return;
    const recentItems = await res.json();
    container.innerHTML = "";
    if (!recentItems || recentItems.length === 0) {
      container.innerHTML = "<p class='text-secondary' style='font-size: 11px; margin: 0;'>No recent playback history yet. Start a book from the Library tab.</p>";
      return;
    }
    recentItems.forEach(item => {
      const card = document.createElement("div");
      card.className = "list-item-card";
      const thumbUrl = item.thumb || "/static/img/placeholder.png";
      card.innerHTML = `
        <div class="list-item-thumb">
          <img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(item.title)}" onerror="this.onerror=null;this.parentElement.innerText='📖'">
        </div>
        <div class="list-item-body">
          <div class="list-item-title">${escapeHtml(item.title)}</div>
          <div class="list-item-desc">${escapeHtml(item.author || "Audiobook")}${item.series ? ` • ${escapeHtml(item.series)}` : ""}</div>
        </div>
        <div>
          <button class="btn btn-primary btn-sm" style="font-size: 11px; padding: 4px 10px;" onclick='openBookModal(${JSON.stringify(item).replace(/'/g, "&#39;")})'>▶️ Resume</button>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Failed to load recent items:", err);
  }
}

