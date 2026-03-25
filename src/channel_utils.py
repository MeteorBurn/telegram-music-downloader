import re
import unicodedata
from pathlib import Path
from typing import Union


def sanitize_channel_name(channel_title: str, max_length: int = 50) -> str:
    """
    Sanitize channel title for use in folder name

    Args:
        channel_title: Original channel title
        max_length: Maximum length of sanitized name

    Returns:
        Sanitized channel name safe for filesystem
    """
    if not channel_title or not isinstance(channel_title, str):
        return "Unknown"

    # Normalize unicode characters
    name = unicodedata.normalize("NFKD", channel_title)

    # Transliterate cyrillic to latin (basic transliteration)
    cyrillic_map = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Е": "E",
        "Ё": "Yo",
        "Ж": "Zh",
        "З": "Z",
        "И": "I",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "H",
        "Ц": "Ts",
        "Ч": "Ch",
        "Ш": "Sh",
        "Щ": "Sch",
        "Ъ": "",
        "Ы": "Y",
        "Ь": "",
        "Э": "E",
        "Ю": "Yu",
        "Я": "Ya",
    }

    # Apply transliteration
    transliterated = []
    for char in name:
        if char in cyrillic_map:
            transliterated.append(cyrillic_map[char])
        else:
            transliterated.append(char)
    name = "".join(transliterated)

    # Remove emojis and non-printable characters
    # Keep only alphanumeric, spaces, hyphens, and underscores
    name = re.sub(r"[^\w\s\-]", "", name, flags=re.UNICODE)

    # Replace spaces with underscores
    name = re.sub(r"\s+", "_", name)

    # Remove multiple consecutive underscores
    name = re.sub(r"_+", "_", name)

    # Remove leading/trailing underscores
    name = name.strip("_")

    # Truncate to max length
    if len(name) > max_length:
        name = name[:max_length].rstrip("_")

    # If name is empty after sanitization, return default
    if not name:
        return "Unknown"

    return name


def format_channel_id(channel_id: Union[str, int]) -> str:
    """
    Format channel ID for use in folder name
    Remove minus sign and @ symbol

    Args:
        channel_id: Channel ID (can be numeric or username)

    Returns:
        Formatted channel ID without minus or @ symbols
    """
    channel_id_str = str(channel_id)

    # Remove minus sign
    if channel_id_str.startswith("-"):
        channel_id_str = channel_id_str[1:]

    # Remove @ symbol
    if channel_id_str.startswith("@"):
        channel_id_str = channel_id_str[1:]

    return channel_id_str


def create_channel_folder_name(
    channel_title: str, channel_id: Union[str, int], max_title_length: int = 50
) -> str:
    """
    Create folder name for channel in format: {sanitized_title}_{channel_id}

    Args:
        channel_title: Original channel title
        channel_id: Channel ID (numeric or username) - used as-is from config.yaml
        max_title_length: Maximum length for title part

    Returns:
        Folder name in format: ChannelName_{channel_id}

    Examples:
        >>> create_channel_folder_name("Music & Rock 🎸", -1001234567890)
        'Music_Rock_-1001234567890'
        >>> create_channel_folder_name("Музыка", -1009876543210)
        'Muzyka_-1009876543210'
        >>> create_channel_folder_name("Jazz", "@jazzmusic")
        'Jazz_@jazzmusic'
    """
    sanitized_title = sanitize_channel_name(channel_title, max_title_length)
    # Use channel_id as-is, without any formatting
    channel_id_str = str(channel_id)

    return f"{sanitized_title}_{channel_id_str}"


def get_channel_directory(
    base_dir: Union[str, Path], channel_title: str, channel_id: Union[str, int]
) -> Path:
    """
    Get channel directory path

    Args:
        base_dir: Base download directory from config
        channel_title: Channel title
        channel_id: Channel ID

    Returns:
        Path to channel directory
    """
    base_path = Path(base_dir)
    folder_name = create_channel_folder_name(channel_title, channel_id)
    return base_path / folder_name


def get_channel_downloads_dir(
    base_dir: Union[str, Path], channel_title: str, channel_id: Union[str, int]
) -> Path:
    """
    Get channel downloads subdirectory

    Args:
        base_dir: Base download directory from config
        channel_title: Channel title
        channel_id: Channel ID

    Returns:
        Path to channel downloads directory
    """
    channel_dir = get_channel_directory(base_dir, channel_title, channel_id)
    return channel_dir / "downloads"


def get_channel_state_path(
    base_dir: Union[str, Path],
    channel_title: str,
    channel_id: Union[str, int],
    filename: str,
) -> Path:
    """Get path to a state file inside the channel directory."""
    channel_dir = get_channel_directory(base_dir, channel_title, channel_id)
    return channel_dir / filename


def get_channel_tracker_path(
    base_dir: Union[str, Path],
    channel_title: str,
    channel_id: Union[str, int],
    tracker_type: str,
) -> Path:
    """Backward-compatible wrapper for tracker path lookup."""
    tracker_filenames = {
        "message": "scan_state.json",
        "file": "download_state.json",
    }
    return get_channel_state_path(
        base_dir,
        channel_title,
        channel_id,
        tracker_filenames.get(tracker_type, tracker_type),
    )
