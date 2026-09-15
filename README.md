# 🎵 Telegram Music Downloader

> **Bring your Telegram music collection to disk.**
> Multiple channels · Parallel downloads · Flexible filters · Organized folders

Download audio and document attachments from Telegram channels and groups you can
access. Choose the formats you want, give your files useful names, and pick up
scanning where the previous run left off.

---

## ✨ Features

| | What you can do |
|---|---|
| 📥 **Collect from multiple channels** | Keep each channel's downloads in its own folder |
| ⚡ **Download in parallel** | Choose the worker count and pace of download attempts |
| 🔍 **Choose what to keep** | Filter by format, size, date and track duration |
| 🏷️ **Make filenames your own** | Use templates and optional track-name cleanup |
| 🔄 **Continue later** | Resume scanning from the saved message checkpoint |
| 📋 **See what happened** | Read download results, skips and errors in one session log |

---

## 🚀 Quick Start

You'll need **Python 3.9+**, Telegram API credentials from
[my.telegram.org](https://my.telegram.org), and access to your chosen channels.
For duration filtering when Telegram has no usable audio duration, you'll also
need **FFmpeg's `ffprobe` on `PATH`**.

### 📦 1. Install

**Windows · PowerShell**

```powershell
git clone https://github.com/MeteorBurn/TelegramDownloader.git telegram-music-downloader
cd telegram-music-downloader

python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\Activate.ps1
```

<details>
<summary>🍎 Installation on macOS / Linux</summary>

Clone the repository, then run these commands inside its folder:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
source venv/bin/activate
```

</details>

### 🔑 2. Add your credentials and channels

Create **`src/local_config.yaml`** with your own API credentials and channel list:

```yaml
telegram:
  api_id: 1234567
  api_hash: "your_api_hash_here"
  two_factor_auth: true

channels:
  - "@musicchannel"       # Public channel username
  - -1001234567890         # Private channel or group ID

filters:
  date:
    from: "2026-01-01"    # Start with messages published from this date
```

Your account must already have access to these channels. Keep numeric IDs as numbers,
including the minus sign. The local file is ignored by Git.

> 💡 You only need to include settings you want to change. The app automatically
> combines `src/config.yaml` with your `src/local_config.yaml`.

### 🎧 3. Start downloading

```powershell
python src/main.py --max-files 20
```

On the first run, enter your **phone number**, **verification code**, and your
**2FA password** if requested. Keep `two_factor_auth: true` if your account uses 2FA.
The login is saved in `telegram.session` and reused on later runs.

Look in **`data/downloads/`** for your channel folders and **`console.log`** for results.
The example queues at most 20 files; skips and failures can mean fewer files are saved.

> 📌 Run commands from the project folder with the virtual environment activated.
> On Windows, you can also use `.\venv\Scripts\python.exe` directly.

---

## ⚙️ Configuration

Use **`src/config.yaml` for the base settings** and **`src/local_config.yaml` for your
personal overrides**. A local setting wins over its base value. Lists such as
`channels` and `formats` replace the whole base list.

### 📝 Main Config

A complete example with every setting filled in: **tracks from 3 to 15 minutes,
published during 2026**. Use it as a reference for your own settings, and replace
the sample credentials and channels.

```yaml
telegram:
  api_id: 12345678
  api_hash: "your_api_hash_here"
  two_factor_auth: true

channels:
  - -1001234567890
  - "@musicchannel"
  - -1009876543210

download:
  output_dir: "./data/downloads"
  timeout_between_messages: 0.3  # Pause between scanned messages, in seconds
  max_files_per_run: 100         # Newly queued tasks across all channels; 0 = no limit
  concurrent_downloads: 5        # Concurrent asyncio workers
  max_queue_size: 100            # Waiting-queue capacity
  worker_timeout: 300           # Present in config, but not used by the runtime
  rate_limit:
    requests_per_second: 2      # Shared rate of worker download attempts
    burst_size: 5               # Maximum token allowance

naming:
  template: "{original_name}__{message_id}"
  date_format: "%Y%m%d_%H%M%S"

normalize_track_names: false

filters:
  file_types: ["audio", "document"]
  formats: [".flac", ".wav", ".aiff", ".aif", ".m4a", ".dsf", ".ape", ".wv", ".mp3"]
  size:
    min_mb: 1                   # Minimum file size, in MiB
    max_mb: 500                 # Maximum file size, in MiB
  duration:
    min_sec: 180                # 3 minutes
    max_sec: 900                # 15 minutes
  date:
    from: "2026-01-01"          # First publication date to include
    to: "2026-12-31"            # Last publication date to include

logging:
  level: "INFO"
  console: true
```

> 📌 This example enables duration filtering, with `ffprobe` as a fallback. The supplied
> [base config](src/config.yaml) leaves duration limits and the end date unset.

### 🔍 Tune your filters

| Filter | How to use it |
|---|---|
| **Type** | `audio` accepts audio MIME types; `document` accepts other Telegram document attachments |
| **Format** | Use extensions such as `.flac` or `.mp3`; matching ignores case |
| **Size** | Set `min_mb` and `max_mb`; values use MiB, shown as MB in the app |
| **Date** | Use quoted dates like `"2026-01-01"`; `null` removes a bound |
| **Duration** | Set `min_sec` and `max_sec`; both `null` disables the check |

Size and duration bounds include their endpoints. An empty type or format list
(`[]`) disables that filter. Photos and other non-document media are skipped.

**Example: keep tracks between 3 and 15 minutes.** Add this to your local config:

```yaml
filters:
  duration:
    min_sec: 180
    max_sec: 900
```

> ⏱️ Telegram audio duration is checked **during scanning, before queueing**. Files
> outside the range are skipped and logged as `[FILTER] duration`. A positive, finite
> numeric duration is used directly. Missing, zero, negative or invalid metadata falls
> back to `ffprobe` **after downloading**; rejected files are deleted. If probing fails,
> the app reports a failure and attempts to remove the file. Existing-file skips bypass
> this fallback, so changing the limit does not recheck files already in your collection.

### ⚡ Adjust download speed

Start with the supplied worker count, or try `--workers 1` for an unstable connection.
`requests_per_second` and `burst_size` control how often workers begin download
attempts; they do not limit every Telegram request or the transfer speed in MB/s.

`max_queue_size` controls how many files can wait for a worker. Scanning pauses when
that queue fills up.

> 🛠️ `worker_timeout` is present in the config but currently has no effect.

### 🗂️ Use another config file

```powershell
python src/main.py --config path/to/config.yaml
```

The selected file must be a complete base config. The app then looks for
`local_config.yaml` beside it. For the usual setup, simply run `python src/main.py`:
passing a partial `src/local_config.yaml` directly to `--config` will not load the
base settings first.

---

## 📥 Everyday Commands

```powershell
# Download with your configured settings.
python src/main.py

# Queue up to 30 files with three workers.
python src/main.py --max-files 30 --workers 3

# See stored download counts for each channel.
python src/main.py --stats

# Remove records for files you have deleted from disk.
python src/main.py --cleanup
```

**How the file limit works:** the app uses the smaller positive limit from your
config and `--max-files`. With `max_files_per_run: 100`, passing `--max-files 20`
queues up to 20 tasks. Passing `--max-files 0` still leaves the config limit of 100
in place. Set both limits to `0` for an unlimited run.

<details>
<summary>📋 All CLI options</summary>

| Option | Short | What it does |
|---|---|---|
| `--config PATH` | `-c` | Select a base config; default: `src/config.yaml` |
| `--max-files N` | `-m` | Limit queued files for this run; default: `0` |
| `--workers N` | `-w` | Override the worker count for this run only |
| `--stats` | `-s` | Show stored statistics without connecting to Telegram |
| `--cleanup` | | Remove missing-file records without connecting to Telegram |
| `--progress` | `-p` | Check in-process progress; a standalone run reports no active session |
| `--help` | `-h` | Show command help |

Use one utility mode at a time. These modes still read your config and write to the
log. `--progress` cannot connect to a download running in another terminal; use
`--stats` for saved counts.

</details>

---

## 🏷️ Filenames

The default template keeps the original name and adds the Telegram message ID:

```text
{original_name}__{message_id}  →  Artist - Track__12345.flac
```

The extension is added automatically. You can change `naming.template` with these fields:

| Field | Inserts |
|---|---|
| `{original_name}` | Original filename without the extension |
| `{message_id}` | Telegram message ID |
| `{publish_date}` | Message date, formatted using `naming.date_format` |
| `{download_date}` | Local time when the filename is generated |
| `{artist}` | Performer from Telegram audio metadata |
| `{title}` | Track title from Telegram audio metadata |
| `{duration}` | Duration in seconds from Telegram audio metadata |
| `{file_size}` | Reported file size in bytes |
| `{mime_type}` | MIME type, with `/` replaced by `_` |

| Example template | Example filename |
|---|---|
| `{original_name}__{message_id}` | `Artist - Track__12345.flac` |
| `{publish_date}_{original_name}` | `20260916_120000_Artist - Track.flac` |
| `{artist} - {title}__{message_id}` | `Artist - Track__12345.flac` |

Dates use `%Y%m%d_%H%M%S` by default. Audio metadata is not always available; when a
template cannot be filled in, the app falls back to `file_<message_id><extension>`.

**Want cleaner names?** Set `normalize_track_names: true`. It normalizes spacing
and Unicode, replaces underscores with spaces, removes terminal `__digits` IDs,
and removes repeated audio extensions matching the actual file suffix. Known mix
phrases and complete version groups move to the end, followed by square-bracket
labels. An explicitly separated version such as
`Artist - Track - Alice Remix` becomes `Artist - Track (Alice Remix)`.

**Track numbering:** vinyl positions such as `A1` and `B2` move to the beginning,
including forms such as `B2.`. When an ordinal and vinyl position occur together
at the start of the name or a dash-separated field, the vinyl position takes
precedence: `Artist - Release Name - 04 B2. Title` becomes
`B2 Artist - Release Name - Title`.
Other numeric track positions are retained.

Cleanup removes Camelot key markers, release tags such as `WEB`, `PROMO`, `FLAC`,
`EP` and `VINYL ONLY` in metadata positions, empty brackets, technical suffixes
such as `24bit 48kHz`, isolated source URL suffixes, and repeated version groups.
Recognized mastering suffixes such as `MBMASTER2`, `MSTR24` or `(Master)` and
separated copy suffixes such as `Artist - Track - Copy` are also removed.

**Version labels:** explicit split labels such as `Original Extended (Version)`,
`Extended (Remix)` and `Radio (Edit)` are joined inside parentheses. Complete
groups such as `(Original Mix)` are kept intact: `Paid In Full (Original Mix)`
and `All Night Long (Original Mix)` keep their title words. Ambiguous qualifiers
are left outside the version group. Musical versions such as `Instrumental`,
`Full`, `Clean`/`Dirty`, punctuation in initials/ellipsis, and mixed-case words
such as `Web` or `Vinyl` inside names are retained.

Unknown working markers and ambiguous fragments remain for review. Bracket repair
is limited to an unambiguous terminal version/technical group with mismatched
delimiters. Unsafe results keep the generated name. DEBUG logs include change
reasons and ambiguity warnings. Existing library files are not renamed automatically.

> 🏷️ Different messages can normalize to the same filename. When that destination
> exists, the new file is downloaded and compared by content. Identical files are
> skipped and the new copy is removed; different content or a comparison error keeps
> the new file under its generated name. Already-tracked messages and existing generated
> paths can still skip downloading. Keep `{message_id}` in the template to distinguish
> generated paths.

---

## 📂 Your Download Folder

Each channel gets its own folder, with the music and its saved progress together:

```text
telegram-music-downloader/
├── telegram.session                  # Saved Telegram login
└── data/downloads/
    ├── console.log                   # Session transcript
    ├── Music_Channel_-1001234567890/
    │   ├── scan_state.json           # Where scanning resumes
    │   ├── download_state.json       # Saved files and blacklist
    │   └── downloads/
    │       └── Artist - Track__12345.flac
    └── Public_Music_@musicchannel/
        └── ...
```

Folder names combine a cleaned-up channel title with the identifier from your config.
Keep your output path and channel identifiers consistent between runs.

### 🔄 Continue a previous run

Run the same command again. Scanning continues after the saved checkpoint: the last
message through which all earlier messages have finished processing. That includes
skipped messages and ordinary failures, so those may not be tried again on the next run.

### 🧹 Clean up after deleting files

Run `python src/main.py --cleanup` to remove records for files that no longer exist.
This updates the stored counts; it does not delete music or clear the blacklist.

> 📌 Cleanup and filter changes **do not rewind scanning**. There is no CLI command
> to reset the checkpoint or automatically download missing historical files again.

<details>
<summary>🔎 A few things to know about saved state</summary>

- Statistics include all channel folders under the output directory, even channels
  removed from your config. They show stored records, not a fresh integrity check.
- A file that already exists is accepted by its path. Partial files are not resumed
  or checked for completeness, so an interrupted download may later be skipped.
- Ordinary download failures allow up to three attempts. Errors mentioning `flood`
  or `timeout` add the message to that channel's blacklist; later attempts can be skipped.
- If a state file cannot be loaded, the app logs an error and starts with empty state.
  It does not make a recovery backup. Inspect the affected JSON before continuing.
- The current state files use schema version 2. Legacy `message_tracker.json` and
  `file_tracker.json` are not imported.

</details>

---

## 📋 Session Log

Open **`download.output_dir/console.log`** to see what happened during a run.
The app appends to the same file, rotating it at 10 MiB and keeping five older copies.

| Look for | Meaning |
|---|---|
| `[AUTH]` · `[CHANNEL]` | Login and channel scanning |
| `[QUEUE]` · `[WORKER_N]` | Queued files and worker activity |
| `[OK]` | Successful download |
| `[SKIP]` · `[FILTER]` | A file was skipped or rejected by a filter |
| `[RENAME]` | A filename was normalized |
| `[FAIL]` · `[CRITICAL]` | A failure that needs attention |
| `[RESULTS]` · `[SUMMARY]` | Totals for the session |

Keep `logging.level: "INFO"` for everyday use; choose `"DEBUG"` when investigating a
problem. `logging.console: false` removes the console log handler, but explicit output
such as statistics and summaries can still appear in the terminal.

---

## 🔧 Troubleshooting

| What you see | What to check |
|---|---|
| **Missing config section** | Run with the base config; a partial local override cannot stand alone |
| **Nothing downloads** | Check channel access, the date/format/size filters, and the saved checkpoint |
| **Fewer files than the limit** | The limit counts queued files; check the log for skips, failures and duration rejections |
| **Could not determine duration** | Make sure `ffprobe` is on `PATH`, then read its error in the log |
| **Flood or timeout errors** | Lower the worker count or attempt rate; check `[BLACKLIST]` entries |
| **Files still missing after cleanup** | Cleanup updates records, but does not rescan older messages |
| **No active session with `--progress`** | This command cannot watch another process; use `--stats` for saved counts |

---

## 🧪 Development

Dependencies are pinned in [requirements.txt](requirements.txt). Run the synthetic
suite from the project root:

```powershell
python -m unittest discover -s tests
```

The tests use temporary files and fake Telegram clients. They do not log in to your
account or download from Telegram; duration tests also simulate the probe result.

<details>
<summary>🛠️ Focused checks and code navigation</summary>

| Test module | Covers |
|---|---|
| `tests/test_app.py` | Statistics, cleanup, progress and configuration |
| `tests/test_runtime.py` | Queueing, downloads, Telegram duration and probe fallback, filename collisions, retries and shutdown |
| `tests/test_state.py` | Saved state and checkpoint behavior |
| `tests/test_logging.py` | Shared logging and session output |

```powershell
python -m unittest tests.test_runtime
python -m compileall src tests
git diff --check
```

Start at `src/main.py` for the CLI and `src/app.py` for session orchestration.
[AGENTS.md](AGENTS.md) contains the full source map and development guidance.

</details>

---

## 🔐 Keep Your Data Private

Keep **API credentials**, **`telegram.session`**, **logs** and **downloaded media**
out of commits. The local config, session files and default `data/` directory are
ignored by Git. If you save downloads elsewhere, check that location separately;
rotated logs outside `data/` are not covered by the `*.log` rule.
