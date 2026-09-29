"""Roadmap Phase C: teams, roles, invitations, business processes.

Role model maps 1:1 onto README §3's distinct permissions:
  observer  — may see observation/status only
  operator  — runs approved workflows; no test/activate rights
  approver  — may test + activate + run
  owner     — everything incl. publish + administration
Invitations are expiring, token-based; revocation semantics follow README
("Revoking execution access stops dependent operations") — last owner cannot be
demoted, so an org can never lose its administrators.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Invitation, Membership, Org, Process, User

ROLES = ("observer", "operator", "approver", "owner")
ROLE_RANK = {"observer": 0, "operator": 1, "approver": 2, "owner": 3}

# README §3 distinct permissions → minimum role
PERMISSION_MIN_ROLE = {
    "observe": "observer",
    "run": "operator",
    "test": "approver",
    "activate": "approver",
    "publish": "owner",
    "admin": "owner",
}


def role_allows(role: str, permission: str) -> bool:
    need = PERMISSION_MIN_ROLE.get(permission)
    if need is None:
        return False
    return ROLE_RANK.get(role, -1) >= ROLE_RANK[need]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def primary_org(db: Session) -> Org:
    from backend.entitlements import get_or_create_org
    return get_or_create_org(db)


def user_role(db: Session, user) -> str:
    """A user's effective role in the primary org (admin users are owners).

    Bug fix (create-flow audit): users without an explicit membership row are
    OPERATOR, not observer. Registration provisions 'operator' (the working
    default — observers are created deliberately by an owner), so a missing row
    can only mean a legacy/provisioned account; defaulting those to read-only
    locked every mutating route behind a false 403. Admin users stay owners.
    """
    from backend.models import Membership
    from sqlalchemy import select
    org = primary_org(db)
    m = db.scalar(select(Membership).where(Membership.org_id == org.id,
                                           Membership.user_id == user.id))
    if m is not None:
        return m.role
    if user.is_admin:
        return "owner"
    return "operator"


def members(db: Session, org_id: str) -> list[dict]:
    rows = (db.query(Membership).filter(Membership.org_id == org_id)
            .order_by(Membership.created_at).all())
    out = []
    for m in rows:
        u = db.get(User, m.user_id)
        out.append({"membership_id": m.id, "user_id": m.user_id,
                    "username": u.username if u else "(deleted)",
                    "display_name": u.display_name if u else "",
                    "role": m.role, "since": m.created_at.isoformat() if m.created_at else None})
    return out


def add_member(db: Session, org_id: str, user_id: str, role: str) -> Membership:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    existing = db.scalar(select(Membership).where(Membership.org_id == org_id,
                                                  Membership.user_id == user_id))
    if existing is not None:
        existing.role = role
        db.commit()
        return existing
    m = Membership(id=secrets.token_hex(12), org_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def set_role(db: Session, org_id: str, membership_id: str, role: str) -> bool:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    m = db.get(Membership, membership_id)
    if m is None or m.org_id != org_id:
        return False
    if m.role == "owner" and role != "owner":
        owners = db.scalar(select(Membership.id).where(
            Membership.org_id == org_id, Membership.role == "owner",
            Membership.id != membership_id).limit(1))
        if owners is None:
            raise ValueError("cannot demote the last owner")
    m.role = role
    db.commit()
    return True


def remove_member(db: Session, org_id: str, membership_id: str) -> bool:
    m = db.get(Membership, membership_id)
    if m is None or m.org_id != org_id:
        return False
    if m.role == "owner":
        owners = db.scalar(select(Membership.id).where(
            Membership.org_id == org_id, Membership.role == "owner",
            Membership.id != membership_id).limit(1))
        if owners is None:
            raise ValueError("cannot remove the last owner")
    db.delete(m)
    db.commit()
    return True


def create_invitation(db: Session, org_id: str, role: str, created_by: str,
                      ttl_hours: int = 72) -> tuple[Invitation, str]:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    token = "inv_" + secrets.token_urlsafe(24)
    inv = Invitation(id=secrets.token_hex(12), org_id=org_id, role=role,
                     token_hash=_hash(token), created_by=created_by,
                     expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours))
    db.add(inv)
    db.commit()
    return inv, token


def accept_invitation(db: Session, token: str, user_id: str) -> Membership:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == _hash(token or "")))
    if inv is None or inv.accepted_by is not None:
        raise ValueError("invitation not valid")
    if inv.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise ValueError("invitation expired")
    inv.accepted_by = user_id
    db.commit()
    return add_member(db, inv.org_id, user_id, inv.role)


def list_invitations(db: Session, org_id: str) -> list[dict]:
    rows = (db.query(Invitation).filter(Invitation.org_id == org_id)
            .order_by(Invitation.created_at.desc()).all())
    return [{"id": i.id, "role": i.role,
             "expires_at": i.expires_at.isoformat(),
             "accepted": i.accepted_by is not None} for i in rows]


def revoke_invitation(db: Session, org_id: str, invitation_id: str) -> bool:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.org_id != org_id or inv.accepted_by is not None:
        return False
    db.delete(inv)
    db.commit()
    return True


# ── processes ────────────────────────────────────────────────────────────────

def create_process(db: Session, org_id: str, name: str, description: str = "",
                   run_quota_per_day: int = 0) -> Process:
    if not (name or "").strip():
        raise ValueError("process name required")
    p = Process(id=secrets.token_hex(12), org_id=org_id, name=name.strip()[:160],
                description=(description or "")[:2000],
                run_quota_per_day=max(0, int(run_quota_per_day)))
    db.add(p)
    db.commit()
    return p


def list_processes(db: Session, org_id: str) -> list[Process]:
    return list(db.scalars(select(Process).where(Process.org_id == org_id)
                           .order_by(Process.created_at)))


def attach_workflow_to_process(db: Session, process_id: str, workflow_id: str) -> bool:
    """Workflows point at a process via Setting rows (keeps Workflow model untouched)."""
    from backend.models import Setting
    row = db.get(Setting, f"workflow_process:{workflow_id}")
    if row is None:
        row = Setting(key=f"workflow_process:{workflow_id}", value_json=json.dumps(process_id))
        db.add(row)
    else:
        row.value_json = json.dumps(process_id)
    db.commit()
    return True


def workflow_process_map(db: Session, workflow_ids: list[str]) -> dict[str, str]:
    from backend.models import Setting
    out: dict[str, str] = {}
    for wid in workflow_ids:
        row = db.get(Setting, f"workflow_process:{wid}")
        if row is not None:
            try:
                out[wid] = json.loads(row.value_json)
            except Exception:
                out[wid] = row.value_json
    return out


# ── org profile: organization types / sizes, departments, process types ──────
# (Product §5) The context model must cover far more than corporate back
# offices: corporate enterprises (by size), government agencies, and
# individuals/solo users. Process types are offered per (org type, size,
# department) so the create flow only ever shows coherent choices.

ORG_TYPES = ("corporate", "government", "individual", "nonprofit", "education")

# Size only applies to organizations — individuals/solo users pick "solo".
ORG_SIZES = ("solo", "small", "medium", "large")

# Department/team catalog per organization type. Values are stable ids shown
# through the API; the frontend maps ids to labels.
DEPARTMENTS: dict[str, tuple[str, ...]] = {
    "corporate": (
        "finance", "operations", "procurement", "human_resources",
        "sales", "marketing", "legal", "it", "customer_support",
    ),
    "government": (
        "revenue", "licensing", "public_works", "health",
        "education", "social_services", "compliance", "records",
    ),
    "individual": ("personal", "freelance", "consulting"),
    "nonprofit": ("programs", "fundraising", "volunteers", "grants", "admin"),
    "education": ("admissions", "academics", "examinations", "library", "admin"),
}

# Process types per department — filtered by (org_type, size, department).
PROCESS_TYPES: dict[str, tuple[str, ...]] = {
    # corporate
    "finance": ("accounts_payable", "accounts_receivable", "invoice_po_matching",
                "tax_filing", "expense_reimbursement", "payroll_processing", "audit_prep"),
    "operations": ("task_tracking", "vendor_followup", "inventory_updates",
                   "report_generation", "escalation_handling"),
    "procurement": ("vendor_onboarding", "purchase_orders", "quote_comparison",
                    "contract_renewals", "goods_receipt"),
    "human_resources": ("employee_onboarding", "leave_management", "payroll_queries",
                        "recruitment_pipeline", "exit_process"),
    "sales": ("lead_followup", "quote_generation", "order_processing",
              "customer_onboarding", "collections"),
    "marketing": ("campaign_tracking", "content_approvals", "lead_nurture", "report_generation"),
    "legal": ("contract_review", "compliance_calendar", "document_drafting"),
    "it": ("ticket_triage", "access_requests", "backup_verification", "asset_tracking"),
    "customer_support": ("ticket_followup", "sla_escalation", "feedback_triage", "knowledge_base_updates"),
    # government
    "revenue": ("tax_filing", "return_processing", "notice_generation", "payment_reconciliation"),
    "licensing": ("license_renewal", "application_followup", "approval_workflows", "status_notifications"),
    "public_works": ("complaint_triage", "work_orders", "inspection_scheduling", "report_generation"),
    "health": ("patient_followup", "campus_screening", "supply_tracking", "compliance_and_filing"),
    "education": ("enrollment_processing", "certification_issuance", "compliance_and_filing"),
    "social_services": ("benefit_applications", "case_followup", "eligibility_screening"),
    "compliance": ("compliance_and_filing", "audit_prep", "approval_workflows", "document_drafting"),
    "records": ("records_requests", "data_entry_verification", "archival_updates"),
    # individual / solo
    "personal": ("personal_finance", "bill_reminders", "document_management", "task_tracking"),
    "freelance": ("invoicing", "client_followup", "quote_generation", "project_tracking"),
    "consulting": ("client_reporting", "engagement_tracking", "invoicing", "proposal_generation"),
    # nonprofit
    "programs": ("beneficiary_tracking", "grant_reporting", "compliance_and_filing"),
    "fundraising": ("donor_followup", "campaign_tracking", "pledge_management"),
    "volunteers": ("volunteer_onboarding", "shift_scheduling", "hours_tracking"),
    "grants": ("grant_applications", "compliance_and_filing", "report_generation"),
    "admin": ("compliance_and_filing", "document_management", "report_generation", "approval_workflows"),
    # education
    "admissions": ("application_followup", "enrollment_processing", "document_management"),
    "academics": ("course_scheduling", "attendance_tracking", "grade_processing"),
    "examinations": ("exam_scheduling", "result_processing", "certificate_issuance"),
    "library": ("overdue_notices", "inventory_updates", "membership_management"),
}

# Fallback for departments missing from PROCESS_TYPES (never an empty menu).
_DEFAULT_PROCESS_TYPES = ("report_generation", "task_tracking", "compliance_and_filing",
                          "approval_workflows", "document_management")

# Sizes available per org type: individuals are always solo (UI hides the picker).
ORG_SIZES_FOR_TYPE: dict[str, tuple[str, ...]] = {
    "corporate": ("small", "medium", "large"),
    "government": ("small", "medium", "large"),
    "nonprofit": ("small", "medium", "large"),
    "education": ("small", "medium", "large"),
    "individual": ("solo",),
}


def valid_context(org_type: str | None, size: str | None, department: str | None,
                  process_type: str | None) -> list[str]:
    """Validate a full context tuple; returns a list of human-readable problems
    (empty = valid). Shared by the API validators and the UI catalog."""
    problems: list[str] = []
    if org_type not in ORG_TYPES:
        problems.append(f"unknown organization type: {org_type}")
        return problems
    if size not in ORG_SIZES_FOR_TYPE.get(org_type, ORG_SIZES):
        problems.append(f"invalid size '{size}' for organization type '{org_type}'")
    if department not in DEPARTMENTS.get(org_type, ()):  # unknown dept for this org type
        problems.append(f"unknown department '{department}' for organization type '{org_type}'")
        return problems
    allowed = PROCESS_TYPES.get(department, _DEFAULT_PROCESS_TYPES)
    if process_type not in allowed:
        problems.append(f"unknown process type '{process_type}' for department '{department}'")
    return problems


def process_types_for(org_type: str, size: str, department: str) -> list[str]:
    """Coherent process-type options for a (org type, size, department) choice.
    Department not in the catalog falls back to the generic set — the UI never
    shows an empty menu."""
    if department in PROCESS_TYPES:
        return list(PROCESS_TYPES[department])
    return list(_DEFAULT_PROCESS_TYPES)


def set_workflow_context(db: Session, workflow_id: str, org_type: str, size: str,
                         department: str, process_type: str) -> None:
    """Persist the classification context of a workflow (create step 1).
    Stored as a Setting JSON row so the Workflow model stays untouched (same
    pattern as workflow_process). Invalid tuples are refused here too."""
    from backend.models import Setting
    problems = valid_context(org_type, size, department, process_type)
    if problems:
        raise ValueError("; ".join(problems))
    row = db.get(Setting, f"workflow_context:{workflow_id}")
    payload = json.dumps({"org_type": org_type, "size": size,
                          "department": department, "process_type": process_type})
    if row is None:
        row = Setting(key=f"workflow_context:{workflow_id}", value_json=payload)
        db.add(row)
    else:
        row.value_json = payload
    db.commit()


def workflow_context_map(db: Session, workflow_ids: list[str]) -> dict[str, dict]:
    """workflow_id -> {org_type, size, department, process_type} (missing = {})."""
    from backend.models import Setting
    out: dict[str, dict] = {}
    for wid in workflow_ids:
        row = db.get(Setting, f"workflow_context:{wid}")
        if row is None:
            continue
        try:
            out[wid] = json.loads(row.value_json)
        except Exception:
            continue
    return out

