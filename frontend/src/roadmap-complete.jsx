// Roadmap completion pages: Notifications Center, Data & Privacy, Connectors.
// Every value shown is real backend state; connector statuses are measured live
// by the worker, never hardcoded (project rule: no invented anything).
import { useState } from 'react';
import { Terminal, Card, Row, Gate, stamp } from './main-shared.jsx';
import { api } from './api.js';

// ── Notifications Center ──────────────────────────────────────────────────────
// Full page behind the bell: real notification rows with filter + read states
// and mark-all-read. Filters use only fields the API actually returns.

export function NotificationCenter() {
  const [notes, setNotes] = useState(null);
  const [filter, setFilter] = useState('all');
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try { setNotes(await api.notifications()); }
    catch (e) { setErr(e.message); }
  }
  useState(() => { refresh(); });

  const visible = (notes || []).filter(n => {
    if (filter === 'unread') return !n.read_at;
    if (filter === 'read') return !!n.read_at;
    if (filter === 'detection') return /detect|candidate|pattern/i.test(n.title + ' ' + n.body);
    return true;
  });
  const unreadCount = (notes || []).filter(n => !n.read_at).length;

  async function markAll() {
    setBusy(true);
    try {
      await api.markAllNotificationsRead();
      await refresh();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }
  async function markOne(id) {
    try { await api.markNotificationRead(id); await refresh(); }
    catch (e) { setErr(e.message); }
  }

  return (
    <div className="screen">
      <header className="screen-head">
        <div>
          <h1>Notifications</h1>
          <p className="muted">{unreadCount} unread · filters over real rows only — nothing here is simulated.</p>
        </div>
        <button className="btn" onClick={markAll} disabled={busy || !notes || unreadCount === 0}>Mark all read</button>
      </header>
      {err && <div className="error">{err}</div>}
      <div className="tier-buttons">
        {['all', 'unread', 'read', 'detection'].map(f => (
          <button key={f} className={`chip ${filter === f ? 'on' : ''}`} onClick={() => setFilter(f)}>{f}</button>
        ))}
      </div>
      <div className="card">
        {!notes && <div className="muted">Loading…</div>}
        {notes && visible.length === 0 && <div className="muted">No notifications match this filter.</div>}
        {notes && visible.map(n => (
          <Row key={n.id}>
            <div className={`note ${n.read_at ? 'read' : 'unread'}`}>
              <div>
                <strong>{n.title}</strong>
                <div className="muted">{n.body}</div>
                <div className="muted small">{n.created_at}{n.read_at ? ` · read ${n.read_at}` : ''}</div>
              </div>
              {!n.read_at && <button className="link" onClick={() => markOne(n.id)}>mark read</button>}
            </div>
          </Row>
        ))}
      </div>
    </div>
  );
}

// ── Data & Privacy ────────────────────────────────────────────────────────────
// README consent/retention commitments made real: retention windows enforced
// server-side with bounds (invalid values are refused, not clamped), a portable
// data export, and the consent ledger computed from real recorded decisions.

export function DataPrivacy() {
  const [retention, setRetention] = useState(null);
  const [caps, setCaps] = useState(null);
  const [obs, setObs] = useState('');
  const [rep, setRep] = useState('');
  const [ledger, setLedger] = useState(null);
  const [result, setResult] = useState(null);
  const [exportData, setExportData] = useState(null);
  const [err, setErr] = useState(null);

  async function refresh() {
    try {
      const r = await api.privacyRetention();
      setRetention(r);
      setObs(String(r.retention.observations_days));
      setRep(String(r.retention.reports_days));
      setLedger(await api.privacyLedger());
      setCaps(await api.capabilities());
    } catch (e) { setErr(e.message); }
  }
  useState(() => { refresh(); });

  async function saveRetention() {
    setResult(null);
    try {
      const r = await api.setRetention(parseInt(obs, 10), parseInt(rep, 10));
      setRetention(r);
      setResult(`Saved: observations ${r.retention.observations_days}d · reports ${r.retention.reports_days}d. The audit ledger is never deleted.`);
    } catch (e) { setResult(e.message); }
  }

  async function doExport() {
    setResult(null);
    try {
      const data = await api.privacyExport();
      setExportData(data);
      setResult(`Export ready — ${data.drafts.length} drafts, ${data.runs.length} runs (shown in the console output).`);
    } catch (e) { setResult(e.message); }
  }

  function downloadExport() {
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `autostack-export-${exportData.exported_at.slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="screen">
      <header className="screen-head">
        <div>
          <h1>Data &amp; Privacy</h1>
          <p className="muted">Retention, export, and the consent ledger — enforced on the worker, mirrored here.</p>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      {result && <div className="muted">{result}</div>}

      <div className="grid2">
        <Gate capability="retention_admin" caps={caps}>
          <Card title="Retention windows (days)">
            <div className="field">
              <label>Observations (default 30, 7–3650)</label>
              <input value={obs} onChange={e => setObs(e.target.value)} />
            </div>
            <div className="field">
              <label>Reports &amp; history (default 90, 7–3650)</label>
              <input value={rep} onChange={e => setRep(e.target.value)} />
            </div>
            <button className="btn" onClick={saveRetention}>Save</button>
            <Row>
              <div className="muted small">Invalid values are refused, not clamped. The hash-chained audit ledger is exempt — it is never deleted.</div>
            </Row>
          </Card>
        </Gate>

        <Card title="Export your data">
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={doExport}>Generate export</button>
            {exportData && <button className="btn-outline" onClick={downloadExport}>Download (.json)</button>}
          </div>
          {exportData && (
            <Terminal title="autostack export" lines={[
              { ts: stamp(), kind: 'ok', text: `export ready at ${exportData.exported_at}` },
              { ts: stamp(), kind: 'info', text: `drafts: ${exportData.drafts.length} (messages AutoStack prepared)` },
              { ts: stamp(), kind: 'info', text: `runs: ${exportData.runs.length} (every automation run, dry runs included)` },
              ...exportData.runs.slice(-5).map(r => ({ ts: stamp(), kind: 'dim', text: `  run ${r.id.slice(0, 8)} · ${r.status} · ${String(r.started_at).slice(0, 19)}` })),
              { ts: stamp(), kind: 'dim', text: 'audit ledger: exported separately from the Trust Log' },
            ]} />
          )}
          <Row>
            <div className="muted small">The audit ledger exports separately via Governance (Trust Log).</div>
          </Row>
        </Card>
      </div>

      <Card title="Consent ledger (real recorded decisions)">
        {!ledger && <div className="muted">Loading…</div>}
        {ledger && (
          <Row>
            <div className="muted">
              test-consent events: {ledger.counts.test_consent} · activations: {ledger.counts.activation} · runner pairings: {ledger.counts.runner_pair}
            </div>
          </Row>
        )}
        {ledger && ledger.recent_decisions.length === 0 && <div className="muted">No recorded approval decisions yet.</div>}
        {ledger && ledger.recent_decisions.map(d => (
          <Row key={d.id}>
            <div className="small">
              {d.decided_at} · <strong>{d.kind}</strong> · artifact {d.artifact_id.slice(0, 8)} · {d.note || '(no note)'}
            </div>
          </Row>
        ))}
        {ledger && <Row><div className="muted small">{ledger.note}</div></Row>}
      </Card>
    </div>
  );
}

// ── Connectors ────────────────────────────────────────────────────────────────
// Honest inventory: the worker measures each status from its real configuration
// at request time — never a hardcoded "supported" sticker. Boundaries (what a
// connector can and cannot see) come from README §4.

export function Connectors() {
  const [items, setItems] = useState(null);
  const [ai, setAi] = useState(null);
  const [err, setErr] = useState(null);

  async function refresh() {
    try { setItems(await api.connectors()); setAi(await api.aiMode()); }
    catch (e) { setErr(e.message); }
  }
  useState(() => { refresh(); });

  return (
    <div className="screen">
      <header className="screen-head">
        <div>
          <h1>Connectors</h1>
          <p className="muted">What each connector can and cannot see — measured live, not promised.</p>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      <div className="grid2">
        {((items && items.connectors) || []).map(c => (
          <Card key={c.id} title={c.name}
                actions={<span className={`conn-status ${c.status}`}>{c.status}</span>}>
            <Row><div><strong>Can see:</strong> {c.can_see}</div></Row>
            <Row><div><strong>Cannot see:</strong> {c.cannot_see}</div></Row>
            {c.detail && <Row><div className="muted small">{c.detail}</div></Row>}
          </Card>
        ))}
      </div>
      {ai && (
        <Card title="Model status">
          <Row>
            <div>Provider: <strong>{ai.provider}</strong>{ai.deterministic_offline ? ' (deterministic offline generator)' : ''}</div>
          </Row>
          <Row>
            <div className="muted small">Gemini key configured: {ai.gemini_key_present ? 'yes' : 'no'}</div>
          </Row>
        </Card>
      )}
      {items && <Row><div className="muted small">{items.note}</div></Row>}
    </div>
  );
}
