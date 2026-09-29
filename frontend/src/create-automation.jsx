// CreateAutomation — REAL backend-gated stepper (Phase 10).
// plan → generate → sandbox test → activation → bind → (optional) publish.
// Every gate is a real worker call that fails closed; the UI never fakes progress.
import React, { useState, useEffect } from 'react';
import { api } from './api.js';
import { subscribeLive, capturePoll } from './live.js';
import { Icon, ICONS, Terminal, stamp } from './main-shared.jsx';
import { CaptureSettings } from './capture-settings.jsx';
import { CodeStream } from './code-stream.jsx';

const loadDraft = () => {
  try {
    const raw = sessionStorage.getItem('autostack_create_flow');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

export function CreateAutomation({ setPage }) {
  const initialDraft = loadDraft();
  const [step, setStep] = useState(initialDraft?.step || 1);
  const [live, setLive] = useState(null);
  useEffect(() => subscribeLive(setLive), []);

  // Step 2: real capture polling against the worker (honest failures included).
  const [monitoring, setMonitoring] = useState(false);
  const [monitorLines, setMonitorLines] = useState([]);
  const [eventCount, setEventCount] = useState(0);

  // Step 3: confirmed plan (the only source of eligibility truth).
  const [candidateId, setCandidateId] = useState(initialDraft?.candidateId || null);
  const [statusVal, setStatusVal] = useState(initialDraft?.statusVal || 'Follow-up due');
  const [dateVal, setDateVal] = useState(initialDraft?.dateVal || '2026-09-20');
  const [actionSel, setActionSel] = useState(initialDraft?.actionSel || 'create_draft');
  const [notifySel, setNotifySel] = useState(initialDraft?.notifySel !== undefined ? initialDraft.notifySel : true);
  const [planId, setPlanId] = useState(initialDraft?.planId || null);
  const [planMissing, setPlanMissing] = useState([]);

  // Step 4: generation → isolated test → activation approval.
  const [artifact, setArtifact] = useState(initialDraft?.artifact || null);
  const [job, setJob] = useState(initialDraft?.job || null);
  const [approval, setApproval] = useState(initialDraft?.approval || null);
  const [genAttempts, setGenAttempts] = useState(initialDraft?.genAttempts || null);
  const [genProvider, setGenProvider] = useState(initialDraft?.genProvider || null);
  const [startBroken, setStartBroken] = useState(false);

  // Step 5: binding to a versioned workflow (+ optional publish).
  const [bound, setBound] = useState(initialDraft?.bound || null);
  const [published, setPublished] = useState(initialDraft?.published || false);

  // Step 1 context (org type → size → department → process type), from the
  // worker's catalog — never a hardcoded UI list. "Other" is free text.
  const [catalog, setCatalog] = useState(null);
  const [ctxOrgType, setCtxOrgType] = useState(initialDraft?.ctxOrgType || 'corporate');
  const [ctxSize, setCtxSize] = useState(initialDraft?.ctxSize || 'medium');
  const [ctxDept, setCtxDept] = useState(initialDraft?.ctxDept || 'finance');
  const [ctxProcess, setCtxProcess] = useState(initialDraft?.ctxProcess || 'accounts_payable');
  const [ctxOther, setCtxOther] = useState(initialDraft?.ctxOther || '');
  useEffect(() => { api.orgCatalog().then(setCatalog).catch(() => setCatalog(null)); }, []);

  // If planId was restored, sync artifacts and test status from the database.
  useEffect(() => {
    if (!planId) return;
    api.listPlanArtifacts(planId).then(res => {
      if (res && res.artifacts && res.artifacts.length > 0) {
        const latest = res.artifacts[0];
        setArtifact(prev => prev || latest);
        if (latest.last_job) setJob(prev => prev || latest.last_job);
        if (latest.approval) setApproval(prev => prev || latest.approval);
      }
    }).catch(() => {});
  }, [planId]);

  // Persist draft updates to sessionStorage so refreshes never lose progress.
  useEffect(() => {
    try {
      const payload = {
        step, candidateId, statusVal, dateVal, actionSel, notifySel,
        planId, artifact, job, approval, bound, published, genAttempts, genProvider,
        ctxOrgType, ctxSize, ctxDept, ctxProcess, ctxOther,
      };
      sessionStorage.setItem('autostack_create_flow', JSON.stringify(payload));
    } catch { /* storage unavailable */ }
  }, [step, candidateId, statusVal, dateVal, actionSel, notifySel,
      planId, artifact, job, approval, bound, published, genAttempts, genProvider,
      ctxOrgType, ctxSize, ctxDept, ctxProcess, ctxOther]);

  const startFresh = () => {
    sessionStorage.removeItem('autostack_create_flow');
    setStep(1);
    setCandidateId(null);
    setPlanId(null);
    setPlanMissing([]);
    setArtifact(null);
    setJob(null);
    setApproval(null);
    setGenAttempts(null);
    setGenProvider(null);
    setBound(null);
    setPublished(false);
    setErr(null);
  };

  // Reset downstream selections whenever an upstream context choice changes.
  useEffect(() => {
    if (!catalog) return;
    if (!catalog.sizes_for_type[ctxOrgType]?.includes(ctxSize)) setCtxSize(catalog.sizes_for_type[ctxOrgType]?.[0] || 'small');
  }, [ctxOrgType]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!catalog) return;
    if (!catalog.departments[ctxOrgType]?.includes(ctxDept)) setCtxDept(catalog.departments[ctxOrgType]?.[0] || '');
  }, [ctxOrgType]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!catalog) return;
    const allowed = catalog.process_types[ctxDept] || catalog.default_process_types;
    if (!allowed.includes(ctxProcess)) setCtxProcess(allowed[0] || '');
  }, [ctxDept, ctxOrgType]); // eslint-disable-line react-hooks/exhaustive-deps

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const connected = !!(live && live.connected);
  const realCands = ((live && live.candidates) || []).filter(c => c.status === 'suggested');

  const pushLine = (kind, text) =>
    setMonitorLines(prev => [...prev, { ts: stamp(), kind, text }].slice(-80));

  const [demoBusy, setDemoBusy] = useState(false);
  const loadSampleWorkspace = async () => {
    setDemoBusy(true);
    pushLine('dim', 'demo.load   replaying SAMPLE sheets (invented companies) through the real sheet diff…');
    try {
      const res = await api.loadDemo();
      setEventCount(n => n + (res.events_new || 0));
      pushLine('ok', `demo.load   ${res.events_replayed} events from saved-sheet diffs (${res.events_new} new) · files: ${res.files.join(', ')}`);
      (res.candidates || []).forEach(c => {
        const verdict = c.status === 'suggested' ? 'DETECTED' : 'below threshold';
        pushLine(c.status === 'suggested' ? 'ok' : 'dim',
          `detect      ${verdict}: ${c.occurrences} instances / ${c.distinct_clients} records · ${c.resource.replace('watched/', '')}`);
      });
      pushLine('dim', 'rule        same ordered steps, 3+ completed instances, 2+ different records');
    } catch (e) {
      pushLine('warn', `demo.load failed: ${e.message}`);
    } finally {
      setDemoBusy(false);
    }
  };

  useEffect(() => {
    if (!monitoring) return undefined;
    const id = setInterval(async () => {
      try {
        const res = await capturePoll();
        if (res) {
          const fresh = typeof res.events === 'number' ? res.events : (res.accepted || []).length;
          const cands = res.detection ? (res.detection.candidates_created || 0) : 0;
          setEventCount(n => n + fresh);
          pushLine(fresh ? 'ok' : 'dim',
            `capture.poll    new_events=${fresh} new_candidates=${cands} gaps=${(res.gaps || []).length}`);
        }
      } catch (e) {
        pushLine('warn', `capture.poll failed: ${e.message} — worker offline; nothing invented`);
      }
    }, 2500);
    return () => clearInterval(id);
  }, [monitoring]);

  const buildPlan = () => ({
    client_id_field: 'ClientID',
    field_mappings: { Name: 'Name', FollowUpDate: 'FollowUpDate' },
    eligibility: { status: statusVal, status_field: 'Status',
                   date_field: 'FollowUpDate', date_value: dateVal },
    action: actionSel,
    destinations: notifySel ? ['in_app', 'desktop_notification'] : ['in_app'],
  });

  const gate = async (fn, okMsg) => {
    setBusy(true); setErr(null);
    try {
      const out = await fn();
      if (okMsg) pushLine('ok', typeof okMsg === 'function' ? okMsg(out) : okMsg);
      return out;
    } catch (e) {
      setErr(e.message);
      pushLine('fail', `gate refused: ${e.message}`);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const savePlan = () => gate(async () => {
    const res = await api.createPlan(buildPlan(),
      candidateId && candidateId.startsWith('real-') ? candidateId.slice(5) : null);
    if (!res.generatable) {
      setPlanMissing(res.missing_rules || []);
      throw new Error(`plan incomplete: ${(res.missing_rules || []).join(', ')}`);
    }
    setPlanMissing([]);
    setPlanId(res.plan_id);
    setStep(4);
    return res;
  }, r => `plan accepted  sha=${(r.plan_sha256 || '').slice(0, 12)}`);

  const generate = () => gate(async () => {
    const art = await api.generate(planId, startBroken);
    setGenAttempts(art.attempts || null);
    setGenProvider(art.provider || null);
    if (art.violations && art.violations.length) {
      throw new Error(`static validation: ${art.violations.join('; ')}`);
    }
    setArtifact(art);
    return art;
  }, a => `artifact generated in ${(a.attempts || []).length || 1} attempt(s)${a.repaired ? ' (self-repaired)' : ''}  sha=${(a.code_sha256 || '').slice(0, 12)}`);

  const runTest = () => {
    if (busy) return;
    return gate(async () => {
      const j = await api.createTestJob(artifact.artifact_id, true);
      setJob(j);
      if (j.status !== 'passed') {
        const errMsg = (j.report && j.report.error)
          ? `isolated test failed: ${j.report.error}`
          : `isolated test ${j.status} — activation stays blocked`;
        throw new Error(errMsg);
      }
      return j;
    }, 'isolated test passed (subprocess sandbox, plan-derived expected outputs)');
  };

  const approve = () => gate(async () => {
    const a = await api.approveActivation(artifact.artifact_id, job && job.job_id);
    setApproval(a);
    return a;
  }, 'human activation approval recorded');

  const bind = () => gate(async () => {
    const context = {
      org_type: ctxOrgType,
      size: ctxSize,
      department: ctxDept,
      process_type: ctxOther.trim() ? ctxOther.trim().toLowerCase().replace(/\s+/g, '_') : ctxProcess,
    };
    const b = await api.createWorkflowFromPlan(planId, context);
    setBound(b);
    return b;
  }, b => `workflow ${b.workflow_id} v${b.version} bound to plan + activated code`);

  const publish = () => gate(async () => {
    if (!bound) throw new Error('bind the workflow first');
    await api.registryPublish({
      slug: `client-followup-${planId.slice(0, 6)}`,
      title: `Client follow-up (${actionSel === 'update_status' ? 'status update' : 'drafts'})`,
      graph: bound.graph,
      compatible_connectors: ['sample-tracking-file'],
      publication_consent: true,
    });
    setPublished(true);
  }, 'published to registry (schema only, no records)');

  // Role awareness: plan/generate/bind are operator+; sandbox test + activation
  // approval are approver+ (backend enforces; the UI mirrors honestly). The
  // bind button checks server state (activation), not local session state, so
  // an operator can bind after an approver activates — the real team flow.
  const role = (live && live.me && live.me.role) || null;
  const rank = { observer: 0, operator: 1, approver: 2, owner: 3 }[role] ?? null;
  const canPlan = rank === null || rank >= 1;
  const canApprove = rank === null || rank >= 2;
  const canPublish = rank === null || rank >= 3;
  const isSoloTier = (live && live.me && live.me.capabilities && live.me.capabilities.tier === 'solo') || false;
  const isAdmin = !!(live && live.me && live.me.user && live.me.user.is_admin);
  const canSelfPromote = isSoloTier || isAdmin;

  const selfPromoteToApprover = async () => {
    setBusy(true); setErr(null);
    try {
      await api.teamSelfRole('owner');
      const me = await api.authMe();
      if (live) live.me = me;
      pushLine('ok', 'switched role to owner (solo workspace: unlocks sandbox test, activation and settings)');
    } catch (e) {
      setErr(e.message);
      pushLine('fail', `role update failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const canJumpToStep = (target) => {
    if (target <= step) return true;
    if (target === 2 || target === 3) return true;
    if (target === 4) return !!planId;
    if (target === 5) return !!(artifact && approval);
    return false;
  };

  const handleNextStep = async () => {
    if (busy) return;
    setErr(null);
    if (step === 1) {
      setStep(2);
    } else if (step === 2) {
      setStep(3);
    } else if (step === 3) {
      if (planId) {
        setStep(4);
      } else {
        await savePlan();
      }
    } else if (step === 4) {
      if (!artifact) {
        setErr('Please generate code before proceeding.');
        return;
      }
      if (!job || job.status !== 'passed') {
        setErr('Isolated sandbox test must pass before proceeding.');
        return;
      }
      if (!approval) {
        setErr('Human activation approval must be recorded before proceeding to bind.');
        return;
      }
      setStep(5);
    }
  };

  return (
    <div className="screen">
      <div className="screen-header">
        <div>
          <div className="breadcrumb">Create Automation</div>
          <h2>Create New Automation</h2>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {(planId || artifact || step > 1) && (
            <button className="btn-outline" style={{ padding: '5px 12px', fontSize: 13 }} onClick={startFresh}>
              Start Fresh
            </button>
          )}
          <span className={`badge ${connected ? 'green' : 'orange'}`}>{connected ? 'Worker: LIVE' : 'Worker offline — gates locked'}</span>
        </div>
      </div>

      <div className="card create-flow-card">
        <div className="stepper-row">
          {['Context', 'Capture', 'Plan', 'Verify', 'Bind & Publish'].map((title, index) => {
            const current = index + 1;
            const stateClass = current < step ? 'done' : current === step ? 'active' : 'todo';
            const reachable = canJumpToStep(current);
            return (
              <button key={title}
                      className={`step-item ${stateClass}`}
                      disabled={!reachable}
                      title={!reachable ? 'Complete preceding steps first' : ''}
                      onClick={() => { if (reachable) { setErr(null); setStep(current); } }}>
                <span>{current}</span>
                <p>{title}</p>
              </button>
            );
          })}
        </div>

        {step === 1 && (
          <div className="step-panel">
            <h3>Know your workflow context</h3>
            <p>Context only — the plan rules themselves are confirmed in step 3. The organization type drives the departments and process types offered; this classification is stored on the workflow.</p>
            {catalog ? (
              <div className="form-grid">
                <label>Organization type
                  <select value={ctxOrgType} onChange={e => setCtxOrgType(e.target.value)}>
                    {catalog.org_types.map(t => (
                      <option key={t} value={t}>{catalog.labels.org_type[t] || t}</option>
                    ))}
                  </select>
                </label>
                <label>Size
                  <select value={ctxSize} onChange={e => setCtxSize(e.target.value)} disabled={catalog.sizes_for_type[ctxOrgType]?.length === 1}>
                    {(catalog.sizes_for_type[ctxOrgType] || []).map(s => (
                      <option key={s} value={s}>{catalog.labels.size[s] || s}</option>
                    ))}
                  </select>
                </label>
                <label>Team / Department
                  <select value={ctxDept} onChange={e => setCtxDept(e.target.value)}>
                    {(catalog.departments[ctxOrgType] || []).map(d => (
                      <option key={d} value={d}>{catalog.labels.department[d] || d}</option>
                    ))}
                  </select>
                </label>
                <label>Process type
                  <select value={ctxProcess} onChange={e => setCtxProcess(e.target.value)} disabled={!!ctxOther.trim()}>
                    {(catalog.process_types[ctxDept] || catalog.default_process_types).map(p => (
                      <option key={p} value={p}>{catalog.labels.process_type[p] || p}</option>
                    ))}
                  </select>
                </label>
                <label>Other process type (optional — overrides the list)
                  <input placeholder="e.g. booth allocation for a fair" value={ctxOther}
                         onChange={e => setCtxOther(e.target.value)} />
                </label>
              </div>
            ) : (
              <p className="muted">Loading the organization catalog from the worker… (context selectors appear once it loads)</p>
            )}
            <div className="form-grid" style={{ marginTop: 14 }}>
              <label>Data Sensitivity
                <select defaultValue="Medium"><option>Low</option><option>Medium</option><option>High</option></select>
              </label>
              <label>Capture surfaces
                <select defaultValue="Tracking file (CSV)"><option>Tracking file (CSV)</option><option>Browser (synthetic contract)</option></select>
              </label>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="step-panel">
            <div className="step-head-row">
              <div>
                <h3>Live capture while you work</h3>
                <p>{connected
                  ? 'Polling the real watched folder. Saved + settled file changes produce contract-validated events; gaps are shown honestly.'
                  : 'The worker is offline, so capture is not running. Start the stack to observe real files — nothing is simulated here.'}</p>
              </div>
              <div className="monitor-actions" style={{ display: 'flex', gap: 8 }}>
                <button className="btn-outline" disabled={demoBusy} onClick={loadSampleWorkspace}
                        title="Replays the bundled SAMPLE sheets (invented companies) through the real diff and runs detection">
                  {demoBusy ? 'Loading sample data…' : 'Load sample workspace'}
                </button>
                {!monitoring
                  ? <button className="btn-primary" onClick={() => { setMonitoring(true); if (!connected) pushLine('warn', 'worker offline — polls will fail honestly'); }}><Icon d={ICONS.eye} size={16} /> Start Capture</button>
                  : <button className="btn-dark" onClick={() => setMonitoring(false)}>Pause capture</button>}
              </div>
            </div>
            {!monitoring && (
              <div className="info-banner" style={{ margin: '10px 0 16px', alignItems: 'center' }}>
                <Icon d={ICONS.eye} size={18} style={{ flexShrink: 0 }} />
                <span>Click the <b>"Start Capture"</b> button above to proceed with real-time event observation.</span>
              </div>
            )}
            <div className="stat-pair" style={{ marginBottom: 14 }}>
              <div className="stat-box"><div className="stat-val">{eventCount}</div><div className="stat-lbl">Events accepted</div></div>
              <div className="stat-box"><div className="stat-val">{realCands.length}</div><div className="stat-lbl">Real candidates</div></div>
            </div>
            <CaptureSettings onChanged={() => pushLine('dim', 'capture settings saved — next poll uses them')} />
            <Terminal title="autostack-capture — /api/capture/poll (real)" lines={monitorLines} running={monitoring} />
          </div>
        )}

        {step === 3 && (
          <div className="step-panel">
            <div className="step-head-row">
              <div>
                <h3>Confirm the plan</h3>
                <p>The plan is the only source of truth for generation and testing. Missing or contradictory rules block generation — no defaults are invented.</p>
              </div>
            </div>
            <div className="form-grid">
              <label>Eligibility status
                <select value={statusVal} onChange={e => setStatusVal(e.target.value)}>
                  <option>Follow-up due</option><option>New</option>
                </select>
              </label>
              <label>Due on or before
                <input type="date" value={dateVal} onChange={e => setDateVal(e.target.value)} />
              </label>
              <label>Action
                <select value={actionSel} onChange={e => setActionSel(e.target.value)}>
                  <option value="create_draft">Prepare in-app drafts</option>
                  <option value="update_status">Update tracking status</option>
                </select>
              </label>
              <label>Notify
                <select value={notifySel ? 'yes' : 'no'} onChange={e => setNotifySel(e.target.value === 'yes')}>
                  <option value="yes">Desktop + in-app</option>
                  <option value="no">In-app only</option>
                </select>
              </label>
            </div>
            <div className="detail-section">
              <div className="detail-label">Linked candidate (evidence-based, optional)</div>
              {realCands.length === 0
                ? <p className="op-sub">No live evidence-based candidates yet — the plan stands on its own confirmed rules.</p>
                : <div className="tag-row">
                    {realCands.map(c => (
                      <button key={c.id} className="tag" style={{ cursor: 'pointer',
                        borderColor: candidateId === `real-${c.id}` ? '#2563EB' : undefined }}
                        onClick={() => setCandidateId(candidateId === `real-${c.id}` ? null : `real-${c.id}`)}>
                        {((c.pattern && c.pattern.sequence) || []).join(' → ')} · {c.occurrences}×
                      </button>
                    ))}
                  </div>}
            </div>
            <div className="publish-actions">
              <button className="btn-primary" disabled={busy || !connected || !canPlan}
                      title={canPlan ? '' : 'creating workflows requires the operator role'} onClick={savePlan}>
                <Icon d={ICONS.check} size={16} /> {busy ? 'Saving…' : 'Confirm plan'}
              </button>
            </div>
            {planMissing.length > 0 && <p className="helper-error">Missing rules: {planMissing.join(', ')}</p>}
          </div>
        )}

        {step === 4 && (
          <div className="step-panel">
            <div className="step-head-row">
              <div>
                <h3>Generate, test in isolation, approve</h3>
                <p>Generated code passes static security validation, then runs in a subprocess sandbox against expected outputs derived from YOUR plan. A failed test blocks activation. Your approval is recorded separately.</p>
              </div>
            </div>
            {!canApprove && (
              <div className="info-banner" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <Icon d={ICONS.lock} size={18} style={{ flexShrink: 0 }} />
                  <span>
                    Sandbox testing and activation approval need the <b>approver</b> role — an operator generates code and an approver takes over from step 4. Your role: <b>{role || 'operator'}</b>.
                  </span>
                </div>
                {canSelfPromote && (
                  <button className="btn-primary" style={{ padding: '6px 14px', fontSize: 13, whiteSpace: 'nowrap', flexShrink: 0 }}
                          onClick={selfPromoteToApprover} disabled={busy}>
                    Switch to Owner Role (solo)
                  </button>
                )}
              </div>
            )}
            <div className="test-rail">
              {[
                ['Plan confirmed', !!planId, false, 'sha-bound'],
                ['Generated + static validation', !!artifact, false, artifact ? artifact.code_sha256.slice(0, 12) : 'awaiting generate'],
                ['Isolated sandbox test', !!(job && job.status === 'passed'), !!(job && job.status === 'failed'), job ? `job ${job.status}` : 'consent-gated'],
                ['Human activation approval', !!approval, false, approval ? 'recorded' : 'required'],
              ].map(([label, ok, failed, sub], i) => (
                <div key={label} className={`rail-row ${ok ? 'pass' : failed ? 'fail' : busy ? 'run' : 'wait'}`}>
                  <span className="rail-idx">{String(i + 1).padStart(2, '0')}</span>
                  <span className="rail-name">{label}<br /><span className="op-sub">{sub}</span></span>
                  <span className="rail-st">{ok ? 'PASS' : failed ? 'FAIL' : busy ? 'RUN' : '—'}</span>
                </div>
              ))}
            </div>
            {!artifact && (
              <label className="muted" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, margin: '12px 0 4px' }}>
                <input type="checkbox" checked={startBroken} onChange={e => setStartBroken(e.target.checked)} style={{ marginTop: 3 }} />
                <span><b>Start from a broken draft (demo).</b> The first version deliberately leaves out the due-date rule, so you can watch the sandbox catch it and the AI repair it. Everything after that first draft is the real loop.</span>
              </label>
            )}
            {genAttempts && genAttempts.length > 0 && (
              <CodeStream attempts={genAttempts} provider={genProvider} />
            )}
            <div className="publish-actions" style={{ flexWrap: 'wrap' }}>
              <button className="btn-outline" disabled={busy || !planId || !!artifact || !canPlan} onClick={generate}>
                {artifact ? '1 · Generated' : '1 · Generate'}
              </button>
              <button className="btn-outline" disabled={busy || !artifact || !canApprove}
                      title={canApprove ? '' : 'requires the approver role'} onClick={runTest}>
                {busy ? 'Running sandbox test…' : job && job.status === 'passed' ? '✓ Sandbox test passed (re-run)' : '2 · Run sandbox test'}
              </button>
              <button className="btn-primary" disabled={busy || !job || job.status !== 'passed' || !!approval || !canApprove}
                      title={canApprove ? '' : 'requires the approver role'} onClick={approve}>
                {approval ? '✓ Activation approved' : '3 · Approve activation'}
              </button>
              {approval && (
                <button className="btn-dark" onClick={() => { setErr(null); setStep(5); }}>
                  Continue to bind <Icon d={ICONS.arrow} size={14} />
                </button>
              )}
              {!approval && artifact && (
                <span className="muted" style={{ fontSize: 13, alignSelf: 'center', marginLeft: 6 }}>
                  Activation approval required before moving to Step 5 (binding).
                </span>
              )}
            </div>
            {job && job.report && (
              <div className="detail-section">
                <div className="detail-label">Isolated test report (content-bound by sha256)</div>
                {job.report.error && (
                  <div className="helper-error" style={{ marginBottom: 10 }}>
                    Test execution failed: {job.report.error}
                  </div>
                )}
                {(job.report.checks || []).map(c => (
                  <div key={c.name} className="approval-row">
                    <span className="mono">{c.name}</span>
                    <span className={`badge ${c.ok ? 'green' : 'red'}`}>{c.ok ? 'Pass' : 'Fail'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {step === 5 && (
          <div className="step-panel">
            <h3>Bind the workflow — then publish if you choose</h3>
            <p>Binding creates a versioned workflow whose hash covers graph + plan + activated code together. Publication is separate consent and shares the schema only.{!approval && ' Binding needs an ACTIVATED artifact — an approver must complete the sandbox test and activation approval first.'}</p>
            <div className="publish-box">
              <div className="publish-stat"><span>Plan</span><b>{planId ? `${planId.slice(0, 8)}…` : '—'}</b></div>
              <div className="publish-stat"><span>Activated code</span><b>{artifact ? `${artifact.code_sha256.slice(0, 10)}…` : '—'}</b></div>
              <div className="publish-stat"><span>Workflow</span><b>{bound ? `${bound.workflow_id} v${bound.version}` : 'not bound'}</b></div>
            </div>
            <div className="info-banner" style={{ margin: '14px 0', alignItems: 'center' }}>
              <Icon d={ICONS.eye} size={18} style={{ flexShrink: 0 }} />
              <span>
                To proceed with your automation, click the <b>"Start Capture"</b> button below to begin observing workflow activity.
              </span>
            </div>
            <div className="publish-actions" style={{ flexWrap: 'wrap' }}>
              <button className="btn-primary" disabled={busy || !!bound || !catalog || !canPlan || !artifact || !approval}
                      title={!approval ? 'Artifact must be tested and activated before binding' : ''}
                      onClick={bind}>
                <Icon d={ICONS.check} size={16} /> {bound ? 'Workflow bound' : 'Create workflow'}
              </button>
              <button className="btn-outline" onClick={() => { setErr(null); setStep(2); setMonitoring(true); }}>
                <Icon d={ICONS.eye} size={16} /> Start Capture
              </button>
              <button className="btn-outline" disabled={!bound || busy || published || !canPublish}
                      title={canPublish ? '' : 'publishing requires the owner role'} onClick={publish}>
                {published ? 'Published' : 'Publish to Registry'}
              </button>
              {bound && <button className="btn-dark" onClick={() => setPage('workflows')}>Go to Workflows <Icon d={ICONS.arrow} size={14} /></button>}
            </div>
          </div>
        )}

        {err && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 8, margin: '14px 0 0' }}>
            <p className="helper-error" style={{ margin: 0 }}>Gate refused: {err}</p>
            <button className="link" style={{ fontSize: 13, color: 'var(--text-3)' }} onClick={() => setErr(null)}>Dismiss</button>
          </div>
        )}

        <div className="step-actions">
          <button className="btn-outline" onClick={() => { setErr(null); setStep(prev => Math.max(1, prev - 1)); }} disabled={step === 1 || busy}>
            Back
          </button>
          {step < 5 ? (
            <button className="btn-primary"
                    onClick={handleNextStep}
                    disabled={busy || (step === 1 && !catalog) || (step === 3 && !canPlan) || (step === 4 && (!artifact || !job || job.status !== 'passed' || !approval))}
                    title={step === 4 && (!artifact || !job || job.status !== 'passed' || !approval) ? 'Complete sandbox test and activation approval before proceeding' : ''}>
              {busy ? 'Processing…' :
                step === 1 ? 'Next: Capture Observation' :
                step === 2 ? 'Next: Confirm Plan' :
                step === 3 ? (planId ? 'Next: Verify Code' : 'Confirm Plan & Next') :
                'Next: Bind Workflow'} <Icon d={ICONS.arrow} size={16} />
            </button>
          ) : bound ? (
            <button className="btn-primary" onClick={() => setPage('workflows')}>
              Go to Workflows <Icon d={ICONS.arrow} size={16} />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
