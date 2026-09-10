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
    except OSError:
        yield None
        return
    fd, tmp = tempfile.mkstemp(prefix="yt-dlp-emby-cookies-", suffix=".txt")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_bytes(original)
        yield str(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
