"""Resolve library/old_dir from CLI flags, environment, then a config file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import tomllib

from yt_emby.ffmpeg import FFmpegNotFoundError, find_ffmpeg

__all__ = [
    "ConfigError",
    "FFmpegNotFoundError",
    "MissingPathError",
    "Settings",
    "resolve_settings",
]


class ConfigError(Exception):
    """Invalid or incomplete configuration."""


class MissingPathError(ConfigError):
    """library or old_dir was not provided."""


@dataclass(frozen=True)
class Settings:
    library: Path
    old_dir: Path
    ffmpeg: Path
    config_path: Path | None = None
    season: int | None = None
    cookies_from_browser: str | None = None
    dry_run: bool = False
    ffmpeg_location: str | None = None


def _load_toml(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for key in ("library", "old_dir"):
        value = data.get(key)
        if value is not None:
            result[key] = str(value)
    return result


def _config_file(
    config_path: str | None,
    environ: Mapping[str, str],
    cwd: Path,
) -> Path | None:
    if config_path:
        return Path(config_path)
    env_path = environ.get("YT_EMBY_CONFIG")
    if env_path:
        return Path(env_path)
    default = cwd / "config.toml"
    if default.is_file():
        return default
    return None


def _pick(
    cli_value: str | None,
    env_value: str | None,
    file_value: str | None,
) -> str | None:
    return cli_value or env_value or file_value


def resolve_settings(
    *,
    library: str | None = None,
    old_dir: str | None = None,
    config_path: str | None = None,
    ffmpeg_location: str | None = None,
    season: int | None = None,
    cookies_from_browser: str | None = None,
    dry_run: bool = False,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Settings:
    if environ is None:
        environ = os.environ
    cwd = cwd if cwd is not None else Path.cwd()

    file_path = _config_file(config_path, environ, cwd)
    file_values: dict[str, str] = {}
    if file_path is not None:
        if not file_path.is_file():
            raise ConfigError(f"Config file not found: {file_path}")
        file_values = _load_toml(file_path)

    resolved_library = _pick(library, environ.get("YT_EMBY_LIBRARY"), file_values.get("library"))
    resolved_old = _pick(old_dir, environ.get("YT_EMBY_OLD_DIR"), file_values.get("old_dir"))

    missing: list[str] = []
    if not resolved_library:
        missing.append("library (--library, YT_EMBY_LIBRARY, or config library)")
    if not resolved_old:
        missing.append("old_dir (--old-dir, YT_EMBY_OLD_DIR, or config old_dir)")
    if missing:
        raise MissingPathError(
            "Missing required path(s): "
            + ", ".join(missing)
            + ". Pass them as flags, environment variables, or a config file."
        )

    ffmpeg = find_ffmpeg(ffmpeg_location, environ=environ)

    return Settings(
        library=Path(resolved_library),
        old_dir=Path(resolved_old),
        ffmpeg=ffmpeg,
        config_path=file_path,
        season=season,
        cookies_from_browser=cookies_from_browser,
        dry_run=dry_run,
        ffmpeg_location=ffmpeg_location,
    )
