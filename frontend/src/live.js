// Live data layer: bridges the real worker (backend/app.py) into the existing UI.
// Rule: the worker owns real state; the UI falls back to demo data only when the
// worker is unreachable. Never invents numbers — real candidates carry exact counts.

import { api } from './api.js';

const state = {
  listeners: new Set(),
  data: {
    connected: false,
    candidates: [],      // real, from /api/candidates
    notifications: [],   // real, from /api/notifications
    audit: null,         // real, from /api/audit?verify=1
    lastRun: null,       // real, from /api/runs/last
    workflows: [],       // real, from /api/workflows
    runs: [],            // real, from /api/runs/list
  },
  timer: null,
};

function emit() {
  const snapshot = { ...state.data };
  state.listeners.forEach((fn) => fn(snapshot));
}

export function subscribeLive(fn) {
  state.listeners.add(fn);
  fn({ ...state.data });
  return () => state.listeners.delete(fn);
}

async function pollOnce() {
  // Anonymous visitors never poll: the console 401-loop is noise for signed-out
  // users, and the data would be refused anyway. Signed-in state re-arms it.
  try { if (!localStorage.getItem('autostack_token')) { state.data = { ...state.data, connected: false }; emit(); return; } } catch { /* storage unavailable */ }
  const next = { ...state.data };
  let connected = false;
  try {
    const [cands, notes, audit, lastRun, workflows, runs, me] = await Promise.all([
      api.candidates(),
      api.notifications(),
      api.audit ? api.audit() : Promise.resolve(null),
      api.lastRun().catch(() => null),
      api.listWorkflows ? api.listWorkflows().catch(() => []) : Promise.resolve([]),
      api.listRuns ? api.listRuns().catch(() => []) : Promise.resolve([]),
      api.authMe().catch(() => null),
    ]);
    next.candidates = Array.isArray(cands) ? cands : [];
    next.notifications = Array.isArray(notes) ? notes : [];
    next.audit = audit;
    next.lastRun = lastRun;
    next.workflows = (workflows && workflows.workflows) || [];
    next.runs = (runs && runs.runs) || [];
    if (me) next.me = me; // {role, user, capabilities} — role-aware UI gating
    connected = true;
  } catch {
    connected = false; // demo mode keeps prior data; nothing invented
  }
  next.connected = connected;
  state.data = next;
  emit();
}

export function startLive(pollMs = 4000) {
  if (state.timer) return;
  pollOnce();
  state.timer = setInterval(pollOnce, pollMs);
}

export function stopLive() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

export async function capturePoll() {
  return api.capturePoll ? api.capturePoll() : null;
}
