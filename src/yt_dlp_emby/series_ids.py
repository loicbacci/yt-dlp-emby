"""Stable ids for series files (slug from display name)."""

from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    text = _SLUG_RE.sub("-", name.casefold()).strip("-")
    return text


def suggest_folder(name: str, tvdb_id: int | None) -> str:
    if tvdb_id is not None and tvdb_id >= 1:
        return f"{name} [tvdbid={tvdb_id}]"
    return name
