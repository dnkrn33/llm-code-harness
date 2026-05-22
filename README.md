# LLM Code Harness

A lightweight local harness for Claude Code, Codex, and other coding agents. It keeps large repositories, logs, schemas, and command output on your machine, then sends only the compact context needed for a task.

## Purpose

LLM coding agents are strongest when they receive precise context. They become expensive and noisy when given full projects, full logs, generated folders, or secrets. This harness provides a small command-line layer that:

- indexes project structure and symbols
- retrieves targeted context bundles
- reduces logs to recent failure blocks
- runs only allowlisted local commands
- applies unified diff patches with backups
- records token-saving reports for each task

## Installation

Requires Python 3.10+.

```bash
cd llm-harness
python harness.py index
```

When used from a Codex skill or another folder, the harness operates on the current working directory by default. Set `HARNESS_ROOT=/path/to/project` to target a different project.
You can also pass `--root` before the command:

```bash
python harness.py --root /path/to/project index
```

No Python packages are required. If `ripgrep` is installed, keep it in the command allowlist for agent workflows that need fast searching.

## Usage

Build or refresh the local index:

```bash
python harness.py index
```

Check the active root, config, index, Python version, and local tools:

```bash
python harness.py doctor
```

Retrieve compact context for a task:

```bash
python harness.py context "Fix Django TemplateDoesNotExist base.html"
```

Reduce a log file to recent useful failure blocks:

```bash
python harness.py logs /var/log/apache2/error.log
```

Run an allowlisted command:

```bash
python harness.py run "python manage.py check"
python harness.py run "pytest"
python harness.py run "git diff"
```

Apply a unified diff patch:

```bash
python harness.py patch fix.patch
```

Show the accumulated report:

```bash
python harness.py report
```

## How It Reduces Token Usage

The indexer stores metadata in `.harness/index.json`: filenames, file kinds, symbols, routes, SQL/config files, and error-looking snippets. The retriever scores files against the task, then extracts matching functions, classes, nearby imports, and line windows instead of full files. The log reducer reads the tail of a log and returns only recent error, warning, traceback, failed SQL, and failed command blocks.

Each task records:

- files inspected
- files skipped
- estimated tokens saved
- commands executed
- final diff summary

## Claude Code / Codex Workflow

1. Run `python harness.py index` after opening a project or changing many files.
2. Ask the agent to call `python harness.py context "<task>"` before reading large files.
3. Use `python harness.py logs <path>` instead of pasting full logs.
4. Use `python harness.py run "<command>"` for local checks. Only allowlisted commands run.
5. Ask the agent to produce minimal unified diffs, then apply them with `python harness.py patch fix.patch`.
6. Review `python harness.py report` before ending the task.

This keeps the model focused on the relevant parts of the codebase while local tooling handles search, validation, and noisy output.

## Security

The harness does not automatically run destructive commands. It blocks shell control operators and common dangerous executables. It redacts common secrets in logs, configs, command output, and context bundles, including password-like keys, API keys, bearer tokens, private keys, PostgreSQL URLs, and MySQL URLs.

Secret-like files such as `.env`, `*.pem`, `*.key`, and SSH private key names are skipped by the indexer.

## Safe Command Allowlist

Edit `config.yaml` to change command policy:

```yaml
allowlist:
  - git status
  - git diff
  - grep
  - rg
  - php -l
  - composer validate
  - python manage.py check
  - pytest
  - npm test
```

Read-only PostgreSQL queries are allowed when passed through `psql -c` and beginning with `SELECT`, `SHOW`, `EXPLAIN`, or `WITH`. Mutating SQL keywords are blocked.

## Project Layout

```text
llm-harness/
  harness.py
  config.yaml
  README.md
  modules/
    indexer.py
    retriever.py
    log_reducer.py
    command_runner.py
    patcher.py
    security.py
    reporting.py
  .harness/
    index.json
```

`.harness/` is generated at runtime.

## Notes

This first version is intentionally simple and extensible. It uses broad language-aware heuristics rather than full parsers for every stack, with Python AST support for Python symbols and regex-based detection for common web, SQL, config, PHP, Java, JavaScript, TypeScript, Go, Ruby, Rust, and generic text files.
