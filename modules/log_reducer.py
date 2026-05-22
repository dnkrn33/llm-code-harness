"""Extract compact failure-oriented blocks from common log formats."""

from __future__ import annotations

import re
from pathlib import Path

from .security import redact


INTERESTING_RE = re.compile(
    r"(?i)(error|warn|warning|critical|fatal|traceback|exception|failed|sqlstate|syntax error|permission denied|template does not exist)"
)
START_RE = re.compile(r"^\s*(?:\d{4}[-/]\d{2}[-/]\d{2}|[A-Z][a-z]{2}\s+\d{1,2}|Traceback|Caused by:|org\.|javax\.|django\.)")


def tail_lines(path: Path, max_bytes: int = 1_000_000) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines()


def collect_block(lines: list[str], index: int, before: int = 4, after: int = 16) -> str:
    start = max(0, index - before)
    end = min(len(lines), index + after + 1)
    extra = index + 1
    while extra < len(lines) and extra < index + 80:
        line = lines[extra]
        if extra > index + after and START_RE.search(line) and not line.startswith((" ", "\t", "at ")):
            break
        if line.startswith((" ", "\t", "at ", "...", "Caused by:")):
            end = extra + 1
        extra += 1
    return redact("\n".join(lines[start:end]))


def reduce_log(path: Path, limit: int = 8) -> dict:
    lines = tail_lines(path)
    matches = [i for i, line in enumerate(lines) if INTERESTING_RE.search(line)]
    latest = matches[-limit:]
    blocks = []
    seen = set()
    for i in latest:
        block = collect_block(lines, i)
        if block not in seen:
            blocks.append({"line": i + 1, "block": block})
            seen.add(block)
    return {
        "path": str(path),
        "lines_scanned": len(lines),
        "blocks_returned": len(blocks),
        "blocks": blocks,
    }
