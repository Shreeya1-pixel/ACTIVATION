"""Mutation test for the self-check: how many deliberately wrong versions of a correct
automation does each layer catch?

  static   static checks only (allowlist, banned constructs, size cap)
  sandbox  static + sandboxed run with structural checks, no expected outputs
  oracle   static + sandboxed run compared with outputs computed independently from the plan

Each fault is run against two sheets: the 3-row sample fixture and a 12-row realistic sheet.
Results are written to docs/oracle-ablation.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import app as app_mod  # noqa: E402
from backend.engine import ai, generation, runner  # noqa: E402

PLAN = {
    "client_id_field": "ClientID",
    "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
    "eligibility": {"status": "Follow-up due", "status_field": "Status",
                    "date_field": "FollowUpDate", "date_value": "2026-09-20"},
    "action": "create_draft",
    "destinations": ["in_app"],
}

REALISTIC = [
    {"ClientID": "C101", "Name": "Al Noor Trading", "FollowUpDate": "2026-09-20", "Status": "Follow-up due"},
    {"ClientID": "C102", "Name": "Desert Foods", "FollowUpDate": "2026-09-18", "Status": "Follow-up due"},
    {"ClientID": "C103", "Name": "Gulf Supplies", "FollowUpDate": "2026-09-21", "Status": "Follow-up due"},
    {"ClientID": "C104", "Name": "Zahra Retail", "FollowUpDate": "2026-09-10", "Status": "New"},
    {"ClientID": "C105", "Name": "Oasis FMCG", "FollowUpDate": "2026-09-19", "Status": "Done"},
    {"ClientID": "C106", "Name": "Blue Coast", "FollowUpDate": "2026-10-02", "Status": "Follow-up due"},
    {"ClientID": "C107", "Name": "Najd Imports", "FollowUpDate": "", "Status": "Follow-up due"},
    {"ClientID": "C108", "Name": "Follow-up due", "FollowUpDate": "2026-09-01", "Status": "New"},
    {"ClientID": "C109", "Name": "Palm Logistics", "FollowUpDate": "2026-09-20", "Status": "follow-up due"},
    {"ClientID": "C110", "Name": "Marina Services", "FollowUpDate": "2025-12-30", "Status": "Follow-up due"},
    {"ClientID": "C111", "Name": "Creek Traders", "FollowUpDate": "2026-09-20", "Status": "New"},
    {"ClientID": "C112", "Name": "Jebel Parts", "FollowUpDate": "2026-08-31", "Status": "Follow-up due"},
]

BASE = ai._synth_code({**generation.plan_run_context(PLAN), "client_id_field": "ClientID",
                       "eligibility": PLAN["eligibility"], "action": PLAN["action"]})

S_CHECK = "        if status is not None and row.get('Status') != status:\n            continue\n"
D_BLOCK = ("        if run_date is not None:\n            due = row.get('FollowUpDate')\n"
           "            if due is None or str(due) > str(run_date):\n                continue\n")
ALL_ROWS = "return [{'ClientID': r.get('ClientID')} for r in rows]"


def sub(a, b, count=1):
    assert a in BASE, a
    return BASE.replace(a, b, count)


MUTANTS = [
    # wrong rows (logic)
    ("wrong rows", "status check inverted", sub("!= status", "== status")),
    ("wrong rows", "status rule dropped", sub(S_CHECK, "")),
    ("wrong rows", "date rule dropped", sub(D_BLOCK, "")),
    ("wrong rows", "status ignored via ctx", sub("status = ctx.get('eligibility_status')", "status = None")),
    ("wrong rows", "date ignored via ctx", sub("run_date = ctx.get('eligibility_date')", "run_date = None")),
    ("wrong rows", "wrong status hardcoded", sub("status = ctx.get('eligibility_status')", "status = 'New'")),
    ("wrong rows", "wrong ctx key for status", sub("ctx.get('eligibility_status')", "ctx.get('status')")),
    ("wrong rows", "wrong ctx key for date", sub("ctx.get('eligibility_date')", "ctx.get('date')")),
    ("wrong rows", "missing-date check inverted", sub("due is None or", "due is not None and")),
    ("wrong rows", "case-folded status compare", sub("row.get('Status') != status", "row.get('Status').lower() != status.lower()")),
    ("wrong rows", "break instead of continue (status)", sub(S_CHECK, S_CHECK.replace("continue", "break"))),
    ("wrong rows", "break instead of continue (date)", sub("                continue\n", "                break\n")),
    ("wrong rows", "returns every row", sub("return out", ALL_ROWS)),
    ("wrong rows", "returns nothing", sub("return out", "return []")),
    ("wrong rows", "drops first result", sub("return out", "return out[1:]")),
    ("wrong rows", "keeps first result only", sub("return out", "return out[:1]")),
    ("wrong rows", "duplicates results", sub("return out", "return out + out")),
    ("wrong rows", "month-level date compare", sub("str(due) > str(run_date)", "str(due)[:7] > str(run_date)[:7]")),
    ("wrong rows", "year-level date compare", sub("str(due) > str(run_date)", "str(due)[:4] > str(run_date)[:4]")),
    # off by one
    ("off by one", "due date >= instead of >", sub("str(due) > str(run_date)", "str(due) >= str(run_date)")),
    ("off by one", "due date < instead of >", sub("str(due) > str(run_date)", "str(due) < str(run_date)")),
    ("off by one", "due date <= instead of >", sub("str(due) > str(run_date)", "str(due) <= str(run_date)")),
    ("off by one", "cut-off one day early", sub("run_date = ctx.get('eligibility_date')", "run_date = '2026-09-19'")),
    ("off by one", "cut-off one day late", sub("run_date = ctx.get('eligibility_date')", "run_date = '2026-09-21'")),
    # wrong column
    ("wrong column", "status read from Name", sub("row.get('Status')", "row.get('Name')")),
    ("wrong column", "date read from Name", sub("row.get('FollowUpDate')", "row.get('Name')")),
    ("wrong column", "ID taken from Name", sub("row.get(id_field)", "row.get('Name')", 2)),
    ("wrong column", "ID column typo", sub("id_field = 'ClientID'", "id_field = 'ClientId'")),
    ("wrong column", "status column typo", sub("row.get('Status')", "row.get('status')")),
    ("wrong column", "date column typo", sub("row.get('FollowUpDate')", "row.get('FollowupDate')")),
    ("wrong column", "effect set to update_status", sub("'effect': 'create_draft'})\n    return", "'effect': 'update_status'})\n    return")),
    ("wrong column", "effect key missing", sub(", 'effect': 'create_draft'})\n    return", "})\n    return")),
    # crashes and bad output shape
    ("crash / bad output", "division by zero", sub("    out = []\n", "    out = []\n    1 / 0\n")),
    ("crash / bad output", "missing column raises KeyError", sub("due = row.get('FollowUpDate')", "due = row['Due']")),
    ("crash / bad output", "returns None", sub("return out", "return None")),
    ("crash / bad output", "returns a dict", sub("return out", "return {'rows': out}")),
    ("crash / bad output", "returns bare IDs", sub("return out", "return [o['ClientID'] for o in out]")),
    ("crash / bad output", "unbounded output", sub("return out", "return out * 2000")),
    ("crash / bad output", "infinite loop", sub("    out = []\n", "    out = []\n    while True:\n        pass\n")),
    ("crash / bad output", "no run() entry point", sub("def run(rows, ctx):", "def main(rows, ctx):")),
    # forbidden constructs
    ("forbidden", "import os", "import os\n" + BASE),
    ("forbidden", "import socket", "import socket\n" + BASE),
    ("forbidden", "import subprocess", "import subprocess\n" + BASE),
    ("forbidden", "import urllib.request", "import urllib.request\n" + BASE),
    ("forbidden", "import shutil", "import shutil\n" + BASE),
    ("forbidden", "open() a file", sub("    out = []\n", "    out = []\n    open('/etc/passwd').read()\n")),
    ("forbidden", "__import__('os')", sub("    out = []\n", "    out = []\n    __import__('os').system('id')\n")),
    ("forbidden", "eval()", sub("    out = []\n", "    out = []\n    eval('1+1')\n")),
    ("forbidden", "exec()", sub("    out = []\n", "    out = []\n    exec('x = 1')\n")),
    ("forbidden", "getattr on builtins", sub("    out = []\n", "    out = []\n    getattr(__builtins__, 'open')\n")),
]


def evaluate(code: str, table: list[dict]) -> dict:
    static = bool(generation.static_check(code))
    table = [dict(r) for r in table]
    table.extend(app_mod._boundary_rows(table, PLAN, "ClientID"))
    ctx = generation.plan_run_context(PLAN)
    policy = {"max_output_items": 1000, "forbidden": ["network", "filesystem", "subprocess"]}
    try:
        plain = runner.run_isolated_test(code, table, ctx=ctx, policy=policy, key_field="ClientID", timeout_s=5)
        sandbox = static or plain["status"] != "passed"
    except Exception:  # noqa: BLE001 - misuse (e.g. no entry point) is a catch
        sandbox = True
    try:
        full = runner.run_isolated_test(code, table, ctx=ctx, policy=policy, key_field="ClientID", timeout_s=5,
                                        expected=app_mod._expected_outputs(table, PLAN, "ClientID"))
        oracle = static or full["status"] != "passed"
    except Exception:  # noqa: BLE001
        oracle = True
    return {"static": static, "sandbox": sandbox, "oracle": oracle}


def main() -> None:
    from backend.file_diff import read_snapshot
    fixture = list(read_snapshot(app_mod._as_tmp_fixture(
        (app_mod.cfg.FIXTURES_DIR / "clients-before.csv").read_bytes())).values())
    base_ok = {name: evaluate(BASE, t)["oracle"] is False for name, t in
               (("fixture", fixture), ("realistic", REALISTIC))}
    assert all(base_ok.values()), f"correct code must pass: {base_ok}"
    out = {"mutants": len(MUTANTS), "correct_code_passes": base_ok, "sheets": {}}
    for sheet, table in (("fixture_3_rows", fixture), ("realistic_12_rows", REALISTIC)):
        rows, totals, by_cat = [], {"static": 0, "sandbox": 0, "oracle": 0}, {}
        for cat, name, code in MUTANTS:
            r = evaluate(code, table)
            rows.append({"category": cat, "fault": name, **r})
            c = by_cat.setdefault(cat, {"n": 0, "static": 0, "sandbox": 0, "oracle": 0})
            c["n"] += 1
            for k in totals:
                totals[k] += r[k]
                c[k] += r[k]
        out["sheets"][sheet] = {"caught": totals, "by_category": by_cat,
                                "missed_by_oracle": [x["fault"] for x in rows if not x["oracle"]], "detail": rows}
        print(f"{sheet}: static {totals['static']}/{len(MUTANTS)}  sandbox {totals['sandbox']}/{len(MUTANTS)}  "
              f"oracle {totals['oracle']}/{len(MUTANTS)}")
        for cat, c in by_cat.items():
            print(f"   {cat:20s} n={c['n']:2d}  static {c['static']:2d}  sandbox {c['sandbox']:2d}  oracle {c['oracle']:2d}")
        print("   missed by oracle:", out["sheets"][sheet]["missed_by_oracle"])
    (ROOT / "docs" / "oracle-ablation.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
