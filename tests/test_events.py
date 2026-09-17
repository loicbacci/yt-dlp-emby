import json
import os
from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.events import (
    allowed_item_id,
    emit,
    item_id,
    merge_plan_source,
    plan_from_events,
    read_events_path,
    reset_runtime,
)


def test_emit_noop_without_env(monkeypatch) -> None:
    reset_runtime()
    monkeypatch.delenv("YT_DLP_EMBY_EVENTS", raising=False)
    path = Path("/tmp/should-not-exist-events.jsonl")
    emit({"event": "test"})
    assert not path.exists()


def test_emit_writes_jsonl(tmp_path: Path, monkeypatch) -> None:
    reset_runtime()
    target = tmp_path / "ev.jsonl"
    monkeypatch.setenv("YT_DLP_EMBY_EVENTS", str(target))
    read_events_path(os.environ)
    emit({"event": "run_started", "source": "dropout"})
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["event"] == "run_started"


def test_only_empty_ids_raises(tmp_path: Path, monkeypatch) -> None:
    reset_runtime()
    only = tmp_path / "only.json"
    only.write_text(json.dumps({"ids": []}), encoding="utf-8")
    monkeypatch.setenv("YT_DLP_EMBY_ONLY", str(only))
    with pytest.raises(ConfigError, match="empty"):
        read_events_path(os.environ)


def test_allowed_item_id_subset(tmp_path: Path, monkeypatch) -> None:
    reset_runtime()
    only = tmp_path / "only.json"
    only.write_text(
        json.dumps({"ids": ["dropout|dimension-20|S21E01"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("YT_DLP_EMBY_ONLY", str(only))
    read_events_path(os.environ)
    assert allowed_item_id("dropout|dimension-20|S21E01")
    assert not allowed_item_id("dropout|dimension-20|S21E02")


def test_item_id_format() -> None:
    assert item_id("dropout", "dimension-20", "S21E04") == "dropout|dimension-20|S21E04"


def test_progress_throttle(tmp_path: Path, monkeypatch) -> None:
    reset_runtime()
    target = tmp_path / "ev.jsonl"
    monkeypatch.setenv("YT_DLP_EMBY_EVENTS", str(target))
    read_events_path(os.environ)
    from yt_dlp_emby.events import emit_progress, set_current_item_id

    set_current_item_id("dropout|x|S01E01")
    for _ in range(10):
        emit_progress({"event": "progress", "id": "dropout|x|S01E01", "phase": "video"})
    lines = [line for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) <= 4


def test_merge_plan_force_sticky(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    merge_plan_source(
        plan_path,
        "dropout",
        {"ok": True, "error": None, "seasons": [], "items": []},
        force=True,
    )
    merge_plan_source(
        plan_path,
        "youtube",
        {"ok": True, "error": None, "seasons": [], "items": []},
        force=False,
    )
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["force"] is True


def test_merge_plan_source(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    merge_plan_source(
        plan_path,
        "dropout",
        {"ok": True, "error": None, "seasons": [], "items": []},
        force=False,
    )
    merge_plan_source(
        plan_path,
        "youtube",
        {"ok": True, "error": None, "seasons": [{"dest_season": 2}], "items": []},
        force=False,
    )
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert "dropout" in data["sources"]
    assert data["sources"]["youtube"]["seasons"][0]["dest_season"] == 2


def test_plan_from_events_filters_platform() -> None:
    events = [
        {"event": "series", "platform": "dropout", "name": "Dimension 20"},
        {
            "event": "season",
            "platform": "dropout",
            "slug": "dimension-20",
            "dest_season": 0,
            "folder": "Specials",
        },
        {
            "event": "item",
            "platform": "dropout",
            "id": "dropout|dimension-20|S00E01",
            "dest_season": 0,
        },
        {
            "event": "season",
            "platform": "youtube",
            "slug": "professor-messer",
            "dest_season": 2,
            "folder": "Season 2",
        },
        {
            "event": "item",
            "platform": "youtube",
            "id": "youtube|professor-messer|S02E01",
            "dest_season": 2,
        },
    ]
    youtube = plan_from_events(events, platform="youtube")
    assert [row["slug"] for row in youtube["seasons"]] == ["professor-messer"]
    assert [row["id"] for row in youtube["items"]] == ["youtube|professor-messer|S02E01"]
    dropout = plan_from_events(events, platform="dropout")
    assert [row["slug"] for row in dropout["seasons"]] == ["dimension-20"]
    assert [row["id"] for row in dropout["items"]] == ["dropout|dimension-20|S00E01"]
