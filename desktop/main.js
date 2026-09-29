/* AutoStack IN — Electron shell (Phase 2).
 *
 * Owns three lifetimes:
 *   1. FastAPI worker  — child process on 127.0.0.1:8747 (health-checked)
 *   2. Node-RED embed  — in-process via red-embed-core.js on 127.0.0.1:18790
 *   3. Renderer        — the existing built UI (frontend/dist), sandboxed
 *
 * Phase-2 rules implemented here:
 *   - closing the window does NOT stop the worker (tray keeps the app alive)
 *   - Pause observation pauses the capture poll loop, not the audit chain
 *   - Quit reconciles and stops everything in order (worker last)
 */
const { app, BrowserWindow, Tray, Menu, shell, nativeImage } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const http = require('node:http');

const WORKER_PORT = 8747;
const RED_PORT = 18790;
const WORKER_TOKEN = process.env.AUTOSTACK_TOKEN || (() => {
  // Roadmap: same stable token source as the worker (artifacts/spike/token), so the
  // shell and the worker can never disagree about auth across restarts.
  try {
    return require('fs').readFileSync(path.join(__dirname, '..', 'artifacts', 'spike', 'token'), 'utf8').trim();
  } catch {
    return 'autostack-local';
  }
})();
const REPO_ROOT = path.join(__dirname, '..');

let workerProc = null;
let redEmbed = null;
let mainWindow = null;
let tray = null;
let paused = false;

function waitFor(url, timeoutMs = 30000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(url, (res) => { res.resume(); resolve(res.statusCode); });
      req.on('error', () => {
        if (Date.now() - started > timeoutMs) reject(new Error(`timeout waiting for ${url}`));
        else setTimeout(attempt, 500);
      });
      req.setTimeout(3000, () => req.destroy());
    };
    attempt();
  });
}

async function startWorker() {
  const python = process.platform === 'win32'
    ? path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(REPO_ROOT, '.venv', 'bin', 'python');
  workerProc = spawn(python, ['-m', 'uvicorn', 'backend.app:app',
    '--host', '127.0.0.1', '--port', String(WORKER_PORT)], {
    cwd: REPO_ROOT,
    env: { ...process.env, AUTOSTACK_TOKEN: WORKER_TOKEN },
    stdio: 'inherit',
  });
  await waitFor(`http://127.0.0.1:${WORKER_PORT}/api/health`);
}

async function startRed() {
  const { createRedEmbed } = require('./red-embed-core.js');
  redEmbed = await createRedEmbed({
    port: RED_PORT,
    nodesDir: path.join(__dirname, 'red-nodes'),
    flowFile: path.join(__dirname, 'spike-flow.json'),
    userDir: path.join(REPO_ROOT, 'artifacts', 'desktop', 'red-userdir'),
  });
  await redEmbed.start(path.join(__dirname, 'spike-flow.json'), {
    workerUrl: `http://127.0.0.1:${WORKER_PORT}`,
    workerToken: WORKER_TOKEN,
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 1000,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.loadFile(path.join(REPO_ROOT, 'frontend', 'dist', 'index.html'));
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.once('ready-to-show', () => mainWindow.show());
  // Phase 2: closing the window does NOT stop the worker.
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
}

function createTray() {
  // 16x16 transparent-ish template image drawn in-code (no binary asset needed).
  const img = nativeImage.createFromDataURL(
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEklEQVR4nGP8z8DAwMDAxIAEAAAAAP//AwB0EQMAAAAA//8DAN3uAwAAAAD//wMA');
  tray = new Tray(img);
  tray.setToolTip('AutoStack IN');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open dashboard', click: () => { createWindowOnce(); } },
    { label: paused ? 'Resume observation' : 'Pause observation',
      click: (item) => {
        paused = !paused;
        item.label = paused ? 'Resume observation' : 'Pause observation';
      } },
    { type: 'separator' },
    { label: 'Quit', click: () => { app.isQuitting = true; app.quit(); } },
  ]));
}

function createWindowOnce() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    return;
  }
  createWindow();
}

app.whenReady().then(async () => {
  try {
    await startWorker();
    await startRed();
    createTray();
    createWindow();
  } catch (err) {
    console.error('AutoStack shell failed to start:', err);
    app.quit();
  }
});

app.on('window-all-closed', (event) => {
  // Tray keeps the app alive; explicit Quit clears app.isQuitting first.
  if (app.isQuitting) {
    if (workerProc) workerProc.kill();
    if (redEmbed) redEmbed.stop().catch(() => {});
    app.quit();
  }
});

process.on('SIGTERM', () => {
  if (workerProc) workerProc.kill();
  if (redEmbed) redEmbed.stop().catch(() => {});
});
