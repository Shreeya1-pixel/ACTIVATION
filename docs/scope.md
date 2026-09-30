# Scope: what's done and what's next

**Known limits:** detection accuracy is measured on synthetic workspaces, and the loop is tested on sample and practice sheets; there are no real-office pilots of AutoStack yet. The oracle checks which rows are selected, not the effect label. On macOS the sandbox cannot cap memory.

## Done and tested

| Loop step | Status |
|---|---|
| Identify | Any folder, CSV and `.xlsx`, any ID column, per-file column choice, duplicate-ID check; detection with evidence and near-miss rejection |
| Generate | AI plan and code generation (Gemini or offline mock) with PII tokenisation |
| Test & self-repair | Static checks + hardened sandbox + automatic repair loop (3 attempts); failing code can never be activated |
| Dry run | Preview from the Workflows page; preflight on every run with hand-back to a person |
| Go live | Manual, schedule, file-change and webhook triggers; exactly-once, rollback, verifiable audit chain |
| Around the loop | Signed registry, 4-role access control, privacy ledger, retention windows, SIEM export, sample workspace, Try it live practice workspace |

## Next (clearly scoped)

| Item | Current state | Next step |
|---|---|---|
| Runtimes for any sheet | Automations run on any CSV in the watched folder, learning the rule and the columns to set from your own edits; Excel files are detected but written back only as CSV | Write back to `.xlsx`; rules with more than one condition (by 14 Nov) |
| Counting the latest occurrence | The most recent occurrence per record counts once it completes, so a pattern is suggested one repeat later | Deliberate, to avoid suggesting half-finished work |
| Browser capture | Prototype extension; folder watching is the supported path | Harden the extension |
| Cloud demo | Live on Railway: [activation-frontend-production.up.railway.app](https://activation-frontend-production.up.railway.app/) (Dockerfiles and `railway.json` included) | Folder capture in the cloud watches the server's volume; for your own files, run the worker locally |
| PII detection | Pattern and field-name based | Add name detection for free text |
| Oracle coverage | Compares the selected row IDs; the effect label is not checked | Compare the effect too |
| Sandbox memory cap | Enforced where the OS supports an address-space limit; not on macOS | Verify on Linux; add a memory watchdog on macOS |
| Measured impact | Savings are illustrative | Pilots with 3 UAE small offices |

## Longer-term roadmap

- Write automations back to `.xlsx`, and rules with more than one condition.
- An e-invoicing export step that prepares structured invoice data for an accredited service provider.
- Outbound HTTP connector, keyring-backed secrets, multi-machine sync.
- A browser extension capture path, moved from prototype to supported.

Full plan: [product-roadmap.md](product-roadmap.md).

[← Back to README](../README.md)
