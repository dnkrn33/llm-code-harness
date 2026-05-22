#!/usr/bin/env python3
"""LLM Code Harness CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from modules.command_runner import DEFAULT_ALLOWLIST, run_allowed
from modules.indexer import index_repository
from modules.log_reducer import reduce_log
from modules.patcher import apply_patch
from modules.reporting import append_task, summarize_report
from modules.retriever import build_context_bundle
from modules.security import redact


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("HARNESS_ROOT", Path.cwd())).resolve()
HARNESS_DIR = ROOT / ".harness"
INDEX_PATH = HARNESS_DIR / "index.json"
CONFIG_PATH = ROOT / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict[str, Any]:
    config: dict[str, Any] = {
        "ignore_dirs": [],
        "allowlist": DEFAULT_ALLOWLIST,
        "context": {"max_files": 8},
        "logs": {"max_blocks": 8},
    }
    if not CONFIG_PATH.exists():
        return config
    current_key: str | None = None
    for raw in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        if re.match(r"^[A-Za-z_][\w-]*:", line):
            key, _, rest = line.partition(":")
            current_key = key.strip()
            if rest.strip():
                config[current_key] = rest.strip()
            elif isinstance(config.get(current_key), list):
                config[current_key] = []
            elif current_key not in config:
                config[current_key] = []
        elif line.strip().startswith("-") and current_key:
            value = line.strip()[1:].strip()
            config.setdefault(current_key, [])
            if isinstance(config[current_key], list):
                config[current_key].append(value)
        elif ":" in line and current_key:
            key, _, value = line.strip().partition(":")
            parent = config.setdefault(current_key, {})
            if isinstance(parent, dict):
                parent[key.strip()] = int(value.strip()) if value.strip().isdigit() else value.strip()
    return config


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_index(_: argparse.Namespace) -> None:
    config = load_config()
    index = index_repository(ROOT, INDEX_PATH, ignore_dirs=config.get("ignore_dirs", []))
    append_task(ROOT, {
        "kind": "index",
        "files_inspected": [item["path"] for item in index["files"]],
        "files_skipped": [item["path"] for item in index["skipped"]],
        "tokens_saved_estimate": 0,
        "commands_executed": [],
        "final_diff_summary": [],
    })
    print_json({"indexed": index["file_count"], "skipped": index["skipped_count"], "output": str(INDEX_PATH)})


def cmd_context(args: argparse.Namespace) -> None:
    config = load_config()
    max_files = int(config.get("context", {}).get("max_files", 8)) if isinstance(config.get("context"), dict) else 8
    bundle = build_context_bundle(ROOT, INDEX_PATH, args.task, limit=max_files, allow_full=args.full)
    append_task(ROOT, {
        "kind": "context",
        "task": args.task,
        "files_inspected": bundle["files_inspected"],
        "files_skipped": bundle["files_skipped_sample"],
        "tokens_saved_estimate": bundle["tokens_saved_estimate"],
        "commands_executed": [],
        "final_diff_summary": [],
    })
    print_json(bundle)


def cmd_logs(args: argparse.Namespace) -> None:
    config = load_config()
    limit = int(config.get("logs", {}).get("max_blocks", 8)) if isinstance(config.get("logs"), dict) else 8
    result = reduce_log(Path(args.path), limit=limit)
    append_task(ROOT, {
        "kind": "logs",
        "files_inspected": [args.path],
        "files_skipped": [],
        "tokens_saved_estimate": max(0, Path(args.path).stat().st_size // 4 - len(json.dumps(result)) // 4),
        "commands_executed": [],
        "final_diff_summary": [],
    })
    print_json(result)


def cmd_run(args: argparse.Namespace) -> None:
    config = load_config()
    allowlist = config.get("allowlist", DEFAULT_ALLOWLIST)
    if not isinstance(allowlist, list):
        allowlist = DEFAULT_ALLOWLIST
    result = run_allowed(args.command, ROOT, allowlist=allowlist)
    append_task(ROOT, {
        "kind": "run",
        "files_inspected": [],
        "files_skipped": [],
        "tokens_saved_estimate": max(0, len(result.get("output", "")) // 2),
        "commands_executed": [args.command] if result.get("allowed") else [],
        "final_diff_summary": [],
    })
    print_json(result)


def cmd_patch(args: argparse.Namespace) -> None:
    result = apply_patch(ROOT, Path(args.path))
    append_task(ROOT, {
        "kind": "patch",
        "files_inspected": [args.path],
        "files_skipped": [],
        "tokens_saved_estimate": 0,
        "commands_executed": ["git apply --check", "git apply"] if result.get("applied") else ["git apply --check"],
        "final_diff_summary": result.get("changed_files", []),
    })
    print_json(result)


def cmd_report(_: argparse.Namespace) -> None:
    report = json.loads(redact(json.dumps(summarize_report(ROOT))))
    print_json(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local LLM Code Harness")
    sub = parser.add_subparsers(required=True)
    index_cmd = sub.add_parser("index", help="scan repository and build .harness/index.json")
    index_cmd.set_defaults(func=cmd_index)
    context_cmd = sub.add_parser("context", help="retrieve a compact context bundle for a task")
    context_cmd.add_argument("task")
    context_cmd.add_argument("--full", action="store_true", help="allow full file loading for selected files")
    context_cmd.set_defaults(func=cmd_context)
    logs_cmd = sub.add_parser("logs", help="reduce a log file to useful failure blocks")
    logs_cmd.add_argument("path")
    logs_cmd.set_defaults(func=cmd_logs)
    run_cmd = sub.add_parser("run", help="run an allowlisted command safely")
    run_cmd.add_argument("command")
    run_cmd.set_defaults(func=cmd_run)
    patch_cmd = sub.add_parser("patch", help="apply a unified diff patch with backups")
    patch_cmd.add_argument("path")
    patch_cmd.set_defaults(func=cmd_patch)
    report_cmd = sub.add_parser("report", help="show token-saving task report")
    report_cmd.set_defaults(func=cmd_report)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
