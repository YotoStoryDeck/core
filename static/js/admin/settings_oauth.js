// ============================================================================
// Admin Settings: In-Browser Yoto OAuth 2.0 PKCE Helpers
// ============================================================================

let activeYotoOAuthState = "";
let yotoOAuthPollTimer = null;
let yotoOAuthHandledState = "";

function toggleYotoRefreshTokenVisibility() {
  const input = document.getElementById("credYotoRefresh");
  const btn = document.getElementById("btnToggleYotoRefresh");
  if (!input) return;
  if (input.type === "password") {
    input.type = "text";
    if (btn) btn.innerText = "🙈";
  } else {
    input.type = "password";
    if (btn) btn.innerText = "👁️";
  }
}

function stopYotoOAuthPolling() {
  if (yotoOAuthPollTimer) {
    clearInterval(yotoOAuthPollTimer);
    yotoOAuthPollTimer = null;
  }
}

async function handleYotoOAuthComplete(ok, state, messageOrError) {
  const dedupeKey = state || activeYotoOAuthState || "manual";
  if (yotoOAuthHandledState && yotoOAuthHandledState === dedupeKey && ok) {
    return;
  }
  stopYotoOAuthPolling();

  const statusEl = document.getElementById("yotoStatusInline");
  if (ok) {
    yotoOAuthHandledState = dedupeKey;
    activeYotoOAuthState = "";
    const helper = document.getElementById("yotoOAuthManualHelper");
    if (helper) helper.style.display = "none";
    const helperInput = document.getElementById("yotoPastedUrl");
    if (helperInput) helperInput.value = "";
    await loadApiCredentials();
    if (statusEl) {
      statusEl.innerHTML = '<span style="color: var(--accent-success);">✅ Connected! Refresh token saved automatically.</span>';
    }
    showToast(messageOrError || "Yoto connected successfully! Refresh token saved.", "success");
  } else {
    const errText = messageOrError || "Failed to complete Yoto login.";
    if (statusEl) {
      statusEl.innerHTML = `<span style="color: var(--accent-danger);">❌ ${escapeHtml(errText)}</span>`;
    }
    showToast(errText, "danger");
  }
}

function startYotoOAuthStatusPolling(state) {
  stopYotoOAuthPolling();
  if (!state) return;

  let attempts = 0;
  const maxAttempts = 120; // 3 minutes at 1500ms interval

  yotoOAuthPollTimer = setInterval(async () => {
    attempts += 1;
    if (attempts > maxAttempts || activeYotoOAuthState !== state) {
      stopYotoOAuthPolling();
      return;
    }
    try {
      const res = await fetch(`/api/admin/yoto/oauth/status?state=${encodeURIComponent(state)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === "completed") {
        await handleYotoOAuthComplete(true, state, data.message);
      } else if (data.status === "error") {
        await handleYotoOAuthComplete(false, state, data.error);
      } else if (data.status === "not_found") {
        stopYotoOAuthPolling();
      }
    } catch (err) {
      // Ignore transient network hiccups during polling
    }
  }, 1500);
}

async function startInBrowserYotoOAuth() {
  const clientId = document.getElementById("credYotoClientId").value.trim();
  if (!clientId) {
    showToast("Please enter your Yoto Client ID first.", "danger");
    document.getElementById("credYotoClientId").focus();
    return;
  }

  stopYotoOAuthPolling();
  showToast("Starting Yoto authorization flow...");
  try {
    const res = await fetch("/api/admin/yoto/oauth/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: clientId,
        client_origin: window.location.origin
      })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      showToast(data.error || "Failed to start Yoto OAuth.", "danger");
      return;
    }

    activeYotoOAuthState = data.state || "";
    yotoOAuthHandledState = "";

    const helper = document.getElementById("yotoOAuthManualHelper");
    const helperTitle = document.getElementById("yotoOAuthHelperTitle");
    const helperDesc = document.getElementById("yotoOAuthHelperDesc");
    if (helperTitle && helperDesc) {
      if (data.auto_callback) {
        helperTitle.textContent = "⏳ Waiting for Yoto Authorization...";
        helperDesc.textContent = "StoryDeck Core will automatically capture and save the refresh token as soon as you click Allow in the popup. Only paste the callback URL or code below if auto-completion fails.";
      } else {
        helperTitle.textContent = "📋 Manual Callback Required (Plain HTTP LAN Mode)";
        helperDesc.textContent = "Yoto requires HTTPS or localhost/127.0.0.1 for automatic redirects. After clicking Allow, copy the full http://127.0.0.1:8787/callback?code=... URL from the popup address bar and paste it below.";
      }
    }
    if (helper) helper.style.display = "block";

    const popup = window.open(data.auth_url, "yotoAuthPopup", "width=600,height=750,menubar=no,toolbar=no");
    if (!popup || popup.closed || typeof popup.closed === "undefined") {
      window.open(data.auth_url, "_blank");
    }

    if (data.auto_callback && activeYotoOAuthState) {
      startYotoOAuthStatusPolling(activeYotoOAuthState);
    }
    showToast("Sign into Yoto in the opened window and approve access.", "info");
  } catch (err) {
    showToast("Network error starting Yoto OAuth: " + err.message, "danger");
  }
}

async function finishInBrowserYotoOAuth(codeOrUrl, explicitState = "") {
  const helperInput = document.getElementById("yotoPastedUrl");
  const input = codeOrUrl || (helperInput ? helperInput.value.trim() : "");
  if (!input) {
    showToast("Please paste the callback URL or authorization code.", "danger");
    return;
  }

  const targetState = explicitState || activeYotoOAuthState;
  showToast("Exchanging code for Yoto Refresh Token...");
  try {
    const res = await fetch("/api/admin/yoto/oauth/finish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url_or_code: input,
        state: targetState
      })
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      await handleYotoOAuthComplete(true, targetState, data.message);
    } else {
      await handleYotoOAuthComplete(false, targetState, data.error || "Failed to complete Yoto login.");
    }
  } catch (err) {
    showToast("Network error completing Yoto login: " + err.message, "danger");
  }
}

window.addEventListener("message", (event) => {
  if (event.origin && event.origin !== window.location.origin) return;
  if (!event.data) return;
  if (event.data.type === "YOTO_AUTH_COMPLETE") {
    handleYotoOAuthComplete(Boolean(event.data.ok), event.data.state || "", event.data.ok ? event.data.message : event.data.error);
  } else if (event.data.type === "YOTO_AUTH_CALLBACK") {
    finishInBrowserYotoOAuth(event.data.code, event.data.state || "");
  }
});

if (typeof BroadcastChannel !== "undefined") {
  try {
    const yotoOAuthChannel = new BroadcastChannel("storydeck_yoto_oauth");
    yotoOAuthChannel.addEventListener("message", (event) => {
      if (event.data && event.data.type === "YOTO_AUTH_COMPLETE") {
        handleYotoOAuthComplete(Boolean(event.data.ok), event.data.state || "", event.data.ok ? event.data.message : event.data.error);
      }
    });
  } catch (err) {
    console.debug("BroadcastChannel listener unavailable:", err);
  }
}

window.addEventListener("storage", (event) => {
  if (event.key !== "storydeck_yoto_oauth_result" || !event.newValue) return;
  try {
    const parsed = JSON.parse(event.newValue);
    if (parsed && parsed.type === "YOTO_AUTH_COMPLETE") {
      handleYotoOAuthComplete(Boolean(parsed.ok), parsed.state || "", parsed.ok ? parsed.message : parsed.error);
    }
  } catch (err) {
    // Ignore malformed localStorage payload
  }
});
