# Phase 1 — feasibility kit

**Status: in progress. Synthetic data only.** The working proofs live in `backend/`, `browser-extension/`, `shared/contracts/`, and `tests/`; the React demo lives in `frontend/`. This guide covers setup and verification. See [phase-1-status.md](phase-1-status.md) for what passed and what is pending, and [contracts.md](contracts.md) for the agreed starting interfaces and limits. The main [development plan](../plan.md) remains the full roadmap; [file.md](../file.md) explains the files.

## What works here

- Compare two saved CSV/XLSX versions by `ClientID`. Report added/removed records and changed column names without exporting their values. Reordering rows is not an edit.
- Observe successful Open record and Save draft actions on **one local sample page** using a small Chromium extension. This proves a site-specific connector can see meaningful DOM actions; it does not observe arbitrary applications or live Excel editing.
- Validate minimized events against a versioned JSON Schema, rejecting extra content, invalid timestamps, and duplicate event IDs.
- Recreate screenshots of the original six React screens, detail panels, and creation steps for later design comparisons.

There is no AI connection, detector, startup app, execution runner, or activation service yet. The runner-report schema is a design contract, not signature verification. The file reader has format/size checks but **does not yet run in a restricted parser process**. Use only the supplied/generated synthetic fixtures; S4 must pass before real file collection is enabled.

## Run the checks

From the repository root, use Python 3.11+ and the Node version described in the main README. A virtual environment keeps Python dependencies separate:

```sh
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` in PowerShell, or `source .venv/bin/activate` on macOS/Linux. If PowerShell activation is restricted, call `.venv\Scripts\python.exe` directly instead of changing machine policy.

```sh
python -m pip install -r backend/requirements.txt
npm run setup
npm run test:unit
python -m backend.file_diff tests/fixtures/clients-before.csv tests/fixtures/clients-after.csv
node tests/node_modules/playwright/cli.js install chromium
npm run test:browser
npm run build
```

In PowerShell, use `npm.cmd` if `npm` is blocked by script execution policy. Browser installation needs a download; no paid account, API key, or Docker is required. Tests were run on Windows; the commands are intended to be portable, but macOS/Linux acceptance is pending.

`npm run setup` installs the two JavaScript packages from `frontend/package-lock.json` and `tests/package-lock.json`. Python dependencies are installed separately by the first command. The root `package.json` only provides shortcuts; run `npm ci` inside a package folder or use its `--prefix`, not a bare `npm ci` at the repository root.

The browser script temporarily serves only local fixtures on ports **4174/4175** and Vite on **5173**, uses a new temporary browser profile, loads the sample extension, performs test clicks, then closes its servers/browser and deletes that profile. Stop an existing Vite server on 5173 first. A busy port fails visibly. It does not use an existing personal browser session. Generated evidence goes into ignored `artifacts/phase-1/`; it is not a monitored office folder.

If reusing an already installed testing runtime, optional environment variables `AUTOSTACK_PLAYWRIGHT_MODULE` and `AUTOSTACK_PYTHON` select its Playwright module and Python executable. Otherwise the normal local dependencies and `python` are used. No account secrets belong in these variables.

## Inspect capture manually

1. Serve **only the fixtures directory**: `python -m http.server 4174 --bind 127.0.0.1 --directory tests/fixtures`.
2. In a dedicated test Chromium profile, open its extensions page, enable developer mode, and load `browser-extension` as an unpacked extension.
3. Open exactly `http://127.0.0.1:4174/office.html`. Open a sample client, enter an invented draft, and save it. Select another client and repeat.
4. Open the extension popup to inspect minimized events. Use Delete fixture events and Delete sample drafts when finished, remove the test extension, and stop the fixture server.

The extension collects only on that exact URL, not other paths/ports. It stops after 100 events; clear them to start another small proof. Popup storage is unencrypted and intended only for the sample IDs. Installing it is not production observation consent. The sample draft editor is a stand-in for the future in-app editor, and does not send email.

Browser automation produces genuine browser-dispatched input, but is **not evidence of a person completing the end-to-end workflow**. A page's DOM can be manipulated, so observations never grant permissions or execution approval. Page-script `.click()` is excluded; this is a useful negative test, not a general human-versus-bot detector.

## Your Phase 1 confirmation checklist

Use only invented data. Complete the setup above first, then run commands from the repository root. These checks confirm the implemented local proofs; they do not complete the deferred Docker/platform/model gates.

| Check | What you should see |
| --- | --- |
| Run `python -m unittest discover -s tests/unit -v` | Currently **20 tests**, ending with `OK`; no failures or errors. |
| Run `python -m backend.file_diff tests/fixtures/clients-before.csv tests/fixtures/clients-after.csv` | `added` and `removed` are empty; `updated` lists only `sample:C001` and `sample:C003`, each with `changed_fields: ["Status"]`. No names, email addresses, or cell values in the result. The command does not change the input files. |
| Run `npm run test:browser` | Report ends with `status: "passed"`, four events, 11 check descriptions, and 13 screenshot names. Inspect the new `artifacts/phase-1/browser-report.json` timestamp so you are checking this run. Close any manual sample server or Vite server first to free ports 4174/4175/5173. |
| Run `npm run dev` (`npm.cmd run dev` in PowerShell if needed) | Open its printed local URL and visit all six sidebar screens. The intended design should remain intact. Screen statistics and sandbox animations still use demo data. Stop the server with Ctrl+C afterward. |
| Perform the manual capture sequence below | The extension records your actual sample-page actions with the expected minimal fields. This is the main human check still needed. |

For the manual check, follow **Inspect capture manually** above to start the sample server and load the extension. Then:

1. Clear previous extension events using **Delete fixture events**, and reload the sample page to start with no opened record.
2. Click **Save draft locally** without opening a client. It should ask for a record/draft; the extension event list should stay empty.
3. Select C001 and click **Open record**. Type an invented draft and save it. Open the extension popup and Refresh: expect exactly `record_opened` followed by `draft_saved`, both for `sample:C001`.
4. Type invented text into **Unobserved test input**. Clear the draft text and try saving the empty draft. Refresh the popup: there should still be only two events. Neither typed text nor draft content should appear in the events.
5. Select C003, open it, enter another invented draft, and save. Refresh: expect four events total, with the second pair belonging to `sample:C003`. UUIDs and timestamps will differ each run.
6. Delete sample drafts on the page and fixture events in the popup. Refresh the popup to confirm `[]`. Remove the test extension and stop the sample server with Ctrl+C.

Record the date, OS/browser, tester, expected/actual results, and any failure in [phase-1-status.md](phase-1-status.md). Leave the human check marked pending until someone actually performs it. If anything differs, keep the error text and stop that check; a screen that merely says “success” is not enough evidence.

## Team next steps

Record a human capture demonstration, assign teammates to the roles in the contracts, obtain macOS/Linux test access, and verify free model access using synthetic context. Docker/local-and-paired tests are deferred at the user's request; they remain an unmet Phase 1 gate. Do not replace them with direct execution of generated Python on the host.

Reference APIs: [Chrome content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts), [Chrome manifest matching](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts), and [Playwright extension testing](https://playwright.dev/docs/chrome-extensions).
