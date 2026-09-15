# AGENTS.md

## Project and source map

Python 3.9+ CLI for downloading Telegram document media, including audio, through
Telethon. Channels are scanned sequentially; downloads run in concurrent `asyncio`
tasks. Runtime state is per-channel JSON. User setup and options are in [README.md](README.md).

| File | Responsibility |
|---|---|
| `src/main.py` | Argument parser, command dispatch, top-level results and errors |
| `src/app.py` | `SessionRunner`, client/component lifecycle, session limits, statistics and cleanup; session-file helpers |
| `src/config.py` | YAML merge, required-field validation, getters and directory creation |
| `src/telegram.py` | Authentication, entity resolution, chronological message parsing, document locator reconstruction |
| `src/channels.py` | Channel paths, pre-download filters, scan/queue orchestration and checkpoint callbacks |
| `src/download.py` | Skip checks, naming, download, duration validation, normalization and file registration |
| `src/renamer.py` | Pure filename cleanup functions |
| `src/runtime.py` | Priority queue, retries, rate limiter, workers, coordinator and progress/summary rendering |
| `src/models.py` | Typed messages, requests, outcomes and persisted-state models; dictionary adapters |
| `src/state.py` | Atomic JSON writes, scan checkpoints, downloaded-file registry, blacklist and state discovery |
| `src/logger.py` | Shared logger, rotating file handler, safe console output and transcript helpers |

Check the responsible implementation and its callers before documenting behavior.
Defaults in getters can differ from the values supplied by `src/config.yaml`.

## Working conventions

- Inspect `git status --short` and the existing diff before editing; preserve unrelated work.
- Keep the flat import model: `from config import ConfigLoader`, not isolated `from src...` imports.
- Match existing formatting: four spaces, type hints for meaningful interfaces, `Path` for paths.
- Preserve `DownloadRequest` context (`file_tracker`, `download_dir`, `outcome_callback`)
  and `extra_fields` when converting between typed objects and dictionaries.
- Keep Telegram I/O asynchronous and preserve the shared tracker/rate-limiter locks.
- Use the existing `requirements.txt` and `unittest` workflow. Reuse `venv` when available;
  installation instructions are in README. No formatter or linter is configured in this repo.
- Keep tests focused on download/filter behavior, file preservation and persisted paths.
  Reuse existing tests; check cosmetic filename rules with read-only examples/corpus runs
  rather than adding a test file or a large case list for every cleanup pattern.

## Configuration and side effects

- CLI default: `src/config.yaml`. `ConfigLoader` loads the selected base file, then
  deep-merges a sibling `local_config.yaml`; lists and scalar values are replaced.
- For a partial local override, run with the base config (or no `--config`). Passing
  `--config src/local_config.yaml` makes that file the base; required sections must
  then exist in it. There is no automatic load of `src/config.yaml` in that case.
- Required keys: `telegram.api_id` (integer), `telegram.api_hash`, `channels`,
  `download.output_dir`, `filters.file_types`, `filters.formats`.
- Relative config/output paths use the working directory. Run commands from the repo root.
  The Telethon session path is fixed relative to the source tree: `<repo>/telegram.session`.
- `ConfigLoader` creates directories. `SessionRunner` also opens/appends the log, including
  in utility modes. Use temporary configs/output directories for synthetic checks.
- `--workers` changes the in-memory config for the current run only. Use positive values.
- `download.worker_timeout` has a getter but no runtime caller; it does not enforce a
  download timeout. Worker-pool shutdown has its own hard-coded five-second timeout.
- Never print or commit local credentials, session files, logs or downloaded media.
  `.gitignore` covers `local_config.yaml`, sessions, `*.log` and `data/`; custom output
  locations and rotated log suffixes are not universally covered.
- Keep the log destination derived from `download.output_dir`; do not add `logging.file`.

## Runtime and persistence contracts

### Scan and queue

- `MessageParser.parse_messages()` uses `reverse=True`, then `min_id` for a saved
  checkpoint or `offset_date` for the configured start date. Checkpoints take precedence.
- `ChannelProcessor` registers messages in scan order. No media, invalid locator and
  pre-download filter rejection produce `skipped`; queued messages finish via callbacks.
- Session limits count newly queued tasks across all channels, including tasks later
  skipped or failed. The smaller positive config/CLI limit applies; zero adds no limit.
- Queue identity is `(channel_id, message_id)`; priority starts at message ID.
  Normal failed downloads allow up to three attempts. Retry accounting must balance
  queue `put`, `task_done` and `join`; retries do not increment the session file count.
- The shared rate limiter runs before each worker download attempt. It does not limit
  every Telethon request or file-transfer chunk.
- Queue rejection raises in `ChannelProcessor`. Recorded queue critical failures are
  checked by `DownloadCoordinator.wait_completion()`. Do not promise immediate
  cancellation of an ongoing scan for every critical condition.

### State files

- Each channel has `scan_state.json`, `download_state.json` and a `downloads/` directory
  under `{sanitized_title}_{config_channel_id}`. Only the title is sanitized; the
  configured identifier is preserved. Discovery uses immediate children of `output_dir`.
- Both state stores currently default to `schema_version: 2`. Legacy
  `message_tracker.json` / `file_tracker.json` are not discovered or migrated.
- `MessageTracker` commits only the contiguous prefix of registered messages whose
  outcomes are `completed`, `skipped` or `failed`. Pending/`critical` messages block
  advancement. Preserve this ordering when changing callbacks or worker behavior.
- The persisted checkpoint is `last_safe_message_id`, not the last message scanned.
  A normal terminal failure can be passed by the next run; resume is not an automatic
  retry of every unsuccessful download.
- `downloaded_files` is keyed by file-content MD5 and stores message/path metadata;
  `blacklisted_message_ids` is per-channel. Do not describe it as a global deduplicator.
  Stored `filename`/`file_path` describe the registered file after naming/normalization;
  the original Telegram filename is not stored separately.
- JSON writes use a sibling `.tmp` followed by `Path.replace()`. Keep atomic replacement.
  Loading merges defaults with JSON; it does not validate schema versions. Load errors
  log a failure and fall back to empty state without preserving a recovery copy.
- `--cleanup` only removes missing-file registry entries. It does not delete media,
  clear the blacklist, reset scan checkpoints or schedule re-downloads.
- `--stats` reads stored counts from all discovered channel folders, including channels
  absent from the current config; it does not validate file integrity.

### Download, naming and filters

- Type/extension/size/date filters run before queueing. `filters.duration` also checks
  Telegram audio duration before queueing. `get_audio_duration_seconds()` accepts
  positive, finite numeric values, excluding booleans. Usable metadata bypasses the
  post-download probe. Missing or invalid duration falls back to `ffprobe` on `PATH`
  after downloading, before normalization and tracking. Both duration limits unset
  means no probe. The fallback deletes and skips out-of-range files; probe or deletion
  errors return `failed`. Existing-file skip paths bypass the fallback.
- Before transfer, skip checks use the blacklist, tracked message/path and ordinary
  generated destination path. Existing files can be registered without re-downloading;
  existence alone is not a completeness check. No byte-offset resume is implemented here.
- An existing normalized destination alone does not skip a transfer. After downloading,
  normalization collisions compare file sizes and bytes in a worker thread. Only a
  verified identical download is deleted and reported as skipped; different content or
  comparison errors keep the new file under its generated name. Preserve detected
  rename-collision handling and register the actual retained path.
- `normalize_track_names` defaults to false. `analyze_track_name` is pure and receives
  the actual extension and message ID. It cleans terminal `__digits`, underscores,
  release/key markers, technical/mastering suffixes and recognized separated `Copy`
  suffixes. Known mixes/version groups move to the end before square-bracket labels.
  Standalone vinyl positions (`A`-`D` plus one or two digits), including a trailing
  dot/parenthesis, move to the beginning. In `04 B2. Title`, the numeric ordinal is
  removed only when the pair starts the name or a dash-separated field; `B2` is retained. Ordinary
  numeric positions otherwise remain.
- Split version repair joins only `Original`, `Extended`, `Radio` or `Original Extended`
  immediately before a bare parenthesized `Mix`, `Edit`, `Remix`, `Version` or `Rework`.
  It leaves complete groups such as `(Original Mix)` and title words such as `Full`,
  `Long`, `Deep` intact. Preserve musical versions and punctuation in initials/ellipsis;
  unknown or ambiguous fragments must not be removed by broad substring rules.
- The analyzer returns the name plus change/warning identifiers; unsafe results fall
  back to the input stem. The downloader calls it once per attempt before transfer and
  reuses the predicted path after duration checks. Internal cleanup repeats to a fixed
  point. `normalize_track_name(str)` remains the context-free string wrapper.
- Filename template errors fall back to `file_<message_id><extension>`. Audio template
  fields are only provided when Telegram audio metadata is available.
- Downloader exceptions containing `flood` or `timeout` (case-insensitive text match)
  add the message to the channel blacklist. A later attempt may therefore be skipped.
- `TelegramDocumentLocator` reconstructs a `Document` from request fields with `dc_id=1`;
  it does not fetch a fresh message or refresh an expired file reference. Parser errors
  are logged and end iteration; its `RpcMcgetFailError` branch waits 60 seconds and returns.

## Logging and progress

- Obtain `telegram_music_downloader` via `get_logger()`; configure handlers centrally.
- `console.log` uses UTF-8, append mode, 10 MiB rotation and five backups. Runtime
  events and summaries obey `logging.level`; live redraws stay screen-only.
- Keep event markers ASCII (`[OK]`, `[SKIP]`, `[FILTER]`, `[FAIL]`, `[CRITICAL]`,
  `[QUEUE]`, `[RENAME]`, `[WORKER_N]`). Use `format_critical_message()` for critical output.
  Existing diagnostics and summary lines do not all have a marker.
- Use `emit_session_message` / `emit_session_lines` for output that belongs in the
  transcript. They can still print when `logging.console` is false; that option only
  removes the console log handler. Blank lines are omitted from the log.
- Keep queue/token internals at DEBUG; retain useful channel/message/file context on errors.
- Standalone `--progress` creates no coordinator and reports no active in-process
  session. It cannot inspect another process. The CLI does not start periodic monitoring.

## Verification

Run from the repository root with the existing environment (PowerShell):

```powershell
.\venv\Scripts\python.exe src/main.py --help
.\venv\Scripts\python.exe -m unittest tests.test_app
.\venv\Scripts\python.exe -m unittest tests.test_runtime
.\venv\Scripts\python.exe -m unittest tests.test_state
.\venv\Scripts\python.exe -m unittest tests.test_logging
# Full suite when scope warrants it; do not repeat each module and then the suite.
.\venv\Scripts\python.exe -m unittest discover -s tests
.\venv\Scripts\python.exe -m compileall src tests
git diff --check
```

| Tests | Contract focus |
|---|---|
| `tests/test_app.py` | Disk-backed stats/cleanup, standalone progress, duration config |
| `tests/test_runtime.py` | Channel queueing/checkpoints, request conversion, metadata duration/fallback, normalization collision and retained paths, retries, shutdown, locator |
| `tests/test_state.py` | Persisted fields, corrupt-state fallback, safe checkpoint prefix and restart outcomes |
| `tests/test_logging.py` | Shared handlers, session transcript, concurrent writes, screen-only redraw, component log messages |

Choose the smallest relevant check. Documentation-only changes need source/example
validation, not new tests. Existing tests use temporary state and fake Telegram clients;
duration tests stub the probe, so they do not prove a real `ffprobe` installation works.
Do not run live Telegram authentication/downloads unless the task requires them.
