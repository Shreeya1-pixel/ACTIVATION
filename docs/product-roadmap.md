# AutoStack IN — Product Roadmap (pages, tiers, teams, automation coverage)

Date: 2026-09-24 · Baseline: post-QA-hardening build (70 tests, live stack, exactly-once verified).
Everything here is **planned, additive work** — nothing in this document claims existing behavior.
Grounded in README §1 (product commitments), §3 (permission model), §7 (runner modes), and the
existing 6-screen dashboard. Rule inherited from the project: **no invented metrics anywhere** —
tier gates are real capability checks, savings stay honest, ratings come from real installs.

---

## 1. Page map — what exists and what gets added

Today the React app is a 6-screen SPA (hash of `page` state, no router): Dashboard, Discovery,
Registry, Workflows, Trust Log, Create Automation. All are live on real backend state. The plan:

### 1.1 New pages

| Page | Purpose | Key contents |
|---|---|---|
| **Home** | Product entry, distinct from the working Dashboard. For the desktop app: a first-run/overview home with setup checklist (worker status, observation consent, connectors, first automation). For the future web presence: landing with tier comparison and download. | Setup progress, tier badge, quick actions, recent activity (real), links into all screens |
| **Login / Signup** | Local-first accounts. Desktop-first product → local profile (username + OS-keyring-stored secret / PIN unlock) with optional cloud account later for registry & teams. Per-user API tokens replace the single shared spike token. | Sign in, create local profile, unlock with OS credential store, recovery key |
| **Settings** | The control surface the product promised but never had. | Sections: Profile · Permissions · Data & Privacy · Connectors · Runner · Notifications · Appearance · Advanced |
| **Teams** | Org management (Team tier+). | Members & roles, invitations, approval policy editor, per-process scoping |
| **Runners** | Runner management (README §7). | Local runner health, paired office-runner pairing flow (identity + consent), runner quotas, job history |
| **Scheduling** | Opt-in recurring runs — README explicitly marks scheduling "later opt-in". Only schedules validated by real calendar history; demo cycles never create schedules. | Schedule list, evidence source (observed dates), pause/resume, next-run preview |
| **Notifications center** | Full page behind the bell: filter by workflow/process, read states, per-category mute. | Real notification rows (already exist) with filters |
| **Data & Privacy** | README consent/retention commitments made real. | Retention (30d observations / 90d reports, configurable), export, delete-by-scope, consent ledger |
| **Connectors** | Connector inventory with honest status. | Each connector: supported/limited/unavailable, what it can and cannot see (README §4 boundaries), consent state |
| **Profile / Account** | Tier, usage, keys. | Current tier + real entitlements, model-quota state (free-tier honesty), API tokens, license |

### 1.2 Navigation & routing

- Replace ad-hoc `page` state with a small **hash router** (`#/dashboard`, `#/settings/permissions`, …)
  — desktop/Electron-safe, deep-linkable, additive (all six existing screens keep their routes).
- Persistent left nav grouped: **Work** (Dashboard, Discovery, Create, Workflows) ·
  **Trust** (Registry, Trust Log) · **Operate** (Runners, Scheduling, Notifications) ·
  **Account** (Teams, Profile, Settings). Tier-gated items render but show their requirement.
- First-run **Onboarding wizard** (Home): tier choice → consents → connector check → first workflow.

---

## 2. Account types (tiers) — mapped to the README feature list

Tiers are **entitlements, not just labels**: a `capabilities` record in the backend drives both the
UI (what renders/enables) and the API (what the server enforces). The server is the gate; the UI
only mirrors it — same rule as every other gate in this codebase.

| Capability (from README) | Solo (free) | Team | Enterprise | Government | Developer/ISV |
|---|---|---|---|---|---|
| Discovery, generation, sandbox testing, activation | ✅ | ✅ | ✅ | ✅ | ✅ |
| Local runner (Docker mode) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Paired office/team runner (shared mode) | — | ✅ | ✅ | ✅ (on-prem) | ✅ |
| Members / roles | 1 user | up to N | unlimited + SSO | unlimited + SSO | 1–few |
| Approval policies (who may test/activate/run/publish) | self | team roles | org policy matrix | statutory role separation | self |
| Private team registry space | — | ✅ | ✅ | ✅ (dept-scoped) | ✅ (publisher) |
| Publish to national registry (reviewed templates) | — | — | — | ✅ (governed) | ✅ (reviewed) |
| Scheduling (opt-in, calendar-validated) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Retention administration | defaults | team defaults | org policy | statutory retention | defaults |
| Audit chain export (SIEM/compliance) | local file | JSON export | SIEM stream | compliance bundle | local file |
| Cloud model generation | free quota | pooled quota | org quota / BYO key | **local-only templates** (no cloud) | dev quota |
| Connector credential vault | OS keyring | team vault | org vault + scoping | on-prem vault | sandbox keys |
| API/CLI access | — | — | ✅ | ✅ (approval-gated) | ✅ (primary feature) |
| Air-gapped / data-residency mode | — | — | option | **default: local-only** | — |

Notes (honesty rules preserved):
- **Government tier is defined by what it refuses**: no cloud model calls, no data leaving the
  premises, deterministic template automation only, plus the governed national-registry
  contribution flow from README §1. This is a *feature* (sovereignty), not a limitation.
- **Solo == everything that exists today**, plus local accounts. It stays free/open-source per
  README ("Free development").
- **Developer/ISV** exists to grow the registry: build connectors/templates, test against sandbox
  quota, publish after review. Selling point: distribution to every installed office.

### 2.1 Entitlements implementation (additive)

- `backend/entitlements.py`: `Entitlements` record (tier, limits, flags) + `GET /api/me/capabilities`.
- License resolution order: org server (paid tiers, later) → local entitlements file signed by the
  org → default Solo. No tier logic is ever hardcoded inside screens; screens read capabilities.
- Every enforcing endpoint checks the capability server-side (e.g., team endpoints on Solo → 403
  with an actionable explanation and the tier that unlocks it).

---

## 3. Teams, roles, processes (per account type)

### 3.1 Teams & roles

Roles map 1:1 onto the README §3 permission model — that model becomes the RBAC matrix:

| Role | Observation | Read content | Test | Activate | Run | Publish | Admin |
|---|---|---|---|---|---|---|---|
| Observer | own | — | — | — | — | — | — |
| Operator | own | own | own | — | approved wfs | — | — |
| Approver | team | team | ✅ | ✅ | ✅ | — | — |
| Owner/Admin | team | team | ✅ | ✅ | ✅ | ✅ | ✅ |

- **Approval policies** (Team+): e.g., "activation requires 2 approvers" (Enterprise/Gov default
  for workflows touching finance), "publish requires governance role" (Gov).
- Processes: workflows are grouped into **business processes** (e.g., Client Follow-ups, Invoice/PO
  Matching, Reporting). Processes carry: owning team, run quotas, retention scope, and audit
  filters. The Trust Log and audit export filter by process — this is how a Gov department proves
  what ran.
- Invitations (Team+): token-based, expiring; roles granted at accept time; revocation stops
  dependent operations per README ("Revoking execution access stops dependent operations").

### 3.2 What stays per-user regardless of tier

Consents, drafts awaiting review, personal tokens, personal observation pause. Teams share
workflows and runners — never consents or drafts (matches "dismissal never means approval").

---

## 4. Automation features to add (maximum workflow coverage, robust by design)

Ordered by (a) README alignment, (b) robustness value, (c) implementation risk. All additive to
the existing catalog/journal/exactly-once machinery.

### 4.1 Execution & trust (highest value, lowest risk)

1. **Dry-run mode** — execute a run with effects computed but *not applied*; report the exact
   would-be changes (diff preview). Uses the same journal machinery with a `dry_run` effect scope.
   Selling point: "see exactly what will change before it does."
2. **Rollback bundles** — for reversible effects, record inverse operations at claim time and add
   `POST /api/runs/{id}/rollback` (audited, itself exactly-once). Backups already exist per write;
   this makes recovery a first-class, user-visible action.
3. **Conditional branching in graphs** — `branch` node over the existing sandboxed expression
   engine (if/else on row fields, counts, time windows). Unlocks real decision workflows.
4. **Approval-gate node** — workflow **pauses** mid-run awaiting a human decision (README:
   "pausing for required human decisions"). Notification → decision → resume/abort, all audited.
5. **Run templates / parameters** — declare parameters (date range, file, threshold) on bind;
   Run-now accepts parameter values within the approved scope (README: "Input records/files and
   run dates are declared parameters within the approved resource scope").

### 4.2 Triggers

6. **Scheduler** (opt-in; §1 Scheduling page) — recurring runs with **calendar-evidence
   validation**: a schedule can only be created from observed date history or explicit user
   confirmation; accelerated demos never create schedules (README §5.5).
7. **Webhook trigger** — inbound allowlisted trigger with per-workflow token → starts an approved
   run (Rate-limited, audited; feeds the Developer tier API story).
8. **File-arrival trigger** — watcher event (already exists) can be attached as a workflow trigger
   for a declared filename pattern within the resource alias.

### 4.3 Catalog expansion (new node types, all through safeio/journal)

9. `file.copy`, `file.archive` (move to dated folder) — within allowlisted alias only.
10. `row.append` (insert new rows with duplicate-ID handling rules).
11. `row.delete` (soft-delete/status flag by default; hard delete requires policy).
12. `email.draft` — creates **drafts only** via later Gmail/Graph connector; never sends without a
    human (README: "Initial drafts stay in-app; no account access or sending").
13. `pdf.generate` (template fill) and `report.compile` (aggregate rows → summary CSV/PDF).
14. `http.request` — **allowlisted-host only**, static allowlist per workflow, no user/model URLs
    (README: "named, allowlisted operations, not arbitrary URLs").
15. `aggregate` / `group-by` node for reporting workflows.

### 4.4 Intelligence & reliability

16. **Approximate sequence matching** for detection (README §5: "comes later with evaluated
    rules") — with evaluated thresholds and reported false-positive counts, never vibes.
17. **Retry policies per node** — bounded retries with backoff for idempotent reads; effects stay
    exactly-once (retries never re-apply — the journal already guarantees this).
18. **Reconciliation v2** — periodic honest diff of DB claims vs resource state; surfaces
    drift as gaps (extends existing reconcile).
19. **Connectors roadmap** (each a separate consent + implementation): Excel add-in events →
    Gmail/Graph reports → browser connector expansion. Coverage matrix per connector published,
    per README §4 ("Define its coverage before claiming a workflow is supported").

### 4.5 Registry v2 (national-scale story)

20. Versioned template publishing with review states (draft → reviewed → published → withdrawn),
    **real** install counts and run-derived quality signals (no invented ratings), offline import
    bundles, and Gov-governance workflow for national contributions.

---

## 5. Selling points (what we market, all demonstrable in the product)

1. **Evidence-based discovery** — suggestions from real observed work with visible evidence;
   no fake confidence percentages (competitors show "91% confidence" — we show the receipts).
2. **Verifiable audit** — hash-chained, tamper-evident ledger; `chain_valid` checkable by anyone;
   compliance export for Gov/Enterprise.
3. **Exactly-once effects** — concurrent-run-proof, cross-transport (UI, Node-RED, API), measured.
4. **Dry-run + rollback** — try safely, recover cleanly.
5. **Human gates everywhere it matters** — separate approvals to test and to activate (README §3).
6. **Sovereign deployment** (Gov) — local-only mode, no cloud, national registry for reuse.
7. **Offline-capable core** — discovery, review, and deterministic approved workflows run without
   internet; only cloud generation waits (README §7).
8. **Honest savings** — measured where measurable, labeled "not measured" where not; formula and
   assumptions displayed (README §6).
9. **Works without Docker on old machines** — paired-runner shared mode (README §7) — a real
   differentiator for under-resourced offices (the core problem statement).
10. **Developer ecosystem** — connectors/templates marketplace with revenue share.

---

## 6. Implementation order (each phase shippable, nothing disruptive)

| Phase | Delivers | Depends on | Status (2026-09-24) |
|---|---|---|---|
| **A. Identity & shell** | Local accounts + per-user tokens; hash router; Login/Signup, Settings (Profile/Permissions/Data), Profile pages; onboarding wizard. *Completion pass: unified auth (user tokens valid on every route), session persistence, deep-link restore* | nothing (backend auth layer is the one structural addition) | **SHIPPED** — `backend/identity.py`, Login/Home/Settings/Profile live; legacy single-token mode untouched |
| **B. Entitlements** | capabilities API + tier resolution; tier gating in UI/API; tier selection; Solo defaults | A | **SHIPPED** — `backend/entitlements.py`, `/api/capabilities`, tier switcher verified in browser |
| **C. Teams & processes** | Teams/roles/invitations; approval policies; process groups; Teams page; audit filters by team/process | B | **SHIPPED** — `backend/teams.py`, Teams page live |
| **D. Runners & triggers** | Runners page + pairing flow; webhook & file-arrival triggers; Scheduling page + calendar-validated schedules | B (C for shared runners) | **SHIPPED** — `backend/orchestration.py`; webhook/file triggers implemented, no external delivery |
| **E. Automation expansion** | dry-run, rollback, branch/approval-gate nodes, parameters, catalog nodes 9–15 | A (journal/catalog) | **SHIPPED** — dry-run `would_*` evidence, inverse-effect rollback, gate pause/resume, param validation |
| **F. Governance** | Enterprise: policy matrix, retention admin, SIEM export, SSO hook. Gov: local-only mode, national-registry contribution flow, compliance bundle | C, D | **SHIPPED (hook-level)** — SIEM export, compliance bundle, local-only enforcement live; SSO is a status endpoint, no IdP wired |
| **G. Ecosystem** | Registry v2 review states; Developer/ISV publisher flow; API/CLI; landing page for web | B–D | **PARTIAL** — registry review states + install counts shipped; publisher flow/API/CLI/landing page not started |

**Migration safety notes**
- Auth (Phase A) is the only structural change; it lands behind a compatibility default: the
  existing single-token mode keeps working (flags/`spike` harness), per-user tokens activate
  alongside, and the QA probe must stay green through the migration.
- Every new node type enters the catalog with static-validation rules and journal-scoped effects —
  no new effect paths outside `safeio`/journal, ever.
- Every new page consumes real endpoints; where a capability is tier-gated, the UI shows the
  requirement instead of a fake state (project rule: no invented anything).
- New endpoints follow the existing pattern: token-authenticated, audited, probed by
  `scripts/qa_probe.py`, and covered by tests before a screen consumes them.

## 7. Explicitly out of scope for now (honesty)

- Actual payment/licensing servers (tiers resolve locally until a real billing decision exists).
- Sending email (drafts only), payments, CAPTCHA/MFA automation, statutory submissions — README
  forbids claiming these without supported integrations and human involvement.
- Cross-OS install evidence (macOS/Linux) and Docker image build — hardware/infra dependent.
