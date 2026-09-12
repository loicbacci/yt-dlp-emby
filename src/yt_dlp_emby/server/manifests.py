"""Confined read/write for youtube.yaml and dropout.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from yt_dlp_emby.config import ConfigError, format_yaml_error
from yt_dlp_emby.dropout_manifest import parse_dropout_manifest
from yt_dlp_emby.youtube_manifest import parse_youtube_manifest

ALLOWED: dict[str, str] = {
    "youtube": "youtube.yaml",
    "dropout": "dropout.yaml",
}
MAX_BYTES = 1_048_576
EXAMPLES_DIR = Path(__file__).parent / "examples"


@dataclass(frozen=True)
class ManifestPayload:
    kind: str
    text: str
    exists: bool


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


def read_manifest(data_dir: Path, kind: str) -> ManifestPayload:
    path = _manifest_path(data_dir, kind)
    if not path.is_file():
        return ManifestPayload(kind=kind, text=_example_text(kind), exists=False)
    text = path.read_text(encoding="utf-8")
    return ManifestPayload(kind=kind, text=text, exists=True)


def _parse_text(kind: str, text: str, data_dir: Path) -> None:
    path = _manifest_path(data_dir, kind)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("manifest too large")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc
    if kind == "youtube":
        parse_youtube_manifest(data, path)
    else:
        parse_dropout_manifest(data, path)


def validate_manifest_text(data_dir: Path, kind: str, text: str) -> None:
    _parse_text(kind, text, data_dir)


def write_manifest(data_dir: Path, kind: str, text: str) -> ManifestPayload:
    _parse_text(kind, text, data_dir)
    path = _manifest_path(data_dir, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return ManifestPayload(kind=kind, text=text, exists=True)
