"""Shared YAML helpers for Dropout and YouTube manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from yt_dlp_emby.config import ConfigError, format_yaml_error

CHILD_FORBIDDEN_KEYS = frozenset({"library", "old_dir", "cookies", "staging", "imports"})
_NAME_BAD = frozenset({"/", "\\"})


def require_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing {key} in {context}")
    return value.strip()


def optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))


def optional_str_path(value: Any, key: str, context: str) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a string in {context}")
    return Path(value.strip())


def int_field(value: Any, key: str, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer in {context}")
    return value


def validate_series_name(name: str, context: str) -> str:
    text = name.strip()
    if not text:
        raise ConfigError(f"Missing name in {context}")
    if any(ch in text for ch in _NAME_BAD) or ".." in text:
        raise ConfigError(f"series name must not contain / \\ or .. in {context}")
    return text


def parse_imports_list(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("imports must be a list of paths")
    if not raw:
        return ()
    paths: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError("imports entries must be non-empty strings")
        paths.append(item.strip())
    return tuple(paths)


def load_yaml_mapping(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"Import file not found: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc
