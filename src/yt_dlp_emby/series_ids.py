"""Stable ids for series files (slug from display name)."""

from __future__ import annotations

import re
from collections.abc import Sequence

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    text = _SLUG_RE.sub("-", name.casefold()).strip("-")
    return text


def unique_slug(name: str, existing: set[str]) -> str:
    base = slugify(name) or "series"
    if base not in existing:
        return base
    n = 2
    candidate = f"{base}-{n}"
    while candidate in existing:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def suggest_folder(name: str, tvdb_id: int | None) -> str:
    if tvdb_id is not None and tvdb_id >= 1:
        return f"{name} [tvdbid={tvdb_id}]"
    return name


def canonical_key(name: str, path: str | None) -> str:
    """Emby folder override when present, else display name."""
    return path if path else name


def assign_manifest_slugs(names: Sequence[str]) -> list[str]:
    """Deterministic in-memory unique slugs for manifest series order.

    Recomputed on each load (no migration). Single unique names keep
    slugify(name); duplicates get -2, -3 suffixes via unique_slug.
    """
    used: set[str] = set()
    out: list[str] = []
    for name in names:
        slug = unique_slug(name, used)
        used.add(slug)
        out.append(slug)
    return out
