"""Security helpers for redaction and command safety."""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".next",
    ".nuxt",
    ".cache",
    "coverage",
}

SECRET_FILE_PATTERNS = {
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_dsa",
    "id_ed25519",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token|access[_-]?key|private[_-]?key)\b\s*[:=]\s*['\"]?([^'\"\s]+)"),
    re.compile(r"(?i)\b(authorization:\s*bearer)\s+([a-z0-9._\-]+)"),
    re.compile(r"(?i)\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\b(sk-[a-z0-9_\-]{16,})\b"),
    re.compile(r"postgres(?:ql)?://[^:\s]+:([^@\s]+)@"),
    re.compile(r"mysql://[^:\s]+:([^@\s]+)@"),
]

DANGEROUS_TOKENS = {
    "rm",
    "del",
    "erase",
    "rmdir",
    "format",
    "mkfs",
    "shutdown",
    "reboot",
    "curl",
    "wget",
    "scp",
    "ssh",
    "sudo",
    "chmod",
    "chown",
    "dd",
}


def normalize_path(path: str | Path) -> str:
    return str(Path(path).as_posix())


def should_ignore_dir(dirname: str, extra_ignores: Iterable[str] = ()) -> bool:
    name = dirname.strip("/\\")
    return name in DEFAULT_IGNORE_DIRS or name in set(extra_ignores)


def is_secret_file(path: str | Path) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_FILE_PATTERNS)


def redact(text: str) -> str:
    """Mask common secrets while preserving enough structure for debugging."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        def repl(match: re.Match[str]) -> str:
            groups = match.groups()
            if len(groups) >= 2:
                return match.group(0).replace(groups[-1], "[REDACTED]")
            return "[REDACTED]"

        redacted = pattern.sub(repl, redacted)
    return redacted


def redact_config_value(key: str, value: object) -> object:
    if re.search(r"(?i)(password|secret|token|key|credential)", key):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact(value)
    return value


def split_command(command: str) -> Sequence[str]:
    if os.name == "nt":
        return shlex.split(command, posix=False)
    return shlex.split(command)


def command_has_shell_control(command: str) -> bool:
    return bool(re.search(r"(\|\||&&|[;&|`<>])", command))


def is_read_only_psql(parts: Sequence[str]) -> bool:
    if not parts or Path(parts[0]).name.lower() != "psql":
        return False
    lowered = [p.lower() for p in parts]
    query = ""
    if "-c" in lowered:
        idx = lowered.index("-c")
        if idx + 1 < len(parts):
            query = parts[idx + 1].strip()
    if not query:
        return False
    return bool(re.match(r"(?is)^\s*(select|show|explain|with)\b", query)) and not re.search(
        r"(?is)\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|vacuum)\b",
        query,
    )


def is_allowed_command(command: str, allowlist: Sequence[str]) -> tuple[bool, str]:
    if command_has_shell_control(command):
        return False, "shell control operators are not allowed"
    try:
        parts = split_command(command)
    except ValueError as exc:
        return False, f"could not parse command: {exc}"
    if not parts:
        return False, "empty command"
    executable = Path(parts[0]).name.lower()
    if executable in DANGEROUS_TOKENS:
        return False, f"dangerous command blocked: {executable}"
    if is_read_only_psql(parts):
        return True, "read-only psql query"
    normalized = " ".join(parts).lower()
    for allowed in allowlist:
        allowed_norm = allowed.lower().strip()
        if normalized == allowed_norm or normalized.startswith(allowed_norm + " "):
            return True, f"matched allowlist: {allowed}"
    return False, "command is not in allowlist"
