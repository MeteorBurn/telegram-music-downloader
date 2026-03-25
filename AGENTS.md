# AGENTS.md
## Purpose
Guidance for coding agents working in `E:\Projects\telegram-music-downloader`.

This repo is a Python 3.9+ CLI app that downloads audio/media from Telegram via
Telethon, stores runtime state in JSON files, and uses `asyncio` for concurrent
downloads.

## Key Files
- `src/main.py` - CLI entry point and orchestration
- `src/config_loader.py` - config loading and validation
- `src/client.py` - Telegram auth/client setup
- `src/session_manager.py` - session file helpers
- `src/message_parser.py` / `src/media_filter.py` - parsing and filtering
- `src/downloader.py` / `src/download_*` - download pipeline
- `src/download_monitor.py` - progress display
- `src/channel_utils.py` - per-channel folder naming and paths
- `src/normalizer.py` - optional track-name normalization
- `src/tracker.py` - persistent JSON trackers
- `src/logger.py` - logging setup
- `data/` - sessions, logs, downloads, tracker files

## Cursor / Copilot Rules
No repository-specific rule files were found during analysis.
- No `.cursor/rules/`
- No `.cursorrules`
- No `.github/copilot-instructions.md`

If any of these files are added later, merge their instructions here and follow
the more specific rule.

## Source of Truth
When docs and code disagree, prefer the actual implementation in:
- `src/main.py`
- `src/config_loader.py`
- `src/tracker.py`
- `src/channel_utils.py`

`README.md` is useful, but some behavior descriptions are partially outdated.

## Setup
Run commands from the repository root.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux use `source venv/bin/activate`.

## Build / Run / Lint / Test Commands
There is no formal build system, linter config, or committed test suite.
There is also no CI/CD workflow checked into `.github/`.

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run the app
```bash
python src/main.py
python src/main.py --config src/config.yaml
python src/main.py --workers 3
python src/main.py --max-files 20
python src/main.py --stats
python src/main.py --cleanup
python src/main.py --progress
```

### Build-like validation
```bash
python -m compileall src
```

### Linting
No linter is configured in-repo.
- Do not invent mandatory lint tooling in routine changes.
- For a quick sanity check, use `python -m compileall src`.
- If asked for linting, explain that `ruff`, `flake8`, `pylint`, and `mypy`
  are not configured here.

### Tests
No automated tests are committed right now.
- No `tests/` directory
- No `pytest.ini`, `tox.ini`, or `pyproject.toml`
- `pytest` is not listed in `requirements.txt`

### Single-test commands
There is no current test target to run. If pytest tests are added later, use:
```bash
python -m pytest
python -m pytest tests/test_tracker.py
python -m pytest tests/test_tracker.py -k last_processed
python -m pytest tests/test_tracker.py::test_mark_message_processed
```

## Import Model and Layout
Modules under `src/` import each other with plain local imports, not package
imports. Keep following that pattern unless the whole project is deliberately
refactored into a package.

Examples from the codebase:
- `from config_loader import ConfigLoader`
- `from tracker import TrackerManager`
- `import normalizer`

- Keep new runtime modules in `src/`.
- Do not introduce isolated `from src...` imports.

## Config, Secrets, and State
- Main config: `src/config.yaml`
- Local secrets: `src/local_config.yaml`
- Runtime state: `data/sessions/`, `data/logs/`, `data/`

Rules:
- `src/local_config.yaml` overrides values from `src/config.yaml` when present.
- Never print or commit secret values from `src/local_config.yaml`.
- Never commit `*.session`, logs, or downloaded media unless asked.
- Redact Telegram credentials in summaries.
- Remember that `ConfigLoader` creates directories as a side effect.

## Current Behavior Notes
- `src/client.py` uses interactive login when no valid Telegram session exists.
- `--progress` in `src/main.py` is a separate display path, not a full download
  session mode by itself.
- `--stats` and `--cleanup` operate on trackers initialized in the current run;
  they are not a full repository-wide scan of all channel folders.
- Message processing and file download tracking are separate concerns; be careful
  when changing tracker semantics.
- Channel folder naming uses the config-specified channel identifier as-is in the
  final folder name, while sanitizing only the title part.

## Code Style Guidelines
Follow existing repository style over external defaults.

### Formatting
- Use 4-space indentation.
- Keep code roughly PEP 8-like; no formatter is enforced.
- Use double-quoted docstrings.
- Preserve the current blank-line spacing between top-level definitions.
- Keep files ASCII unless Unicode is already present or necessary.

### Imports
- Group imports as standard library, third-party, then local modules.
- Prefer one import per line unless names are tightly related.
- Prefer `pathlib.Path` for filesystem work.
- Avoid adding unused imports.

### Types
- Add type hints to new public functions and meaningful helpers.
- Match the existing style: `Dict[str, Any]`, `List[...]`, `Optional[...]`, and
  built-in generics where already used.
- Preserve async return annotations for coroutines and async iterators.

### Naming
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Variables/attributes: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Factory helpers use `create_*` names.
- Prefer descriptive names like `message_info`, `channel_result`, and
  `file_tracker`.

### Async and Concurrency
- Keep Telegram/network workflows async.
- Use `async def`/`await` consistently through the call chain.
- Use existing locking patterns for shared mutable state.
- Preserve chronological processing assumptions in tracker and queue logic.
- Do not describe the worker model as thread-based unless you are changing it;
  current concurrency is built on `asyncio` tasks and queues.

### Error Handling
- Log exceptions with enough context to identify the channel, message, or file.
- Raise when the caller can handle or surface the failure meaningfully.
- Keep structured status dicts only in places that already use them.
- Avoid broad silent `except` blocks; if you must catch broadly, log it.
- Do not hide failures that affect tracker correctness or download integrity.

### Logging and CLI Output
- Use `logging.getLogger(__name__)` in modules.
- Match the repo's logging-heavy operational style.
- Keep direct `print(...)` mostly in `src/main.py` CLI flows.
- Prefer concise log messages with useful identifiers.

### Filesystem and Persistence
- Tracker JSON files are part of the app's persistent state.
- Preserve atomic write patterns when editing tracker behavior.
- Avoid destructive cleanup of `data/` unless explicitly requested.
- Be careful with naming-template, tracker-schema, and channel-folder changes;
  they affect resumability and duplicate detection.

## Recommended Post-Change Checks
```bash
python -m compileall src
```

If runtime behavior changed and safe credentials already exist, a focused smoke
check such as `python src/main.py --stats` is appropriate.

`src/client.py` uses interactive Telegram login when no valid session exists, so
avoid running live auth/download flows unless the task requires it.

Do not run live Telegram download flows unless the task requires it.
