// ============================================================================
// Interactive Icon Search & Multi-Track Studio Modal
// ============================================================================

let currentChosenArtwork = null; // { url, name, b64, file }

function switchIconPickerTab(tabName) {
  const btnSearch = document.getElementById("btnIconTabSearch");
  const btnUpload = document.getElementById("btnIconTabUpload");
  const secSearch = document.getElementById("iconPickerSectionSearch");
  const secUpload = document.getElementById("iconPickerSectionUpload");

  if (tabName === "search") {
    btnSearch.className = "btn btn-sm btn-primary";
    btnUpload.className = "btn btn-sm btn-secondary";
    secSearch.style.display = "block";
    secUpload.style.display = "none";
  } else {
    btnSearch.className = "btn btn-sm btn-secondary";
    btnUpload.className = "btn btn-sm btn-primary";
    secSearch.style.display = "none";
    secUpload.style.display = "block";
  }
}

function openIconPickerForTrack(trackIndex) {
  activePickerTrackIndex = trackIndex;
  const modal = document.getElementById("iconPickerModal");
  const track = currentTracklistMedia && currentTracklistMedia.tracks ? currentTracklistMedia.tracks.find(t => t.index === trackIndex) : null;
  const trackTitle = track ? track.title : `Track ${trackIndex + 1}`;

  document.getElementById("iconPickerSubtitle").innerText =
    `Choose artwork or 16×16 pixel art for: "${trackTitle}"`;

  // Pre-fill labels
  document.getElementById("iconScopeSingleLabel").innerText = `Current Track Only (#${trackIndex + 1}: ${trackTitle})`;
  document.getElementById("iconScopeRemainingLabel").innerText = `From Track #${trackIndex + 1} to End of Book (${currentTracklistMedia.tracks.length - trackIndex} tracks)`;

  // Reset chosen artwork banner and canvas
  clearChosenIcon();
  switchIconPickerTab("search");

  // Reset inputs
  const fileInput = document.getElementById("iconFileInput");
  if (fileInput) fileInput.value = "";
  const urlInput = document.getElementById("iconUrlInput");
  if (urlInput) urlInput.value = "";
  const overlayCheckbox = document.getElementById("iconOverlayCheckbox");
  if (overlayCheckbox) overlayCheckbox.checked = false;
  toggleOverlayOption(false);

  // Default radio scope
  const singleRadio = document.querySelector('input[name="iconTargetScope"][value="single"]');
  if (singleRadio) singleRadio.checked = true;
  onIconScopeChange("single");

  // Render custom checkboxes list
  renderCustomTrackCheckboxes(trackIndex);

  // Pre-fill search query with clean chapter title
  const cleanQ = trackTitle.replace(/^(?:Chapter|Track|Part|Book)\s*\d+[:.\s-]*/i, "").trim() || trackTitle;
  document.getElementById("iconSearchInput").value = cleanQ;

  modal.style.display = "flex";
  executeIconSearch();
}

function renderCustomTrackCheckboxes(initialTrackIndex) {
  const container = document.getElementById("iconCustomTrackList");
  if (!container || !currentTracklistMedia || !currentTracklistMedia.tracks) return;

  container.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid var(--border-subtle);">
      <span style="font-size: 11px; color: var(--text-muted);">Select specific tracks:</span>
      <div style="display: flex; gap: 6px;">
        <button type="button" class="btn btn-secondary btn-sm" style="font-size: 10px; padding: 1px 6px;" onclick="setAllCustomTrackCheckboxes(true)">All</button>
        <button type="button" class="btn btn-secondary btn-sm" style="font-size: 10px; padding: 1px 6px;" onclick="setAllCustomTrackCheckboxes(false)">None</button>
      </div>
    </div>
  `;

  currentTracklistMedia.tracks.forEach(tr => {
    const isChecked = tr.index === initialTrackIndex;
    const label = document.createElement("label");
    label.style.display = "flex";
    label.style.alignItems = "center";
    label.style.gap = "6px";
    label.style.fontSize = "11px";
    label.style.padding = "2px 0";
    label.style.cursor = "pointer";

    label.innerHTML = `
      <input type="checkbox" class="custom-track-chk" value="${tr.index}" ${isChecked ? "checked" : ""}>
      <span style="color: var(--text-muted); min-width: 22px;">#${tr.track_number}</span>
      <span style="color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(tr.title)}</span>
    `;
    container.appendChild(label);
  });
}

function setAllCustomTrackCheckboxes(checked) {
  document.querySelectorAll(".custom-track-chk").forEach(chk => chk.checked = checked);
}

function onIconScopeChange(scope) {
  const customList = document.getElementById("iconCustomTrackList");
  if (customList) {
    customList.style.display = (scope === "custom") ? "block" : "none";
  }
}

function toggleOverlayOption(enabled) {
  const wrapper = document.getElementById("iconOverlayCornerWrapper");
  if (wrapper) wrapper.style.display = enabled ? "flex" : "none";
  if (currentChosenArtwork) {
    drawCanvasPreview(currentChosenArtwork.url || currentChosenArtwork.b64);
  }
}

function closeIconPickerModal() {
  const modal = document.getElementById("iconPickerModal");
  if (modal) modal.style.display = "none";
  activePickerTrackIndex = null;
  currentChosenArtwork = null;
}

function searchIconTag(tag) {
  document.getElementById("iconSearchInput").value = tag;
  executeIconSearch();
}

async function executeIconSearch() {
  const query = document.getElementById("iconSearchInput").value.trim();
  const resultsContainer = document.getElementById("iconPickerResults");
  if (!query) {
    resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px;">Type a keyword above to search icons.</p>`;
    return;
  }

  resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px;">Searching YotoIcons & Tinker...</p>`;

  try {
    const res = await fetch(`/api/admin/icons/search?q=${encodeURIComponent(query)}&limit=30`);
    const data = await res.json();
    if (!data.ok || !data.results || data.results.length === 0) {
      resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px;">No icons found for "${escapeHtml(query)}". Try another word.</p>`;
      return;
    }

    resultsContainer.innerHTML = "";
    data.results.forEach(icon => {
      const tile = document.createElement("div");
      tile.style.background = "var(--bg-base)";
      tile.style.border = "1px solid var(--border-subtle)";
      tile.style.borderRadius = "8px";
      tile.style.padding = "8px 6px";
      tile.style.display = "flex";
      tile.style.flexDirection = "column";
      tile.style.alignItems = "center";
      tile.style.cursor = "pointer";
      tile.style.transition = "transform 0.15s, border-color 0.15s, background 0.15s";
      tile.title = `${icon.name} (${icon.source})`;

      tile.onmouseover = () => {
        tile.style.borderColor = "var(--accent-yoto)";
        tile.style.background = "rgba(229, 53, 43, 0.08)";
        tile.style.transform = "translateY(-2px)";
      };
      tile.onmouseout = () => {
        tile.style.borderColor = "var(--border-subtle)";
        tile.style.background = "var(--bg-base)";
        tile.style.transform = "translateY(0)";
      };

      tile.onclick = () => selectIconForActiveTrack(icon);

      tile.innerHTML = `
        <img src="${escapeHtml(icon.url)}" style="width: 40px; height: 40px; image-rendering: pixelated; object-fit: contain; border-radius: 4px;" alt="${escapeHtml(icon.name)}">
        <span style="font-size: 10px; color: var(--text-primary); margin-top: 4px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; width: 100%; display: block;">${escapeHtml(icon.name)}</span>
        <span style="font-size: 9px; color: var(--text-muted);">${icon.source === "tinker" ? "Tinker" : "YotoIcons"}</span>
      `;
      resultsContainer.appendChild(tile);
    });
  } catch (err) {
    console.error("Error searching icons:", err);
    resultsContainer.innerHTML = `<p class="text-secondary" style="grid-column: 1 / -1; text-align: center; padding: 20px; color: var(--accent-danger);">Network error searching icons.</p>`;
  }
}

// ----------------------------------------------------------------------------
// File and URL Handling with 16x16 Canvas Downscaling
// ----------------------------------------------------------------------------

function handleIconFileSelected(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    const b64 = e.target.result;
    setChosenArtwork({
      name: file.name,
      b64: b64,
      file: file,
      source: "Uploaded PC File"
    });
    drawCanvasPreview(b64);
  };
  reader.readAsDataURL(file);
}

function handleIconUrlInput(url) {
  url = url.trim();
  if (!url) return;

  setChosenArtwork({
    name: "Web Image",
    url: url,
    source: "Web URL"
  });
  drawCanvasPreview(url);
}

function setChosenArtwork(art) {
  currentChosenArtwork = art;
  const banner = document.getElementById("iconPickerChosenBanner");
  const thumb = document.getElementById("iconPickerChosenThumb");
  const title = document.getElementById("iconPickerChosenTitle");
  const source = document.getElementById("iconPickerChosenSource");

  thumb.src = art.url || art.b64;
  title.innerText = art.name || "Selected Artwork";
  source.innerText = art.source || "Ready to apply";
  banner.style.display = "flex";
}

function clearChosenIcon() {
  currentChosenArtwork = null;
  const banner = document.getElementById("iconPickerChosenBanner");
  if (banner) banner.style.display = "none";
  const canvas = document.getElementById("iconUploadCanvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, 16, 16);
  }
}

function drawCanvasPreview(imgSrc) {
  const canvas = document.getElementById("iconUploadCanvas");
  if (!canvas || !imgSrc) return;
  const ctx = canvas.getContext("2d");

  // If imgSrc is a remote web URL (starts with http/https), route through our local thumbnail proxy
  // to avoid browser CORS policy blocking direct canvas rendering.
  let targetSrc = imgSrc;
  if (imgSrc.startsWith("http://") || imgSrc.startsWith("https://")) {
    targetSrc = `/api/thumb?type=yoto&url=${encodeURIComponent(imgSrc)}`;
  }

  const img = new Image();
  img.onload = () => {
    ctx.clearRect(0, 0, 16, 16);
    // Center crop square
    const minDim = Math.min(img.width, img.height);
    const sx = (img.width - minDim) / 2;
    const sy = (img.height - minDim) / 2;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, sx, sy, minDim, minDim, 0, 0, 16, 16);

    // If overlay is checked, simulate tiny corner number
    const overlayCheckbox = document.getElementById("iconOverlayCheckbox");
    if (overlayCheckbox && overlayCheckbox.checked) {
      ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
      ctx.fillRect(10, 0, 6, 5);
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 5px sans-serif";
      ctx.fillText("#", 11, 4);
    }
  };
  img.onerror = () => {
    console.warn("Failed to load image preview for:", imgSrc);
  };
  img.src = targetSrc;
}

function selectIconForActiveTrack(icon) {
  // Sets community icon as chosen artwork and draws canvas preview
  setChosenArtwork({
    name: icon.name,
    url: icon.url,
    source: icon.source === "tinker" ? "Tinker Icons" : "YotoIcons"
  });
  drawCanvasPreview(icon.url);
}

// ----------------------------------------------------------------------------
// Batch Multi-Track Artwork Dispatch
// ----------------------------------------------------------------------------

async function applyArtworkToTargets() {
  if (!currentChosenArtwork || !currentTracklistMedia) {
    showToast("Please choose or upload an icon first", true);
    return;
  }

  const mediaId = currentTracklistMedia.id;
  const mediaType = currentTracklistMedia.type;
  const tracks = currentTracklistMedia.tracks || [];

  // Determine target track indices based on selected scope
  const scopeRadio = document.querySelector('input[name="iconTargetScope"]:checked');
  const scope = scopeRadio ? scopeRadio.value : "single";
  let targetIndices = [];

  if (scope === "single") {
    targetIndices = [activePickerTrackIndex !== null ? activePickerTrackIndex : 0];
  } else if (scope === "remaining") {
    const startIdx = activePickerTrackIndex !== null ? activePickerTrackIndex : 0;
    targetIndices = tracks.filter(t => t.index >= startIdx).map(t => t.index);
  } else if (scope === "all") {
    targetIndices = tracks.map(t => t.index);
  } else if (scope === "custom") {
    document.querySelectorAll(".custom-track-chk:checked").forEach(chk => {
      targetIndices.push(parseInt(chk.value, 10));
    });
  }

  if (targetIndices.length === 0) {
    showToast("No tracks selected to apply artwork", true);
    return;
  }

  const applyOverlay = document.getElementById("iconOverlayCheckbox").checked;
  const overlayCorner = document.getElementById("iconOverlayCornerSelect").value || "top-right";

  const btnApply = document.getElementById("btnApplyArtwork");
  btnApply.disabled = true;
  btnApply.innerText = "Applying...";

  try {
    let payload = {
      type: mediaType,
      track_indices: targetIndices,
      apply_overlay: applyOverlay,
      overlay_corner: overlayCorner
    };

    let fetchOptions = {};

    if (currentChosenArtwork.file) {
      // Multipart upload
      const formData = new FormData();
      formData.append("file", currentChosenArtwork.file);
      formData.append("type", mediaType);
      formData.append("track_indices", JSON.stringify(targetIndices));
      formData.append("apply_overlay", applyOverlay ? "true" : "false");
      formData.append("overlay_corner", overlayCorner);

      fetchOptions = {
        method: "POST",
        body: formData
      };
    } else {
      // JSON payload (URL or base64)
      if (currentChosenArtwork.b64) {
        payload.image_b64 = currentChosenArtwork.b64;
      } else {
        payload.icon_url = currentChosenArtwork.url;
      }

      fetchOptions = {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      };
    }

    const res = await fetch(`/api/admin/media/${encodeURIComponent(mediaId)}/tracks/batch-icon`, fetchOptions);
    const data = await res.json();

    if (data.ok) {
      // Update client model rows
      const iconUrl = currentChosenArtwork.url || currentChosenArtwork.b64;
      const nowTs = Date.now();
      targetIndices.forEach(idx => {
        const tr = tracks.find(t => t.index === idx);
        if (tr) {
          const serverUrl = data.updated_urls ? (data.updated_urls[idx] || data.updated_urls[String(idx)]) : null;
          if (serverUrl) {
            tr.icon_url = `${serverUrl}&_cb=${nowTs}`;
          } else {
            tr.icon_url = iconUrl;
          }
          tr.has_custom_icon = true;
        }
      });

      renderTracklistRows();
      showToast(`Updated artwork for ${targetIndices.length} track(s)${applyOverlay ? ' with chapter overlays' : ''}!`);
      closeIconPickerModal();
    } else {
      showToast(data.error || "Failed to update track artwork", true);
    }
  } catch (err) {
    console.error("Error applying artwork to tracks:", err);
    showToast(`Error applying artwork: ${err.message || err}`, true);
  } finally {
    btnApply.disabled = false;
    btnApply.innerText = "✨ Apply Artwork";
  }
}
