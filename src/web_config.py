import copy
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from config import ConfigLoader


_MISSING = object()
_INTEGER_STRING = re.compile(r"^-?\d+$")
_DATE_STRING = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FILE_TYPES = ("audio", "document")
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_DATE_FROM_PATH = ("filters", "date", "from")
# Read-only fields from read() that a client may echo back; ignored on update.
_READ_ONLY_KEYS = {("telegram", "api_hash_set"), ("telegram", "api_hash_hint")}


class ConfigValidationError(ValueError):
    def __init__(self, errors: List[str]) -> None:
        self.errors: List[str] = list(errors)
        super().__init__("; ".join(self.errors))


Validator = Callable[[str, Any, List[str]], Any]


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bool(name: str, value: Any, errors: List[str]) -> Any:
    if not isinstance(value, bool):
        errors.append(f"{name} must be true or false")
    return value


def _string(name: str, value: Any, errors: List[str]) -> Any:
    if not isinstance(value, str):
        errors.append(f"{name} must be a string")
    return value


def _non_empty_string(name: str, value: Any, errors: List[str]) -> Any:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{name} must be a non-empty string")
    return value


def _int_range(minimum: int, maximum: Optional[int] = None) -> Validator:
    def validate(name: str, value: Any, errors: List[str]) -> Any:
        valid = _is_int(value) and value >= minimum
        if maximum is not None:
            valid = valid and value <= maximum
            if not valid:
                errors.append(f"{name} must be an integer between {minimum} and {maximum}")
        elif not valid:
            errors.append(f"{name} must be an integer >= {minimum}")
        return value

    return validate


def _number_min(minimum: float, strict: bool) -> Validator:
    def validate(name: str, value: Any, errors: List[str]) -> Any:
        if not _is_number(value) or (value <= minimum if strict else value < minimum):
            errors.append(f"{name} must be a number {'>' if strict else '>='} {minimum:g}")
        return value

    return validate


def _optional_number(name: str, value: Any, errors: List[str]) -> Any:
    if value is not None and (not _is_number(value) or value < 0):
        errors.append(f"{name} must be null or a number >= 0")
    return value


def _optional_date(name: str, value: Any, errors: List[str]) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and _DATE_STRING.match(value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            pass
    errors.append(f"{name} must be null or a date in YYYY-MM-DD format")
    return value


def _api_id(name: str, value: Any, errors: List[str]) -> Any:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not _is_int(value) or value <= 0:
        errors.append(f"{name} must be a positive integer")
    return value


def _channels(name: str, value: Any, errors: List[str]) -> Any:
    if not isinstance(value, list) or not value:
        errors.append(f"{name} must be a non-empty list")
        return value
    channels: List[Any] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and item.strip():
            item = item.strip()
            if _INTEGER_STRING.match(item):
                item = int(item)
        elif not _is_int(item):
            errors.append(f"{name}[{index}] must be a non-empty string or an integer")
            continue
        if item in channels:
            errors.append(f"{name}[{index}] duplicates channel {item}")
            continue
        channels.append(item)
    return channels


def _file_types(name: str, value: Any, errors: List[str]) -> Any:
    if not isinstance(value, list) or not value:
        errors.append(f"{name} must be a non-empty list")
        return value
    file_types: List[str] = []
    for item in value:
        if item not in _FILE_TYPES:
            errors.append(f"{name} contains unsupported value {item!r} (allowed: audio, document)")
        elif item not in file_types:
            file_types.append(item)
    return file_types


def _formats(name: str, value: Any, errors: List[str]) -> Any:
    if not isinstance(value, list) or not value:
        errors.append(f"{name} must be a non-empty list")
        return value
    formats: List[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip().lstrip("."):
            errors.append(f"{name}[{index}] must be a non-empty extension string")
            continue
        extension = "." + item.strip().lstrip(".").lower()
        if extension not in formats:
            formats.append(extension)
    return formats


def _log_level(name: str, value: Any, errors: List[str]) -> Any:
    if not isinstance(value, str) or value.upper() not in _LOG_LEVELS:
        errors.append(f"{name} must be one of DEBUG, INFO, WARNING, ERROR")
        return value
    return value.upper()


SCHEMA: Dict[str, Any] = {
    "telegram": {
        "api_id": _api_id,
        "api_hash": _string,
        "two_factor_auth": _bool,
    },
    "channels": _channels,
    "download": {
        "output_dir": _non_empty_string,
        "timeout_between_messages": _number_min(0, strict=False),
        "max_files_per_run": _int_range(0),
        "concurrent_downloads": _int_range(1, 20),
        "max_queue_size": _int_range(1),
        "rate_limit": {
            "requests_per_second": _number_min(0, strict=True),
            "burst_size": _int_range(1),
        },
    },
    "naming": {
        "template": _non_empty_string,
        "date_format": _non_empty_string,
    },
    "normalize_track_names": _bool,
    "filters": {
        "file_types": _file_types,
        "formats": _formats,
        "size": {"min_mb": _optional_number, "max_mb": _optional_number},
        "duration": {"min_sec": _optional_number, "max_sec": _optional_number},
        "date": {"from": _optional_date, "to": _optional_date},
    },
    "logging": {
        "level": _log_level,
        "console": _bool,
    },
}

_RANGE_CHECKS = (
    (("filters", "size", "min_mb"), ("filters", "size", "max_mb")),
    (("filters", "duration", "min_sec"), ("filters", "duration", "max_sec")),
    (("filters", "date", "from"), ("filters", "date", "to")),
)


def _leaf_paths(schema: Dict[str, Any], prefix: Tuple[str, ...] = ()) -> List[Tuple[str, ...]]:
    paths: List[Tuple[str, ...]] = []
    for key, rule in schema.items():
        if isinstance(rule, dict):
            paths.extend(_leaf_paths(rule, prefix + (key,)))
        else:
            paths.append(prefix + (key,))
    return paths


_LEAF_PATHS = _leaf_paths(SCHEMA)


def _get_path(data: Any, path: Tuple[str, ...], default: Any = _MISSING) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def _set_path(data: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    for key in path[:-1]:
        if not isinstance(data.get(key), dict):
            data[key] = {}
        data = data[key]
    data[path[-1]] = value


def _remove_path(data: Dict[str, Any], path: Tuple[str, ...]) -> bool:
    parents = []
    node: Any = data
    for key in path[:-1]:
        if not isinstance(node, dict) or not isinstance(node.get(key), dict):
            return False
        parents.append((node, key))
        node = node[key]
    if not isinstance(node, dict) or path[-1] not in node:
        return False
    del node[path[-1]]
    for parent, key in reversed(parents):
        if parent[key]:
            break
        del parent[key]
    return True


def _deep_update(target: Dict[str, Any], updates: Dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_value(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left == right


def _write_atomic(path: Path, data: bytes) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_bytes(data)
    temporary_path.replace(path)


class WebConfigService:
    def __init__(self, config_path: str) -> None:
        self.config_path = config_path

    def read(self) -> Dict[str, Any]:
        loader = ConfigLoader(self.config_path)
        raw = loader._config
        telegram = raw.get("telegram") or {}
        download = raw.get("download") or {}
        filters = raw.get("filters") or {}
        api_hash = telegram.get("api_hash")
        api_hash = api_hash if isinstance(api_hash, str) else ""
        date_filter = filters.get("date") or {}
        return {
            "base_path": str(loader.base_config_path),
            "local_path": str(loader.local_config_path),
            "local_exists": loader.local_config_path.exists(),
            "config": {
                "telegram": {
                    "api_id": loader.get_api_id(),
                    "api_hash_set": bool(api_hash),
                    "api_hash_hint": f"****{api_hash[-4:]}" if api_hash else "",
                    "two_factor_auth": loader.is_two_factor_enabled(),
                },
                "channels": list(loader.get_channels()),
                "download": {
                    "output_dir": loader.get_download_dir(),
                    "timeout_between_messages": loader.get_message_timeout(),
                    "max_files_per_run": loader.get_max_files_per_run(),
                    "concurrent_downloads": loader.get_concurrent_downloads(),
                    "max_queue_size": loader.get_max_queue_size(),
                    "rate_limit": {
                        "requests_per_second": loader.get_requests_per_second(),
                        "burst_size": loader.get_burst_size(),
                    },
                },
                "naming": {
                    "template": loader.get_naming_template(),
                    "date_format": loader.get_date_format(),
                },
                "normalize_track_names": loader.get_normalize_track_names(),
                "filters": {
                    "file_types": list(loader.get_file_types()),
                    "formats": list(loader.get_allowed_formats()),
                    "size": loader.get_size_filter(),
                    "duration": loader.get_duration_filter(),
                    "date": {
                        "from": date_filter.get("from"),
                        "to": date_filter.get("to"),
                    },
                },
                "logging": {
                    "level": loader.get_log_level(),
                    "console": loader.is_console_logging_enabled(),
                },
            },
        }

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        loader = ConfigLoader(self.config_path)
        current = copy.deepcopy(loader._config)

        updates = self._validate(payload, current)

        effective = copy.deepcopy(current)
        _deep_update(effective, updates)

        base_path = loader.base_config_path
        local_path = loader.local_config_path
        base_bytes = base_path.read_bytes()
        local_bytes = local_path.read_bytes() if local_path.exists() else None

        base_raw = yaml.safe_load(base_bytes.decode("utf-8")) or {}
        old_local: Dict[str, Any] = {}
        if local_bytes is not None:
            loaded_local = yaml.safe_load(local_bytes.decode("utf-8"))
            if loaded_local is not None and not isinstance(loaded_local, dict):
                raise ConfigValidationError(
                    [f"{local_path} is not a YAML mapping; fix or remove it before saving"]
                )
            old_local = loaded_local or {}
        new_local = copy.deepcopy(old_local)

        for path in _LEAF_PATHS:
            if path == _DATE_FROM_PATH:
                continue
            value = _get_path(effective, path)
            if value is _MISSING:
                continue
            base_value = _get_path(base_raw, path)
            if _same_value(base_value, value) or (base_value is _MISSING and value is None):
                _remove_path(new_local, path)
            else:
                _set_path(new_local, path, value)

        local_had_date_from = _get_path(old_local, _DATE_FROM_PATH) is not _MISSING
        _remove_path(new_local, _DATE_FROM_PATH)
        new_date_from = _get_path(effective, _DATE_FROM_PATH, None)
        date_from_changed = not _same_value(
            _get_path(current, _DATE_FROM_PATH, None), new_date_from
        )

        try:
            if date_from_changed or local_had_date_from:
                loader.set_date_from(new_date_from)
            if new_local != old_local or (local_bytes is None and new_local):
                _write_atomic(
                    local_path,
                    yaml.safe_dump(
                        new_local, sort_keys=False, allow_unicode=True
                    ).encode("utf-8"),
                )
            ConfigLoader(self.config_path)
        except Exception as exc:
            _write_atomic(base_path, base_bytes)
            if local_bytes is None:
                local_path.unlink(missing_ok=True)
            else:
                _write_atomic(local_path, local_bytes)
            raise ConfigValidationError([str(exc)]) from exc

        return self.read()

    def _validate(self, payload: Any, current: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ConfigValidationError(["config must be an object"])
        errors: List[str] = []
        updates = self._validate_section(payload, SCHEMA, (), errors)

        telegram_updates = updates.get("telegram")
        if isinstance(telegram_updates, dict) and telegram_updates.get("api_hash") == "":
            del telegram_updates["api_hash"]
            if not telegram_updates:
                del updates["telegram"]

        if not errors:
            effective = copy.deepcopy(current)
            _deep_update(effective, updates)
            for low_path, high_path in _RANGE_CHECKS:
                low = _get_path(effective, low_path, None)
                high = _get_path(effective, high_path, None)
                comparable = (_is_number(low) and _is_number(high)) or (
                    isinstance(low, str) and isinstance(high, str)
                )
                if comparable and low > high:
                    errors.append(
                        f"{'.'.join(low_path)} must not be greater than {'.'.join(high_path)}"
                    )

        if errors:
            raise ConfigValidationError(errors)
        return updates

    def _validate_section(
        self,
        payload: Dict[str, Any],
        schema: Dict[str, Any],
        prefix: Tuple[str, ...],
        errors: List[str],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in payload.items():
            path = prefix + (key,)
            name = ".".join(str(part) for part in path)
            if path in _READ_ONLY_KEYS:
                continue
            if key not in schema:
                errors.append(f"{name} is not a supported setting")
                continue
            rule = schema[key]
            if isinstance(rule, dict):
                if not isinstance(value, dict):
                    errors.append(f"{name} must be an object")
                    continue
                section = self._validate_section(value, rule, path, errors)
                if section:
                    result[key] = section
            else:
                result[key] = rule(name, value, errors)
        return result
