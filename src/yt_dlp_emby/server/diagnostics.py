"""Read-only, bounded diagnostics for the private web worker."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from yt_dlp_emby.config import config_target_path, env_value, inspect_config, load_config_values
from yt_dlp_emby.cookies import confined_cookie_path, cookie_jar_path, cookies_file_usable
from yt_dlp_emby.extract import find_node
from yt_dlp_emby.ffmpeg import FFmpegNotFoundError, find_ffmpeg
from yt_dlp_emby.server.manifests import paths_from_text
from yt_dlp_emby.sonarr import assert_sonarr_url_allowed

ALLOWED_CHECKS = frozenset({"paths", "cookies", "ffmpeg", "node", "sonarr", "worker", "database"})
MIN_FREE_BYTES = 200 * 1024 * 1024

Emit = Callable[[dict[str, Any]], None]


def _result(name: str, ok: bool, status: str, message: str, **metadata: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, "status": status, "message": message, **metadata}


def _absolute(value: str, base: Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else base / candidate


def _configured_path_targets(
    data_dir: Path, environ: Mapping[str, str], key: str
) -> list[tuple[str, Path]]:
    config_path, _exists, fields = inspect_config(environ=environ, cwd=data_dir)
    env = env_value(environ, key.upper())
    if env:
        return [("environment", _absolute(env, data_dir))]

    manifest_targets: list[tuple[str, Path]] = []
    for kind in ("youtube", "dropout"):
        manifest_path = data_dir / f"{kind}.yaml"
        try:
            text = manifest_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError:
            continue
        paths = paths_from_text(text, data_dir, environ) or {}
        field = paths.get(key) or {}
        value = field.get("effective")
        if value and field.get("source") == "manifest":
            resolved = _absolute(str(value), manifest_path.parent)
            if all(path != resolved for _, path in manifest_targets):
                manifest_targets.append((kind, resolved))
    if manifest_targets:
        return manifest_targets

    config_field = fields.get(key)
    if config_field and config_field.effective:
        base = config_path.parent
        return [("config", _absolute(config_field.effective, base))]
    return []


def _check_path(path: Path, label: str, *, writable: bool) -> dict[str, Any]:
    if not path.exists():
        return _result(label, False, "missing", f"{label} path does not exist", path=str(path))
    if not path.is_dir():
        return _result(label, False, "invalid", f"{label} path is not a directory", path=str(path))
    readable = os.access(path, os.R_OK | os.X_OK)
    can_write = os.access(path, os.W_OK | os.X_OK)
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        free = None
    ok = readable and (can_write if writable else True) and (free is None or free >= MIN_FREE_BYTES)
    if not readable:
        message = f"{label} path is not readable"
    elif writable and not can_write:
        message = f"{label} path is not writable"
    elif free is not None and free < MIN_FREE_BYTES:
        message = f"{label} has less than 200 MiB free"
    elif free is None:
        message = f"{label} is accessible; free space could not be checked"
    else:
        message = f"{label} is accessible"
    return _result(
        label,
        ok,
        "ok" if ok else "unavailable",
        message,
        path=str(path),
        free_bytes=free,
        readable=readable,
        writable=can_write,
    )


def _paths_check(data_dir: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    for key, writable in (("library", True), ("staging", True)):
        targets = _configured_path_targets(data_dir, environ, key)
        if not targets:
            if key == "library":
                outcomes.append(
                    _result("library", False, "missing", "Library path is not configured")
                )
            else:
                outcomes.append(
                    _result("staging", True, "skipped", "Staging path is not configured")
                )
            continue
        for owner, path in targets:
            outcome = _check_path(path, key, writable=writable)
            outcome["source"] = owner
            outcomes.append(outcome)
    failed = [row for row in outcomes if not row["ok"]]
    return _result(
        "paths",
        not failed,
        "ok" if not failed else "unavailable",
        "Configured library and staging paths checked"
        if not failed
        else "; ".join(row["message"] for row in failed),
        paths=outcomes,
    )


def _cookie_targets(data_dir: Path, environ: Mapping[str, str]) -> list[tuple[str, Path]]:
    configured: list[tuple[str, Path]] = []
    env_cookie = env_value(environ, "COOKIES")
    if env_cookie:
        configured.append(("environment", _absolute(env_cookie, data_dir)))

    config_path = config_target_path(None, environ, data_dir)
    try:
        values = load_config_values(config_path) if config_path.is_file() else {}
    except Exception:
        values = {}
    if values.get("cookies"):
        configured.append(("config", _absolute(values["cookies"], config_path.parent)))

    for kind in ("youtube", "dropout"):
        manifest_path = data_dir / f"{kind}.yaml"
        try:
            data = json.loads("null")  # Keep parsing below local and side-effect free.
            del data
            import yaml

            parsed = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            parsed = None
        except Exception:
            parsed = None
        filename = parsed.get("cookies") if isinstance(parsed, dict) else None
        if isinstance(filename, str) and filename.strip():
            confined = confined_cookie_path(data_dir, filename)
            if confined is not None:
                configured.append((kind, confined))

    if not configured:
        for kind in ("youtube", "dropout"):
            path = cookie_jar_path(data_dir, kind)
            if path.exists():
                configured.append((kind, path))
    unique: list[tuple[str, Path]] = []
    for owner, path in configured:
        if all(existing != path for _name, existing in unique):
            unique.append((owner, path))
    return unique


def _cookies_check(data_dir: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    targets = _cookie_targets(data_dir, environ)
    if not targets:
        return _result("cookies", False, "missing", "No usable cookie file is configured")
    outcomes: list[dict[str, Any]] = []
    for owner, path in targets:
        exists = path.is_file()
        usable = exists and cookies_file_usable(path)
        outcomes.append(
            _result(
                owner,
                usable,
                "ok" if usable else "unavailable",
                "Cookie file is readable" if usable else "Cookie file is missing or empty",
                filename=path.name,
                exists=exists,
                usable=usable,
            )
        )
    failed = [row for row in outcomes if not row["ok"]]
    return _result(
        "cookies",
        not failed,
        "ok" if not failed else "unavailable",
        "Configured cookie files checked"
        if not failed
        else "; ".join(row["message"] for row in failed),
        cookies=outcomes,
    )


def _version_check(name: str, command: Sequence[str] | None) -> dict[str, Any]:
    if command is None:
        return _result(name, False, "missing", f"{name} was not found")
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _result(name, False, "unavailable", f"{name} could not be executed")
    output = (completed.stdout or completed.stderr or "").splitlines()
    version = output[0][:200] if output else None
    ok = completed.returncode == 0
    return _result(
        name,
        ok,
        "ok" if ok else "unavailable",
        f"{name} is available" if ok else f"{name} version check failed",
        version=version,
    )


def _ffmpeg_check(environ: Mapping[str, str]) -> dict[str, Any]:
    try:
        binary = find_ffmpeg(None, environ)
    except FFmpegNotFoundError:
        return _result("ffmpeg", False, "missing", "ffmpeg was not found")
    result = _version_check("ffmpeg", [str(binary), "-version"])
    result["path"] = str(binary)
    return result


def _node_check() -> dict[str, Any]:
    node = find_node()
    return _version_check("node", [node, "--version"] if node else None)


def _sonarr_credentials(data_dir: Path, environ: Mapping[str, str]) -> tuple[str, str]:
    config_path = config_target_path(None, environ, data_dir)
    try:
        config = load_config_values(config_path) if config_path.is_file() else {}
    except Exception:
        config = {}
    return (
        (env_value(environ, "SONARR_URL") or config.get("sonarr_url") or "").strip(),
        (env_value(environ, "SONARR_API_KEY") or config.get("sonarr_api_key") or "").strip(),
    )


def _sonarr_check(data_dir: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    base_url, api_key = _sonarr_credentials(data_dir, environ)
    if not base_url or not api_key:
        return _result("sonarr", False, "missing", "Sonarr URL or API key is not configured")
    try:
        assert_sonarr_url_allowed(base_url, environ=environ)
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
    except Exception:
        return _result("sonarr", False, "invalid", "Sonarr URL is invalid or disallowed")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v3/system/status",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read(1_048_576).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        version = str(payload.get("version") or "").strip() or None
    except urllib.error.HTTPError as exc:
        status = "unauthorized" if exc.code in {401, 403} else "unavailable"
        message = (
            "Sonarr rejected the API key" if status == "unauthorized" else "Sonarr request failed"
        )
        return _result("sonarr", False, status, message)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return _result(
            "sonarr", False, "unavailable", "Sonarr could not be reached or returned invalid data"
        )
    return _result(
        "sonarr",
        True,
        "ok",
        "Sonarr is reachable",
        version=version,
        host=parsed.hostname,
    )


def _worker_check() -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec("yt_dlp_emby.server.worker")
    except (ImportError, ModuleNotFoundError, ValueError):
        spec = None
    ok = spec is not None and spec.origin is not None
    return _result(
        "worker",
        ok,
        "ok" if ok else "missing",
        "Private worker module is available" if ok else "Private worker module is unavailable",
    )


def _database_check(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "jobs.sqlite3"
    if not path.is_file():
        return _result("database", False, "missing", "Jobs database does not exist")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return _result("database", False, "corrupt", "Jobs database integrity check failed")
    status = str(row[0]) if row else "no result"
    ok = status == "ok"
    return _result(
        "database",
        ok,
        "ok" if ok else "corrupt",
        "Jobs database is healthy" if ok else "Jobs database integrity check failed",
    )


def diagnostics(
    data_dir: Path,
    environ: Mapping[str, str],
    checks: Sequence[str],
    emit: Emit | None = None,
) -> dict[str, Any]:
    """Run requested diagnostics only; never create paths or reveal credentials."""
    requested = list(checks)
    outputs: list[dict[str, Any]] = []
    for index, name in enumerate(requested, start=1):
        if emit is not None:
            emit(
                {
                    "event": "progress",
                    "stage": "diagnostics",
                    "target": name,
                    "completed": index - 1,
                    "total": len(requested),
                }
            )
        if name not in ALLOWED_CHECKS:
            output = _result(name, False, "invalid", "Unknown diagnostic check")
        elif name == "paths":
            output = _paths_check(data_dir, environ)
        elif name == "cookies":
            output = _cookies_check(data_dir, environ)
        elif name == "ffmpeg":
            output = _ffmpeg_check(environ)
        elif name == "node":
            output = _node_check()
        elif name == "sonarr":
            output = _sonarr_check(data_dir, environ)
        elif name == "worker":
            output = _worker_check()
        else:
            output = _database_check(data_dir)
        outputs.append(output)
        if emit is not None:
            emit(
                {
                    "event": "progress",
                    "stage": "diagnostics",
                    "target": name,
                    "completed": index,
                    "total": len(requested),
                    "item": output,
                }
            )
    return {"ok": all(row["ok"] for row in outputs), "checks": outputs}
