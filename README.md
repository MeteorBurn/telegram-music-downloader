# Telegram Music Downloader

Python CLI application for downloading audio and media files from Telegram
channels or groups you have access to. The project uses Telethon, keeps local
JSON trackers for resumable runs, and supports concurrent downloads via
`asyncio`.

## What It Does

- Downloads Telegram media, primarily music files
- Filters files by type, extension, size, and message date
- Tracks processed messages and downloaded files per channel
- Organizes output into separate folders per configured channel
- Supports concurrent downloads with rate limiting
- Optionally normalizes downloaded track names
- Writes logs to console and rotating log files

## Supported Media Filters

The default config is aimed at music collections and includes formats such as:

- `.flac`
- `.wav`
- `.aiff`
- `.m4a`
- `.mp3`

The actual filter behavior comes from `src/config.yaml` and
`src/local_config.yaml`.

## Requirements

- Python 3.9+
- Telegram API credentials from <https://my.telegram.org>
- Access to the target channels/groups

## Installation

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux use:

```bash
source venv/bin/activate
```

## Configuration

Main config file:

- `src/config.yaml`

Optional local override for secrets and machine-specific settings:

- `src/local_config.yaml`

`src/local_config.yaml` overrides values from `src/config.yaml` when present.

### Minimal local config

```yaml
telegram:
  api_id: 1234567
  api_hash: "your_api_hash_here"
```

### Important Telegram settings

The current code reads these Telegram settings:

- `api_id`
- `api_hash`
- `session_name`
- `two_factor_auth`

Note: the app does not read `phone_number` from config. If no valid Telegram
session exists, `src/client.py` asks for the phone number, login code, and
optionally the 2FA password interactively.

### Example channel config

```yaml
channels:
  - -1001234567890
  - "@musicchannel"
  - -1009876543210
```

### Example download config

```yaml
download:
  output_dir: "./data/downloads"
  timeout_between_messages: 0.3
  max_files_per_run: 100
  concurrent_downloads: 3
  max_queue_size: 100
  worker_timeout: 300
  rate_limit:
    requests_per_second: 2
    burst_size: 5
```

### Example filters

```yaml
filters:
  file_types: ["audio", "document"]
  formats: [".flac", ".wav", ".aiff", ".m4a", ".mp3"]
  size:
    min_mb: 1
    max_mb: 500
  date:
    from: "2025-01-01"
    to: null
```

### Track name normalization

To enable optional filename cleanup after download:

```yaml
normalize_track_names: true
```

When enabled, the app applies normalization rules from `src/normalizer.py`
after a successful download.

## How to Get a Channel or Group ID

1. Forward a message from the target channel to `@ShowJsonBot`
2. Find a value like `"chat":{"id":-1001234567890}` in the response
3. Use that numeric id in `channels:`

Notes:

- Private channels/groups usually need numeric IDs
- Public channels can be configured by username such as `@channelname`
- The configured identifier is used as-is in the final channel folder name

## Usage

Run from the repository root:

```bash
python src/main.py
```

### Common commands

```bash
python src/main.py --config src/config.yaml
python src/main.py --workers 1
python src/main.py --workers 5
python src/main.py --max-files 20
python src/main.py --stats
python src/main.py --cleanup
python src/main.py --progress
```

### Command line options

| Option | Short | Description |
|--------|-------|-------------|
| `--config` | `-c` | Config file path |
| `--max-files` | `-m` | Maximum files to download in this run |
| `--workers` | `-w` | Override configured worker count |
| `--progress` | `-p` | Show current progress once |
| `--stats` | `-s` | Show stats for trackers initialized in current run |
| `--cleanup` | | Remove missing-file entries from trackers initialized in current run |

## Important Behavior Notes

These notes reflect the current code, even where older docs may imply broader
behavior.

- `--progress` is a separate display path, not a full download mode by itself
- In the current implementation, `python src/main.py --progress` initializes the
  client and prints progress once; it does not start a download session
- `--stats` and `--cleanup` do not scan all existing channel folders on disk;
  they operate on trackers initialized in the current process
- Message processing and file download tracking are separate; be careful when
  changing tracker semantics
- The current concurrency model is `asyncio` tasks and queues, not OS threads

## How Downloads Are Organized

Each configured channel gets its own root folder under the configured download
directory.

Folder naming:

- Format: `{SanitizedChannelTitle}_{channel_identifier_from_config}`
- The title part is sanitized
- The configured channel id/username part is preserved as-is

Examples:

- `MusicChannel_-1002006273817`
- `PublicMusic_@publicmusic`

Inside each channel folder, the app stores trackers and downloaded files:

```text
data/
  downloads/
    MusicChannel_-1001234567890/
      message_tracker.json
      file_tracker.json
      downloads/
        song1.flac
        song2.mp3
```

## Project Structure

```text
telegram-music-downloader/
  README.md
  requirements.txt
  AGENTS.md
  src/
    main.py
    config.yaml
    local_config.yaml
    config_loader.py
    client.py
    session_manager.py
    message_parser.py
    media_filter.py
    downloader.py
    download_queue.py
    download_worker.py
    download_coordinator.py
    download_monitor.py
    tracker.py
    channel_utils.py
    normalizer.py
    logger.py
  data/
    downloads/
    logs/
    sessions/
```

## Development Notes

- There is no formal build system
- There is no configured linter in the repository
- There is no committed automated test suite at the moment
- There is no CI/CD workflow checked into `.github/`
- A safe code validation step is:

```bash
python -m compileall src
```

## Troubleshooting

- If Telegram asks for login, complete the interactive prompts in the terminal
- If you hit API limits, reduce `--workers` or lower the configured request rate
- If your connection is unstable, try `python src/main.py --workers 1`
- Check `data/logs/downloader.log` for operational details

## Security Notes

- Do not commit `src/local_config.yaml` with real credentials
- Do not commit `*.session` files
- Do not commit `data/logs/` or downloaded media unless intended

## License

MIT
