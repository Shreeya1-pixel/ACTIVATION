// Reusable premium primitives (Apple-grade materials + 21st.dev-style motion).
// Every component gates itself through motion.js LEVEL — reduced-motion and
// touch devices automatically get the calm variant. Pointer effects are
// CSS-first where possible so they cost nothing when unused.
import React, { useRef, useEffect, useState } from 'react';
import { motion, AnimatePresence, useScroll, useTransform, useSpring, useMotionValue } from 'motion/react';
import { LEVEL, spring, ease, dur } from './motion.js';
import { getTheme, setTheme } from './theme.js';

// ─── GlassSurface ─────────────────────────────────────────────────────────────
// Adaptive translucent material (navbar, sidebar, menus, toolbars). The actual
// material (blur/saturation/border/highlight) lives in CSS classes .glass /
// .glass-strong so themes stay the source of truth.
export function GlassSurface({ as: Tag = 'div', strong = false, className = '', children, ...rest }) {
  return (
    <Tag className={`glass${strong ? ' glass-strong' : ''} ${className}`.trim()} {...rest}>
      {children}
    </Tag>
  );
}

// ─── Reveal ───────────────────────────────────────────────────────────────────
// Viewport-entry reveal: fade + rise + blur-to-sharp. Stagger via `delay`.
// Order matters: headline → support → CTA → visual (timing hierarchy).
export function Reveal({ children, delay = 0, y = 18, blur = true, className = '', once = true, as = 'div' }) {
  const Tag = motion[as] || motion.div;
  if (!LEVEL.cinematic) {
    // L1 subtle: simple fade, no transform/blur.
    return (
      <Tag className={className}
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: dur(420), delay }}>
        {children}
      </Tag>
    );
  }
  return (
    <Tag
      className={className}
      initial={{ opacity: 0, y, filter: 'blur(6px)' }}
      whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      viewport={{ once, margin: '0px 0px -10% 0px' }}
      transition={{ duration: dur(640), delay, ease: ease.out }}
    >
      {children}
    </Tag>
  );
}

// ─── StaggerReveal ────────────────────────────────────────────────────────────
export function StaggerReveal({ children, step = 0.07, className = '' }) {
  const arr = React.Children.toArray(children);
  return (
    <div className={className}>
      {arr.map((child, i) => (
        <Reveal key={child.key || i} delay={i * step}>{child}</Reveal>
      ))}
    </div>
  );
}

// ─── ParallaxSection ──────────────────────────────────────────────────────────
// Layered parallax at three rates. Layers receive different transform scales;
// background slowest, foreground minimal — depth without disorientation.
export function ParallaxSection({ background, mid, children, className = '' }) {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'end start'] });
  const pBg = useTransform(scrollYProgress, [0, 1], [0, -60]);
  const pMid = useTransform(scrollYProgress, [0, 1], [0, -24]);
  const pFg = useTransform(scrollYProgress, [0, 1], [0, 10]);
  return (
    <section ref={ref} className={`parallax ${className}`.trim()}>
      {background && <motion.div className="parallax-layer parallax-bg" style={{ y: LEVEL.cinematic ? pBg : 0 }}>{background}</motion.div>}
      {mid && <motion.div className="parallax-layer parallax-mid" style={{ y: LEVEL.cinematic ? pMid : 0 }}>{mid}</motion.div>}
      <motion.div className="parallax-layer parallax-fg" style={{ y: LEVEL.cinematic ? pFg : 0 }}>{children}</motion.div>
    </section>
  );
}

// ─── MagneticButton ───────────────────────────────────────────────────────────
// Primary CTA: subtle magnetic pull (≤6px) + press spring. Disabled on touch
// and reduced motion. Never blocks click semantics.
export function MagneticButton({ children, className = '', onClick, type = 'button', disabled, title, style }) {
  const ref = useRef(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 260, damping: 22 });
  const sy = useSpring(y, { stiffness: 260, damping: 22 });
  const active = LEVEL.cinematic;
  const onMove = (e) => {
    if (!active || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const dx = e.clientX - (r.left + r.width / 2);
    const dy = e.clientY - (r.top + r.height / 2);
    x.set(Math.max(-6, Math.min(6, dx * 0.12)));
    y.set(Math.max(-4, Math.min(4, dy * 0.12)));
  };
  const onLeave = () => { x.set(0); y.set(0); };
  return (
    <motion.button
      ref={ref} type={type} title={title} disabled={disabled} className={className}
      style={{ x: active ? sx : 0, y: active ? sy : 0, ...style }}
      onMouseMove={onMove} onMouseLeave={onLeave}
      whileTap={active ? { scale: 0.97 } : undefined}
      transition={spring.snappy}
      onClick={onClick}
    >
      {children}
    </motion.button>
  );
}

// ─── Spotlight / TiltCard ─────────────────────────────────────────────────────
// PremiumCard with cursor-aware highlight + sub-1° tilt. The highlight is one
// absolutely-positioned radial layer following the pointer (CSS var driven).
export function PremiumCard({ children, className = '', tilt = true, onClick, style, revealDelay }) {
  const ref = useRef(null);
  const rx = useMotionValue(0);
  const ry = useMotionValue(0);
  const srx = useSpring(rx, { stiffness: 200, damping: 24 });
  const sry = useSpring(ry, { stiffness: 200, damping: 24 });
  const active = LEVEL.cinematic && tilt;
  // Optional in-card reveal: bento cards are grid items, so the reveal must
  // live ON the card (a wrapper div would break grid placement).
  const revealProps = revealDelay === undefined ? {} : (LEVEL.cinematic
    ? { initial: { opacity: 0, y: 18, filter: 'blur(6px)' },
        whileInView: { opacity: 1, y: 0, filter: 'blur(0px)' },
        viewport: { once: true, margin: '0px 0px -10% 0px' },
        transition: { duration: dur(640), delay: revealDelay, ease: ease.out } }
    : { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: dur(420), delay: revealDelay } });
  const onMove = (e) => {
    if (!active || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    ref.current.style.setProperty('--mx', `${(px * 100).toFixed(2)}%`);
    ref.current.style.setProperty('--my', `${(py * 100).toFixed(2)}%`);
    ry.set((px - 0.5) * 1.2);   // ≤0.6° each way — imperceptible until felt
    rx.set((0.5 - py) * 1.2);
  };
  const onLeave = () => {
    if (!ref.current) return;
    ref.current.style.setProperty('--mx', '50%');
    ref.current.style.setProperty('--my', '50%');
    rx.set(0); ry.set(0);
  };
  return (
    <motion.div
      ref={ref} className={`pcard ${className}`.trim()}
      style={{ rotateX: active ? srx : 0, rotateY: active ? sry : 0, ...style }}
      onMouseMove={onMove} onMouseLeave={onLeave} onClick={onClick}
      {...revealProps}
    >
      {children}
    </motion.div>
  );
}

// ─── AmbientBackground ────────────────────────────────────────────────────────
// Hero atmosphere: two slow drifting light fields + a fine dot grid. Pure CSS
// animation (no JS loop). Reduced-motion → static gradient, nothing moves.
export function AmbientBackground() {
  return (
    <div className="ambient" aria-hidden="true">
      <div className="ambient-field ambient-a" />
      <div className="ambient-field ambient-b" />
      <div className="ambient-dots" />
      <div className="ambient-vignette" />
    </div>
  );
}

// ─── BentoGrid / BentoCard ────────────────────────────────────────────────────
export function BentoGrid({ children, className = '' }) {
  return <div className={`bento ${className}`.trim()}>{children}</div>;
}

export function BentoCard({ wide = false, tall = false, full = false, className = '', revealDelay, children, ...rest }) {
  return (
    <PremiumCard
      revealDelay={revealDelay}
      className={`bento-card ${wide ? 'bento-wide' : ''} ${tall ? 'bento-tall' : ''} ${full ? 'bento-full' : ''} ${className}`.trim()}
      {...rest}
    >
      {children}
    </PremiumCard>
  );
}

// ─── PageTransition ───────────────────────────────────────────────────────────
// App screens: quick fade + 8px rise. Kept subtle so dense screens feel stable.
export function PageTransition({ pageKey, children }) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={pageKey}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: dur(220), ease: ease.out }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// ─── AnimatedChevron ──────────────────────────────────────────────────────────
export function AnimatedChevron({ open = false, size = 16 }) {
  return (
    <motion.span
      className="a-chevron"
      animate={{ rotate: open ? 90 : 0 }}
      transition={spring.snappy}
      style={{ display: 'inline-flex' }}
    >
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6" /></svg>
    </motion.span>
  );
}

// ─── ScrollText (21st.dev “Text Scroll” reference, reuno-ui) ─────────────────
// Word-by-word headline reveal on viewport entry. Use ONLY for hero-adjacent
// or section headlines — never body copy. Reduced-motion → simple fade.
export function ScrollText({ text, className = '', delay = 0 }) {
  const words = String(text).split(' ').filter(Boolean);
  return (
    <motion.span className={`scroll-text ${className}`.trim()} aria-label={text}>
      {words.map((w, i) => (
        <motion.span
          key={`${w}-${i}`} aria-hidden="true" className="st-word"
          initial={LEVEL.cinematic ? { opacity: 0, y: '0.55em', filter: 'blur(5px)' } : false}
          whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          viewport={{ once: true, margin: '0px 0px -12% 0px' }}
          transition={{ duration: dur(560), delay: delay + i * 0.05, ease: ease.out }}
        >
          {w}
        </motion.span>
      ))}
    </motion.span>
  );
}

// ─── ContainerScroll (21st.dev “Container Scroll Animation”, Manu Arora) ─────
// Sticky viewport section: the framed product surface starts tilted (rotateX)
// and flattens to face the reader as the section scrolls through. The frame
// carries a title bar so it reads as a product window, not a screenshot.
export function ContainerScroll({ titleComponent, children, rotate = 14 }) {
  const ref = useRef(null);
  const [desktop, setDesktop] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 861px)');
    const update = () => setDesktop(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'start start'] });
  const rot = useTransform(scrollYProgress, [0, 1], [desktop ? rotate : 0, 0]);
  const scale = useTransform(scrollYProgress, [0, 1], [desktop ? 0.96 : 1, 1]);
  return (
    <section ref={ref} className="container-scroll">
      {titleComponent}
      <motion.div
        className="cs-frame-wrap"
        style={LEVEL.cinematic && desktop ? { rotateX: rot, scale, perspective: 1200 } : {}}
      >
        <div className="cs-frame glass glass-strong">
          <div className="cs-titlebar" aria-hidden="true">
            <span /><span /><span />
            <span className="cs-tb-label">autostack · governed run</span>
          </div>
          {children}
        </div>
      </motion.div>
    </section>
  );
}

// ─── SpringPopover (morph: trigger → panel) ───────────────────────────────────
// Outside-click + Escape close built in. `children` may be a render prop
// receiving { close } so menu items can dismiss the panel after acting.
export function SpringPopover({ label, children, align = 'right', className = '' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);
  const close = () => setOpen(false);
  return (
    <div className={`popover-anchor ${className}`.trim()} ref={ref}>
      <button type="button" className="popover-trigger" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(o => !o)}>
        {label}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            className={`glass glass-strong popover-panel align-${align}`}
            initial={{ opacity: 0, scale: 0.96, y: -6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -4 }}
            transition={spring.gentle}
            role="menu"
          >
            {typeof children === 'function' ? children({ close }) : children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── ThemeSwitcher (segmented light/dark/system; data-theme source of truth) ──
export function ThemeSwitcher({ compact = false }) {
  const [theme, setThemeState] = useState(getTheme());
  const options = [
    { id: 'light', label: 'Light' },
    { id: 'dark', label: 'Dark' },
    { id: 'system', label: 'System' },
  ];
  return (
    <div className="theme-switch" role="group" aria-label="Color theme">
      {options.map(o => (
        <button
          key={o.id}
          className={`theme-opt ${theme === o.id ? 'on' : ''}`}
          aria-pressed={theme === o.id}
          title={`${o.label} theme`}
          onClick={() => { setTheme(o.id); setThemeState(o.id); }}
        >{compact ? o.label[0].toUpperCase() + o.label.slice(1, 2) : o.label}</button>
      ))}
    </div>
  );
}
