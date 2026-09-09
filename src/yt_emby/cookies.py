"""Load Netscape cookies without letting yt-dlp truncate the original file."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def cookie_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def cookies_file_usable(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(cookie_lines(text))


@contextmanager
def sandbox_cookiefile(path: str | Path | None) -> Iterator[str | None]:
    """Give yt-dlp a temp copy so it cannot empty the user's cookies file.

    If yt-dlp writes a still-usable jar (session refresh), copy that back.
    """
    if not path:
        yield None
        return
    source = Path(path)
    try:
        original = source.read_bytes()
    except OSError:
        yield str(source)
        return
    fd, tmp = tempfile.mkstemp(prefix="yt-emby-cookies-", suffix=".txt")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_bytes(original)
        yield str(tmp_path)
        try:
            updated = tmp_path.read_bytes()
        except OSError:
            return
        if cookie_lines(updated.decode("utf-8", "replace")) and updated != original:
            source.write_bytes(updated)
    finally:
        tmp_path.unlink(missing_ok=True)
