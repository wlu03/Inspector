const { app, BrowserWindow } = require("electron");

app.commandLine.appendSwitch("remote-debugging-port", "9223");

function createWindow() {
  const win = new BrowserWindow({
    width: 720,
    height: 520,
    title: "Sample Buggy Counter",
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.loadFile("index.html");
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
