# Full-System Test Report & Fix Plan — 2026-09-24

Scope: backend API (hostile probes), frontend (live browser walk of all 15 pages),
static hygiene (unused imports, duplication, garbage), git state, and cross-cutting
auth/RBAC. Baseline at start of pass: **105 pytest + 29 subtests green, 57/57 QA
probe, stack healthy** (worker `:8747`, Node-RED ready, Vite `:5173`).

## Verified working (no action needed)

- All 15 pages render in a signed-in session; zero console errors; hash nav + reload
  session restore hold; filters/poll interactions stable (remount fix verified).
- Exactly-once effect journal, hash-chained audit (verified repeatedly incl. under
  concurrency), auth on every endpoint (401 without/with bad token), 413 body cap,
  400/404/413/422 discipline on bad input, traversal + synthetic-contract defenses.
- Webhook triggers: secret checked before any state change (wrong secret → 401, no
  Run row created); rate limiting active.
- Git: only the 3 intended tracked files modified; everything else additive; no
  tracked file deleted; `artifacts/` (incl. token file) properly ignored.

## Bug catalog (with evidence)

### B1 · Legacy mutating routes ignore user roles — HIGH (security)
`require_token` authenticates any valid principal but never checks roles. Probed
live: a user whose role resolves to **observer** successfully ran a workflow
(`POST /api/runs` → 200, real run executed) and created a workflow
(`POST /api/workflows` → 200). Only roadmap routes enforce roles (`admin_guard`,
`teams.role_allows`) — so RBAC is enforced on the new half of the API and absent on
the original half.
**Fix (no behavior change for existing callers):** add a `require_writer` dependency
in `backend/security/tokens.py`: service token → allowed (owner-equivalent, exactly
today's behavior); user token → role must be owner/admin/operator; observer → 403.
Apply it to mutating legacy routes (`POST/PUT` routes in `app.py`). Read routes keep
plain auth. The QA probe and Electron shell use the service token → zero impact.
**Verify:** new tests (observer 403 / operator 200 on each mutating route class +
service token still 200), full suite, 57-check probe.

### B2 · Webhook fire creates a zombie run — HIGH (correctness)
`webhook_fire` creates a `Run(status="running")` but nothing ever executes it — the
run stays `running` forever (no node records) and the response claims "started /
execution proceeds through the normal run path", which is false. Probed: 0 webhook
runs currently exist, so no data damage yet — the trap is live for the first real user.
**Fix:** after secret/enable checks, call the same in-process path `POST /api/runs`
uses (`_start_run_graph` with the bound workflow graph), and create the Run there so
status is managed by the executor. Response returns the real run_id and initial
status. No change to the exactly-once journal path.
**Verify:** integration test: create webhook → fire → run reaches passed/failed with
node records; second fire does not double-claim effects.

### B3 · Schedules & file triggers are stored but never fire — MEDIUM
No scheduler/tick loop exists anywhere; `trigger_type="schedule"` is declared on Run
and the Scheduling page writes triggers, but nothing ever starts a run. File-arrival
triggers likewise have no firing path. Today this is honest-but-inert UI (no lies in
data), yet the feature "opt-in recurring runs" does not actually recur.
**Fix (phase with B2):** one in-process trigger loop on app startup (daemon thread,
bounded every ~30s, single-flight lock):
- `schedule` → extend creation config (kept evidence-gated) with an explicit
  recurrence the user confirms (`time_of_day` + optional `days_of_week`); loop fires
  when due, stamps `last_fired_at`, starts the run through the same path as run-now.
- `file` → fire when the existing folder watcher registers a new settled file
  matching the trigger's filename pattern; dedupe per file+mtime.
- All firings audited (`trigger.fired`), all runs through the normal executor.
**Verify:** fake-clock unit test for due-ness; integration test firing one schedule
run and one file run end-to-end; loop start/stop test.

### B4 · No workflow deletion → permanent junk accumulation — MEDIUM (+ hygiene)
The dev DB holds **338 workflows, ~335 of them junk** (`wf-<hex>` rows written by
test runs directly into the live DB), and the Dashboard honestly displays the
pollution ("Active Automations: 311+"). There is no `DELETE /api/workflows/{id}` at
all, so users could never clean up either.
**Fix:** `DELETE /api/workflows/{id}` (owner/admin only, 404-safe, refuses only when
an in-flight run exists; versions/runs history kept — audit is never destroyed).
One-off dev-DB cleanup: delete `wf-<hex>` rows with zero non-test runs.
**Verify:** deletion test (owner ok, observer 403, unknown 404, has-run kept).

### B5 · Test suite pollutes the persistent dev DB — MEDIUM (root cause of B4's mess)
`test_roadmap.py` fixtures run against the live dev DB (`SessionLocal`/`engine`):
they wrote the ~335 junk workflows, left org tier changes behind, and set retention
45/120 on the real workspace (observed this pass). Tests passing today depend on
order-sensitive pins rather than isolation.
**Fix (do early — it stops new pollution):** per-test **temporary SQLite DB** in the
roadmap/hardening fixtures via `create_engine("sqlite:///...tmp")` +
`Base.metadata.create_all` + session override on `app` (the existing spike tests
already do this pattern). Tests that specifically exercise persistence keep using
the live DB but must clean up their rows in teardown.
**Verify:** run suite twice; assert dev DB workflow count unchanged before/after.

### B6 · Retention accepts booleans as day counts — LOW (hardening)
`observations_days: true` passes `isinstance(v, int)` (bool subclasses int). Tier
gating currently blocks reaching it on solo, so it is latent.
**Fix:** one line — `isinstance(v, bool) or not isinstance(v, int)` → 422. Also
explicitly reject float. **Verify:** parametrized bad-type test.

### B7 · Webhook rate-limiter memory grows before auth — LOW
`_WEBHOOK_HITS.setdefault(trigger_id, ...)` runs **before** the secret check, so
unauthenticated requests can create unbounded dict keys (memory-growth vector).
**Fix:** look up the trigger and verify the secret **first** (a DB hit that fails
closed); only then touch the limiter; also cap the dict (e.g., evict keys idle >5min).
**Verify:** test that unknown trigger ids leave no limiter state.

## Cleanliness catalog (codebase organization)

- **C1 · Duplicated UI primitives:** `Card`/`Row`/`Gate` defined twice
  (`roadmap-pages.jsx`, `roadmap-complete.jsx`). → Extract to `main-shared.jsx`
  (single source), import in both; delete the copies. Behavior-identical.
- **C2 · `__import__("json")` hack** in `orchestration.create_trigger` and a local
  `import uuid` inside `webhook_fire`. → Normal top-level imports (`json`, `uuid`).
- **C3 · Unused imports:** `app.py` → `_io`, `resolve_resource`, `RESOURCE_DIRS`;
  `orchestration.py` → `timedelta`; `engine/rows.py` → `eval_text`;
  `nodebridge/flow_compiler.py` → `CATALOG`. (6 names, 4 files — verified unused.)
- **C4 · Stale copy:** Settings still says "Deletion controls land with the Data &
  Privacy page" — that page now exists. → Point to it.
- **C5 · Minor duplication (note only):** `now_iso()` defined in both `identity.py`
  and `app.py`. Acceptable module independence; consolidate opportunistically, not
  worth churn now.

## Execution plan (each phase ends green: full pytest + 57-check probe + build)

| Phase | Items | Why this order |
|---|---|---|
| **1. Stop the bleeding** | B5 test isolation, B6 bool guard, B7 limiter order, C2–C4 cleanups | No API/UX contract changes at all; prevents further pollution while we work |
| **2. Guard the doors** | B1 `require_writer` on legacy mutating routes + regression tests | Pure tightening: service-token callers (probe, Electron) unchanged |
| **3. Make triggers real** | B2 webhook executes properly, B3 trigger loop (schedule + file), B4 delete endpoint + dev-DB cleanup | New executor paths land last, on a clean, guarded base |
| **4. UI consolidation** | C1 shared primitives | Touches rendering only after backend is stable |
| **5. Final sweep** | Re-run everything; refresh `docs/spike-evidence.md`, roadmap status markers | Proof over promises |

**Non-negotiables throughout:** additive diffs only (git additive guarantee
re-verified at the end); service-token behavior byte-compatible; exactly-once
journal untouched; audit ledger append-only; every deletion reference-checked first;
no fabricated values anywhere.

## Risk notes

- B1 is the only change that can surprise an existing caller — mitigated because
  every current caller (QA probe, Node-RED bridge, Electron, tests) authenticates as
  the service principal, which keeps owner rights.
- B3's loop is the largest new surface; it stays behind an enable flag per trigger
  (already exists) and reuses the run-now executor, so no new effect path is created.

## QA round 6 — production-readiness pass (2026-09-25)

Full re-inspection of the shipped tree with a dedicated hunt for defects the
round-5 suites could not see. Findings, all fixed with armor tests in
`tests/spike/test_hardening_round6.py`:

| # | Defect | Root cause | Severity | Fix |
|---|--------|-----------|----------|-----|
| R6-1 | `teams.workflow_process_map` returned raw JSON strings | `_json` name existed only inside the sibling function; `except Exception` swallowed the NameError | medium | module-level `json` import; roundtrip armor test |
| R6-2 | `/api/compare/run` never ran its promised oracle check | `expected_matches` computed then discarded; docstring lied | medium | fail-closed oracle gate (503 + audit on disagreement) |
| R6-3 | `POST /api/triggers/tick` open to any authenticated principal | route used `require_principal` (authN only) | high | `require_writer`; observer 403 test |
| R6-4 | Six org/capability GET routes served data with no token | dependencies missing (`/api/team/members` leaked the full roster) | high | `require_principal` on all six; negative + positive tests |
| R6-5 | Caller-caused node data failures returned HTTP 500 | `_is_client_error` only knew `InvalidFixture`; `rows.py` raised bare `ValueError`s | medium | `ClientDataError` (ValueError subclass) raised at all five data-contract sites; run route maps chain to 400 |
| R6-6 | Hot filter columns unindexed | schema had PKs/uniques only | low (spike scale) | 9 idempotent `CREATE INDEX IF NOT EXISTS` at startup, additive to model layer later |
| R6-7 | Dev DB held 365 historical test-junk workflows | pre-isolation test rounds | low (demo honesty) | `scripts/cleanup_dev_junk.py` (dry-run default, soft-delete only, history kept); 368 → 3 real workflows |
| R6-8 | Budgets script penalized cold-start poll | single first-call measurement | low | warmup call before timing |

Behavioral battery (`scripts/scenario_battery.py`, 31 checks against the LIVE
server): happy path + idempotent rerun, failure path (400 + failed run + failing
node recorded), cancel semantics, invalid inputs, 6-way concurrent exactly-once,
webhook auth/fire, schedule tick + once-per-day stamp, RBAC edges, audit chain
`verify=1` — all passing; battery self-cleans its workflows.

False alarms investigated and retracted: "Next button jumps to dashboard" (test
harness DOM-shift artifact, stepper is correct), "fresh user can run workflows"
(documented local-first design: registration joins the single org as operator).

## QA round 7 — authorization audit (2026-09-25)

Full authorization sweep: all 85 routes mapped to their guards, one real account
per role (observer/operator/approver/owner) created against the LIVE server, and
every protected endpoint exercised with each role via
`scripts/authz_matrix.py` (147 checks, all passing after fixes).

| # | Defect | Root cause | Severity | Fix |
|---|--------|-----------|----------|-----|
| R7-1 | Operator could test/activate automations via legacy routes (`/api/test-jobs`, `/api/approvals/activation`) | routes used `require_writer`; product model says test/activate = approver | high | `require_tester` (new guard, `test` permission = approver) |
| R7-2 | Approver could publish to the registry via the legacy route | same tier mismatch (publish = owner) | high | `require_publisher` (new guard, `publish` permission = owner) |
| R7-3 | Node-callback effect routes accepted any authenticated user (`require_token`) — an observer could drive row updates/drafts/run-completion directly | bridge callbacks and user tokens shared one guard | high | `require_writer` on `/api/nodes/*` and `/api/runs/{id}/complete`; Node-RED bridge (service token) unaffected |
| R7-4 | Saving a workflow into a soft-deleted id returned 200 but silently did nothing | `save_workflow` didn't check `deleted_at`; also let non-owners bypass the owner-only delete gate by id reuse | medium | 409 with `how_to_unlock` hint; regression test |
| R7-5 | `/api/org/sso` served tier capability info without a token | missing dependency | low | `require_principal` |
| R7-6 | `notifications/read-all` docstring claimed "owner+ only" but the notifications model is org-global | stale docstring | low | docstring corrected to actual behavior |

Escalation/IDOR/lifecycle checks (all passing live): observer/operator cannot
self-elevate or add members; register ignores injected `is_admin`/`role` fields;
forged users land as operator; cross-user token revocation is 404 (ownership
enforced in `identity.revoke_token`); revoked tokens die immediately; tampered
and garbage tokens 401; anonymous requests 401 on every sensitive route;
workflow delete remains owner-only (delete is a one-way gate).
