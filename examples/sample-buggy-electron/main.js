const { app, BrowserWindow } = require("electron");
const path = require("path");

// Expose the renderer's DevTools/console over CDP so an external testing agent
// can observe console.error and uncaught errors. Must be set before app ready.
app.commandLine.appendSwitch("remote-debugging-port", "9223");

function createWindow() {
  const win = new BrowserWindow({
    width: 800,
    height: 600,
    title: "Sample Buggy Electron",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile("index.html");
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
