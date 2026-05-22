"""Repository scanner that builds a compact searchable metadata index."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .security import is_secret_file, normalize_path, redact, should_ignore_dir


TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".php", ".java", ".cs", ".go", ".rb", ".rs",
    ".sql", ".html", ".htm", ".css", ".scss", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".env", ".md", ".txt", ".xml", ".properties",
}
CONFIG_NAMES = {
    "dockerfile", "makefile", "package.json", "composer.json", "pyproject.toml",
    "requirements.txt", "manage.py", "settings.py", "config.yaml", "config.yml",
    ".gitignore",
}
ERROR_RE = re.compile(r"(?i)\b(error|exception|traceback|warning|failed|fatal|template does not exist)\b")
ROUTE_RE = re.compile(
    r"(?i)(@(?:app|router)\.(?:get|post|put|patch|delete)|path\(|url\(|route\(|urlpatterns|Route::|router\.)"
)
FUNC_RE = re.compile(
    r"^\s*(?:async\s+)?(?:function\s+|def\s+|class\s+|public\s+|private\s+|protected\s+|static\s+|final\s+|func\s+|fn\s+)?"
    r"([A-Za-z_][\w$]*)\s*(?:\(|:|\{)"
)
CLASS_RE = re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_][\w$]*)")


@dataclass
class IndexedFile:
    path: str
    size: int
    extension: str
    kind: str
    symbols: list[dict] = field(default_factory=list)
    routes: list[dict] = field(default_factory=list)
    error_patterns: list[dict] = field(default_factory=list)


def iter_repo_files(root: Path, ignore_dirs: Iterable[str] = ()) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel_parts = path.relative_to(root).parts
        if any(should_ignore_dir(part, ignore_dirs) for part in rel_parts[:-1]):
            continue
        if rel_parts and rel_parts[0] == ".harness":
            continue
        yield path


def file_kind(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower()
    if ext == ".sql":
        return "sql"
    if ext in {".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json", ".properties"} or name in CONFIG_NAMES:
        return "config"
    if ext in {".log", ".out", ".err"}:
        return "log"
    if ext in {".py", ".js", ".jsx", ".ts", ".tsx", ".php", ".java", ".cs", ".go", ".rb", ".rs"}:
        return "source"
    return "text"


def safe_read_text(path: Path, max_bytes: int = 350_000) -> str:
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


def extract_python_symbols(text: str) -> list[dict]:
    symbols: list[dict] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append({
                "name": node.name,
                "type": "class" if isinstance(node, ast.ClassDef) else "function",
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
            })
    return sorted(symbols, key=lambda item: item["line"])


def extract_regex_symbols(text: str) -> list[dict]:
    symbols: list[dict] = []
    for i, line in enumerate(text.splitlines(), start=1):
        class_match = CLASS_RE.search(line)
        if class_match:
            symbols.append({"name": class_match.group(1), "type": "class", "line": i})
            continue
        func_match = FUNC_RE.search(line)
        if func_match:
            name = func_match.group(1)
            if name not in {"if", "for", "while", "switch", "catch", "return"}:
                symbols.append({"name": name, "type": "function", "line": i})
    return symbols


def extract_routes(text: str) -> list[dict]:
    routes = []
    for i, line in enumerate(text.splitlines(), start=1):
        if ROUTE_RE.search(line):
            routes.append({"line": i, "snippet": redact(line.strip())[:240]})
    return routes


def extract_errors(text: str) -> list[dict]:
    errors = []
    for i, line in enumerate(text.splitlines(), start=1):
        if ERROR_RE.search(line):
            errors.append({"line": i, "snippet": redact(line.strip())[:240]})
            if len(errors) >= 20:
                break
    return errors


def index_repository(root: Path, output: Path, ignore_dirs: Iterable[str] = ()) -> dict:
    root = root.resolve()
    files: list[IndexedFile] = []
    skipped: list[dict] = []
    for path in iter_repo_files(root, ignore_dirs):
        rel = normalize_path(path.relative_to(root))
        ext = path.suffix.lower()
        size = path.stat().st_size
        if is_secret_file(path):
            skipped.append({"path": rel, "reason": "secret file"})
            continue
        if ext not in TEXT_EXTENSIONS and path.name.lower() not in CONFIG_NAMES:
            skipped.append({"path": rel, "reason": "unsupported/binary extension"})
            continue
        try:
            text = safe_read_text(path)
        except OSError as exc:
            skipped.append({"path": rel, "reason": f"read failed: {exc}"})
            continue
        kind = file_kind(path)
        symbols = extract_python_symbols(text) if ext == ".py" else extract_regex_symbols(text)
        files.append(IndexedFile(
            path=rel,
            size=size,
            extension=ext,
            kind=kind,
            symbols=symbols[:200],
            routes=extract_routes(text)[:100],
            error_patterns=extract_errors(text),
        ))
    index = {
        "version": 1,
        "root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "skipped_count": len(skipped),
        "files": [asdict(item) for item in files],
        "skipped": skipped[:500],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index
