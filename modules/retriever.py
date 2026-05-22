"""Selective context retrieval from the harness index."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .indexer import safe_read_text
from .security import is_secret_file, normalize_path, redact


MAX_FULL_FILE_BYTES = 32_000
DEFAULT_CONTEXT_RADIUS = 24


def tokenize(query: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_./:-]{3,}", query)}


def load_index(index_path: Path) -> dict:
    if not index_path.exists():
        raise FileNotFoundError(f"index not found: {index_path}. Run `python harness.py index` first.")
    return json.loads(index_path.read_text(encoding="utf-8"))


def score_file(entry: dict, terms: set[str]) -> int:
    haystack_parts = [entry.get("path", ""), entry.get("kind", ""), entry.get("extension", "")]
    haystack_parts.extend(symbol.get("name", "") for symbol in entry.get("symbols", []))
    haystack_parts.extend(route.get("snippet", "") for route in entry.get("routes", []))
    haystack_parts.extend(err.get("snippet", "") for err in entry.get("error_patterns", []))
    haystack = " ".join(haystack_parts).lower()
    score = sum(4 for term in terms if term in entry.get("path", "").lower())
    score += sum(2 for term in terms if term in haystack)
    if entry.get("kind") in {"config", "sql"}:
        score += sum(1 for term in terms if term in haystack)
    return score


def imports_prefix(lines: list[str], max_lines: int = 80) -> list[str]:
    selected = []
    for line in lines[:max_lines]:
        stripped = line.strip()
        if stripped.startswith(("import ", "from ", "require(", "const ", "use ", "namespace ", "package ")):
            selected.append(line)
    return selected[:30]


def matching_windows(lines: list[str], terms: set[str], radius: int = DEFAULT_CONTEXT_RADIUS) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    lowered_terms = {term.lower() for term in terms}
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(term in lower for term in lowered_terms):
            start = max(0, i - radius)
            end = min(len(lines), i + radius + 1)
            windows.append((start, end))
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1] + 3:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged[:8]


def extract_context(root: Path, entry: dict, terms: set[str], allow_full: bool = False) -> dict:
    path = root / entry["path"]
    rel = normalize_path(path.relative_to(root))
    if is_secret_file(path):
        return {"path": rel, "skipped": True, "reason": "secret file"}
    text = safe_read_text(path)
    lines = text.splitlines()
    if allow_full or path.stat().st_size <= MAX_FULL_FILE_BYTES and not terms:
        body = redact("\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines)))
        return {"path": rel, "full": True, "content": body}
    sections = []
    prefix = imports_prefix(lines)
    if prefix:
        sections.append({"label": "nearby imports/setup", "start_line": 1, "content": redact("\n".join(prefix))})
    for start, end in matching_windows(lines, terms):
        content = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
        sections.append({"label": "matching section", "start_line": start + 1, "end_line": end, "content": redact(content)})
    if not sections:
        symbols = entry.get("symbols", [])[:10]
        content = "\n".join(f"{sym.get('line')}: {sym.get('type')} {sym.get('name')}" for sym in symbols)
        sections.append({"label": "symbol summary", "content": redact(content or "(no matching sections)")})
    return {"path": rel, "full": False, "sections": sections}


def build_context_bundle(root: Path, index_path: Path, task: str, limit: int = 8, allow_full: bool = False) -> dict:
    index = load_index(index_path)
    terms = tokenize(task)
    scored = [
        (score_file(entry, terms), entry)
        for entry in index.get("files", [])
    ]
    selected = [entry for score, entry in sorted(scored, key=lambda item: item[0], reverse=True) if score > 0][:limit]
    if not selected:
        selected = index.get("files", [])[: min(3, limit)]
    contexts = [extract_context(root, entry, terms, allow_full=allow_full) for entry in selected]
    inspected = [ctx["path"] for ctx in contexts]
    skipped = [entry["path"] for _, entry in scored if entry["path"] not in inspected][:25]
    total_bytes = sum(entry.get("size", 0) for _, entry in scored)
    sent_chars = sum(len(json.dumps(ctx)) for ctx in contexts)
    return {
        "task": task,
        "files_inspected": inspected,
        "files_skipped_sample": skipped,
        "tokens_saved_estimate": max(0, (total_bytes - sent_chars) // 4),
        "contexts": contexts,
    }
