// Deliberately buggy: the Save button is supposed to show a "Saved" confirmation,
// but it throws before updating the UI. LoopBack should catch this via:
//   - the log tap (console.error + uncaught TypeError), and
//   - verify-after-act (the screen does not change → `changed: false`).
document.getElementById("save").addEventListener("click", () => {
  console.error("query not invalidated after save");
  const result = undefined;
  result.show(); // BUG: TypeError — Cannot read properties of undefined (reading 'show')
  // unreachable:
  document.getElementById("toast").textContent = "Saved";
});
