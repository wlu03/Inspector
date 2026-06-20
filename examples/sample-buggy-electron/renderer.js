// Same bug as the web sample: Save is supposed to show a "Saved" toast but throws
// a TypeError first, so the UI never updates. LoopBack should catch it via the
// renderer console (CDP on --remote-debugging-port) and via verify-after-act.
document.getElementById("save").addEventListener("click", () => {
  console.error("query not invalidated after save");
  const result = undefined;
  result.show(); // BUG: TypeError — Cannot read properties of undefined (reading 'show')
  document.getElementById("toast").textContent = "Saved"; // unreachable
});
