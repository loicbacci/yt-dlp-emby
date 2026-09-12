"""Confined read/write for youtube.yaml and dropout.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.dropout_manifest import load_dropout_manifest
from yt_dlp_emby.youtube_manifest import load_youtube_manifest

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


def write_manifest(data_dir: Path, kind: str, text: str) -> ManifestPayload:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("manifest too large")
    path = _manifest_path(data_dir, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    try:
        if kind == "youtube":
            load_youtube_manifest(path)
        else:
            load_dropout_manifest(path)
    except ConfigError as exc:
        raise ConfigError(str(exc)) from exc
    return ManifestPayload(kind=kind, text=text, exists=True)
