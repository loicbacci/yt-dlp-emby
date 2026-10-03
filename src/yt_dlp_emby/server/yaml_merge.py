"""Update round-trip YAML nodes while retaining comments on surviving entries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ruamel.yaml.scalarstring import ScalarString


def _identity(value: Any) -> tuple[str, Any] | None:
    if isinstance(value, Mapping):
        for key in ("dropout", "dropout_episode", "name", "url"):
            if value.get(key) is not None:
                return key, value[key]
    return None


def merge_round_trip(existing: Any, replacement: Any) -> Any:
    """Retain YAML annotations; removed keys and list entries stay removed.

    Match identifiable list entries before falling back to their position, so
    discovery additions/reordering retain annotations on configured seasons.
    """
    if isinstance(existing, dict) and isinstance(replacement, Mapping):
        for key in list(existing):
            if key not in replacement:
                del existing[key]
        for key, value in replacement.items():
            existing[key] = merge_round_trip(existing.get(key), value)
        return existing
    if isinstance(existing, list) and isinstance(replacement, (list, tuple)):
        originals = list(existing)
        used: set[int] = set()
        merged = []
        for index, value in enumerate(replacement):
            identity = _identity(value)
            match = next(
                (
                    i
                    for i, old in enumerate(originals)
                    if i not in used and identity is not None and _identity(old) == identity
                ),
                None,
            )
            if match is None and identity is None and index < len(originals) and index not in used:
                match = index
            if match is not None:
                used.add(match)
            old = originals[match] if match is not None else None
            merged.append(merge_round_trip(old, value))
        existing[:] = merged
        return existing
    if isinstance(existing, ScalarString) and isinstance(replacement, str):
        return type(existing)(replacement)
    return replacement
