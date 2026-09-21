"""Load Netscape cookies without letting yt-dlp truncate the original file."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping


def cookie_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def cookies_text_usable(text: str) -> bool:
    return bool(cookie_lines(text))


def cookies_file_usable(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(cookie_lines(text))


@contextmanager
def sandbox_cookiefile(path: str | Path | None) -> Iterator[str | None]:
    """Give yt-dlp a temp copy so it cannot empty or rewrite the user's cookies file.

    Never copy the jar back. After a failed or logged-out request yt-dlp often
    saves a still-non-empty file that no longer has the Dropout `_session` cookie.
    """
    if not path:
        yield None
        return
    source = Path(path)
    try:
        original = source.read_bytes()
    except OSError as exc:
        from yt_dlp_emby.log import warn

        warn(f"could not read cookies file {source}: {exc}")
        raise
    fd, tmp = tempfile.mkstemp(prefix=f"yt-dlp-emby-cookies-{os.getpid()}-", suffix=".txt")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_bytes(original)
        yield str(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


DEFAULT_COOKIE_FILES = {
    "youtube": "cookies.txt",
    "dropout": "dropout-cookies.txt",
}
MAX_COOKIE_BYTES = 1_048_576


def cookie_jar_path(data_dir: Path, kind: str) -> Path:
    name = DEFAULT_COOKIE_FILES.get(kind)
    if name is None:
        raise ValueError(f"unknown cookie kind: {kind}")
    return data_dir / name


def confined_cookie_path(data_dir: Path, filename: str | None) -> Path | None:
    """Return a data_dir-relative cookie path, or None if filename is unusable."""
    if not filename or not str(filename).strip():
        return None
    raw = str(filename).strip()
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (data_dir / raw).resolve()
    if not resolved.is_relative_to(data_dir.resolve()):
        return None
    return resolved


def inspect_cookie_jars(data_dir: Path, environ: Mapping[str, str]) -> dict[str, object]:
    from yt_dlp_emby.config import env_value, env_var_name

    env_cookies = env_value(environ, "COOKIES")
    jars: dict[str, dict[str, object]] = {}
    for kind, filename in DEFAULT_COOKIE_FILES.items():
        path = cookie_jar_path(data_dir, kind)
        exists = path.is_file()
        jars[kind] = {
            "filename": filename,
            "path": str(path),
            "exists": exists,
            "usable": cookies_file_usable(path) if exists else False,
        }
    return {
        "env_name": env_var_name(environ, "COOKIES"),
        "env_set": bool(env_cookies),
        "env_path": env_cookies,
        "jars": jars,
    }


def write_cookie_jar(data_dir: Path, kind: str, text: str, *, filename: str | None = None) -> Path:
    path = confined_cookie_path(data_dir, filename) or cookie_jar_path(data_dir, kind)
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_COOKIE_BYTES:
        raise ValueError("cookies file too large")
    if not cookies_text_usable(text):
        raise ValueError("cookies file is empty")
    data_dir.mkdir(parents=True, exist_ok=True)
    body = text if text.endswith("\n") else text + "\n"
    from yt_dlp_emby.cache import atomic_write_private

    atomic_write_private(path, body, mode=0o600)
    return path
