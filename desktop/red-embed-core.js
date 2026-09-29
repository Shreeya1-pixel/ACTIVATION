/* Node-RED embed core (shared by the spike harness and the Electron shell).
 *
 * Boots an embedded Node-RED runtime in the CURRENT process with our custom bridge
 * nodes from red-nodes/, mounting RED.httpAdmin / RED.httpNode on an express app
 * (RED.init only prepares the routers — the embedder must attach them).
 *
 * Returns { start, stop, server } so the Electron main process owns the lifecycle.
 */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const express = require('express'); // resolves from desktop/node_modules (node-red dep)

async function createRedEmbed({ port = 18790, host = '127.0.0.1', nodesDir, flowFile, userDir } = {}) {
  const RED = require('node-red');
  const app = express();
  const server = http.createServer(app);

  const settings = {
    uiHost: host,
    uiPort: port,
    userDir,
    nodesDir,
    flowFile,
    httpAdminRoot: '/admin-api',
    httpNodeRoot: '/',
    editorTheme: { enabled: false, tours: false },
    runtimeState: { enabled: false, ui: false },
    logging: { console: { level: 'warn' } },
    externalModules: { autoInstall: false },
    functionExternalModules: false,
    // The Function-node sandbox does not expose global fetch by default; provide it
    functionGlobalContext: {
      fetch: globalThis.fetch,
      Headers: globalThis.Headers,
      Request: globalThis.Request,
      Response: globalThis.Response,
    },
  };

  RED.init(server, settings); // prepares RED.httpAdmin / RED.httpNode; does NOT mount them
  app.use(settings.httpAdminRoot, RED.httpAdmin);
  app.use('/', RED.httpNode);

  let deployedFlows = null;

  async function start(flows, creds) {
    await RED.start();
    if (flows) {
      let loaded = JSON.parse(fs.readFileSync(flows, 'utf8'));
      if (creds && creds.workerToken) {
        // Inject live credentials at start time (same contract as red-embed.js),
        // then persist the injected copy to a gitignored runtime file under the
        // user dir — NEVER back to the tracked template, which keeps placeholders.
        loaded = loaded.map((node) => {
          if (node.type === 'tab' && Array.isArray(node.env)) {
            return { ...node, env: node.env.map((e) => {
              if (e.name === 'WORKER_URL' && e.type === 'str') return { ...e, value: creds.workerUrl };
              if (e.name === 'WORKER_TOKEN' && e.type === 'str') return { ...e, value: creds.workerToken };
              return e;
            }) };
          }
          if (node.type && node.type.startsWith('as-')) {
            return { ...node, workerUrl: creds.workerUrl, workerToken: creds.workerToken };
          }
          return node;
        });
        fs.mkdirSync(userDir, { recursive: true });
        settings.flowFile = path.join(userDir, 'runtime-flow.json');
        fs.writeFileSync(settings.flowFile, JSON.stringify(loaded, null, 2));
      }
      deployedFlows = loaded;
      await RED.nodes.setFlows(loaded, 'full');
    }
    // Wait until the admin API answers with the deployed tab ids (ready probe).
    for (let attempt = 0; attempt < 20; attempt++) {
      try {
        const ok = await new Promise((resolve) => {
          const req = http.get({ host, port, path: '/admin-api/flows', timeout: 3000 }, (res) => {
            let body = '';
            res.on('data', (c) => { body += c; });
            res.on('end', () => resolve(res.statusCode === 200));
          });
          req.on('error', () => resolve(false));
          req.on('timeout', () => { req.destroy(); resolve(false); });
        });
        if (ok) break;
      } catch { /* retry */ }
      await new Promise((r) => setTimeout(r, 500));
    }
    return { url: `http://${host}:${port}` };
  }

  async function stop() {
    await RED.stop();
    server.close();
  }

  return { start, stop, server, settings };
}

module.exports = { createRedEmbed };
