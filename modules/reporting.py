"""Task report persistence for token-saving summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def report_path(root: Path) -> Path:
    return root / ".harness" / "report.json"


def load_report(root: Path) -> dict:
    path = report_path(root)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"tasks": []}


def append_task(root: Path, task: dict) -> dict:
    report = load_report(root)
    task["timestamp"] = datetime.now(timezone.utc).isoformat()
    report.setdefault("tasks", []).append(task)
    path = report_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def summarize_report(root: Path) -> dict:
    report = load_report(root)
    tasks = report.get("tasks", [])
    return {
        "task_count": len(tasks),
        "tokens_saved_estimate": sum(int(task.get("tokens_saved_estimate", 0)) for task in tasks),
        "commands_executed": [cmd for task in tasks for cmd in task.get("commands_executed", [])],
        "latest_tasks": tasks[-10:],
    }
