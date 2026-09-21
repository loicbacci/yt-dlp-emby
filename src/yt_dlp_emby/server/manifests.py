"""Confined read/write for youtube.yaml and dropout.yaml."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from yt_dlp_emby.cache import atomic_write_private, file_lock
from yt_dlp_emby.config import ConfigError, describe_manifest_paths, format_yaml_error
from yt_dlp_emby.dropout_manifest import parse_dropout_manifest, parse_dropout_series_file
from yt_dlp_emby.youtube_manifest import parse_youtube_manifest, parse_youtube_series_file

ALLOWED: dict[str, str] = {
    "youtube": "youtube.yaml",
    "dropout": "dropout.yaml",
}
MAX_BYTES = 1_048_576
EXAMPLES_DIR = Path(__file__).parent / "examples"


@dataclass(frozen=True)
class ImportPayload:
    path: str
    text: str
    exists: bool


@dataclass(frozen=True)
class ManifestPayload:
    kind: str
    text: str
    exists: bool
    imports: tuple[ImportPayload, ...] = field(default_factory=tuple)


def paths_from_text(
    text: str, data_dir: Path, environ: Mapping[str, str]
) -> dict[str, dict[str, str | None]] | None:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return describe_manifest_paths(data, environ=environ, cwd=data_dir)


def _manifest_path(data_dir: Path, kind: str) -> Path:
    if kind not in ALLOWED:
        raise ValueError(f"unknown manifest kind: {kind}")
    resolved_data = data_dir.resolve()
    path = (resolved_data / ALLOWED[kind]).resolve()
    if not path.is_relative_to(resolved_data):
        raise ValueError("manifest path escapes data directory")
    return path


def _example_text(kind: str) -> str:
    example = EXAMPLES_DIR / f"{kind}.yaml.example"
    return example.read_text(encoding="utf-8")


def _import_paths_from_text(text: str) -> list[str]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("imports")
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _confined_import_path(data_dir: Path, listed: str) -> Path | None:
    resolved_data = data_dir.resolve()
    candidate = Path(listed)
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (resolved_data / listed).resolve()
    )
    if not resolved.is_relative_to(resolved_data):
        return None
    return resolved


def listed_on_disk_imports(data_dir: Path, kind: str = "dropout") -> list[str]:
    root = _manifest_path(data_dir, kind)
    if not root.is_file():
        return []
    return _import_paths_from_text(root.read_text(encoding="utf-8"))


def imports_payload(data_dir: Path, root_text: str) -> tuple[ImportPayload, ...]:
    items: list[ImportPayload] = []
    resolved_data = data_dir.resolve()
    for listed in _import_paths_from_text(root_text):
        confined = _confined_import_path(data_dir, listed)
        if confined is None:
            continue
        exists = confined.is_file()
        text = confined.read_text(encoding="utf-8") if exists else ""
        if Path(listed).is_absolute():
            path = str(confined.relative_to(resolved_data))
        else:
            path = listed
        items.append(ImportPayload(path=path, text=text, exists=exists))
    return tuple(items)


def read_manifest(data_dir: Path, kind: str) -> ManifestPayload:
    path = _manifest_path(data_dir, kind)
    if not path.is_file():
        text = _example_text(kind)
        imports = imports_payload(data_dir, text)
        return ManifestPayload(kind=kind, text=text, exists=False, imports=imports)
    text = path.read_text(encoding="utf-8")
    imports = imports_payload(data_dir, text)
    return ManifestPayload(kind=kind, text=text, exists=True, imports=imports)


def _parse_text(kind: str, text: str, data_dir: Path) -> None:
    path = _manifest_path(data_dir, kind)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("manifest too large")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc
    if kind == "youtube":
        parse_youtube_manifest(data, path, load_imports=False)
    else:
        parse_dropout_manifest(data, path, load_imports=False)


def validate_manifest_text(data_dir: Path, kind: str, text: str) -> None:
    _parse_text(kind, text, data_dir)


def atomic_write_manifest_text(path: Path, text: str, *, mode: int = 0o644) -> None:
    """Unique-tmp + fsync + single `.bak` + replace for manifest YAML (0644)."""
    if path.is_file():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    atomic_write_private(path, text, mode=mode)


def write_manifest(data_dir: Path, kind: str, text: str) -> ManifestPayload:
    _parse_text(kind, text, data_dir)
    path = _manifest_path(data_dir, kind)
    with file_lock(path):
        atomic_write_manifest_text(path, text)
    imports = imports_payload(data_dir, text)
    return ManifestPayload(kind=kind, text=text, exists=True, imports=imports)


def write_import(data_dir: Path, kind: str, listed_path: str, text: str) -> ImportPayload:
    if kind not in ALLOWED:
        raise ValueError("unknown manifest kind")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("manifest too large")
    if listed_path not in listed_on_disk_imports(data_dir, kind):
        raise ValueError(f"import path is not listed in {ALLOWED[kind]}")
    confined = _confined_import_path(data_dir, listed_path)
    if confined is None:
        raise ValueError("import path escapes data directory")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc
    if kind == "youtube":
        parse_youtube_series_file(data, confined)
    else:
        parse_dropout_series_file(data, confined)
    with file_lock(confined):
        atomic_write_manifest_text(confined, text)
    return ImportPayload(path=listed_path, text=text, exists=True)


def write_dropout_import(data_dir: Path, listed_path: str, text: str) -> ImportPayload:
    return write_import(data_dir, "dropout", listed_path, text)
