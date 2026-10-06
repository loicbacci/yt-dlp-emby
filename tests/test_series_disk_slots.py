from yt_dlp_emby.server.series import series_disk_slot_status


def test_series_disk_slot_status_checks_only_requested_slots(tmp_path) -> None:
    library = tmp_path / "library"
    season = library / "Show" / "Season 1"
    season.mkdir(parents=True)
    (season / "Show - S01E03 - Existing.mkv").touch()
    (tmp_path / "dropout.yaml").write_text(
        f"library: {library}\n"
        "series:\n"
        "  - name: Show\n"
        "    path: Show\n"
        "    url: https://watch.dropout.tv/show\n"
        "    seasons:\n"
        "      - dropout: 1\n"
        "        to_season: 1\n"
        "        url: https://watch.dropout.tv/show/season-1\n",
        encoding="utf-8",
    )

    result = series_disk_slot_status(
        tmp_path,
        "dropout",
        "show",
        [{"season": 1, "episode": 3}, {"season": 1, "episode": 4}],
        environ={},
    )

    assert result == {
        "slots": [
            {"season": 1, "episode": 3, "on_disk": True},
            {"season": 1, "episode": 4, "on_disk": False},
        ]
    }
