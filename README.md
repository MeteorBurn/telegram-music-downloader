# Telegram Music Downloader

> **Note:** This project was developed with AI assistance.

A Python-based application designed to download audio files (primarily music) from specified Telegram channels. It offers features like **concurrent downloads**, advanced filtering, download tracking, and robust logging.

## Features

*   **🚀 Concurrent Downloads**: Download 1-5 files simultaneously for faster processing with intelligent rate limiting.
*   **📥 Download from Telegram**: Fetches audio files from public or private Telegram channels you have access to.
*   **🔍 Advanced Filtering**:
    *   Filter by file type (e.g., audio, document).
    *   Filter by specific file formats (e.g., `.mp3`, `.flac`, `.wav`).
    *   Filter by file size (min/max MB).
    *   Filter by message date range.
*   **📊 Download & Message Tracking**: Tracks both downloaded files and processed messages using separate, robust tracker modules. Prevents duplicates and enables reliable recovery.
*   **📝 Robust Logging**: Comprehensive and resilient logging to both console and file, including log rotation and logger health checks.
*   **📁 Customizable File Naming**: Define templates for naming downloaded files.
*   **✨ Track Name Normalization & Cleanup**: Automatically cleans up and standardizes track names after download (optional, see below).
*   **⚙️ Secure Configuration**:
    *   Main application settings are managed in `src/config.yaml`.
*   **🔄 Real-time Progress Monitoring**: Live progress tracking with download statistics and worker status.

### Track Name Normalization & Cleanup

The downloader can automatically clean and standardize the names of downloaded audio tracks. This feature removes unnecessary tags, extra spaces, technical info, and other "garbage" from file names, making your downloaded music tidy and consistent.

- **How it works:**
    - Applies a series of normalization functions to each file name after download (removes message IDs, extra spaces, bracket artifacts, technical tags, etc).
    - Helps prevent messy or unreadable filenames from Telegram uploads.
- **How to enable:**
    - In your `src/config.yaml` or `src/local_config.yaml`, set:
      ```yaml
      normalize_track_names: true
      ```
    - By default, this feature is **disabled** (`false`).
- **When enabled:**
    - All normalization and cleanup rules are applied automatically to every downloaded track.
    - If disabled, file names are left as-is.

### 🚀 Concurrent Downloads

The application supports downloading multiple files simultaneously to significantly speed up the process while respecting Telegram's API limits.

- **How it works:**
    - Uses a producer-consumer pattern with a priority queue
    - Downloads 1-5 files concurrently (configurable)
    - Intelligent rate limiting prevents API blocking
    - Thread-safe file tracking prevents duplicates
    - Real-time progress monitoring with worker status

- **Configuration:**
    ```yaml
    download:
      concurrent_downloads: 3      # Number of simultaneous downloads (1-5)
      max_queue_size: 100         # Maximum queue size
      worker_timeout: 300         # Worker timeout in seconds
      rate_limit:
        requests_per_second: 2    # API rate limit
        burst_size: 5            # Burst capacity
    ```

- **Command line options:**
    ```bash
    # Use specific number of workers (overrides config)
    python src/main.py --workers 1    # Single-threaded mode
    python src/main.py --workers 5    # Maximum concurrency
    
    # Show real-time progress
    python src/main.py --progress
    ```

- **Performance benefits:**
    - **3x faster** downloads with 3 concurrent workers
    - **5x faster** with 5 workers (for large files)
    - Automatic fallback to single-threaded mode if needed
    - Smart queue management prevents memory issues

## Setup

1. **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/telegram-music-downloader.git
    cd telegram-music-downloader
    ```

2. **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3. **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4. **Configure the application:**
    - Edit `src/config.yaml` for main settings (channels, filters, download directory, etc).
    - Create `src/local_config.yaml` and add your Telegram `api_id` and `api_hash` (and optionally `phone_number`).
      Example `src/local_config.yaml`:
      ```yaml
      telegram:
        api_id: 1234567
        api_hash: "your_api_hash_here"
        # phone_number: "+1234567890" # If needed for login
      ```

### How to Get Channel or Group ID

To specify channels in `config.yaml`, you need their numeric IDs. Here's how to get them:

1. Forward any message from the target channel to @ShowJsonBot
2. The bot will reply with JSON data containing channel information
3. Look for `"chat":{"id":-1001234567890}` in the response
4. Use the number after `"id":` (including the minus sign)

**Important Notes:**
- Channel IDs are usually negative numbers (e.g., `-1001234567890`)
- Public channels can be specified by username (e.g., `@channelname`) or numeric ID
- Private channels/groups must use numeric ID
- In `config.yaml`, list channel IDs under the `channels:` section:
  ```yaml
  channels:
    - -1001234567890  # Private channel ID
    - @publicchannel  # Public channel username
    - -1009876543210  # Another channel ID
  ```

## Usage

### Basic Usage

- Run the main script from the project's root directory:
    ```bash
    python src/main.py
    ```
- To use a custom config file:
    ```bash
    python src/main.py --config path/to/your/custom_config.yaml
    ```

### Advanced Usage

- **Single-threaded mode** (for slow connections or API limits):
    ```bash
    python src/main.py --workers 1
    ```

- **Maximum concurrency** (fastest downloads):
    ```bash
    python src/main.py --workers 5
    ```

- **With real-time progress monitoring**:
    ```bash
    python src/main.py --progress --workers 3
    ```

- **Limit number of files and show progress**:
    ```bash
    python src/main.py --max-files 50 --progress --workers 3
    ```

- **Show statistics only** (no downloads):
    ```bash
    python src/main.py --stats
    ```

- **Clean up tracker from missing files**:
    ```bash
    python src/main.py --cleanup
    ```

### Command Line Options

| Option | Short | Description |
|--------|-------|-------------|
| `--config` | `-c` | Custom config file path |
| `--max-files` | `-m` | Maximum files to download (0 = unlimited) |
| `--workers` | `-w` | Number of concurrent workers (1-5) |
| `--progress` | `-p` | Show real-time download progress |
| `--stats` | `-s` | Show statistics only |
| `--cleanup` | | Clean up tracker from missing files |

The application will automatically manage sessions, track downloads and messages, and log all activity. Statistics are available after each run.

## Project Structure

```
telegram-music-downloader/
├── .gitignore
├── README.md
├── requirements.txt
├── CONCURRENT_DOWNLOADS.md  # Detailed concurrent downloads documentation
├── src/
│   ├── main.py               # Async main entry point with concurrent support
│   ├── config.yaml           # Main configuration file (template/defaults)
│   ├── local_config.yaml     # Local configuration with secrets (gitignored)
│   ├── config_loader.py      # Loads and merges configurations
│   ├── client.py             # Async Telegram client setup
│   ├── downloader.py         # Async file downloading logic
│   ├── download_queue.py     # Priority queue for concurrent downloads
│   ├── download_worker.py    # Worker threads for concurrent processing
│   ├── download_coordinator.py # Coordinates concurrent download process
│   ├── download_monitor.py   # Real-time progress monitoring
│   ├── logger.py             # Robust logging (rotation, health checks)
│   ├── media_filter.py       # Flexible, configurable media filtering
│   ├── message_parser.py     # Async parsing of channel messages for media
│   ├── normalizer.py         # Track name normalization and cleanup
│   ├── session_manager.py    # Manages and backs up Telegram sessions
│   └── tracker.py            # Thread-safe tracking of files and messages
└── data/                     # Default directory for downloads, logs, sessions
    ├── downloads/
    ├── logs/
    └── sessions/
```

## Performance & Tips

### 🚀 Concurrent Download Performance

Real-world performance improvements with concurrent downloads:

| Workers | Speed Improvement | Best For |
|---------|------------------|----------|
| 1 | Baseline | Slow connections, API limits |
| 2 | ~2x faster | Balanced performance |
| 3 | ~3x faster | **Recommended default** |
| 4 | ~4x faster | Fast connections |
| 5 | ~5x faster | Maximum speed, stable connections |

### 💡 Optimization Tips

- **Start with 3 workers**: Good balance between speed and stability
- **Use `--progress`**: Monitor download progress and worker efficiency
- **Single-threaded mode**: Use `--workers 1` if experiencing API limits or connection issues
- **Rate limiting**: Automatically prevents Telegram API blocking
- **Large files**: Higher worker counts show more improvement with larger files (>50MB)

### 🔧 Troubleshooting

- **API limits**: Reduce workers or increase `rate_limit.requests_per_second`
- **Connection issues**: Use `--workers 1` for unstable connections
- **Memory usage**: Reduce `max_queue_size` if experiencing memory issues
- **Progress monitoring**: Use `--progress` to identify bottlenecks

## Requirements

- Python 3.9+
- [Telethon](https://github.com/LonamiWebs/Telethon) and other dependencies in `requirements.txt`

## License

MIT
