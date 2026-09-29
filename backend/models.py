"""ORM models for the Stage 0 spike (subset of Master Plan §5.4 DDL)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Workflow(Base):
    """A user-visible workflow. Soft-deleted via deleted_at (runs/audit retained)."""
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # B4 soft delete: set when removed; runs/versions/audit history are retained
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_json: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = ({"sqlite_autoincrement": False},)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)  # manual|test|schedule|inject
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    # pending|running|passed|failed|cancelled|waiting
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    measured_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RunNodeRecord(Base):
    __tablename__ = "run_node_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # running|passed|failed|skipped
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class IdempotencyClaim(Base):
    """Exactly-once business effects (S11). Claim before applying, in a transaction."""
    __tablename__ = "idempotency_claims"
    effect_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    record_key: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), default="en")
    destination: Mapped[str] = mapped_column(String(32), default="in_app")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    record_key: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[str] = mapped_column(String(40), nullable=False)
    processed_at: Mapped[str] = mapped_column(String(40), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pattern_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="suggested")  # suggested|reviewed|dismissed
    first_seen: Mapped[str] = mapped_column(String(40), nullable=False)
    last_seen: Mapped[str] = mapped_column(String(40), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditEntry(Base):
    """Hash-chained append-only audit (USP-2). hash = sha256(prev_hash|payload|at|seq).

    `at` is a canonical ISO-8601 UTC string (contracts style) so the hash material is
    byte-identical after any SQLite round-trip.
    """
    __tablename__ = "audit_entries"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)


class Notification(Base):
    """Persistent dashboard notification (Phase 4). Generic content only; opening one
    navigates to its candidate. Re-alerts for an unchanged candidate are suppressed."""
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class GenerationPlan(Base):
    """Phase 5: explicit user-approved specification. Generation is BLOCKED while
    required rules are missing or contradictory (missing_rules_json non-empty)."""
    __tablename__ = "generation_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)      # the full spec
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    missing_rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")  # draft|approved_for_generation
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class GeneratedArtifact(Base):
    """Phase 5: model output + code + version identity stored together. States:
    generating → awaiting_test_approval | invalid (static checks failed)."""
    __tablename__ = "generated_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_output_json: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    code_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    static_check_json: Mapped[str] = mapped_column(Text, nullable=False)  # violations list
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # awaiting_test_approval|invalid|test_passed|activated|revoked
    activated_code_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class TestJob(Base):
    """Phase 6: one isolated test execution. The report is bound to job, code, input,
    runtime and policy hashes; mismatched/stale evidence is rejected on read."""
    __tablename__ = "test_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    code_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fixture_name: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # consent_pending|running|passed|failed
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class Approval(Base):
    """Explicit human decision (test consent / activation). Never minted by a model
    response or a runner report; referenced by content hashes, not trust."""
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # test_consent|activation
    artifact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    code_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class RegistryTemplate(Base):
    """Phase 9: shared registry entry. Publication stores VERSIONED LOGIC + parameters
    + synthetic examples only — never private records, credentials, or approval state.
    Imports arrive as untrusted drafts that must re-pass local tests + activation."""
    __tablename__ = "registry_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    graph_json: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    compatible_connectors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="published")  # published|withdrawn
    published_at: Mapped[str] = mapped_column(String(40), nullable=False)
    withdrawn_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    signature: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signer_pubkey: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class RegistryImport(Base):
    """A template import into a local office: always an untrusted draft; carries its
    own mapping + local test evidence before it can ever be activated."""
    __tablename__ = "registry_imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(36), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    local_mapping_json: Mapped[str] = mapped_column(Text, nullable=False)
    imported_graph_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="untrusted_draft")  # untrusted_draft|tested|activated|rejected|revoked
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


# ── Roadmap: identity, entitlements, teams, runners, triggers, governance ────

class User(Base):
    """Roadmap Phase A: local-first account. First created user administers the machine."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiToken(Base):
    """Roadmap Phase A: per-user API token. Only the sha256 of the token is stored;
    plaintext is displayed exactly once at creation."""
    __tablename__ = "api_tokens"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(24), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False, default="default")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Org(Base):
    """Roadmap Phase B/C: the account organization. `tier` resolves entitlements;
    local_only marks the Government/sovereign deployment mode (no cloud calls)."""
    __tablename__ = "orgs"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tier: Mapped[str] = mapped_column(String(24), nullable=False, default="solo")  # solo|team|enterprise|government|developer
    local_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    """Roadmap Phase C: user ↔ org with a role from the README permission model."""
    __tablename__ = "memberships"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(24), ForeignKey("orgs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(24), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="operator")  # observer|operator|approver|owner
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invitation(Base):
    """Roadmap Phase C: expiring, token-based team invitation; role granted at accept."""
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(24), ForeignKey("orgs.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="operator")
    created_by: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Process(Base):
    """Roadmap Phase C: business-process grouping (owning org, quotas, retention).

    Context model (product §5): a process belongs to an organization TYPE
    (corporate / government / individual / nonprofit / education) with a SIZE
    (solo/small/medium/large), a DEPARTMENT (per org type), and a PROCESS TYPE
    (per department) — the create flow cascades these so only coherent choices
    are offered. Existing rows keep "" defaults (legacy = unclassified)."""
    __tablename__ = "processes"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(24), ForeignKey("orgs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    run_quota_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = unlimited
    org_type: Mapped[str] = mapped_column(String(24), nullable=False, default="")   # corporate|government|individual|nonprofit|education
    size: Mapped[str] = mapped_column(String(16), nullable=False, default="")       # solo|small|medium|large
    department: Mapped[str] = mapped_column(String(40), nullable=False, default="")  # per teams.DEPARTMENTS[org_type]
    process_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")  # per teams.PROCESS_TYPES[department]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Runner(Base):
    """Roadmap Phase D: execution runner (local Docker or paired office machine).
    README §7: pair identities, authenticate connections, consent for transfer."""
    __tablename__ = "runners"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(String(24), ForeignKey("orgs.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="local")  # local|paired
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="registered")  # registered|paired|online|offline|revoked
    identity_pubkey: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_seen_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trigger(Base):
    """Roadmap Phase D: workflow triggers (webhook, file-arrival, schedule).
    Schedules store their evidence source — demo cycles can never create them."""
    __tablename__ = "triggers"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflows.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # webhook|file|schedule
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evidence_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunParameter(Base):
    """Roadmap Phase E: declared run parameters per workflow version (approved scope)."""
    __tablename__ = "run_parameters"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_versions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    param_type: Mapped[str] = mapped_column(String(16), nullable=False, default="string")  # string|number|date
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_json: Mapped[str] = mapped_column(Text, nullable=False, default="null")


class ReviewGate(Base):
    """Roadmap Phase E: a paused mid-run human decision (approval-gate node)."""
    __tablename__ = "review_gates"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending|approved|rejected
    decided_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class RegistryEvent(Base):
    """Roadmap Phase G: honest registry signals — real installs and real run counts only."""
    __tablename__ = "registry_events"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("registry_templates.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # install|run_report
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    at: Mapped[str] = mapped_column(String(40), nullable=False)
