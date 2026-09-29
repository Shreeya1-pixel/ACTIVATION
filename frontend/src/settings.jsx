// Dedicated Settings experience (contract Phases 7–9): a real context with its
// own two-pane navigation — never the application sidebar. Deep-linkable via
// #/settings/<section> so refresh and back/forward keep the section.
// Role model mirrors the backend exactly: admin actions (tier, org name) render
// ONLY for owner; everyone else gets the real read-only state plus the
// requirement — the worker remains authoritative either way.
import React, { useEffect, useState } from 'react';
import { Icon, ICONS, Card, Row, Gate } from './main-shared.jsx';
import { ThemeSwitcher, Reveal } from './premium.jsx';
import { api } from './api.js';
import { getTheme, setTheme } from './theme.js';

const SECTIONS = [
  { id: 'general',    label: 'General',        icon: ICONS.grid },
  { id: 'profile',    label: 'Profile',        icon: ICONS.user },
  { id: 'appearance', label: 'Appearance',     icon: ICONS.eye },
  { id: 'security',   label: 'Security',       icon: ICONS.shield },
  { id: 'organization', label: 'Organization', icon: ICONS.users, owner: true },
];

function SettingsNav({ sections, active, onNavigate }) {
  return (
    <nav className="settings-nav" aria-label="Settings sections">
      <div className="settings-nav-label">Settings</div>
      {sections.map(s => (
        <button
          key={s.id}
          className={`settings-nav-item ${active === s.id ? 'active' : ''}`}
          aria-current={active === s.id ? 'page' : undefined}
          onClick={() => onNavigate(s.id)}
        >
          <Icon d={s.icon} size={16} />
          <span>{s.label}</span>
        </button>
      ))}
    </nav>
  );
}

function SectionHead({ title, sub, children }) {
  return (
    <header className="settings-head">
      <div>
        <h1>{title}</h1>
        <p className="muted">{sub}</p>
      </div>
      {children}
    </header>
  );
}

// ── General: build facts (no invented settings) ───────────────────────────────
function GeneralSection() {
  return (
    <div className="settings-body">
      <SectionHead title="General" sub="About this installation. Everything here is read from the running worker." />
      <Card title="About this build">
        <Row><div>Worker: FastAPI on 127.0.0.1:8747 · Node-RED embedded on :18790</div></Row>
        <Row><div className="muted">All effects are exactly-once via the effect journal; the audit ledger is hash-chained.</div></Row>
      </Card>
      <Card title="Governance exports">
        <GovernanceStatus />
      </Card>
    </div>
  );
}

function GovernanceStatus() {
  const [state, setState] = useState(null);
  useState(() => {
    api.capabilities().then(caps => setState(caps)).catch(() => setState({}));
  });
  const has = (k) => state && (state[k] === true || (typeof state[k] === 'number' && state[k] > 0));
  return (
    <>
      <Row><div>Audit ledger export</div><div className={has('api_access') ? 'badge ok' : 'muted'}>{has('api_access') ? 'available (governance/audit-export)' : 'enterprise tier capability'}</div></Row>
      <Row><div>SIEM streaming</div><div className={has('siem_export') ? 'badge ok' : 'muted'}>{has('siem_export') ? 'available (governance/siem/stream)' : 'enterprise tier capability'}</div></Row>
      <Row><div>Compliance bundle</div><div className={has('siem_export') ? 'badge ok' : 'muted'}>{has('siem_export') ? 'available (governance/compliance-bundle)' : 'enterprise tier capability'}</div></Row>
    </>
  );
}

// ── Profile: identity + API tokens (moved from the old Profile screen) ────────
function ProfileSection({ identity }) {
  const [tokens, setTokens] = useState(null);
  const [newToken, setNewToken] = useState(null);
  const user = identity && identity.user;

  async function refresh() { try { setTokens(await api.authListTokens()); } catch { setTokens({ tokens: [] }); } }
  useState(() => { refresh(); });

  async function issue() {
    const pwd = window.prompt('Confirm your password to issue a token:');
    if (!pwd) return;
    try {
      const issued = await api.authIssueToken(user.username, pwd, 'from-settings');
      setNewToken(issued.token);
      refresh();
    } catch (err) { setNewToken(null); window.alert(err.message); }
  }
  async function revoke(id) {
    try { await api.authRevokeToken(id); refresh(); } catch (e) { window.alert(e.message); }
  }

  return (
    <div className="settings-body">
      <SectionHead title="Profile" sub="Your identity and API tokens on this machine." />
      <Card title="Account">
        <Row><div>Username</div><div>{user ? user.username : 'service token (no local user)'}</div></Row>
        <Row><div>Display name</div><div>{user && user.display_name ? user.display_name : '—'}</div></Row>
        <Row><div>Role</div><div>{identity ? identity.role : '—'}</div></Row>
        <Row><div>Organization</div><div>{identity && identity.org_name ? identity.org_name : '—'}</div></Row>
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
                <button className="link danger" onClick={() => revoke(t.id)}>revoke</button>
              </Row>
            ))
        ) : <p className="muted">Loading…</p>}
      </Card>
    </div>
  );
}

// ── Appearance: real theme state + live preview ───────────────────────────────
function AppearanceSection() {
  const [theme, setThemeState] = useState(getTheme());
  const current = theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme;
  return (
    <div className="settings-body">
      <SectionHead title="Appearance" sub="Light, dark, or follow your system. The preference applies to the whole application." />
      <Card title="Color theme">
        <ThemeSwitcher />
        <Row><div className="muted">Currently rendering: <strong>{current}</strong> surfaces{theme === 'system' ? ' (from your OS preference)' : ''}.</div></Row>
      </Card>
      <Card title="Motion">
        <Row><div>Reduced motion</div><div className="muted">Follows your OS “prefers reduced motion” setting automatically.</div></Row>
      </Card>
    </div>
  );
}

// ── Security: sessions are real API tokens with prefix + expiry ───────────────
function SecuritySection({ identity }) {
  const [tokens, setTokens] = useState(null);
  async function refresh() { try { setTokens(await api.authListTokens()); } catch { setTokens({ tokens: [] }); } }
  useState(() => { refresh(); });
  return (
    <div className="settings-body">
      <SectionHead title="Security" sub="Credential health on this machine. Revoking a token ends that session immediately." />
      <Card title="Access tokens (sessions)" actions={<button className="link" onClick={refresh}>Refresh</button>}>
        {tokens ? (
          tokens.tokens.length === 0
            ? <p className="muted">No active API tokens.</p>
            : tokens.tokens.map(t => (
              <Row key={t.id}>
                <div>{t.name} <span className="muted">({t.prefix}…){t.expires_at ? ` · expires ${String(t.expires_at).slice(0, 10)}` : ''}</span></div>
                <button className="link danger" onClick={async () => { await api.authRevokeToken(t.id); refresh(); }}>revoke</button>
              </Row>
            ))
        ) : <p className="muted">Loading…</p>}
      </Card>
      <Card title="Audit chain">
        <Row><div className="muted">The append-only, hash-chained audit ledger is verifiable on the Trust Log page. It is never deleted.</div></Row>
      </Card>
    </div>
  );
}

// ── Organization: owner-only administration; others get real state ────────────
function OrgProfileCard({ isOwner }) {
  const [profile, setProfile] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [draft, setDraft] = useState({ org_type: '', size: '', department: '' });
  const [result, setResult] = useState(null);

  async function refresh() {
    try {
      const p = await api.orgProfile();
      setProfile(p.profile || {});
      setDraft({ org_type: (p.profile && p.profile.org_type) || 'corporate',
                 size: (p.profile && p.profile.size) || 'medium',
                 department: (p.profile && p.profile.department) || 'finance' });
      setCatalog(await api.orgCatalog());
    } catch (e) { setResult(e.message); }
  }
  useState(() => { refresh(); });

  async function save() {
    setResult(null);
    try {
      await api.setOrgProfile(draft.org_type, draft.size, draft.department);
      await refresh();
      setResult('Organization profile saved — new workflows default to this context.');
    } catch (e) { setResult(e.message); }
  }

  const sizes = (catalog && catalog.sizes_for_type[draft.org_type]) || [];
  const depts = (catalog && catalog.departments[draft.org_type]) || [];
  const label = (kind, v) => (catalog && catalog.labels[kind] && catalog.labels[kind][v]) || v;

  return (
    <Card title="Organization profile">
      <p className="muted">Type, size, and department drive which departments and process types the create wizard offers. Government agencies, companies of any size, and individuals are all first-class.</p>
      {catalog && isOwner ? (
        <>
          <div className="form-grid">
            <label>Organization type
              <select value={draft.org_type} onChange={e => setDraft({ ...draft, org_type: e.target.value })}>
                {catalog.org_types.map(t => <option key={t} value={t}>{catalog.labels.org_type[t] || t}</option>)}
              </select>
            </label>
            <label>Size
              <select value={draft.size} onChange={e => setDraft({ ...draft, size: e.target.value })} disabled={sizes.length === 1}>
                {sizes.map(s => <option key={s} value={s}>{catalog.labels.size[s] || s}</option>)}
              </select>
            </label>
            <label>Primary department
              <select value={draft.department} onChange={e => setDraft({ ...draft, department: e.target.value })}>
                {depts.map(d => <option key={d} value={d}>{catalog.labels.department[d] || d}</option>)}
              </select>
            </label>
          </div>
          <button className="btn" onClick={save}>Save organization profile</button>
        </>
      ) : profile ? (
        <Row><div>
          {label('org_type', profile.org_type) || '—'} · {label('size', profile.size) || '—'} · {label('department', profile.department) || '—'}
          {!isOwner && <span className="muted"> (changing it requires the owner role)</span>}
        </div></Row>
      ) : (
        <div className="muted">Loading…</div>
      )}
      {result && <div className="muted">{result}</div>}
    </Card>
  );
}

function OrganizationSection({ identity, setPage }) {
  const caps = identity && identity.capabilities;
  const isOwner = identity && identity.role === 'owner';
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
    <div className="settings-body">
      <SectionHead title="Organization" sub={isOwner
        ? 'Tier and org name — enforced server-side.'
        : 'Read-only: changing the tier requires the owner role.'} />
      <Card title="Account & tier">
        <p className="muted">The tier gates real capabilities on the worker. Solo is the free default; other tiers model what a paid plan unlocks.</p>
        <div className="tier-buttons">
          {['solo', 'team', 'enterprise', 'government', 'developer'].map(t => (
            <button key={t} className={`chip ${((tier && tier.tier) || (caps && caps.tier)) === t ? 'on' : ''}`}
                    onClick={() => switchTier(t)} disabled={!isOwner}>{t}</button>
          ))}
        </div>
        <div className="field">
          <input placeholder="Organization name (optional)" value={name} onChange={e => setName(e.target.value)} disabled={!isOwner} />
        </div>
        {result && <div className="muted">{result}</div>}
      </Card>
      <OrgProfileCard isOwner={isOwner} />
      <div className="grid2">
        <Gate capability="retention_admin" caps={caps}>
          <Card title="Data & privacy (retention admin)">
            <Row><div>Observations: 30 days default</div></Row>
            <Row><div>Reports &amp; history: 90 days default</div></Row>
            <Row><button className="link" onClick={() => setPage('privacy')}>Open Data &amp; Privacy →</button></Row>
          </Card>
        </Gate>
        <Gate capability="sso" caps={caps}>
          <Card title="Single sign-on">
            <SSOStatus />
          </Card>
        </Gate>
      </div>
      <Card title="Members, roles & invitations">
        {identity && identity.role === 'owner'
          ? <Row><button className="link" onClick={() => setPage('teams')}>Open Members &amp; organization →</button></Row>
          : <Row><div className="muted">Member management requires the owner role.</div></Row>}
      </Card>
    </div>
  );
}

function SSOStatus() {
  const [status, setStatus] = useState(null);
  useState(() => { api.ssoStatus().then(setStatus).catch(() => setStatus({ enabled: false })); });
  return <Row><div>{status ? (status.enabled ? `Enabled — ${status.provider}` : 'Not enabled on this tier') : '…'}</div></Row>;
}

export function Settings({ identity, onExit, setPage }) {
  // Section state lives in the hash (#/settings/security) so refresh and
  // back/forward keep the current section — same contract as the app router.
  const sectionForHash = () => {
    const h = (window.location.hash || '').replace(/^#/, '');
    const m = h.match(/^settings\/([a-z]+)/);
    return (m && SECTIONS.some(s => s.id === m[1])) ? m[1] : 'general';
  };
  const [section, setSectionState] = useState(sectionForHash);
  useEffect(() => {
    const onHash = () => setSectionState(sectionForHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const setSection = (id) => {
    const next = `settings/${id}`;
    if (window.location.hash !== `#${next}`) window.location.hash = next;
    else setSectionState(id);
  };

  // Role-aware IA: the Organization section is owner-only, mirroring the
  // backend's admin_guard on /org/tier, /team/* and /runners (UI hides it;
  // the backend still enforces everything).
  const visibleSections = SECTIONS.filter(s => !s.owner || (identity && identity.role === 'owner'));
  const active = visibleSections.some(s => s.id === section) ? section : 'general';

  return (
    <div className="settings-wrap">
      <div className="settings-back-row">
        <button className="link" onClick={onExit}>← Back to application</button>
      </div>
      <SettingsNav sections={visibleSections} active={active} onNavigate={setSection} />
      <Reveal key={active} className="settings-content" y={10} blur={false}>
        {active === 'general' && <GeneralSection />}
        {active === 'profile' && <ProfileSection identity={identity} />}
        {active === 'appearance' && <AppearanceSection />}
        {active === 'security' && <SecuritySection identity={identity} />}
        {active === 'organization' && <OrganizationSection identity={identity} setPage={setPage} />}
      </Reveal>
    </div>
  );
}
