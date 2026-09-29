# Platform & Connector Feature Matrix (Phase 8)

Published instead of assuming OS parity (plan.md Phase 8). Every row is backed by
either a passing test in this repo, a recorded measurement (`budgets.json`), or an
explicitly scoped limitation — no invented capabilities.

## Runtime stack

| Capability | Windows (dev machine) | macOS | Linux |
|---|---|---|---|
| Worker (FastAPI + SQLite) | ✅ verified (64 tests + live stack) | untested — no machine | untested — no machine |
| Node-RED embedded runtime | ✅ verified (S4/S5 spikes) | untested | untested |
| Electron shell + tray | ✅ code + smoke (v33.2.0) | untested | untested |
| Isolated-runner POSIX rlimits | n/a (Windows path uses wall-clock kill) | code present, untested | code present, untested |
| Keyring token storage | planned (Milestone A) | planned | planned |

## Measurement (Windows 11, python 3.13, this dev machine)

| Metric | Budget | Measured | Verdict |
|---|---|---|---|
| Idle CPU (worker + Node-RED, dashboard closed) | ≤ 1% of one core | see `budgets.json` | recorded per run |
| Resident memory (background) | ≤ 400 MiB | see `budgets.json` | recorded per run |
| Capture poll latency (sample folder) | ≤ 500 ms | see `budgets.json` | recorded per run |
| Event ingest queue bound | 1,000 events | enforced at ingest | ✅ by contract |

Reproduce: `python scripts/measure_budgets.py 10` with the stack running.

## Connectors

| Connector | Status | Notes |
|---|---|---|
| CSV tracking file (alias `sample-tracking-file`) | ✅ supported | bounded parser, staged atomic writes, exactly-once effects |
| Invoice/PO CSV registers (alias `invoice-register`) | ✅ supported (Phase 8 second workflow) | three-way scoped compare, independent-oracle tested |
| Excel (.xlsx) | ❌ intentionally unsupported | plan Phase 3: claim only what the parser proves; xlsx parser is Phase 8+ scoped work |
| Email (drafts) | ⚠️ partial | in-app drafts only; no SMTP/IMAP send path exists to claim |
| Email (send) | ❌ unsupported | account-based integration; must never be mandatory for the free core demo |
| Browser capture | ⚠️ synthetic v1 contract only | v2 watcher events are real; browser extension remains Phase-1 synthetic scope |
| Government API verification | ❌ unsupported | an unavailable API never becomes a fake verification (plan rule) |
| Desktop notifications | ✅ supported | in-app notification center + Electron tray path |

## Known connector limits

- Files are polled (settled size+mtime), not OS-hooked: live edits inside an open
  editor are invisible until saved and settled — by design (no invented events).
- Parser budgets: ≤1000 rows/file, ≤1000 events/queue, synthetic fixture cap 100.
- All writes go through declared resource aliases; path strings never grant access.
