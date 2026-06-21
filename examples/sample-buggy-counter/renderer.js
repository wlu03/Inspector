// Three deterministic, AX/state-observable bugs for Cartographer Phase 0.
let count = 0;
const out = document.getElementById("count");
function render() { out.textContent = String(count); }

document.getElementById("minus").addEventListener("click", () => { count -= 1; render(); });
// BUG-01 (LOGIC_ARITHMETIC): Plus increments by 2 instead of 1.
document.getElementById("plus").addEventListener("click", () => { count += 2; render(); });
// BUG-02 (LOGIC_ARITHMETIC): Reset sets the count to 1 instead of 0.
document.getElementById("reset").addEventListener("click", () => { count = 1; render(); });

// BUG-03 (STATE_SYNC): the toggle's visible label flips, but aria-pressed (its backing
// state) is never updated — the control and its state disagree.
let on = false;
const notif = document.getElementById("notif");
notif.addEventListener("click", () => {
  on = !on;
  notif.textContent = on ? "On" : "Off";   // label flips
  // intentionally NOT: notif.setAttribute("aria-pressed", String(on));
});
