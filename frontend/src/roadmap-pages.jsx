// Roadmap pages: Login, Home, Settings, Profile, Teams, Runners, Scheduling.
// Every value shown is real backend state; gated features render their
// requirement instead of a fake state (project rule: no invented anything).
import { useState } from 'react';
import { Icon, ICONS, Terminal, stamp, Card, Row, Gate } from './main-shared.jsx';
import { api, setToken, getToken } from './api.js';
import { MagneticButton } from './premium.jsx';

// ── shared bits ───────────────────────────────────────────────────────────────

// ── Login / Signup ────────────────────────────────────────────────────────────

export function Login({ setPage, setIdentity, initialMode = 'login', onBack }) {
  const [mode, setMode] = useState(initialMode);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (busy) return; // double-submission guard
    setBusy(true);
    setMsg(null);
    try {
      if (mode === 'signup') {
        await api.authRegister(username, password, displayName);
      }
      const issued = await api.authIssueToken(username, password, 'dashboard');
      setToken(issued.token);
      const me = await api.authMe();
      setIdentity(me);
      setPage('landing');
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <h2>{mode === 'login' ? 'Sign in to AutoStack' : 'Create your local account'}</h2>
        <p className="muted">Local-first: your account lives on this machine. The first account administers it.</p>
        <label>Username
          <input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        {mode === 'signup' && (
          <label>Display name
            <input value={displayName} onChange={e => setDisplayName(e.target.value)} />
          </label>
        )}
        <label>Password
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                 autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength={8} />
        </label>
        {msg && <div className="error" role="alert">{msg}</div>}
        <MagneticButton className="primary" type="submit" disabled={busy} style={{ width: '100%', padding: '11px 16px' }}>
          {busy ? (mode === 'login' ? 'Signing in…' : 'Creating account…')
                : (mode === 'login' ? 'Sign in' : 'Create account')}
        </MagneticButton>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <button type="button" className="link" onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}>
            {mode === 'login' ? 'Need an account? Create one' : 'Have an account? Sign in'}
          </button>
          {onBack && (
            <button type="button" className="link" onClick={onBack}>
              ← Back
            </button>
          )}
        </div>
      </form>
    </div>
  );
}


// ── Settings ──────────────────────────────────────────────────────────────────

export function Settings({ identity }) {
  const caps = identity && identity.capabilities;
  const [name, setName] = useState('');
  const [result, setResult] = useState(null);
  const [tier, setTier] = useState(null);

  async function switchTier(t) {
    setResult(null);
    try {
      const capsNow = await api.setTier(t, name || undefined);
      setTier(capsNow);
      setResult(`Tier switched to ${capsNow.tier}.`);
    } catch (err) { setResult(err.message); }
  }

  return (
    <div className="screen">
      <header className="screen-head">
        <div><h1>Settings</h1><p className="muted">Workspace controls — enforced server-side, mirrored here.</p></div>
      </header>

      <Card title="Account & tier">
        <p className="muted">The tier gates real capabilities on the worker. Solo is the free default; other tiers model what a paid plan unlocks.</p>
        <div className="tier-buttons">
          {['solo', 'team', 'enterprise', 'government', 'developer'].map(t => (
            <button key={t} className={`chip ${caps && caps.tier === t ? 'on' : ''}`}
                    onClick={() => switchTier(t)} disabled={!tier && !(identity && identity.capabilities)}>{t}</button>
          ))}
        </div>
        <div className="field">
          <input placeholder="Organization name (optional)" value={name} onChange={e => setName(e.target.value)} />
        </div>
        {result && <div className="muted">{result}</div>}
      </Card>

      <div className="grid2">
        <Gate capability="retention_admin" caps={caps}>
          <Card title="Data & privacy (retention admin)">
            <Row><div>Observations: 30 days default</div></Row>
            <Row><div>Reports &amp; history: 90 days default</div></Row>
            <Row><div className="muted">Retention, export, and the consent ledger live on the Data &amp; Privacy page; the audit ledger is never deleted.</div></Row>
          </Card>
        </Gate>
        <Gate capability="sso" caps={caps}>
          <Card title="Single sign-on">
            <SSOStatus />
          </Card>
        </Gate>
      </div>

      <Card title="About this build">
        <Row><div>Worker: FastAPI on 127.0.0.1:8747 · Node-RED embedded on :18790</div></Row>
        <Row><div className="muted">All effects exactly-once via the effect journal; audit ledger is hash-chained.</div></Row>
      </Card>
    </div>
  );
}

function SSOStatus() {
  const [status, setStatus] = useState(null);
  useState(() => { api.ssoStatus().then(setStatus).catch(() => setStatus({ enabled: false })); });
  return <Row><div>{status ? (status.enabled ? `Enabled — ${status.provider}` : 'Not enabled on this tier') : '…'}</div></Row>;
}

// ── Profile / API tokens ──────────────────────────────────────────────────────

export function Profile({ identity }) {
  const [tokens, setTokens] = useState(null);
  const [newToken, setNewToken] = useState(null);
  const user = identity && identity.user;

  async function refresh() { try { setTokens(await api.authListTokens()); } catch { setTokens({ tokens: [] }); } }
  useState(() => { refresh(); });

  async function issue() {
    const pwd = prompt('Confirm your password to issue a token:');
    if (!pwd) return;
    try {
      const issued = await api.authIssueToken(user.username, pwd, 'from-profile');
      setNewToken(issued.token);
      refresh();
    } catch (err) { setNewToken(null); alert(err.message); }
  }

  return (
    <div className="screen">
      <header className="screen-head">
        <div><h1>Profile</h1><p className="muted">Your identity and API tokens on this machine.</p></div>
      </header>
      <Card title="Account">
        <Row><div>Username: {user ? user.username : 'service token (no local user)'}</div></Row>
        <Row><div>Display name: {user && user.display_name ? user.display_name : '—'}</div></Row>
        <Row><div>Role: {identity ? identity.role : '—'}</div></Row>
      </Card>
      <Card title="API tokens" actions={<button className="link" onClick={issue}>Issue new token</button>}>
        {newToken && (
          <div className="token-reveal">
            <strong>Copy it now — shown once:</strong>
            <code>{newToken}</code>
          </div>
        )}
        {tokens ? (
          tokens.tokens.length === 0
            ? <p className="muted">No tokens yet. Issue one to call the worker API as this user.</p>
            : tokens.tokens.map(t => (
              <Row key={t.id}>
                <div>{t.name} <span className="muted">({t.prefix}…)</span></div>
                <button className="link danger" onClick={async () => { await api.authRevokeToken(t.id); refresh(); }}>revoke</button>
              </Row>
            ))
        ) : <p className="muted">Loading…</p>}
      </Card>
    </div>
  );
}

// ── Teams ─────────────────────────────────────────────────────────────────────

const ROLES = ['observer', 'operator', 'approver', 'owner'];

export function Teams({ identity }) {
  const isOwner = !!(identity && identity.role === 'owner');
  const [members, setMembers] = useState(null);
  const [invites, setInvites] = useState(null);
  const [processes, setProcesses] = useState(null);
  const [username, setUsername] = useState('');
  const [invite, setInvite] = useState(null);
  const [procName, setProcName] = useState('');
  const [err, setErr] = useState(null);
  const [procErr, setProcErr] = useState(null);

  async function refresh() {
    try {
      setMembers(await api.teamMembers());
      setInvites(await api.teamInvitations());
      setProcesses(await api.processes());
    } catch (e) { setErr(e.message); }
  }
  useState(() => { refresh(); });

  return (
    <div className="screen">
      <header className="screen-head">
        <div><h1>Teams</h1><p className="muted">Members, roles, invitations, and business processes.</p></div>
      </header>
      {err && <div className="error">{err}</div>}

      <Card title="Members">
        {members && members.members.map(m => (
          <Row key={m.membership_id}>
            <div>{m.display_name || m.username} <span className="muted">({m.username})</span></div>
            <div>
              {isOwner ? (
                <select value={m.role} onChange={async e => { await api.teamSetRole(m.membership_id, e.target.value); refresh(); }}>
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              ) : <span className="muted">{m.role}</span>}
            </div>
          </Row>
        ))}
        {members && members.members.length === 0 && <p className="muted">No members yet.</p>}
        {!isOwner && <p className="muted">Changing roles requires the owner role.</p>}
      </Card>

      <Card title="Invite a teammate">
        {isOwner ? (
          <>
            <div className="field"><input placeholder="username of a local account" value={username} onChange={e => setUsername(e.target.value)} /></div>
            <button className="primary" onClick={async () => { await api.teamAddMember(username, 'operator'); setUsername(''); refresh(); }}>Add as operator</button>
            <button className="link" onClick={async () => {
              const out = await api.teamCreateInvitation('approver');
              setInvite(out);
              refresh();
            }}>Create approver invitation</button>
            {invite && (
              <div className="token-reveal"><strong>Invitation token (share over a trusted channel):</strong><code>{invite.token}</code></div>
            )}
          </>
        ) : (
          <p className="muted">Inviting members requires the owner role.</p>
        )}
        {invites && invites.invitations.map(i => (
          <Row key={i.id}>
            <div>invitation · {i.role} · expires {new Date(i.expires_at).toLocaleString()}</div>
            {!i.accepted && <button className="link danger" onClick={async () => { await api.teamRevokeInvitation(i.id); refresh(); }}>revoke</button>}
          </Row>
        ))}
      </Card>

      <Card title="Business processes">
        {isOwner && (
          <>
            <div className="field"><input placeholder="new process name" value={procName} onChange={e => setProcName(e.target.value)} /></div>
            <button className="primary" onClick={async () => {
              setProcErr(null);
              try { await api.createProcess(procName); setProcName(''); refresh(); }
              catch (e) { setProcErr(e.message); }
            }}>Create process</button>
            {procErr && <div className="error">{procErr}</div>}
          </>
        )}
        {!isOwner && <p className="muted">Creating processes requires the owner role.</p>}
        {processes && processes.processes.map(p => (
          <Row key={p.id}><div>{p.name} <span className="muted">quota/day: {p.run_quota_per_day || 'unlimited'}</span></div></Row>
        ))}
      </Card>
    </div>
  );
}

// ── Runners ───────────────────────────────────────────────────────────────────

export function Runners({ identity }) {
  const isOwner = !!(identity && identity.role === 'owner');
  const [runners, setRunners] = useState(null);
  const [name, setName] = useState('');
  const [pairing, setPairing] = useState(null);
  const [err, setErr] = useState(null);
  const [regErr, setRegErr] = useState(null);

  async function refresh() { try { setRunners(await api.runners()); } catch (e) { setErr(e.message); } }
  useState(() => { refresh(); });

  return (
    <div className="screen">
      <header className="screen-head">
        <div><h1>Runners</h1><p className="muted">Local execution and paired office machines (README §7 modes).</p></div>
      </header>
      {err && <div className="error">{err}</div>}
      <Card title="Register a runner">
        {isOwner ? (
          <>
            <div className="field"><input placeholder="runner name" value={name} onChange={e => setName(e.target.value)} /></div>
            <button className="primary" onClick={async () => {
              setRegErr(null);
              try { await api.registerRunner(name || 'local-runner', 'local'); setName(''); refresh(); }
              catch (e) { setRegErr(e.message); }
            }}>Register local runner</button>
            <button className="link" onClick={async () => {
              setRegErr(null);
              try {
                const r = await api.registerRunner(name || 'office-runner', 'paired');
                const p = await api.pairRunner(r.runner_id);
                setPairing(p);
                refresh();
              } catch (e) { setRegErr(e.message); }
            }}>Register paired runner (team tier)</button>
            {regErr && <div className="error">{regErr}</div>}
            {pairing && (
              <div className="token-reveal">
                <strong>Pairing code — enter on the runner host:</strong>
                <code>{pairing.pairing_code}</code>
                <div className="muted">fingerprint {pairing.fingerprint}</div>
              </div>
            )}
          </>
        ) : (
          <p className="muted">Registering and pairing runners requires the owner role.</p>
        )}
      </Card>
      <Card title="Registered runners">
        {runners && runners.runners.map(r => (
          <Row key={r.id}>
            <div>{r.name} <span className="muted">({r.kind})</span></div>
            <div>
              <span className={`badge ${r.status === 'paired' || r.status === 'online' ? 'ok' : ''}`}>{r.status}</span>
              {r.status !== 'revoked' && <button className="link danger" onClick={async () => { await api.revokeRunner(r.id); refresh(); }}>revoke</button>}
            </div>
          </Row>
        ))}
        {runners && runners.runners.length === 0 && <p className="muted">No runners registered.</p>}
      </Card>
    </div>
  );
}

// ── Scheduling (opt-in, evidence-gated) ───────────────────────────────────────

export function Scheduling({ identity }) {
  // Triggers are workflows-management: operator+ can create/enable/disable
  // (backend requires "run"); the old owner-only gate falsely blocked operators.
  const rank = { observer: 0, operator: 1, approver: 2, owner: 3 }[identity && identity.role] ?? -1;
  const canManage = rank >= 1;
  const [wfs, setWfs] = useState(null);
  const [triggers, setTriggers] = useState(null);
  const [wid, setWid] = useState('');
  const [dates, setDates] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [err, setErr] = useState(null);

  async function refresh() {
    try { setWfs(await api.listWorkflows()); setTriggers(await api.triggers()); }
    catch (e) { setErr(e.message); }
  }
  useState(() => { refresh(); });

  return (
    <div className="screen">
      <header className="screen-head">
        <div><h1>Scheduling</h1><p className="muted">Opt-in recurring runs. Schedules require real calendar evidence — accelerated demos can never create one.</p></div>
      </header>
      {err && <div className="error">{err}</div>}
      <Card title="Create a schedule">
        {canManage ? (
          <>
            <div className="field">
              <select value={wid} onChange={e => setWid(e.target.value)}>
                <option value="">choose a workflow…</option>
                {wfs && wfs.workflows.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </div>
            <div className="field">
              <input placeholder="observed dates (comma separated, e.g. 2026-09-01, 2026-09-08, 2026-09-15)"
                     value={dates} onChange={e => setDates(e.target.value)} />
            </div>
            <label className="check">
              <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
              I confirm this recurrence from real usage (not a demo cycle)
            </label>
            <button className="primary" onClick={async () => {
              setErr(null);
              try {
                const config = {
                  observed_dates: dates.split(',').map(s => s.trim()).filter(Boolean),
                  user_confirmed: confirmed,
                };
                await api.createTrigger(wid, 'schedule', config, confirmed ? 'user-confirmed recurrence' : 'observed dates');
                refresh();
              } catch (e) { setErr(e.message); }
            }}>Create schedule</button>
            <p className="muted">Schedules need 3+ distinct observed dates or explicit confirmation — enforced by the worker.</p>
          </>
        ) : (
          <p className="muted">Creating schedules requires the operator role or higher.</p>
        )}
      </Card>
      <Card title="Triggers">
        {triggers && triggers.triggers.map(t => (
          <Row key={t.id}>
            <div>{t.kind} → {t.workflow_id} {t.enabled ? '' : '(disabled)'}</div>
            {canManage && (
              <button className="link" onClick={async () => { try { await (t.enabled ? api.disableTrigger(t.id) : api.enableTrigger(t.id)); refresh(); } catch (e) { setErr(e.message); } }}>
                {t.enabled ? 'disable' : 'enable'}
              </button>
            )}
          </Row>
        ))}
        {triggers && triggers.triggers.length === 0 && <p className="muted">No triggers yet.</p>}
      </Card>
    </div>
  );
}
