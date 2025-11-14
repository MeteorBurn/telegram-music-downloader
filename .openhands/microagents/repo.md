# Repository Overview: Telegram Music Downloader

## Purpose

**Telegram Music Downloader** is a Python-based application designed to download audio files (primarily music) from specified Telegram channels and groups. The application offers concurrent downloads, advanced filtering, download tracking, and robust logging capabilities.

**Key Objectives:**
- Download audio/media files from public or private Telegram channels/groups
- Provide concurrent multi-threaded downloading (1-5 workers) for performance
- Track downloaded files and processed messages to prevent duplicates
- Filter media by type, format, size, and date
- Organize downloads into per-channel folders with separate trackers
- Normalize and clean up track names

**Target Users:** Users who want to archive or collect audio content from Telegram channels in an organized and efficient manner.

## General Setup

### Prerequisites
- **Python 3.9+**
- Telegram API credentials (api_id, api_hash from my.telegram.org)
- Access to target Telegram channels/groups

### Installation

1. Clone repository and navigate to project directory
2. Create Python virtual environment: `python -m venv venv`
3. Activate virtual environment:
   - Windows: `venv\Scripts\activate`
   - macOS/Linux: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`

### Configuration Files

**Main configuration:** `src/config.yaml`
- Channels/groups to monitor (IDs or usernames)
- Download settings (concurrent workers, rate limits, timeouts)
- File filters (types, formats, size range, date range)
- Naming templates
- Logging settings

**Local secrets:** `src/local_config.yaml` (gitignored)
- Telegram API credentials (api_id, api_hash)
- Phone number (optional)

**Note:** `local_config.yaml` overrides settings from `config.yaml`

### Running the Application

Basic usage:
```bash
python src/main.py
```

Common options:
- `--workers N` - Set concurrent download workers (1-5, default: 3)
- `--progress` - Show real-time download progress
- `--max-files N` - Limit files to download (0 = unlimited)
- `--stats` - Show statistics only (no downloads)
- `--cleanup` - Clean up tracker from missing files
- `--config PATH` - Use custom config file

Examples:
```bash
python src/main.py --workers 5 --progress
python src/main.py --max-files 50 --workers 3
python src/main.py --stats
```

## Repository Structure

### Directory Layout

```
telegram-music-downloader/
├── src/                          # Source code
│   ├── main.py                   # Entry point with async/concurrent support
│   ├── config.yaml              # Main configuration template
│   ├── local_config.yaml        # Local secrets (gitignored)
│   ├── config_loader.py         # Configuration management
│   ├── client.py                # Telegram client initialization
│   ├── session_manager.py       # Telegram session management
│   ├── message_parser.py        # Parse messages from channels
│   ├── media_filter.py          # Filter media by criteria
│   ├── tracker.py               # Track messages and files (per-channel)
│   ├── downloader.py            # File download logic
│   ├── download_queue.py        # Priority queue for downloads
│   ├── download_worker.py       # Worker threads for concurrent downloads
│   ├── download_coordinator.py  # Coordinate concurrent downloads
│   ├── download_monitor.py      # Real-time progress monitoring
│   ├── normalizer.py            # Track name normalization/cleanup
│   ├── channel_utils.py         # Channel folder naming utilities
│   └── logger.py                # Logging with rotation
│
├── data/                         # Runtime data (gitignored)
│   ├── downloads/               # Downloaded files (per-channel folders)
│   │   ├── {ChannelName}_{ChannelID}/
│   │   │   ├── file1.mp3
│   │   │   ├── message_tracker.json
│   │   │   └── file_tracker.json
│   │   └── {AnotherChannel}_{ID}/
│   ├── logs/                    # Application logs
│   │   └── downloader.log
│   └── sessions/                # Telegram session files
│       └── session.session
│
├── requirements.txt              # Python dependencies
├── README.md                     # Main documentation
├── CONCURRENT_DOWNLOADS.md      # Concurrent downloads documentation
├── CHANNEL_STRUCTURE_UPDATE.md  # Per-channel structure documentation
└── IMPLEMENTATION_SUMMARY_RU.md # Implementation summary (Russian)
```

### Core Modules

**main.py**
- Entry point for the application
- Initializes all components (client, parsers, filters, trackers, downloader, coordinator)
- Implements `TelegramMusicDownloader` class
- Manages download sessions
- Command-line argument parsing
- Uses `TrackerManager` to handle per-channel trackers

**config_loader.py**
- Loads and merges configurations from `config.yaml` and `local_config.yaml`
- Provides configuration access methods
- Validates configuration values

**client.py**
- Initializes Telegram client using Telethon
- Handles authentication
- Manages client lifecycle

**session_manager.py**
- Manages Telegram session files
- Creates backups before new sessions

**message_parser.py**
- Parses messages from Telegram channels
- Extracts media metadata (filename, size, duration, etc.)
- Yields messages in chronological order (oldest first)

**media_filter.py**
- Filters media based on configuration:
  - File types (audio, document)
  - Formats (.mp3, .flac, .wav, etc.)
  - Size range (min/max MB)
  - Date range (from/to dates)

**tracker.py**
- **MessageTracker**: Tracks processed messages per channel
- **FileTracker**: Tracks downloaded files per channel (hash-based duplicate detection)
- **TrackerManager**: Manages per-channel trackers, creates/caches tracker instances
- Thread-safe operations
- JSON-based persistence

**downloader.py**
- Downloads media files from Telegram using Telethon
- Generates filenames based on templates
- Optional track name normalization
- Thread-safe file tracker integration
- Accepts per-channel file_tracker and download_dir via media_info

**download_queue.py**
- Priority queue for download tasks
- Thread-safe operations
- Rate limiting logic

**download_worker.py**
- Worker threads for concurrent downloads
- Processes tasks from queue
- Handles download lifecycle

**download_coordinator.py**
- Coordinates concurrent download process
- Manages worker pool
- Collects session statistics

**download_monitor.py**
- Real-time progress monitoring
- Displays download statistics and worker status

**normalizer.py**
- Cleans and normalizes track names
- Removes unwanted tags, extra spaces, technical info

**channel_utils.py** (NEW in v2.0.0)
- Utilities for channel folder management
- Sanitizes channel names (transliteration, emoji removal)
- Formats channel IDs (removes `-` and `@`)
- Creates channel folder names: `{sanitized_title}_{channel_id}`
- Generates paths for channel downloads and trackers

**logger.py**
- Configures logging with rotation
- Console and file logging
- Health checks

### Dependencies (requirements.txt)

```
telethon==1.32.1       # Telegram API client library
pyyaml==6.0.1          # YAML configuration parsing
python-dateutil==2.8.2 # Date parsing and manipulation
humanize==4.8.0        # Human-readable file sizes/dates
aiofiles==23.2.1       # Async file operations
cryptg==0.4.0          # Crypto library for Telegram
```

### Per-Channel Structure (v2.0.0)

Each Telegram channel/group has:
- **Separate folder**: `{sanitized_channel_title}_{channel_id}/`
- **Separate trackers**: `message_tracker.json` and `file_tracker.json` in each folder
- **Independent tracking**: Progress tracked separately per channel

**Folder naming example:**
- Channel: "Music & Rock 🎸"
- Channel ID: `-1001234567890`
- Folder name: `Music_Rock_1001234567890/`

### Key Features

**1. Concurrent Downloads**
- Download 1-5 files simultaneously
- Configurable via `concurrent_downloads` in config or `--workers` CLI option
- Intelligent rate limiting (requests_per_second, burst_size)
- Performance: 3x-5x faster than single-threaded mode
- Thread-safe file tracking

**2. Download Tracking**
- Per-channel message tracking (processed message IDs)
- Per-channel file tracking (hash-based duplicate detection)
- Blacklist support for problematic files
- Resume capability (continues from last processed message)

**3. Advanced Filtering**
- File types: audio, document
- Formats: .mp3, .flac, .wav, .aiff, .m4a, etc.
- Size range: min/max MB
- Date range: from/to dates

**4. Track Name Normalization**
- Optional cleanup of downloaded filenames
- Removes message IDs, extra spaces, technical tags
- Configurable via `normalize_track_names: true/false`

**5. Progress Monitoring**
- Real-time download statistics
- Worker status and queue information
- Available with `--progress` flag

### How to Get Channel/Group ID

1. Forward any message from target channel to @ShowJsonBot
2. Bot replies with JSON containing channel info
3. Find `"chat":{"id":-1001234567890}` in response
4. Use the number after `"id":` (include minus sign for channels/groups)

### Workflow

1. **Initialization**: Load config, setup logging, initialize Telegram client
2. **Authentication**: Connect to Telegram (interactive login if needed)
3. **Channel Processing**: For each configured channel:
   - Get or create per-channel trackers
   - Retrieve channel entity
   - Parse messages starting from last processed ID
   - Filter media files based on criteria
   - Queue files for download
4. **Concurrent Downloading**: Worker pool processes queue with rate limiting
5. **Tracking**: Record downloaded files and processed messages per channel
6. **Cleanup**: Disconnect client, finalize logs

### CI/CD

**No CI/CD workflows found** - `.github/` directory does not exist.

Suggested CI checks (not implemented):
- Python linting (pylint, flake8)
- Type checking (mypy)
- Unit tests (pytest)
- Integration tests
- Code formatting (black, isort)

### Development Notes

- **Python version**: 3.9+ required
- **Async/await**: Heavily uses asyncio for I/O operations
- **Thread safety**: Download workers use threading with async coordination
- **Error handling**: Comprehensive error logging and recovery
- **No tests**: Testing infrastructure not present
- **AI-assisted development**: Project developed with AI assistance

### Recent Changes (v2.0.0)

- Added per-channel folder structure
- Implemented `TrackerManager` for managing per-channel trackers
- Created `channel_utils.py` with channel folder utilities
- Modified `MessageTracker` and `FileTracker` to work per-channel
- Updated `downloader.py` to use per-channel trackers and directories
- Updated `main.py` to create and use per-channel trackers

### Configuration Examples

**Concurrent downloads:**
```yaml
download:
  concurrent_downloads: 3
  max_queue_size: 100
  worker_timeout: 300
  rate_limit:
    requests_per_second: 2
    burst_size: 5
```

**Media filters:**
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

**Channels:**
```yaml
channels:
  - -1001234567890      # Private channel ID
  - "@musicchannel"     # Public channel username
  - -1009876543210      # Private group ID
```

### Troubleshooting

- **API limits**: Reduce workers or adjust rate limits
- **Connection issues**: Use `--workers 1` for unstable connections
- **Missing files cleanup**: Run with `--cleanup` flag
- **View statistics**: Run with `--stats` flag
- **Logs**: Check `data/logs/downloader.log` for detailed information

### License

MIT License
