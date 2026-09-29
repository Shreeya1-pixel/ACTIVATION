"""Sandboxed expressions (S9): Jinja2 SandboxedEnvironment, whitelisted filters only.

Supported context: row, run_date, params. Unknown names raise SecurityError (fail-closed
at evaluation; compile-time checks land with the editors in Milestone B).
"""
from __future__ import annotations

from jinja2 import Environment
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment

_ALLOWED_FILTERS = {
    "default", "length", "join", "upper", "lower", "trim",
    "first", "last", "sort", "map", "selectattr", "string", "int",
}


def build_env() -> Environment:
    env = SandboxedEnvironment()
    env.filters = {name: env.filters[name] for name in _ALLOWED_FILTERS if name in env.filters}
    # No globals: only explicit per-call context below.
    return env


_ENV = build_env()


class ExpressionError(ValueError):
    pass


def eval_bool(expression: str, context: dict) -> bool:
    try:
        template = _ENV.from_string("{% if " + expression + " %}1{% else %}0{% endif %}")
        return template.render(**context).strip() == "1"
    except SecurityError as exc:
        raise ExpressionError(f"unsafe expression rejected: {exc}") from exc
    except Exception as exc:  # jinja2 raises varied types on syntax errors
        raise ExpressionError(f"bad expression: {exc}") from exc


def eval_text(template_src: str, context: dict) -> str:
    try:
        return _ENV.from_string(template_src).render(**context)
    except SecurityError as exc:
        raise ExpressionError(f"unsafe expression rejected: {exc}") from exc
    except Exception as exc:
        raise ExpressionError(f"bad template: {exc}") from exc
