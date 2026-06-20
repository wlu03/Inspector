// Minimal, deliberately-buggy multi-screen fixture for an automated UI-testing
// agent. Three screens (Settings / Profile / About) with hash-based navigation,
// one shared state object, and exactly six planted bugs (BUG-01..BUG-06).
//
// Each bug emits a distinct, greppable console.error line BEFORE its faulty
// behavior. See BUGS.md / bugs.json for the scored manifest.

const APP_VERSION = "1.0.0";

// Shared application state. The single source of truth.
const state = {
  savedName: "", // set by Settings "Save"
  notifications: false, // SHOULD be flipped by the toggle (see BUG-02)
  theme: "system",
};

// A stand-in for a query cache that SHOULD be invalidated after a save.
// In this buggy build it is never wired up (stays undefined). See BUG-01.
const queryCache = undefined;

// A separate, never-updated copy that the Profile summary reads from.
// Because nothing ever writes to it, the summary is always stale. See BUG-04.
const profileMirror = { name: "" };

const app = document.getElementById("app");

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

const routes = {
  settings: renderSettings,
  profile: renderProfile,
  about: renderAbout,
};

function currentRoute() {
  const hash = window.location.hash.replace(/^#\//, "");
  return hash || "settings";
}

function render() {
  const route = currentRoute();
  const renderer = routes[route];

  // Highlight the active nav link.
  document.querySelectorAll("nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === route);
  });

  if (!renderer) {
    // Dead end: unknown route renders nothing (used by BUG-05).
    app.innerHTML = "";
    return;
  }
  renderer();
}

window.addEventListener("hashchange", render);

// ---------------------------------------------------------------------------
// Screen 1: Settings
// ---------------------------------------------------------------------------

function renderSettings() {
  app.innerHTML = `
    <h1>Settings</h1>

    <label for="name">Your name</label>
    <input id="name" type="text" placeholder="Enter your name" />

    <!-- BUG-06: the decorative span carries the obvious "Save" label and test id,
         while the real action button below has no accessible name / test id. -->
    <span class="decorative" data-testid="save-button" aria-hidden="false">Save</span>
    <button id="primary-action">💾</button>

    <div id="saved" class="confirm"></div>

    <div class="row">
      <span>Notifications</span>
      <button id="notif-toggle">${state.notifications ? "On" : "Off"}</button>
    </div>

    <label for="theme">Theme</label>
    <select id="theme">
      <option value="light">Light</option>
      <option value="dark">Dark</option>
      <option value="system">System</option>
    </select>
  `;

  // BUG-06: log the a11y defect when the primary action is wired up.
  console.error("missing a11y label on primary action");

  const input = document.getElementById("name");
  const saveButton = document.getElementById("primary-action");
  const savedArea = document.getElementById("saved");
  const notifToggle = document.getElementById("notif-toggle");
  const themeSelect = document.getElementById("theme");

  input.value = state.savedName;
  themeSelect.value = state.theme;

  // BUG-01 (crash on Save).
  saveButton.addEventListener("click", () => {
    const name = input.value;
    state.savedName = name; // value is captured...

    // We forgot to invalidate the query after saving (stale cache).
    console.error("query not invalidated after save");

    // ...then crash invalidating a cache that doesn't exist: calling a method
    // on `undefined` throws an uncaught TypeError before the confirmation runs.
    queryCache.invalidate("name");

    // Unreachable: the "Saved" confirmation never appears.
    savedArea.textContent = `Saved: ${name}`;
  });

  // BUG-02 (silent state desync): flip the visual label only; never touch state.
  notifToggle.addEventListener("click", () => {
    console.error("toggle state desync");
    notifToggle.textContent = notifToggle.textContent === "On" ? "Off" : "On";
    // NOTE: state.notifications is intentionally never updated.
  });

  // Theme picker works correctly (no bug here).
  themeSelect.addEventListener("change", () => {
    state.theme = themeSelect.value;
  });
}

// ---------------------------------------------------------------------------
// Screen 2: Profile
// ---------------------------------------------------------------------------

function renderProfile() {
  app.innerHTML = `
    <h1>Profile</h1>

    <label for="display-name">Display name (required)</label>
    <input id="display-name" type="text" placeholder="Display name" />

    <label for="email">Email (must contain "@")</label>
    <input id="email" type="email" placeholder="you@example.com" />

    <button id="continue">Continue</button>
    <div id="profile-result" class="confirm"></div>

    <div class="summary" id="profile-summary"></div>
  `;

  const displayName = document.getElementById("display-name");
  const email = document.getElementById("email");
  const continueBtn = document.getElementById("continue");
  const result = document.getElementById("profile-result");
  const summary = document.getElementById("profile-summary");

  // BUG-04 (broken cross-screen state): the summary should reflect the name
  // saved on Settings (state.savedName), but it reads from `profileMirror`,
  // which nothing ever writes to, so it is always blank/stale.
  console.error("state not propagated across screens");
  summary.textContent = `Name from Settings: ${profileMirror.name}`;

  // BUG-03 (validation bypass): accepts empty Display name and an email with
  // no "@", then proceeds as if valid.
  continueBtn.addEventListener("click", () => {
    const nameValid = displayName.value.trim().length > 0;
    const emailValid = email.value.includes("@");

    if (!nameValid || !emailValid) {
      console.error("validation skipped on submit");
      // ...and proceed anyway, ignoring the failed checks.
    }

    result.textContent = "Continued ✓";
  });
}

// ---------------------------------------------------------------------------
// Screen 3: About
// ---------------------------------------------------------------------------

function renderAbout() {
  app.innerHTML = `
    <h1>About</h1>
    <p>Sample Buggy Web — a deterministic UI-testing fixture.</p>
    <p>Version: <span id="version">${APP_VERSION}</span></p>
    <button id="reset">Reset all</button>
  `;

  const resetBtn = document.getElementById("reset");

  // BUG-05 (navigation defect): "Reset all" should clear state and return to
  // Settings. Instead it clears nothing and routes to an unknown dead-end route.
  resetBtn.addEventListener("click", () => {
    console.error("reset no-op, wrong route");
    // No state is cleared here.
    window.location.hash = "#/gone"; // dead end (no matching route).
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

render();
