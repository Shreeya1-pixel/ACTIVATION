# Stage-0 Spike Evidence (AutoStack IN)

Date: 2026-09-23 · Baseline: upstream `adf5570` (Phase 1) · All new work is **additive** —
`git status` shows zero modified tracked files; every Phase-1 artifact is untouched.

## Spike verdicts

| Spike | Claim to prove | Verdict | Evidence |
|---|---|---|---|
| S1 | Node-RED 4.1.1 embeds in-process with our custom nodes | **PASS** | `NODE_RED_READY` + `SELF_PROBE 200 flows-deployed=true` from `desktop/red-embed.js`; custom `as-*` nodes load from `desktop/red-nodes/` |
| S2 | Worker serves state with token auth + audit | **PASS** | `POST /api/ping` writes DB row + audit entry; 401 without bearer token |
| S3 | graph→Node-RED flow compiler is lossless for our graph shapes | **PASS** | `tests/spike/test_flow_compiler.py` 7/7 (positions, wires, creds injection, env) |
| S4 | **The whole automation actually works, twice, exactly-once** | **PASS** | `tests/spike/test_s4_end_to_end.py` green (twice consecutively): real POST `/spike/run` → embedded Node-RED → worker bridge-start → read-due (Phase-1 parser) → per-row fan-out → join → update-row (journal claim + safeio) → draft-create → notify → complete |
| S5 | Safe file IO + verifiable audit chain | **PASS** | staged atomic writes with `.bak` backups; `GET /api/audit?verify=1` → `chain_valid: true` after both runs |
| S6 | Worker containerizes cleanly | **PARTIAL** | `deploy/Dockerfile.worker` written (non-root, healthcheck); Docker CLI 29.5.3 present but daemon not running on this machine — build deferred to Milestone C CI |
| S7 | AI generation adapter with offline guarantee | **PASS** | `backend/engine/ai.py` (mock deterministic; Gemini REST provider fails closed without key); `ai:auto` template drafts through the same journal path (tests green) |

## S4 proof details (from the green run)

- **Run 1**: 2 due rows (C001, C003) → 2 `file.update_rows` + 2 `draft.create` node records
  (all `passed`), 4 journal claims all `applied`, file diff = exactly
  `sample:C001 ['Status']` + `sample:C003 ['Status']`, nothing added/removed.
- **Run 2** (identical trigger): 0 drafts, 0 file changes — every effect
  `idempotent-claimed` via the journal.
- **Audit**: single unbroken hash chain across both runs (workflow.saved →
  resource.staged → run.bridge-started → 4× effect.applied → notify.desktop →
  run.completed → second run → run.completed); `verify_chain` recomputes every link.

## Engineering bugs found and fixed during the spike (the point of spiking)

1. **Audit chain fork under concurrency** — two parallel bridge calls read the same
   chain tail and computed the same `prev_hash`. Fix: process-wide append lock +
   dedicated committed transaction per link (`backend/security/audit.py`).
2. **SQLite single-writer deadlock** — caller's open transaction + audit's dedicated
   session. Fix: commit caller transaction before the audit insert (documented
   trade-off; outbox pattern scheduled for Milestone C).
3. **Lost-update race on the tracking file** — concurrent read-modify-write of the
   same CSV dropped one row's update. Fix: per-resource threading lock around the
   whole read-modify-write (`backend/engine/rows.py`).
4. **Node-RED 4 embed semantics** — `RED.init` does not mount middleware (embedder
   must attach `RED.httpAdmin`/`RED.httpNode`); function-node sandbox has no `fetch`
   (provided via `functionGlobalContext`); async/return mode determines `send` vs
   `return` semantics; `cloneMessage` deep-copies `msg.res` (202-ack must keep the
   original message on the response path).

## Regression gate

- `tests/unit`: **20 passed, 29 subtests** (Phase-1 contracts + file-diff, unchanged).
- `npm run build` (frontend): clean production build, 1.29s.
- `git status`: **no tracked file modified** — Phase-1 baseline `adf5570` intact.

## Stack layout delivered

- `backend/` — FastAPI worker: settings, DB (WAL SQLite), models, security
  (tokens/audit/safeio), engine (expressions/journal/catalog/rows/ai), nodebridge
  (flow compiler), routes for workflows/runs/nodes/events/candidates/audit.
- `desktop/` — Node-RED embed harness + 4 custom bridge nodes + spike flow +
  Electron entrypoint skeleton (`main.js`, activates after `npm i -D electron`).
- `frontend/src/api.js` — typed worker API client for the existing UI.
- `deploy/Dockerfile.worker` — non-root worker image.
- `tests/spike/` — compiler, AI adapter, AI draft journal, S4 end-to-end.

All services reproducible:
`python scripts/run_worker.py` + `node desktop/red-embed.js http://127.0.0.1:8747 $(cat artifacts/spike/token) desktop/spike-flow.json`
→ `pytest tests/unit tests/spike` → 33 passed.

---

# Milestones A–K build record (Phase 2–9 implementation, 2026-09-23)

Post-spike full build following `plan.md` phases 2–10. Current totals: **64 passed,
29 subtests** (Phase-1 units unchanged + all new suites), frontend builds clean.

| Phase | Delivered | Evidence (tests) |
|---|---|---|
| 2 — Desktop foundation | Electron shell (`desktop/main.js`): worker child on :8747, in-process Node-RED via `red-embed-core.js` on :18790, tray (Open dashboard / Pause observation / Quit), window-close keeps worker alive, secure renderer (contextIsolation, sandbox, no nodeIntegration). Electron 33.2.0 installed. | shell boots; `node --check` clean; lifecycle owned by tray |
| 3 — Real capture | `backend/capture/watcher.py`: bounded folder polling, 5-second settling grace, `~$` lock files never parsed, stable-version diff via Phase-1 `file_diff`, honest gaps instead of invented events, v2 contract events. Route: `POST /api/capture/poll` (persistent baseline state). | `test_watcher.py` (5), `test_detect_chain.py::capture` |
| 4 — Detection | `backend/detection/sequences.py` + `service.py`: per-client instance streams, followed-instance closing semantics (trailing = open until ≥10-min silence proven), ≥3 instances across ≥2 clients threshold, autostack/failure exclusion, exact-count evidence (NO fabricated confidence), persistent notifications with re-alert suppression. Routes: `/api/events` (chains detection), `/api/candidates`, `/api/notifications[+/read]`. | `test_detection.py` (10), `test_detect_chain.py` (2) |
| 5 — Plan + generation | `backend/engine/generation.py`: REQUIRED_RULES block generation on missing/contradictory rules; provider adapter (mock deterministic / Gemini REST); static security validation with hard rejects (imports outside allowlist, network, subprocess, eval/exec, os/sys, dunder escapes, dependency installs, raw open). Models: `GenerationPlan`, `GeneratedArtifact` (versioned, content-hashed). Routes: `/api/plans`, `/api/artifacts/generate`. | `test_generation_runner.py` (plan blocked, approval enforced, mock output rejected by validation) |
| 6 — Isolated runner | `backend/engine/runner.py`: fresh subprocess with RLIMIT_CPU/AS/NPROC/FS (POSIX) + wall-clock kill, network hard-blocked via startup guard, static violations refuse execution, independent functional checks (result shape/bounds), content-bound reports (policy_sha256 + report_sha256). Test consent required; failed tests are valid outcomes that keep activation blocked. Routes: `/api/test-jobs`. | `test_generation_runner.py` (evil code refused, failing test blocks activation, binding enforced) |
| 7 — Run now + lifecycle | Cancellation keeps already-applied effects and reports them (scoped recovery, no silent undo); restart reconciliation closes stuck runs as failed; both audited. Routes: `/api/runs/{id}/cancel`, `/api/runs/reconcile`. Exactly-once journal (spike S4) remains the effect source of truth. | `test_lifecycle.py` (3) |
| 9 — Registry | Publication consent + secret scan (credentials/private paths blocked) + graph validation + versioning; listing shows only latest per slug with NO invented ratings/counts; imports are ALWAYS untrusted drafts (mapping applied, artifact hash changes, approvals never inherited); withdrawal stops new imports without invalidating installed copies. Routes: `/api/registry/*`. | `test_registry.py` (5) |
| Frontend wiring | `live.js` polls real worker state (anonymous users never poll — no 401 loop); Discovery shows only real evidence-based candidates with an honest empty state (demo cards removed); Trust Log shows the live hash chain with `chain_valid`; the floating nav shows a worker status dot. Navigation is a floating top bar with dropdown groups (see README "Using the app"). | build clean; UI re-verified via DOM probes after the floating-nav rebuild |

## Tracked-file policy

Exactly two tracked files were modified, both intentionally and additively:
- `backend/validate_events.py` — v2 contract support (v1 behavior byte-identical, all 20 Phase-1 unit tests still pass).
- `frontend/src/main.jsx` — live-data wiring (demo data preserved as fallback; demo mode is the plan's product requirement).

Everything else is new files. Regression gate: 70 passed / 0 failed, `npm run build` clean.

## Phase 8/10 build record (final session)

**Keystone (plan→workflow→run).** `graph_build.py` compiles a confirmed plan into a
catalog-valid graph; `_exec_graph` runs it topologically through the same exactly-once
effect paths as the Node-RED bridge. `POST /api/plan/{id}/create-workflow` binds an
ACTIVATED artifact to a versioned workflow (hash covers graph+plan+code together).
`POST /api/runs` (Run-now) executes compiled versions. Proven live over HTTP:
plan → generate → sandbox test (plan-derived expected outputs) → activation → bind →
run 1 drafted C001+C003 → run 2 idempotent-claimed. Test: `test_keystone_chain.py`.

**Second workflow (Phase 8).** Invoice/PO comparison (`compare.py` + `POST
/api/compare/run`): three-way scoped categories (matched / amount_mismatch / missing_po),
exact-cents tolerance math (a float-boundary bug was caught by the test), independent
linear-scan oracle, effects via the same journal. Exactly-once proven (run 2 = no-op).

**Measurements (Phase 8, `docs/budgets.json`, Win11/py3.13).** Idle CPU 0.31% of a
core (budget 1%), resident memory 94 MiB (budget 400), capture poll 21.6 ms (budget
500 — the first measurement caught a REAL bug: the watcher slept `settle_seconds` for
every file every poll; now only changed files settle, 24× faster, same honesty).

**Platform matrix.** `docs/platform-matrix.md` — verified/tested/unsupported rows per
the plan's no-parity-assumption rule (xlsx/email-send/Gov-API explicitly unsupported).

**Phase 10 frontend (all six screens live-capable).** Dashboard: real runs/notifications,
recorded-data chart, honest empty states, savings labeled "not measured". Workflows:
real versions/runs/Run-now/cancel/node records. Registry: live publish/import with
consent, untrusted-draft imports, zero invented ratings. Trust Log: real hash chain,
workflow filter, `chain_valid` shown. Discovery: dismiss control persisted to backend.
Create Automation: real backend-gated stepper (plan→generate→test→approve→bind→publish);
backend gates cannot be bypassed by clicking ahead.

**Bugs found & fixed this phase:** route shadowing (`/api/runs/list` vs `/api/runs/{id}`),
Jinja sandbox literals (`none` not `None`, `|string` filter instead of `str()`),
`GenerationPlan`/`time` import gaps, float cents comparison in the matcher, watcher
poll cost. Each caught by a test before reaching the demo.

## Remaining (external dependencies only)

- macOS/Linux install + sign-in startup + notification platform tests (code paths are cross-platform; OS matrix evidence needs the machines).
- Docker build evidence (daemon was not running on this machine; `deploy/Dockerfile.worker` is ready).
- Phase 10 visual acceptance screenshots at phase-1 reference window sizes (screens are functionally complete; pixel comparison needs the human eye).

## QA pass (feature-by-feature verification)

`scripts/qa_probe.py` exercises 57 checks across 13 feature areas against the LIVE
stack (auth, staging + traversal, capture, events/detection, notifications, the full
plan→generate→sandbox→activation→bind→run-now chain, compare workflow, cancel/
reconcile, registry incl. secret-scan + withdrawal, audit chain, AI fail-closed,
Node-RED S4). **57/57 pass, twice consecutively.** The browser UI was driven through
all six screens with live data, including the full Create-Automation gate chain
(plan → generate → sandbox report → approval → `wf-36a99e38 v1` bound) and a registry
import arriving as an untrusted draft.

Bugs the QA pass found and fixed (each caught before it could ship):
1. Create Automation crashed the whole app — missing React hooks import (build didn't catch it; the browser did).
2. No CORS middleware — the dashboard could never reach the worker from a browser (scoped origin allowlist added; token auth unchanged).
3. `/api/resources/stage` returned 500 on traversal filenames (now 400 with detail).
4. Malformed `run_date` returned 500 on run-now/bridge-start (now 400, 3 call sites).
5. Capture-poll response shape mismatch with the UI (now a superset: counts + arrays).
6. Watcher `gaps` list grew unbounded in a long-running worker (now capped at 100).
7. Trust Log never ran chain verification (`chain_valid` stayed null) — live layer now calls `?verify=1`.

Completeness matrix: 17 tables ↔ 36 routes ↔ 0 orphan routes (every route referenced
by tests, the probe, the frontend, or the S4 flow); regression state 70 pytest +
57 probe + clean build; tracked-file policy still exactly 2 modified files.

## QA round 2 — re-verification + hostile exploration (2026-09-24)

All 7 round-1 fixes re-verified live on a fresh stack. New hostile classes probed
concurrency (8-way parallel run-now), oversized payloads, template/expression
injection, method hygiene, parallel capture polls, Node-RED bridge auth.

Verified sound under attack:
- Exactly-once under contention: 8 concurrent run-now on fresh data drafted exactly
  2 effects (0 duplicates); 9th run no-op.
- Template/expression injection (`{{ ''.__class__.__mro__ }}` in data): rendered as
  literal text; sandboxed Jinja held; no sandbox leak in any draft body.
- Fixture contract enforced: wrong columns and non-sample client IDs rejected
  (`InvalidFixture`), runs recorded honestly as failed.
- Node-RED bridge auth (401 on wrong token), method hygiene (405/404), unicode
  filenames accepted, traversal `as_filename` blocked, parallel capture polls safe.
- Audit hash chain intact through the entire campaign (`chain_valid: true`).

New bugs found and fixed:
8. Bad fixture content (wrong columns / non-sample IDs) on run-now surfaced as HTTP
   500 — `InvalidFixture` (a `ValueError`) was stringified at the node boundary and
   lost its type. Fixed by chaining the node error (`raise ... from`) and mapping the
   cause chain to 400 in both run paths; runs still record honest failure rows.
9. "unsafe filename" error message doubled (route prepended a prefix to a message
   that already contained it) — deduped.
10. Known hardening note (not fixed, by design for the spike): no request size cap
    (2 MB plan accepted); recommend a body-size limit before any real deployment.

Final state: 70 pytest + 29 subtests green after the fixes, clean frontend build,
S4 Node-RED transport re-verified against the restarted worker, chain_valid: true.

## Roadmap implementation (Phases A-G) — 2026-09-24

Implemented the approved product roadmap (docs/product-roadmap.md) in full:

- **A Identity**: local-first accounts (PBKDF2 200k, lockout after 10 failures), per-user API
  tokens hashed at rest (plaintext shown once), backward-compatible service token. Login/Signup
  page gates the app; the Electron shell and QA tooling now read the same stable token.
- **B Entitlements**: tier capability matrix (solo/team/enterprise/government/developer) enforced
  server-side with actionable unlock hints; government tier = local-only (cloud generation
  refused, governed national-registry publishing allowed).
- **C Teams**: roles over README §3's permission model, last-owner protection, expiring
  invitations, business processes with daily run quotas (429 on breach).
- **D Orchestration**: runner registration + paired-runner pairing (fingerprint-verified),
  webhook triggers (secret + rate limit) that start real runs, file-arrival and calendar-evidence
  schedules (3+ distinct observed dates or explicit confirmation; interval/cron shortcuts refused).
- **E Automation expansion**: dry-run (would_update/would_draft, consumes no claims), honest
  rollback (inverse row updates from prior values captured at effect time; exactly-once;
  audited), control.branch (sandboxed condition skips downstream), approval.gate (run pauses
  with persisted context, human decision resumes it without redoing claimed effects), declared
  run parameters validated against the approved scope, user-authored graphs now run as authored.
- **F Governance**: audit export, tier-gated SIEM JSONL stream, compliance bundle with live
  chain verification.
- **G Registry**: review states + honest install/run-report signal counts (nothing estimated).

Frontend: Login/Signup, Home, Settings (tier switch + gated cards render their requirement),
Profile (API tokens, shown-once), Teams, Runners, Scheduling — all on real endpoints; grouped
nav (Work/Trust/Operate/Account); identity chip reflects the real principal.

Hardening closed from QA rounds 2-3: request bodies >1 MB -> 413; stable worker token persisted
to artifacts/spike/token (restarts no longer rotate auth; env AUTOSTACK_TOKEN still wins);
desktop shell reads the same token source; Node-RED harness injects real credentials into tab
env (spike flow worked after rotation); dev-DB reset clears run-scoped FK children (ReviewGate,
run-context keys); dead code, empty leftover packages, duplicate probe script, and probe-junk
fixtures removed; requirements.txt pinned; scripts/run_worker.py relocated from the runtime dir.

Verification: **98 pytest + 29 subtests green** (21 roadmap + 7 hardening tests added), 57/57
live QA probe, clean frontend build, S4 Node-RED chain 202 + exactly-once, browser-verified
signup → logged-in workspace across all 12 screens.

## Round 4 — roadmap completion pass (2026-09-24)

Closed the three planned-but-missing surfaces: **Notifications Center** page,
**Data & Privacy** page (retention admin with bounds enforced server-side, portable
export, consent ledger from real approvals), and **Connectors** page (statuses
measured live — Gemini key presence, government local-only; email and cloud transfer
honestly "unavailable"). Seven new endpoints: notifications/read-all, privacy/ledger,
privacy/retention GET+POST, privacy/export, connectors, system/ai-mode.

New bugs found by browser walkthrough — all fixed and verified live:
1. **Legacy routes rejected per-user tokens** (only `/api/roadmap*` routes accepted
   them) — a signed-in user got 401s across the original screens. Fixed: `require_token`
   now falls back to the user-token lookup; service-token path unchanged
   (verified: user token 200 → revoke → 401, service token unaffected).
2. **Boot token clobber** — `live.js` reset the token to the legacy default on every
   load, poisoning restored sessions. Fixed: default only when no session exists.
3. **Session lost on reload** — token lived only in a module variable. Fixed:
   localStorage persistence (`autostack_token`), invalid tokens fall out via the
   boot auth probe.
4. **Page state wiped every live-poll cycle** — the Screen map held inline arrow
   components, so each App re-render created a new component type and React
   remounted the page (notification filters reverted after ~2.4 s; any form input
   would have been cleared mid-typing). Fixed: render elements, not component
   wrappers (verified: filter persists across 10 poll cycles).
5. **Deep links never restored** — hash was written but never read on boot. Fixed:
   hash router completed (hash is source of truth; reload restores the page).

Verification: **105 pytest + 29 subtests green**, frontend build clean, all seven
new endpoints 200 on the live worker, browser walk of Notifications (filters),
Data & Privacy (ledger rows, gate), Connectors (6 honest cards + model status),
Dashboard live data, signup → reload → session restored.
