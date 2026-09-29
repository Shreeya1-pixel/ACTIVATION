// Floating navigation system (contract: sidebar → floating nav).
// Desktop: a fixed, floating pill nav with contextual dropdown panels
// (21st.dev Floating Nav / Navbar Menu / Mega Menu references), an account
// menu, a notifications panel and a ⌘K command palette.
// Mobile: the same object becomes a compact top bar whose menu opens a
// grouped sheet — never the desktop nav squeezed into the viewport.
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Icon, ICONS } from './main-shared.jsx';
import { ThemeLogo } from './brand.jsx';
import { ThemeSwitcher } from './premium.jsx';
import { spring, dur, LEVEL } from './motion.js';

// ── Navigation model: groups map to REAL routes only. ────────────────────────
export const NAV_GROUPS = [
  {
    id: 'product', label: 'Product',
    items: [
      { id: 'dashboard', label: 'Dashboard', desc: 'Live operations overview', icon: ICONS.grid },
      { id: 'workflows', label: 'Workflows', desc: 'Manage automations & runs', icon: ICONS.flow },
      { id: 'practice', label: 'Try it live', desc: 'Your own edits, end to end', icon: ICONS.eye },
      { id: 'discovery', label: 'Discovery', desc: 'Evidence-based candidates', icon: ICONS.zap },
      { id: 'create', label: 'Create', desc: 'Guided automation builder', icon: ICONS.plus },
    ],
  },
  {
    id: 'operate', label: 'Operate',
    items: [
      { id: 'scheduling', label: 'Scheduling', desc: 'Evidence-gated triggers', icon: ICONS.clock },
      { id: 'runners', label: 'Runners', desc: 'Local & paired executors', icon: ICONS.cpu },
      { id: 'connectors', label: 'Connectors', desc: 'Measured integration status', icon: ICONS.package },
    ],
  },
  {
    id: 'trust', label: 'Trust',
    items: [
      { id: 'registry', label: 'Registry', desc: 'Publish & import schemas', icon: ICONS.db },
      { id: 'trustlog', label: 'Trust Log', desc: 'Hash-chained audit trail', icon: ICONS.shield },
      { id: 'privacy', label: 'Data & Privacy', desc: 'Retention & consent ledger', icon: ICONS.lock },
    ],
  },
];

function useClickOutside(open, onClose, ref) {
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open, onClose, ref]);
}

// ── Contextual dropdown panel (anchored to its trigger) ──────────────────────
function DropdownPanel({ group, onNavigate, close }) {
  return (
    <motion.div
      className={`nav-panel glass glass-strong nav-panel-${group.items.length}`}
      initial={{ opacity: 0, scale: 0.97, y: -6 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98, y: -4 }}
      transition={spring.gentle}
      role="menu"
      aria-label={`${group.label} pages`}
    >
      {group.items.map((item, i) => (
        <motion.button
          key={item.id}
          className="nav-panel-item"
          role="menuitem"
          initial={LEVEL.cinematic ? { opacity: 0, y: 4 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: dur(180), delay: 0.03 + i * 0.025 }}
          onClick={() => { close(); onNavigate(item.id); }}
        >
          <span className="npi-icon"><Icon d={item.icon} size={17} /></span>
          <span className="npi-copy">
            <span className="npi-label">{item.label}</span>
            <span className="npi-desc">{item.desc}</span>
          </span>
        </motion.button>
      ))}
    </motion.div>
  );
}

// ── Account dropdown ─────────────────────────────────────────────────────────
export function AccountMenu({ identity, isOwner, onNavigate, onSignOut, compact = false }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useClickOutside(open, () => setOpen(false), ref);
  const close = () => setOpen(false);
  const user = identity && identity.user;
  const role = identity && identity.role;
  const item = (label, icon, fn, danger = false) => (
    <button className={`account-item ${danger ? 'danger' : ''}`} onClick={() => { close(); fn(); }}>
      <Icon d={icon} size={16} /> {label}
    </button>
  );
  return (
    <div className={`account-pop nav-account ${compact ? 'compact' : ''}`} ref={ref}>
      <button
        type="button" className="account-btn nav-account-trigger"
        aria-expanded={open} aria-haspopup="menu"
        onClick={() => setOpen(o => !o)}
      >
        <span className="avatar">{user ? user.username.slice(0, 2).toUpperCase() : 'SV'}</span>
        {!compact && user && (
          <span className="account-user-meta">
            <span className="user-name">{user.display_name || user.username}</span>
            <span className="user-role">{role} · {identity.capabilities.tier}</span>
          </span>
        )}
        <Icon d={ICONS.chevron} size={13} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            className="glass glass-strong account-menu nav-account-panel"
            initial={{ opacity: 0, scale: 0.96, y: -6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -4 }}
            transition={spring.gentle}
            role="menu"
          >
            <div className="account-menu-head">
              <span className="user-name">{user ? (user.display_name || user.username) : 'Service token'}</span>
              <span className="user-role">{user ? `@${user.username} · ${role} · ${identity.capabilities.tier} tier` : 'legacy mode'}</span>
            </div>
            {item('Account & tokens', ICONS.user, () => onNavigate('profile'))}
            {isOwner && item('Members & organization', ICONS.users, () => onNavigate('teams'))}
            {item('Settings', ICONS.cog, () => onNavigate('settings'))}
            <div className="account-menu-sep" />
            <div className="account-theme"><span>Appearance</span><ThemeSwitcher compact /></div>
            <div className="account-menu-sep" />
            {item('Sign out', ICONS.logout, onSignOut, true)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Notifications panel (real data only) ─────────────────────────────────────
export function NotificationsMenu({ live, onNavigate }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useClickOutside(open, () => setOpen(false), ref);
  const notes = (live && live.notifications) || [];
  const unread = notes.filter(n => !n.read_at).length;
  const close = () => setOpen(false);
  return (
    <div className="nav-bell" ref={ref}>
      <button
        className="nav-icon-btn" aria-label={`Notifications${unread ? ` (${unread} unread)` : ''}`}
        aria-expanded={open} aria-haspopup="menu"
        onClick={() => setOpen(o => !o)}
      >
        <Icon d={ICONS.bell} size={17} />
        {unread > 0 && <span className="nav-badge">{unread > 9 ? '9+' : unread}</span>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            className="glass glass-strong notif-panel"
            initial={{ opacity: 0, scale: 0.96, y: -6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -4 }}
            transition={spring.gentle}
            role="menu"
          >
            <div className="notif-head">
              <strong>Notifications</strong>
              {unread > 0 && <span className="badge blue">{unread} unread</span>}
            </div>
            {notes.length === 0 && (
              <div className="notif-empty">No notifications yet.</div>
            )}
            {notes.slice(0, 5).map(n => (
              <button
                key={n.id}
                className={`notif-row ${n.read_at ? 'read' : 'unread'}`}
                onClick={() => { close(); onNavigate('notifications'); }}
              >
                <span className="notif-dot" aria-hidden="true" />
                <span className="notif-copy">
                  <span className="notif-title">{n.title}</span>
                  <span className="notif-time">{String(n.created_at || '').slice(0, 16).replace('T', ' ')}</span>
                </span>
              </button>
            ))}
            <button className="notif-all link" onClick={() => { close(); onNavigate('notifications'); }}>
              View all notifications →
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Command palette (⌘K): real pages + real actions only ────────────────────
export function CommandPalette({ open, setOpen, onNavigate, isOwner, onSignOut, workerUp }) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);
  const actions = React.useMemo(() => {
    const list = [];
    NAV_GROUPS.forEach(g => g.items.forEach(it => list.push({ kind: 'Page', label: it.label, desc: it.desc, icon: it.icon, run: () => onNavigate(it.id) })));
    list.push({ kind: 'Page', label: 'Notifications', desc: 'In-app feed', icon: ICONS.bell, run: () => onNavigate('notifications') });
    list.push({ kind: 'Page', label: 'Profile', desc: 'Account & API tokens', icon: ICONS.user, run: () => onNavigate('profile') });
    list.push({ kind: 'Page', label: 'Settings', desc: 'Application settings', icon: ICONS.cog, run: () => onNavigate('settings') });
    if (isOwner) list.push({ kind: 'Page', label: 'Members', desc: 'People, roles & invitations', icon: ICONS.users, run: () => onNavigate('teams') });
    list.push({ kind: 'Action', label: 'Sign out', desc: 'End this session', icon: ICONS.logout, run: onSignOut });
    return list;
  }, [isOwner, onNavigate, onSignOut]);
  const filtered = actions.filter(a => a.label.toLowerCase().includes(query.toLowerCase()) || a.desc.toLowerCase().includes(query.toLowerCase()));

  useEffect(() => {
    if (open) { setQuery(''); setCursor(0); setTimeout(() => inputRef.current && inputRef.current.focus(), 40); }
  }, [open]);
  useEffect(() => { if (open) setCursor(0); }, [query, open]);

  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(c + 1, filtered.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)); }
    else if (e.key === 'Enter' && filtered[cursor]) { setOpen(false); filtered[cursor].run(); }
    else if (e.key === 'Escape') setOpen(false);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="cmdk-backdrop"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: dur(150) }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
        >
          <motion.div
            className="glass glass-strong cmdk"
            role="dialog" aria-label="Command palette"
            initial={{ opacity: 0, scale: 0.97, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: -8 }}
            transition={spring.gentle}
          >
            <div className="cmdk-input-row">
              <Icon d={ICONS.search} size={16} />
              <input
                ref={inputRef} value={query} placeholder="Search pages and actions…"
                onChange={e => setQuery(e.target.value)} onKeyDown={onKey}
                aria-label="Search pages and actions"
              />
              <span className="cmdk-esc">esc</span>
            </div>
            <div className="cmdk-list">
              {filtered.length === 0 && <div className="cmdk-empty">No matches for “{query}”.</div>}
              {filtered.map((a, i) => (
                <button
                  key={`${a.kind}-${a.label}`}
                  className={`cmdk-item ${i === cursor ? 'cursor' : ''}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => { setOpen(false); a.run(); }}
                >
                  <span className="npi-icon"><Icon d={a.icon} size={16} /></span>
                  <span className="npi-copy">
                    <span className="npi-label">{a.label}</span>
                    <span className="npi-desc">{a.desc}</span>
                  </span>
                  <span className="cmdk-kind">{a.kind}</span>
                </button>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ── Mobile sheet (grouped accordion navigation) ──────────────────────────────
function MobileSheet({ open, setOpen, identity, isOwner, onNavigate, onSignOut, workerUp }) {
  const [expanded, setExpanded] = useState('product');
  const panelRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    // rudimentary focus trap: keep Tab within the sheet
    const onTab = (e) => {
      if (e.key !== 'Tab' || !panelRef.current) return;
      const focusables = panelRef.current.querySelectorAll('button, [href], input');
      if (!focusables.length) return;
      const first = focusables[0]; const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onTab);
    setTimeout(() => panelRef.current && panelRef.current.querySelector('button') && panelRef.current.querySelector('button').focus(), 60);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('keydown', onTab); };
  }, [open, setOpen]);

  const Group = ({ group }) => (
    <div className="sheet-group">
      <button
        className={`sheet-group-head ${expanded === group.id ? 'on' : ''}`}
        aria-expanded={expanded === group.id}
        onClick={() => setExpanded(expanded === group.id ? null : group.id)}
      >
        {group.label}
        <Icon d={ICONS.chevron} size={15} />
      </button>
      <AnimatePresence initial={false}>
        {expanded === group.id && (
          <motion.div
            className="sheet-group-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: dur(240), ease: [0.22, 1, 0.36, 1] }}
          >
            {group.items.map(it => (
              <button key={it.id} className="sheet-item" onClick={() => { setOpen(false); onNavigate(it.id); }}>
                <Icon d={it.icon} size={17} />
                <span className="npi-copy">
                  <span className="npi-label">{it.label}</span>
                  <span className="npi-desc">{it.desc}</span>
                </span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="sheet-backdrop"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: dur(180) }}
            onMouseDown={() => setOpen(false)}
            aria-hidden="true"
          />
          <motion.div
            className="glass glass-strong sheet"
            ref={panelRef}
            role="dialog" aria-label="Navigation"
            initial={{ x: '-100%' }} animate={{ x: 0 }} exit={{ x: '-100%' }}
            transition={{ type: 'spring', stiffness: 320, damping: 34 }}
          >
            <div className="sheet-head">
              <ThemeLogo lockup={false} h={32} />
              <button className="nav-icon-btn" aria-label="Close navigation" onClick={() => setOpen(false)}>
                <Icon d={ICONS.x} size={18} />
              </button>
            </div>
            <div className="sheet-scroll">
              {NAV_GROUPS.map(g => <Group key={g.id} group={g} />)}
              <div className="sheet-group">
                <button className="sheet-group-head" onClick={() => { setOpen(false); onNavigate('notifications'); }}>
                  Notifications <Icon d={ICONS.bell} size={15} />
                </button>
              </div>
              <div className="sheet-sep" />
              <div className="sheet-account">
                <span className="avatar">{identity && identity.user ? identity.user.username.slice(0, 2).toUpperCase() : 'SV'}</span>
                <span className="npi-copy">
                  <span className="npi-label">{identity && identity.user ? (identity.user.display_name || identity.user.username) : 'Service token'}</span>
                  <span className="npi-desc">{identity ? `${identity.role} · ${identity.capabilities.tier}` : ''}</span>
                </span>
              </div>
              <button className="sheet-item" onClick={() => { setOpen(false); onNavigate('profile'); }}>
                <Icon d={ICONS.user} size={17} /> <span className="npi-label">Account &amp; tokens</span>
              </button>
              {isOwner && (
                <button className="sheet-item" onClick={() => { setOpen(false); onNavigate('teams'); }}>
                  <Icon d={ICONS.users} size={17} /> <span className="npi-label">Members &amp; organization</span>
                </button>
              )}
              <button className="sheet-item" onClick={() => { setOpen(false); onNavigate('settings'); }}>
                <Icon d={ICONS.cog} size={17} /> <span className="npi-label">Settings</span>
              </button>
              <button className="sheet-item" onClick={() => { setOpen(false); onNavigate('notifications'); }}>
                <Icon d={ICONS.bell} size={17} /> <span className="npi-label">Notifications</span>
              </button>
              <div className="sheet-group">
                <div className="sheet-group-head on" style={{ cursor: 'default' }}>
                  Appearance
                </div>
                <div className="sheet-group-body" style={{ padding: '10px 14px' }}>
                  <ThemeSwitcher compact />
                </div>
              </div>
              <button className="sheet-item danger" onClick={() => { setOpen(false); onSignOut(); }}>
                <Icon d={ICONS.logout} size={17} /> <span className="npi-label">Sign out</span>
              </button>
              <div className="sheet-status">
                <span className={`pulse-dot ${workerUp ? '' : 'off'}`} />
                {workerUp ? 'Worker online' : 'Worker unreachable'}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

// ── The floating nav itself ──────────────────────────────────────────────────
export function FloatingNav({ page, setPage, identity, isOwner, live, onSignOut }) {
  const [openGroup, setOpenGroup] = useState(null);
  const [scrolled, setScrolled] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [cmdk, setCmdk] = useState(false);
  const navRef = useRef(null);

  const workerUp = !!(live && live.connected);
  const close = useCallback(() => setOpenGroup(null), []);
  useClickOutside(openGroup !== null, close, navRef);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  // ⌘K / Ctrl+K opens the palette; route change closes any open dropdown.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmdk(o => !o); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
  useEffect(() => { close(); }, [page, close]);

  const activeGroup = NAV_GROUPS.find(g => g.items.some(it => it.id === page));

  return (
    <>
      <div className={`floating-nav glass${scrolled ? ' scrolled glass-strong' : ''}`} ref={navRef}>
        <button className="nav-icon-btn nav-burger" aria-label="Open navigation" onClick={() => setSheet(true)}>
          <Icon d={ICONS.list} size={19} />
        </button>

        <button className="fn-brand" aria-label="AutoStack IN — home" title="Home" onClick={() => setPage('landing')}>
          <ThemeLogo lockup h={30} />
        </button>

        <nav className="fn-groups" aria-label="Application">
          {NAV_GROUPS.map(g => (
            <div key={g.id} className="fn-group">
              <button
                className={`fn-trigger ${openGroup === g.id ? 'open' : ''} ${activeGroup && activeGroup.id === g.id ? 'active' : ''}`}
                aria-expanded={openGroup === g.id}
                aria-haspopup="menu"
                onClick={() => setOpenGroup(openGroup === g.id ? null : g.id)}
              >
                {g.label}
                <motion.span className="fn-chevron" animate={{ rotate: openGroup === g.id ? 90 : 0 }} transition={spring.snappy}>
                  <Icon d={ICONS.chevron} size={13} />
                </motion.span>
              </button>
              <AnimatePresence>
                {openGroup === g.id && (
                  <DropdownPanel group={g} onNavigate={setPage} close={close} />
                )}
              </AnimatePresence>
            </div>
          ))}
        </nav>

        <div className="fn-right">
          <span
            className={`worker-dot ${workerUp ? 'on' : 'off'}`}
            title={workerUp ? 'Worker on :8747 — live data' : 'Worker unreachable — demo data shown'}
            aria-label={workerUp ? 'Worker online' : 'Worker offline'}
          />
          <button className="nav-icon-btn nav-search" aria-label="Search (Ctrl+K)" onClick={() => setCmdk(true)}>
            <Icon d={ICONS.search} size={16} />
            <span className="nav-kbd">⌘K</span>
          </button>
          <NotificationsMenu live={live} onNavigate={setPage} />
          <AccountMenu identity={identity} isOwner={isOwner} onNavigate={setPage} onSignOut={onSignOut} />
        </div>
      </div>

      <MobileSheet
        open={sheet} setOpen={setSheet}
        identity={identity} isOwner={isOwner}
        onNavigate={setPage} onSignOut={onSignOut}
        workerUp={workerUp}
      />
      <CommandPalette
        open={cmdk} setOpen={setCmdk}
        onNavigate={setPage} isOwner={isOwner}
        onSignOut={onSignOut} workerUp={workerUp}
      />
    </>
  );
}
