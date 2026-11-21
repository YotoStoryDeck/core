// ============================================================================
// Admin Settings: Household User Accounts & Role Management (DLP-009)
// ============================================================================

async function loadHouseholdUsers() {
  const tbody = document.getElementById("adminUsersTableBody");
  if (!tbody) return;
  try {
    const res = await fetch("/api/admin/users");
    if (!res.ok) return;
    const data = await res.json();
    renderHouseholdUsers(data.users || []);
  } catch (err) {
    console.error("Failed to load household users:", err);
  }
}

function renderHouseholdUsers(users) {
  const tbody = document.getElementById("adminUsersTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!users || users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="padding: 12px; color: var(--text-secondary);">No user accounts configured.</td></tr>`;
    return;
  }
  users.forEach(u => {
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-subtle)";
    const isAdmin = u.role === "admin";
    tr.innerHTML = `
      <td style="padding: 8px; font-weight: 600;">${escapeHtml(u.username)}</td>
      <td style="padding: 8px;">${escapeHtml(u.display_name || u.username)}</td>
      <td style="padding: 8px;">
        <select class="form-control" style="width: 155px; font-size: 12px; padding: 3px 6px;" onchange="changeHouseholdUserRole('${escapeHtml(u.user_id)}', this.value)">
          <option value="admin" ${isAdmin ? 'selected' : ''}>🛡️ Admin (Console)</option>
          <option value="member" ${!isAdmin ? 'selected' : ''}>👤 Member (Portal)</option>
        </select>
      </td>
      <td style="padding: 8px; text-align: right; white-space: nowrap;">
        <button type="button" class="btn btn-secondary btn-sm" style="font-size: 11px;" onclick="resetHouseholdUserPassword('${escapeHtml(u.user_id)}', '${escapeHtml(u.username)}')">🔑 Reset Password</button>
        <button type="button" class="btn btn-danger btn-sm" style="font-size: 11px; margin-left: 4px;" onclick="deleteHouseholdUser('${escapeHtml(u.user_id)}', '${escapeHtml(u.username)}')">🗑️</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function createNewHouseholdUser() {
  const usernameEl = document.getElementById("newAdminUsername");
  const displayEl = document.getElementById("newAdminDisplayName");
  const roleEl = document.getElementById("newAdminRole");
  const passwordEl = document.getElementById("newAdminPassword");

  const username = usernameEl?.value.trim() || "";
  const display_name = displayEl?.value.trim() || username;
  const role = roleEl?.value || "member";
  const password = passwordEl?.value || "";

  if (!username || !password) {
    showToast("Username and password (min 6 chars) are required.", "warning");
    return;
  }

  try {
    const res = await fetch("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, display_name, role, password })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Created user '${username}' (${role}).`, "success");
      if (usernameEl) usernameEl.value = "";
      if (displayEl) displayEl.value = "";
      if (passwordEl) passwordEl.value = "";
      await loadHouseholdUsers();
    } else {
      showToast(data.error || "Failed to create user.", "danger");
    }
  } catch (err) {
    showToast("Network error creating user.", "danger");
  }
}

async function changeHouseholdUserRole(userId, role) {
  try {
    const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast("Updated user role.", "success");
      await loadHouseholdUsers();
    } else {
      showToast(data.error || "Failed to update role.", "danger");
      await loadHouseholdUsers();
    }
  } catch (err) {
    showToast("Network error updating role.", "danger");
  }
}

async function resetHouseholdUserPassword(userId, username) {
  const newPassword = prompt(`Enter new password for '${username}' (minimum 6 characters):`);
  if (!newPassword) return;
  if (newPassword.length < 6) {
    showToast("Password must be at least 6 characters.", "warning");
    return;
  }
  try {
    const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: newPassword })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Password updated for '${username}'.`, "success");
    } else {
      showToast(data.error || "Failed to reset password.", "danger");
    }
  } catch (err) {
    showToast("Network error resetting password.", "danger");
  }
}

async function deleteHouseholdUser(userId, username) {
  if (!confirm(`Delete user account '${username}'?`)) return;
  try {
    const res = await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Deleted user '${username}'.`, "success");
      await loadHouseholdUsers();
    } else {
      showToast(data.error || "Failed to delete user.", "danger");
    }
  } catch (err) {
    showToast("Network error deleting user.", "danger");
  }
}
