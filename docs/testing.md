# Testing

```bash
.venv/bin/python -m pytest tests/ -q                # 216 passed, 2 skipped, 29 subtests
.venv/bin/python scripts/benchmark_detection.py     # precision / recall on 500 synthetic workspaces
.venv/bin/python scripts/oracle_ablation.py         # 50 broken programs through each check layer
.venv/bin/python scripts/sandbox_attacks.py         # 30 attack attempts against the sandbox
.venv/bin/python scripts/registry_tamper_demo.py    # tampered shared templates vs the import route
# with the worker running:
.venv/bin/python scripts/qa_probe.py                # 54 end-to-end checks
.venv/bin/python scripts/scenario_battery.py        # 31 behaviour checks
.venv/bin/python scripts/authz_matrix.py            # 165 authorization checks
cd frontend && npm run build
```

| Suite | Covers | Last result |
|---|---|---|
| pytest | Lifecycle, detection quality and stitching, self-repairing generation, generic capture, XLSX, sample replay, RBAC, sandbox, triggers, registry signing and revocation, preflight, dry run, PII, privacy, retention, practice workspace end to end, sandbox hardening | 216 pass / 2 skip |
| benchmark_detection | 500 synthetic workspaces × 3 timing scenarios | P/R 1.00 clean |
| oracle_ablation | 50 hand-written broken programs (wrong rows, off-by-one dates, wrong column, crashes, forbidden imports) on a 12-row sheet and the 3-row fixture | Caught: static 11, + sandbox 18, + oracle 47 (43 on the fixture) |
| sandbox_attacks | 30 attempts at network, file system, processes, host access, escape tricks and resource exhaustion; run with and without the static check | 29 / 30 blocked (27 by the sandbox alone) |
| registry_tamper_demo | Publish a signed template, tamper with the stored copy 5 ways, try to import | 5 / 5 refused with 409; the untouched copy imports |
| qa_probe | Full live stack end to end | 54 / 54 |
| scenario_battery | Concurrency, failure paths, webhook, schedule, RBAC edges | 31 / 31 |
| authz_matrix | Every protected endpoint, IDOR, escalation, token lifecycle | 165 / 165 |
| Frontend build | Production Vite bundle | Pass |

What the numbers do not show: the 3 broken programs the oracle misses are one bug that cannot occur with CSV input and two that change only the effect label (the oracle compares selected row IDs, not the effect). Running the attack battery found 4 real holes (`ctypes`, `pickle` and `multiprocessing` imports, and a typo in the dunder pattern); they were fixed with a module allowlist enforced in both the static check and the sandbox, and are covered by `tests/spike/test_sandbox_hardening.py`. The remaining attack, a memory bomb, is not stopped on macOS because the address-space limit is unsupported there; it has not been verified on Linux. Raw results: `docs/oracle-ablation.json`, `docs/sandbox-attacks.json`, `docs/registry-tamper.json`.

Tested on macOS (Python 3.14) and Windows (Python 3.13). Resource budgets were measured on Windows (`docs/budgets.json`).

[← Back to README](../README.md)
