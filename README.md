# Telegram Music Downloader

A command-line tool for downloading audio files and music from Telegram channels
and groups. Supports concurrent downloads, flexible filtering, resumable sessions,
and per-channel download tracking.

---

## Features

- Download music from public and private Telegram channels and groups
- Concurrent downloads — configurable workers with built-in rate limiting
- Flexible filtering by file type, format, size, and message date
- Per-channel organization — separate folder and versioned state files for each channel
- Resumable sessions — continues from the last processed message ID
- Track name normalization — optional cleanup of downloaded filenames
- Centralized logging — one project logger writes a full session transcript to console and `output_dir/console.log`

---

## Requirements

- Python **3.9+**
- Telegram API credentials — `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org)
- Access to the target channels or groups

---

## Installation

```powershell
# 1. Clone the repository
git clone https://github.com/MeteorBurn/telegram-music-downloader.git
cd telegram-music-downloader

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the environment
# Windows PowerShell
.\venv\Scripts\Activate.ps1
# Windows CMD
venv\Scripts\activate.bat
# macOS / Linux
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

### Dependencies

| Package | Version | Purpose |
|---|---|---|
| `telethon` | 1.32.1 | Telegram API client |
| `pyyaml` | 6.0.1 | YAML config parsing |
| `python-dateutil` | 2.8.2 | Date parsing for filters |
| `humanize` | 4.8.0 | Human-readable file sizes |
| `aiofiles` | 23.2.1 | Async file I/O |
| `cryptg` | 0.4.0 | Faster Telegram encryption |

---

## Configuration

### Step 1 — API credentials

Get your `api_id` and `api_hash` at [my.telegram.org](https://my.telegram.org).

Create `src/local_config.yaml` (excluded from git) with your credentials:

```yaml
telegram:
  api_id: 1234567
  api_hash: "your_api_hash_here"
```

> `src/local_config.yaml` is deep-merged on top of `src/config.yaml`.
> All keys from `local_config.yaml` override the corresponding keys in `config.yaml`.
> In normal local usage always launch with `--config src/local_config.yaml`.

### Step 2 — Main config

Edit `src/config.yaml` to set channels, filters, and download options:

```yaml
telegram:
  api_id: 12345678           # from my.telegram.org
  api_hash: "your_api_hash"  # from my.telegram.org
  two_factor_auth: true      # set true if your account uses 2FA

channels:
  - -1001234567890   # private channel / group — numeric ID with minus sign
  - "@musicchannel"  # public channel — username with @

download:
  output_dir: "./data/downloads"   # base folder for all downloads and state files
  timeout_between_messages: 0.3    # pause between messages in seconds (0 = no pause)
  max_files_per_run: 100           # hard cap per session (0 = unlimited)
  concurrent_downloads: 3          # parallel download workers (1–5 recommended)
  max_queue_size: 100              # maximum tasks in the download queue
  worker_timeout: 300              # seconds before a stalled worker is considered failed
  rate_limit:
    requests_per_second: 2         # Telegram API request rate limit
    burst_size: 5                  # allowed burst above the steady rate

naming:
  template: "{original_name}__{message_id}"  # output filename template
  date_format: "%Y%m%d_%H%M%S"              # date format used inside template

normalize_track_names: false  # true = run normalizer on filenames after download

filters:
  file_types: ["audio", "document"]           # accepted Telegram media types
  formats: [".flac", ".wav", ".aiff", ".m4a", ".mp3"]  # accepted file extensions
  size:
    min_mb: 1     # skip files smaller than this (MB)
    max_mb: 500   # skip files larger than this (MB)
  date:
    from: "2025-01-01"  # only download messages from this date (YYYY-MM-DD or null)
    to: null            # only download messages up to this date (null = no upper limit)

logging:
  level: "INFO"   # DEBUG | INFO | WARNING | ERROR
  console: true   # print log output to terminal in addition to file
```

> The log file path is always `download.output_dir/console.log`.
> There is no separate configurable log file key in YAML.

### Filename template variables

| Variable | Description |
|---|---|
| `{original_name}` | Original filename without extension |
| `{message_id}` | Telegram message ID |
| `{publish_date}` | Message publish date, formatted with `date_format` |
| `{download_date}` | Download timestamp, formatted with `date_format` |
| `{file_size}` | File size in bytes |
| `{mime_type}` | MIME type with `/` replaced by `_` |
| `{artist}` | Performer field from Telegram audio metadata |
| `{title}` | Title field from Telegram audio metadata |
| `{duration}` | Duration in seconds from Telegram audio metadata |

Template examples:

| Template | Output filename |
|---|---|
| `{original_name}__{message_id}` | `track__12345.flac` |
| `{publish_date}_{original_name}` | `20250315_120000_track.flac` |
| `{artist} - {title}__{message_id}` | `DJ Name - Song Title__12345.flac` |

---

## How to get a channel or group ID

1. Forward any message from the target channel to `@ShowJsonBot`
2. Find `"chat":{"id":-1001234567890}` in the bot's response
3. Copy the full number including the minus sign

> **Public channels** can be specified by username: `@channelname`
> **Private channels and groups** require the numeric ID

---

## Usage

All commands are run from the repository root with the virtual environment activated.

```powershell
# Full download session using local config
python src/main.py --config src/local_config.yaml

# Limit to 20 files this run
python src/main.py --config src/local_config.yaml --max-files 20

# Use 5 concurrent download workers
python src/main.py --config src/local_config.yaml --workers 5

# Combine: 5 workers, max 30 files
python src/main.py --config src/local_config.yaml --workers 5 --max-files 30

# Show per-channel statistics without downloading
python src/main.py --config src/local_config.yaml --stats

# Remove tracker entries for files missing from disk
python src/main.py --config src/local_config.yaml --cleanup

# Show live download progress of the current running session
python src/main.py --config src/local_config.yaml --progress
```

### All CLI options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | `str` | `src/config.yaml` | Path to the YAML config file |
| `--max-files` | `-m` | `int` | `0` | Maximum files to download this run (0 = unlimited) |
| `--workers` | `-w` | `int` | from config | Override concurrent download workers (overrides `concurrent_downloads` in config) |
| `--stats` | `-s` | flag | — | Print per-channel statistics and exit without downloading |
| `--cleanup` | — | flag | — | Remove tracker entries for files no longer on disk, then exit |
| `--progress` | `-p` | flag | — | Print a live snapshot of the in-process download session, then exit |

> `--workers` only overrides for the current run; it does not write back to the config file.

---

## Download organization

Each configured channel gets its own folder inside `output_dir`:

```
data/
  downloads/
    console.log                        <- shared session log for this output_dir
    MusicChannel_-1001234567890/       <- channel folder: {SanitizedTitle}_{channel_id}
      scan_state.json                  <- message scan checkpoint
      download_state.json              <- downloaded files registry
      downloads/
        track1__12345.flac
        track2__12346.mp3
    PublicMusic_@musicchannel/
      scan_state.json
      download_state.json
      downloads/
        ...
```

The Telegram login session is always stored as `telegram.session` in the project root.

**Folder naming rule:** `{SanitizedTitle}_{channel_id_from_config}`

- The channel title is fetched from Telegram and sanitized (special chars removed, transliterated)
- The channel identifier is used exactly as written in `config.yaml`

| `config.yaml` value | Folder name |
|---|---|
| `-1002006273817` | `MusicChannel_-1002006273817` |
| `@publicmusic` | `PublicMusic_@publicmusic` |

---

## First run and authentication

On the first run, or when `telegram.session` does not exist, the app prompts for:

1. **Phone number** — in international format, e.g. `+12025550123`
2. **Verification code** — sent to your Telegram app
3. **2FA password** — only if `two_factor_auth: true` and the account has 2FA enabled

Once authenticated, the session is saved to `telegram.session` in the project root
and reused automatically on all subsequent runs.

---

## Session log — console.log

Every session writes a full transcript to `output_dir/console.log`.

The log captures all meaningful events with structured `[TAG]` markers:

| Marker | Meaning |
|---|---|
| `[START]` / `[STOP]` | Session boundaries |
| `[AUTH]` | Telegram connection and authentication |
| `[INIT]` | Component initialization (trackers, workers, coordinator) |
| `[CHANNEL]` | Per-channel scan progress |
| `[QUEUE]` | File added to the download queue |
| `[DOWN]` | Worker started downloading a file |
| `[OK]` | File downloaded successfully |
| `[SKIP]` | File skipped (already downloaded, blacklisted, or filtered) |
| `[FILTER]` | File rejected by type / format / size / date filter |
| `[FAIL]` | Any error or failure |
| `[NORM]` | Track name normalized (shows original → normalized) |
| `[BLACKLIST]` | File added to or removed from the blacklist |
| `[CLEANUP]` | Missing-file tracker cleanup |
| `[STATS]` | Statistics output |
| `[RESULTS]` | Session results summary |
| `[SUMMARY]` | Download session summary with speeds and totals |
| `[WARN]` | Non-fatal warning |
| `[worker_N]` | Per-worker prefix on all worker events |

Example log output:

```
[START] Telegram Music Downloader Started
[AUTH] Successfully connected to Telegram
[INIT] Download coordinator starting: 5 workers, queue 100, rate 2 req/sec
[worker_1] Started
[worker_2] Started
[CHANNEL] Processing: -1001234567890 (Music Channel)
[QUEUE] track_name__12345.flac [05:30] [62.5 MB]
[worker_1] [DOWN] Downloading: track_name__12345.flac [05:30] [62.5 MB]
[worker_1] [OK] Completed: track_name__12345.flac
[SKIP] other_track__12340.flac - File already downloaded: /path/to/file
[FILTER] format: podcast.mp4
[NORM] 'Artist Name Song Title' -> 'Artist Name - Song Title'
[SUMMARY] Download Session Complete
Files queued:     30
Files completed:  28
Files skipped:    2
Files failed:     0
Total downloaded: 1850.3 MB
Duration:         06:12
[STOP] Telegram Music Downloader Finished
```

Live redraw progress (progress bar and active downloads list) is shown on screen only
and is not written to `console.log`.

---

## Behavior notes

- `--progress` reports a snapshot of the currently running in-process session; it is not a persisted historical view
- `--stats` and `--cleanup` work entirely from files on disk — no Telegram connection is required
- `--stats` before a download session also prints the current filter and directory configuration
- Concurrency is implemented with `asyncio` tasks and queues, not OS threads
- The persisted schema (`scan_state.json` / `download_state.json`) is versioned; legacy `message_tracker.json` / `file_tracker.json` files are not used
- `max_files_per_run` in config and `--max-files` on the CLI are additive caps — the lower of the two applies when both are set
- Files that fail due to flood or timeout errors are added to a per-channel blacklist automatically
- `src/local_config.yaml` is deep-merged, so you only need to include keys you want to override

---

## Tests

The repository includes a synthetic `unittest` suite that covers the full logging
pipeline, download pipeline, state stores, and session orchestration.
No external services or credentials are required to run the tests.

### Run all tests

```powershell
python -m unittest discover -s tests
```

### Run a specific test module

```powershell
python -m unittest tests.test_logging
python -m unittest tests.test_logging.LoggingIntegrationTests
python -m unittest tests.test_logging.LoggingMessageCoverageTests
python -m unittest tests.test_phase1_refactor
python -m unittest tests.test_phase1_refactor.DownloadCoordinatorTests
python -m unittest tests.test_session_runner
python -m unittest tests.test_state_store
python -m unittest tests.test_downloader_contracts
python -m unittest tests.test_channel_processor
```

### Run with verbose output

```powershell
python -m unittest discover -s tests -v
python -m unittest tests.test_logging -v
```

### Run a single test case

```powershell
python -m unittest tests.test_logging.LoggingIntegrationTests.test_async_concurrent_logging_records_every_message_without_hanging -v
```

### Build-like validation (compile check)

```powershell
python -m compileall src
```

### What the test suite covers

| Module | Coverage |
|---|---|
| `test_logging.py` | Centralized logger setup, idempotent handler init, session transcript mirroring, live progress not written to file, async concurrent writes, all module log message types (worker, coordinator, queue, tracker, filter, parser, client, channel) |
| `test_phase1_refactor.py` | Download coordinator lifecycle, worker pool, queue operations |
| `test_session_runner.py` | Session statistics, cleanup commands, config loading |
| `test_state_store.py` | JSON state persistence, atomic writes, schema versioning |
| `test_downloader_contracts.py` | Downloader skip/success/fail outcomes |
| `test_channel_processor.py` | Per-channel message processing and queueing |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Telegram requests login on every run | Check that `telegram.session` exists in the project root and is not in `.gitignore` |
| API rate limit / flood errors | Reduce `--workers` or lower `requests_per_second` in config |
| Unstable or slow connection | Run with `--workers 1` |
| Files not downloading | Inspect `output_dir/console.log` — look for `[FAIL]` or `[FILTER]` lines |
| Nothing is queued | Check date filter (`filters.date.from`) and format filter (`filters.formats`) |
| Duplicate downloads | Run `--cleanup` to remove stale tracker entries, then retry |
| Folder not created | Ensure `output_dir` path exists and is writable |
| Wrong workers count | `--workers` overrides `concurrent_downloads` in config for the current run only |
| Stats show 0 files | No state files found yet — run a download session first |

---

## Security

- Do not commit `src/local_config.yaml` — it contains real API credentials
- Do not commit `telegram.session` — it grants full account access
- Do not commit `output_dir/console.log` or downloaded media files
- All three are excluded by `.gitignore` by default

---

## Project structure

```
telegram-music-downloader/
├── README.md
├── AGENTS.md
├── requirements.txt
├── telegram.session              # created on first successful Telegram login
├── src/
│   ├── main.py                   # CLI entry point and argument parser
│   ├── session_runner.py         # session orchestration and top-level commands
│   ├── config.yaml               # main config file (committed, no secrets)
│   ├── local_config.yaml         # local overrides and secrets (not committed)
│   ├── config_loader.py          # config loading, merging, and validation
│   ├── client.py                 # Telegram auth and client lifecycle
│   ├── session_manager.py        # telegram.session file helpers
│   ├── message_parser.py         # message traversal and media field extraction
│   ├── media_filter.py           # filtering by type, format, size, date
│   ├── domain_models.py          # shared typed domain and state models
│   ├── channel_models.py         # channel-level context and result models
│   ├── download_models.py        # download request and outcome models
│   ├── downloader.py             # file download, naming, and tracker integration
│   ├── telegram_locator.py       # Telegram document reconstruction adapter
│   ├── download_queue.py         # async priority queue and rate limiter
│   ├── download_worker.py        # asyncio worker tasks and worker pool
│   ├── download_coordinator.py   # coordinator: ties pool, queue, and stats together
│   ├── download_monitor.py       # live progress display and session summary
│   ├── channel_processor.py      # per-channel scan, filter, queue orchestration
│   ├── tracker.py                # scan and file trackers with persistent state
│   ├── state_store.py            # versioned atomic JSON state store
│   ├── channel_utils.py          # channel folder naming and path helpers
│   ├── normalizer.py             # optional track name normalization
│   └── logger.py                 # centralized logger, handlers, transcript helpers
└── tests/
    ├── test_logging.py            # logging pipeline and message coverage tests
    ├── test_phase1_refactor.py    # coordinator, worker pool, queue tests
    ├── test_session_runner.py     # session commands tests
    ├── test_state_store.py        # state persistence tests
    ├── test_downloader_contracts.py  # downloader outcome tests
    └── test_channel_processor.py  # channel processing tests
```

---

## Verified smoke run

A real local run with `--config src/local_config.yaml --workers 5 --max-files 30`
completed successfully. `console.log` confirmed:

- `[QUEUE]` lines: `30`
- `[OK] Downloaded:` lines: `30`
- `[worker_N] Started` / `Stopped`: `5` each
- No dropped or missing messages across all 5 concurrent workers

---

## License

MIT
