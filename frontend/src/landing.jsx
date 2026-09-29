// Cinematic landing + auth presentation.
// Composition order everywhere: brand → nav → page identity → primary message
// → primary interaction → supporting info → secondary actions.
// All motion gates through motion.js LEVEL; all materials through styles-premium.
import React, { useEffect, useRef, useState } from 'react';
import { motion, useScroll, useTransform } from 'motion/react';
import { Icon, ICONS, Terminal } from './main-shared.jsx';
import { ThemeLogo } from './brand.jsx';
import { LEVEL, spring, ease, dur } from './motion.js';
import {
  AmbientBackground, BentoCard, BentoGrid, ContainerScroll, MagneticButton, ParallaxSection,
  PremiumCard, Reveal, ScrollText, StaggerReveal,
} from './premium.jsx';

const NAV_LINKS = [
  { id: 'capabilities', label: 'Capabilities' },
  { id: 'how', label: 'How it works' },
  { id: 'trust', label: 'Trust' },
];

function scrollToId(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: LEVEL.cinematic ? 'smooth' : 'auto', block: 'start' });
}

// Animated Navigation Tabs (21st.dev “Animated Navigation Tabs”, LN): a
// spring-driven pill slides under the active link instead of a hard swap.
function AnimatedTabs() {
  const [active, setActive] = useState(null);
  const refs = useRef({});
  const [pill, setPill] = useState(null);
  const measure = (id) => {
    const el = refs.current[id];
    if (!el) return;
    setPill({ left: el.offsetLeft, width: el.offsetWidth });
  };
  useEffect(() => {
    if (active) measure(active);
    else setPill(null);
  }, [active]);
  return (
    <span className="ln-links" onMouseLeave={() => setActive(null)}>
      {pill && (
        <motion.span
          className="ln-pill" aria-hidden="true"
          initial={{ opacity: 0 }} animate={{ opacity: 1, left: pill.left, width: pill.width }}
          transition={spring.gentle}
        />
      )}
      {NAV_LINKS.map(l => (
        <button
          key={l.id} ref={el => { refs.current[l.id] = el; }}
          className={`ln-link ${active === l.id ? 'on' : ''}`}
          onFocus={() => setActive(l.id)} onMouseEnter={() => setActive(l.id)}
          onClick={() => scrollToId(l.id)}
        >
          {l.label}
        </button>
      ))}
    </span>
  );
}

function LandingNav({ scrolled, onSignIn, onSignUp, onHome }) {
  return (
    <motion.nav
      className={`landing-nav glass${scrolled ? ' glass-strong scrolled' : ''}`}
      initial={{ y: -24, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ ...spring.gentle, delay: dur(150) }}
    >
      <button className="ln-brand" aria-label="AutoStack IN — home" title="Home"
              onClick={onHome || (() => scrollToId('top'))}>
        <ThemeLogo lockup={false} h={36} />
      </button>
      <AnimatedTabs />
      <span style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
        <button className="ln-link" onClick={onSignIn}>Sign in</button>
        <MagneticButton className="btn-hero" style={{ padding: '8px 18px', fontSize: 13.5 }} onClick={onSignUp}>
          Get started
        </MagneticButton>
      </span>
    </motion.nav>
  );
}

function Hero({ onGetStarted, onSignIn, workerUp }) {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] });
  const yCopy = useTransform(scrollYProgress, [0, 1], [0, -70]);
  const yBg = useTransform(scrollYProgress, [0, 1], [0, -190]);
  const opacity = useTransform(scrollYProgress, [0, 0.75], [1, 0]);
  const blur = useTransform(scrollYProgress, [0, 0.8], ['blur(0px)', 'blur(5px)']);
  const scaleStrip = useTransform(scrollYProgress, [0, 0.9], [1, 0.94]);

  const lift = LEVEL.cinematic ? { y: yCopy, opacity, filter: blur } : {};
  const bgLift = LEVEL.cinematic ? { y: yBg } : {};
  return (
    <header className="hero" ref={ref} style={{ perspective: '1200px' }}>
      <motion.div className="ambient" style={bgLift}>
        <AmbientBackground />
      </motion.div>
      <motion.div className="hero-inner" style={{ ...lift, position: 'relative', zIndex: 2 }}>
        <Reveal><span className="hero-eyebrow"><span className="pulse-dot" />{workerUp ? 'Local worker connected' : 'Runs locally on your machine'}</span></Reveal>
        <Reveal delay={0.08}>
          <h1 className="hero-title">
            <ScrollText text="Automation that earns" />{' '}
            <span className="grad">trust</span>.
          </h1>
        </Reveal>
        <Reveal delay={0.16}>
          <p className="hero-sub">
            AutoStack watches repeated desk work, drafts an automation, proves it in a sandbox,
            and activates it only after a human approves — with a hash-chained audit trail.
          </p>
        </Reveal>
        <Reveal delay={0.24}>
          <div className="hero-ctas">
            <MagneticButton className="btn-hero" onClick={onGetStarted}>
              Create your first automation <Icon d={ICONS.arrow} size={16} />
            </MagneticButton>
            <button className="btn-ghost" onClick={onSignIn}>Sign in</button>
          </div>
        </Reveal>
        <Reveal delay={0.34}>
          <motion.div className="hero-strip" style={LEVEL.cinematic ? { scale: scaleStrip } : undefined}>
            <div className="glass exec-band" style={{ marginTop: 0 }}>
              <div className="exec-copy">
                <h3>Observe. Draft. Prove. Approve.</h3>
                <p>Every automation passes a twelve-check sandbox — schema binding, secret scans,
                   drift injection, idempotency — before it can touch your files.</p>
                <div className="exec-states">
                  <span className="exec-state"><span className="st-dot pass" />Sandbox gate passed</span>
                  <span className="exec-state"><span className="st-dot run" />Human approval required</span>
                  <span className="exec-state"><span className="st-dot idle" />Activation pending</span>
                </div>
              </div>
              <div className="exec-term"><Terminal title="governance" lines={HERO_TERM} running /></div>
            </div>
          </motion.div>
        </Reveal>
      </motion.div>
    </header>
  );
}

const HERO_TERM = [
  { kind: 'cmd', text: '$ autostack sandbox run --job tds-filing-v3' },
  { kind: 'ok', text: 'PASS  secret_scan        0 secrets  0 high-severity' },
  { kind: 'ok', text: 'PASS  schema_bind        4/4 columns resolved' },
  { kind: 'warn', text: 'INJECT  header drift     col TRN -> TAX_REG_NO' },
  { kind: 'ok', text: 'PASS  drift guard caught mutation  rollback=ok' },
  { kind: 'info', text: 'gate    awaiting human approval  ed25519 sig' },
];

// Product-reveal content: the same twelve-check sequence the real sandbox
// runs (condensed for the frame) — no invented features.
const RUN_TERM = [
  { kind: 'cmd', text: '$ autostack sandbox run --job tds-filing-v3 --isolate docker' },
  { kind: 'ok', text: 'PASS  ast_compile  secret_scan  schema_bind  golden_path' },
  { kind: 'warn', text: 'INJECT  header drift  col "TRN" -> "TAX_REG_NO"  (deliberate)' },
  { kind: 'ok', text: 'PASS  drift guard caught mutation  delivery BLOCKED  rollback=ok' },
  { kind: 'ok', text: 'PASS  idempotent re-run  PII redaction  timeout bounds' },
  { kind: 'ok', text: 'PASS  audit hash-chain  rollback hook  permission scope' },
  { kind: 'info', text: '────────  12 passed  1 injected-fail caught  0 delivered-on-fail  ────────' },
  { kind: 'cmd', text: 'gate    GATE HELD  awaiting human approval  (approver role)' },
];

// Scroll media expansion hero (21st.dev reference, Arunachalam) + Container
// Scroll Animation (Manu Arora): the hero hands off to a product window that
// starts tilted in perspective and flattens as the reader scrolls — a real
// scroll-linked transition instead of a hard section swap.
function ProductReveal() {
  return (
    <ContainerScroll
      titleComponent={
        <Reveal className="chapter-head cs-head">
          <div className="chapter-kicker">The product</div>
          <h2>A governed run, end to end.</h2>
          <p className="chapter-sub">The same terminal your operators see — sandbox checks, deliberate drift injection, and the approval gate that holds delivery until a human decides.</p>
        </Reveal>
      }
    >
      <Terminal title="governed run" lines={RUN_TERM} running />
    </ContainerScroll>
  );
}

function Capabilities() {
  return (
    <section className="chapter" id="capabilities">
      <Reveal><div className="chapter-head">
        <div className="chapter-kicker">Capabilities</div>
        <h2>One platform, four disciplines.</h2>
        <p className="chapter-sub">Discovery finds the work. The studio drafts it. Trust systems prove it. Teams run it.</p>
      </div></Reveal>
      <BentoGrid>
        <BentoCard wide tall revealDelay={0}>
          <div className="bento-icon"><Icon d={ICONS.eye} size={20} /></div>
          <h3>Discovery engine</h3>
          <p>Watch approved applications — browser, spreadsheet, email — and surface repeated
             procedures with exact occurrence counts. Never an invented confidence number.</p>
          <div className="bento-stat-row">
            <span className="bento-chip">evidence-first</span>
            <span className="bento-chip">consent-gated</span>
            <span className="bento-chip">PII redacted</span>
          </div>
        </BentoCard>
        <BentoCard revealDelay={0.08}>
          <div className="bento-icon"><Icon d={ICONS.zap} size={20} /></div>
          <h3>Automation studio</h3>
          <p>Turn a detected pattern into a reviewable plan, then a working automation.</p>
        </BentoCard>
        <BentoCard revealDelay={0.14}>
          <div className="bento-icon"><Icon d={ICONS.shield} size={20} /></div>
          <h3>Trust systems</h3>
          <p>Sandboxed tests, human approval gates, hash-chained audit.</p>
        </BentoCard>
        <BentoCard revealDelay={0.08}>
          <div className="bento-icon"><Icon d={ICONS.flow} size={20} /></div>
          <h3>Team operations</h3>
          <p>Roles for observers, operators, approvers and owners. Every action authorized.</p>
        </BentoCard>
        <BentoCard revealDelay={0.14}>
          <div className="bento-icon"><Icon d={ICONS.db} size={20} /></div>
          <h3>Private registry</h3>
          <p>Publish proven automations to your organization's registry. Imports arrive as
             untrusted drafts — approvals are never inherited.</p>
        </BentoCard>
      </BentoGrid>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    { icon: ICONS.eye, t: 'Observe', s: 'The agent records approved app usage with values redacted.' },
    { icon: ICONS.zap, t: 'Draft', s: 'Repeated sequences become a reviewable automation plan.' },
    { icon: ICONS.shield, t: 'Prove', s: 'A sandboxed replay passes twelve checks before delivery.' },
    { icon: ICONS.check, t: 'Approve', s: 'A human activates. Every decision lands in the audit chain.' },
  ];
  return (
    <section className="chapter" id="how">
      <Reveal><div className="chapter-head">
        <div className="chapter-kicker">How it works</div>
        <h2>From habit to governed automation.</h2>
      </div></Reveal>
      <ParallaxSection background={<div className="ambient-field ambient-a" style={{ opacity: 0.18, left: '30%', top: '20%' }} />}>
        <div className="pipeline">
          {steps.map((st, i) => (
            <React.Fragment key={st.t}>
              <Reveal delay={i * 0.08} className="pipe-node-wrap">
                <div className="pipe-node">
                  <div className="pipe-ic"><Icon d={st.icon} size={20} /></div>
                  <strong>{st.t}</strong>
                  <span>{st.s}</span>
                </div>
              </Reveal>
              {i < steps.length - 1 && (
                <span className="pipe-conn"><Icon d={ICONS.arrow} size={18} /></span>
              )}
            </React.Fragment>
          ))}
        </div>
      </ParallaxSection>
    </section>
  );
}

function TrustChapter() {
  const items = [
    { icon: ICONS.shield, t: 'Sandbox before delivery', s: 'Twelve checks in isolation: AST, secrets, schema, golden path, drift injection, idempotency, PII, timeouts.' },
    { icon: ICONS.user, t: 'Human approval gates', s: 'No automation runs without an explicit approve. RBAC separates who tests from who activates.' },
    { icon: ICONS.hash, t: 'Hash-chained audit', s: 'Every action appended to a tamper-evident ledger, verifiable in one click.' },
    { icon: ICONS.lock, t: 'Secrets never stored', s: 'Keys are read at request time, redacted from logs, absent from exports.' },
  ];
  return (
    <section className="chapter" id="trust">
      <Reveal><div className="chapter-head">
        <div className="chapter-kicker">Trust</div>
        <h2>Proven before it runs.</h2>
        <p className="chapter-sub">AutoStack is built for regulated back offices — the controls are the product.</p>
      </div></Reveal>
      <StaggerReveal className="trust-list">
        {items.map(it => (
          <PremiumCard key={it.t} className="trust-item">
            <span className="ti-ic"><Icon d={it.icon} size={17} /></span>
            <span><strong>{it.t}</strong><span>{it.s}</span></span>
          </PremiumCard>
        ))}
      </StaggerReveal>
    </section>
  );
}

function FinalCTA({ onGetStarted }) {
  return (
    <section className="final-cta">
      <AmbientBackground />
      <Reveal><h2>Give your team automation they can <span className="grad">sign off on</span>.</h2></Reveal>
      <Reveal delay={0.1}><p>Runs entirely on your machine or your office runner. Your data never leaves the building.</p></Reveal>
      <Reveal delay={0.18}>
        <div className="hero-ctas">
          <MagneticButton className="btn-hero" onClick={onGetStarted}>
            Get started <Icon d={ICONS.arrow} size={16} />
          </MagneticButton>
        </div>
      </Reveal>
    </section>
  );
}

export function Landing({ onSignUp, onSignIn, workerUp }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const signup = () => onSignUp();
  const signin = () => onSignIn();
  const goHome = () => { window.scrollTo({ top: 0, behavior: LEVEL.cinematic ? 'smooth' : 'auto' }); };
  return (
    <div className="landing" id="top">
      <LandingNav scrolled={scrolled} onSignIn={signin} onSignUp={signup} onHome={goHome} />
      <Hero onGetStarted={signup} onSignIn={signin} workerUp={workerUp} />
      <ProductReveal />
      <Capabilities />
      <HowItWorks />
      <TrustChapter />
      <FinalCTA onGetStarted={signup} />
      <footer className="landing-footer">
        <div className="lf-copy"><strong>AutoStack IN</strong> — local-first automation for small back offices. Sandbox, approval, audit.</div>
        <div className="lf-links">
          {NAV_LINKS.map(l => <button key={l.id} onClick={() => scrollToId(l.id)}>{l.label}</button>)}
          <button onClick={onSignIn}>Sign in</button>
          <button onClick={onSignUp}>Get started</button>
        </div>
        <div className="lf-copy" style={{ gridColumn: '1 / -1' }}>Runs entirely on your machine — your data never leaves the building.</div>
</footer>
    </div>
  );
}

// ─── In-app landing homepage (#/landing) ───────────────────────────────────
// The signed-in entry surface: logo, title, tagline, and real CTAs into the
// product. Deliberately quieter than the marketing page — it orients, not sells.
export function AppHome({ setPage }) {
  const quick = [
    { id: 'workflows', label: 'Workflows', desc: 'Manage automations & runs', icon: ICONS.flow },
    { id: 'discovery', label: 'Discovery', desc: 'Evidence-based candidates', icon: ICONS.zap },
    { id: 'trustlog', label: 'Trust Log', desc: 'Hash-chained audit trail', icon: ICONS.shield },
    { id: 'settings', label: 'Settings', desc: 'Profile, appearance, security', icon: ICONS.cog },
  ];
  return (
    <div className="screen app-home">
      <div className="ah-hero">
        <Reveal><span className="ah-brand"><ThemeLogo h={64} /></span></Reveal>
        <Reveal delay={0.08}>
          <h1 className="ah-title">Automation that earns <span className="grad">trust</span>.</h1>
        </Reveal>
        <Reveal delay={0.16}>
          <p className="ah-sub">
            AutoStack watches repeated desk work, drafts an automation, proves it in a
            sandbox, and activates it only after a human approves — with a hash-chained
            audit trail. Everything runs locally.
          </p>
        </Reveal>
        <Reveal delay={0.24}>
          <div className="hero-ctas ah-ctas">
            <MagneticButton className="btn-hero" onClick={() => setPage('dashboard')}>
              Go to Dashboard <Icon d={ICONS.arrow} size={16} />
            </MagneticButton>
            <button className="btn-ghost" onClick={() => setPage('create')}>Create automation</button>
          </div>
        </Reveal>
      </div>
      <StaggerReveal className="ah-quick">
        {quick.map(q => (
          <PremiumCard key={q.id} className="ah-quick-card" onClick={() => setPage(q.id)}>
            <span className="npi-icon"><Icon d={q.icon} size={18} /></span>
            <span className="npi-copy">
              <span className="npi-label">{q.label}</span>
              <span className="npi-desc">{q.desc}</span>
            </span>
            <Icon d={ICONS.chevron} size={15} />
          </PremiumCard>
        ))}
      </StaggerReveal>
    </div>
  );
}

// ─── Auth hero (login/signup with landing context) ───────────────────────────
// Uses the SAME floating pill navbar as the marketing landing (single navbar
// design across public pages); the hero below carries the full lockup.
export function AuthScreen({ children, onSignIn, onSignUp }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return (
    <div className="landing auth-landing">
      <AmbientBackground />
      {onSignIn && onSignUp && (
        <LandingNav scrolled={scrolled} onSignIn={onSignIn} onSignUp={onSignUp}
                    onHome={() => { window.scrollTo({ top: 0, behavior: 'auto' }); }} />
      )}
      <div className="auth-hero" style={{ position: 'relative', zIndex: 2 }}>
        <Reveal className="ah-copy">
          <span className="ah-brand"><ThemeLogo h={44} /></span>
          <h1>Automation that earns <span className="grad">trust</span>.</h1>
          <p>Your account lives on this machine — the first account administers it.
             Automations run in a sandbox and activate only after human approval.</p>
          <div className="auth-points">
            <span className="ap"><Icon d={ICONS.check} size={15} /> Evidence-based discovery, never invented numbers</span>
            <span className="ap"><Icon d={ICONS.check} size={15} /> Twelve-check sandbox gate before delivery</span>
            <span className="ap"><Icon d={ICONS.check} size={15} /> Hash-chained audit of every decision</span>
          </div>
        </Reveal>
        <Reveal delay={0.12}>{children}</Reveal>
      </div>
    </div>
  );
}
