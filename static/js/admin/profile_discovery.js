// Household Auto-Discovery Modal & Handlers (extracted from profiles.js)

let discoveredHouseholdMatches = [];

// ----------------------------------------------------------------------------
// Household Auto-Discovery Handlers
// ----------------------------------------------------------------------------

async function runHouseholdAutoDiscovery() {
  const modal = document.getElementById("discoveryModal");
  const loading = document.getElementById("discoveryLoading");
  const results = document.getElementById("discoveryResults");
  const tbody = document.getElementById("discoveryTableBody");

  modal.style.display = "flex";
  loading.style.display = "block";
  results.style.display = "none";
  tbody.innerHTML = "";

  try {
    const res = await fetch("/api/admin/discovery/household-match");
    if (!res.ok) {
      throw new Error(`Discovery probe failed with status ${res.status}`);
    }
    const data = await res.json();
    discoveredHouseholdMatches = data.matches || [];

    loading.style.display = "none";
    results.style.display = "block";

    if (discoveredHouseholdMatches.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">No matching Yoto players or Audiobookshelf users discovered. Check Yoto Cloud or Audiobookshelf server connection.</td></tr>`;
      return;
    }

    discoveredHouseholdMatches.forEach((m, idx) => {
      const tr = document.createElement("tr");
      const playerInfo = m.matched_yoto_player ? `${escapeHtml(m.matched_yoto_player.name)} <code style="font-size: 11px;">(${escapeHtml(m.matched_yoto_player.id)})</code>` : "None";
      const absInfo = m.matched_abs_user ? `<code>${escapeHtml(m.matched_abs_user.username)}</code>` : "<span class='text-secondary'>Unmatched</span>";
      const confBadge = m.confidence >= 0.8
        ? `<span class="badge badge-success">High (${Math.round(m.confidence * 100)}%)</span>`
        : `<span class="badge badge-warning">Partial (${Math.round(m.confidence * 100)}%)</span>`;
      const alreadyBadge = m.already_exists ? ` <span class="badge badge-subtle">Exists</span>` : "";

      tr.innerHTML = `
        <td><input type="checkbox" class="discovery-select" data-idx="${idx}" ${m.already_exists ? "" : "checked"}></td>
        <td><strong>${escapeHtml(m.display_name)}</strong> <span class="text-secondary">(${escapeHtml(m.suggested_profile_id)})</span>${alreadyBadge}</td>
        <td>${playerInfo}</td>
        <td>${absInfo}</td>
        <td>${confBadge}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    loading.innerHTML = `<p style="color: var(--accent-danger);">Discovery failed: ${escapeHtml(err.message)}</p><button class="btn btn-secondary btn-sm" onclick="closeDiscoveryModal()">Close</button>`;
  }
}

function closeDiscoveryModal() {
  document.getElementById("discoveryModal").style.display = "none";
}

function toggleSelectAllDiscovery(checked) {
  document.querySelectorAll(".discovery-select").forEach(cb => cb.checked = checked);
}

async function confirmImportDiscovery() {
  const selectedIndices = [];
  document.querySelectorAll(".discovery-select:checked").forEach(cb => {
    selectedIndices.push(parseInt(cb.getAttribute("data-idx")));
  });

  if (selectedIndices.length === 0) {
    showToast("No profiles selected for import.", "info");
    return;
  }

  const profilesToImport = selectedIndices.map(idx => {
    const m = discoveredHouseholdMatches[idx];
    const pid = m.suggested_profile_id;
    const absUser = m.matched_abs_user ? m.matched_abs_user.username : "";
    const playerId = m.matched_yoto_player ? m.matched_yoto_player.id : "";
    return {
      id: pid,
      display_name: m.display_name,
      abs_username: absUser,
      abs_api_key: "",
      abs_tag: absUser || pid,
      default_player_id: playerId,
      player_ids: playerId ? [playerId] : []
    };
  });

  try {
    const res = await fetch("/api/admin/discovery/auto-import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profiles: profilesToImport })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Successfully provisioned ${data.imported_count} profile(s)!`, "success");
      closeDiscoveryModal();
      loadProfiles();
      loadMatrix();
    } else {
      showToast(data.error || "Failed to import profiles.", "danger");
    }
  } catch (err) {
    showToast("Network error importing profiles.", "danger");
  }
}

