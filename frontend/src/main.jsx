import React, { useState, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { motion, AnimatePresence } from 'motion/react';
import './styles.css';
import './styles-premium.css';
import { subscribeLive, startLive } from './live.js';

import { Icon, ICONS, StatusBadge } from './main-shared.jsx';
import { PageTransition } from './premium.jsx';
import { Landing, AuthScreen, AppHome } from './landing.jsx';
import { FloatingNav } from './nav.jsx';

// ─── tiny icon set (inline SVG so no dependency issues) ───────────────────────
// ─── data ─────────────────────────────────────────────────────────────────────
// ─── screens ──────────────────────────────────────────────────────────────────
// Dashboard/Workflows/Registry/TrustLog are live modules (Phase 10).
import { Dashboard, Workflows, Registry, TrustLog } from './screens-live.jsx';
import { NotificationCenter, DataPrivacy, Connectors } from './roadmap-complete.jsx';
import { api, setToken } from './api.js';
import { Login, Profile, Teams, Runners, Scheduling } from './roadmap-pages.jsx';
import { Settings } from './settings.jsx';
import { describePattern, whyNotSuggested } from './pattern-words.js';
import { Practice } from './practice.jsx';

function Discovery({ setPage }) {
  const [selected, setSelected] = useState(null);
  const [drafted, setDrafted] = useState([]);
  const [live, setLive] = useState(null);
  useEffect(() => subscribeLive(setLive), []);

  const all = (live && live.connected && live.candidates) || [];
  const shown = all.filter(c => c.status === 'suggested').map(c => ({ id: `real-${c.id}`, raw: c, d: describePattern(c) }));
  const nearMisses = all.filter(c => c.status === 'observed').map(c => ({ id: `obs-${c.id}`, d: describePattern(c) }));
  const [dismissedIds, setDismissedIds] = useState([]);
  const [dismissErr, setDismissErr] = useState(null);
  const dismissReal = async (realId) => {
    setDismissErr(null);
    try { await api.dismissCandidate(realId); setDismissedIds(d => [...d, realId]); }
    catch (e) { setDismissErr(e.message); }
  };
  const visible = shown.filter(c => !dismissedIds.includes(c.id));

  return (
    <div className="screen">
      <div className="screen-header">
        <div>
          <div className="breadcrumb">Discovery Engine</div>
          <h2>What AutoStack identified</h2>
        </div>
      </div>

      <div className="info-banner">
        <Icon d={ICONS.eye} size={18} />
        <span>Built from saved spreadsheet changes in your watched folder: which rows changed and which columns. Cell values, keystrokes and screens are not recorded. Rule: <b>the same steps, 3+ times, on 2+ different records</b>.</span>
      </div>

      <div className="two-col" style={{ alignItems: 'flex-start' }}>
        <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
          {dismissErr && <div className="info-banner"><span>Dismiss refused: {dismissErr}</span></div>}
          {visible.length === 0 && (
            <div className="card empty-state" style={{ padding: 24 }}>
              <p>Nothing identified yet. Patterns appear only from real repeated work (3+ times across 2+ records). Try <b>Create → Load sample workspace</b>.</p>
            </div>
          )}
          {visible.map(c => (
            <div key={c.id}
                 className={`card candidate-card ${selected?.id === c.id ? 'selected' : ''}`}
                 onClick={() => setSelected(c)}>
              <span className="identified-tag">IDENTIFIED · CAN BE AUTOMATED</span>
              <div className="op-name">{c.d.title}</div>
              <div className="identified-kinds">{c.d.kinds.map(k => <span key={k}>{k}</span>)}</div>
              <div className="candidate-meta">
                <span><Icon d={ICONS.refresh} size={14} /> {c.d.steps.length} steps, done {c.d.instances} times</span>
                <span><Icon d={ICONS.users} size={14} /> on {c.d.distinct} records</span>
              </div>
              <div style={{ marginTop: 8 }}>
                <button className="btn-outline" onClick={(e) => { e.stopPropagation(); dismissReal(c.id.slice(5)); }}>
                  Not useful, dismiss
                </button>
              </div>
            </div>
          ))}
          {nearMisses.length > 0 && (
            <div className="card" style={{ padding: 16 }}>
              <div className="detail-label">Seen, but not suggested</div>
              {nearMisses.map(n => (
                <p key={n.id} className="op-sub" style={{ margin: '8px 0 0' }}>
                  <b>{n.d.title}</b> ({n.d.steps.join(' → ')}): {whyNotSuggested(n.d)}.
                </p>
              ))}
            </div>
          )}
        </div>

        <div>
          {selected ? (
            <div className="card" style={{ position:'sticky', top:20 }}>
              <div className="card-header">
                <strong>{selected.d.title}</strong>
                <button className="btn-icon small" onClick={() => setSelected(null)}><Icon d={ICONS.x} size={16} /></button>
              </div>
              <div className="detail-section">
                <div className="detail-label">Type of work</div>
                <div className="identified-kinds">{selected.d.kinds.map(k => <span key={k}>{k}</span>)}</div>
              </div>
              <div className="detail-section">
                <div className="detail-label">The routine, step by step</div>
                <ol className="steps-list">
                  {selected.d.steps.map((s, i) => <li key={i}>Someone {s}</li>)}
                </ol>
              </div>
              <div className="detail-section">
                <div className="detail-label">Evidence</div>
                <p className="op-sub" style={{ margin: 0 }}>
                  Same {selected.d.steps.length} steps, in the same order, {selected.d.instances} times on {selected.d.distinct} records: {selected.d.records.join(', ')}.
                </p>
              </div>
              <button
                className={`btn-primary full-w ${drafted.includes(selected.id) ? 'success' : ''}`}
                onClick={() => {
                  setDrafted(d => [...d, selected.id]);
                  setTimeout(() => setPage('create'), 800);
                }}
              >
                {drafted.includes(selected.id)
                  ? <><Icon d={ICONS.check} size={16} /> Sent to Create Flow</>
                  : <><Icon d={ICONS.zap} size={16} /> Automate this</>}
              </button>
            </div>
          ) : (
            <div className="card empty-state">
              <Icon d={ICONS.search} size={32} />
              <p>Select an identified pattern to see the steps and the evidence.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// CreateAutomation now lives in its own module (real backend-gated stepper).
import { CreateAutomation } from './create-automation.jsx';
import { spring } from './motion.js';

// Unknown hashes must never dead-end: the router falls back to a real page
// with a working path back into the app.
function NotFound({ setPage }) {
  return (
    <div className="screen">
      <header className="screen-head">
        <div>
          <h1>Page not found</h1>
          <p className="muted">That link doesn't match any page in this workspace.</p>
        </div>
      </header>
      <div style={{ display: 'flex', gap: 10 }}>
        <button className="btn" onClick={() => setPage('dashboard')}>Go to Dashboard</button>
        <button className="btn-outline" onClick={() => setPage('landing')}>Go to Home</button>
      </div>
    </div>
  );
}

function App() {
  // Hash router: the URL is the source of truth, so deep links (#/page) survive
  // reloads and every navigation writes a shareable hash. Unknown hashes render
  // NotFound (never a blank screen).
  const pageForHash = () => {
    const h = (window.location.hash || '').replace(/^#/, '');
    if (!h) return 'landing'; // root URL → landing homepage
    // Settings owns its sub-path (#/settings/<section>); the app router only
    // needs to know the context is "settings".
    if (h.startsWith('settings')) return 'settings';
    return h;
  };
  const [page, setPageState] = useState(pageForHash);
  const setPage = (p) => {
    if (window.location.hash !== '#' + p) window.location.hash = p;
    else setPageState(p);
  };
  useEffect(() => {
    const onHash = () => setPageState(pageForHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const [live, setLive] = useState(null);
  const [identity, setIdentity] = useState(null);
  const [authState, setAuthState] = useState('checking'); // checking|anon|ok
  const [authMode, setAuthMode] = useState(null); // null → landing; 'login'|'signup' → auth hero
  useEffect(() => {
    const unsubscribe = subscribeLive(setLive);
    startLive(4000);
    api.authMe().then((me) => { setIdentity(me); setAuthState('ok'); })
      .catch(() => setAuthState('anon'));
    return unsubscribe;
  }, []);
  const workerUp = !!(live && live.connected);
  if (authState === 'checking') {
    return <div className="login-wrap"><div className="muted">Connecting to worker…</div></div>;
  }
  if (authState === 'anon') {
    // Cinematic landing is the entry surface; the auth card appears as a
    // hero-split screen (AuthScreen) so context is never lost.
    if (!authMode) {
      return <Landing
        workerUp={workerUp}
        onSignUp={() => setAuthMode('signup')}
        onSignIn={() => setAuthMode('login')}
      />;
    }
    return (
      <AuthScreen
        onSignIn={() => setAuthMode('login')}
        onSignUp={() => setAuthMode('signup')}
      >
        <Login
          setPage={setPage}
          initialMode={authMode}
          onBack={() => setAuthMode(null)}
          setIdentity={(me) => { setIdentity(me); setAuthState('ok'); }}
        />
      </AuthScreen>
    );
  }
  // BUGFIX (Phase 2 audit): Dashboard/Discovery/Workflows/Create render real
  // navigation buttons that call setPage — they must receive it, or every one
  // of those buttons throws "setPage is not a function" on click.
  const screenMap = {
    landing: <AppHome setPage={setPage} />,
    settings: <Settings identity={identity} onExit={() => setPage('dashboard')} setPage={setPage} />,
    profile: <Profile identity={identity} />,
    teams: <Teams identity={identity} />,
    runners: <Runners identity={identity} />,
    scheduling: <Scheduling identity={identity} />,
    notifications: <NotificationCenter />,
    privacy: <DataPrivacy />,
    connectors: <Connectors />,
    dashboard: <Dashboard setPage={setPage} />,
    practice: <Practice setPage={setPage} />,
    discovery: <Discovery setPage={setPage} />,
    registry: <Registry identity={identity} />,
    workflows: <Workflows setPage={setPage} />,
    create: <CreateAutomation setPage={setPage} />,
    trustlog: <TrustLog />,
  };
  const Screen = screenMap[page] || <NotFound setPage={setPage} />;

  const doSignOut = async () => {
    setToken('');
    setIdentity(null);
    setAuthState('anon');
    setPage('dashboard');
  };
  const isOwner = !!(identity && identity.role === 'owner');

  return (
    <div className="shell">
      <FloatingNav
        page={page} setPage={setPage}
        identity={identity} isOwner={isOwner}
        live={live} onSignOut={doSignOut}
      />
      <main className="main">
        <PageTransition pageKey={page}>
          {Screen}
        </PageTransition>
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
