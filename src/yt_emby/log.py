"""Simple stdout/stderr logging with flush so progress is visible immediately."""

from __future__ import annotations

import sys


def info(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr, flush=True)
