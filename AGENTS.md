# AGENTS.md
## Purpose
Guidance for coding agents working in `E:\Projects\telegram-music-downloader`.

This repo is a Python 3.9+ CLI app that downloads audio/media from Telegram via
Telethon, stores runtime state in JSON files, and uses `asyncio` for concurrent
downloads.

## Key Files
- `src/main.py` - CLI entry point only
- `src/app.py` - application/session orchestration and session helpers
- `src/config.py` - config loading, validation, and path getters
- `src/telegram.py` - Telegram auth/client setup, message parsing, locator reconstruction
- `src/channels.py` - per-channel orchestration, filtering, and channel path helpers
- `src/download.py` - download pipeline and optional track-name normalization
- `src/renamer.py` - track-name normalization helpers used before final save name is kept on disk
- `src/runtime.py` - queue, workers, coordinator, and progress display
- `src/models.py` - shared typed domain/state models
- `src/state.py` - persistent JSON state stores and tracker management
- `src/logger.py` - centralized session logger and CLI transcript helpers
- `tests/test_app.py` - app/session orchestration tests
- `tests/test_runtime.py` - runtime/download/channel tests
- `tests/test_state.py` - tracker/state persistence tests
- `tests/test_logging.py` - logging contract tests
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
- `src/app.py`
- `src/config.py`
- `src/state.py`
- `src/channels.py`

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
python -m compileall src tests
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
python -m unittest tests.test_app
python -m unittest tests.test_runtime
python -m unittest tests.test_state
```

## Import Model and Layout
Modules under `src/` import each other with plain local imports, not package
imports. Keep following that pattern unless the whole project is deliberately
refactored into a package.

Examples from the codebase:
- `from config import ConfigLoader`
- `from state import TrackerManager`
- `from runtime import DownloadCoordinator`

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
- `src/telegram.py` uses interactive login when no valid Telegram session exists.
- The Telethon session file is always `telegram.session` in the repository root.
- `--progress` in `src/main.py` is a separate display path, not a full download
  session mode by itself; standalone `--progress` only reports live in-process
  progress and is not a persisted historical view.
- `--stats` and `--cleanup` scan the configured `download.output_dir` for
  `scan_state.json` and `download_state.json` files on disk.
- Message processing and file download tracking are separate concerns; be careful
  when changing tracker semantics.
- Message outcomes now distinguish `failed` from `critical`:
  `failed` is checkpoint-safe, while `critical` blocks checkpoint advancement.
- Any runtime `critical` condition is treated as stop-worthy: the active session
  is aborted and a red-highlighted `[CRITICAL]` line is emitted to console/log.
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
- Live redraw progress from `src/runtime.py` is intentionally screen-only
  and should not spam `console.log` on every refresh tick.
- `src/telegram.py` currently reconstructs a downloadable Telegram
  `Document` from stored locator fields; this works for current clean usage but
  is still a technical-debt boundary.

## Remaining Improvements
Keep these in mind for future work; they are not required for the current clean
setup but are the main known follow-ups.

- Run a deliberate manual `resume / repeated run / cleanup / re-download missing files`
  verification cycle on real data and keep notes about expected behavior.
- Revisit `src/telegram.py` and `src/download.py` if a more robust
  Telegram message/document retrieval path is needed later.
- Review the normalization helpers in `src/renamer.py` separately; track-name
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

#### Log Message Markers
All runtime log messages use a consistent `[TAG]` prefix at the start of the
message text. Do not use Unicode symbols (`✓`, `✗`, `→`) — use ASCII markers only.

| Marker | Meaning | Modules |
|---|---|---|
| `[OK]` | Successful download | `download.py` |
| `[FAIL]` | Error or failure of any kind | all modules |
| `[CRITICAL]` | Critical failure that aborts the active session | `runtime.py`, `channels.py` |
| `[FILTER]` | File rejected by filter | `channels.py` |
| `[QUEUE]` | File added to download queue | `channels.py` |
| `[NORM]` | Track name normalized | `download.py`, `renamer.py` |
| `[TRACK]` | File registered in tracker (DEBUG only) | `state.py` |
| `[BLACKLIST]` | Blacklist add/remove | `state.py` |
| `[CHANNEL]` | Channel processing events | `channels.py`, `telegram.py` |
| `[AUTH]` | Telegram auth/connect events | `telegram.py` |
| `[INIT]` | Initialization events | `coordinator`, `worker pool`, `tracker` |
| `[STOP]` | Shutdown events | `coordinator`, `worker pool` |
| `[WAIT]` | Waiting for queue completion | `runtime.py` |
| `[SESSION]` | Session-level progress | `app.py` |
| `[CLEANUP]` | Tracker cleanup | `app.py`, `state.py` |
| `[STATS]` | Statistics display | `app.py` |
| `[RESULTS]` | Session results block | `main.py` |
| `[SUMMARY]` | Download summary block | `runtime.py` |
| `[WARN]` | Non-fatal warning context | `state.py`, `channels.py` |
| `[WORKER_N]` | Per-worker prefix | `runtime.py` |

Worker events always include the worker identifier:
```
[WORKER_3] -> Downloading: track.wav [07:30] [70.0 MB]
[WORKER_3] [OK] Completed: track.wav
[WORKER_3] Skipped: track.wav
[WORKER_3] [FAIL] Failed: track.wav
```

#### Log Levels
- `INFO` — all user-visible session events: auth, channel scan, queue, skip, download, summary, errors.
- `DEBUG` — internal diagnostics: `[TRACK]` tracker records, rate limiter tokens, queue internals.
- `WARNING` — recoverable issues: invalid date format, blacklist ops, missing-on-disk files, Telegram internal errors, shutdown timeouts.
- `ERROR` — failures that affect correctness: download errors, failed queue ops, entity resolution failures, state load failures.
- `CRITICAL` — stop-worthy runtime failures; session is aborted immediately.

Do not log `Rate limit: ... req/sec`, `Queue size: ...`, or `coordinator started successfully`
at `INFO` level — these belong at `DEBUG`.

#### Empty Lines in Logs
`emit_session_lines()` skips empty strings in the log file (they go to console only).
Use separator strings like `"-" * 40` or `"=" * 50` as content lines, not empty entries.

### Filesystem and Persistence
- Tracker JSON files are part of the app's persistent state.
- Preserve atomic write patterns when editing tracker behavior.
- Avoid destructive cleanup of `data/` unless explicitly requested.
- Be careful with naming-template, tracker-schema, and channel-folder changes;
  they affect resumability and duplicate detection.

## Recommended Post-Change Checks
```bash
python -m compileall src tests
python -m unittest tests.test_app
python -m unittest tests.test_logging
python -m unittest tests.test_runtime
python -m unittest tests.test_state
python -m unittest discover -s tests
```

If runtime behavior changed and safe credentials already exist, a focused smoke
check such as `python src/main.py --stats` is appropriate.

`src/telegram.py` uses interactive Telegram login when no valid session exists, so
avoid running live auth/download flows unless the task requires it.

Do not run live Telegram download flows unless the task requires it.
