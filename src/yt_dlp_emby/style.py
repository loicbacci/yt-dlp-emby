"""TTY-aware ANSI styling. Off when piped, silent, dumb TERM, or NO_COLOR."""

from __future__ import annotations

import os
import re
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TRUTHY = {"1", "true", "yes", "on"}


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def visible_len(text: str) -> int:
    return len(strip_ansi(text))


def color_enabled(stream: object | None = None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    force = os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE") or ""
    if force.lower() in _TRUTHY:
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    stream = sys.stdout if stream is None else stream
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty()) if callable(isatty) else False
    except Exception:
        return False


def paint(
    text: str,
    *codes: str,
    enabled: bool | None = None,
    stream: object | None = None,
) -> str:
    if not text or not codes:
        return text
    if enabled is None:
        enabled = color_enabled(stream)
    if not enabled:
        return text
    return "".join(codes) + text + RESET


def bold(text: str, *, enabled: bool | None = None, stream: object | None = None) -> str:
    return paint(text, BOLD, enabled=enabled, stream=stream)


def dim(text: str, *, enabled: bool | None = None, stream: object | None = None) -> str:
    return paint(text, DIM, enabled=enabled, stream=stream)


def red(text: str, *, enabled: bool | None = None, stream: object | None = None) -> str:
    return paint(text, RED, enabled=enabled, stream=stream)


def green(text: str, *, enabled: bool | None = None, stream: object | None = None) -> str:
    return paint(text, GREEN, enabled=enabled, stream=stream)


def yellow(text: str, *, enabled: bool | None = None, stream: object | None = None) -> str:
    return paint(text, YELLOW, enabled=enabled, stream=stream)


def cyan(text: str, *, enabled: bool | None = None, stream: object | None = None) -> str:
    return paint(text, CYAN, enabled=enabled, stream=stream)


def pad_visible(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_len(text))
