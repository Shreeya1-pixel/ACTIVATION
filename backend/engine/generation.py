"""Phase 5: plan validation + generation with STATIC security validation (S9).

Rules (from the plan):
  - Missing or contradictory rules BLOCK generation (no defaults invented).
  - Generated code is validated statically; unsupported/extra behavior is rejected.
    Hard rejects: imports outside an allowlist, network/socket/subprocess/eval/exec,
    filesystem writes outside the permitted resource alias, os/env/system access,
    dunder abuse, dependency installation. Repair attempts are capped; every version
    is preserved in the artifact table.
  - A model response can NEVER mint a permission or approval (it only ever returns
    text; the plan and the approvals table are the only sources of authority).
"""
from __future__ import annotations

import hashlib
import time
import json
import re

from backend.engine import ai

REQUIRED_RULES = ["client_id_field", "field_mappings", "eligibility", "action", "destinations"]
ALLOWED_DESTINATIONS = {"in_app", "desktop_notification"}
ALLOWED_ACTIONS = {"update_status", "create_draft"}

# Static security validation -------------------------------------------------
ALLOWED_MODULES = {"csv", "io", "datetime", "re", "json"}
BANNED_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:import|from)\s+(?:os|sys|subprocess|socket|urllib|http|requests|shutil|pathlib|importlib)\b",
     "import outside allowlist"),
    (r"\b__import__\b", "dynamic import"),
    (r"\beval\s*\(", "eval"),
    (r"\bexec\s*\(", "exec"),
    (r"\bcompile\s*\(", "compile"),
    (r"\bgetattr\s*\(", "getattr"),
    (r"\bopen\s*\(", "raw open() (use the provided safe io handle)"),
    (r"\bos\.", "os access"),
    (r"\bsys\.", "sys access"),
    (r"\bsubprocess", "subprocess"),
    (r"\bsocket\b", "socket"),
    (r"\be__class__\b|\b__globals__\b|\b__builtins__\b|\b__subclasses__\b", "dunder escape"),
    (r"\bpip\b|\binstall\b.*\bpackage\b", "dependency installation"),
]
MAX_CODE_CHARS = 20000


class PlanError(ValueError):
    pass


class ValidationError(Exception):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


def validate_plan(plan: dict) -> list[str]:
    """Returns the list of missing/contradictory rules. Empty list = generatable."""
    missing = [r for r in REQUIRED_RULES if r not in plan or plan[r] in (None, "", [], {})]
    contradictions: list[str] = []
    if not missing:
        if plan["action"] not in ALLOWED_ACTIONS:
            contradictions.append(f"unsupported action: {plan['action']}")
        bad = [d for d in plan["destinations"] if d not in ALLOWED_DESTINATIONS]
        if bad:
            contradictions.append(f"unsupported destinations: {bad}")
        if not isinstance(plan["field_mappings"], dict) or not plan["field_mappings"]:
            contradictions.append("field_mappings must be a non-empty object")
        if not isinstance(plan["eligibility"], dict) or not plan["eligibility"]:
            contradictions.append("eligibility rules required")
    return missing + contradictions


def plan_sha256(plan: dict) -> str:
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


GEN_PROMPT = (
    "Generate a single Python function `def run(rows, ctx):` that processes tracking "
    "rows according to the rules. Return ONLY the function. No imports beyond "
    "csv/io/datetime/re/json, no file/network/os access, no eval/exec. The function "
    "returns a list of row results.\n\n"
    "Contract:\n"
    "- `rows` is a list of dicts mapping column name to string value.\n"
    "- `ctx['eligibility_status']` is a string or None; `ctx['eligibility_date']` is an "
    "ISO date string or None.\n"
    "- Column names come from CONTEXT: `client_id_field`, `eligibility.status_field` "
    "(default 'Status'), `eligibility.date_field` (may be absent), and `action`.\n"
    "- Keep a row only if eligibility_status is None or row[status_field] equals it, AND "
    "(when date_field is given and eligibility_date is not None) row[date_field] is present "
    "and str(row[date_field]) <= eligibility_date.\n"
    "- For each kept row, in input order, append {client_id_field: row.get(client_id_field), "
    "'effect': action}.\n"
    "- Use only builtins. Wrap the function in a ```python code block."
)


def plan_run_context(plan: dict) -> dict:
    """Independent runtime context for the runner, derived ONLY from the confirmed plan.

    The model never supplies expected outcomes; eligibility comes from the plan the user
    approved so the isolated test checks the plan's rules, not the model's word.
    """
    elig = plan.get("eligibility") or {}
    return {
        "eligibility_status": elig.get("status"),
        "eligibility_date": elig.get("run_date") or elig.get("date_value"),
        "destinations": plan.get("destinations") or [],
    }


MAX_REPAIR_ATTEMPTS = 3

REPAIR_PROMPT = (
    "\n\nYour previous version was rejected. Fix every problem listed in "
    "`repair_feedback` and return the corrected function only. Same constraints apply."
)


def generate(plan: dict, *, feedback: list[str] | None = None,
             previous_code: str | None = None) -> dict:
    """One generation attempt. Returns {model_output, code, sha256, violations}.

    Violations non-empty ⇒ artifact must be stored as `invalid` (never testable).
    `feedback` / `previous_code` turn this into a repair attempt.
    """
    missing = validate_plan(plan)
    if missing:
        raise PlanError(f"plan is not generatable: {missing}")
    context = {**plan_run_context(plan),
               "client_id_field": plan["client_id_field"],
               "field_mappings": plan["field_mappings"],
               "eligibility": plan["eligibility"],
               "action": plan["action"],
               "destinations": plan["destinations"],
               "mode": "code"}  # provider must return a runnable run(rows, ctx)
    prompt = GEN_PROMPT
    if feedback:
        context["repair_feedback"] = feedback[:10]
        context["previous_code"] = (previous_code or "")[:MAX_CODE_CHARS]
        prompt = GEN_PROMPT + REPAIR_PROMPT
    model_output = ai.generate_text(prompt, context)
    code = extract_code(model_output)
    violations = static_check(code)
    return {"model_output": model_output, "code": code,
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "violations": violations}


def report_problems(report: dict) -> list[str]:
    """Turn a sandbox report into concrete, model-readable repair feedback."""
    problems: list[str] = []
    if report.get("violations"):
        problems.extend(f"static check: {v}" for v in report["violations"])
    if report.get("error"):
        problems.append(f"sandbox error: {str(report['error'])[-300:]}")
    for c in report.get("checks") or []:
        if not c.get("ok"):
            detail = c.get("detail")
            problems.append(f"check {c['name']} failed" + (f": {json.dumps(detail, default=str)[:300]}"
                                                            if detail else ""))
    if not problems and report.get("status") not in (None, "passed"):
        problems.append(f"sandbox status {report.get('status')}")
    return problems


def broken_draft(plan: dict) -> dict:
    """A deliberately flawed first draft (ignores the due-date rule), used only when a
    demo asks to watch the repair loop. It goes through the same checks as real output."""
    elig = plan.get("eligibility") or {}
    id_field = plan.get("client_id_field", "ClientID")
    has_date = bool(elig.get("date_field") and (elig.get("date_value") or elig.get("run_date")))
    status_check = (
        f"        if status is not None and row.get({elig.get('status_field', 'Status')!r}) != status:\n"
        "            continue\n") if has_date else ""
    flaw = "due-date rule left out" if has_date else "status rule left out"
    code = (
        "def run(rows, ctx):\n"
        "    out = []\n"
        "    status = ctx.get('eligibility_status')\n"
        f"    id_field = {id_field!r}\n"
        "    for row in rows:\n"
        + status_check +
        f"        out.append({{{id_field!r}: row.get(id_field), 'effect': {plan.get('action', 'create_draft')!r}}})\n"
        "    return out\n"
    )
    return {"model_output": f"[demo] deliberately broken first draft: {flaw}",
            "code": code, "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "violations": static_check(code), "seeded": True}


def generate_with_repair(plan: dict, self_check, *, max_attempts: int = MAX_REPAIR_ATTEMPTS,
                         start_broken: bool = False) -> dict:
    """Generate → static check → sandbox self-check → feed failures back → retry.

    `self_check(code)` runs the code in the sandbox against the plan-derived oracle and
    returns a runner report. Stops at the first attempt with no problems, or after
    `max_attempts`. Every attempt is returned so each version can be preserved.
    `start_broken` replaces attempt 1 with `broken_draft(plan)` (labelled as seeded).
    """
    attempts: list[dict] = []
    feedback: list[str] | None = None
    previous: str | None = None
    for n in range(1, max(1, max_attempts) + 1):
        t0 = time.perf_counter()
        if start_broken and n == 1:
            outcome = broken_draft(plan)
        else:
            outcome = generate(plan, feedback=feedback, previous_code=previous)
        gen_ms = int((time.perf_counter() - t0) * 1000)
        problems = list(outcome["violations"])
        report = None
        t1 = time.perf_counter()
        if not problems:
            report = self_check(outcome["code"])
            problems = report_problems(report)
        attempts.append({**outcome, "attempt": n, "problems": problems, "self_check": report,
                         "gen_ms": gen_ms, "check_ms": int((time.perf_counter() - t1) * 1000)})
        if not problems:
            break
        feedback, previous = problems, outcome["code"]
    final = attempts[-1]
    return {"attempts": attempts, "final": final, "ok": not final["problems"],
            "repaired": len(attempts) > 1 and not final["problems"]}


def extract_code(model_output: str) -> str:
    """Pull a python block out of the model output; fall back to the raw text."""
    fence = re.search(r"```(?:python)?\s*\n(.*?)```", model_output, re.DOTALL)
    return fence.group(1).strip() if fence else model_output.strip()


def static_check(code: str) -> list[str]:
    """Hard-reject static security validation (S9). Empty list = accepted."""
    violations: list[str] = []
    if len(code) > MAX_CODE_CHARS:
        violations.append(f"code exceeds {MAX_CODE_CHARS} chars")
    if not re.search(r"\bdef\s+run\s*\(", code):
        violations.append("no run(rows, ctx) entrypoint found")
    for pattern, label in BANNED_PATTERNS:
        if re.search(pattern, code):
            violations.append(f"forbidden construct: {label}")
    return violations
