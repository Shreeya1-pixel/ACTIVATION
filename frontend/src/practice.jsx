// Practice — the whole loop on the user's own edits, no sample data:
// work in a real sheet → identified → AutoStack plans, writes, repairs and tests the
// code on a copy of the sheet → you approve → dry run → you go live → undo.
// Every step is a real worker call; the workspace replays their real outputs.
import React, { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';
import { Icon, ICONS, Terminal, stamp } from './main-shared.jsx';
import { AIWorkspace } from './ai-workspace.jsx';
import { describePattern } from './pattern-words.js';

const CTX = { org_type: 'corporate', size: 'small', department: 'finance', process_type: 'accounts_payable' };

function StepCard({ n, title, done, locked, children }) {
  return (
    <div className="card" style={{ padding: 20, opacity: locked ? 0.5 : 1 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: locked ? 0 : 12 }}>
        <span className={`badge ${done ? 'green' : ''}`} style={{ minWidth: 26, textAlign: 'center' }}>{done ? '✓' : n}</span>
        <h3 style={{ margin: 0 }}>{title}</h3>
      </div>
      {!locked && children}
    </div>
  );
}

const modelLabel = (p) => (p === 'gemini' ? 'model: Gemini' : 'model: offline generator (no LLM call)');
const sha8 = (s) => (s || '').slice(0, 8);

export function Practice() {
  const [sheet, setSheet] = useState(null);
  const [rows, setRows] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [lines, setLines] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [changed, setChanged] = useState([]);

  const [startBroken, setStartBroken] = useState(true);
  const [events, setEvents] = useState([]);
  const [folder, setFolder] = useState(null);
  const [model, setModel] = useState(modelLabel(null));
  const [phase, setPhase] = useState('idle'); // idle | building | await_approve | approving | await_live | live | undone
  const [ctx, setCtx] = useState({});
  const [replayIdle, setReplayIdle] = useState(true);
  const [runKey, setRunKey] = useState(0);

  const log = (kind, text) => setLines(prev => [...prev, { ts: stamp(), kind, text }].slice(-60));
  const push = (evs) => { setReplayIdle(false); setEvents(prev => [...prev, ...evs]); };
  const onIdle = useCallback(() => setReplayIdle(true), []);

  const load = async () => {
    const s = await api.practiceSheet();
    setSheet(s);
    if (s.active) { setRows(s.rows.map(r => ({ ...r }))); setDirty(false); }
    return s;
  };
  useEffect(() => { load().catch(e => setErr(e.message)); }, []);

  const act = async (fn) => {
    setBusy(true); setErr(null);
    try { return await fn(); } catch (e) { setErr(e.message); log('fail', e.message); return null; } finally { setBusy(false); }
  };

  const start = () => act(async () => {
    const r = await api.practiceStart();
    setEvents([]); setPhase('idle'); setCtx({}); setChanged([]); setLines([]); setFolder(null); setRunKey(k => k + 1);
    log('ok', `workspace ready: ${r.folder}/${r.file} (no history, nothing replayed)`);
    await load();
  });

  const save = () => act(async () => {
    const r = await api.practiceSave(rows);
    if (!r.changes.length) log('dim', 'saved: no changes seen');
    r.changes.forEach(c => log('ok', `saved → ${c.row}: ${c.action === 'row.updated' ? `changed ${c.columns.join(', ')}` : c.action}`));
    setSheet(s => ({ ...s, progress: r.progress, candidates: r.candidates }));
    setDirty(false);
  });

  const done = (rowId) => act(async () => {
    if (dirty) { setErr('Save first, then mark the row as done.'); return; }
    const r = await api.practiceDone(rowId);
    log('info', `done with ${rowId} → routine finished on ${r.progress.repeats} of ${r.progress.needed} rows needed`);
    setSheet(s => ({ ...s, progress: r.progress, candidates: r.candidates }));
  });

  const checkFolder = () => act(async () => {
    const r = await api.capturePoll();
    log(r.events ? 'ok' : 'dim', `checked the folder: ${r.events} change(s) from edits made outside the app`);
    await load();
  });

  const openFile = (target) => act(async () => {
    const r = await api.practiceOpen(target);
    log('dim', r.opened);
  });

  const edit = (i, col, value) => {
    setRows(prev => prev.map((r, j) => (j === i ? { ...r, [col]: value } : r)));
    setDirty(true);
  };

  const identified = ((sheet && sheet.candidates) || []).find(c => c.status === 'suggested');
  const d = identified ? describePattern(identified) : null;

  const ensureOwner = async () => {
    const me = await api.authMe().catch(() => null);
    if (me && me.role && me.role !== 'owner') await api.teamSelfRole('owner');
  };

  const fileEv = (f, tag, text, kind) => ({ tag, text, kind, file: { name: f.name, content: f.content, lines: f.lines } });

  // Identify → plan → generate (+ self-repair) → formal sandbox test. Stops at the human gate.
  const build = () => act(async () => {
    setPhase('building'); setEvents([]); setRunKey(k => k + 1);
    try { await buildSteps(); } catch (e) { setPhase('idle'); throw e; }
  });

  const buildSteps = async () => {
    const sug = await api.practiceSuggestPlan(identified.id);
    const plan = sug.plan;
    const sets = Object.entries(plan.set_fields).map(([k, v]) => `${k} → "${v}"`).join(', ');
    push([
      { tag: 'identify', text: `pattern: ${d.title} · ${d.kinds.join(', ')}` },
      { tag: 'identify', kind: 'dim', text: `evidence: same ${d.steps.length} steps × ${d.instances} times on ${d.distinct} rows (${d.records.join(', ')})` },
      { tag: 'identify', kind: 'ok', text: 'rule met: 3+ repeats on 2+ different rows → automatable' },
      { tag: 'plan', text: `reading ${sug.file} to learn values from the rows you finished…` },
      { tag: 'plan', kind: 'ok', text: `when ${plan.eligibility.status_field} = "${plan.eligibility.status}" → set ${sets}` },
      { tag: 'plan', kind: 'dim', text: `would apply now to: ${sug.would_match_now.join(', ') || 'no rows'}` },
    ]);
    const p = await api.createPlan(plan, identified.id);
    if (!p.generatable) throw new Error(`plan incomplete: ${(p.missing_rules || []).join(', ')}`);
    push([{ tag: 'plan', kind: 'ok', text: `plan locked · sha ${sha8(p.plan_sha256)}` },
          { tag: 'generate', text: `asking the model to write run(rows, ctx) for this plan${startBroken ? ' (demo: first draft deliberately broken)' : ''}…` }]);

    const gen = await api.generate(p.plan_id, startBroken);
    setModel(modelLabel(gen.provider));
    const byName = Object.fromEntries((gen.files || []).map(f => [f.name, f]));
    if (gen.files && gen.files[0]) setFolder(gen.files[0].folder);
    const evs = [];
    if (byName['plan.json']) evs.push(fileEv(byName['plan.json'], 'plan', `created plan.json (${byName['plan.json'].lines} lines)`, 'dim'));
    gen.attempts.forEach((a, i) => {
      const code = byName[`automation_v${a.version}.py`];
      const rep = byName[`sandbox_v${a.version}.json`];
      evs.push({ tag: 'generate', text: `attempt ${a.attempt}/3 · writing automation_v${a.version}.py${a.seeded ? ' (deliberately broken draft)' : ''}` });
      if (code) evs.push(fileEv(code, 'generate', `+ automation_v${a.version}.py · ${code.lines} lines · sha ${sha8(a.code_sha256)} · ${a.gen_ms ?? 0} ms`, 'dim'));
      const staticFail = a.problems.some(x => x.startsWith('static check'));
      evs.push({ tag: 'sandbox', kind: staticFail ? 'fail' : 'ok', text: `static safety check (no imports, network, files, eval): ${staticFail ? 'FAIL' : 'PASS'}` });
      if (!staticFail) evs.push({ tag: 'sandbox', text: `running in an isolated subprocess on a copy of ${sug.file}…`, delay: 500 });
      if (a.problems.length) {
        a.problems.forEach(pr => evs.push({ tag: 'sandbox', kind: 'fail', text: `FAIL ${pr}` }));
        if (rep) evs.push(fileEv(rep, 'sandbox', `+ sandbox_v${a.version}.json (failure report)`, 'dim'));
        if (i < gen.attempts.length - 1) evs.push({ tag: 'repair', kind: 'warn', text: `sending ${a.problems.length} problem(s) + the failing code back to the model → attempt ${a.attempt + 1}/3`, delay: 700 });
      } else {
        evs.push({ tag: 'sandbox', kind: 'ok', text: `PASS · ${a.checks.length} checks · ${a.check_ms ?? 0} ms` });
        if (rep) evs.push(fileEv(rep, 'sandbox', `+ sandbox_v${a.version}.json`, 'dim'));
      }
    });
    if (gen.repaired) evs.push({ tag: 'repair', kind: 'ok', text: 'self-repaired: no human edited the code' });
    push(evs);

    await ensureOwner();
    const job = await api.createTestJob(gen.artifact_id, true);
    const tevs = [{ tag: 'test', text: `formal test job (with consent) on ${job.tested_on} · ${job.rows_tested} rows` }];
    (job.report.checks || []).forEach(c => tevs.push({ tag: 'test', kind: c.ok ? 'ok' : 'fail', text: `${c.ok ? '✓' : '✗'} ${c.name}` }));
    if (job.file) tevs.push(fileEv(job.file, 'test', `+ ${job.file.name}`, 'dim'));
    tevs.push({ tag: 'test', kind: job.status === 'passed' ? 'ok' : 'fail', text: job.status === 'passed' ? 'TEST PASSED · waiting for a person to approve' : 'TEST FAILED · activation stays blocked' });
    push(tevs);
    setCtx({ sug, plan, planId: p.plan_id, gen, job });
    setPhase(job.status === 'passed' ? 'await_approve' : 'idle');
    log('ok', 'AutoStack built and tested the automation; your approval is needed');
  };

  // Human approval → workflow → automatic dry run with a real before/after diff.
  const approve = () => act(async () => {
    setPhase('approving');
    await api.approveActivation(ctx.gen.artifact_id, ctx.job.job_id);
    const wf = await api.createWorkflowFromPlan(ctx.planId, CTX);
    push([
      { tag: 'approve', kind: 'ok', text: `approved by you · code sha ${sha8(ctx.gen.code_sha256)} locked (any change needs a new test + approval)` },
      { tag: 'approve', kind: 'dim', text: `workflow ${wf.workflow_id} v${wf.version} created · not run yet` },
      { tag: 'dryrun', text: 'dry run: computing every change without writing anything…' },
    ]);
    const dry = await api.runWorkflow(wf.workflow_id, undefined, ctx.sug.file, true);
    const idCol = ctx.plan.client_id_field;
    const current = Object.fromEntries(rows.map(r => [r[idCol], r]));
    const diff = [`--- ${ctx.sug.file} (now)`, `+++ ${ctx.sug.file} (after this automation)`];
    (dry.would_update || []).forEach(id => {
      diff.push(`@@ ${idCol} ${id} @@`);
      Object.entries(ctx.plan.set_fields).forEach(([k, v]) => {
        const before = (current[id] || {})[k] ?? '';
        if (before !== v) { diff.push(`- ${k}: ${before || '(blank)'}`); diff.push(`+ ${k}: ${v}`); }
      });
    });
    const diffText = diff.join('\n');
    push([
      { tag: 'dryrun', kind: 'dim', text: `preflight: ${ctx.sug.file} and its columns still match the plan ✓` },
      { tag: 'dryrun', text: '+ dry_run.diff', file: { name: 'dry_run.diff', content: diffText, lines: diff.length } },
      ...(dry.file ? [fileEv(dry.file, 'dryrun', `+ ${dry.file.name}`, 'dim')] : []),
      { tag: 'dryrun', kind: 'ok', text: `${(dry.would_update || []).length} row(s) would change · 0 writes applied · file untouched` },
    ]);
    setCtx(c => ({ ...c, wf, dry }));
    setPhase('await_live');
    log('info', `dry run: ${(dry.would_update || []).length} row(s) would change`);
  });

  const goLive = () => act(async () => {
    push([{ tag: 'live', text: 'running for real: exactly-once writes, backup kept, every effect audited…' }]);
    const r = await api.runWorkflow(ctx.wf.workflow_id, undefined, ctx.sug.file, false);
    await api.practiceRebaseline();
    setChanged(r.updated || []);
    await load();
    push([
      { tag: 'live', kind: 'ok', text: `updated ${(r.updated || []).length} row(s) in ${ctx.sug.file}: ${(r.updated || []).join(', ')}` },
      ...(r.file ? [fileEv(r.file, 'live', `+ ${r.file.name}`, 'dim')] : []),
      { tag: 'live', kind: 'dim', text: 'trust log: effect.applied recorded for every change · undo available' },
    ]);
    setCtx(c => ({ ...c, live: r }));
    setPhase('live');
    log('ok', `live: updated ${(r.updated || []).length} row(s)`);
  });

  const undo = () => act(async () => {
    const r = await api.rollbackRun(ctx.live.run_id);
    await api.practiceRebaseline();
    setChanged(r.restored_rows || []);
    await load();
    push([{ tag: 'undo', kind: 'warn', text: `undo: restored ${(r.restored_rows || []).length} row(s) to their previous values` }]);
    setPhase('undone');
  });

  const active = sheet && sheet.active;
  const progress = (sheet && sheet.progress) || { repeats: 0, needed: 3, completed_rows: [] };
  const header = (sheet && sheet.header) || [];
  const idCol = sheet && sheet.id_column;
  const gateReady = replayIdle && !busy;

  return (
    <div className="screen">
      <div className="screen-header">
        <div>
          <div className="breadcrumb">Try it live</div>
          <h2>Your own work, automated end to end</h2>
        </div>
      </div>
      <div className="info-banner">
        <Icon d={ICONS.eye} size={18} />
        <span>No sample data. You edit a real spreadsheet; AutoStack learns only from what you change, then writes, tests and runs the automation on that same file.</span>
      </div>
      {err && <div className="info-banner" style={{ borderColor: 'rgba(239,68,68,.4)' }}><span className="helper-error" style={{ margin: 0 }}>{err}</span></div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <StepCard n={1} title="Open a practice workspace" done={!!active}>
          <p className="op-sub">A real folder with one invoice sheet and no history. Capture starts watching it.</p>
          {active && <p className="mono" style={{ fontSize: 12 }}>{sheet.folder}/{sheet.file}</p>}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className={active ? 'btn-outline' : 'btn-primary'} disabled={busy} onClick={start}>
              {active ? 'Reset workspace (start over)' : 'Start practice workspace'}
            </button>
            {active && <button className="btn-primary" disabled={busy} onClick={() => openFile('excel')}>Open in Excel</button>}
            {active && <button className="btn-outline" disabled={busy} onClick={() => openFile('finder')}>Show in Finder</button>}
          </div>
          {active && <p className="op-sub" style={{ marginTop: 8 }}>Edit in Excel if you like: save as CSV (Keep format), then click “Check folder for outside edits” below.</p>}
        </StepCard>

        <StepCard n={2} title="Do your normal work" done={!!identified} locked={!active}>
          <div className="info-banner" style={{ margin: '0 0 12px' }}>
            <span>Pick an invoice. Set <b>Status</b> to <b>Approved</b> and type your initials in <b>Checked By</b>, then <b>Save</b>. Next set <b>Payment Requested</b> to <b>Yes</b> and <b>Save</b>. Then click <b>Done</b> on that row. Repeat for 3 invoices.</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', fontSize: 13 }}>
              <thead><tr>{header.map(h => <th key={h} style={{ textAlign: 'left' }}>{h}</th>)}<th /></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r[idCol] || i} style={{ background: changed.includes(r[idCol]) ? 'rgba(22,163,74,0.08)' : undefined }}>
                    {header.map(h => (
                      <td key={h}>
                        {h === idCol
                          ? <span className="mono">{r[h]}</span>
                          : <input value={r[h] || ''} onChange={e => edit(i, h, e.target.value)}
                                   style={{ width: '100%', minWidth: 80, padding: '4px 6px', fontSize: 13 }} />}
                      </td>
                    ))}
                    <td>
                      {progress.completed_rows.includes(r[idCol])
                        ? <span className="badge green">Done</span>
                        : <button className="btn-outline" style={{ padding: '3px 10px', fontSize: 12 }} disabled={busy} onClick={() => done(r[idCol])}>Done</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '12px 0' }}>
            <button className="btn-primary" disabled={busy || !dirty} onClick={save}>{dirty ? 'Save (like Ctrl+S)' : 'Saved'}</button>
            <button className="btn-outline" disabled={busy} onClick={checkFolder} title="If you edited the file in Excel instead">Check folder for outside edits</button>
            <span className="muted" style={{ fontSize: 13 }}>Routine finished on <b>{progress.repeats}</b> of {progress.needed} rows needed</span>
          </div>
          <Terminal title="what capture saw (saved-file comparison)" lines={lines} running={!!active} />
        </StepCard>

        <StepCard n={3} title="AutoStack identified something to automate" done={phase !== 'idle'} locked={!identified}>
          {d && (
            <>
              <span className="identified-tag">IDENTIFIED · CAN BE AUTOMATED</span>
              <div className="op-name">{d.title}</div>
              <div className="identified-kinds">{d.kinds.map(k => <span key={k}>{k}</span>)}</div>
              <ol className="steps-list">{d.steps.map((s, i) => <li key={i}>You {s}</li>)}</ol>
              <p className="op-sub">Same {d.steps.length} steps, in the same order, {d.instances} times on {d.distinct} different rows: {d.records.join(', ')}.</p>
              {phase === 'idle' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
                  <button className="hero-cta" disabled={busy} onClick={build}>⚡ Automate this</button>
                  <label className="muted" style={{ display: 'flex', gap: 8, fontSize: 13 }}>
                    <input type="checkbox" checked={startBroken} onChange={e => setStartBroken(e.target.checked)} />
                    <span>Start from a broken draft (demo): watch the test catch it and the AI repair it</span>
                  </label>
                </div>
              )}
            </>
          )}
        </StepCard>

        <StepCard n={4} title="AutoStack builds it: plan, code, test, dry run" done={phase === 'live'} locked={phase === 'idle' && events.length === 0}>
          <AIWorkspace key={runKey} events={events} folder={folder} model={model} onIdle={onIdle} />

          {phase === 'await_approve' && gateReady && (
            <div className="gate-card">
              <span><b>Your turn.</b> The code passed its tests on a copy of your sheet. Nothing runs until you approve.</span>
              <button className="hero-cta" disabled={busy} onClick={approve}>Approve</button>
            </div>
          )}
          {phase === 'await_live' && gateReady && (
            <div className="gate-card">
              <span><b>Dry run done.</b> Check dry_run.diff: that is every change it will make. Go live?</span>
              <button className="hero-cta" disabled={busy} onClick={goLive}><Icon d={ICONS.zap} size={16} /> Go live</button>
            </div>
          )}
          {phase === 'live' && gateReady && (
            <div className="gate-card" style={{ borderColor: 'rgba(34,197,94,.5)', background: 'rgba(34,197,94,.08)' }}>
              <span><b style={{ color: '#15803d' }}>Automated.</b> {changed.length} row(s) updated in the real file, highlighted green in the sheet above.</span>
              <button className="btn-outline" disabled={busy} onClick={undo}>Undo this run</button>
            </div>
          )}
          {phase === 'undone' && <p className="op-sub" style={{ marginTop: 10 }}>Undone: {changed.length} row(s) restored. Check the sheet above.</p>}
        </StepCard>
      </div>
    </div>
  );
}
