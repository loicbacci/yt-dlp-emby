from pathlib import Path

from yt_dlp_emby.server.refresh_stamp import (
    PARTS,
    load_refresh_stamps,
    series_refresh_key,
    series_refresh_payload,
    stamp_series_refresh,
)


def test_stamp_listings_disk_sonarr_independently(tmp_path: Path) -> None:
    first = stamp_series_refresh(
        tmp_path, "dropout", "show", "listings", when="2026-01-01T00:00:00+00:00"
    )
    assert first == {"listings": "2026-01-01T00:00:00+00:00", "disk": None, "sonarr": None}
    second = stamp_series_refresh(
        tmp_path,
        "dropout",
        "show",
        "disk",
        "sonarr",
        when="2026-01-02T00:00:00+00:00",
    )
    assert second["listings"] == "2026-01-01T00:00:00+00:00"
    assert second["disk"] == "2026-01-02T00:00:00+00:00"
    assert second["sonarr"] == "2026-01-02T00:00:00+00:00"
    assert tuple(second) == PARTS


def test_unknown_parts_are_ignored(tmp_path: Path) -> None:
    stamp_series_refresh(tmp_path, "youtube", "chan", "nope", when="t")
    payload = series_refresh_payload(tmp_path, "youtube", "chan")
    assert payload == {"listings": None, "disk": None, "sonarr": None}


def test_missing_series_payload_is_empty_parts(tmp_path: Path) -> None:
    assert series_refresh_payload(tmp_path, "dropout", "missing") == {
        "listings": None,
        "disk": None,
        "sonarr": None,
    }


def test_load_refresh_stamps_recovers_from_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "refresh.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_refresh_stamps(tmp_path) == {"series": {}}


def test_series_refresh_key() -> None:
    assert series_refresh_key("dropout", "game-changer") == "dropout|game-changer"
