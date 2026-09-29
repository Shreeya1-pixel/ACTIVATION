/* Isolated synthetic browser proof + visual reference capture. Never uses a personal browser profile. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const {createHash} = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.AUTOSTACK_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..', '..');
const frontend = path.join(root, 'frontend');
const evidence = path.join(root, 'artifacts', 'phase-1');
const checks = [];
const screenshots = [];
let context, vite, profile;
const servers = [];

async function startFixtureServer(port) {
  const html = await fs.readFile(path.join(root, 'tests', 'fixtures', 'office.html'));
  const js = await fs.readFile(path.join(root, 'tests', 'fixtures', 'office.js'));
  const server = http.createServer((req, res) => {
    const file = req.url === '/office.js' ? js : ['/office.html', '/other.html'].includes(req.url) ? html : null;
    res.writeHead(file ? 200 : 404, {'Content-Type': req.url === '/office.js' ? 'application/javascript' : 'text/html',
      'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'});
    res.end(file || 'Not found');
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  servers.push(server);
}

async function main() {
  await fs.mkdir(evidence, {recursive: true});
  // Replace a previous report before starting, so a failed rerun cannot leave a stale PASS summary.
  await fs.writeFile(path.join(evidence, 'browser-report.json'), JSON.stringify({status: 'in_progress'}));
  await startFixtureServer(4174);
  await startFixtureServer(4175);
  const {createServer} = await import(pathToFileURL(path.join(frontend, 'node_modules/vite/dist/node/index.js')).href);
  vite = await createServer({root: frontend, server: {host: '127.0.0.1', port: 5173, strictPort: true}});
  await vite.listen();
  profile = await fs.mkdtemp(path.join(evidence, 'browser-profile-'));
  const extension = path.join(root, 'browser-extension');
  context = await chromium.launchPersistentContext(profile, {channel: 'chromium', headless: true, chromiumSandbox: true,
    viewport: {width: 1440, height: 1000},
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`]});
  const browserVersion = context.browser().version();
  const blockedExternal = new Set();
  await context.route(/^https?:/, (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === '127.0.0.1') return route.continue();
    blockedExternal.add(url.origin);
    return route.abort();
  });
  const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
  const events = () => worker.evaluate(async () => (await chrome.storage.local.get('events')).events || []);
  const expectCount = async (count) => {
    for (let i = 0; i < 50; i++) {
      if ((await events()).length === count) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.equal((await events()).length, count);
  };
  const expectNoNew = async (count, name) => {
    await new Promise(resolve => setTimeout(resolve, 200));
    assert.equal((await events()).length, count, name);
    checks.push(name);
  };
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:4174/office.html');
  // document_idle injection must have finished before the first test interaction.
  await page.waitForLoadState('networkidle');
  await page.locator('#save').click();
  await expectNoNew(0, 'save without an opened record is not a successful observation');
  await page.locator('#open').click();
  await expectCount(1);
  await page.locator('#private-input').fill('invented-secret-negative-test');
  await page.locator('#draft').fill('Synthetic follow-up body, not collected by the extension.');
  await expectNoNew(1, 'password and draft typing are not collected');
  await page.locator('#open').evaluate(button => button.click());
  await expectNoNew(1, 'page-script clicks are not counted as browser input');
  await page.locator('#save').click();
  await expectCount(2);
  assert.equal(await page.evaluate(() => localStorage.getItem('autostack-sample-draft:C001')),
    'Synthetic follow-up body, not collected by the extension.');
  await page.locator('#client').selectOption('C003');
  await page.locator('#open').click();
  await expectCount(3);
  await page.locator('#draft').fill('Another invented draft.');
  await page.locator('#save').click();
  await expectCount(4);
  const captured = await events();
  assert.deepEqual(captured.map(({action, record_key}) => [action, record_key]), [
    ['record_opened', 'sample:C001'], ['draft_saved', 'sample:C001'],
    ['record_opened', 'sample:C003'], ['draft_saved', 'sample:C003'],
  ]);
  assert(!JSON.stringify(captured).match(/invented-secret|follow-up body|example\.invalid/));
  checks.push('four real DOM action observations match the independent expected sequence and omit field values');
  await page.locator('#draft').fill('');
  await page.locator('#save').click();
  await expectNoNew(4, 'empty draft is not a successful save');
  await page.locator('#draft').fill('Storage should fail.');
  await page.evaluate(() => { Storage.prototype.setItem = () => { throw new Error('simulated storage failure'); }; });
  await page.locator('#save').click();
  await expectNoNew(4, 'failed storage is not a successful save');
  for (const url of ['http://127.0.0.1:4174/other.html', 'http://127.0.0.1:4175/office.html']) {
    await page.goto(url);
    await page.waitForLoadState('networkidle');
    await page.locator('#open').click();
    await expectNoNew(4, `capture is disabled on ${url}`);
  }
  const exportPath = path.join(evidence, 'capture-events.json');
  await fs.writeFile(exportPath, JSON.stringify(captured, null, 2));
  const validation = spawnSync(process.env.AUTOSTACK_PYTHON || 'python', ['-m', 'backend.validate_events', exportPath],
    {cwd: root, encoding: 'utf8'});
  assert.equal(validation.status, 0, validation.stderr || String(validation.error || 'event validation failed'));
  checks.push('exported events pass the versioned JSON Schema and duplicate-ID validation');

  const uiErrors = [];
  page.on('pageerror', error => uiErrors.push(error.message));
  await page.goto('http://127.0.0.1:5173');
  await page.locator('.sidebar').waitFor();
  await page.evaluate(() => document.fonts.ready);
  async function snap(name) {
    await page.screenshot({path: path.join(evidence, `${name}.png`), fullPage: true, animations: 'disabled'});
    screenshots.push(name);
  }
  for (const [label, filename] of [['Dashboard', 'dashboard'], ['Discovery', 'discovery'], ['Registry', 'registry'],
    ['Workflows', 'workflows'], ['Create Automation', 'create'], ['Trust Log', 'trust-log']]) {
    await page.locator('.nav').getByRole('button', {name: label, exact: true}).click();
    await snap(filename);
    if (label === 'Discovery') { await page.locator('.candidate-card').first().click(); await snap('discovery-detail'); }
    if (label === 'Registry') { await page.locator('.registry-item').first().click(); await snap('registry-detail'); }
    if (label === 'Workflows') { await page.locator('tbody tr').first().click(); await snap('workflow-detail'); }
    if (label === 'Create Automation') {
      for (let step = 1; step < 5; step++) { await page.locator('.step-item').nth(step).click(); await snap(`create-step-${step + 1}`); }
    }
  }
  assert.deepEqual(uiErrors, []);
  await expectNoNew(4, 'the existing React dashboard is outside the observation allowlist');
  checks.push('six original React screens, three details and all five creation steps render without page errors');
  const hashes = {};
  for (const name of ['frontend/src/main.jsx', 'frontend/src/styles.css']) {
    hashes[name] = createHash('sha256').update(await fs.readFile(path.join(root, name))).digest('hex');
  }
  const report = {status: 'passed', recorded_at: new Date().toISOString(), platform: process.platform,
    node: process.version, chromium: browserVersion, mode: 'automated browser fixture test; not a human acceptance test',
    viewport: {width: 1440, height: 1000}, checks, event_count: captured.length, screenshots,
    source_sha256: hashes, external_requests_blocked: [...blockedExternal],
    limitations: ['No human workflow acceptance yet', 'No desktop observer, detector, runner, or execution',
      'DOM signals are observations, not authorization', 'Offline font fallback baseline', 'Windows only']};
  await fs.writeFile(path.join(evidence, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}

main().catch(async error => {
  console.error(error);
  await fs.mkdir(evidence, {recursive: true});
  await fs.writeFile(path.join(evidence, 'browser-report.json'), JSON.stringify({status: 'failed', checks, error: error.message}, null, 2));
  process.exitCode = 1;
}).finally(async () => {
  if (context) await context.close();
  if (vite) await vite.close();
  for (const server of servers) await new Promise(resolve => server.close(resolve));
  if (profile) {
    // Before recursive cleanup, verify the actual generated directory stays inside our evidence directory.
    const actual = await fs.realpath(profile);
    const base = await fs.realpath(evidence);
    if (path.dirname(actual) !== base || !path.basename(actual).startsWith('browser-profile-')) {
      throw new Error('Refusing cleanup outside the generated test profile directory');
    }
    await fs.rm(actual, {recursive: true, force: true, maxRetries: 3});
  }
});
