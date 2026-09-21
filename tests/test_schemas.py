"""Validate shipped YAML examples against JSON Schema and keep copies in sync."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from jsonschema.validators import RefResolver

REPO = Path(__file__).resolve().parent.parent
SCHEMAS = REPO / "schemas"
ROOT_YOUTUBE = REPO / "youtube.yaml.example"
ROOT_DROPOUT = REPO / "dropout.yaml.example"
SERVER_EXAMPLES = REPO / "src" / "yt_dlp_emby" / "server" / "examples"
SHOWS_D20 = REPO / "shows" / "dimension-20.yaml.example"


def _resolver(schema: dict) -> RefResolver:
    base_uri = SCHEMAS.resolve().as_uri()
    if not base_uri.endswith("/"):
        base_uri += "/"
    return RefResolver(base_uri=base_uri, referrer=schema)


def _validator(schema_name: str) -> Draft7Validator:
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    return Draft7Validator(schema, resolver=_resolver(schema))


def _load_yaml(path: Path) -> object:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _without_schema_header(text: str) -> str:
    """Drop the yaml-language-server schema comment (relative path differs)."""
    lines = text.splitlines()
    if lines and lines[0].startswith("# yaml-language-server:"):
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


@pytest.mark.parametrize(
    ("example", "schema_name"),
    [
        (ROOT_YOUTUBE, "youtube.schema.json"),
        (ROOT_DROPOUT, "dropout.schema.json"),
        (SERVER_EXAMPLES / "youtube.yaml.example", "youtube.schema.json"),
        (SERVER_EXAMPLES / "dropout.yaml.example", "dropout.schema.json"),
        (SHOWS_D20, "dropout-series.schema.json"),
    ],
)
def test_shipped_examples_match_schema(example: Path, schema_name: str) -> None:
    assert example.is_file(), f"missing example {example}"
    _validator(schema_name).validate(_load_yaml(example))


@pytest.mark.parametrize("name", ["youtube.yaml.example", "dropout.yaml.example"])
def test_root_examples_match_server_examples_modulo_header(name: str) -> None:
    root = (REPO / name).read_text(encoding="utf-8")
    server = (SERVER_EXAMPLES / name).read_text(encoding="utf-8")
    assert _without_schema_header(root) == _without_schema_header(server)


def test_empty_youtube_series_rejected() -> None:
    with pytest.raises(ValidationError, match="minItems|\\[\\]|too short"):
        _validator("youtube.schema.json").validate({"series": []})


def test_empty_dropout_series_rejected() -> None:
    with pytest.raises(ValidationError, match="minItems|\\[\\]|too short"):
        _validator("dropout.schema.json").validate({"series": []})


def test_remap_without_to_fields_rejected() -> None:
    payload = {
        "series": [
            {
                "name": "Show",
                "path": "Show",
                "url": "https://watch.dropout.tv/show",
                "seasons": [
                    {
                        "dropout": 1,
                        "remap": [{"dropout_episode": 1}],
                    }
                ],
            }
        ]
    }
    with pytest.raises(ValidationError):
        _validator("dropout.schema.json").validate(payload)


def test_skip_remap_without_to_fields_accepted() -> None:
    payload = {
        "series": [
            {
                "name": "Show",
                "path": "Show",
                "url": "https://watch.dropout.tv/show",
                "seasons": [
                    {
                        "dropout": 1,
                        "remap": [{"dropout_episode": 1, "skip": True}],
                    }
                ],
            }
        ]
    }
    _validator("dropout.schema.json").validate(payload)


def test_negative_youtube_season_rejected() -> None:
    payload = {
        "series": [
            {
                "name": "Channel",
                "playlists": [
                    {
                        "url": "https://www.youtube.com/playlist?list=PLx",
                        "season": -1,
                    }
                ],
            }
        ]
    }
    with pytest.raises(ValidationError):
        _validator("youtube.schema.json").validate(payload)


def test_negative_dropout_season_rejected() -> None:
    payload = {
        "series": [
            {
                "name": "Show",
                "path": "Show",
                "url": "https://watch.dropout.tv/show",
                "seasons": [{"dropout": -1}],
            }
        ]
    }
    with pytest.raises(ValidationError):
        _validator("dropout.schema.json").validate(payload)


def test_negative_to_season_rejected() -> None:
    payload = {
        "series": [
            {
                "name": "Show",
                "path": "Show",
                "url": "https://watch.dropout.tv/show",
                "seasons": [{"dropout": 1, "to_season": -1}],
            }
        ]
    }
    with pytest.raises(ValidationError):
        _validator("dropout.schema.json").validate(payload)
