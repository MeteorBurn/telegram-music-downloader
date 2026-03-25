# 🎵 Telegram Music Downloader

> **CLI tool for downloading audio and music from Telegram channels and groups.**
> Concurrent downloads · smart filtering · resumable sessions · full session logging.

---

## ✨ Features

| | |
|---|---|
| 📥 **Multi-channel download** | Download from multiple public and private channels in one run |
| ⚡ **Concurrent workers** | Configurable parallel downloads with built-in Telegram rate limiting |
| 🔍 **Flexible filtering** | Filter by file type, format, size range, and message date |
| 📁 **Per-channel organization** | Separate folder and versioned state file per channel |
| 🔄 **Resumable sessions** | Continues exactly from the last processed message ID |
| 🏷️ **Track name normalization** | Optional automatic cleanup of downloaded filenames |
| 📋 **Session transcript** | One centralized logger writes every event to `console.log` |
| 🛡️ **Blacklist protection** | Files that fail on flood/timeout are auto-blacklisted per channel |

---

## 🛠️ Requirements

- Python **3.9+**
- Telegram API credentials — `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org)
- Access to the target channels or groups

---

## 📦 Installation

```powershell
# 1. Clone the repository
git clone https://github.com/MeteorBurn/telegram-music-downloader.git
cd telegram-music-downloader

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the environment
.\venv\Scripts\Activate.ps1        # Windows PowerShell
venv\Scripts\activate.bat          # Windows CMD
source venv/bin/activate           # macOS / Linux

# 4. Install dependencies
pip install -r requirements.txt
```

### 📚 Dependencies

| Package | Version | Purpose |
|---|---|---|
| `telethon` | 1.32.1 | Telegram API client |
| `pyyaml` | 6.0.1 | YAML config parsing |
| `python-dateutil` | 2.8.2 | Date parsing for filters |
| `humanize` | 4.8.0 | Human-readable file sizes |
| `aiofiles` | 23.2.1 | Async file I/O |
| `cryptg` | 0.4.0 | Faster Telegram encryption |

---

## ⚙️ Configuration

### 🔑 Step 1 — API Credentials

Get your `api_id` and `api_hash` at [my.telegram.org](https://my.telegram.org).

Create `src/local_config.yaml` — this file is excluded from git and overrides `src/config.yaml`:

```yaml
telegram:
  api_id: 1234567
  api_hash: "your_api_hash_here"
```

> 💡 `local_config.yaml` is **deep-merged** on top of `config.yaml`.
> You only need to include the keys you want to override.
> Always launch with `--config src/local_config.yaml` for local use.

---

### 📝 Step 2 — Main Config

Full reference for `src/config.yaml`:

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
  max_queue_size: 100              # maximum tasks in the download queue at once
  worker_timeout: 300              # seconds before a stalled worker is considered failed
  rate_limit:
    requests_per_second: 2         # Telegram API request rate limit
    burst_size: 5                  # allowed burst above the steady rate

naming:
  template: "{original_name}__{message_id}"  # output filename template
  date_format: "%Y%m%d_%H%M%S"              # date format used inside the template

normalize_track_names: false  # true = run normalizer on filenames after download

filters:
  file_types: ["audio", "document"]                       # accepted Telegram media types
  formats: [".flac", ".wav", ".aiff", ".m4a", ".mp3"]    # accepted file extensions
  size:
    min_mb: 1     # skip files smaller than this (MB)
    max_mb: 500   # skip files larger than this (MB)
  date:
    from: "2025-01-01"  # download messages from this date (YYYY-MM-DD or null)
    to: null            # download messages up to this date (null = no upper limit)

logging:
  level: "INFO"   # DEBUG | INFO | WARNING | ERROR
  console: true   # mirror log output to terminal
```

> 📌 The log file is always written to `download.output_dir/console.log`.
> There is no separate log file path key in YAML.

---

### 🗂️ Filename Template Variables

| Variable | Description | Example value |
|---|---|---|
| `{original_name}` | Original filename without extension | `DJ Mix Vol 1` |
| `{message_id}` | Telegram message ID | `12345` |
| `{publish_date}` | Message publish date (uses `date_format`) | `20250315_120000` |
| `{download_date}` | Download timestamp (uses `date_format`) | `20250325_183000` |
| `{file_size}` | File size in bytes | `65011712` |
| `{mime_type}` | MIME type with `/` replaced by `_` | `audio_vnd.wave` |
| `{artist}` | Performer from Telegram audio metadata | `Artist Name` |
| `{title}` | Title from Telegram audio metadata | `Song Title` |
| `{duration}` | Duration in seconds from Telegram audio metadata | `375` |

**Template examples:**

| Template | Result |
|---|---|
| `{original_name}__{message_id}` | `track__12345.flac` |
| `{publish_date}_{original_name}` | `20250315_120000_track.flac` |
| `{artist} - {title}__{message_id}` | `DJ Name - Song Title__12345.flac` |

---

## 🔑 How to Find a Channel or Group ID

1. Forward any message from the target channel to `@ShowJsonBot`
2. Find `"chat":{"id":-1001234567890}` in the bot's response
3. Copy the full number **including the minus sign**

> **Public channels** → use username: `@channelname`
> **Private channels / groups** → use numeric ID: `-1001234567890`

---

## 🚀 Usage

All commands run from the repository root with the virtual environment activated.

### Basic commands

```powershell
# Full download session
python src/main.py --config src/local_config.yaml

# Limit to 20 files this run
python src/main.py --config src/local_config.yaml --max-files 20

# Use 5 concurrent download workers
python src/main.py --config src/local_config.yaml --workers 5

# Recommended: 5 workers, max 30 files
python src/main.py --config src/local_config.yaml --workers 5 --max-files 30
```

### Utility commands

```powershell
# Show per-channel statistics (no download, no Telegram connection needed)
python src/main.py --config src/local_config.yaml --stats

# Remove tracker entries for files missing from disk
python src/main.py --config src/local_config.yaml --cleanup

# Show live progress of the currently running download session
python src/main.py --config src/local_config.yaml --progress
```

### 📋 All CLI Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | `str` | `src/config.yaml` | Path to the YAML config file |
| `--max-files` | `-m` | `int` | `0` | Max files to download this run (`0` = unlimited) |
| `--workers` | `-w` | `int` | from config | Override concurrent workers for this run only |
| `--stats` | `-s` | flag | — | Print per-channel statistics and exit (no downloads) |
| `--cleanup` | — | flag | — | Remove tracker entries for missing files, then exit |
| `--progress` | `-p` | flag | — | Print a live snapshot of the active download session, then exit |

> ⚠️ `--workers` overrides `concurrent_downloads` for the **current run only** — it does not write back to the config file.
> When both `max_files_per_run` (config) and `--max-files` (CLI) are set, the **lower** value applies.

---

## 📂 Download Organization

Each channel gets its own folder inside `output_dir`:

```
data/
  downloads/
    console.log                          ← full session log
    MusicChannel_-1001234567890/         ← {SanitizedTitle}_{channel_id}
    │   scan_state.json                  ← message scan checkpoint
    │   download_state.json              ← downloaded files registry
    │   downloads/
    │       track1__12345.flac
    │       track2__12346.wav
    │
    PublicMusic_@musicchannel/
        scan_state.json
        download_state.json
        downloads/
            ...
```

**Folder naming rule:** `{SanitizedTitle}_{channel_id_from_config}`

- Title is fetched from Telegram and sanitized (special chars removed, transliterated)
- Channel identifier is used **exactly** as written in `config.yaml`

| `config.yaml` value | Folder name |
|---|---|
| `-1002006273817` | `MusicChannel_-1002006273817` |
| `@publicmusic` | `PublicMusic_@publicmusic` |

`telegram.session` is always stored in the **project root** — never inside `output_dir`.

---

## 🔐 First Run & Authentication

On first run (or if `telegram.session` is missing), the app prompts interactively:

1. **📱 Phone number** — international format, e.g. `+12025550123`
2. **🔢 Verification code** — sent to your Telegram app
3. **🔒 2FA password** — only if `two_factor_auth: true` and 2FA is enabled on the account

Once authenticated, the session is saved to `telegram.session` and reused on all subsequent runs.

---

## 📋 Session Log — console.log

Every session writes a full human-readable transcript to `output_dir/console.log`.
All events use structured `[TAG]` markers for easy grepping and parsing.

### Log Markers

| Marker | Meaning |
|---|---|
| `[START]` / `[STOP]` | Session start and finish boundaries |
| `[AUTH]` | Telegram connection and authentication events |
| `[INIT]` | Component startup — trackers, workers, coordinator |
| `[CHANNEL]` | Per-channel scan progress and results |
| `[QUEUE]` | File added to the download queue |
| `[DOWN]` | Worker started downloading a file |
| `[OK]` | File downloaded successfully |
| `[SKIP]` | File skipped — already downloaded, blacklisted, or name conflict |
| `[FILTER]` | File rejected by type / format / size / date filter |
| `[FAIL]` | Any error or failure |
| `[NORM]` | Track name normalized — shows `original → normalized` |
| `[BLACKLIST]` | File added to or removed from the per-channel blacklist |
| `[CLEANUP]` | Tracker cleanup of missing files |
| `[STATS]` | Statistics display block |
| `[RESULTS]` | Session results summary |
| `[SUMMARY]` | Download summary with totals and speed |
| `[WARN]` | Non-fatal warning |
| `[worker_N]` | Per-worker prefix on all worker-level events |

### Example Output

```
==================================================
[START] Telegram Music Downloader Started
==================================================
[AUTH] Successfully connected to Telegram
[INIT] Download coordinator starting: 5 workers, queue 100, rate 2 req/sec
[worker_1] Started
[worker_2] Started
...
[CHANNEL] Processing: -1001234567890 (Music Channel)
[CHANNEL] Resume from message ID: 10200

[QUEUE] Black Loops - CDMX__10201.wav [06:42] [78.4 MB]
[QUEUE] Miroloja - Revolution__10202.wav [07:15] [85.1 MB]

[worker_1] [DOWN] Downloading: Black Loops - CDMX__10201.wav [06:42] [78.4 MB]
[worker_2] [DOWN] Downloading: Miroloja - Revolution__10202.wav [07:15] [85.1 MB]
[worker_1] [OK] Completed: Black Loops - CDMX__10201.wav
[worker_2] [OK] Completed: Miroloja - Revolution__10202.wav

[SKIP] OldTrack__10190.wav - File already downloaded: /data/downloads/...
[FILTER] format: podcast_episode.mp4
[NORM] 'Artist Name Song Title' -> 'Artist Name - Song Title'

--------------------------------------------------
[SUMMARY] Download Session Complete
==================================================
Files queued:     30
Files completed:  28
Files skipped:    2
Files failed:     0
Total downloaded: 1850.3 MB
Duration:         06:12
Avg speed:        298.1 MB/min
Success rate:     100.0%
==================================================

--------------------------------------------
[RESULTS] Session Results
--------------------------------------------
Channels processed:  1
Messages scanned:    155
Files found:         30
Files downloaded:    28
Files skipped:       2
Files failed:        0
--------------------------------------------
==================================================
[STOP] Telegram Music Downloader Finished
==================================================
```

> 💡 Live progress redraw (progress bar, active downloads list, ETA) is **screen-only**
> and is never written to `console.log` to keep it readable.

---

## ⚠️ Behavior Notes

- **`--progress`** — shows a snapshot of the active in-process session; not a persisted historical view
- **`--stats` and `--cleanup`** — work entirely from files on disk, no Telegram connection needed
- **`--stats`** run before a download session also prints current filter and directory config
- **Concurrency** — implemented with `asyncio` tasks and queues, not OS threads
- **State schema** — `scan_state.json` / `download_state.json` are versioned; legacy `message_tracker.json` / `file_tracker.json` are not used
- **File cap** — `max_files_per_run` (config) and `--max-files` (CLI) both apply; the lower value wins
- **Auto-blacklist** — files that fail with flood or timeout errors are blacklisted per channel automatically
- **Local config** — `local_config.yaml` deep-merges over `config.yaml`; include only the keys you want to override

---

## 🧪 Tests

Synthetic `unittest` suite — no external services, no credentials required.

### ▶️ Run All Tests

```powershell
python -m unittest discover -s tests
```

### ▶️ Run a Specific Module

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

### ▶️ Verbose Output

```powershell
python -m unittest discover -s tests -v
python -m unittest tests.test_logging -v
```

### ▶️ Single Test Case

```powershell
python -m unittest tests.test_logging.LoggingIntegrationTests.test_async_concurrent_logging_records_every_message_without_hanging -v
```

### ▶️ Compile Check

```powershell
python -m compileall src
```

### 📊 Test Coverage

| Test module | What it covers |
|---|---|
| `test_logging.py` | Logger setup, idempotent handler init, session transcript mirroring, live progress not in file, async concurrent writes without message loss, all `[TAG]` marker paths across every module |
| `test_phase1_refactor.py` | Download coordinator lifecycle, worker pool start/stop, queue operations |
| `test_session_runner.py` | `--stats`, `--cleanup`, config loading, session orchestration |
| `test_state_store.py` | JSON state persistence, atomic writes, schema versioning, corrupt file recovery |
| `test_downloader_contracts.py` | Downloader skip / success / fail outcomes, tracker integration |
| `test_channel_processor.py` | Per-channel message scanning, filter decisions, queue handoff |

---

## 🔧 Troubleshooting

| Problem | Solution |
|---|---|
| Telegram asks for login on every run | Verify `telegram.session` exists in the project root |
| Flood / rate limit errors | Lower `--workers` or reduce `rate_limit.requests_per_second` in config |
| Slow or unstable connection | Run with `--workers 1` |
| Files not downloading | Check `console.log` for `[FAIL]` lines |
| Nothing is queued | Check `filters.date.from` and `filters.formats` — they may filter everything out |
| Duplicate / already downloaded skipped | Expected behavior — the tracker prevents re-downloading |
| Stale tracker entries after manual deletion | Run `--cleanup` to remove entries for files no longer on disk |
| Wrong worker count active | `--workers` overrides `concurrent_downloads` for the current run only |
| `--stats` shows 0 files | No state files found yet — run a download session first |
| `output_dir` not created | Ensure the path is writable; `ConfigLoader` creates it automatically |

---

## 🔐 Security

> ⚠️ Never commit secrets or session files.

| File | Why it must not be committed |
|---|---|
| `src/local_config.yaml` | Contains real `api_id` and `api_hash` |
| `telegram.session` | Grants full Telegram account access |
| `output_dir/console.log` | May contain channel names, file paths, and timing data |
| Downloaded media files | User content — not part of the repository |

All of the above are excluded by `.gitignore` by default.

---

## 📁 Project Structure

```
telegram-music-downloader/
├── README.md
├── AGENTS.md                          ← agent / coding assistant guidance
├── requirements.txt
├── telegram.session                   ← created on first Telegram login (not in git)
├── src/
│   ├── main.py                        ← CLI entry point and argument parser
│   ├── session_runner.py              ← session orchestration and top-level commands
│   ├── config.yaml                    ← main config (committed, no secrets)
│   ├── local_config.yaml              ← local overrides and secrets (not committed)
│   ├── config_loader.py               ← config loading, deep-merge, validation
│   ├── client.py                      ← Telegram auth and client lifecycle
│   ├── session_manager.py             ← telegram.session file helpers
│   ├── message_parser.py              ← message traversal and media field extraction
│   ├── media_filter.py                ← filtering by type, format, size, date
│   ├── domain_models.py               ← shared typed domain and state models
│   ├── channel_models.py              ← channel-level context and result models
│   ├── download_models.py             ← download request and outcome models
│   ├── downloader.py                  ← file download, naming, tracker integration
│   ├── telegram_locator.py            ← Telegram document reconstruction adapter
│   ├── download_queue.py              ← async priority queue and rate limiter
│   ├── download_worker.py             ← asyncio worker tasks and worker pool
│   ├── download_coordinator.py        ← ties pool, queue, and session stats together
│   ├── download_monitor.py            ← live progress display and session summary
│   ├── channel_processor.py           ← per-channel scan, filter, queue orchestration
│   ├── tracker.py                     ← scan and file trackers with persistent state
│   ├── state_store.py                 ← versioned atomic JSON state store
│   ├── channel_utils.py               ← channel folder naming and path helpers
│   ├── normalizer.py                  ← optional track name normalization
│   └── logger.py                      ← centralized logger, handlers, transcript helpers
└── tests/
    ├── test_logging.py                ← logging pipeline and all [TAG] marker tests
    ├── test_phase1_refactor.py        ← coordinator, worker pool, queue tests
    ├── test_session_runner.py         ← session command tests
    ├── test_state_store.py            ← state persistence tests
    ├── test_downloader_contracts.py   ← downloader outcome tests
    └── test_channel_processor.py     ← channel processing tests
```

---

## ✅ Verified Smoke Run

Real local session — `--config src/local_config.yaml --workers 5 --max-files 30`:

| Metric | Result |
|---|---|
| `[QUEUE]` entries in `console.log` | **30** |
| `[OK] Downloaded:` entries | **30** |
| `[worker_N] Started` | **5** (one per worker) |
| `[worker_N] Stopped` | **5** (all clean shutdowns) |
| Dropped or missing messages | **0** |

---

## 📄 License

MIT
