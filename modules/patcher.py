"""Minimal unified-diff patch application."""

from __future__ import annotations

import difflib
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def snapshot_diff(root: Path) -> str:
    try:
        proc = subprocess.run(["git", "diff", "--"], cwd=str(root), capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            return proc.stdout
    except FileNotFoundError:
        pass
    return ""


def backup_files(root: Path, patch_text: str) -> list[str]:
    backup_dir = root / ".harness" / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    files = sorted(set(
        line[4:].strip()
        for line in patch_text.splitlines()
        if line.startswith(("--- ", "+++ ")) and not line.endswith("/dev/null")
    ))
    backed_up = []
    for item in files:
        rel = item[2:] if item.startswith(("a/", "b/")) else item
        path = (root / rel).resolve()
        if root.resolve() not in path.parents and path != root.resolve():
            continue
        if path.exists() and path.is_file():
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            backed_up.append(rel)
    return backed_up


def patch_targets(patch_text: str) -> list[str]:
    targets = []
    for line in patch_text.splitlines():
        if line.startswith("+++ ") and not line.endswith("/dev/null"):
            rel = line[4:].strip()
            targets.append(rel[2:] if rel.startswith("b/") else rel)
    return sorted(set(targets))


def parse_hunk_header(header: str) -> tuple[int, int]:
    match = header.split("@@")[1].strip()
    old_part, new_part = match.split()[:2]
    start = int(new_part[1:].split(",", 1)[0])
    return start, int(old_part[1:].split(",", 1)[0])


def apply_unified_diff_fallback(root: Path, patch_text: str) -> tuple[bool, str, list[str]]:
    lines = patch_text.splitlines()
    i = 0
    changed: list[str] = []
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        old_name = lines[i][4:].strip()
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            return False, "invalid unified diff: missing +++ header", changed
        new_name = lines[i][4:].strip()
        rel = new_name[2:] if new_name.startswith("b/") else new_name
        if rel == "/dev/null":
            rel = old_name[2:] if old_name.startswith("a/") else old_name
        target = (root / rel).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            return False, f"patch target escapes repository: {rel}", changed
        original = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        output: list[str] = []
        cursor = 0
        i += 1
        while i < len(lines) and lines[i].startswith("@@"):
            _, old_start = parse_hunk_header(lines[i])
            hunk_start = max(0, old_start - 1)
            output.extend(original[cursor:hunk_start])
            cursor = hunk_start
            i += 1
            while i < len(lines) and not lines[i].startswith(("@@", "--- ")):
                line = lines[i]
                if not line:
                    prefix, body = " ", ""
                else:
                    prefix, body = line[0], line[1:]
                if prefix == " ":
                    if cursor >= len(original) or original[cursor] != body:
                        return False, f"context mismatch applying patch to {rel}", changed
                    output.append(original[cursor])
                    cursor += 1
                elif prefix == "-":
                    if cursor >= len(original) or original[cursor] != body:
                        return False, f"delete mismatch applying patch to {rel}", changed
                    cursor += 1
                elif prefix == "+":
                    output.append(body)
                elif prefix == "\\":
                    pass
                else:
                    return False, f"unsupported patch line in {rel}: {line}", changed
                i += 1
        output.extend(original[cursor:])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(output) + ("\n" if output else ""), encoding="utf-8")
        changed.append(rel)
    return True, "applied with standard-library fallback", sorted(set(changed))


def apply_patch(root: Path, patch_path: Path) -> dict:
    patch_text = patch_path.read_text(encoding="utf-8")
    before = snapshot_diff(root)
    backed_up = backup_files(root, patch_text)
    try:
        proc = subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=str(root), capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            apply_proc = subprocess.run(["git", "apply", str(patch_path)], cwd=str(root), capture_output=True, text=True, check=False)
            ok = apply_proc.returncode == 0
            output = apply_proc.stdout + apply_proc.stderr
        else:
            ok = False
            output = proc.stdout + proc.stderr
    except FileNotFoundError:
        ok, output, fallback_changed = apply_unified_diff_fallback(root, patch_text)
    after = snapshot_diff(root)
    changed = sorted(set(
        line.split(maxsplit=2)[-1]
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="")
        if line.startswith(("+++ b/", "--- a/"))
    ))
    if not changed and "fallback_changed" in locals():
        changed = fallback_changed
    if not changed:
        changed = patch_targets(patch_text) if ok else []
    return {
        "patch": str(patch_path),
        "applied": ok,
        "backed_up_files": backed_up,
        "changed_files": changed,
        "output": output.strip(),
    }
