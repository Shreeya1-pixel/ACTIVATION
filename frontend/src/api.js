// AutoStack worker API client (Spike deliverable: typed wrapper over the v1 contracts).
// The worker owns every effect; the browser only talks to these endpoints.

const BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8747';
let token = '';
// Session persistence: restore the token at module load so a reload (or app
// restart) resumes the signed-in session. Invalid/revoked tokens fall out
// naturally — the boot auth probe 401s and the Login screen takes over.
try { token = localStorage.getItem('autostack_token') || ''; } catch { /* storage unavailable */ }

export function setToken(t) {
  token = t || '';
  try {
    if (token) localStorage.setItem('autostack_token', token);
    else localStorage.removeItem('autostack_token');
  } catch { /* storage unavailable */ }
}
export function getToken() { return token; }

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const detail = data && data.detail;
    const err = new Error((detail && (detail.error || JSON.stringify(detail))) || `HTTP ${res.status} ${path}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  health: () => request('/api/health'),
  ping: (note) => request('/api/ping', { method: 'POST', body: { note } }),

  stage: (fixture, asFilename) =>
    request('/api/resources/stage', { method: 'POST', body: { fixture, as_filename: asFilename || 'clients.csv' } }),

  saveWorkflow: (wf) => request('/api/workflows', { method: 'POST', body: wf }),
  getWorkflow: (id) => request(`/api/workflows/${encodeURIComponent(id)}`),

  startRun: (body) => request('/api/runs', { method: 'POST', body }),
  bridgeStart: (workflowId) =>
    request('/api/runs/bridge-start', { method: 'POST', body: { workflow_id: workflowId } }),
  getRun: (id) => request(`/api/runs/${encodeURIComponent(id)}`),
  lastRun: () => request('/api/runs/last'),

  postEvent: (event) => request('/api/events', { method: 'POST', body: event }),
  postEvents: (events) => request('/api/events', { method: 'POST', body: events }),
  candidates: () => request('/api/candidates'),
  notifications: () => request('/api/notifications'),
  markNotificationRead: (id) => request(`/api/notifications/${encodeURIComponent(id)}/read`, { method: 'POST', body: {} }),
  capturePoll: () => request('/api/capture/poll', { method: 'POST', body: {} }),
  captureConfig: () => request('/api/capture/config'),
  setCaptureConfig: (body) => request('/api/capture/config', { method: 'POST', body }),
  capturePreview: () => request('/api/capture/preview'),
  loadDemo: () => request('/api/demo/load', { method: 'POST', body: {} }),
  practiceStart: () => request('/api/practice/start', { method: 'POST', body: {} }),
  practiceSheet: () => request('/api/practice/sheet'),
  practiceSave: (rows) => request('/api/practice/save', { method: 'POST', body: { rows } }),
  practiceDone: (rowId) => request('/api/practice/done', { method: 'POST', body: { row_id: rowId } }),
  practiceOpen: (target) => request('/api/practice/open', { method: 'POST', body: { target } }),
  practiceRebaseline: () => request('/api/practice/rebaseline', { method: 'POST', body: {} }),
  practiceSuggestPlan: (candidateId) => request('/api/practice/suggest-plan', { method: 'POST', body: { candidate_id: candidateId } }),
  audit: () => request('/api/audit?verify=1&limit=50'),

  createPlan: (plan, candidateId) => request('/api/plans', { method: 'POST', body: { plan, candidate_id: candidateId } }),
  getPlan: (planId) => request(`/api/plans/${encodeURIComponent(planId)}`),
  generate: (planId, startBroken = false) => request('/api/artifacts/generate', { method: 'POST', body: { plan_id: planId, approve_generation: true, start_broken: startBroken } }),
  listPlanArtifacts: (planId) => request(`/api/plans/${encodeURIComponent(planId)}/artifacts`),
  createTestJob: (artifactId, consent = true) => request('/api/test-jobs', { method: 'POST', body: { artifact_id: artifactId, fixture: 'reset', consent } }),
  getTestJob: (jobId) => request(`/api/test-jobs/${encodeURIComponent(jobId)}`),
  approveActivation: (artifactId, jobId) => request('/api/approvals/activation', { method: 'POST', body: { artifact_id: artifactId, job_id: jobId, note: 'approved in app' } }),
  createWorkflowFromPlan: (planId, context) => request(`/api/plan/${encodeURIComponent(planId)}/create-workflow`, { method: 'POST', body: context || {} }),

  listWorkflows: () => request('/api/workflows'),
  listRuns: () => request('/api/runs/list'),
  runNodes: (runId) => request(`/api/runs/${encodeURIComponent(runId)}/nodes`),
  cancelRun: (runId) => request(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST', body: {} }),
  dismissCandidate: (id) => request(`/api/candidates/${encodeURIComponent(id)}/dismiss`, { method: 'POST', body: {} }),
  compareRun: () => request('/api/compare/run', { method: 'POST', body: {} }),
  registryTemplates: () => request('/api/registry/templates'),
  registryImport: (templateId, localMapping) =>
    request('/api/registry/import', { method: 'POST', body: { template_id: templateId, local_mapping: localMapping } }),
  registryPublish: (payload) => request('/api/registry/publish', { method: 'POST', body: payload }),

  // ── Roadmap: identity ──
  authRegister: (username, password, displayName) =>
    request('/api/auth/register', { method: 'POST', body: { username, password, display_name: displayName || '' } }),
  authLogin: (username, password) =>
    request('/api/auth/login', { method: 'POST', body: { username, password } }),
  authIssueToken: (username, password, name) =>
    request('/api/auth/tokens', { method: 'POST', body: { username, password, name: name || 'default' } }),
  authMe: () => request('/api/auth/me'),
  authListTokens: () => request('/api/auth/tokens'),
  authRevokeToken: (id) => request(`/api/auth/tokens/${encodeURIComponent(id)}/revoke`, { method: 'POST', body: {} }),

  // ── Roadmap: entitlements / org ──
  capabilities: () => request('/api/me/capabilities'),
  setTier: (tier, orgName) => request('/api/org/tier', { method: 'POST', body: { tier, org_name: orgName } }),
  ssoStatus: () => request('/api/org/sso'),
  orgCatalog: () => request('/api/org/catalog'),
  orgProfile: () => request('/api/org/profile'),
  setOrgProfile: (orgType, size, department) =>
    request('/api/org/profile', { method: 'POST', body: { org_type: orgType, size, department } }),

  // ── Roadmap: teams & processes ──
  teamMembers: () => request('/api/team/members'),
  teamAddMember: (username, role) => request('/api/team/members', { method: 'POST', body: { username, role } }),
  teamSetRole: (membershipId, role) => request(`/api/team/members/${encodeURIComponent(membershipId)}/role`, { method: 'POST', body: { role } }),
  teamSelfRole: (role) => request('/api/team/self-role', { method: 'POST', body: { role } }),
  teamRemoveMember: (membershipId) => request(`/api/team/members/${encodeURIComponent(membershipId)}`, { method: 'DELETE' }),
  teamInvitations: () => request('/api/team/invitations'),
  teamCreateInvitation: (role, ttlHours) => request('/api/team/invitations', { method: 'POST', body: { role, ttl_hours: ttlHours || 72 } }),
  teamRevokeInvitation: (id) => request(`/api/team/invitations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  teamAcceptInvitation: (token) => request('/api/team/invitations/accept', { method: 'POST', body: { token } }),
  processes: () => request('/api/processes'),
  createProcess: (name, description, quota) =>
    request('/api/processes', { method: 'POST', body: { name, description: description || '', run_quota_per_day: quota || 0 } }),

  // ── Roadmap: runners & triggers ──
  runners: () => request('/api/runners'),
  registerRunner: (name, kind) => request('/api/runners', { method: 'POST', body: { name, kind } }),
  pairRunner: (id) => request(`/api/runners/${encodeURIComponent(id)}/pair`, { method: 'POST', body: {} }),
  confirmPairing: (id, code) => request(`/api/runners/${encodeURIComponent(id)}/pair/confirm`, { method: 'POST', body: { code } }),
  revokeRunner: (id) => request(`/api/runners/${encodeURIComponent(id)}/revoke`, { method: 'POST', body: {} }),
  triggers: () => request('/api/triggers'),
  createTrigger: (workflowId, kind, config, evidenceNote) =>
    request('/api/triggers', { method: 'POST', body: { workflow_id: workflowId, kind, config: config || {}, evidence_note: evidenceNote || '' } }),
  enableTrigger: (id) => request(`/api/triggers/${encodeURIComponent(id)}/enable`, { method: 'POST', body: {} }),
  disableTrigger: (id) => request(`/api/triggers/${encodeURIComponent(id)}/disable`, { method: 'POST', body: {} }),

  // ── Roadmap: automation expansion ──
  runWorkflow: (workflowId, runDate, filename, dryRun, params) =>
    request('/api/runs', { method: 'POST', body: { workflow_id: workflowId, run_date: runDate, filename: filename || 'clients.csv', dry_run: !!dryRun, params: params || {} } }),
  rollbackRun: (runId) => request(`/api/runs/${encodeURIComponent(runId)}/rollback`, { method: 'POST', body: {} }),
  runGates: (runId) => request(`/api/runs/${encodeURIComponent(runId)}/gates`),
  decideGate: (gateId, approved, decidedBy) =>
    request(`/api/gates/${encodeURIComponent(gateId)}/decide`, { method: 'POST', body: { approved, decided_by: decidedBy || 'user' } }),
  declareParameter: (workflowId, name, paramType, required, defaultValue) =>
    request(`/api/workflows/${encodeURIComponent(workflowId)}/parameters`, { method: 'POST', body: { name, param_type: paramType || 'string', required: !!required, default: defaultValue === undefined ? null : defaultValue } }),

  // ── Roadmap: governance ──
  auditExport: () => request('/api/governance/audit-export'),
  siemStream: () => request('/api/governance/siem/stream'),
  complianceBundle: () => request('/api/governance/compliance-bundle'),

  // ── Roadmap completion: notifications center, privacy, connectors ──
  markAllNotificationsRead: (ids) =>
    request('/api/notifications/read-all', { method: 'POST', body: { ids: ids && ids.length ? ids : null } }),
  privacyLedger: () => request('/api/privacy/ledger'),
  privacyRetention: () => request('/api/privacy/retention'),
  setRetention: (observationsDays, reportsDays) =>
    request('/api/privacy/retention', { method: 'POST', body: { observations_days: observationsDays, reports_days: reportsDays } }),
  privacyExport: () => request('/api/privacy/export', { method: 'POST', body: {} }),
  connectors: () => request('/api/connectors'),
  aiMode: () => request('/api/system/ai-mode'),
};
