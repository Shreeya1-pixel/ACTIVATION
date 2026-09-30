# Testing

```bash
.venv/bin/python -m pytest tests/ -q                # 203 passed, 2 skipped, 29 subtests
.venv/bin/python scripts/benchmark_detection.py     # precision / recall on 500 synthetic workspaces
# with the worker running:
.venv/bin/python scripts/qa_probe.py                # 54 end-to-end checks
.venv/bin/python scripts/scenario_battery.py        # 31 behaviour checks
.venv/bin/python scripts/authz_matrix.py            # 165 authorization checks
cd frontend && npm run build
```

| Suite | Covers | Last result |
|---|---|---|
| pytest | Lifecycle, detection quality and stitching, self-repairing generation, generic capture, XLSX, sample replay, RBAC, sandbox, triggers, registry signing and revocation, preflight, dry run, PII, privacy, retention, practice workspace end to end | 203 pass / 2 skip |
| benchmark_detection | 500 synthetic workspaces × 3 timing scenarios | P/R 1.00 clean |
| qa_probe | Full live stack end to end | 54 / 54 |
| scenario_battery | Concurrency, failure paths, webhook, schedule, RBAC edges | 31 / 31 |
| authz_matrix | Every protected endpoint, IDOR, escalation, token lifecycle | 165 / 165 |
| Frontend build | Production Vite bundle | Pass |

Tested on macOS (Python 3.14) and Windows (Python 3.13). Resource budgets were measured on Windows (`docs/budgets.json`).

[← Back to README](../README.md)
