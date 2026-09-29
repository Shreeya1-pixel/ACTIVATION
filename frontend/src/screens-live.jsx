// Phase 10 live screens: Dashboard, Workflows, Registry, TrustLog.
// Rule: real worker data when connected (labeled), demo data only when offline,
// honest empty states everywhere. No invented percentages, ratings, or savings.
import React, { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { api } from './api.js';
import { subscribeLive } from './live.js';
import { Icon, ICONS, StatusBadge } from './main-shared.jsx';
import { Reveal } from './premium.jsx';
import { LEVEL, spring, dur } from './motion.js';

function timeShort(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

export function Dashboard({ setPage }) {
  const [live, setLive] = useState(null);
  useEffect(() => subscribeLive(setLive), []);
  const connected = !!(live && live.connected);
  const workflows = (live && live.workflows) || [];
  const runs = (live && live.runs) || [];
  const cands = ((live && live.candidates) || []).filter(c => c.status === 'suggested');
  const notes = (live && live.notifications) || [];
  const unread = notes.filter(n => !n.read_at).length;

  const passed = runs.filter(r => r.status === 'passed').length;
  const successRate = runs.length ? Math.round((passed / runs.length) * 100) : null;

  // Efficiency chart uses RECORDED runs only: runs per day over the last 14 days.
  const dayBuckets = useMemo(() => {
    const days = [];
    for (let i = 13; i >= 0; i -= 1) {
      const d = new Date(Date.now() - i * 86400000);
      days.push(d.toISOString().slice(0, 10));
    }
    const counts = Object.fromEntries(days.map(d => [d, 0]));
    for (const r of runs) {
      const key = String(r.started_at || '').slice(0, 10);
      if (key in counts) counts[key] += 1;
    }
    const max = Math.max(1, ...Object.values(counts));
    return days.map(d => ({ day: d, count: counts[d], pct: Math.round((counts[d] / max) * 100) }));
  }, [runs]);
  const totalRecorded = dayBuckets.reduce((s, b) => s + b.count, 0);

  const metrics = [
    { label: 'Active Automations', value: connected ? String(workflows.length) : '—',
      sub: connected ? 'live from worker' : 'worker offline', color: 'blue' },
    { label: 'Success Rate (runs)', value: successRate === null ? '—' : `${successRate}%`,
      sub: connected ? `${passed}/${runs.length} runs passed` : 'worker offline', color: 'green', bar: successRate !== null },
    { label: 'Unread Notifications', value: connected ? String(unread) : '—',
      sub: connected ? `${notes.length} total` : 'worker offline', color: 'orange' },
    { label: 'Estimated Savings', value: 'not measured',
      sub: 'no time study recorded — no invented numbers', color: 'purple' },
  ];

  return (
    <div className="screen">
      <div className="screen-header">
        <div>
          <div className="breadcrumb">Workspace</div>
          <h2>Dashboard</h2>
          <p className="profile-sub">Live operations across your automations — every number comes from the worker, never sampled.</p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button className="btn-icon" title="Notifications" aria-label="Notifications" onClick={() => setPage('notifications')}><Icon d={ICONS.bell} /></button>
          <button className="btn-primary" onClick={() => setPage('create')}>
            <Icon d={ICONS.plus} size={16} /> Create automation
          </button>
        </div>
      </div>

      {/* 1. What is happening now — execution health leads the page. */}
      <div className={`dash-hero ${connected ? '' : 'off'}`}>
        <div className="dash-hero-main">
          <div className="dash-hero-label">Execution health</div>
          <div className="dash-hero-value">
            {successRate === null ? '—' : `${successRate}%`}
            <span className="dash-hero-sub">{connected ? `${passed} / ${runs.length} runs passed` : 'worker offline'}</span>
          </div>
          {successRate !== null && (
            <div className="metric-bar"><div className="metric-bar-fill" style={{ width: `${successRate}%` }} /></div>
          )}
        </div>
        <div className="dash-hero-side">
          <div className="dash-side-metric">
            <div className="metric-label">Active automations</div>
            <div className="metric-value">{connected ? workflows.length : '—'}</div>
          </div>
          <div className="dash-side-metric">
            <div className="metric-label">Unread notifications</div>
            <div className="metric-value">{connected ? unread : '—'}</div>
          </div>
        </div>
      </div>

      {/* 4. What should I do next — one honest opportunity line, demoted. */}
      <div className="dash-note">
        <Icon d={ICONS.chart} size={14} />
        <span>Efficiency (hours saved) is not measured — it appears here only after a real time study.</span>
      </div>

      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <div className="card-title-row">
              <span className={`dot ${connected ? 'green' : 'red'}`} /> <strong>{connected ? 'Live Operations' : 'Recent Runs (offline)'}</strong>
            </div>
            <button className="link-btn" onClick={() => setPage('workflows')}>View All</button>
          </div>
          {runs.length === 0 ? (
            <div className="empty-state" style={{ padding: 24 }}>
              <p>{connected ? 'No runs recorded yet. Run a workflow to see live operations here.' : 'Connect the worker to see real run history.'}</p>
            </div>
          ) : (
            <table className="ops-table">
              <tbody>
                {runs.slice(0, 6).map(r => (
                  <tr key={r.id}>
                    <td>
                      <div className={`op-icon ${r.status === 'passed' ? 'green' : r.status === 'running' ? 'blue' : 'red'}`}>
                        <Icon d={ICONS.flow} size={15} />
                      </div>
                    </td>
                    <td>
                      <div className="op-name">{r.workflow_id || 'run'}</div>
                      <div className="op-sub">{r.trigger || 'manual'}</div>
                    </td>
                    <td className="op-right">
                      <StatusBadge s={r.status === 'passed' ? 'Success' : r.status === 'running' ? 'In Progress' : r.status === 'cancelled' ? 'Rolled back' : 'Failed'} />
                      <div className="op-time">{timeShort(r.started_at)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="right-col">
          {/* 2. What needs attention — compact strip, prominent only when there is evidence. */}
          <button className={`dash-discovery ${cands.length ? 'has-candidates' : ''}`} onClick={() => setPage('discovery')}>
            <Icon d={ICONS.search} size={16} />
            {cands.length ? (
              <span className="dd-copy">
                <strong>Discovery: new evidence-based candidate</strong>
                <span>{(cands[0].pattern && cands[0].pattern.sequence || []).join(' → ')} · {cands[0].occurrences} instances</span>
              </span>
            ) : (
              <span className="dd-copy">
                <strong>Discovery engine</strong>
                <span>{connected ? 'No qualifying patterns yet — they appear from real repeated work only.' : 'Connect the worker to see detected patterns.'}</span>
              </span>
            )}
            <Icon d={ICONS.chevron} size={15} />
          </button>

          <div className="card">
            <div className="card-header"><strong>Quick Actions</strong></div>
            {[
              ['Review Workflows', 'workflows'],
              ['Create Custom Workflow', 'create'],
              ['View Registry', 'registry'],
              ['Open Trust Log', 'trustlog'],
            ].map(([label, page]) => (
              <button className="quick-action" key={label} onClick={() => setPage(page)}>
                {label} <Icon d={ICONS.chevron} size={16} />
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 20 }}>
        <div className="card-header">
          <strong>Runs per day (14 days)</strong>
          <span className="badge blue">recorded data</span>
        </div>
        {totalRecorded === 0 ? (
          <div className="empty-state" style={{ padding: 24 }}>
            <p>No runs recorded in this window — the chart uses real run history only, never sample data.</p>
          </div>
        ) : (
          <>
            <div className="bar-chart">
              {dayBuckets.map(b => (
                <div key={b.day} className="bar-wrap" title={`${b.day}: ${b.count} runs`}>
                  <div className="bar" style={{ height: `${Math.max(4, b.pct)}%` }} />
                </div>
              ))}
            </div>
            <div className="chart-labels">
              <span>{dayBuckets[0].day.slice(5)}</span>
              <span>{dayBuckets[7].day.slice(5)}</span>
              <span>{dayBuckets[13].day.slice(5)}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Workflows ────────────────────────────────────────────────────────────────

export function Workflows({ setPage }) {
  const [live, setLive] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  useEffect(() => subscribeLive(setLive), []);
  const connected = !!(live && live.connected);
  const workflows = (live && live.workflows) || [];
  const runs = (live && live.runs) || [];
  const selected = workflows.find(w => w.id === selectedId) || null;
  const selRuns = runs.filter(r => r.workflow_id === selectedId);
  const runningRun = selRuns.find(r => r.status === 'running' || r.status === 'pending');

  useEffect(() => {
    if (!runningRun) return undefined;
    const id = setInterval(async () => setNodes(await api.runNodes(runningRun.id).then(r => r.nodes).catch(() => [])), 2000);
    return () => clearInterval(id);
  }, [runningRun && runningRun.id]);

  const runNow = async (wfId, dryRun = false) => {
    setBusy(true); setMsg(null);
    try {
      const res = await api.startRun({ workflow_id: wfId, run_date: '2026-09-20', filename: 'clients.csv', dry_run: dryRun });
      if (dryRun) {
        const wu = res.would_update || [];
        const wd = res.would_draft || [];
        setMsg({ ok: true, text: `dry run ${res.run_id.slice(0, 8)} — nothing changed. Would update ${wu.length} row(s)${wu.length ? ` (${wu.slice(0, 5).join(', ')}${wu.length > 5 ? '…' : ''})` : ''}, would draft ${wd.length} message(s).` });
        return;
      }
      setMsg({ ok: true, text: `run ${res.run_id.slice(0, 8)} — ${res.status} (updated: ${(res.updated || []).length}, drafted: ${(res.drafted || []).length}, skipped: ${(res.skipped || []).length})` });
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally { setBusy(false); }
  };

  const runCompare = async () => {
    setBusy(true); setMsg(null);
    try {
      const res = await api.compareRun();
      setMsg({ ok: true, text: `invoice/PO compare — ${res.status} (matched: ${res.matched}, mismatched: ${res.mismatched}, drafts: ${(res.drafted || []).length})` });
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally { setBusy(false); }
  };

  const cancel = async (runId) => {
    setBusy(true);
    try {
      await api.cancelRun(runId);
      setMsg({ ok: true, text: `run ${runId.slice(0, 8)} cancel requested` });
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally { setBusy(false); }
  };

  const showNodes = async (runId) => {
    const r = await api.runNodes(runId).catch(() => ({ nodes: [] }));
    setNodes(r.nodes || []);
  };

  return (
    <div className="screen">
      <div className="screen-header">
        <div>
          <div className="breadcrumb">My Workflows</div>
          <h2>All Workflows</h2>
        </div>
        <button className="btn-primary" onClick={() => setPage('create')}>
          <Icon d={ICONS.plus} size={16} /> Create New Automation
        </button>
      </div>

      {!connected && (
        <div className="info-banner">
          <Icon d={ICONS.lock} size={18} />
          <span>Worker offline — run controls are locked. Start the stack to execute workflows for real.</span>
        </div>
      )}
      {msg && (
        <div className="info-banner">
          <Icon d={ICONS.check} size={18} />
          <span>{msg.text}</span>
        </div>
      )}

      <div className="two-col" style={{ alignItems: 'flex-start' }}>
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          {connected && workflows.length === 0 ? (
            <div className="empty-state" style={{ padding: 28 }}>
              <p>No workflows yet. Create one from a confirmed plan in Create Automation.</p>
            </div>
          ) : (
            <table className="full-table">
              <thead>
                <tr><th>Workflow</th><th>Version</th><th>Runs</th><th>Bound artifact</th></tr>
              </thead>
              <tbody>
                {(connected ? workflows : []).map(w => (
                  <tr key={w.id} onClick={() => setSelectedId(w.id)} className={selectedId === w.id ? 'row-active' : ''}>
                    <td><div className="op-name">{w.name}</div><div className="op-sub">{w.id}</div></td>
                    <td>v{w.version}</td>
                    <td>{w.runs}</td>
                    <td><span className="mono dim">{(w.artifact_sha256 || '').slice(0, 10)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selected && (
          <div className="card" style={{ minWidth: 300, position: 'sticky', top: 20 }}>
            <div className="card-header">
              <strong>{selected.name}</strong>
              <button className="btn-icon small" onClick={() => setSelectedId(null)}><Icon d={ICONS.x} size={16} /></button>
            </div>
            <div className="detail-section">
              <div className="detail-label">Version &amp; provenance</div>
              <div className="approval-row"><span>Version</span><b>v{selected.version}</b></div>
              <div className="approval-row"><span>Artifact sha256</span><span className="mono dim">{(selected.artifact_sha256 || '').slice(0, 16)}…</span></div>
              <div className="approval-row"><span>Total runs</span><b>{selected.runs}</b></div>
            </div>
            {selected.context && selected.context.org_type && (
              <div className="detail-section">
                <div className="detail-label">Classification</div>
                <div className="approval-row"><span>Organization</span><b>{String(selected.context.org_type).replace(/_/g, ' ')} · {String(selected.context.size).replace(/_/g, ' ')}</b></div>
                <div className="approval-row"><span>Department</span><b>{String(selected.context.department).replace(/_/g, ' ')}</b></div>
                <div className="approval-row"><span>Process type</span><b>{String(selected.context.process_type).replace(/_/g, ' ')}</b></div>
              </div>
            )}
            <div className="detail-section">
              <div className="detail-label">Actions</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                <button className="btn-outline full-w" disabled={busy || !connected} onClick={() => runNow(selected.id, true)}>
                  Dry run (preview, changes nothing)
                </button>
                <button className="btn-primary full-w" disabled={busy || !connected} onClick={() => runNow(selected.id)}>
                  <Icon d={ICONS.refresh} size={16} /> Run now
                </button>
                {selected.id === 'wf_invoice_po_compare' && (
                  <button className="btn-outline full-w" disabled={busy || !connected} onClick={runCompare}>
                    Run invoice/PO comparison
                  </button>
                )}
                {runningRun && (
                  <button className="btn-outline full-w" disabled={busy} onClick={() => cancel(runningRun.id)}>
                    Cancel running run
                  </button>
                )}
              </div>
            </div>
            <div className="detail-section">
              <div className="detail-label">Run history (real)</div>
              {selRuns.length === 0 && <p className="op-sub">No runs yet for this workflow.</p>}
              {selRuns.slice(0, 6).map(r => (
                <div key={r.id} className="approval-row">
                  <span className="op-sub" style={{ cursor: 'pointer' }} onClick={() => showNodes(r.id)}>
                    {timeShort(r.started_at)} · {r.status}
                  </span>
                  <StatusBadge s={r.status === 'passed' ? 'Success' : r.status === 'running' ? 'In Progress' : r.status === 'cancelled' ? 'Rolled back' : 'Failed'} />
                </div>
              ))}
            </div>
            {nodes.length > 0 && (
              <div className="detail-section">
                <div className="detail-label">Node records</div>
                {nodes.map((n, i) => {
                  // Execution status materials: pass / run / fail (pending → run).
                  const cls = n.status === 'passed' ? 'pass'
                    : (n.status === 'running' || n.status === 'pending') ? 'run' : 'fail';
                  const badgeCls = cls === 'pass' ? 'green' : cls === 'run' ? 'blue' : 'red';
                  return (
                    <motion.div
                      key={`${n.seq}-${n.node}-${i}`} className={`run-node ${cls}`}
                      initial={LEVEL.interactive ? { opacity: 0, x: -10 } : false}
                      animate={{ opacity: 1, x: 0 }}
                      transition={spring.gentle}
                    >
                      <span className="rn-dot" />
                      <span className="rn-name">#{n.seq} {n.node}</span>
                      {n.ms ? <span className="rn-ms">{n.ms}ms</span> : null}
                      <span className={`badge ${badgeCls}`}>{n.status}</span>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Registry ─────────────────────────────────────────────────────────────────

export function Registry({ identity }) {
  const isOwner = !!(identity && identity.role === 'owner');
  // Imports create untrusted drafts (a write) — observers are read-only.
  const rank = { observer: 0, operator: 1, approver: 2, owner: 3 }[identity && identity.role] ?? -1;
  const canImport = rank >= 1;
  const [live, setLive] = useState(null);
  const [search, setSearch] = useState('');
  const [templates, setTemplates] = useState([]);
  const [importState, setImportState] = useState({});
  const [publishWf, setPublishWf] = useState('');
  const [consent, setConsent] = useState(false);
  const [msg, setMsg] = useState(null);
  useEffect(() => subscribeLive(setLive), []);
  const connected = !!(live && live.connected);
  const myWorkflows = (live && live.workflows) || [];

  useEffect(() => {
    if (connected) api.registryTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [connected]);

  const filtered = templates.filter(t =>
    t.title.toLowerCase().includes(search.toLowerCase()) ||
    t.slug.toLowerCase().includes(search.toLowerCase()));

  const doImport = async (t) => {
    setImportState(s => ({ ...s, [t.template_id]: { busy: true } }));
    try {
      const res = await api.registryImport(t.template_id, {
        ClientID: 'ClientID', Name: 'Name', FollowUpDate: 'FollowUpDate', Status: 'Status',
      });
      setImportState(s => ({ ...s, [t.template_id]: { done: res.status, note: res.note } }));
    } catch (e) {
      setImportState(s => ({ ...s, [t.template_id]: { error: e.message } }));
    }
  };

  const doPublish = async () => {
    setMsg(null);
    try {
      if (!publishWf) throw new Error('select one of your workflows');
      if (!consent) throw new Error('publication consent is required');
      const wf = await api.getWorkflow(publishWf);
      const res = await api.registryPublish({
        slug: `wf-${publishWf.slice(0, 12)}`,
        title: `Shared: ${wf.name}`,
        graph: wf.graph,
        compatible_connectors: ['sample-tracking-file'],
        publication_consent: true,
      });
      setMsg({ ok: true, text: `published ${res.slug} v${res.version} — schema only, no records` });
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    }
  };

  return (
    <div className="screen">
      <div className="screen-header">
        <div>
          <div className="breadcrumb">Shared Registry</div>
          <h2>Automation Registry</h2>
        </div>
        <div className="search-box">
          <Icon d={ICONS.search} size={16} />
          <input placeholder="Search published templates..." value={search} onChange={e => setSearch(e.target.value)} />
        </div>
      </div>

      <div className="info-banner">
        <Icon d={ICONS.package} size={18} />
        <span>Imports arrive as <b>untrusted drafts</b>: approvals are never inherited, and local tests + activation are always required. Only workflow schemas are shared — never records, credentials, or private paths.</span>
      </div>

      {msg && (
        <div className={`info-banner`}>
          <Icon d={ICONS.check} size={18} />
          <span>{msg.text}</span>
        </div>
      )}

      <div className="card">
        <div className="card-header"><strong>Publish one of your workflows</strong></div>
        <p className="profile-sub">Publication is a separate consent. The registry receives the validated graph and connectors — not your data. Publishing requires the owner role.</p>
        {isOwner ? (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <select value={publishWf} onChange={e => setPublishWf(e.target.value)} style={{ minWidth: 240 }}>
              <option value="">Select workflow…</option>
              {myWorkflows.map(w => <option key={w.id} value={w.id}>{w.name} (v{w.version})</option>)}
            </select>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
              I consent to publishing this schema</label>
            <button className="btn-dark" disabled={!connected} onClick={doPublish}>Publish</button>
          </div>
        ) : (
          <p className="muted">Publishing templates requires the owner role — imports stay open to all writers and always arrive as untrusted drafts.</p>
        )}
      </div>

      <div className="registry-grid" style={{ marginTop: 16 }}>
        {filtered.map(t => {
          const st = importState[t.template_id] || {};
          return (
            <div className="card registry-item" key={t.template_id}>
              <div className="reg-top">
                <div>
                  <div className="op-name">{t.title}</div>
                  <div className="op-sub">{t.slug} · v{t.version}</div>
                </div>
                <div className="reg-rating mono dim">{(t.artifact_sha256 || '').slice(0, 8)}</div>
              </div>
              <div className="tag-row" style={{ margin: '10px 0' }}>
                {(t.compatible_connectors || []).map(c => <span key={c} className="tag">{c}</span>)}
              </div>
              <div className="reg-footer">
                <div className="reg-stat">Published template — usage stats are not invented</div>
                {canImport ? (
                  <button className="btn-dark" disabled={!connected || st.busy || st.done} onClick={() => doImport(t)}>
                    {st.done ? 'Imported (untrusted draft)' : st.busy ? 'Importing…' : 'Use Workflow'}
                  </button>
                ) : (
                  <span className="muted">Importing requires the operator role or higher.</span>
                )}
              </div>
              {st.error && <p className="helper-error">Import refused: {st.error}</p>}
              {st.done && <p className="op-sub">Status: {st.done}. {st.note || ''} Re-test and activate locally before running.</p>}
            </div>
          );
        })}
        {connected && templates.length === 0 && (
          <div className="card empty-state" style={{ gridColumn: '1/-1' }}>
            <Icon d={ICONS.package} size={28} />
            <p>No templates published yet. Publish one of your workflows above to share its schema.</p>
          </div>
        )}
        {!connected && (
          <div className="card empty-state" style={{ gridColumn: '1/-1' }}>
            <Icon d={ICONS.lock} size={28} />
            <p>Connect the worker to browse the live registry — demo templates are intentionally not shown.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Trust Log ────────────────────────────────────────────────────────────────

export function TrustLog() {
  const [live, setLive] = useState(null);
  const [wfFilter, setWfFilter] = useState('');
  useEffect(() => subscribeLive(setLive), []);
  const connected = !!(live && live.connected);
  const workflows = (live && live.workflows) || [];
  const audit = live && live.audit;

  const entries = ((audit && audit.entries) || []).map(e => ({
    ...e,
    workflowId: (e.payload && (e.payload.workflow_id || e.payload.slug)) || null,
  }));
  const filtered = wfFilter ? entries.filter(e => e.workflowId === wfFilter) : entries;

  return (
    <div className="screen">
      <div className="screen-header">
        <div>
          <div className="breadcrumb">Trust &amp; Audit</div>
          <h2>Trust Log</h2>
        </div>
        <div className="tag-row">
          <span className="tag">Hash-chained</span>
          <span className="tag">Append-only</span>
          <span className="tag">SHA-256</span>
        </div>
      </div>

      <div className="info-banner">
        <Icon d={ICONS.lock} size={18} />
        <span>{audit
          ? `Live verification: chain_valid = ${audit.chain_valid} over ${audit.count} entries. Selecting a workflow filters to its actual evidence.`
          : 'Connect the worker for the live hash chain — demo entries are not shown.'}</span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header"><strong>Filter by workflow</strong></div>
        <select value={wfFilter} onChange={e => setWfFilter(e.target.value)} style={{ minWidth: 260 }}>
          <option value="">All entries</option>
          {workflows.map(w => <option key={w.id} value={w.id}>{w.name} ({w.id})</option>)}
        </select>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="full-table">
          <thead>
            <tr><th>Seq</th><th>Action</th><th>Linked object</th><th>When (UTC)</th><th>Hash</th><th>Chain</th></tr>
          </thead>
          <tbody>
            {filtered.map(e => (
              <tr key={e.seq}>
                <td><span className="mono">#{e.seq}</span></td>
                <td>{e.kind}</td>
                <td className="op-sub">{e.payload
                  ? Object.entries(e.payload).slice(0, 2).map(([k, v]) => `${k}=${String(v).slice(0, 24)}`).join(' ')
                  : '—'}</td>
                <td className="op-sub">{String(e.at || '').slice(0, 19)}</td>
                <td><span className="mono dim">{e.hash}</span></td>
                <td><StatusBadge s={audit && audit.chain_valid === false ? 'Blocked' : 'Pass'} /></td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan="6"><div className="empty-state" style={{ padding: 20 }}>
                <p>{connected ? 'No entries for this filter yet.' : 'Connect the worker to see the live audit chain.'}</p>
              </div></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
