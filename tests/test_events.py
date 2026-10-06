"""Operation-local callbacks and explicit selections replace JSONL sidecars."""

import asyncio

import pytest

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.events import (
    OperationContext,
    allowed_item_id,
    allowed_provider_action,
    capture_events,
    current_item_id,
    emit,
    emit_progress,
    set_current_item_id,
    use_operation_context,
    validate_selected_action,
)


def test_nested_context_restores_selection_and_item_identity() -> None:
    with use_operation_context(OperationContext(selected_ids={"outer"})):
        set_current_item_id("outer")
        assert allowed_item_id("outer")
        assert not allowed_item_id("inner")
        with use_operation_context(OperationContext(selected_ids=set())):
            set_current_item_id("inner")
            assert not allowed_item_id("outer")
            assert not allowed_item_id("inner")
        assert current_item_id() == "outer"
    assert current_item_id() is None


def test_callbacks_ignore_retired_environment_sidecars(tmp_path, monkeypatch) -> None:
    target = tmp_path / "events.jsonl"
    monkeypatch.setenv("YT_DLP_EMBY_EVENTS", str(target))
    with capture_events() as rows:
        emit({"event": "progress", "completed": 1})
    assert rows == [{"event": "progress", "completed": 1}]
    emit({"event": "ignored"})
    assert not target.exists()


def test_provider_selection_distinguishes_same_slot_action_and_source() -> None:
    key = ("youtube", "show", "video-a", "remove")
    with use_operation_context(OperationContext(selected_actions={key})):
        assert allowed_provider_action(*key, "same-slot")
        assert not allowed_provider_action("youtube", "show", "video-a", "download", "same-slot")
        assert not allowed_provider_action("youtube", "show", "video-b", "remove", "same-slot")


def test_changed_destination_is_rejected_before_media_execution() -> None:
    key = ("dropout", "show", "source:28:4", "download")
    expected = {
        "dest_season": 27,
        "dest_episode": 9,
        "title": "Custom",
        "url": "https://watch.dropout.tv/videos/four",
    }
    with use_operation_context(
        OperationContext(selected_actions={key}, selected_action_specs={key: expected})
    ):
        assert validate_selected_action(*key, expected)
        with pytest.raises(ConfigError, match="PLAN_STALE"):
            validate_selected_action(*key, {**expected, "dest_episode": 10})
        assert not validate_selected_action("dropout", "show", "other", "download", expected)


def test_progress_throttling_does_not_leak_across_operations(monkeypatch) -> None:
    monkeypatch.setattr("yt_dlp_emby.events.time.monotonic", lambda: 100.0)
    for _ in range(2):
        with capture_events() as rows:
            emit_progress({"event": "progress", "completed": 1})
            emit_progress({"event": "progress", "completed": 2})
            emit_progress({"event": "progress", "completed": 3}, force=True)
        assert [row["completed"] for row in rows] == [1, 3]


async def test_concurrent_contexts_do_not_mix_callbacks_or_item_ids() -> None:
    async def collect(ident: str):
        with capture_events() as rows:
            set_current_item_id(ident)
            await asyncio.sleep(0)
            emit({"event": "progress", "id": current_item_id()})
            return rows

    first, second = await asyncio.gather(collect("first"), collect("second"))
    assert first == [{"event": "progress", "id": "first"}]
    assert second == [{"event": "progress", "id": "second"}]
