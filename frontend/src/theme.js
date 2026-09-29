// Theme system: light | dark | system, persisted in localStorage.
//
// data-theme="light" | "dark" is written on <html>; "system" resolves through
// the prefers-color-scheme media query and live-updates on OS changes. The
// index.html boot script applies the stored choice before first paint to avoid
// a flash of the wrong theme.

const KEY = 'autostack_theme';
export const THEMES = ['light', 'dark', 'system'];

const media = window.matchMedia?.('(prefers-color-scheme: dark)');

export function getTheme() {
  return getStoredTheme();
}

export function getStoredTheme() {
  try {
    const t = localStorage.getItem(KEY);
    return THEMES.includes(t) ? t : 'system';
  } catch {
    return 'system';
  }
}

function resolvedOf(theme) {
  return theme === 'system' ? (media?.matches ? 'dark' : 'light') : theme;
}

function apply(theme) {
  const resolved = resolvedOf(theme);
  document.documentElement.setAttribute('data-theme', resolved);
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) meta.setAttribute('content', resolved);
}

export function setTheme(theme) {
  if (!THEMES.includes(theme)) theme = 'system';
  try { localStorage.setItem(KEY, theme); } catch { /* storage unavailable */ }
  apply(theme);
}

export function resolvedTheme() {
  return resolvedOf(getStoredTheme());
}

// Boot: apply immediately (module import time) and follow OS changes while on
// the "system" setting.
apply(getStoredTheme());
media?.addEventListener?.('change', () => {
  if (getStoredTheme() === 'system') apply('system');
});
