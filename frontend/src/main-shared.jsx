// Shared UI atoms (Phase 10 refactor): extracted from main.jsx so additional
// screen modules can reuse the exact same visual primitives.
import React, { useEffect, useRef } from 'react';

export const Icon = ({ d, size = 18, stroke = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke={stroke} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {Array.isArray(d) ? d.map((p, i) => <path key={i} d={p} />) : <path d={d} />}
  </svg>
);

export const ICONS = {
  grid:    "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  search:  "M11 3a8 8 0 1 0 0 16A8 8 0 0 0 11 3zM21 21l-4.35-4.35",
  db:      ["M12 2C6.48 2 2 4.02 2 6.5v11C2 19.98 6.48 22 12 22s10-2.02 10-4.5v-11C22 4.02 17.52 2 12 2z", "M2 6.5C2 8.98 6.48 11 12 11s10-2.02 10-4.5", "M2 12c0 2.48 4.48 4.5 10 4.5s10-2.02 10-4.5"],
  flow:    ["M5 6a1 1 0 1 0 2 0A1 1 0 0 0 5 6zM5 18a1 1 0 1 0 2 0A1 1 0 0 0 5 18zM17 12a1 1 0 1 0 2 0A1 1 0 0 0 17 12z", "M7 6h4a4 4 0 0 1 4 4v0a4 4 0 0 0 4 4", "M7 18h4a4 4 0 0 0 4-4v0a4 4 0 0 1 4-4"],
  shield:  ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", "M9 12l2 2 4-4"],
  bell:    ["M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9", "M13.73 21a2 2 0 0 1-3.46 0"],
  check:   "M20 6L9 17l-5-5",
  x:       "M18 6L6 18M6 6l12 12",
  circle:  "M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2z",
  zap:     "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  arrow:   "M5 12h14M12 5l7 7-7 7",
  clock:   ["M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2z", "M12 6v6l4 2"],
  chart:   ["M18 20V10", "M12 20V4", "M6 20v-6"],
  user:    ["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2", "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"],
  lock:    ["M19 11H5a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2z", "M7 11V7a5 5 0 0 1 10 0v4"],
  refresh: "M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15",
  eye:     ["M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12z", "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"],
  plus:    "M12 5v14M5 12h14",
  chevron: "M9 18l6-6-6-6",
  package: ["M16.5 9.4l-9-5.18M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z", "M3.27 6.96L12 12.01l8.73-5.05", "M12 22.08V12"],
  list:    ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"],
  hash:    ["M4 9h16", "M4 15h16", "M10 3L8 21", "M16 3l-2 18"],
  users:   ["M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M23 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],
  cog:     ["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"],
  cpu:     ["M6 19v-3M10 19v-3M14 19v-3M18 19v-3M8 11V9M16 11V9M12 11V9", "M2 15h20M2 7h20M6 19h12a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2z"],
  logout:  ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "M16 17l5-5-5-5", "M21 12H9"],
};

export const StatusBadge = ({ s }) => {
  const map = {
    'Success':       'badge green',
    'Verified':      'badge green',
    'In Progress':   'badge blue',
    'Drafting':      'badge blue',
    'Failed':        'badge red',
    'Needs Review':  'badge orange',
    'Blocked':       'badge red',
    'Pass':          'badge green',
    'Flagged':       'badge orange',
    'Rolled back':   'badge gray',
  };
  return <span className={map[s] || 'badge gray'}>{s}</span>;
};

export function stamp() {
  return new Date().toLocaleTimeString('en-GB', { hour12: false });
}

export function Terminal({ title, lines, running }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);

  return (
    <div className="term">
      <div className="term-bar">
        <div className="term-dots"><i /><i /><i /></div>
        <span className="term-title">{title}</span>
        {running
          ? <span className="term-live">● LIVE</span>
          : <span className="term-idle">idle</span>}
      </div>
      <div className="term-body" ref={ref}>
        {lines.length === 0 && (
          <div className="term-line dim">waiting for process…</div>
        )}
        {lines.map((line, i) => (
          <div key={i} className={`term-line ${line.kind || ''}`}>
            {line.ts && <span className="term-ts">{line.ts}</span>}
            <span>{line.text}</span>
          </div>
        ))}
        {running && <div className="term-line cursor"><span className="blink">█</span></div>}
      </div>
    </div>
  );
}

// ── shared UI primitives (single source for all roadmap pages) ────────────────

export function Card({ title, children, actions }) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
        {actions}
      </div>
      {children}
    </div>
  );
}

export function Row({ children }) {
  return <div className="row-item">{children}</div>;
}

export function Gate({ capability, caps, children }) {
  if (!caps) return <div className="muted">Loading capabilities…</div>;
  if (caps[capability] === true || (typeof caps[capability] === 'number' && caps[capability] > 0)) {
    return children;
  }
  const need = { paired_runner: 'team', approval_policy: 'team', private_registry: 'team',
    api_access: 'enterprise', siem_export: 'enterprise', sso: 'enterprise',
    publish_national: 'developer', retention_admin: 'team' }[capability] || 'a higher tier';
  return (
    <div className="card gated">
      <h3>{capability.replace(/_/g, ' ')}</h3>
      <p className="muted">Not enabled on the <strong>{caps.tier}</strong> tier — unlocked by the <strong>{need}</strong> tier. Switch tiers in Profile → Account.</p>
    </div>
  );
}
