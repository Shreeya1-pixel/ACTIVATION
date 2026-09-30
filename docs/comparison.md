# What makes AutoStack different

1. **It tells you what to automate.** Zapier, Make, n8n and Power Automate start from a blank canvas: someone has to know what to build. AutoStack starts from how people actually work and proposes automations with evidence attached: how many times, for which records, in what order.
2. **It writes the automation for you, and fixes its own mistakes.** The detected pattern becomes a plan and then runnable code automatically. If the code fails the sandbox, the exact failure goes back to the AI and it tries again. There is no flow-builder to learn and no developer needed.
3. **It proves the automation before trusting it.** Generated code must pass static checks and a sandboxed run on a copy of your own sheet, and a dry run shows its real effect row by row, before anyone can switch it on. Most tools only find out an automation is wrong after it has run.
4. **A person stays accountable.** Approval is bound to the exact code (by SHA-256) and its passing test. Change the code and it must be tested and approved again.
5. **Safe to share between offices, like signed apps.** Approved automations can be published to a registry as Ed25519-signed templates with permissions derived from what they actually do, never self-declared. Imports arrive untrusted and must re-pass the sandbox on the receiving office's own machine. A publisher can withdraw a template (no new installs) or revoke it (every installed copy switches off). We have not seen this in any automation tool aimed at small offices.
6. **Private by default.** Everything runs on the office PC. With the offline AI mode nothing leaves the machine; with Gemini, personal data is tokenised first and restored locally.

**Related work, and what is ours.** Learning from examples is not new: Excel's Flash Fill learns a transformation from a few typed examples, RPA recorders replay recorded clicks, and task-mining tools (UiPath Task Mining, Power Automate Process Advisor, Celonis) find processes for enterprises so a developer can build them. Code assistants such as ChatGPT or Copilot write code, but only after you describe the task. What AutoStack adds is the chain between them, with checks at every link: generated code is tested against an **independent oracle** built from the confirmed plan (not from the model's own claims) and **repaired automatically** until it passes; **approval is bound to the exact code** and its passing test; and automations are **shared as signed, scoped, revocable templates**.

## Feature comparison

| | ChatGPT / Copilot | Zapier / Make | n8n | UiPath / Power Automate | **AutoStack** |
|---|---|---|---|---|---|
| Finds what to automate | No, you must ask | No | No | Task mining (enterprise add-on) | **Yes, from spreadsheet edits** |
| Raw data stays on the machine; AI sees masked values | No | No (cloud) | Yes, if self-hosted | Mostly (desktop robots) | **Yes, by default** |
| AI output tested before it runs | No | No | No | Partly | **Sandbox run required** |
| Human approval bound to the artifact | No | Optional | Optional | Optional | **Required** |
| Tamper-evident audit log | No | Paid tiers | Limited | Yes | **Hash-chained, verifiable** |
| Signed, scoped sharing between offices | No | No | No | Orchestrator governance | **Ed25519 + derived scopes** |
| Pricing model | Per seat | Per task | Free community edition / cloud plans | Per robot or user | **No per-task fees** |

Competitor features and pricing change often; check vendor sites before relying on this table.

[← Back to README](../README.md)
