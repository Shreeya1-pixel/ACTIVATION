# AutoStack

> **NOVA 2026 · BITS Pilani Dubai · Track C (AI Engineering) · Theme: Open Innovation · Team Activation**
>
> **AutoStack finds the work your office repeats, writes the automation code for it, tests that code in a sandbox and repairs it until it passes, dry-runs it on your data, and puts it live only after a person approves.**
>
> Other tools wait for you to design an automation. AutoStack watches the spreadsheets you already use, works out what can be automated, generates the code, tests it in a sandbox, feeds any failure back to the AI to fix, previews exactly what it would change, and only then runs it for real. Every step goes into a tamper-evident audit log.

**Demo video:** [Google Drive](https://drive.google.com/file/d/11lU6d4mTxDCkl8erF6AZy_DYP-136ZwN/view?usp=drivesdk)

| At a glance | |
|---|---|
| The loop | **Identify → Generate → Test & self-repair → Dry run → Go live**, end to end in one app |
| Detection accuracy | **Precision 1.00 / recall 1.00** on 500 synthetic workspaces (982 planted patterns, 983 near-misses); **0.97 / 0.999** when 15% of steps are interrupted |
| Automated tests | **197 pass**, 2 skipped, 29 subtests (25 test files) |
| Live-stack checks | **250 pass**: 54/54 end-to-end · 31/31 scenario battery · 165/165 authorization matrix |
| Code | 7,422 lines of backend Python · 6,240 lines of frontend · 4,286 lines of tests |
| API | 99 routes · 28 database tables · 7 workflow node types |
| Footprint (measured on Windows) | 15.1 ms per capture poll · 0.47% idle CPU · 98.5 MiB RAM |
| Try it | Clone to a detected pattern in **about 5 minutes**, no API key needed |

---

## 1. The problem

Small offices run on spreadsheets: vendor follow-ups, invoice status, weekly wage collation, payment reminders. Staff make the same edits in the same order every week, by hand. They rarely have time to stop, map that work out and build an automation for it, so it never gets automated.

- **SMEs are 94.4% of UAE companies** and produce **63.5% of non-oil GDP** (Central Bank of the UAE annual report 2022, via Gulf Today, May 2024). The UAE aims to grow from about 557,000 SMEs to **1 million by 2030**.
- **Manual entry is expensive.** In a survey of 500 US professionals, employees reported spending **9+ hours a week** on manual data entry (Parseur / QuestionPro, July 2025).
- **Manual mistakes are real risk.** In April 2024 a manual-entry slip at Citi credited a client account with **$81 trillion** instead of $280. Two reviewers missed it; it was caught after 90 minutes and reversed, and no money left the bank (Financial Times, February 2025).
- **The rules are tightening.** UAE B2B e-invoicing becomes mandatory on **1 January 2027** for businesses with revenue of AED 50M or more, and on **1 July 2027** for smaller businesses (Ministerial Decision 244 of 2025; Decision 66 of 2026 moved only the large-business deadline for appointing a service provider, to 30 October 2026). The Ministry of Finance states that PDF, Word, scanned and emailed invoices are not e-invoices. Late corporate-tax registration already carries an **AED 10,000** penalty (Cabinet Decision 10 of 2024). Offices need back-office steps that are consistent and traceable.

**The gap:** automation tools assume you already know what to automate and can build it safely. Small offices usually don't know where to start, and they can't afford an automation that silently does the wrong thing.

## 2. The AutoStack loop

AutoStack closes the whole loop, from noticing the work to running it safely:

```
 1. IDENTIFY          2. GENERATE           3. TEST & REPAIR     4. DRY RUN            5. GO LIVE
 Watch the sheets  →  AI writes the     →  Static checks +   →  Preview every row  →  Approved runs on a
 you already use,     automation code      sandboxed run;       it would change,      schedule, file change
 find repeated        from the detected    failures go back     change nothing        or webhook, fully
 edit sequences       pattern              to the AI to fix                           audited, reversible
                                          └── a person approves the tested code before steps 4 and 5 ──┘
```

| Step | What happens | How it is built | Proof in the repo |
|---|---|---|---|
| **1. Identify** | Point AutoStack at any folder of CSV or Excel files. It compares every save row by row and finds the same ordered edits repeated **3+ times across 2+ records**. Reformatting a date or amount is ignored. Routines interrupted by a coffee break are stitched back together. | Per-record instances with a 10-minute gap rule, 45-minute stitching when the joined routine itself repeats, fragment folding, value normalisation; you pick the ID column and the columns that matter | `backend/detection/sequences.py`; benchmark precision/recall 1.00 on clean data; sample replay detects 2 real patterns and rejects 2 near-misses |
| **2. Generate** | AI turns the detected pattern into a structured plan, then into runnable Python code (`run(rows, ctx)`). Personal data is tokenised before any external AI call. | Gemini or a deterministic offline mock; plan validation; code hashed with SHA-256 | `backend/engine/generation.py`, `backend/engine/ai.py` |
| **3. Test & self-repair** | The generated code is statically checked (allowlist, banned constructs, size cap), then executed in a hardened sandbox and compared with an independent oracle computed from the plan. **Any failure (forbidden import, crash, wrong rows) is turned into specific feedback and sent back to the AI, which rewrites the code: up to 3 attempts.** Every attempt is kept and audited; superseded or failing versions can never be tested or activated. | Fresh subprocess, sockets blocked, builtins stripped, CPU and memory limits, wall-clock kill; `generate_with_repair` loop | `backend/engine/generation.py`, `backend/engine/runner.py`; 9 self-repair tests |
| **4. Dry run** | Before a live run, preview exactly which rows would be updated and which messages drafted. **Nothing is written.** A preflight check also confirms every file and column the automation needs still exists. | `dry_run: true` on runs; preflight on every run | *Dry run* button on the Workflows page; `test_dry_run_computes_but_does_not_apply`; 4 preflight tests |
| **5. Go live** | Only after a person approves that exact code and its passing test does it run, on a schedule, a file change, a webhook or on demand. | Exactly-once journal, idempotent steps, cancel and rollback, SHA-256 hash-chained audit log | 31/31 scenario battery; *Verify chain* on the Trust Log page |

**Why this matters:** each step catches a different failure. Identification keeps you from automating noise. The sandbox catches broken code, and self-repair fixes it without a developer. The dry run catches "right code, wrong rows". Approval keeps a person accountable. The audit log proves what happened afterwards.

---

## 3. Quick start (about 5 minutes)

Everything here uses **sample data**: invented UAE-style companies, fake TRNs and trade licence numbers, and `.example` email addresses. No real business data is included, and no API key is needed.

**Prerequisites:** Python 3.11+ and Node.js 18+.

```bash
git clone https://github.com/allurimohansrisaivarma-coder/autostack-in.git
cd autostack-in

python -m venv .venv
# macOS / Linux
.venv/bin/pip install -r requirements.txt
# Windows
.venv\Scripts\pip install -r requirements.txt

cd frontend && npm install && cd ..
```

**Step 1: load the sample workspace (30 seconds).**

```bash
.venv/bin/python scripts/load_demo.py        # Windows: .venv\Scripts\python scripts\load_demo.py
```

Expected output:

```
DETECTED  9 instances / 3 records  watched/sample_vendor_followups: ... TRN Check ... Payment Requested On
DETECTED  6 instances / 2 records  watched/sample_payroll_collation: ... Net Pay (AED) ... Status
not yet   3 instances / 1 records  watched/sample_vendor_followups: Remarks -> Amount (AED)
not yet   2 instances / 2 records  watched/sample_invoice_status: Last Reminder On -> Notes
```

**Step 2: start the app.**

```bash
.venv/bin/python scripts/run_worker.py       # terminal 1, worker on :8747
cd frontend && npm run dev                   # terminal 2, UI on :5173
```

**Step 3: click through.** Open http://localhost:5173 and register (the first user becomes owner).

This walks the whole loop in order:

1. **Identify:** open **Discovery**. Two detected patterns appear with their evidence (how many times, which records, the exact steps). The two near-misses are listed as "observed" and not suggested.
2. **Generate:** open **Create Automation**, pick a pattern and generate the plan and code.
3. **Test:** run the sandbox test and watch it pass the static checks and the sandboxed run.
4. **Approve:** approve the tested artifact. It becomes a workflow.
5. **Dry run:** on **Workflows**, choose **Dry run (preview, changes nothing)** to see exactly which rows would change.
6. **Go live:** choose **Run now**, then open **Trust Log** and choose *Verify chain* to check the audit trail.

To skip the CLI, use the **Load sample workspace** button on the Create Automation page instead.

**Use your own files:** in *Create Automation → Capture settings*, set any folder, pick the ID column for each file and tick the columns that matter. CSV and `.xlsx` are both supported.

### What the sample data proves

| Sample sheet | Rows | Designed behaviour | Result |
|---|---|---|---|
| `sample_vendor_followups.csv` | 21 | Invoice received → TRN check → payment requested, done 4 weeks running for 3 vendors | **Detected** (9 completed instances, 3 vendors) |
| `sample_payroll_collation.csv` | 18 | Weekly wage collation for 2 contract workers | **Detected** (6 instances, 2 employees) |
| Same vendor sheet, VND-1071 | – | Repeats, but only ever for **one** vendor | **Not suggested**: fails the 2-record rule |
| `sample_invoice_status.csv` | 16 | Reminders for 2 clients, only **twice** each | **Not suggested**: fails the 3-occurrence rule |
| Same vendor sheet, VND-1050 | – | Date and amount retyped in a different format | **0 events**: normalisation ignores it |

The sheets are deliberately messy: blank rows, rows with no ID, mixed date formats (`05/09/2026`, `5 Sep 2026`, `2026-09-05`, `05-09-26`) and mixed amounts (`AED 48,500.00`, `12600`, `3,250`).

---

## 4. What makes it different

1. **It tells you what to automate.** Zapier, Make, n8n and Power Automate start from a blank canvas: someone has to know what to build. AutoStack starts from how people actually work and proposes automations with evidence attached: how many times, for which records, in what order.
2. **It writes the automation for you, and fixes its own mistakes.** The detected pattern becomes a plan and then runnable code automatically. If the code fails the sandbox, the exact failure goes back to the AI and it tries again. There is no flow-builder to learn and no developer needed.
3. **It proves the automation before trusting it.** Generated code must pass static checks and a sandboxed run, and a dry run shows its real effect on your data, before anyone can switch it on. Most tools only find out an automation is wrong after it has run.
4. **A person stays accountable.** Approval is bound to the exact code (by SHA-256) and its passing test. Change the code and it must be tested and approved again.
5. **Safe to share between offices.** Approved automations can be published to a registry as Ed25519-signed templates with permissions derived from what they actually do. Imports arrive untrusted and must re-pass the sandbox locally. Templates can be withdrawn or revoked.
6. **Private by default.** Everything runs on the office PC. With the offline AI mode nothing leaves the machine; with Gemini, personal data is tokenised first and restored locally.

## 5. How it is built

| Area | Implementation | Evidence |
|---|---|---|
| Detection | Per-record instances with a 10-minute gap split, 45-minute stitching of interrupted routines (only when the joined routine itself meets the rule), fragment folding. Trailing open instances are not counted. Needs 3+ occurrences across 2+ records. Step labels include the changed fields | `backend/detection/sequences.py`, benchmark below, 6 quality tests |
| Self-repairing generation | Static and sandbox failures converted to model-readable feedback (`report_problems`), previous code and feedback sent back, capped at 3 attempts, every version preserved and audited | `backend/engine/generation.py`, 9 tests |
| Capture | Any ID column with a duplicate-ID check. Per-file column selection. CSV and XLSX (zip-bomb checked). Configurable folder, with system and home roots blocked | `backend/capture/`, 12 tests |
| Sandbox | Static allowlist, banned constructs, 20 KB cap. Fresh subprocess with sockets blocked, builtins stripped, rlimits probed per OS, wall-clock kill | `backend/engine/runner.py` |
| Reliability | Exactly-once journal, idempotent steps, dry run, cancel, rollback. Preflight check before any effect | `backend/engine/`, scenario battery 31/31 |
| Security | PBKDF2 (200k iterations), hashed bearer tokens, login lockout. 4-role RBAC enforced on every route. Constant-time webhook secrets, rate limits | authz matrix 165/165 |
| Audit | SHA-256 hash chain, `GET /api/audit?verify=1`, SIEM stream, compliance bundle | Trust Log page |
| Registry | Ed25519 signatures over a manifest (graph SHA-256, scopes, connectors). Trusted-signer list. 409 on tamper, 403 on missing scopes, revocation | `backend/security/signing.py`, 8 tests |
| PII | Tokenised before Gemini. Keyed HMAC pseudonyms in the event log. Detects Emirates ID, UAE TRN, IBAN, UAE mobile numbers, email, plus common tax and national ID formats | `backend/security/pii.py` |

### Detection benchmark

`python scripts/benchmark_detection.py` builds 500 synthetic workspaces with known answers: real routines, near-misses (repeated only twice, or only ever on one record), one-off noise edits, several records worked on the same day, and events arriving out of order. It then scores the detector. Results are saved to `docs/detection-benchmark.json`.

| Scenario | Planted patterns | Near-misses | Precision | Recall | False alarms |
|---|---|---|---|---|---|
| Clean timing | 982 | 983 | **1.00** | **1.00** | 0 |
| 5% of steps interrupted (11–25 min pause) | 980 | 1,000 | **1.00** | **1.00** | 0 |
| 15% of steps interrupted | 988 | 1,015 | **0.97** | **0.999** | 30 |

Before stitching was added, the 15% scenario scored precision 0.56 and recall 0.93, because interrupted routines split into fragments that looked like patterns. The benchmark found that weakness, and stitching fixed it. Speed: about 3–4 ms per 1,000 events. This measures the implementation against its rule under messy timing; accuracy on a specific office's data will depend on how that office works.

## 6. Impact and viability

**Evidence the problem is real:**

> "Retailers continue to manage inventory, reconciliation, and reporting through custom-built Excel sheets. This is not due to a lack of awareness or access to alternatives, but rather because many existing tools fail to align with how these businesses actually operate. Each business had developed its own customised Excel workflows, tailored precisely to its operations."
> **Ahmed Sameh, CMO, Fortis**, on research with 130+ UAE SMEs ([MENAFN, April 2026](https://menafn.com/1111035482/Despite-the-AED-543B-digital-push-64-of-UAE-SMEs-run-core-operations-on-Excel))

- **64% of UAE SMEs run core operations on Excel**, more than use accounting systems (51%) or POS systems (34%) (Fortis, April 2026). AutoStack is built for exactly this: it learns each office's own spreadsheet routine instead of replacing it with a new tool.
- **First-hand case: TÜV Rheinland factory audits.** A member of Team Activation automated factory-audit report preparation for TÜV Rheinland work: reading a factory's document folder and master list, matching documents to the audit checklist and filling the report template. Each run matched **47 checklist items across 19 audit sections and placed 12 photos** automatically, work normally done by hand for every factory. It took about 8,300 lines of custom code, written by a developer. AutoStack exists so the next office doesn't need a developer to get the same result.

**Who it's for:** offices of 2 to 50 people whose work already lives in spreadsheets, such as trading companies, clinics, facility services, logistics and accounting firms.

**Illustrative savings (conservative, with the maths shown):**

| Input | Value | Basis |
|---|---|---|
| Admin salary | AED 6,000 / month | **Assumption.** Typical UAE admin or accounts clerk; replace with your own figure |
| Working hours | 48 h / week | UAE private-sector maximum |
| Hourly cost | ≈ AED 29 | 6,000 × 12 ÷ (48 × 52) |
| Hours saved | **3 h / week** | A third of the 9 h/week reported in Parseur's US survey, for margin |
| **Saving per employee** | **≈ AED 4,150 / year** | 3 × 29 × 48 working weeks |
| **5-person back office** | **≈ AED 20,700 / year** | Before counting fewer errors or late-filing penalties |

**Why it's viable:**

- **Zero setup cost:** it runs on hardware the office already owns (measured on Windows at under 100 MiB RAM and under 1% idle CPU).
- **Zero running cost:** no per-task fees, and the offline AI mode means no AI bill at all.
- **Zero automation expertise needed:** the office doesn't design anything; it reviews and approves what AutoStack proposes.
- **Built for what's coming:** consistent, audited back-office steps make the 2027 e-invoicing switch easier, because the data is already clean and traceable.

**Path to adoption:**

| Stage | What happens |
|---|---|
| Week 1 | Install locally, point AutoStack at the team's shared folder, let it observe |
| Weeks 2–4 | First patterns appear; the team approves the ones it trusts |
| Month 2+ | Approved automations run on schedule; templates are shared between branches through the signed registry |
| Next | Pilot with 3 UAE small offices (Dec to Feb) to replace illustrative savings with measured hours |

---

## 7. Scope: what's done and what's next

### Done and tested

| Loop step | Status |
|---|---|
| Identify | Any folder, CSV and `.xlsx`, any ID column, per-file column choice, duplicate-ID check; detection with evidence and near-miss rejection |
| Generate | AI plan and code generation (Gemini or offline mock) with PII tokenisation |
| Test & self-repair | Static checks + hardened sandbox + automatic repair loop (3 attempts); failing code can never be activated |
| Dry run | Preview from the Workflows page; preflight on every run with hand-back to a person |
| Go live | Manual, schedule, file-change and webhook triggers; exactly-once, rollback, verifiable audit chain |
| Around the loop | Signed registry, 4-role access control, privacy ledger, retention windows, SIEM export, sample workspace |

### Next (clearly scoped)

| Item | Current state | Next step |
|---|---|---|
| Generated runtimes for any sheet shape | Detection works on any sheet; generated runtimes currently cover follow-up and status-update workflows | Generalise the runtime to any detected schema (by 14 Nov) |
| Counting the latest occurrence | The most recent occurrence per record counts once it completes, so a pattern is suggested one repeat later | Deliberate, to avoid suggesting half-finished work |
| Browser capture | Prototype extension; folder watching is the supported path | Harden the extension |
| Cloud demo | Frontend and backend deploy to Railway (Dockerfiles and `railway.json` included, container build smoke-tested) | Folder capture in the cloud watches the server's volume; for your own files, run the worker locally |
| PII detection | Pattern and field-name based | Add name detection for free text |
| Measured impact | Savings are illustrative | Pilots with 3 UAE small offices |

---

## 8. How it compares

| | Zapier / Make | n8n | UiPath / Power Automate | **AutoStack** |
|---|---|---|---|---|
| Finds what to automate | No | No | Task mining (enterprise add-on) | **Yes, from spreadsheet edits** |
| Data stays on the machine | No (cloud) | Yes, if self-hosted | Mostly (desktop robots) | **Yes, by default** |
| AI output tested before it runs | No | No | Partly | **Sandbox run required** |
| Human approval bound to the artifact | Optional | Optional | Optional | **Required** |
| Tamper-evident audit log | Paid tiers | Limited | Yes | **Hash-chained, verifiable** |
| Signed, scoped sharing between offices | No | No | Orchestrator governance | **Ed25519 + derived scopes** |
| Pricing model | Per task | Free community edition / cloud plans | Per robot or user | **No per-task fees** |

Competitor features and pricing change often; check vendor sites before relying on this table.

---

## 9. Architecture and stack

```
Browser (React 19 + Vite, :5173)
   │  bearer token, live polling
   ▼
Worker (FastAPI, :8747) ──► SQLite (WAL): workflows, runs, events, candidates, audit chain
   │  capture → detect → plan → generate → sandbox → approve → run
   ▼
Node-RED (optional, :18790) ──► calls back per step (read-due / update-row / draft-create / notify)
```

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, CSS design tokens, Motion |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, SQLite (WAL), APScheduler |
| Files | csv, openpyxl (read-only, `data_only`, zip-bomb checked) |
| AI | Google Gemini (optional) or deterministic offline mock |
| Security | PBKDF2-HMAC, hashed tokens, subprocess sandbox, SHA-256 audit chain, Ed25519 (`cryptography`), PII tokenisation |
| Desktop | Electron shell (optional) |

### Roles

| Role | Can |
|---|---|
| Observer | Read |
| Operator | Run workflows, stage events, load sample data |
| Approver | Sandbox-test and activate automations |
| Owner | Publish to the registry, change the capture folder, manage members and triggers |

The first registered user becomes owner; later users join as operators.

### Registry supply chain

- **Signed:** each version carries an Ed25519 signature over its slug, version, title, graph SHA-256, connectors and scopes. The office key is a 0600 file in the data directory.
- **Tamper-evident:** on import the hash, scopes and signature are re-verified. Any mismatch returns 409 and is audited as `registry.import_refused`.
- **Scoped:** scopes (`read-content`, `write-target`, `draft-create`, `notify`, `connector`) come from the node catalog. An import is refused (403) unless every scope is granted.
- **Trusted signers:** this office's key plus keys listed in `AUTOSTACK_TRUSTED_SIGNERS`.
- **Untrusted by default:** imports arrive as drafts that must pass local sandbox tests and approval.
- **Withdraw vs revoke:** withdrawing stops new installs. Revoking (reason required) also marks installed copies revoked and blocks their run reports.

### PII handling

- **External AI:** names, emails, phones, addresses, Emirates IDs, TRNs, IBANs and other ID fields become `⟦P1⟧`-style tokens before a Gemini call and are restored locally.
- **Event log:** identifiers in record keys are stored as keyed pseudonyms such as `[EMAIL:1a2b3c4d]`, so detection can still tell records apart without storing the value.

---

## 10. Testing

```bash
.venv/bin/python -m pytest tests/ -q                # 197 passed, 2 skipped, 29 subtests
.venv/bin/python scripts/benchmark_detection.py     # precision / recall on 500 synthetic workspaces
# with the worker running:
.venv/bin/python scripts/qa_probe.py                # 54 end-to-end checks
.venv/bin/python scripts/scenario_battery.py        # 31 behaviour checks
.venv/bin/python scripts/authz_matrix.py            # 165 authorization checks
cd frontend && npm run build
```

| Suite | Covers | Last result |
|---|---|---|
| pytest | Lifecycle, detection quality and stitching, self-repairing generation, generic capture, XLSX, sample replay, RBAC, sandbox, triggers, registry signing and revocation, preflight, dry run, PII, privacy, retention | 197 pass / 2 skip |
| benchmark_detection | 500 synthetic workspaces × 3 timing scenarios | P/R 1.00 clean |
| qa_probe | Full live stack end to end | 54 / 54 |
| scenario_battery | Concurrency, failure paths, webhook, schedule, RBAC edges | 31 / 31 |
| authz_matrix | Every protected endpoint, IDOR, escalation, token lifecycle | 165 / 165 |
| Frontend build | Production Vite bundle | Pass |

Tested on macOS (Python 3.14) and Windows (Python 3.13). Resource budgets were measured on Windows (`docs/budgets.json`).

---

## 11. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AUTOSTACK_TOKEN` | auto-generated | Service bearer token |
| `AUTOSTACK_AI_PROVIDER` | `mock` | `mock` (offline) or `gemini` |
| `AUTOSTACK_GEMINI_KEY` | unset | Only needed for `gemini` |
| `AUTOSTACK_TRUSTED_SIGNERS` | unset | Comma-separated base64 Ed25519 public keys of other trusted offices |

Copy `.env.example` to `.env`. Never commit `.env`.

## 12. Repository layout

```
backend/
  app.py, roadmap_routes.py   API routes
  capture/                    sheets.py (CSV/XLSX), watcher.py, config.py, ingest.py
  detection/                  sequences.py (rule), service.py (candidates)
  engine/                     runner (sandbox), journal, rollback, preflight, ai
  security/                   auth, RBAC, signing.py (Ed25519), pii.py
  demo.py                     sample-workspace replay
demo_data/                    SAMPLE DATA: 3 messy sheets + timeline.json
frontend/src/                 React UI (create-automation, capture-settings, screens)
scripts/                      run_worker, load_demo, qa_probe, scenario_battery, authz_matrix
tests/                        pytest (isolated databases)
docs/                         contracts, roadmap, budgets, test reports
```

## 13. Deployment (Railway)

Both services deploy from this repo. The container builds were smoke-tested locally: health check, frontend, CORS, sample loader and code generation with self-check.

**Backend service**
- Root directory: repo root. Uses `railway.json` → `deploy/Dockerfile.worker` (starts the API and the trigger loop).
- Add a volume mounted at `/data` (database, audit chain, signing key survive redeploys).
- Variables: `ALLOWED_ORIGINS=https://<frontend>.up.railway.app`, `RAILWAY_RUN_UID=0`, optionally `AUTOSTACK_TOKEN`, `AUTOSTACK_AI_PROVIDER`, `AUTOSTACK_GEMINI_KEY`.

**Frontend service**
- Root directory: `frontend`. Uses `frontend/railway.json` → `frontend/Dockerfile` (Vite build served by nginx on `$PORT`).
- Variable (used at build time): `VITE_API_BASE=https://<backend>.up.railway.app`.

**Local Docker**

```bash
docker build -f deploy/Dockerfile.worker -t autostack-backend .
docker build --build-arg VITE_API_BASE=http://localhost:8747 -t autostack-frontend frontend
docker run -p 8747:8747 -v autostack-data:/data --user 0 autostack-backend
docker run -p 8080:8080 autostack-frontend
```

## 14. Roadmap

- Generate runtime workflows from any detected sheet schema, not just the built-in contract.
- An e-invoicing export step that prepares structured invoice data for an accredited service provider.
- Outbound HTTP connector, keyring-backed secrets, multi-machine sync.
- A browser extension capture path, moved from prototype to supported.

## Team

**Team Activation**, NOVA 2026, BITS Pilani Dubai, Track C: AI Engineering.

## License

Submitted to NOVA 2026. All rights reserved by Team Activation.

| More docs | |
|---|---|
| [docs/contracts.md](docs/contracts.md) | Event, plan and artifact contracts |
| [docs/product-roadmap.md](docs/product-roadmap.md) | Full roadmap |
| [docs/test-report-and-fix-plan.md](docs/test-report-and-fix-plan.md) | QA rounds: bugs, root causes, fixes |
| [docs/platform-matrix.md](docs/platform-matrix.md) | OS and runtime matrix |
