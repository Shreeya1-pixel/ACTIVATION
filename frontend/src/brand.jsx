// Brand identity: real logo assets (user-supplied lockups processed to
// transparent PNGs; see scripts/process_logos.py). Light theme → metallic
// lockup with dark text; dark theme → metallic lockup with white text.
// Swap happens through theme CSS ([data-theme]), so "system" mode adapts
// automatically. No filters or glows anywhere — the mark is crisp by asset.
import React from 'react';
import lockupLight from './assets/autostack-lockup-light.png';
import lockupDark from './assets/autostack-lockup-dark.png';
import markLight from './assets/autostack-mark-light.png';
import markDark from './assets/autostack-mark-dark.png';

export function ThemeLogo({ lockup = true, h = 26, title = 'AutoStack' }) {
  const light = lockup ? lockupLight : markLight;
  const dark = lockup ? lockupDark : markDark;
  return (
    <span className="theme-logo" style={{ height: h }} title={title}>
      <img className="logo-light" src={light} alt={title} />
      <img className="logo-dark" src={dark} alt="" aria-hidden="true" />
    </span>
  );
}
