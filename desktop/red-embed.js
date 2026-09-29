/* Spike S4 orchestrator: embed Node-RED with our nodes, mount its middleware (the embedder
 * MUST attach RED.httpAdmin / RED.httpNode itself — RED.init only prepares them), deploy
 * spike-flow.json with worker credentials injected, and KEEP RUNNING while
 * tests/spike/test_s4_end_to_end.py drives POST /spike/run.
 *
 * Requires the worker already running on :8747.
 * Usage: node red-embed.js <workerUrl> <workerToken> <flowFile>
 */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const express = require('express'); // resolves from desktop/node_modules (node-red dep)

const [, , workerUrl, workerToken, flowFileArg] = process.argv;
if (!workerUrl || !workerToken || !flowFileArg) {
  console.error('usage: node red-embed.js <workerUrl> <workerToken> <flowFile>');
  process.exit(2);
}

const RED = require('node-red');
const flowFile = path.resolve(process.cwd(), flowFileArg);
const userDir = path.join(__dirname, '..', 'artifacts', 'spike', 'red-userdir');
fs.mkdirSync(userDir, { recursive: true });

// Inject credentials into bridge nodes AND tab env at deploy time (Milestone A moves
// this to the compiler). Function nodes read WORKER_URL/WORKER_TOKEN from tab env,
// so those must carry the SAME real credentials the as-* nodes receive.
const flows = JSON.parse(fs.readFileSync(flowFile, 'utf8')).map((node) => {
  if (node.type && node.type === 'tab' && Array.isArray(node.env)) {
    return { ...node, env: node.env.map((e) => {
      if (e.name === 'WORKER_URL' && e.type === 'str') return { ...e, value: workerUrl };
      if (e.name === 'WORKER_TOKEN' && e.type === 'str') return { ...e, value: workerToken };
      return e;
    }) };
  }
  if (node.type && node.type.startsWith('as-')) {
    return { ...node, workerUrl, workerToken };
  }
  return node;
});

const SETTINGS = {
  uiHost: '127.0.0.1',
  uiPort: 18790,
  userDir,
  nodesDir: path.join(__dirname, 'red-nodes'),
  // Node-RED writes whatever it was given (including the injected credentials) back
  // to SETTINGS.flowFile on deploy. Point that at a gitignored runtime copy so the
  // tracked template (desktop/spike-flow.json) keeps its __WORKER_TOKEN__
  // placeholders and never collects live secrets.
  flowFile: path.join(userDir, 'runtime-flow.json'),
  httpAdminRoot: '/admin-api',
  httpNodeRoot: '/',
  editorTheme: { enabled: false, tours: false },
  runtimeState: { enabled: false, ui: false },
  logging: { console: { level: 'warn' } },
  externalModules: { autoInstall: false },
  functionExternalModules: false,
  // The Function-node sandbox does not expose global fetch by default; provide it
  // (Node 18+ global) so bridge-start can call the worker.
  functionGlobalContext: {
    fetch: globalThis.fetch,
    Headers: globalThis.Headers,
    Request: globalThis.Request,
    Response: globalThis.Response,
  },
};

const app = express();
const server = http.createServer(app);
RED.init(server, SETTINGS); // prepares RED.httpAdmin / RED.httpNode; does NOT mount them
app.use(SETTINGS.httpAdminRoot, RED.httpAdmin);
app.use('/', RED.httpNode);

async function ensureWorkflowRegistered() {
  // The spike flow calls bridge-start with workflow_id=wf_client_followup; register it
  // (idempotent) so the worker can version+hash the graph.
  const graph = {
    id: 'wf_client_followup', name: 'Client Follow-up (spike)',
    triggers: [{ type: 'schedule', cron: '0 9 * * MON-FR' }],
    nodes: [
      { id: 'src', type: 'file.read_table', params: { alias: 'sample-tracking-file', max_rows: 1000 } },
      { id: 'due', type: 'data.filter', params: { from: 'src.rows', where: 'due' } },
      { id: 'upd', type: 'file.update_rows', params: { alias: 'sample-tracking-file',
        filename: 'clients.csv', set: 'Draft prepared', purpose: 'followup' } },
      { id: 'drft', type: 'draft.create', params: { record_key: '{{row}}',
        template_id: 'followup_en', destination: 'in_app' } },
      { id: 'note', type: 'notify.desktop', params: { title_key: 'run_done' } },
    ],
    edges: [
      { from: 'src', to: 'due' }, { from: 'due', to: 'upd' },
      { from: 'upd', to: 'drft' }, { from: 'drft', to: 'note' },
    ],
  };
  const res = await fetch(`${workerUrl}/api/workflows`, {
    method: 'POST', headers: { 'Content-Type': 'application/json',
      Authorization: `Bearer ${workerToken}` },
    body: JSON.stringify({ id: graph.id, name: graph.name, graph }) });
  if (!res.ok) throw new Error(`workflow register failed: ${res.status} ${await res.text()}`);
  const data = await res.json();
  console.log(`WORKFLOW_REGISTERED v${data.version} artifact=${data.artifact_sha256.slice(0, 12)}…`);
}

server.listen(SETTINGS.uiPort, '127.0.0.1', async () => {
  try {
    await ensureWorkflowRegistered();
    await RED.start();
    await RED.nodes.setFlows(flows, 'full');
    // Readiness probe WITHOUT side effects: the admin flows API reflects the deployed
    // flow once the runtime has started and node routes are bound. (Probing /spike/run
    // itself would trigger a real run before the test can stage its fixture.)
    let probe = null;
    for (let attempt = 0; attempt < 20; attempt++) {
      probe = await new Promise((resolve, reject) => {
        const req = http.request({ host: '127.0.0.1', port: SETTINGS.uiPort, path: '/admin-api/flows',
          method: 'GET', timeout: 4000 },
          (res) => { let body = ''; res.on('data', (c) => { body += c; });
            res.on('end', () => resolve({ status: res.statusCode, body })); });
        req.on('error', reject);
        req.on('timeout', () => { req.destroy(); reject(new Error('probe timeout')); });
        req.end();
      }).catch((err) => ({ status: 0, body: String(err.message) }));
      if (probe.status === 200 && probe.body.includes('tab-spike')) break;
      await new Promise((r) => setTimeout(r, 500));
    }
    const deployed = probe.status === 200 && probe.body.includes('tab-spike');
    console.log(`SELF_PROBE ${probe.status} flows-deployed=${deployed}`);
    if (!deployed) throw new Error(`flows never deployed: ${probe.body.slice(0, 160)}`);
    await new Promise((r) => setTimeout(r, 1000)); // grace for httpNode route binding
    console.log('NODE_RED_READY');
  } catch (err) {
    console.error('NODE_RED_FAILED', err);
    process.exit(1);
  }
});

process.on('SIGINT', async () => { await RED.stop(); process.exit(0); });
process.on('SIGTERM', async () => { await RED.stop(); process.exit(0); });
