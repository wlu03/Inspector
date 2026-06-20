// Renderer for the multi-screen buggy fixture.
//
// Navigation uses the standard web hash-router idiom; state lives in a plain
// in-memory object (no backend, no storage). Six bugs are planted; each emits a
// distinct greppable line via console.error BEFORE its faulty behavior, so an
// external agent can observe them over CDP (--remote-debugging-port=9223).
//
// See BUGS.md / bugs.json for the scored manifest.

// ---- in-memory app state ----
const store = {
  name: "", // the name the user "saves" on Settings
  notifications: false, // underlying notifications state
  theme: "system",
  display: { displayName: "", email: "" },
};

// BUG-04: this cache is supposed to mirror store.name for the Profile summary,
// but nothing ever writes to it, so the summary is always blank/stale.
let propagatedName = "";

// ---- router (standard hash navigation) ----
const routes = {
  "#/settings": "screen-settings",
  "#/profile": "screen-profile",
  "#/about": "screen-about",
};

function navigate(hash) {
  location.hash = hash;
}

function router() {
  const hash = location.hash || "#/settings";
  const screenId = routes[hash];

  document.querySelectorAll(".screen").forEach((s) => (s.hidden = true));
  document
    .querySelectorAll("nav a")
    .forEach((a) => a.classList.toggle("active", a.dataset.route === hash));

  if (!screenId) {
    // Unknown route → dead end (no screen shown). BUG-05 can land here.
    return;
  }
  document.getElementById(screenId).hidden = false;

  if (screenId === "screen-profile") onProfileShown();
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", () => {
  wireSettings();
  wireProfile();
  wireAbout();
  router();
});

// ---- Settings ----
function wireSettings() {
  // BUG-01 (crash, Save): the REAL primary button. Logs, then throws an
  // uncaught TypeError (method on undefined) before "Saved" can render.
  document.getElementById("primaryAction").addEventListener("click", () => {
    console.error("query not invalidated after save");
    const result = undefined;
    result.show(); // TypeError: Cannot read properties of undefined (reading 'show')
    store.name = document.getElementById("name").value; // unreachable
    propagatedName = store.name; // unreachable
    document.getElementById("toast").textContent = "Saved"; // unreachable
  });

  // BUG-06 (a11y/locator trap): the decoy carries the obvious "Save" label but
  // does nothing useful. Naive locators that select by label "Save" land here.
  document.getElementById("decoSave").addEventListener("click", () => {
    console.error("missing a11y label on primary action");
    // no-op: this is not the real Save control
  });

  // BUG-02 (silent state): flips the visual label only; store.notifications is
  // never updated, so the UI and the underlying state desync.
  document.getElementById("notifToggle").addEventListener("click", (e) => {
    console.error("toggle state desync");
    const btn = e.currentTarget;
    const showingOn = btn.textContent.trim() === "On";
    btn.textContent = showingOn ? "Off" : "On";
    btn.setAttribute("aria-pressed", String(!showingOn));
    // store.notifications intentionally NOT updated
  });

  // Theme picker works correctly (no bug) — applies a real theme.
  const theme = document.getElementById("theme");
  theme.addEventListener("change", () => {
    store.theme = theme.value;
    document.body.dataset.theme = theme.value;
  });
}

// ---- Profile ----
function wireProfile() {
  // BUG-03 (validation bypass): logs, then proceeds without validating the
  // required Display name or the "@" in Email — accepts anything.
  document.getElementById("continueBtn").addEventListener("click", () => {
    console.error("validation skipped on submit");
    const displayName = document.getElementById("displayName").value;
    const email = document.getElementById("email").value;
    // No validation performed; proceeds as if valid.
    store.display = { displayName, email };
    document.getElementById("profileResult").textContent = "Continued ✓";
  });
}

// BUG-04 (broken cross-screen state): should show store.name saved on Settings,
// but reads `propagatedName`, which is never updated → always blank/stale.
function onProfileShown() {
  console.error("state not propagated across screens");
  document.getElementById("profileSummary").textContent =
    "Saved name: " + propagatedName; // propagatedName is always ""
}

// ---- About ----
function wireAbout() {
  // BUG-05 (navigation defect): should clear all state and return to Settings;
  // instead clears nothing and routes to the wrong screen.
  document.getElementById("resetAll").addEventListener("click", () => {
    console.error("reset no-op, wrong route");
    // (no state cleared)
    navigate("#/profile"); // wrong route — should be "#/settings"
  });
}
