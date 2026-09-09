"""Resolve library/old_dir from CLI flags, environment, then a config file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import tomllib

from yt_emby.cookies import cookies_file_usable
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
    cookiefile: Path | None = None
    dry_run: bool = False
    ffmpeg_location: str | None = None
    quiet: bool = False
    silent: bool = False
    verbose: bool = False
    debug: bool = False
    staging: Path | None = None
    force_refetch: bool = False

    @property
    def show_progress(self) -> bool:
        return not self.quiet and not self.silent and not self.verbose

    @property
    def show_steps(self) -> bool:
        return not self.quiet and not self.silent

    @property
    def show_summary(self) -> bool:
        return not self.silent

    @property
    def show_warnings(self) -> bool:
        return not self.silent


def _load_toml(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for key in ("library", "old_dir", "staging", "cookies"):
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
    cookiefile: str | None = None,
    dry_run: bool = False,
    quiet: bool = False,
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
    staging: str | None = None,
    force_refetch: bool = False,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    use_default_config: bool = True,
    auto_cookies: bool = True,
) -> Settings:
    if environ is None:
        environ = os.environ
    cwd = cwd if cwd is not None else Path.cwd()

    file_path = _config_file(config_path, environ, cwd) if use_default_config else (
        Path(config_path) if config_path else None
    )
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

    resolved_staging = _pick(staging, environ.get("YT_EMBY_STAGING"), file_values.get("staging"))
    resolved_cookies = _pick(cookiefile, environ.get("YT_EMBY_COOKIES"), file_values.get("cookies"))
    if auto_cookies and not resolved_cookies:
        default_cookies = cwd / "cookies.txt"
        if default_cookies.is_file():
            resolved_cookies = str(default_cookies)
    cookie_path: Path | None = None
    if resolved_cookies:
        cookie_path = Path(resolved_cookies)
        if not cookie_path.is_file():
            raise ConfigError(f"Cookies file not found: {cookie_path}")
        if not cookies_file_usable(cookie_path):
            raise ConfigError(f"Cookies file is empty: {cookie_path}")

    ffmpeg = find_ffmpeg(ffmpeg_location, environ=environ)

    if not verbose:
        env_verbose = environ.get("YT_EMBY_VERBOSE", "")
        verbose = env_verbose.lower() in {"1", "true", "yes", "on"}
    if quiet or silent:
        verbose = False
    if not debug:
        env_debug = environ.get("YT_EMBY_DEBUG", "")
        debug = env_debug.lower() in {"1", "true", "yes", "on"}
    if not force_refetch:
        env_refetch = environ.get("YT_EMBY_FORCE_REFETCH", "")
        force_refetch = env_refetch.lower() in {"1", "true", "yes", "on"}

    return Settings(
        library=Path(resolved_library),
        old_dir=Path(resolved_old),
        ffmpeg=ffmpeg,
        config_path=file_path,
        season=season,
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookie_path,
        dry_run=dry_run,
        ffmpeg_location=ffmpeg_location,
        quiet=quiet,
        silent=silent,
        verbose=verbose,
        debug=debug,
        staging=Path(resolved_staging) if resolved_staging else None,
        force_refetch=force_refetch,
    )
