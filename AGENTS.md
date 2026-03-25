# AGENTS.md
## Purpose
Guidance for coding agents working in `E:\Projects\telegram-music-downloader`.

This repo is a Python 3.9+ CLI app that downloads audio/media from Telegram via
Telethon, stores runtime state in JSON files, and uses `asyncio` for concurrent
downloads.

## Key Files
- `src/main.py` - CLI entry point only
- `src/session_runner.py` - application/session orchestration
- `src/config_loader.py` - config loading and validation
- `src/client.py` - Telegram auth/client setup
- `src/session_manager.py` - session file helpers
- `src/channel_processor.py` - per-channel orchestration and queueing
- `src/message_parser.py` / `src/media_filter.py` - parsing and filtering
- `src/downloader.py` / `src/download_*` - download pipeline
- `src/domain_models.py` - shared typed domain/state models
- `src/download_monitor.py` - progress display
- `src/channel_utils.py` - per-channel folder naming and paths
- `src/normalizer.py` - optional track-name normalization
- `src/tracker.py` / `src/state_store.py` - persistent JSON state stores
- `src/logger.py` - centralized session logger and CLI transcript helpers
- `tests/` - synthetic tests and current local download target during development
- `telegram.session` - Telethon session file stored at project root

## Cursor / Copilot Rules
No repository-specific rule files were found during analysis.
- No `.cursor/rules/`
- No `.cursorrules`
- No `.github/copilot-instructions.md`

If any of these files are added later, merge their instructions here and follow
the more specific rule.

## Source of Truth
When docs and code disagree, prefer the actual implementation in:
- `src/session_runner.py`
- `src/config_loader.py`
- `src/tracker.py`
- `src/channel_utils.py`

`README.md` is useful and should generally match the current implementation.

## Setup
Run commands from the repository root.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux use `source venv/bin/activate`.

## Build / Run / Lint / Test Commands
There is no formal build system or linter config.
There is also no CI/CD workflow checked into `.github/`.

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run the app
```bash
python src/main.py
python src/main.py --config src/config.yaml
python src/main.py --config src/local_config.yaml
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
There is a small committed unittest-based test suite.
- Tests live under `tests/`
- No `pytest.ini`, `tox.ini`, or `pyproject.toml`
- `pytest` is not listed in `requirements.txt`

### Single-test commands
Use the standard library test runner:
```bash
python -m unittest discover -s tests
python -m unittest tests.test_logging
python -m unittest tests.test_logging.LoggingIntegrationTests
python -m unittest tests.test_phase1_refactor
python -m unittest tests.test_phase1_refactor.DownloadCoordinatorTests
python -m unittest tests.test_session_runner
python -m unittest tests.test_state_store
python -m unittest tests.test_downloader_contracts
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
- Telegram session: `telegram.session` in the project root
- Runtime state: per-channel state folders inside `download.output_dir`
- Scan checkpoint file: `scan_state.json` inside each channel folder
- Download state file: `download_state.json` inside each channel folder
- Session log: `console.log` inside `download.output_dir`

Rules:
- `src/local_config.yaml` overrides values from `src/config.yaml` when present.
- In normal local usage, prefer running with `--config src/local_config.yaml`.
- Never print or commit secret values from `src/local_config.yaml`.
- Never commit `*.session`, logs, or downloaded media unless asked.
- Redact Telegram credentials in summaries.
- Remember that `ConfigLoader` creates directories as a side effect.
- Do not reintroduce `logging.file` in YAML; log path is derived from `download.output_dir`.
- Do not rely on `telegram.session` being configurable; it is fixed intentionally.

## Current Behavior Notes
- `src/client.py` uses interactive login when no valid Telegram session exists.
- The Telethon session file is always `telegram.session` in the repository root.
- `--progress` in `src/main.py` is a separate display path, not a full download
  session mode by itself; standalone `--progress` only reports live in-process
  progress and is not a persisted historical view.
- `--stats` and `--cleanup` scan the configured `download.output_dir` for
  `scan_state.json` and `download_state.json` files on disk.
- Message processing and file download tracking are separate concerns; be careful
  when changing tracker semantics.
- The current persisted schema is versioned and intended for clean usage; backward
  compatibility with legacy `message_tracker.json` / `file_tracker.json` is not required.
- Channel folder naming uses the config-specified channel identifier as-is in the
  final folder name, while sanitizing only the title part.
- The shared session log file is always `console.log` in the configured
  `download.output_dir`.
- Console output must remain ASCII-safe on Windows terminals; Unicode may still
  be preserved in the UTF-8 log file.
- Runtime logging is centralized through `src/logger.py`; modules should obtain
  the shared project logger instead of configuring per-module handlers.
- `console.log` is intended to be a readable transcript of the session: startup,
  queueing, worker events, download outcomes, summaries, and top-level errors.
- Live redraw progress from `src/download_monitor.py` is intentionally screen-only
  and should not spam `console.log` on every refresh tick.
- `src/telegram_locator.py` currently reconstructs a downloadable Telegram
  `Document` from stored locator fields; this works for current clean usage but
  is still a technical-debt boundary.

## Remaining Improvements
Keep these in mind for future work; they are not required for the current clean
setup but are the main known follow-ups.

- Run a deliberate manual `resume / repeated run / cleanup / re-download missing files`
  verification cycle on real data and keep notes about expected behavior.
- Revisit `src/telegram_locator.py` and `src/downloader.py` if a more robust
  Telegram message/document retrieval path is needed later.
- Review `src/normalizer.py` behavior and naming output separately; track-name
  normalization was intentionally deferred from the main refactor phases.

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
- Use the shared logger helper from `src/logger.py` for runtime modules.
- Match the repo's logging-heavy operational style.
- Treat CLI-visible session messages as loggable events when they should appear
  in `console.log`.
- Keep direct `print(...)` mainly for live progress redraw/output that should not
  be mirrored line-for-line into the log file.
- Prefer concise log messages with useful identifiers.
- Treat `download.output_dir/console.log` as the single session log destination.
- Keep final session summary mirrored into `console.log`.
- A real smoke run with `--workers 5 --max-files 30` has been validated locally;
  worker start/download/completion/stop events were all captured in one
  `console.log` without dropped messages.

### Filesystem and Persistence
- Tracker JSON files are part of the app's persistent state.
- Preserve atomic write patterns when editing tracker behavior.
- Avoid destructive cleanup of `data/` unless explicitly requested.
- Be careful with naming-template, tracker-schema, and channel-folder changes;
  they affect resumability and duplicate detection.

## Recommended Post-Change Checks
```bash
python -m compileall src
python -m unittest tests.test_logging
python -m unittest tests.test_phase1_refactor
python -m unittest discover -s tests
```

If runtime behavior changed and safe credentials already exist, a focused smoke
check such as `python src/main.py --stats` is appropriate.

`src/client.py` uses interactive Telegram login when no valid session exists, so
avoid running live auth/download flows unless the task requires it.

Do not run live Telegram download flows unless the task requires it.
