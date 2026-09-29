"""Capture settings: which folder the watcher reads, and per-file ID / tracked columns.

Stored as JSON in the data dir. Defaults keep the original behaviour: the sample
`watched` folder, ID column auto-suggested per file, every non-ID column tracked.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from backend.spike_config import DATA_DIR

CONFIG_FILE = DATA_DIR / "capture_config.json"
DEFAULT_FOLDER = DATA_DIR / "watched"

_BLOCKED_POSIX = ("/etc", "/bin", "/sbin", "/usr", "/var", "/System", "/Library", "/private",
                  "/dev", "/proc", "/sys", "/boot", "/root")
_BLOCKED_WIN = ("c:\\windows", "c:\\program files", "c:\\program files (x86)", "c:\\programdata")


class CaptureConfigError(ValueError):
    pass


def load() -> dict:
    cfg = {"folder": None, "files": {}}
    if CONFIG_FILE.is_file():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in ("folder", "files") if k in data})
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def folder(cfg: dict | None = None) -> Path:
    cfg = cfg or load()
    return Path(cfg["folder"]) if cfg.get("folder") else DEFAULT_FOLDER


def file_settings(cfg: dict, name: str) -> dict:
    s = (cfg.get("files") or {}).get(name) or {}
    return {"id_column": s.get("id_column") or None, "columns": s.get("columns") or None,
            "sheet": s.get("sheet") or None}


def validate_folder(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise CaptureConfigError("folder is required")
    p = Path(os.path.expanduser(str(raw).strip()))
    if not p.is_absolute():
        raise CaptureConfigError("folder must be an absolute path")
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CaptureConfigError("folder does not exist") from exc
    if not p.is_dir():
        raise CaptureConfigError("path is not a folder")
    text = str(p)
    if sys.platform == "win32":
        low = text.lower().rstrip("\\")
        if len(low) <= 3 or any(low == b or low.startswith(b + "\\") for b in _BLOCKED_WIN):
            raise CaptureConfigError("system folders cannot be watched")
    else:
        home = str(Path.home().resolve())
        allowed_private = text.startswith("/private/tmp") or text.startswith("/private/var/folders")
        if text == "/" or text == home or (
                any(text == b or text.startswith(b + "/") for b in _BLOCKED_POSIX) and not allowed_private):
            raise CaptureConfigError("system folders (or your whole home folder) cannot be watched")
    return p


def save(new_folder: str | None, files: dict | None) -> dict:
    cfg = load()
    if new_folder is not None:
        cfg["folder"] = str(validate_folder(new_folder)) if new_folder else None
    if files is not None:
        clean: dict[str, dict] = {}
        for name, s in files.items():
            if not isinstance(s, dict) or "/" in name or "\\" in name or name.startswith("."):
                raise CaptureConfigError(f"invalid file entry: {name!r}")
            cols = s.get("columns")
            if cols is not None and (not isinstance(cols, list) or not all(isinstance(c, str) for c in cols)):
                raise CaptureConfigError(f"{name}: columns must be a list of names")
            clean[name] = {"id_column": s.get("id_column") or None, "columns": cols or None,
                           "sheet": s.get("sheet") or None}
        cfg["files"] = clean
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg
