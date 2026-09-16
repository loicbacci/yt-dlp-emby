"""Resolve library/old_dir from CLI flags, environment, then a config file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import tomllib

from yt_dlp_emby.cookies import cookies_file_usable
from yt_dlp_emby.ffmpeg import FFmpegNotFoundError, find_ffmpeg

__all__ = [
    "CONFIG_FIELDS",
    "ConfigError",
    "ConfigField",
    "FFmpegNotFoundError",
    "MissingPathError",
    "Settings",
    "config_target_path",
    "describe_manifest_paths",
    "env_value",
    "env_var_name",
    "format_yaml_error",
    "inspect_config",
    "load_config_values",
    "resolve_settings",
    "write_config",
]

FALLBACK_KEYS = ("library", "old_dir", "staging")
ROOT_KEYS = ("cookies", "bench_dest", "sonarr_url", "sonarr_api_key", "shows_dir")
PATH_ENV_SUFFIX = {
    "library": "LIBRARY",
    "old_dir": "OLD_DIR",
    "staging": "STAGING",
}
CONFIG_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("library", "LIBRARY", "fallback"),
    ("old_dir", "OLD_DIR", "fallback"),
    ("staging", "STAGING", "fallback"),
    ("bench_dest", "BENCH_DEST", "root"),
    ("sonarr_url", "SONARR_URL", "root"),
    ("sonarr_api_key", "SONARR_API_KEY", "root"),
    ("shows_dir", "SHOWS_DIR", "root"),
)


class ConfigError(Exception):
    """Invalid or incomplete configuration."""


def format_yaml_error(exc: BaseException) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc).strip()
    if mark is not None and hasattr(mark, "line"):
        column = getattr(mark, "column", None)
        where = f"line {mark.line + 1}"
        if isinstance(column, int):
            where += f", column {column + 1}"
        return f"Invalid YAML at {where}: {problem}"
    return f"Invalid YAML: {problem}"


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
    layout: bool = False
    ffmpeg_location: str | None = None
    quiet: bool = False
    silent: bool = False
    verbose: bool = False
    debug: bool = False
    staging: Path | None = None
    force_refetch: bool = False
    bench_dest: Path | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None

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


@dataclass(frozen=True)
class ConfigField:
    key: str
    file: str | None
    effective: str | None
    source: str
    env_name: str | None
    section: str


def _stringify(value: object) -> str | None:
    if value is None or isinstance(value, dict):
        return None
    text = str(value).strip()
    return text or None


def load_config_values(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    fallback = data.get("fallback")
    if isinstance(fallback, dict):
        for key in FALLBACK_KEYS:
            text = _stringify(fallback.get(key))
            if text:
                result[key] = text
    for key in FALLBACK_KEYS:
        if key in result:
            continue
        text = _stringify(data.get(key))
        if text:
            result[key] = text
    for key in ROOT_KEYS:
        text = _stringify(data.get(key))
        if text:
            result[key] = text
    return result


def config_target_path(
    config_path: str | None,
    environ: Mapping[str, str],
    cwd: Path,
) -> Path:
    if config_path:
        return Path(config_path)
    env_path = env_value(environ, "CONFIG")
    if env_path:
        return Path(env_path)
    return cwd / "config.toml"


def _config_file(
    config_path: str | None,
    environ: Mapping[str, str],
    cwd: Path,
    *,
    use_default_config: bool,
) -> Path | None:
    if config_path:
        return Path(config_path)
    env_path = env_value(environ, "CONFIG")
    if env_path:
        return Path(env_path)
    if not use_default_config:
        return None
    default = cwd / "config.toml"
    if default.is_file():
        return default
    return None


def env_value(environ: Mapping[str, str], name: str) -> str | None:
    """`YT_DLP_EMBY_<name>`, then the legacy `YT_EMBY_<name>`."""
    for prefix in ("YT_DLP_EMBY_", "YT_EMBY_"):
        value = environ.get(prefix + name)
        if value:
            return value
    return None


def env_var_name(environ: Mapping[str, str], name: str) -> str | None:
    for prefix in ("YT_DLP_EMBY_", "YT_EMBY_"):
        key = prefix + name
        if environ.get(key):
            return key
    return None


def _pick(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def inspect_config(
    *,
    config_path: str | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[Path, bool, dict[str, ConfigField]]:
    if environ is None:
        environ = os.environ
    cwd = cwd if cwd is not None else Path.cwd()
    path = config_target_path(config_path, environ, cwd)
    exists = path.is_file()
    file_values = load_config_values(path) if exists else {}
    fields: dict[str, ConfigField] = {}
    for key, suffix, section in CONFIG_FIELDS:
        file_value = file_values.get(key)
        env_name = env_var_name(environ, suffix)
        env = env_value(environ, suffix)
        if env:
            source = "env"
            effective = env
        elif file_value:
            source = "file"
            effective = file_value
        else:
            source = "unset"
            effective = None
        fields[key] = ConfigField(
            key=key,
            file=file_value,
            effective=effective,
            source=source,
            env_name=env_name,
            section=section,
        )
    return path, exists, fields


def inspect_config_payload(
    *,
    config_path: str | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    path, exists, fields = inspect_config(
        config_path=config_path, environ=environ, cwd=cwd
    )
    return {
        "path": str(path),
        "exists": exists,
        "fields": {
            key: {
                "file": item.file,
                "effective": item.effective,
                "source": item.source,
                "env_name": item.env_name,
                "section": item.section,
            }
            for key, item in fields.items()
        },
    }


def _toml_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _clean_config_value(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def render_config_toml(values: Mapping[str, str | None], *, cookies: str | None) -> str:
    lines: list[str] = []
    root_order = ("bench_dest", "shows_dir", "sonarr_url", "sonarr_api_key")
    for key in root_order:
        value = _clean_config_value(values.get(key))
        if value:
            lines.append(f"{key} = {_toml_literal(value)}")
    cookies_value = _clean_config_value(cookies)
    if cookies_value:
        lines.append(f"cookies = {_toml_literal(cookies_value)}")
    if lines:
        lines.append("")
    fallback_items = [
        (key, _clean_config_value(values.get(key))) for key in FALLBACK_KEYS
    ]
    fallback_items = [(key, value) for key, value in fallback_items if value]
    if fallback_items:
        lines.append(
            "# Path fallbacks: used when youtube.yaml / dropout.yaml omit the key."
        )
        lines.append(
            "# YT_DLP_EMBY_* environment variables override both the manifest and this table."
        )
        lines.append("[fallback]")
        for key, value in fallback_items:
            lines.append(f"{key} = {_toml_literal(value)}")
    if not lines:
        lines.append(
            "# Path fallbacks: used when youtube.yaml / dropout.yaml omit the key."
        )
        lines.append("[fallback]")
    return "\n".join(lines).rstrip() + "\n"


def write_config(
    path: Path,
    values: Mapping[str, str | None],
) -> None:
    cookies: str | None = None
    if path.is_file():
        cookies = load_config_values(path).get("cookies")
    text = render_config_toml(values, cookies=cookies)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def describe_manifest_paths(
    data: Mapping[str, Any] | None,
    *,
    environ: Mapping[str, str],
    cwd: Path,
    config_path: str | None = None,
) -> dict[str, dict[str, str | None]]:
    file_values: dict[str, str] = {}
    target = config_target_path(config_path, environ, cwd)
    if target.is_file():
        file_values = load_config_values(target)
    mapping = data if isinstance(data, Mapping) else {}
    out: dict[str, dict[str, str | None]] = {}
    for key, suffix in PATH_ENV_SUFFIX.items():
        raw = mapping.get(key) if key in mapping else None
        if raw is None or raw == "":
            manifest_val = None
        elif not isinstance(raw, str):
            manifest_val = None
        else:
            manifest_val = raw.strip() or None
        env = env_value(environ, suffix)
        file_value = file_values.get(key)
        if env:
            source = "env"
            effective = env
        elif manifest_val:
            source = "manifest"
            effective = manifest_val
        elif file_value:
            source = "fallback"
            effective = file_value
        else:
            source = "unset"
            effective = None
        out[key] = {
            "manifest": manifest_val,
            "effective": effective,
            "source": source,
            "env_name": env_var_name(environ, suffix),
        }
    return out


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
    layout: bool = False,
    quiet: bool = False,
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
    staging: str | None = None,
    force_refetch: bool = False,
    bench_dest: str | None = None,
    sonarr_url: str | None = None,
    sonarr_api_key: str | None = None,
    manifest_library: str | None = None,
    manifest_old_dir: str | None = None,
    manifest_staging: str | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    use_default_config: bool = True,
    use_file_cookies: bool = True,
    auto_cookies: bool = True,
    auto_cookie_name: str = "cookies.txt",
) -> Settings:
    if environ is None:
        environ = os.environ
    cwd = cwd if cwd is not None else Path.cwd()

    file_path = _config_file(config_path, environ, cwd, use_default_config=use_default_config)
    file_values: dict[str, str] = {}
    if file_path is not None:
        if not file_path.is_file():
            raise ConfigError(f"Config file not found: {file_path}")
        file_values = load_config_values(file_path)

    resolved_library = _pick(
        library,
        env_value(environ, "LIBRARY"),
        manifest_library,
        file_values.get("library"),
    )
    resolved_old = _pick(
        old_dir,
        env_value(environ, "OLD_DIR"),
        manifest_old_dir,
        file_values.get("old_dir"),
    )

    missing: list[str] = []
    if not resolved_library:
        missing.append(
            "library (--library, YT_DLP_EMBY_LIBRARY, manifest library, or config [fallback].library)"
        )
    if not resolved_old:
        missing.append(
            "old_dir (--old-dir, YT_DLP_EMBY_OLD_DIR, manifest old_dir, or config [fallback].old_dir)"
        )
    if missing:
        raise MissingPathError(
            "Missing required path(s): "
            + ", ".join(missing)
            + ". Pass them as flags, environment variables, a manifest, or a config file."
        )

    resolved_staging = _pick(
        staging,
        env_value(environ, "STAGING"),
        manifest_staging,
        file_values.get("staging"),
    )
    resolved_bench = _pick(
        bench_dest, env_value(environ, "BENCH_DEST"), file_values.get("bench_dest")
    )
    resolved_sonarr_url = _pick(
        sonarr_url, env_value(environ, "SONARR_URL"), file_values.get("sonarr_url")
    )
    resolved_sonarr_key = _pick(
        sonarr_api_key, env_value(environ, "SONARR_API_KEY"), file_values.get("sonarr_api_key")
    )
    file_cookies = file_values.get("cookies") if use_file_cookies else None
    resolved_cookies = _pick(cookiefile, env_value(environ, "COOKIES"), file_cookies)
    if auto_cookies and not resolved_cookies:
        name = Path(auto_cookie_name).name
        default_cookies = cwd / (name if name else "cookies.txt")
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
        env_verbose = env_value(environ, "VERBOSE") or ""
        verbose = env_verbose.lower() in {"1", "true", "yes", "on"}
    if quiet or silent:
        verbose = False
    if not debug:
        env_debug = env_value(environ, "DEBUG") or ""
        debug = env_debug.lower() in {"1", "true", "yes", "on"}
    if not force_refetch:
        env_refetch = env_value(environ, "FORCE_REFETCH") or ""
        force_refetch = env_refetch.lower() in {"1", "true", "yes", "on"}

    return Settings(
        library=Path(resolved_library),
        old_dir=Path(resolved_old),
        ffmpeg=ffmpeg,
        config_path=file_path,
        season=season,
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookie_path,
        dry_run=dry_run or layout,
        layout=layout,
        ffmpeg_location=ffmpeg_location,
        quiet=quiet,
        silent=silent,
        verbose=verbose,
        debug=debug,
        staging=Path(resolved_staging) if resolved_staging else None,
        force_refetch=force_refetch,
        bench_dest=Path(resolved_bench) if resolved_bench else None,
        sonarr_url=resolved_sonarr_url.rstrip("/") if resolved_sonarr_url else None,
        sonarr_api_key=resolved_sonarr_key,
    )
