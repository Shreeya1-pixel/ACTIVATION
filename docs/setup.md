# Setup, configuration and deployment

## Quick start in full

Everything here uses **sample data**: invented UAE-style companies, fake TRNs and trade licence numbers, and `.example` email addresses. No real business data is included, and no API key is needed.

**Prerequisites:** Python 3.11+ and Node.js 18+.

```bash
git clone https://github.com/Shreeya1-pixel/ACTIVATION.git
cd ACTIVATION

python -m venv .venv
# macOS / Linux
.venv/bin/pip install -r requirements.txt
# Windows
.venv\Scripts\pip install -r requirements.txt

cd frontend && npm install && cd ..
```

**Fastest proof: Try it live (no sample data, about 3 minutes).** Start the app (Step 2 below), register, and open **Product → Try it live**:

1. **Start practice workspace.** A real folder with one invoice sheet and no history. **Open in Excel** opens it, or edit it in the page.
2. **Do your normal work** on 3 invoices: set *Status* to *Approved* and *Checked By* to your initials, save; set *Payment Requested* to *Yes*, save; click **Done**. The log shows each change AutoStack captured from the saved file.
3. **Identified:** a card shows the routine it found, in plain words, with the rows it saw it on.
4. **⚡ Automate this:** an IDE-style view shows the pipeline live. Files appear as they are written, the code types in, the sandbox runs on a copy of your sheet, and (with *broken draft* ticked) a failing first version is caught and repaired by the AI.
5. **Approve**, then read `dry_run.diff` (every change, nothing written), then **Go live**. The rows change in the real file; **Undo this run** puts them back.

The *Done* button closes a routine immediately; in normal use detection waits for 10 quiet minutes instead.

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

## What the sample data proves

| Sample sheet | Rows | Designed behaviour | Result |
|---|---|---|---|
| `sample_vendor_followups.csv` | 21 | Invoice received → TRN check → payment requested, done 4 weeks running for 3 vendors | **Detected** (9 completed instances, 3 vendors) |
| `sample_payroll_collation.csv` | 18 | Weekly wage collation for 2 contract workers | **Detected** (6 instances, 2 employees) |
| Same vendor sheet, VND-1071 | – | Repeats, but only ever for **one** vendor | **Not suggested**: fails the 2-record rule |
| `sample_invoice_status.csv` | 16 | Reminders for 2 clients, only **twice** each | **Not suggested**: fails the 3-occurrence rule |
| Same vendor sheet, VND-1050 | – | Date and amount retyped in a different format | **0 events**: normalisation ignores it |

The sheets are deliberately messy: blank rows, rows with no ID, mixed date formats (`05/09/2026`, `5 Sep 2026`, `2026-09-05`, `05-09-26`) and mixed amounts (`AED 48,500.00`, `12600`, `3,250`).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AUTOSTACK_TOKEN` | auto-generated | Service bearer token |
| `AUTOSTACK_AI_PROVIDER` | `mock` | `mock` (offline) or `gemini` |
| `AUTOSTACK_GEMINI_KEY` | unset | Only needed for `gemini` |
| `AUTOSTACK_TRUSTED_SIGNERS` | unset | Comma-separated base64 Ed25519 public keys of other trusted offices |

Copy `.env.example` to `.env`. Never commit `.env`.
| `AUTOSTACK_GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model used when the provider is `gemini` |

## Repository layout

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

## Deployment (Railway)

Both services deploy from this repo. The container builds were smoke-tested locally: health check, frontend, CORS, sample loader and code generation with self-check.

**Backend service**
- Root directory: repo root. Uses `railway.json` → `deploy/Dockerfile.worker` (starts the API and the trigger loop).
- Add a volume mounted at `/data` (database, audit chain, signing key survive redeploys).
- Variables: `ALLOWED_ORIGINS=https://<frontend>.up.railway.app`, `RAILWAY_RUN_UID=0`, optionally `AUTOSTACK_TOKEN`, `AUTOSTACK_AI_PROVIDER`, `AUTOSTACK_GEMINI_KEY`, `AUTOSTACK_GEMINI_MODEL` (default `gemini-2.5-flash`).

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

[← Back to README](../README.md)
