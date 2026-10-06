from __future__ import annotations

from yt_dlp_emby.server.series import refresh_series_batch


def test_refresh_batch_runs_sequentially_reports_progress_and_continues(
    monkeypatch, tmp_path
) -> None:
    called: list[str] = []
    progress: list[dict[str, object]] = []

    def refresh(_data_dir, _platform, slug, **_kwargs):
        called.append(slug)
        if slug == "broken":
            raise RuntimeError("temporarily unavailable")
        return None

    monkeypatch.setattr("yt_dlp_emby.server.series.refresh_series_metadata", refresh)

    result = refresh_series_batch(
        tmp_path,
        [
            {"platform": "dropout", "slug": "broken"},
            {"platform": "youtube", "slug": "healthy"},
        ],
        environ={},
        on_progress=progress.append,
    )

    assert called == ["broken", "healthy"]
    assert [row["error"] for row in result["results"]] == [
        "temporarily unavailable",
        None,
    ]
    assert [entry["completed"] for entry in progress] == [0, 1, 1, 2]
    assert progress[0]["current"] == {"platform": "dropout", "slug": "broken"}
    assert progress[-1]["last"] == {
        "platform": "youtube",
        "slug": "healthy",
        "error": None,
    }
