# 🎵 Telegram Music Downloader

A command-line tool for downloading audio files and music from Telegram channels
and groups. Supports concurrent downloads, flexible filtering, resumable sessions,
and per-channel download tracking.

---

## ✨ Features

- 📥 **Download music** from public and private Telegram channels/groups
- ⚡ **Concurrent downloads** — up to 5 files at once with built-in rate limiting
- 🔍 **Flexible filtering** by file type, format, size, and message date
- 📁 **Per-channel organization** — separate folder and trackers for each channel
- 🔄 **Resumable sessions** — continues from the last processed message
- 🏷️ **Track name normalization** — optional cleanup of downloaded filenames
- 📝 **Logging** — to console and rotating log file

---

## 🛠️ Requirements

- Python **3.9+**
- Telegram API credentials — `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org)
- Access to the target channels/groups

---

## 📦 Installation

```bash
# 1. Clone the repository
git clone https://github.com/MeteorBurn/telegram-music-downloader.git
cd telegram-music-downloader

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the environment
# Windows
venv\Scripts\activate
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
| `python-dateutil` | 2.8.2 | Date parsing |
| `humanize` | 4.8.0 | Human-readable file sizes |
| `aiofiles` | 23.2.1 | Async file I/O |
| `cryptg` | 0.4.0 | Faster Telegram encryption |

---

## ⚙️ Configuration

### Step 1 — API credentials

Get your `api_id` and `api_hash` at [my.telegram.org](https://my.telegram.org).

Create `src/local_config.yaml` (excluded from git):

```yaml
telegram:
  api_id: 1234567
  api_hash: "your_api_hash_here"
```

> `src/local_config.yaml` overrides any values from `src/config.yaml`.

### Step 2 — Main config

Edit `src/config.yaml` to set up channels, filters, and download options:

```yaml
telegram:
  api_id: 12345678           # from my.telegram.org
  api_hash: "your_api_hash"  # from my.telegram.org
  session_name: "session"    # session filename in data/sessions/
  two_factor_auth: true      # enable if you use 2FA

channels:
  - -1001234567890   # private channel / group numeric ID
  - "@musicchannel"  # public channel username

download:
  output_dir: "./data/downloads"
  timeout_between_messages: 0.3  # delay between messages, seconds
  max_files_per_run: 100         # 0 = unlimited
  concurrent_downloads: 3        # workers (1–5)
  max_queue_size: 100
  worker_timeout: 300
  rate_limit:
    requests_per_second: 2
    burst_size: 5

naming:
  template: "{original_name}__{message_id}"  # filename template
  date_format: "%Y%m%d_%H%M%S"

normalize_track_names: false  # true = clean up filenames after download

filters:
  file_types: ["audio", "document"]
  formats: [".flac", ".wav", ".aiff", ".m4a", ".mp3"]
  size:
    min_mb: 1
    max_mb: 500
  date:
    from: "2025-01-01"  # YYYY-MM-DD or null
    to: null

logging:
  level: "INFO"   # DEBUG | INFO | WARNING | ERROR
  file: "./data/logs/downloader.log"
  console: true
```

### Filename template variables

| Variable | Description |
|---|---|
| `{original_name}` | Original filename without extension |
| `{message_id}` | Telegram message ID |
| `{publish_date}` | Message publish date |
| `{download_date}` | Download timestamp |
| `{file_size}` | File size in bytes |
| `{artist}` | Performer (from Telegram audio metadata) |
| `{title}` | Track title (from Telegram audio metadata) |

---

## 🔑 How to get a channel or group ID

1. Forward any message from the target channel to `@ShowJsonBot`
2. Find `"chat":{"id":-1001234567890}` in the bot's response
3. Copy the full number, including the minus sign

> **Public channels** can be specified by username: `@channelname`.  
> **Private channels and groups** require a numeric ID.

---

## 🚀 Usage

Run from the repository root:

```bash
# Normal download session
python src/main.py

# Use a specific config file
python src/main.py --config src/config.yaml

# Limit number of files per run
python src/main.py --max-files 20

# Set number of concurrent workers
python src/main.py --workers 5

# Show statistics without downloading
python src/main.py --stats

# Remove missing-file entries from trackers
python src/main.py --cleanup

# Show current download progress
python src/main.py --progress
```

### 📋 All CLI options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | `str` | `src/config.yaml` | Path to config file |
| `--max-files` | `-m` | `int` | `0` | Max files per run (0 = unlimited) |
| `--workers` | `-w` | `int` | from config | Number of concurrent workers (1–5) |
| `--stats` | `-s` | flag | — | Show statistics and exit (no downloads) |
| `--cleanup` | — | flag | — | Remove entries for missing files from trackers |
| `--progress` | `-p` | flag | — | Print current download progress once |

---

## 📂 Download organization

Each configured channel gets its own folder inside `output_dir`:

```
data/
  downloads/
    MusicChannel_-1001234567890/      ← channel folder
      message_tracker.json            ← processed message IDs
      file_tracker.json               ← downloaded files (hashes)
      downloads/
        track1.flac
        track2.mp3
    PublicMusic_@musicchannel/
      message_tracker.json
      file_tracker.json
      downloads/
        ...
```

**Folder naming:** `{SanitizedTitle}_{channel_id_from_config}`

- The channel title is sanitized (transliterated, special chars removed)
- The channel identifier is used exactly as specified in `config.yaml`

Examples:

| config.yaml value | Folder name |
|---|---|
| `-1002006273817` | `MusicChannel_-1002006273817` |
| `@publicmusic` | `PublicMusic_@publicmusic` |

---

## 🔄 First run and authentication

On first run (or when no session file exists), the app will ask for:

1. **Phone number** — in international format, e.g. `+12025550123`
2. **Verification code** — sent to your Telegram app
3. **2FA password** — if two-factor authentication is enabled

Once authenticated, the session is saved to `data/sessions/` and reused on subsequent runs.

---

## ⚠️ Behavior notes

- `--progress` prints progress once and exits — it is not a live background monitor
- `--stats` and `--cleanup` only operate on trackers initialized in the current process run
- Concurrency is implemented with `asyncio` tasks and queues, not OS threads

---

## 🔧 Troubleshooting

| Problem | Solution |
|---|---|
| Telegram requests login | Follow the interactive prompts in the terminal |
| API rate limit errors | Lower `--workers` or reduce `requests_per_second` |
| Unstable connection | Run with `--workers 1` |
| Files not downloading | Check `data/logs/downloader.log` for details |
| Folders not created | Ensure `output_dir` is writable |

---

## 🔐 Security

- Do not commit `src/local_config.yaml` with real credentials
- Do not commit `*.session` files
- Do not commit `data/logs/` or downloaded media

---

## 📁 Project structure

```
telegram-music-downloader/
├── README.md
├── AGENTS.md
├── requirements.txt
├── src/
│   ├── main.py                  # entry point, CLI, orchestration
│   ├── config.yaml              # main config file
│   ├── local_config.yaml        # local secrets (not in git)
│   ├── config_loader.py         # config loading and merging
│   ├── client.py                # Telegram auth and client setup
│   ├── session_manager.py       # session file management
│   ├── message_parser.py        # message traversal and media extraction
│   ├── media_filter.py          # filtering by type, format, size, date
│   ├── downloader.py            # file download and naming
│   ├── download_queue.py        # priority queue and rate limiter
│   ├── download_worker.py       # asyncio worker tasks
│   ├── download_coordinator.py  # worker pool coordination
│   ├── download_monitor.py      # progress display
│   ├── tracker.py               # persistent JSON message/file trackers
│   ├── channel_utils.py         # channel folder naming and paths
│   ├── normalizer.py            # track name normalization
│   └── logger.py                # logging setup with rotation
└── data/                        # runtime data (not in git)
    ├── downloads/
    ├── logs/
    └── sessions/
```

---

## 📄 License

MIT
