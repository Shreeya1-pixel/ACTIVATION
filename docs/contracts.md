# Initial contracts and limits

These are Phase 1 design decisions. **Only the fixture capture, event validation, and file comparison are implemented.** Backend permissions, workflow transitions, report verification, runner isolation, and production retention still require their implementation phases and tests. Changes to these interfaces require a version change and affected-test review.

Machine-readable definitions live in [event.schema.json](../shared/contracts/event.schema.json) and [runner-report.schema.json](../shared/contracts/runner-report.schema.json), shared by the backend and tests.

## Observation and data

`event.schema.json` is a closed, synthetic-only event format: unknown properties fail. UUID identifies an event; capture time is when the source sees the action, processing time is when its connector processes it. Source/version, action, resource alias, sample record key, changed field names, and success/ambiguity describe evidence. No field values, credentials, URL query text, clipboard contents, draft bodies, or approval flags belong here.

`sample:C001` is an invented identifier, not privacy protection for a real customer. Phase 3 will use locally protected matching tokens and consented mappings for real records. All timestamps include a timezone. A future ingest service must validate clocks/order and remove duplicates across batches; this proof checks duplicates within a batch only.

Tracking input is UTF-8 CSV or a plain XLSX containing one `Clients` worksheet with exactly `ClientID,Name,Email,FollowUpDate,Status` columns. IDs are unique; initial fixtures are `C000`–`C999`. XLSX cells must be plain text. For this narrow prototype, formulas and text beginning with `=`, `+`, `-`, or `@` after whitespace are rejected. Real phone-number/date formats need explicit later rules. The comparator identifies saved-state differences, not edit gestures, authorship, or a live Excel change stream.

The first confirmed business rule will be: a record with status `Follow-up due` and `FollowUpDate <= run_date` gets an in-app reminder draft and status `Draft prepared`. `run_date` is an explicit date in the user's chosen timezone. Missing/invalid dates or duplicate IDs block the affected batch. The first draft template is `Hello {Name}, this is a sample follow-up reminder for {FollowUpDate}.` It is never sent. In the before/after fixtures, C001 and C003 qualify on 2026-09-20; C002 remains unchanged. These are independent expected results for future generation tests, not a rule already applied by the comparator.

## Workflow states and authority

| Transition | Future backend requirement |
| --- | --- |
| Detected → Plan confirmed | User confirms ID/columns, eligibility, date/timezone, destinations, duplicate rules, and synthetic examples. |
| Plan confirmed → Draft → Awaiting test approval | Minimized cloud-transfer permission; validated artifact tied to the plan; generation alone runs nothing. |
| Awaiting test approval → Testing | Explicit test consent for this version/input/runner; static validation; trusted runner readiness. |
| Testing → Passed / Blocked | Independently verified required checks, correct outputs, and a fresh authenticated report. Failure, timeout, cancellation, or missing evidence cannot pass. |
| Passed → Awaiting activation → Ready | Separate user approval bound to the tested artifact, mappings, permission scopes, dependencies, connectors, and policy. |
| Ready → Running → Completed / Failed / Cancelled | Explicit Run now; current permission and input-version checks; isolated execution; trusted output validation and local application. Return to Ready only while approval remains valid. |
| Any affected state → Blocked | Permission/security revocation, changed code/scope/runtime/policy, or invalid evidence. A new version/retest and any needed renewed permission are required. |

State is server-owned; observations, model output, renderer messages, and imported templates cannot set approval flags. Per-run status is separate from a reusable workflow's activation state. A failed run does not automatically revoke a still-valid version, but reconciliation must finish before another conflicting run.

Permissions are separate grants for **observe**, **read content**, **transfer synthetic context to model**, **transfer to named runner**, **test**, **activate**, **run**, and later **publish**. Each grant records local owner, exact resource aliases/operations, purpose, version, issue/expiry/revocation times. Default is deny; an omitted expiry cannot mean unrestricted access. Path strings from data/model output do not create grants. Pausing collection and cancelling execution are distinct controls; revocation blocks dependent future effects and pending result application.

The model/code may propose only `update_status` and `create_local_draft` for the first workflow. Proposed outputs must include the input version and a business-effect key `(ClientID, follow-up purpose/date, destination alias)`. No arbitrary path, external recipient, shell command, or email-send operation is accepted. The trusted broker checks all fields, claims keys atomically, journals each effect, and rechecks authorization immediately before application. This broker is Phase 7 work.

## Runner report and pairing

`runner-report.schema.json` defines the proposed report envelope. Digests bind artifact, confirmed plan, permission scope, exact input/output, immutable runtime, and independent test suite; job/owner/runner IDs and policy/connector versions must also match. A `passed` report cannot contain a failed/missing/timed-out check. Shape validation alone does not verify a signature, complete check list, ownership, output, or execution policy.

Phase 6 must keep the controller, expected results, and signing key outside the guest. Use a reviewed canonical JSON implementation and Ed25519 library for signing the report body excluding `signature`; include `signature_key_id`. The client must authenticate the runner first, verify the signature and pinned signing-key identity, require the exact suite's unique check IDs, check all version hashes and `issued_at`/`expires_at`, and reject replay/unknown jobs. Initial activation evidence expires after **24 hours**; changing an approval-bound component invalidates it immediately. A schema-valid fake report cannot enable execution.

Pair by independently comparing a one-time code/fingerprint on both trusted devices, then authenticate HTTPS with pinned runner identity and per-user credentials. Pairing invitations expire after 10 minutes and are single-use; operational credentials expire after 24 hours and renew only through a still-valid device pairing. Persist revocation; unpairing blocks new work and invalidates pending reports. Lost-device revocation and key rotation must be tested before paired use. Do not expose a Docker socket/administration port to the client. A team's trusted host may see its submitted synthetic data; disclose that before transfer.

For later registry imports, cache authenticated, monotonically versioned status for at most **24 hours**. A known security revocation remains blocked even offline and is never undone by older status. Unknown/stale status blocks an imported workflow until refreshed. Ordinary withdrawal prevents new imports but does not itself revoke installed versions. Clock rollback or unverifiable freshness must block, not extend the allowance.

## Limits, cleanup, and owners

Numbers below are initial engineering budgets, not measured performance or enforced runner claims.

| Area / role owner | Initial policy | Enforcement phase |
| --- | --- | --- |
| Parser / Capture + security | Input ≤1,000,000 bytes; expanded ZIP ≤8,000,000 bytes; ≤100 archive entries; ≤1,000 data rows, 5 columns, 512 characters/cell; 5-second wall time, 256 MiB memory; no network/macros/external links/formula evaluation. | Shape/size checks exist; process/time/memory/network isolation still Phase 3. |
| Sandbox / Runner + security | 1 CPU, 512 MiB RAM with no additional swap allowance, 64 processes, 30-second wall deadline, 64 MiB scratch, 1 MiB total outputs/logs. Non-root, read-only runtime, no network/host paths/secrets/control sockets. Kill job and reject partial outputs on limits. | Phase 6: verify enforcement, not just configuration. |
| Background agent / Desktop + capture | Target mean idle CPU ≤1% of one core over 5 minutes and resident background memory ≤400 MiB with dashboard closed. Bound ingest queue to 1,000 events; stop collection with a visible gap on overflow. | Measure in Phase 2 and on all platforms in Phase 8. Fixture extension separately caps at 100 events. |
| Snapshots and transfers / Capture + backend | Minimum two protected versions for a saved-file comparison; delete superseded raw snapshots within 24 hours. Cancel unsent transfers on revocation; clear failed/revoked temporary data at next safe cleanup/restart. | Phases 2–3, 6–7. No sensitive persistence without OS-backed protection. |
| Events / Capture + backend | Default 30 days; user deletion cascades to associated raw comparison snapshots and queued transfers. | Phases 2–4. |
| Reports / Runner + backend | Redacted evidence 90 days; job input/temp copies removed on completion, abandoned jobs within 24 hours. Deletion includes crash leftovers; remote cleanup failures remain visible. | Phase 6. |
| Recovery / Backend + security | Protected user-file backups at most 7 days by default; restore rechecks permission. Keep minimum business-effect journal for workflow lifetime to prevent duplicates. If user deletes it, block unattended replay until manual reconciliation; never silently recreate effects. | Phase 7. Explain externally synced backups and physical-erasure limits. |

Role ownership: Desktop leads **S2**; Backend leads **S3/S9/S11**; Capture leads **S4/S7** with each component responsible for its copies; Runner/security leads **S1/S5/S6/S8**; Registry/backend leads **S10**. Reviewers come from the other work areas. **Named teammates are not assigned yet** and must be recorded before those phases start.

For each S1–S11 test, record its fixture ID, expected allowed/rejected outcome, exact component versions/platform, actual result, and reviewer in phase evidence. This document supplies limits and responsibilities; it does not count as passing security evidence. Full dependency vulnerability scanning, Python transitive lock/hashes, artifact integrity enforcement, and patch/revalidation procedures remain S8 work; a clean npm advisory result alone does not prove safety.
