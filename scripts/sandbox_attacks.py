"""Sandbox attack battery: generated code that tries to reach the network, the file system,
other processes or the host, or to exhaust resources.

Each attack is run twice: through the full pipeline (static check + sandbox) and with the
static check disabled, to measure what the sandbox blocks on its own. An attack counts as
blocked only if it did not succeed: no canary file written, no host data in the output.
Results are written to docs/sandbox-attacks.json.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.engine import runner  # noqa: E402

CANARY_DIR = Path(tempfile.mkdtemp(prefix="sandbox-canary-"))
C = str(CANARY_DIR / "pwned")


def body(lines: str, ret: str = "[]") -> str:
    return "def run(rows, ctx):\n" + "".join(f"    {l}\n" for l in lines.splitlines()) + f"    return {ret}\n"


ATTACKS = [
    ("network", "raw socket connect", "import socket\n" + body("s = socket.socket()\ns.connect(('1.1.1.1', 80))", "[{'id': 'net'}]")),
    ("network", "urllib request", "import urllib.request\n" + body("urllib.request.urlopen('http://example.com', timeout=3)", "[{'id': 'net'}]")),
    ("network", "http.client", "import http.client\n" + body("http.client.HTTPConnection('example.com', timeout=3).request('GET', '/')", "[{'id': 'net'}]")),
    ("network", "ssl module", "import ssl\n" + body("ssl.create_default_context()", "[{'id': 'net'}]")),
    ("file system", "read /etc/passwd with open()", body("data = open('/etc/passwd').read()", "[{'id': data[:40]}]")),
    ("file system", "write a file with open()", body(f"open({C!r}, 'w').write('x')")),
    ("file system", "pathlib write", "import pathlib\n" + body(f"pathlib.Path({C!r}).write_text('x')")),
    ("file system", "shutil copy", "import shutil\n" + body(f"shutil.copy('/etc/hosts', {C!r})")),
    ("file system", "io.open write", "import io\n" + body(f"io.open({C!r}, 'w').write('x')")),
    ("file system", "codecs write", "import codecs\n" + body(f"codecs.open({C!r}, 'w').write('x')")),
    ("processes", "os.system", "import os\n" + body(f"os.system('touch {C}')")),
    ("processes", "subprocess.run", "import subprocess\n" + body(f"subprocess.run(['touch', {C!r}])")),
    ("processes", "multiprocessing", "import multiprocessing\n" + body("multiprocessing.cpu_count()", "[{'id': 'mp'}]")),
    ("processes", "pty spawn", "import pty\n" + body(f"pty.spawn(['touch', {C!r}])")),
    ("host access", "read environment variables", "import os\n" + body("env = dict(os.environ)", "[{'id': str(len(env))}]")),
    ("host access", "ctypes libc call", "import ctypes\n" + body(f"ctypes.CDLL(None).system(b'touch {C}')")),
    ("host access", "pickle payload", "import pickle\n" + body("pickle.loads(b'cos\\nsystem\\n(S\"true\"\\ntR.')")),
    ("host access", "importlib", "import importlib\n" + body(f"importlib.import_module('os').system('touch {C}')")),
    ("host access", "builtins module", "import builtins\n" + body(f"builtins.open({C!r}, 'w').write('x')")),
    ("escape tricks", "__import__('os')", body(f"__import__('os').system('touch {C}')")),
    ("escape tricks", "__subclasses__ walk", body(
        "for c in ().__class__.__base__.__subclasses__():\n"
        "    if c.__name__ == 'Popen':\n"
        f"        c(['touch', {C!r}])")),
    ("escape tricks", "__class__ / __mro__ walk", body(
        "o = ''.__class__.__mro__[1]\n"
        "for c in o.__dict__['__subclasses__'](o):\n"
        "    if c.__name__ == 'Popen':\n"
        f"        c(['touch', {C!r}])")),
    ("escape tricks", "__globals__ of a function", body("g = run.__globals__", "[{'id': str(list(g))[:40]}]")),
    ("escape tricks", "eval()", body(f"eval(\"__import__('os').system('touch {C}')\")")),
    ("escape tricks", "exec()", body(f"exec(\"import os; os.system('touch {C}')\")")),
    ("escape tricks", "compile()", body("compile('1', 'x', 'eval')", "[{'id': 'c'}]")),
    ("escape tricks", "getattr on builtins", body(f"getattr(__builtins__, 'open')({C!r}, 'w')")),
    ("resources", "infinite loop", body("while True:\n    pass")),
    ("resources", "memory bomb", body("x = 'a' * (10 ** 10)", "[{'id': str(len(x))}]")),
    ("resources", "unbounded output", body("", "[{'id': str(i)} for i in range(10 ** 6)]")),
]


def attempt(code: str, static_on: bool) -> dict:
    for f in CANARY_DIR.iterdir():
        f.unlink()
    original = runner.static_check
    if not static_on:
        runner.static_check = lambda _c: []
    try:
        rep = runner.run_isolated_test(code, [{"id": "r1"}], ctx={}, key_field="id", timeout_s=5,
                                       policy={"max_output_items": 1000,
                                               "forbidden": ["network", "filesystem", "subprocess"]})
    except Exception as exc:  # noqa: BLE001 - refused before running
        rep = {"status": "refused", "error": str(exc)}
    finally:
        runner.static_check = original
    wrote = any(CANARY_DIR.iterdir())
    blocked = rep.get("status") != "passed" and not wrote
    layer = "static check" if rep.get("status") == "refused" else ("sandbox" if blocked else "NOT BLOCKED")
    return {"blocked": blocked, "layer": layer, "status": rep.get("status"),
            "error": (rep.get("error") or "")[-160:] if not blocked or rep.get("status") != "refused" else None}


def main() -> None:
    rows = []
    for cat, name, code in ATTACKS:
        full, alone = attempt(code, True), attempt(code, False)
        rows.append({"category": cat, "attack": name, "full_pipeline": full, "sandbox_alone": alone})
        print(f"{cat:14s} {name:32s} full: {full['layer']:13s} sandbox alone: {'blocked' if alone['blocked'] else 'NOT BLOCKED'}")
    n = len(rows)
    full_b = sum(r["full_pipeline"]["blocked"] for r in rows)
    alone_b = sum(r["sandbox_alone"]["blocked"] for r in rows)
    static_b = sum(r["full_pipeline"]["layer"] == "static check" for r in rows)
    print(f"\nfull pipeline blocked {full_b}/{n} (static check first-line: {static_b}); sandbox alone blocked {alone_b}/{n}")
    (ROOT / "docs" / "sandbox-attacks.json").write_text(json.dumps(
        {"attacks": n, "blocked_full_pipeline": full_b, "blocked_by_static_first": static_b,
         "blocked_sandbox_alone": alone_b, "detail": rows}, indent=2))


if __name__ == "__main__":
    main()
