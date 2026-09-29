// ─── Effect-intensity system ─────────────────────────────────────────────────
// Central switchboard for every decorative motion decision in the app.
//   L0 static      — prefers-reduced-motion: no decorative movement at all
//   L1 subtle      — fades only (always allowed)
//   L2 interactive — hover/press/material response (desktop + touch hoverless ok)
//   L3 cinematic   — landing storytelling (desktop, motion allowed)
//   L4 showcase    — hero/parallax moments (desktop, motion allowed)
// Components read LEVEL, never device detection themselves.

const mqlReduce = window.matchMedia?.('(prefers-reduced-motion: reduce)');
const mqlTouch = window.matchMedia?.('(hover: none), (pointer: coarse)');

export const FX = {
  reduced: mqlReduce?.matches ?? false,
  touch: mqlTouch?.matches ?? false,
};

export const LEVEL = {
  subtle: true,
  interactive: !FX.reduced,
  cinematic: !FX.reduced && !FX.touch,
  showcase: !FX.reduced && !FX.touch,
};

// Publish the level so CSS can gate purely decorative pieces.
document.documentElement.dataset.fx = FX.reduced ? 'reduced' : (FX.touch ? 'touch' : 'full');

// Motion tokens (values themselves live in styles.css for CSS-side animation).
export const spring = {
  gentle: { type: 'spring', stiffness: 190, damping: 26, mass: 0.9 },
  snappy: { type: 'spring', stiffness: 340, damping: 30, mass: 0.7 },
  soft: { type: 'spring', stiffness: 120, damping: 22, mass: 1.0 },
};

export const ease = {
  out: [0.22, 1, 0.36, 1],
  inOut: [0.65, 0, 0.35, 1],
};

export const dur = (ms) => (FX.reduced ? 0 : ms / 1000);
