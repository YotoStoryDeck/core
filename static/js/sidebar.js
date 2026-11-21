// ============================================================================
// StoryDeck Core Shared Collapsible Sidebar Controller
// Synchronizes collapsed state and mobile drawer across Parent & Admin Portals.
// ============================================================================

const SIDEBAR_STORAGE_KEY = "storydeck_sidebar_collapsed";

function initSidebar() {
  try {
    if (localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1") {
      document.body.classList.add("sidebar-collapsed");
    }
  } catch (e) {
    // Ignore storage access restriction errors
  }

  const collapseBtn = document.getElementById("sidebarCollapseBtn");
  if (collapseBtn) {
    const collapsed = document.body.classList.contains("sidebar-collapsed");
    collapseBtn.setAttribute("aria-expanded", String(!collapsed));
    collapseBtn.title = collapsed ? "Expand menu" : "Collapse menu";
  }
}

function toggleSidebarCollapse() {
  const collapsed = document.body.classList.toggle("sidebar-collapsed");
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
  } catch (e) {
    // Ignore storage access restriction errors
  }
  const collapseBtn = document.getElementById("sidebarCollapseBtn");
  if (collapseBtn) {
    collapseBtn.setAttribute("aria-expanded", String(!collapsed));
    collapseBtn.title = collapsed ? "Expand menu" : "Collapse menu";
  }
}

function openMobileSidebar() {
  document.body.classList.add("sidebar-mobile-open");
}

function closeMobileSidebar() {
  document.body.classList.remove("sidebar-mobile-open");
}

function toggleMobileSidebar() {
  document.body.classList.toggle("sidebar-mobile-open");
}

document.addEventListener("DOMContentLoaded", initSidebar);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeMobileSidebar();
  }
});
