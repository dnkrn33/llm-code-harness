"""Allowlisted local command runner."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from .security import is_allowed_command, redact, split_command


DEFAULT_ALLOWLIST = [
    "git status",
    "git diff",
    "grep",
    "rg",
    "php -l",
    "composer validate",
    "python manage.py check",
    "pytest",
    "npm test",
]


def run_allowed(command: str, cwd: Path, allowlist: Sequence[str] | None = None, timeout: int = 120) -> dict:
    allowlist = list(allowlist or DEFAULT_ALLOWLIST)
    allowed, reason = is_allowed_command(command, allowlist)
    if not allowed:
        return {"command": command, "allowed": False, "reason": reason, "returncode": None, "output": ""}
    parts = split_command(command)
    try:
        proc = subprocess.run(
            parts,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
        output = redact((proc.stdout or "") + (proc.stderr or ""))
        if len(output) > 12_000:
            output = output[-12_000:]
        return {
            "command": command,
            "allowed": True,
            "reason": reason,
            "returncode": proc.returncode,
            "output": output,
        }
    except FileNotFoundError as exc:
        return {"command": command, "allowed": True, "reason": reason, "returncode": 127, "output": str(exc)}
    except subprocess.TimeoutExpired as exc:
        output = redact(((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else "")
        return {"command": command, "allowed": True, "reason": reason, "returncode": 124, "output": output + "\n[TIMEOUT]"}
