# Phase 1 evidence — 20 September 2026 (Asia/Dubai)

**In progress.** Local proofs passed; the phase completion gate has not passed. No generated code has been run and no customer data has been collected. Docker and paired-runner testing are explicitly deferred by the user.

After organizing the repository into component folders, the 20 Python tests, 11 browser checks, and frontend build passed again. Imports, test paths, command shortcuts, and documentation links were checked. The React screen/style contents retain the original fingerprints below; the files now live under `frontend/`.

| Check | Actual result |
| --- | --- |
| Windows environment | Windows NT 10.0.26200; Node 24.11.0, npm 11.6.1, Python 3.11.9. |
| Saved CSV/XLSX comparison + contracts | **20 unit tests passed**. Independent expected field differences; row reorder/add/remove; duplicate/missing IDs; malformed/oversized/archive/XML/formula cases; event shape, timestamps, raw-value exclusion, duplicate events, report-shape requirements. |
| Browser connector | **11 automated checks passed**, four observed actions for C001/C003. Empty/failed saves, form typing, script clicks, wrong route/port, and the React dashboard do not add events. |
| Browser environment | Fresh Chromium 151.0.7922.34 profile through Playwright 1.62.1. Profile deleted after run. No personal browser session used. |
| Visual reference | **13 screenshots** at 1440×1000 viewport: all six destinations, three detail states, and four additional creation steps. Dashboard and sandbox screen visually inspected. Existing `frontend/src/main.jsx` / `frontend/src/styles.css` unchanged. |
| Frontend build | `npm run build` passed. Existing dependency versions pinned; dev/preview bind to loopback by default. |
| Dependency advisory check | npm reported zero known vulnerabilities for the frontend installation and the Phase 1 Playwright lockfile at check time. This is not a full security review. |
| Human demonstration | Pending. Automated fixture input is not human end-to-end acceptance. |
| Local Docker | Not on PATH or either checked standard Windows install path. Availability elsewhere unverified. No container test performed. |
| Paired runner | A trusted team host can be arranged later. OS/network/pairing details and isolated fixture test pending. No remote connection attempted. |
| macOS / Linux | No test results yet. Cross-platform support remains a target. |
| Free cloud model | No Gemini/Google API key present in the checked environment. Account quota/access not verified; no AI call made. |
| Named owners | Work-area roles defined; teammate names pending. |

## Reproduce and inspect

Run the commands in [phase-1.md](phase-1.md). Local generated evidence is intentionally ignored by Git. Paths below are relative to the repository root:

- `artifacts/phase-1/browser-report.json`: check names, tool versions, source hashes, screenshot names, and limitations.
- `artifacts/phase-1/capture-events.json`: four minimized synthetic events validated against the schema.
- `artifacts/phase-1/*.png`: visual references. The run blocks external page requests, so the current Google Fonts import uses its local fallback. Preserve that condition in comparisons until offline fonts are packaged.

Report timestamps are UTC; the run on the local 20 September date is recorded as 19 September UTC. These are development artifacts, not authenticated runner reports. A future teammate reruns the proof instead of relying on this summary as test execution.

Source fingerprints for the visual reference:

```text
frontend/src/main.jsx   6134922ce42b57ff59e84a27db14a3c0c25bd8a5f70a95f7b66b68a0319d34cb
frontend/src/styles.css ad76ea7bbd1bbad6fe58bd056ffc048885f354fede28f8353498bdb4187c927f
```

**Next gate:** teammate/manual review of contracts and capture, test machine/model inventory, and trusted local/paired isolated fixture evidence. Until then, Phase 1 remains in progress; production observation and workflow execution remain unimplemented.
