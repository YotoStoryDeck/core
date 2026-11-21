// ============================================================================
// StoryDeck Core Live Connection & Offline Awareness Monitor
// Shared across Parent Portal (/) and Admin Console (/admin).
// ============================================================================

(function () {
  const HEALTH_POLL_ONLINE_MS = 10000;
  const HEALTH_POLL_RETRY_MS = 1500;
  const HEALTH_POLL_OFFLINE_MS = 5000;
  const HEALTH_TIMEOUT_MS = 4000;
  const CONSECUTIVE_FAILURES_FOR_OFFLINE = 2;

  const state = {
    status: "online", // "online" | "reconnecting" | "offline"
    consecutiveFailures: 0,
    lastHealthyAt: null,
    lastVersion: "",
    lastLatencyMs: null,
    lastReason: "",
    checking: false,
    timerId: null
  };

  function scheduleNextProbe(delayMs) {
    if (state.timerId) {
      clearTimeout(state.timerId);
      state.timerId = null;
    }
    state.timerId = setTimeout(() => {
      if (document.visibilityState === "hidden" && state.status === "online") {
        scheduleNextProbe(HEALTH_POLL_ONLINE_MS);
        return;
      }
      checkCoreHealth(false);
    }, delayMs);
  }

  function formatTime(dateObj) {
    if (!dateObj) return "";
    try {
      return dateObj.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch (e) {
      return "";
    }
  }

  function applyHealthUI(prevStatus, manual) {
    const isOffline = state.status === "offline";
    const isReconnecting = state.status === "reconnecting";
    const isOnline = state.status === "online";

    document.body.classList.toggle("core-offline", isOffline);
    document.body.classList.toggle("core-reconnecting", isReconnecting);

    const pill = document.getElementById("coreConnectionPill");
    if (pill) {
      pill.classList.remove("online", "reconnecting", "offline");
      pill.classList.add(state.status);
      const textEl = pill.querySelector(".core-status-text");
      if (isOnline) {
        if (textEl) textEl.innerText = "Core Online";
        const verStr = state.lastVersion ? `v${state.lastVersion}` : "Connected";
        const latStr = state.lastLatencyMs !== null ? ` (${state.lastLatencyMs}ms)` : "";
        pill.title = `StoryDeck Core ${verStr}${latStr} • Click to verify`;
      } else if (isReconnecting) {
        if (textEl) textEl.innerText = "Reconnecting...";
        pill.title = state.lastReason || "Reconnecting to StoryDeck Core...";
      } else {
        if (textEl) textEl.innerText = "Core Offline";
        pill.title = state.lastReason || "StoryDeck Core is unreachable";
      }
    }

    document.querySelectorAll(".sidebar-footer-dot").forEach((dot) => {
      dot.classList.remove("online", "reconnecting", "offline");
      dot.classList.add(state.status);
    });

    const banner = document.getElementById("coreOfflineBanner");
    const reasonEl = document.getElementById("coreOfflineReason");
    const retryBtn = document.getElementById("btnRetryCoreHealth");
    if (banner) {
      if (isOffline) {
        banner.style.display = "flex";
        if (reasonEl) {
          const lastSeen = state.lastHealthyAt ? ` • Last seen ${formatTime(state.lastHealthyAt)}` : "";
          reasonEl.innerText = `${state.lastReason || "Cannot reach StoryDeck Core server."}${lastSeen}`;
        }
      } else {
        banner.style.display = "none";
      }
    }
    if (retryBtn) {
      retryBtn.disabled = Boolean(manual && state.checking);
      retryBtn.innerText = (manual && state.checking) ? "⏳ Checking..." : "🔄 Retry Now";
    }

    const stateChanged = prevStatus !== state.status;
    if (stateChanged) {
      const recovered = prevStatus === "offline" && isOnline;
      window.dispatchEvent(new CustomEvent("storydeck:core-status", {
        detail: {
          status: state.status,
          online: isOnline,
          reconnecting: isReconnecting,
          offline: isOffline,
          recovered,
          version: state.lastVersion,
          latencyMs: state.lastLatencyMs,
          reason: state.lastReason
        }
      }));
    }
  }

  function handleProbeSuccess(payload, latencyMs) {
    const prevStatus = state.status;
    state.status = "online";
    state.consecutiveFailures = 0;
    state.lastHealthyAt = new Date();
    state.lastLatencyMs = latencyMs;
    state.lastVersion = (payload && payload.version) ? String(payload.version) : state.lastVersion;
    state.lastReason = "";
    state.checking = false;
    applyHealthUI(prevStatus, false);
    scheduleNextProbe(HEALTH_POLL_ONLINE_MS);
    return true;
  }

  function handleProbeFailure(reason, immediateOffline) {
    const prevStatus = state.status;
    state.consecutiveFailures += 1;
    state.lastReason = reason || "StoryDeck Core server did not respond.";
    state.checking = false;

    if (immediateOffline || navigator.onLine === false || state.consecutiveFailures >= CONSECUTIVE_FAILURES_FOR_OFFLINE) {
      state.status = "offline";
      applyHealthUI(prevStatus, false);
      scheduleNextProbe(HEALTH_POLL_OFFLINE_MS);
    } else {
      state.status = "reconnecting";
      applyHealthUI(prevStatus, false);
      scheduleNextProbe(HEALTH_POLL_RETRY_MS);
    }
    return false;
  }

  async function checkCoreHealth(manual = false) {
    if (state.checking && !manual) {
      return state.status === "online";
    }

    if (navigator.onLine === false) {
      return handleProbeFailure("Your device reports no active network connection.", true);
    }

    state.checking = true;
    if (manual) {
      applyHealthUI(state.status, true);
    }

    const startedAt = Date.now();
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);

    try {
      const res = await fetch(`/health?t=${startedAt}`, {
        method: "GET",
        cache: "no-store",
        signal: controller.signal
      });
      clearTimeout(abortTimer);

      const latencyMs = Math.max(1, Date.now() - startedAt);
      if (res.status === 502 || res.status === 503 || res.status === 504) {
        return handleProbeFailure(`Reverse proxy / Core returned HTTP ${res.status}.`, true);
      }
      if (!res.ok) {
        return handleProbeFailure(`Health check returned HTTP ${res.status}.`, false);
      }

      let payload = null;
      try {
        payload = await res.json();
      } catch (e) {
        return handleProbeFailure("Invalid JSON response from Core health endpoint.", false);
      }

      if (!payload || payload.status !== "healthy") {
        return handleProbeFailure("StoryDeck Core reported an unhealthy status.", false);
      }

      return handleProbeSuccess(payload, latencyMs);
    } catch (err) {
      clearTimeout(abortTimer);
      const isTimeout = err && err.name === "AbortError";
      const msg = isTimeout
        ? "Timed out waiting for StoryDeck Core (/health)."
        : "Cannot reach StoryDeck Core server. Check if the service is running.";
      return handleProbeFailure(msg, false);
    }
  }

  function reportNetworkError(reason) {
    if (navigator.onLine === false) {
      handleProbeFailure("Your device reports no active network connection.", true);
      return;
    }
    if (state.status === "offline") return;
    if (!state.checking) {
      if (reason) state.lastReason = reason;
      checkCoreHealth(false);
    }
  }

  window.StoryDeckHealth = {
    isOnline: () => state.status === "online",
    isOffline: () => state.status === "offline",
    getStatus: () => state.status,
    checkNow: (manual = true) => checkCoreHealth(manual),
    reportNetworkError
  };

  window.addEventListener("offline", () => {
    handleProbeFailure("Browser lost network connectivity.", true);
  });

  window.addEventListener("online", () => {
    state.consecutiveFailures = Math.min(state.consecutiveFailures, 1);
    checkCoreHealth(false);
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      checkCoreHealth(false);
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    checkCoreHealth(false);
  });
})();
