// Profile Avatar Helpers & Swatch Pickers (extracted from profiles.js)

function computeHouseholdMonograms(profiles) {
  const byLetter = {};
  const profs = profiles || currentProfiles;
  Object.keys(profs).forEach(pid => {
    const p = profs[pid];
    const name = (p.display_name || pid).trim();
    const firstChar = (name[0] || "C").toUpperCase();
    if (!byLetter[firstChar]) byLetter[firstChar] = [];
    byLetter[firstChar].push({ id: pid, name, customInitial: p.avatar_initial });
  });

  const monograms = {};
  Object.keys(byLetter).forEach(letter => {
    const list = byLetter[letter];
    if (list.length === 1) {
      monograms[list[0].id] = list[0].customInitial || letter;
    } else {
      // Disambiguate when starting letter collides!
      const used = new Set();
      // 1. Multi-word pass (e.g. "Jack B" -> "JB")
      list.forEach(item => {
        if (item.customInitial) {
          monograms[item.id] = item.customInitial;
          used.add(item.customInitial);
          return;
        }
        const words = item.name.split(/\s+/);
        if (words.length >= 2 && words[0] && words[1]) {
          const mono = (words[0][0] + words[1][0]).toUpperCase();
          monograms[item.id] = mono;
          used.add(mono);
        }
      });

      // 2. Single-word distinctive pass
      list.forEach(item => {
        if (monograms[item.id]) return;
        const clean = item.name.replace(/[^a-zA-Z0-9]/g, "");
        if (clean.length >= 2) {
          const cand = clean.substring(0, 2);
          if (!used.has(cand)) {
            monograms[item.id] = cand;
            used.add(cand);
          } else if (clean.length >= 3) {
            const cand2 = clean[0] + clean[2];
            monograms[item.id] = cand2;
            used.add(cand2);
          } else {
            monograms[item.id] = cand;
          }
        } else {
          monograms[item.id] = letter;
        }
      });
    }
  });
  return monograms;
}

function getAvatarColor(nameOrId, customColor = "") {
  if (customColor && customColor.startsWith("#")) return customColor;
  const str = (nameOrId || "Child").trim().toLowerCase();
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) & 0xFFFFFFFF;
  }
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
}

function createInitialAvatarElement(initial, bgColor, size = 44) {
  const div = document.createElement("div");
  div.style.width = `${size}px`;
  div.style.height = `${size}px`;
  div.style.borderRadius = "50%";
  div.style.background = bgColor;
  div.style.color = "#ffffff";
  div.style.display = "flex";
  div.style.alignItems = "center";
  div.style.justifyContent = "center";
  div.style.fontSize = `${Math.round(size * (initial && initial.length > 1 ? 0.38 : 0.45))}px`;
  div.style.fontWeight = "700";
  div.style.flexShrink = "0";
  div.style.boxShadow = "0 2px 8px rgba(0,0,0,0.25)";
  div.innerText = initial || "C";
  return div;
}

let pendingAvatarFile = null;

function renderColorSwatches(activeColor) {
  const container = document.getElementById("avatarColorSwatches");
  if (!container) return;
  container.innerHTML = "";
  AVATAR_PALETTE.forEach(c => {
    const swatch = document.createElement("button");
    swatch.type = "button";
    swatch.className = "color-swatch-btn";
    swatch.style.width = "22px";
    swatch.style.height = "22px";
    swatch.style.borderRadius = "50%";
    swatch.style.background = c;
    swatch.style.border = (activeColor && activeColor.toLowerCase() === c.toLowerCase()) ? "2px solid #ffffff" : "2px solid rgba(0,0,0,0.3)";
    swatch.style.cursor = "pointer";
    swatch.style.padding = "0";
    swatch.style.boxShadow = (activeColor && activeColor.toLowerCase() === c.toLowerCase()) ? "0 0 0 2px var(--accent-info)" : "none";
    swatch.onclick = () => selectAvatarColor(c);
    container.appendChild(swatch);
  });
}

function selectAvatarColor(colorHex) {
  document.getElementById("profileAvatarColorHidden").value = colorHex;
  renderColorSwatches(colorHex);
  updateAvatarPreview(document.getElementById("profileAvatarUrlHidden").value);
}

function onCustomInitialInput(val) {
  updateAvatarPreview(document.getElementById("profileAvatarUrlHidden").value);
}

function updateAvatarPreview(url, fallbackName = "") {
  const img = document.getElementById("profileAvatarPreview");
  const placeholder = document.getElementById("profileAvatarPlaceholder");
  const wrapper = document.getElementById("profileAvatarPreviewWrapper");
  const removeBtn = document.getElementById("btnRemoveAvatar");
  const hiddenInput = document.getElementById("profileAvatarUrlHidden");
  const colorInput = document.getElementById("profileAvatarColorHidden");
  const initialInput = document.getElementById("profileAvatarInitialInput");
  const customizer = document.getElementById("avatarFallbackCustomizer");

  const name = fallbackName || document.getElementById("profileDisplayName").value || document.getElementById("profileIdField").value || "Child";
  const customColor = colorInput ? colorInput.value : "";
  const customInitial = initialInput ? initialInput.value.trim() : "";

  // Compute monogram
  let monogram = customInitial;
  if (!monogram) {
    const monos = computeHouseholdMonograms();
    const pid = document.getElementById("profileIdField").value || fallbackName;
    monogram = monos[pid] || (name.trim().charAt(0) || "C").toUpperCase();
  }

  const color = getAvatarColor(name, customColor);

  if (url) {
    img.src = url;
    img.style.display = "block";
    placeholder.style.display = "none";
    if (wrapper) wrapper.style.background = "var(--bg-surface-elevated)";
    removeBtn.style.display = "inline-block";
    hiddenInput.value = url;
    if (customizer) customizer.style.display = "none";
  } else {
    img.src = "";
    img.style.display = "none";
    placeholder.style.display = "flex";
    placeholder.innerText = monogram;
    placeholder.style.width = "100%";
    placeholder.style.height = "100%";
    placeholder.style.alignItems = "center";
    placeholder.style.justifyContent = "center";
    placeholder.style.fontSize = monogram.length > 1 ? "22px" : "28px";
    placeholder.style.fontWeight = "bold";
    placeholder.style.color = "#ffffff";
    if (wrapper) {
      wrapper.style.background = color;
      wrapper.style.border = `2px solid ${color}`;
    }
    removeBtn.style.display = "none";
    hiddenInput.value = "";
    if (customizer) customizer.style.display = "block";
  }
}

function handleAvatarFileSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  pendingAvatarFile = file;

  const reader = new FileReader();
  reader.onload = (event) => {
    updateAvatarPreview(event.target.result);
  };
  reader.readAsDataURL(file);
}

function toggleAvatarUrlInput() {
  const input = document.getElementById("profileAvatarUrlInput");
  if (input.style.display === "none") {
    input.style.display = "block";
    input.focus();
  } else {
    input.style.display = "none";
  }
}

function handleAvatarUrlInput(url) {
  pendingAvatarFile = null;
  updateAvatarPreview(url.trim());
}

function removeProfileAvatar() {
  pendingAvatarFile = null;
  document.getElementById("profileAvatarFileInput").value = "";
  document.getElementById("profileAvatarUrlInput").value = "";
  updateAvatarPreview("");
}

