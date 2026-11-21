// ============================================================================
// Admin Users & Access Control Page (Household Accounts, LAN Access & SSO)
// ============================================================================

let cachedUsersList = [];
let cachedSsoMeta = {
  sso_config: {},
  env_trusted_proxies: ["127.0.0.1/32"],
  lan_sitter_access_enabled: true,
  current_auth_type: "session",
  oidc_callback_path: "/api/auth/oidc/callback"
};
let ssoBaselineSnapshot = null;
let ssoDirtyBound = false;

async function loadUsersPage() {
  await Promise.all([loadHouseholdUsers(), loadSsoAccessConfig()]);
  updateUsersKpis();
}

async function loadHouseholdUsers() {
  const tbody = document.getElementById("adminUsersTableBody");
  if (!tbody) return;
  try {
    const res = await fetch("/api/admin/users", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    cachedUsersList = Array.isArray(data.users) ? data.users : [];
    renderHouseholdUsers(cachedUsersList);
    updateUsersKpis();
  } catch (err) {
    console.error("Failed to load household users:", err);
  }
}

function updateUsersKpis() {
  const total = cachedUsersList.length;
  const admins = cachedUsersList.filter(u => u.role === "admin").length;
  const members = total - admins;
  const ssoUsers = cachedUsersList.filter(u => Boolean(u.sso_provider)).length;

  const kpiTotal = document.getElementById("kpiTotalUsers");
  const kpiBreak = document.getElementById("kpiUsersBreakdown");
  const countBadge = document.getElementById("userCountBadge");
  if (kpiTotal) kpiTotal.innerText = String(total);
  if (kpiBreak) kpiBreak.innerText = `${admins} Admin · ${members} Member${ssoUsers ? ` · ${ssoUsers} SSO` : ""}`;
  if (countBadge) countBadge.innerText = `${total} Account${total === 1 ? "" : "s"}`;

  const authTypeMap = {
    sso: "SSO Proxy",
    api_key: "Master API Key",
    session: "Local Session"
  };
  const authType = cachedSsoMeta.current_auth_type || (typeof currentUser === "object" && currentUser ? currentUser.auth_type : "session") || "session";
  const kpiMethod = document.getElementById("kpiActiveAuthMethod");
  const kpiMethodSub = document.getElementById("kpiActiveAuthSub");
  if (kpiMethod) kpiMethod.innerText = authTypeMap[authType] || "Local Session";
  if (kpiMethodSub && typeof currentUser === "object" && currentUser) {
    kpiMethodSub.innerText = `Signed in as ${currentUser.display_name || currentUser.username}`;
  }

  const lanEnabled = Boolean(cachedSsoMeta.lan_sitter_access_enabled);
  const kpiLan = document.getElementById("kpiLanGuestStatus");
  const kpiLanSub = document.getElementById("kpiLanGuestSub");
  if (kpiLan) {
    kpiLan.innerText = lanEnabled ? "Enabled" : "Disabled";
    kpiLan.style.color = lanEnabled ? "var(--accent-success)" : "var(--text-secondary)";
  }
  if (kpiLanSub) {
    kpiLanSub.innerText = lanEnabled ? "LAN portals open without sign-in" : "Private LAN sign-in required";
  }

  const cfg = cachedSsoMeta.sso_config || {};
  const fwdEnabled = cfg.forward_auth_enabled !== false;
  const oidcEnabled = Boolean(cfg.oidc_enabled);
  const providerName = cfg.provider_name || "Authentik";
  const kpiSso = document.getElementById("kpiSsoStatus");
  const kpiSsoSub = document.getElementById("kpiSsoSub");
  if (kpiSso) {
    kpiSso.innerText = oidcEnabled ? `${providerName} (OIDC Ready)` : (fwdEnabled ? `${providerName} Proxy` : "Disabled");
    kpiSso.style.color = (fwdEnabled || oidcEnabled) ? "#93c5fd" : "var(--text-muted)";
  }
  if (kpiSsoSub) {
    kpiSsoSub.innerText = fwdEnabled
      ? `Header: ${cfg.header_username || "X-authentik-username"}`
      : "Local password authentication only";
  }
}

function renderHouseholdUsers(users) {
  const tbody = document.getElementById("adminUsersTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!users || users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="padding: 14px; color: var(--text-secondary);">No user accounts configured.</td></tr>`;
    return;
  }

  users.forEach(u => {
    const uid = u.id || u.user_id || "";
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-subtle)";
    const isAdmin = u.role === "admin";
    const ssoProv = (u.sso_provider || "").trim();
    const authBadge = ssoProv
      ? `<span class="badge badge-info" title="Authenticated via SSO / Reverse Proxy">🛡️ SSO: ${escapeHtml(ssoProv)}</span>`
      : `<span class="badge badge-subtle">🔑 Local</span>`;
    const lastLogin = u.last_login ? escapeHtml(String(u.last_login).replace("T", " ").slice(0, 16)) : `<span style="color: var(--text-muted);">Never</span>`;

    tr.innerHTML = `
      <td style="padding: 10px 12px; font-weight: 600;">${escapeHtml(u.username)}</td>
      <td style="padding: 10px 12px;">${escapeHtml(u.display_name || u.username)}</td>
      <td style="padding: 10px 12px;">${authBadge}</td>
      <td style="padding: 10px 12px;">
        <select class="form-control" style="width: 155px; font-size: 12px; padding: 4px 8px;" onchange="changeHouseholdUserRole('${escapeHtml(uid)}', this.value)">
          <option value="admin" ${isAdmin ? 'selected' : ''}>🛡️ Admin (Console)</option>
          <option value="member" ${!isAdmin ? 'selected' : ''}>👤 Member (Portal)</option>
        </select>
      </td>
      <td style="padding: 10px 12px; font-size: 12px; color: var(--text-secondary);">${lastLogin}</td>
      <td style="padding: 10px 12px; text-align: right; white-space: nowrap;">
        <button type="button" class="btn btn-secondary btn-sm" style="font-size: 11px;" onclick="resetHouseholdUserPassword('${escapeHtml(uid)}', '${escapeHtml(u.username)}')">${ssoProv ? "🔑 Set Local PW" : "🔑 Reset PW"}</button>
        <button type="button" class="btn btn-danger btn-sm" style="font-size: 11px; margin-left: 4px;" onclick="deleteHouseholdUser('${escapeHtml(uid)}', '${escapeHtml(u.username)}')">🗑️</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function onNewUserAuthSourceChange() {
  const sourceEl = document.getElementById("newAdminAuthSource");
  const pwEl = document.getElementById("newAdminPassword");
  if (!sourceEl || !pwEl) return;

  if (sourceEl.value) {
    pwEl.value = "";
    pwEl.disabled = true;
    pwEl.placeholder = "Managed by SSO / IdP";
  } else {
    pwEl.disabled = false;
    pwEl.placeholder = "Min 8 chars";
  }
}

async function createNewHouseholdUser() {
  const usernameEl = document.getElementById("newAdminUsername");
  const displayEl = document.getElementById("newAdminDisplayName");
  const roleEl = document.getElementById("newAdminRole");
  const sourceEl = document.getElementById("newAdminAuthSource");
  const passwordEl = document.getElementById("newAdminPassword");

  const username = usernameEl?.value.trim() || "";
  const display_name = displayEl?.value.trim() || username;
  const role = roleEl?.value || "member";
  const sso_provider = sourceEl?.value.trim() || "";
  const password = passwordEl?.value || "";

  if (!username) {
    showToast("Username is required.", "warning");
    return;
  }
  if (!sso_provider && password.length < 8) {
    showToast("Password must be at least 8 characters for local accounts.", "warning");
    return;
  }

  try {
    const res = await fetch("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, display_name, role, sso_provider, password })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`Created ${sso_provider ? "SSO-linked " : ""}user '${username}' (${role}).`, "success");
      if (usernameEl) usernameEl.value = "";
      if (displayEl) displayEl.value = "";
      if (passwordEl) passwordEl.value = "";
      if (sourceEl) sourceEl.value = "";
      onNewUserAuthSourceChange();
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
  const newPassword = prompt(`Enter new password for '${username}' (minimum 8 characters):`);
  if (!newPassword) return;
  if (newPassword.length < 8) {
    showToast("Password must be at least 8 characters.", "warning");
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

// ----------------------------------------------------------------------------
// LAN Guest Policy & SSO / Authentik Configuration
// ----------------------------------------------------------------------------

function readSsoFormValues() {
  const extraRaw = document.getElementById("ssoExtraTrustedProxies")?.value || "";
  const extraList = extraRaw.split(",").map(s => s.trim()).filter(Boolean);
  return {
    forward_auth_enabled: Boolean(document.getElementById("ssoForwardAuthEnabled")?.checked),
    provider_name: document.getElementById("ssoProviderName")?.value || "Authentik",
    default_role: document.getElementById("ssoDefaultRole")?.value || "admin",
    admin_group: document.getElementById("ssoAdminGroup")?.value.trim() || "",
    header_username: document.getElementById("ssoHeaderUsername")?.value.trim() || "X-authentik-username",
    header_display_name: document.getElementById("ssoHeaderDisplayName")?.value.trim() || "X-authentik-name",
    header_groups: document.getElementById("ssoHeaderGroups")?.value.trim() || "X-authentik-groups",
    extra_trusted_proxies: extraList,
    logout_url: document.getElementById("ssoLogoutUrl")?.value.trim() || "",
    auto_provision_users: Boolean(document.getElementById("ssoAutoProvisionUsers")?.checked),
    oidc_enabled: Boolean(document.getElementById("ssoOidcEnabled")?.checked),
    oidc_issuer_url: document.getElementById("ssoOidcIssuerUrl")?.value.trim() || "",
    oidc_client_id: document.getElementById("ssoOidcClientId")?.value.trim() || "",
    oidc_client_secret: document.getElementById("ssoOidcClientSecret")?.value.trim() || ""
  };
}

function setSsoDirty(isDirty) {
  const badge = document.getElementById("unsaved-sso");
  if (badge) badge.style.display = isDirty ? "inline-flex" : "none";
  const btn = document.getElementById("btnSaveSsoConfig");
  if (btn) btn.classList.toggle("btn-unsaved", Boolean(isDirty));
}

function checkSsoDirty() {
  if (!ssoBaselineSnapshot) return;
  const cur = JSON.stringify(readSsoFormValues());
  setSsoDirty(cur !== ssoBaselineSnapshot);
}

function bindSsoDirtyListeners() {
  if (ssoDirtyBound) return;
  const form = document.getElementById("ssoConfigForm");
  if (!form) return;
  ssoDirtyBound = true;
  form.querySelectorAll("input, select").forEach((el) => {
    if (el.id === "ssoOidcCallbackUri") return;
    el.addEventListener("input", checkSsoDirty);
    el.addEventListener("change", checkSsoDirty);
  });
}

async function loadSsoAccessConfig() {
  try {
    const res = await fetch("/api/admin/auth/sso-config", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    cachedSsoMeta = data;
    renderSsoConfig(data);
  } catch (err) {
    console.error("Failed to load SSO config:", err);
  }
}

function renderSsoConfig(data) {
  const cfg = data.sso_config || {};

  const toggleLan = document.getElementById("toggleLanSitterAccess");
  const lanLabel = document.getElementById("lanSitterToggleLabel");
  if (toggleLan) {
    toggleLan.checked = Boolean(data.lan_sitter_access_enabled);
  }
  if (lanLabel) {
    lanLabel.innerText = data.lan_sitter_access_enabled ? "Enabled" : "Disabled";
  }

  const envEl = document.getElementById("ssoEnvTrustedProxies");
  if (envEl) {
    const envProxies = Array.isArray(data.env_trusted_proxies) ? data.env_trusted_proxies : [];
    envEl.innerText = envProxies.length ? envProxies.join(", ") : "None";
  }

  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val ?? "";
  };
  const setChecked = (id, flag) => {
    const el = document.getElementById(id);
    if (el) el.checked = Boolean(flag);
  };

  setChecked("ssoForwardAuthEnabled", cfg.forward_auth_enabled !== false);
  setVal("ssoProviderName", cfg.provider_name || "Authentik");
  setVal("ssoDefaultRole", cfg.default_role || "admin");
  setVal("ssoAdminGroup", cfg.admin_group || "");
  setVal("ssoHeaderUsername", cfg.header_username || "X-authentik-username");
  setVal("ssoHeaderDisplayName", cfg.header_display_name || "X-authentik-name");
  setVal("ssoHeaderGroups", cfg.header_groups || "X-authentik-groups");
  setVal("ssoExtraTrustedProxies", Array.isArray(cfg.extra_trusted_proxies) ? cfg.extra_trusted_proxies.join(", ") : "");
  setVal("ssoLogoutUrl", cfg.logout_url || "");
  setChecked("ssoAutoProvisionUsers", cfg.auto_provision_users);
  setChecked("ssoOidcEnabled", cfg.oidc_enabled);
  setVal("ssoOidcIssuerUrl", cfg.oidc_issuer_url || "");
  setVal("ssoOidcClientId", cfg.oidc_client_id || "");
  setVal("ssoOidcClientSecret", cfg.oidc_client_secret || "");

  const cbPath = data.oidc_callback_path || "/api/auth/oidc/callback";
  setVal("ssoOidcCallbackUri", `${window.location.origin}${cbPath}`);

  const badge = document.getElementById("ssoConfigStatusBadge");
  if (badge) {
    const active = cfg.forward_auth_enabled !== false;
    badge.className = active ? "badge badge-info" : "badge badge-subtle";
    badge.innerText = active ? `ForwardAuth: ${cfg.provider_name || "Authentik"}` : "ForwardAuth Disabled";
  }

  ssoBaselineSnapshot = JSON.stringify(readSsoFormValues());
  setSsoDirty(false);
  bindSsoDirtyListeners();
  updateUsersKpis();
}

async function saveLanSitterToggle() {
  const toggleLan = document.getElementById("toggleLanSitterAccess");
  const lanLabel = document.getElementById("lanSitterToggleLabel");
  if (!toggleLan) return;
  const enabled = Boolean(toggleLan.checked);

  try {
    const res = await fetch("/api/admin/auth/sso-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lan_sitter_access_enabled: enabled })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      cachedSsoMeta = data;
      if (lanLabel) lanLabel.innerText = enabled ? "Enabled" : "Disabled";
      updateUsersKpis();
      showToast(`LAN Guest Access ${enabled ? "enabled" : "disabled"}.`, "success");
    } else {
      toggleLan.checked = !enabled;
      showToast(data.error || "Failed to update LAN guest setting.", "danger");
    }
  } catch (err) {
    toggleLan.checked = !enabled;
    showToast("Network error updating LAN guest policy.", "danger");
  }
}

async function saveSsoConfig() {
  const btn = document.getElementById("btnSaveSsoConfig");
  if (btn) {
    btn.disabled = true;
    btn.innerText = "💾 Saving...";
  }

  const ssoPayload = readSsoFormValues();
  try {
    const res = await fetch("/api/admin/auth/sso-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sso_config: ssoPayload })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      cachedSsoMeta = data;
      renderSsoConfig(data);
      showToast("SSO & Identity Provider configuration saved.", "success");
    } else {
      showToast(data.error || "Failed to save SSO configuration.", "danger");
    }
  } catch (err) {
    showToast("Network error saving SSO configuration.", "danger");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "💾 Save Access & SSO Settings";
    }
  }
}

function copyOidcCallbackUri() {
  const el = document.getElementById("ssoOidcCallbackUri");
  if (!el || !el.value) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(el.value).then(() => {
      showToast("Copied OIDC Callback URI to clipboard.", "success");
    }).catch(() => {
      el.select();
      showToast("Select and copy the callback URI field.", "info");
    });
  } else {
    el.select();
    showToast("Select and copy the callback URI field.", "info");
  }
}
