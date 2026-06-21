// Acme Workspace — a deliberately buggy multi-screen app used as an Inspector test
// fixture. Each screen plants a DIFFERENT class of bug so the agent's oracles get a
// full workout. Bug IDs below map 1:1 to bugs.json. KEEP THESE BUGS — they're the point.

const store = {
  profile: { username: "", email: "" },
  notifications: false,
  tasks: [
    { id: 1, text: "Review Q3 report", done: false },
    { id: 2, text: "Email the design team", done: true },
  ],
  cart: [
    { id: 1, name: "Pro Plan (seat)", price: 12.0, qty: 2 },
    { id: 2, name: "Extra storage 50GB", price: 4.5, qty: 1 },
  ],
  team: [
    { name: "Wesley Lu", email: "wesley@acme.co" },
    { name: "Dana Kim", email: "dana@acme.co" },
  ],
};

// theme is INTENTIONALLY view-local, not in the store → see BUG-04
let pendingTheme = "system";

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");

function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast"), 1800);
}

// ---------- views ----------

function dashboard() {
  // BUG-05 surfaces here too: "active" counts completed tasks.
  const active = store.tasks.length; // should be tasks.filter(t => !t.done).length
  const cartItems = store.cart.reduce((n, i) => n + i.qty, 0);
  view.innerHTML = `
    <h1>Dashboard</h1>
    <p class="sub">Welcome back. Here's your workspace at a glance.</p>
    <div class="stat-grid">
      <div class="stat"><div class="n">${active}</div><div class="l">Active tasks</div></div>
      <div class="stat"><div class="n">${cartItems}</div><div class="l">Items in cart</div></div>
      <div class="stat"><div class="n">${store.notifications ? "On" : "Off"}</div><div class="l">Notifications</div></div>
    </div>
    <div class="card" style="margin-top:18px">
      <h2>Quick actions</h2>
      <div class="row">
        <button onclick="location.hash='#/tasks'">Go to Tasks</button>
        <button class="ghost" onclick="location.hash='#/cart'">View Cart</button>
      </div>
    </div>`;
}

function settings() {
  view.innerHTML = `
    <h1>Settings</h1>
    <p class="sub">Manage your account and preferences.</p>
    <div class="card">
      <h2>Profile name</h2>
      <div class="field"><label for="name">Display name</label>
        <input id="name" placeholder="Your name" value="${store.profile.username}" /></div>
      <button id="save">Save</button>
    </div>
    <div class="card">
      <h2>Notifications</h2>
      <div class="toggle ${store.notifications ? "on" : ""}" id="notif">
        <span class="track"><span class="knob"></span></span>
        <span id="notif-label">${store.notifications ? "On" : "Off"}</span>
      </div>
    </div>
    <div class="card">
      <h2>Theme</h2>
      <select id="theme">
        <option value="system" ${pendingTheme === "system" ? "selected" : ""}>System</option>
        <option value="light" ${pendingTheme === "light" ? "selected" : ""}>Light</option>
        <option value="dark" ${pendingTheme === "dark" ? "selected" : ""}>Dark</option>
      </select>
      <p class="muted" style="margin-top:8px">Theme applies across the app.</p>
    </div>`;

  // BUG-01 (KEEP): Save throws a TypeError before the toast → UI never confirms.
  $("#save").addEventListener("click", () => {
    console.error("query not invalidated after save");
    const result = undefined;
    result.show(); // TypeError — Cannot read properties of undefined (reading 'show')
    store.profile.username = $("#name").value;
    toast("Saved");
  });

  // BUG-08: toggle flips the visual + label but never updates store.notifications,
  // so the Dashboard + the persisted state disagree with what the UI shows.
  $("#notif").addEventListener("click", () => {
    const el = $("#notif");
    const nowOn = !el.classList.contains("on");
    el.classList.toggle("on", nowOn);
    $("#notif-label").textContent = nowOn ? "On" : "Off";
    // store.notifications = nowOn;  // <-- the missing line
  });

  // BUG-04: theme is stored in a view-local var, so navigating away and back resets it.
  $("#theme").addEventListener("change", (e) => {
    pendingTheme = e.target.value;
    toast("Theme set to " + e.target.value);
  });
}

function profile() {
  view.innerHTML = `
    <h1>Profile</h1>
    <p class="sub">Your public details.</p>
    <div class="card">
      <div class="field"><label for="username">Username</label>
        <input id="username" placeholder="e.g. Wesley Lu" value="${store.profile.username}" /></div>
      <div class="field"><label for="email">Email</label>
        <input id="email" placeholder="you@example.com" value="${store.profile.email}" /></div>
      <button id="psave">Save profile</button>
    </div>`;

  // BUG-02: the input handler silently strips spaces, so what's typed != what's stored
  // (type "Wesley Lu" → the field holds "WesleyLu"). Input-integrity oracle bait.
  $("#username").addEventListener("input", (e) => {
    e.target.value = e.target.value.replace(/\s+/g, "");
  });

  // BUG-03: "validation" accepts anything — no @, empty, whatever — and reports success.
  $("#psave").addEventListener("click", () => {
    const email = $("#email").value;
    const looksValid = email.length >= 0; // always true — validation bypass
    if (looksValid) {
      store.profile.username = $("#username").value;
      store.profile.email = email;
      toast("Profile saved");
    } else {
      toast("Invalid email", true);
    }
  });
}

function tasks() {
  const render = () => {
    // BUG-05: the badge counts ALL tasks, not just the active (not-done) ones.
    const activeCount = store.tasks.length; // should filter !t.done
    const items = store.tasks
      .map(
        (t) => `<li>
          <input type="checkbox" data-id="${t.id}" ${t.done ? "checked" : ""} />
          <span class="grow ${t.done ? "done" : ""}">${t.text}</span>
          <button class="ghost sm" data-del="${t.id}">Delete</button>
        </li>`
      )
      .join("");
    view.innerHTML = `
      <h1>Tasks <span class="badge amber">${activeCount} active</span></h1>
      <p class="sub">Track what needs doing.</p>
      <div class="card">
        <div class="row">
          <input id="newtask" placeholder="Add a task…" />
          <button id="addtask">Add</button>
        </div>
        <ul class="list">${items || '<li class="muted">No tasks yet.</li>'}</ul>
      </div>`;

    $("#addtask").addEventListener("click", () => {
      const text = $("#newtask").value.trim();
      if (!text) return;
      store.tasks.push({ id: Date.now(), text, done: false });
      render();
      refreshNav();
    });
    view.querySelectorAll("[data-id]").forEach((cb) =>
      cb.addEventListener("change", (e) => {
        const t = store.tasks.find((x) => x.id == e.target.dataset.id);
        if (t) t.done = e.target.checked;
        render();
        refreshNav();
      })
    );
    view.querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", (e) => {
        store.tasks = store.tasks.filter((x) => x.id != e.target.dataset.del);
        render();
        refreshNav();
      })
    );
  };
  render();
}

function cart() {
  const render = () => {
    // BUG-06: total sums QUANTITIES and forgets to multiply by price.
    const total = store.cart.reduce((sum, i) => sum + i.qty, 0); // should be i.price * i.qty
    const rows = store.cart
      .map(
        (i) => `<li>
          <span class="grow">${i.name} <span class="muted">($${i.price.toFixed(2)})</span></span>
          <button class="ghost sm" data-dec="${i.id}">−</button>
          <span class="price">${i.qty}</span>
          <button class="ghost sm" data-inc="${i.id}">+</button>
        </li>`
      )
      .join("");
    view.innerHTML = `
      <h1>Cart</h1>
      <p class="sub">Review your order.</p>
      <div class="card">
        <ul class="list">${rows || '<li class="muted">Your cart is empty.</li>'}</ul>
        <div class="row" style="justify-content:space-between;margin-top:14px">
          <span class="muted">Total</span><span class="total price">$${total.toFixed(2)}</span>
        </div>
      </div>
      <button id="checkout">Place order</button>`;

    view.querySelectorAll("[data-inc]").forEach((b) =>
      b.addEventListener("click", (e) => {
        const i = store.cart.find((x) => x.id == e.target.dataset.inc);
        if (i) i.qty++;
        render();
        refreshNav();
      })
    );
    view.querySelectorAll("[data-dec]").forEach((b) =>
      b.addEventListener("click", (e) => {
        const i = store.cart.find((x) => x.id == e.target.dataset.dec);
        if (i && i.qty > 0) i.qty--;
        render();
        refreshNav();
      })
    );
    // BUG-07: checkout succeeds even with an empty cart (no validation).
    $("#checkout").addEventListener("click", () => {
      toast("Order placed! 🎉");
      store.cart = [];
      render();
      refreshNav();
    });
  };
  render();
}

function billing() {
  view.innerHTML = `
    <h1>Billing</h1>
    <p class="sub">Manage your subscription and payment method.</p>
    <div class="card">
      <h2>Plan</h2>
      <p>You're on the <span class="badge green">Pro</span> plan — $24/mo.</p>
      <button class="danger" id="cancel">Cancel subscription</button>
    </div>
    <div class="card">
      <h2>Payment method</h2>
      <div class="field"><label for="card">Card number</label>
        <input id="card" placeholder="•••• •••• •••• 4242" /></div>
      <button id="updcard">Update card</button>
    </div>`;

  // BUG-10: the primary "Cancel subscription" action is dead — no handler, nothing happens.
  // (intentionally no listener attached to #cancel)

  $("#updcard").addEventListener("click", () => toast("Card updated"));
}

function about() {
  // BUG-09: an "Export data" button is part of this screen's spec (see README + the
  // commented markup below) but the render omits it — the missing-element oracle flags it.
  view.innerHTML = `
    <h1>About</h1>
    <p class="sub">Acme Workspace · v2.0.0</p>
    <div class="card">
      <h2>Your data</h2>
      <p class="muted">Download a copy of everything in your workspace.</p>
      <div class="row" id="data-actions">
        <button class="ghost" id="check">Check for updates</button>
        <!-- expected here: <button id="export">Export data</button> -->
      </div>
    </div>`;
  $("#check").addEventListener("click", () => toast("You're up to date"));
}

function reports() {
  const done = store.tasks.filter((t) => t.done).length;
  // BUG-11: completion rate divides done by done (always 100%) instead of done/total.
  const rate = done ? Math.round((done / done) * 100) : 0; // should be done/store.tasks.length
  const revenue = store.cart.reduce((s, i) => s + i.price * i.qty, 0);
  view.innerHTML = `
    <h1>Reports</h1>
    <p class="sub">Workspace analytics.</p>
    <div class="stat-grid">
      <div class="stat"><div class="n">${rate}%</div><div class="l">Task completion</div></div>
      <div class="stat"><div class="n">$${revenue.toFixed(2)}</div><div class="l">Cart value</div></div>
      <div class="stat"><div class="n">${store.team.length}</div><div class="l">Team members</div></div>
    </div>
    <div class="card" style="margin-top:18px"><h2>Notes</h2>
      <p class="muted">Task completion should be completed ÷ total tasks.</p></div>`;
}

function team() {
  const render = () => {
    const rows = store.team
      .map(
        (m, idx) => `<li>
          <span class="grow">${m.name || "(no name)"} <span class="muted">${m.email || "—"}</span></span>
          <button class="ghost sm" data-rm="${idx}">Remove</button>
        </li>`
      )
      .join("");
    view.innerHTML = `
      <h1>Team <span class="badge">${store.team.length}</span></h1>
      <p class="sub">Manage who has access.</p>
      <div class="card">
        <div class="row">
          <input id="invite" placeholder="teammate@example.com" />
          <button id="add-member">Invite</button>
        </div>
        <ul class="list">${rows}</ul>
      </div>`;

    // BUG-12: invite accepts an empty/invalid email and adds a blank member anyway.
    $("#add-member").addEventListener("click", () => {
      store.team.push({ name: "New member", email: $("#invite").value });
      toast("Invite sent");
      render();
      refreshNav();
    });

    // BUG-13: Remove always drops the FIRST member, ignoring which row was clicked.
    view.querySelectorAll("[data-rm]").forEach((b) =>
      b.addEventListener("click", () => {
        store.team.shift(); // should splice the clicked index
        render();
        refreshNav();
      })
    );
  };
  render();
}

// ---------- router ----------

const routes = { dashboard, settings, profile, tasks, cart, billing, reports, team, about };

function refreshNav() {
  const route = location.hash.replace("#/", "") || "dashboard";
  document.querySelectorAll("#nav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.route === route)
  );
  $("#nav-task-count").textContent = store.tasks.length || "";
  $("#nav-cart-count").textContent = store.cart.reduce((n, i) => n + i.qty, 0) || "";
}

function router() {
  const name = location.hash.replace("#/", "") || "dashboard";
  (routes[name] || dashboard)();
  refreshNav();
}

window.addEventListener("hashchange", router);
router();
