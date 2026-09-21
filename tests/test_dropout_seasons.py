from yt_dlp_emby.dropout_seasons import (
    discover_dropout_seasons,
    normalize_dropout_catalog_url,
    season_numbers_from_html,
)


def test_normalize_season_url() -> None:
    base, lone = normalize_dropout_catalog_url("https://watch.dropout.tv/show/season:3")
    assert lone == 3
    assert base.endswith("/show")


def test_season_numbers_from_html() -> None:
    html = '<a href="/dimension-20/season:1">S1</a><a href="/dimension-20/season:2">'
    assert season_numbers_from_html(html, "https://watch.dropout.tv/dimension-20") == [
        1,
        2,
    ]


def test_discover_single_season_url() -> None:
    seasons = discover_dropout_seasons(
        "https://watch.dropout.tv/foo/season:2",
        fetch_html=lambda _url: "",
    )
    assert len(seasons) == 1
    assert seasons[0]["dropout"] == 2
